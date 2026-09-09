import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.domain.cloudatlas_sources import (
    CloudAtlasBoundaryError,
    OctobusCloudAtlasClient,
)
from app.domain.models import (
    AuditEvent,
    Finding,
    GovernanceReport,
    GovernanceRun,
    ManualReview,
)
from app.governance_runner import main as run_governance_runner
from tests.api.routes.test_ai_governance_draft_requests import (
    _operator_draft_request_context,
)
from tests.api.routes.test_governance_report_reads import _prepare_rerun
from tests.api.routes.test_governance_run_netflow import _prepare_present_run
from tests.api.routes.test_governance_runs import (
    XLSX_MEDIA_TYPE,
    _create_member,
    _create_project,
    _trigger_stage5_run,
    _workbook_bytes,
)


def prepare_manual_review_context(
    *,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> tuple[str, dict[str, str], dict[str, str]]:
    project, report, headers, finding_id, _url = _operator_draft_request_context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        qualify_model=False,
    )
    with Session(engine) as session:
        finding = session.get(Finding, uuid.UUID(finding_id))
        assert finding is not None
        scope = {
            "resource_id": str(finding.resource_id),
            "run_id": str(report.governance_run_id),
            "finding_id": finding_id,
        }
    return f"/api/v1/projects/{project['id']}/manual-reviews", headers, scope


@pytest.fixture
def review_context(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> tuple[str, dict[str, str], dict[str, str]]:
    return prepare_manual_review_context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )


def publish_review_run(
    *,
    client: TestClient,
    headers: dict[str, str],
    monkeypatch: MonkeyPatch,
    project_id: str,
    run_id: str,
    cloud_ips: tuple[str, ...],
    fail: bool = False,
) -> GovernanceRun:
    """Real runner/Publish with synthetic upstream data; manual APIs stay unmocked."""

    def page(
        _client: object,
        _source: object,
        *,
        capset_token: str,
        page: int,
        size: int,
    ) -> dict[str, Any]:
        del capset_token
        if fail:
            raise CloudAtlasBoundaryError("cloudatlas_upstream_failed")
        return {
            "items": [
                {"id": f"review-{index}", "ip": ip, "status": "valid"}
                for index, ip in enumerate(cloud_ips)
            ],
            "page": page,
            "size": size,
            "total": len(cloud_ips),
        }

    monkeypatch.setattr(OctobusCloudAtlasClient, "list_ip_assets_page", page)
    trigger = f"manual-review-{uuid.uuid4()}"
    environment = _prepare_rerun(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=project_id,
        run_id=run_id,
        trigger_id=trigger,
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    assert run_governance_runner() == (1 if fail else 0)
    with Session(engine) as session:
        run = session.exec(
            select(GovernanceRun).where(
                GovernanceRun.project_id == uuid.UUID(project_id),
                GovernanceRun.trigger_id == trigger,
            )
        ).one()
        session.expunge(run)
    return run


def _save(
    client: TestClient,
    url: str,
    headers: dict[str, str],
    scope: dict[str, str],
    **extra: Any,
) -> dict[str, Any]:
    response = client.post(
        url,
        headers=headers,
        json={
            **scope,
            "conclusion": "Owner checked source inventories.",
            "pending_verification": "Confirm both sources observe the same IP.",
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _list(
    client: TestClient,
    url: str,
    headers: dict[str, str],
    scope: dict[str, str],
    **params: Any,
) -> dict[str, Any]:
    response = client.get(url, headers=headers, params={**scope, **params})
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_save_without_model_is_immutable_not_a_finding_update_and_authorized(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    review_context: tuple[str, dict[str, str], dict[str, str]],
    monkeypatch: MonkeyPatch,
) -> None:
    url, headers, scope = review_context
    monkeypatch.setattr(settings, "MODEL_API_ENDPOINT", None)
    monkeypatch.setattr(settings, "MODEL_API_KEY", None)
    with Session(engine) as session:
        finding = session.get(Finding, uuid.UUID(scope["finding_id"]))
        run = session.get(GovernanceRun, uuid.UUID(scope["run_id"]))
        report = session.exec(
            select(GovernanceReport).where(
                GovernanceReport.governance_run_id == uuid.UUID(scope["run_id"])
            )
        ).one()
        assert finding is not None and run is not None
        before = (finding.model_dump(), run.model_dump(), report.model_dump())
    record = _save(client, url, headers, scope)
    assert record["status"] == "PENDING" and record["verifications"] == []
    assert record["author_name"] and record["author_id"] and record["created_at"]
    with Session(engine) as session:
        finding = session.get(Finding, uuid.UUID(scope["finding_id"]))
        run = session.get(GovernanceRun, uuid.UUID(scope["run_id"]))
        report = session.exec(
            select(GovernanceReport).where(
                GovernanceReport.governance_run_id == uuid.UUID(scope["run_id"])
            )
        ).one()
        assert finding is not None and run is not None
        assert (finding.model_dump(), run.model_dump(), report.model_dump()) == before
        event = session.exec(
            select(AuditEvent).where(
                AuditEvent.target_id == uuid.UUID(record["id"]),
                AuditEvent.action == "manual_review.created",
            )
        ).one()
        assert event.actor_subject == record["author_id"]
        for statement in (
            "UPDATE manual_reviews SET conclusion = 'rewritten' WHERE id = :id",
            "DELETE FROM manual_reviews WHERE id = :id",
        ):
            with pytest.raises(DBAPIError):
                session.connection().execute(text(statement), {"id": record["id"]})
            session.rollback()
    project_id = url.split("/")[4]
    viewer = _create_member(
        client, superuser_token_headers, project_id=project_id, roles=["viewer"]
    )
    approver = _create_member(
        client, superuser_token_headers, project_id=project_id, roles=["approver"]
    )
    assert _list(client, url, superuser_token_headers, scope)["can_create"] is True
    for readonly in (viewer, approver):
        assert _list(client, url, readonly, scope)["can_create"] is False
        assert (
            client.post(
                url,
                headers=readonly,
                json={
                    **scope,
                    "conclusion": "Changed",
                    "pending_verification": "Recheck",
                },
            ).status_code
            == 404
        )
    assert _list(client, url, viewer, scope)["data"] == [record]
    other = _create_project(client, superuser_token_headers)
    assert (
        client.get(
            f"/api/v1/projects/{other['id']}/manual-reviews",
            headers=superuser_token_headers,
            params=scope,
        ).status_code
        == 404
    )
    assert (
        client.get(
            url, headers=viewer, params={**scope, "resource_id": str(uuid.uuid4())}
        ).status_code
        == 404
    )
    assert (
        client.post(
            url,
            headers=headers,
            json={
                **scope,
                "conclusion": "duplicate",
                "pending_verification": "duplicate",
            },
        ).status_code
        == 409
    )
    assert _list(client, url, headers, scope)["count"] == 1
    assert _list(client, url, headers, scope, skip=1)["data"] == []
    for change in (
        {"conclusion": " "},
        {"pending_verification": "x" * 4001},
        {"author_id": str(uuid.uuid4())},
    ):
        assert (
            client.post(
                url,
                headers=headers,
                json={
                    **scope,
                    "conclusion": "valid",
                    "pending_verification": "valid",
                    **change,
                },
            ).status_code
            == 422
        )
    asset_scope = {key: value for key, value in scope.items() if key != "finding_id"}
    admin_record = _save(client, url, superuser_token_headers, asset_scope)
    assert _list(client, url, viewer, asset_scope)["data"] == [admin_record]


def test_matching_persistent_failure_and_correction_history(
    client: TestClient,
    review_context: tuple[str, dict[str, str], dict[str, str]],
    monkeypatch: MonkeyPatch,
) -> None:
    url, headers, scope = review_context
    original = _save(client, url, headers, scope)
    persistent = publish_review_run(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=url.split("/")[4],
        run_id=scope["run_id"],
        cloud_ips=("192.0.2.20",),
    )
    record = _list(client, url, headers, scope)["data"][0]
    assert record["status"] == "UNRESOLVED"
    assert record["verifications"][0]["run_id"] == str(persistent.id)
    matched = publish_review_run(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=url.split("/")[4],
        run_id=str(persistent.id),
        cloud_ips=("192.0.2.10",),
    )
    resolved = _list(client, url, headers, scope)["data"][0]
    assert resolved["status"] == "RESOLVED"
    assert resolved["verifications"][0]["reason"] == "both_sources_observed"
    failed = publish_review_run(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=url.split("/")[4],
        run_id=str(matched.id),
        cloud_ips=(),
        fail=True,
    )
    preserved = _list(client, url, headers, scope)["data"][0]
    assert preserved["status"] == "RESOLVED"
    assert preserved["verifications"][0]["run_id"] == str(failed.id)
    assert preserved["verifications"][0]["status"] == "NO_NEW_CONCLUSION"
    assert preserved["verifications"][1:] == resolved["verifications"]
    correction = _save(
        client,
        url,
        headers,
        scope,
        supersedes_id=original["id"],
        conclusion="Corrected explanation, not new evidence.",
    )
    assert correction["status"] == "PENDING" and correction["version"] == 2
    history = _list(client, url, headers, scope)
    assert history["data"][0] == correction
    assert history["data"][1] == {**preserved, "is_current": False}
    assert _list(client, url, headers, scope, skip=1, limit=1)["data"] == [
        {**preserved, "is_current": False}
    ]
    assert (
        client.post(
            url,
            headers=headers,
            json={
                **scope,
                "supersedes_id": original["id"],
                "conclusion": "stale",
                "pending_verification": "recheck",
            },
        ).status_code
        == 409
    )
    later = publish_review_run(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=url.split("/")[4],
        run_id=str(failed.id),
        cloud_ips=("192.0.2.10",),
    )
    history = _list(client, url, headers, scope)
    assert history["data"][0]["status"] == "RESOLVED"
    assert [item["run_id"] for item in history["data"][0]["verifications"]] == [
        str(later.id)
    ]
    assert history["data"][1] == {**preserved, "is_current": False}


def test_asset_only_missing_resource_is_insufficient_not_closed(
    client: TestClient,
    review_context: tuple[str, dict[str, str], dict[str, str]],
    monkeypatch: MonkeyPatch,
) -> None:
    url, headers, scope = review_context
    with Session(engine) as session:
        finding = session.exec(
            select(Finding).where(
                Finding.project_id == uuid.UUID(url.split("/")[4]),
                Finding.finding_type == "UNREPORTED_ASSET",
            )
        ).one()
        scope = {"resource_id": str(finding.resource_id), "run_id": scope["run_id"]}
    _save(client, url, headers, scope)
    later = publish_review_run(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=url.split("/")[4],
        run_id=scope["run_id"],
        cloud_ips=("192.0.2.10",),
    )
    record = _list(client, url, headers, scope)["data"][0]
    assert record["finding_id"] is None
    assert record["status"] == "INSUFFICIENT_EVIDENCE"
    assert record["verifications"][0]["run_id"] == str(later.id)
    assert record["verifications"][0]["reason"] == "resource_not_observed"
    with Session(engine) as session:
        stored = session.get(Finding, finding.id)
        assert stored is not None and stored.status == "OPEN"


def test_prior_success_cannot_verify_a_later_record_and_bad_receipt_is_unavailable(
    client: TestClient,
    review_context: tuple[str, dict[str, str], dict[str, str]],
    monkeypatch: MonkeyPatch,
) -> None:
    url, headers, scope = review_context
    prior = publish_review_run(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=url.split("/")[4],
        run_id=scope["run_id"],
        cloud_ips=("192.0.2.10",),
    )
    _save(client, url, headers, scope)
    assert _list(client, url, headers, scope)["data"][0]["verifications"] == []
    later = publish_review_run(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=url.split("/")[4],
        run_id=str(prior.id),
        cloud_ips=("192.0.2.10",),
    )
    with Session(engine) as session:
        session.connection().exec_driver_sql(
            "SET LOCAL session_replication_role = replica"
        )
        session.connection().execute(
            text(
                "UPDATE run_steps SET output_hash = :hash WHERE governance_run_id = :id AND step_code = 'PUBLISH'"
            ),
            {"id": later.id, "hash": "0" * 64},
        )
        session.commit()
    record = _list(client, url, headers, scope)["data"][0]
    assert record["status"] == "INSUFFICIENT_EVIDENCE"
    assert record["verifications"][0]["reason"] == "comparison_evidence_unavailable"


def test_database_rejects_cross_scope_and_duplicate_corrections(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    review_context: tuple[str, dict[str, str], dict[str, str]],
) -> None:
    url, headers, scope = review_context
    record = _save(client, url, headers, scope)
    other = _create_project(client, superuser_token_headers)
    with Session(engine) as session:
        original = session.get(ManualReview, uuid.UUID(record["id"]))
        assert original is not None
        data = original.model_dump()
    for changed in (
        {"project_id": uuid.UUID(str(other["id"]))},
        {"version": 1},
        {"supersedes_id": uuid.UUID(record["id"]), "version": 3},
        {"baseline_classification": "cloudatlas_only"},
    ):
        with Session(engine) as session:
            session.add(ManualReview(**{**data, "id": uuid.uuid4(), **changed}))
            with pytest.raises(DBAPIError):
                session.commit()
            session.rollback()
    assert _list(client, url, headers, scope)["count"] == 1


@pytest.mark.parametrize("activity", ["active", "empty", "zero"])
def test_netflow_never_resolves_two_source_absence(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    activity: str,
) -> None:
    content = b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
    if activity == "active":
        content += b"192.0.2.20,198.51.100.20,6,443,53000\n"
    elif activity == "zero":
        content += b"invalid,192.0.2.20,6,443,53000\n"
    trigger = f"manual-netflow-{uuid.uuid4()}"
    project, _dataset, _environment = _prepare_present_run(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        content=content,
        trigger_id=trigger,
    )
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _client, _source, *, capset_token, page, size: {
            "items": [{"id": "netflow-review", "ip": "192.0.2.20", "status": "valid"}],
            "page": page,
            "size": size,
            "total": 1,
        },
    )
    assert run_governance_runner() == 0
    with Session(engine) as session:
        base = session.exec(
            select(GovernanceRun).where(
                GovernanceRun.trigger_id == trigger,
            )
        ).one()
        finding = session.exec(
            select(Finding).where(
                Finding.project_id == base.project_id,
                Finding.finding_type == "UNREPORTED_ASSET",
            )
        ).one()
        scope = {
            "resource_id": str(finding.resource_id),
            "run_id": str(base.id),
            "finding_id": str(finding.id),
        }
    url = f"/api/v1/projects/{project['id']}/manual-reviews"
    _save(client, url, superuser_token_headers, scope)
    later = publish_review_run(
        client=client,
        headers=superuser_token_headers,
        monkeypatch=monkeypatch,
        project_id=str(project["id"]),
        run_id=scope["run_id"],
        cloud_ips=("192.0.2.10",),
    )
    record = _list(client, url, superuser_token_headers, scope)["data"][0]
    assert record["status"] == "INSUFFICIENT_EVIDENCE"
    assert record["verifications"][0]["run_id"] == str(later.id)
    assert record["verifications"][0]["reason"] == "resource_not_observed"
    with Session(engine) as session:
        stored = session.get(Finding, uuid.UUID(scope["finding_id"]))
        assert stored is not None and stored.status == "OPEN"


def test_run_already_started_when_record_is_saved_cannot_verify_it(
    client: TestClient,
    review_context: tuple[str, dict[str, str], dict[str, str]],
    monkeypatch: MonkeyPatch,
) -> None:
    url, headers, scope = review_context
    created: list[dict[str, Any]] = []

    def page(
        _client: object,
        _source: object,
        *,
        capset_token: str,
        page: int,
        size: int,
    ) -> dict[str, Any]:
        del capset_token
        if not created:
            created.append(_save(client, url, headers, scope))
        return {
            "items": [{"id": "temporal-review", "ip": "192.0.2.10", "status": "valid"}],
            "page": page,
            "size": size,
            "total": 1,
        }

    monkeypatch.setattr(OctobusCloudAtlasClient, "list_ip_assets_page", page)
    environment = _prepare_rerun(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=url.split("/")[4],
        run_id=scope["run_id"],
        trigger_id=f"review-inflight-{uuid.uuid4()}",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    assert run_governance_runner() == 0
    assert _list(client, url, headers, scope)["data"] == created


def test_reversed_difference_does_not_verify_original_difference(
    client: TestClient,
    review_context: tuple[str, dict[str, str], dict[str, str]],
    monkeypatch: MonkeyPatch,
) -> None:
    url, headers, scope = review_context
    _save(client, url, headers, scope)
    project_id = url.split("/")[4]
    publish_review_run(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=project_id,
        run_id=scope["run_id"],
        cloud_ips=("192.0.2.10",),
    )
    uploads_url = f"/api/v1/projects/{project_id}/customer-uploads"
    upload = client.post(
        uploads_url,
        headers=headers,
        files={
            "file": ("customer.xlsx", _workbook_bytes("192.0.2.20"), XLSX_MEDIA_TYPE)
        },
    )
    assert upload.status_code == 201, upload.text
    assert (
        client.post(
            f"{uploads_url}/{upload.json()['id']}/select",
            headers=headers,
        ).status_code
        == 200
    )
    _trigger_stage5_run(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project={"id": project_id},
        trigger_id=f"review-reversed-{uuid.uuid4()}",
    )
    assert run_governance_runner() == 0
    record = _list(client, url, headers, scope)["data"][0]
    assert record["status"] == "INSUFFICIENT_EVIDENCE"
    assert record["verifications"][0]["reason"] == "difference_direction_changed"
    assert record["verifications"][1]["status"] == "RESOLVED"


@pytest.mark.parametrize("failure_path", ["session_terminal", "retry_start"])
def test_corrected_history_retains_control_plane_failures(
    client: TestClient,
    review_context: tuple[str, dict[str, str], dict[str, str]],
    monkeypatch: MonkeyPatch,
    failure_path: str,
) -> None:
    from app.domain.governance_runs import converge_terminal_run, fail_retry_start
    from app.domain.models import Project

    url, headers, scope = review_context
    original = _save(client, url, headers, scope)
    project_id = uuid.UUID(url.split("/")[4])
    trigger_id = f"review-terminated-{uuid.uuid4()}"
    environment = _prepare_rerun(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=project_id,
        run_id=scope["run_id"],
        trigger_id=trigger_id,
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    def terminate(*_args: Any, **_kwargs: Any) -> None:
        raise SystemExit("synthetic runner termination")

    monkeypatch.setattr(OctobusCloudAtlasClient, "list_ip_assets_page", terminate)
    with pytest.raises(SystemExit):
        run_governance_runner()
    with Session(engine) as session:
        session.exec(
            select(Project).where(Project.id == project_id).with_for_update()
        ).one()
        run = session.exec(
            select(GovernanceRun).where(GovernanceRun.trigger_id == trigger_id)
        ).one()
        assert run.status == "RUNNING"
        transition = (
            converge_terminal_run
            if failure_path == "session_terminal"
            else fail_retry_start
        )
        transition(
            session=session,
            run=run,
            actor_subject=original["author_id"],
            request_ip=None,
        )
        session.commit()
        failed_id = str(run.id)
    prior = _list(client, url, headers, scope)["data"][0]
    assert prior["verifications"][0]["run_id"] == failed_id
    assert prior["verifications"][0]["run_status"] == "FAILED_PROCESSING"
    assert prior["verifications"][0]["status"] == "NO_NEW_CONCLUSION"
    _save(client, url, headers, scope, supersedes_id=original["id"])
    assert _list(client, url, headers, scope)["data"][1] == {
        **prior,
        "is_current": False,
    }
