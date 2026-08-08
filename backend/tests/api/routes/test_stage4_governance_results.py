import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlmodel import Session, func, select

from app.core.config import settings
from app.core.db import engine
from app.domain.cloudatlas_sources import OctobusCloudAtlasClient
from app.domain.models import (
    Artifact,
    AuditEvent,
    Finding,
    FindingOccurrence,
    FindingOccurrenceObservation,
    FindingOccurrenceSnapshot,
    FindingTransition,
    FindingTransitionObservation,
    FindingTransitionSnapshot,
    GovernanceRun,
    Observation,
    ObservationResourceLink,
    Project,
    Resource,
    RunStep,
    SourceSnapshot,
)
from app.governance_runner import main as run_governance_runner
from app.integrations.agent_compose import (
    AgentComposeClient,
    AgentComposeRunStart,
    AgentComposeSession,
    AgentComposeSessionObservation,
)
from tests.api.routes.test_governance_runs import (
    _create_member,
    _create_project,
    _mock_cloudatlas,
    _prepare_ready_project,
    _runner_environment,
    _workbook_bytes,
)
from tests.utils.audit import (
    reject_project_latest_run_updates,
    reject_publish_audit_inserts,
)


def test_stage4_run_publishes_ip_results_and_is_reentrant(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _client, _source, *, capset_token, page, size: {
            "items": [
                {
                    "id": "fixture-cloud-only",
                    "ip": "203.0.113.5",
                    "status": "valid",
                }
            ],
            "page": page,
            "size": size,
            "total": 1,
        },
    )

    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="stage4-happy-path",
        session_seed="stage4-session",
    )
    environment["GOVERNANCE_PROCESSING_CONTRACT_VERSION"] = "ip-v1"
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert run_governance_runner() == 0
    assert run_governance_runner() == 0

    run_payload = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()
    run = run_payload["data"][0]
    assert run["processing_contract_version"] == "ip-v1"
    assert [step["step_code"] for step in run["steps"]] == [
        "LOAD_CUSTOMER",
        "PULL_CLOUDATLAS",
        "NORMALIZE",
        "RESOLVE",
        "CHECK_FINDINGS",
        "PUBLISH",
    ]
    assert all(step["status"] == "SUCCEEDED" for step in run["steps"])
    assert all(len(step["output_hash"] or "") == 64 for step in run["steps"])

    assets = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets",
        headers=superuser_token_headers,
    )
    assert assets.status_code == 200, assets.text
    assert assets.json()["compatible"] is True
    assert assets.json()["count"] == 2
    assert client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/assets",
        headers=superuser_token_headers,
    ).status_code == 404
    assert {
        (
            asset["canonical_ip"],
            asset["customer_observed"],
            asset["cloudatlas_observed"],
        )
        for asset in assets.json()["data"]
    } == {
        ("192.0.2.10", True, False),
        ("203.0.113.5", False, True),
    }
    asset_id = assets.json()["data"][0]["id"]
    asset_detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets/{asset_id}",
        headers=superuser_token_headers,
    )
    assert asset_detail.status_code == 200, asset_detail.text
    assert len(asset_detail.json()["observations"]) == 1

    findings = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/findings",
        headers=superuser_token_headers,
    )
    assert findings.status_code == 200, findings.text
    assert findings.json()["count"] == 2
    assert {item["finding_type"] for item in findings.json()["data"]} == {
        "UNREPORTED_ASSET",
        "UNOBSERVED_ASSET",
    }

    finding_id = findings.json()["data"][0]["id"]
    detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/findings/{finding_id}",
        headers=superuser_token_headers,
    )
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["occurrences"]) == 1
    assert len(detail.json()["transitions"]) == 1
    assert len(detail.json()["occurrences"][0]["source_snapshot_ids"]) == 2
    assert len(detail.json()["occurrences"][0]["source_snapshots"]) == 2
    assert len(detail.json()["transitions"][0]["source_snapshot_ids"]) == 2
    assert len(detail.json()["transitions"][0]["source_snapshots"]) == 2

    with Session(engine) as session:
        run_id = uuid.UUID(str(run["id"]))
        project_id = uuid.UUID(str(project["id"]))
        assert (
            session.exec(
                select(func.count())
                .select_from(GovernanceRun)
                .where(GovernanceRun.id == run_id)
            ).one()
            == 1
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(Observation)
                .where(Observation.governance_run_id == run_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(Resource)
                .where(Resource.project_id == project_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(ObservationResourceLink)
                .where(ObservationResourceLink.governance_run_id == run_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(Finding)
                .where(Finding.project_id == project_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(FindingOccurrence)
                .where(FindingOccurrence.governance_run_id == run_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(FindingTransition)
                .where(FindingTransition.governance_run_id == run_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(FindingOccurrenceObservation)
                .where(FindingOccurrenceObservation.governance_run_id == run_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(FindingOccurrenceSnapshot)
                .where(FindingOccurrenceSnapshot.governance_run_id == run_id)
            ).one()
            == 4
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(FindingTransitionObservation)
                .where(FindingTransitionObservation.governance_run_id == run_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(FindingTransitionSnapshot)
                .where(FindingTransitionSnapshot.governance_run_id == run_id)
            ).one()
            == 4
        )
        assert session.exec(
            select(RunStep).where(RunStep.governance_run_id == run_id)
        ).all()
        assert (
            session.exec(
                select(GovernanceRun).where(
                    GovernanceRun.project_id == project_id,
                    GovernanceRun.trigger_id == "stage4-happy-path",
                )
            )
            .one()
            .processing_contract_version
            == "ip-v1"
        )


def test_stage4_publish_pointer_failure_rolls_back_and_retries_once(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _client, _source, *, capset_token, page, size: {
            "items": [
                {
                    "id": "fixture-cloud-only",
                    "ip": "203.0.113.5",
                    "status": "valid",
                }
            ],
            "page": page,
            "size": size,
            "total": 1,
        },
    )
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="stage4-pointer-failure",
        session_seed="stage4-pointer-failure-session",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with reject_project_latest_run_updates(db):
        assert run_governance_runner() == 1

    failed = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    assert failed["status"] == "FAILED_PROCESSING"
    assert [
        (step["step_code"], step["status"], step["attempt"])
        for step in failed["steps"]
    ] == [
        ("LOAD_CUSTOMER", "SUCCEEDED", 1),
        ("PULL_CLOUDATLAS", "SUCCEEDED", 1),
        ("NORMALIZE", "SUCCEEDED", 1),
        ("RESOLVE", "SUCCEEDED", 1),
        ("CHECK_FINDINGS", "SUCCEEDED", 1),
        ("PUBLISH", "FAILED", 1),
    ]
    with Session(engine) as session:
        stored_project = session.get(Project, uuid.UUID(str(project["id"])))
        assert stored_project is not None
        assert stored_project.latest_completed_run_id is None
        assert session.exec(
            select(func.count()).select_from(Finding).where(
                Finding.project_id == stored_project.id
            )
        ).one() == 0
        assert session.exec(
            select(func.count()).select_from(FindingOccurrence).where(
                FindingOccurrence.governance_run_id == uuid.UUID(str(failed["id"]))
            )
        ).one() == 0
        assert session.exec(
            select(func.count()).select_from(FindingTransition).where(
                FindingTransition.governance_run_id == uuid.UUID(str(failed["id"]))
            )
        ).one() == 0
        assert session.exec(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.target_id == uuid.UUID(str(failed["id"])),
                AuditEvent.action == "governance_run.published",
            )
        ).one() == 0

    session_id = environment["SANDBOX_ID"]
    monkeypatch.setattr(
        AgentComposeClient,
        "get_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.TERMINAL,
        ),
    )
    monkeypatch.setattr(
        AgentComposeClient,
        "resume_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.RUNNING,
        ),
    )
    monkeypatch.setattr(
        AgentComposeClient,
        "start_governance_run",
        lambda _client, **kwargs: AgentComposeRunStart(
            run_id="b" * 64,
            started=True,
            status="RUN_STATUS_PENDING",
            session_id=kwargs["session_id"],
        ),
    )
    retry = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{failed['id']}/retry",
        headers=superuser_token_headers,
    )
    assert retry.status_code == 202, retry.text
    assert retry.json()["session_id"] == session_id

    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("PUBLISH Retry must not reread CloudAtlas")
        ),
    )
    assert run_governance_runner() == 0

    completed = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    assert completed["status"] == "COMPLETED"
    assert completed["session_id"] == session_id
    assert {
        step["step_code"]: step["attempt"] for step in completed["steps"]
    } == {
        "LOAD_CUSTOMER": 1,
        "PULL_CLOUDATLAS": 1,
        "NORMALIZE": 1,
        "RESOLVE": 1,
        "CHECK_FINDINGS": 1,
        "PUBLISH": 2,
    }
    with Session(engine) as session:
        stored_project = session.get(Project, uuid.UUID(str(project["id"])))
        assert stored_project is not None
        assert stored_project.latest_completed_run_id == uuid.UUID(
            str(completed["id"])
        )
        assert session.exec(
            select(func.count()).select_from(Finding).where(
                Finding.project_id == stored_project.id
            )
        ).one() == 2
        assert session.exec(
            select(func.count()).select_from(FindingOccurrence).where(
                FindingOccurrence.governance_run_id
                == uuid.UUID(str(completed["id"]))
            )
        ).one() == 2
        assert session.exec(
            select(func.count()).select_from(FindingTransition).where(
                FindingTransition.governance_run_id
                == uuid.UUID(str(completed["id"]))
            )
        ).one() == 2
        assert session.exec(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.target_id == uuid.UUID(str(completed["id"])),
                AuditEvent.action == "governance_run.published",
            )
        ).one() == 1


def test_stage4_finding_lifecycle_state_machine_is_exposed_by_public_api(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)

    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    target_ip = "192.0.2.10"
    project_url = f"{settings.API_V1_STR}/projects/{project['id']}"

    def run(
        *,
        trigger_id: str,
        session_seed: str,
        cloudatlas_items: list[dict[str, str]],
        current_upload: dict[str, object] = upload,
        expected_exit: int = 0,
    ) -> None:
        def list_page(
            _client: object,
            _source: object,
            *,
            capset_token: str,
            page: int,
            size: int,
        ) -> dict[str, object]:
            del capset_token
            return {
                "items": cloudatlas_items,
                "page": page,
                "size": size,
                "total": len(cloudatlas_items),
            }

        monkeypatch.setattr(
            OctobusCloudAtlasClient, "list_ip_assets_page", list_page
        )
        environment = _runner_environment(
            project=project,
            upload=current_upload,
            source=source,
            trigger_id=trigger_id,
            session_seed=session_seed,
        )
        for name, value in environment.items():
            monkeypatch.setenv(name, value)
        assert run_governance_runner() == expected_exit

    def items(*, ip: str, status: str = "valid") -> list[dict[str, str]]:
        return [{"id": f"asset-{ip}", "ip": ip, "status": status}]

    def read_findings(status: str = "OPEN") -> list[dict[str, object]]:
        response = client.get(
            f"{project_url}/findings?status={status}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200, response.text
        return cast(list[dict[str, object]], response.json()["data"])

    def find_finding(status: str, finding_type: str) -> dict[str, object]:
        matches = [
            finding
            for finding in read_findings(status)
            if finding["finding_type"] == finding_type
            and finding["canonical_ip"] == target_ip
        ]
        assert len(matches) == 1
        return matches[0]

    def read_detail(finding_id: object) -> dict[str, object]:
        response = client.get(
            f"{project_url}/findings/{finding_id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200, response.text
        return cast(dict[str, object], response.json())

    # OPENED, then a complete reproduction without another transition.
    run(
        trigger_id="lifecycle-opened",
        session_seed="lifecycle-opened-session",
        cloudatlas_items=[],
    )
    opened = find_finding("OPEN", "UNOBSERVED_ASSET")
    finding_id = opened["id"]
    assert opened["occurrence_count"] == 1
    assert opened["transition_count"] == 1
    run(
        trigger_id="lifecycle-reproduced",
        session_seed="lifecycle-reproduced-session",
        cloudatlas_items=[],
    )
    reproduced = find_finding("OPEN", "UNOBSERVED_ASSET")
    assert reproduced["id"] == finding_id
    assert reproduced["occurrence_count"] == 2
    assert reproduced["transition_count"] == 1

    # A positive match closes the original finding and cites both sides.
    run(
        trigger_id="lifecycle-closed",
        session_seed="lifecycle-closed-session",
        cloudatlas_items=items(ip=target_ip),
    )
    closed = find_finding("CLOSED", "UNOBSERVED_ASSET")
    assert closed["id"] == finding_id
    assert closed["occurrence_count"] == 2
    assert closed["transition_count"] == 2
    closed_detail = read_detail(finding_id)
    closed_transitions = cast(list[dict[str, Any]], closed_detail["transitions"])
    closed_transition = closed_transitions[0]
    assert closed_transition["transition_type"] == "CLOSED"
    assert len(closed_transition["observation_ids"]) == 2
    assert len(closed_transition["source_snapshot_ids"]) == 2
    assert {
        observation["source_type"]
        for observation in closed_transition["observations"]
    } == {"CUSTOMER_UPLOAD", "CLOUDATLAS"}

    # The same difference reopens the same Finding with one new occurrence.
    run(
        trigger_id="lifecycle-reopened",
        session_seed="lifecycle-reopened-session",
        cloudatlas_items=[],
    )
    reopened = find_finding("OPEN", "UNOBSERVED_ASSET")
    assert reopened["id"] == finding_id
    assert reopened["occurrence_count"] == 3
    assert reopened["transition_count"] == 3
    reopened_detail = read_detail(finding_id)
    reopened_transitions = cast(
        list[dict[str, Any]], reopened_detail["transitions"]
    )
    reopened_transition = reopened_transitions[0]
    assert reopened_transition["transition_type"] == "REOPENED"
    assert len(reopened_transition["observation_ids"]) == 1
    assert len(reopened_transition["source_snapshot_ids"]) == 2

    # Flip the direction after selecting a new immutable customer input.  The
    # old Finding remains open while the opposite type gets its own identity.
    upload_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=superuser_token_headers,
        files={
            "file": (
                "customer-flipped.xlsx",
                _workbook_bytes("198.51.100.7"),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert upload_response.status_code == 201, upload_response.text
    flipped_upload = upload_response.json()
    select_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads/{flipped_upload['id']}/select",
        headers=superuser_token_headers,
    )
    assert select_response.status_code == 200, select_response.text
    run(
        trigger_id="lifecycle-direction-flip",
        session_seed="lifecycle-direction-flip-session",
        cloudatlas_items=items(ip=target_ip),
        current_upload=flipped_upload,
    )
    still_open = find_finding("OPEN", "UNOBSERVED_ASSET")
    opposite = find_finding("OPEN", "UNREPORTED_ASSET")
    assert still_open["id"] == finding_id
    assert still_open["occurrence_count"] == 3
    assert still_open["transition_count"] == 3
    assert opposite["id"] != finding_id
    assert opposite["occurrence_count"] == 1
    assert opposite["transition_count"] == 1

    # With neither side observing the old IP, both open Findings are retained
    # without a new occurrence or transition.
    before_missing = {
        finding["id"]: (
            finding["occurrence_count"],
            finding["transition_count"],
        )
        for finding in (still_open, opposite)
    }
    run(
        trigger_id="lifecycle-both-missing",
        session_seed="lifecycle-both-missing-session",
        cloudatlas_items=[],
        current_upload=flipped_upload,
    )
    after_missing = {
        finding["id"]: (
            finding["occurrence_count"],
            finding["transition_count"],
        )
        for finding in read_findings()
        if finding["id"] in before_missing
    }
    assert after_missing == before_missing

    # A failed Run never reaches PUBLISH, so the last complete public result
    # and every Finding lifecycle fact remain unchanged.
    latest_complete = client.get(
        f"{project_url}/governance-runs", headers=superuser_token_headers
    ).json()["data"][0]["id"]
    before_failed = {
        finding["id"]: (
            finding["status"],
            finding["occurrence_count"],
            finding["transition_count"],
        )
        for finding in read_findings()
    }
    run(
        trigger_id="lifecycle-failed",
        session_seed="lifecycle-failed-session",
        cloudatlas_items=items(ip=target_ip, status="stale"),
        current_upload=flipped_upload,
        expected_exit=1,
    )
    after_failed = {
        finding["id"]: (
            finding["status"],
            finding["occurrence_count"],
            finding["transition_count"],
        )
        for finding in read_findings()
    }
    assert after_failed == before_failed
    failed_result = client.get(
        f"{project_url}/findings", headers=superuser_token_headers
    ).json()
    assert failed_result["latest_run_id"] == latest_complete


def test_stage4_read_api_is_safe_until_a_compatible_run_exists(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project = _create_project(client, superuser_token_headers)
    project_url = f"{settings.API_V1_STR}/projects/{project['id']}"

    assets = client.get(
        f"{project_url}/ip-assets",
        headers=superuser_token_headers,
    )
    assert assets.status_code == 200, assets.text
    assert assets.json() == {
        "data": [],
        "count": 0,
        "latest_run_id": None,
        "latest_run_completed_at": None,
        "compatible": False,
        "compatibility_code": "stage4_run_required",
    }

    findings = client.get(
        f"{project_url}/findings?status=OPEN",
        headers=superuser_token_headers,
    )
    assert findings.status_code == 200, findings.text
    assert findings.json() == {
        "data": [],
        "count": 0,
        "status": "OPEN",
        "latest_run_id": None,
        "latest_run_completed_at": None,
        "compatible": False,
        "compatibility_code": "stage4_run_required",
    }

    invalid_status = client.get(
        f"{project_url}/findings?status=NOT_A_STATUS",
        headers=superuser_token_headers,
    )
    assert invalid_status.status_code == 400
    assert invalid_status.json()["detail"]["code"] == "finding_status_invalid"

    missing_asset = client.get(
        f"{project_url}/ip-assets/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )
    missing_finding = client.get(
        f"{project_url}/findings/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )
    assert missing_asset.status_code == 404
    assert missing_finding.status_code == 404


def test_stage4_matching_run_exposes_assets_without_open_findings(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)

    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="stage4-matching-assets",
        session_seed="stage4-matching-assets-session",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert run_governance_runner() == 0

    assets = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets",
        headers=superuser_token_headers,
    )
    assert assets.status_code == 200, assets.text
    asset_payload = assets.json()
    assert asset_payload["compatible"] is True
    assert asset_payload["count"] == 1
    assert asset_payload["data"][0] == {
        "id": asset_payload["data"][0]["id"],
        "resource_id": asset_payload["data"][0]["resource_id"],
        "resource_type": "IP",
        "canonical_key": "192.0.2.10",
        "canonical_ip": "192.0.2.10",
        "customer_observation_count": 1,
        "cloudatlas_observation_count": 1,
        "observation_count": 2,
        "customer_observed": True,
        "cloudatlas_observed": True,
        "open_finding_id": None,
        "open_finding_type": None,
    }

    findings = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/findings",
        headers=superuser_token_headers,
    )
    assert findings.status_code == 200, findings.text
    assert findings.json()["compatible"] is True
    assert findings.json()["count"] == 0
    assert findings.json()["data"] == []


def test_stage4_result_reads_are_paginated_and_trace_is_bounded(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _client, _source, *, capset_token, page, size: {
            "items": [
                {"id": "matching", "ip": "192.0.2.10", "status": "valid"},
                {"id": "cloud-only-1", "ip": "203.0.113.5", "status": "valid"},
                {"id": "cloud-only-2", "ip": "203.0.113.5", "status": "valid"},
            ],
            "page": page,
            "size": size,
            "total": 3,
        },
    )

    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="stage4-bounded-trace",
        session_seed="stage4-bounded-trace-session",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert run_governance_runner() == 0

    page = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets?skip=1&limit=1",
        headers=superuser_token_headers,
    )
    assert page.status_code == 200, page.text
    assert page.json()["count"] == 2
    assert [asset["canonical_ip"] for asset in page.json()["data"]] == [
        "203.0.113.5"
    ]
    resource_id = page.json()["data"][0]["resource_id"]
    asset_detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets/{resource_id}",
        headers=superuser_token_headers,
    )
    assert asset_detail.status_code == 200, asset_detail.text
    assert [
        observation["source_record_key"]
        for observation in asset_detail.json()["observations"]
    ] == ["page:1:item:1", "page:1:item:2"]
    asset_detail_page = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets/{resource_id}"
        "?skip=1&limit=1",
        headers=superuser_token_headers,
    )
    assert asset_detail_page.status_code == 200, asset_detail_page.text
    assert asset_detail_page.json()["observation_count"] == 2
    assert [
        observation["source_record_key"]
        for observation in asset_detail_page.json()["observations"]
    ] == ["page:1:item:2"]

    findings = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/findings",
        headers=superuser_token_headers,
    )
    unreported = next(
        item
        for item in findings.json()["data"]
        if item["finding_type"] == "UNREPORTED_ASSET"
    )
    finding_detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/findings/{unreported['id']}?trace_limit=1",
        headers=superuser_token_headers,
    )
    assert finding_detail.status_code == 200, finding_detail.text
    detail_payload = finding_detail.json()
    assert len(detail_payload["occurrences"]) == 1
    assert len(detail_payload["transitions"]) == 1
    assert len(detail_payload["occurrences"][0]["observation_ids"]) == 1
    assert len(detail_payload["occurrences"][0]["source_snapshot_ids"]) == 1
    assert len(detail_payload["transitions"][0]["observation_ids"]) == 1
    assert len(detail_payload["transitions"][0]["source_snapshot_ids"]) == 1


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {
            "items": [
                {"id": "fixture", "ip": "203.0.113.5", "status": "valid"}
            ],
            "page": 2,
            "size": 200,
            "total": 1,
        },
        {
            "items": [
                {"id": "fixture", "ip": "203.0.113.5", "status": "valid"}
            ],
            "page": 1,
            "size": 200,
            "total": 0,
        },
        {
            "items": [
                {"id": "fixture", "ip": "203.0.113.5", "status": "valid"}
            ],
            "page": 1,
            "total": 1,
        },
    ],
    ids=["page", "total", "envelope"],
)
def test_cloudatlas_pagination_contract_failure_does_not_create_snapshot(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    invalid_payload: dict[str, object],
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda *_args, **_kwargs: invalid_payload,
    )
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="invalid-pagination-contract",
        session_seed=f"invalid-pagination-contract-{uuid.uuid4()}",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert run_governance_runner() == 1
    run = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    assert run["status"] == "FAILED_DATA"
    assert [step["step_code"] for step in run["steps"]] == [
        "LOAD_CUSTOMER",
        "PULL_CLOUDATLAS",
    ]
    assert [snapshot["source_type"] for snapshot in run["snapshots"]] == [
        "CUSTOMER_UPLOAD"
    ]
    cloudatlas_directory = tmp_path / "cloudatlas_snapshots"
    assert not cloudatlas_directory.exists() or not list(cloudatlas_directory.iterdir())



def test_complete_snapshot_record_error_is_non_retryable_without_partial_facts(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda *_args, **_kwargs: {
            "items": [
                {"id": "fixture", "ip": "203.0.113.5", "status": "stale"}
            ],
            "page": 1,
            "size": 200,
            "total": 1,
        },
    )
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="invalid-complete-record",
        session_seed="invalid-complete-record-session",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert run_governance_runner() == 1
    run = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    assert run["status"] == "FAILED_PROCESSING"
    assert run["session_recovery_code"].startswith("non_retryable:")
    assert [
        (step["step_code"], step["status"], step["error_code"])
        for step in run["steps"]
    ] == [
        ("LOAD_CUSTOMER", "SUCCEEDED", None),
        ("PULL_CLOUDATLAS", "SUCCEEDED", None),
        ("NORMALIZE", "FAILED", "normalize_contract_failed"),
    ]
    with Session(engine) as session:
        run_id = uuid.UUID(str(run["id"]))
        project_id = uuid.UUID(str(project["id"]))
        assert session.exec(
            select(func.count()).select_from(Observation).where(
                Observation.governance_run_id == run_id
            )
        ).one() == 0
        assert session.exec(
            select(func.count()).select_from(ObservationResourceLink).where(
                ObservationResourceLink.governance_run_id == run_id
            )
        ).one() == 0
        assert session.exec(
            select(func.count()).select_from(Resource).where(
                Resource.project_id == project_id
            )
        ).one() == 0
        assert session.exec(
            select(func.count()).select_from(Finding).where(
                Finding.project_id == project_id
            )
        ).one() == 0



def test_failed_run_preserves_previous_results_and_all_project_read_roles_can_trace(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda *_args, **_kwargs: {
            "items": [
                {"id": "fixture", "ip": "203.0.113.5", "status": "valid"}
            ],
            "page": 1,
            "size": 200,
            "total": 1,
        },
    )
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    first_environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="published-before-failure",
        session_seed="published-before-failure-session",
    )
    for name, value in first_environment.items():
        monkeypatch.setenv(name, value)
    assert run_governance_runner() == 0
    first_run = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    previous_assets = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets",
        headers=superuser_token_headers,
    ).json()
    previous_findings = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/findings",
        headers=superuser_token_headers,
    ).json()
    finding_id = previous_findings["data"][0]["id"]

    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda *_args, **_kwargs: {
            "items": [
                {"id": "fixture", "ip": "203.0.113.5", "status": "stale"}
            ],
            "page": 1,
            "size": 200,
            "total": 1,
        },
    )
    second_environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="failed-after-publication",
        session_seed="failed-after-publication-session",
    )
    for name, value in second_environment.items():
        monkeypatch.setenv(name, value)
    assert run_governance_runner() == 1

    assets = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets",
        headers=superuser_token_headers,
    ).json()
    findings = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/findings",
        headers=superuser_token_headers,
    ).json()
    assert assets == previous_assets
    assert findings == previous_findings
    assert assets["latest_run_id"] == first_run["id"]
    assert findings["latest_run_id"] == first_run["id"]

    for role in ("viewer", "operator", "approver"):
        role_headers = _create_member(
            client,
            superuser_token_headers,
            project_id=project["id"],
            roles=[role],
        )
        role_assets = client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets",
            headers=role_headers,
        )
        role_findings = client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}/findings",
            headers=role_headers,
        )
        role_detail = client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}/findings/{finding_id}",
            headers=role_headers,
        )
        assert role_assets.status_code == 200
        assert role_findings.status_code == 200
        assert role_detail.status_code == 200


def test_publish_snapshot_integrity_failure_is_not_retryable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="publish-integrity-failure",
        session_seed="publish-integrity-failure-session",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with reject_publish_audit_inserts(db):
        assert run_governance_runner() == 1

    failed = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    with Session(engine) as session:
        cloudatlas_snapshot = session.exec(
            select(SourceSnapshot).where(
                SourceSnapshot.governance_run_id == uuid.UUID(str(failed["id"])),
                SourceSnapshot.source_type == "CLOUDATLAS",
            )
        ).one()
        artifact = session.get(Artifact, cloudatlas_snapshot.artifact_id)
        assert artifact is not None
        artifact_path = tmp_path / artifact.storage_key
        artifact_path.chmod(0o640)
        artifact_path.write_bytes(artifact_path.read_bytes() + b"tampered")

    monkeypatch.setattr(
        "app.api.routes.governance_runs.AgentComposeClient.get_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.TERMINAL,
        ),
    )
    monkeypatch.setattr(
        "app.api.routes.governance_runs.AgentComposeClient.resume_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.RUNNING,
        ),
    )
    monkeypatch.setattr(
        "app.api.routes.governance_runs.AgentComposeClient.start_governance_run",
        lambda _client, **kwargs: AgentComposeRunStart(
            run_id="a" * 64,
            started=True,
            status="RUN_STATUS_PENDING",
            session_id=kwargs["session_id"],
        ),
    )
    retry = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{failed['id']}/retry",
        headers=superuser_token_headers,
    )
    assert retry.status_code == 202, retry.text

    assert run_governance_runner() == 1
    recovered = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    assert recovered["status"] == "FAILED_PROCESSING"
    assert recovered["session_recovery_code"] == "non_retryable:publish_failed"
    assert [
        (step["step_code"], step["status"], step["error_code"])
        for step in recovered["steps"]
        if step["step_code"] == "PUBLISH"
    ] == [("PUBLISH", "FAILED", "publish_failed")]


@pytest.mark.parametrize(
    ("failed_stage", "error_code"),
    [
        ("RESOLVE", "resolve_unexpected_failure"),
        ("CHECK_FINDINGS", "check_findings_unexpected_failure"),
    ],
)
def test_unexpected_stage4_processing_failure_is_recorded_atomically(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    failed_stage: str,
    error_code: str,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id=f"{failed_stage.lower()}-unexpected-failure",
        session_seed=f"{failed_stage.lower()}-unexpected-failure-session",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    if failed_stage == "RESOLVE":

        def fail_sort(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("unexpected resolution failure")

        monkeypatch.setattr(
            "app.domain.governance_runs.ip_observation_sort_key", fail_sort
        )
    else:

        def fail_check(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("unexpected finding check failure")

        monkeypatch.setattr(
            "app.domain.governance_runs._stage4_check_payload", fail_check
        )

    assert run_governance_runner() == 1
    run = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    assert run["status"] == "FAILED_PROCESSING"
    assert run["session_recovery_code"] is None
    expected_steps: list[tuple[str, str, str | None]] = [
        ("LOAD_CUSTOMER", "SUCCEEDED", None),
        ("PULL_CLOUDATLAS", "SUCCEEDED", None),
        ("NORMALIZE", "SUCCEEDED", None),
    ]
    if failed_stage == "CHECK_FINDINGS":
        expected_steps.append(("RESOLVE", "SUCCEEDED", None))
    expected_steps.append((failed_stage, "FAILED", error_code))
    assert [
        (step["step_code"], step["status"], step["error_code"])
        for step in run["steps"]
    ] == expected_steps

    with Session(engine) as session:
        run_id = uuid.UUID(str(run["id"]))
        project_id = uuid.UUID(str(project["id"]))
        assert session.exec(
            select(func.count()).select_from(Observation).where(
                Observation.governance_run_id == run_id
            )
        ).one() == 2
        assert session.exec(
            select(func.count()).select_from(ObservationResourceLink).where(
                ObservationResourceLink.governance_run_id == run_id
            )
        ).one() == (0 if failed_stage == "RESOLVE" else 2)
        assert session.exec(
            select(func.count()).select_from(Resource).where(
                Resource.project_id == project_id
            )
        ).one() == (0 if failed_stage == "RESOLVE" else 1)
        assert session.exec(
            select(func.count()).select_from(Finding).where(
                Finding.project_id == project_id
            )
        ).one() == 0
