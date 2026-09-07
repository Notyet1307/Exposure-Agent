import io
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook  # type: ignore[import-untyped]
from psycopg.errors import UniqueViolation
from pydantic import ValidationError
from pytest import MonkeyPatch
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, delete, select, update

from app.api.deps import get_db
from app.api.routes.ip_results import _finding_read_session
from app.core.config import settings
from app.core.db import engine
from app.domain import ip_results
from app.domain.cloudatlas_sources import OctobusCloudAtlasClient
from app.domain.ip_source_comparison import read_published_netflow_activities
from app.domain.models import (
    AuditEvent,
    Finding,
    FindingDetailPublic,
    FindingNetFlowContextPublic,
    GovernanceRun,
    NetFlowIPActivity,
    Project,
    Resource,
    RunStep,
    SourceSnapshot,
)
from app.domain.netflow_activity import (
    NetFlowIPActivityAggregate,
    netflow_activity_content_hash,
    netflow_activity_output_hash,
)
from app.governance_runner import main as run_runner
from app.main import app
from tests.api.routes import test_governance_runs as run_fixtures
from tests.api.routes.test_governance_report_reads import (
    _configure_runner,
    _prepare_rerun,
    _start_rerun,
)
from tests.api.routes.test_governance_run_netflow import _prepare_present_run
from tests.api.routes.test_ip_source_comparison import _hash
from tests.api.routes.test_netflow_datasets import _upload


def test_finding_detail_returns_published_positive_netflow_context(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
) -> None:
    project, _, _ = _prepare_present_run(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        content=(
            b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
            b"192.0.2.10,198.51.100.20,6,53000,443\n"
        ),
        trigger_id="finding-netflow-positive",
    )
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _client, _source, *, capset_token, page, size: {
            "items": [],
            "page": page,
            "size": size,
            "total": 0,
        },
    )
    assert run_runner() == 0
    project_id = uuid.UUID(str(project["id"]))
    finding = db.exec(select(Finding).where(Finding.project_id == project_id)).one()
    activity = db.exec(
        select(NetFlowIPActivity).where(
            NetFlowIPActivity.project_id == project_id,
            NetFlowIPActivity.resource_id == finding.resource_id,
        )
    ).one()
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_id}/findings/{finding.id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["netflow_context"] == {
        "governance_run_id": str(activity.governance_run_id),
        "status": "POSITIVE_ACTIVITY",
        "activity": {
            "activity_id": str(activity.id),
            "source_snapshot_id": str(activity.source_snapshot_id),
            "aggregation_contract_version": "netflow-ip-activity-v1",
            "content_sha256": activity.content_sha256,
            "flow_count": 1,
            "first_seen_utc": None,
            "last_seen_utc": None,
        },
    }


def _cloud_ips(monkeypatch: MonkeyPatch, ips: list[str]) -> None:
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _client, _source, *, capset_token, page, size: {
            "items": [
                {"id": f"asset-{index}", "ip": ip, "status": "valid"}
                for index, ip in enumerate(ips)
            ],
            "page": page,
            "size": size,
            "total": len(ips),
        },
    )


def _detail(
    client: TestClient,
    headers: dict[str, str],
    project_id: object,
    finding_id: object,
    **params: int,
) -> dict[str, Any]:
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project_id}/findings/{finding_id}",
        headers=headers,
        params=params,
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


@pytest.fixture
def finding_run(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
    request: pytest.FixtureRequest,
) -> tuple[dict[str, object], Finding]:
    mode = getattr(request, "param", "active")
    project, _, _ = _prepare_present_run(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        content=(
            b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
            + (b"" if mode == "empty" else b"192.0.2.10,198.51.100.20,6,53000,443\n")
        ),
        trigger_id=f"finding-context-{uuid.uuid4()}",
    )
    _cloud_ips(monkeypatch, [])
    assert run_runner() == 0
    finding = db.exec(
        select(Finding).where(Finding.project_id == uuid.UUID(str(project["id"])))
    ).one()
    return project, finding


def test_activity_follows_lifecycle_eligibility_not_history_page(
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project, finding = finding_run
    headers = superuser_token_headers
    first = _detail(client, headers, project["id"], finding.id)
    identity = first["id"]

    def rerun(ips: list[str]) -> dict[str, Any]:
        previous = _detail(client, headers, project["id"], finding.id)
        _cloud_ips(monkeypatch, ips)
        _start_rerun(
            client=client,
            headers=headers,
            monkeypatch=monkeypatch,
            project_id=project["id"],
            run_id=previous["netflow_context"]["governance_run_id"],
            trigger_id=f"finding-lifecycle-{uuid.uuid4()}",
        )
        return _detail(client, headers, project["id"], finding.id)

    repeated = rerun([])
    assert (
        repeated["id"],
        repeated["status"],
        repeated["occurrence_count"],
        repeated["transition_count"],
    ) == (identity, "OPEN", 2, 1)
    assert repeated["netflow_context"]["status"] == "POSITIVE_ACTIVITY"
    assert (
        repeated["netflow_context"]["activity"]["activity_id"]
        != first["netflow_context"]["activity"]["activity_id"]
    )

    closed = rerun(["192.0.2.10"])
    assert (
        closed["status"],
        closed["occurrence_count"],
        closed["transition_count"],
    ) == ("CLOSED", 2, 2)
    assert closed["transitions"][0]["transition_type"] == "CLOSED"
    current_run = closed["netflow_context"]["governance_run_id"]
    assert all(
        item["governance_run_id"] != current_run for item in closed["occurrences"]
    )
    assert closed["netflow_context"]["status"] == "POSITIVE_ACTIVITY"
    paged = _detail(
        client,
        headers,
        project["id"],
        finding.id,
        trace_limit=1,
        occurrence_skip=100,
        transition_skip=100,
    )
    assert paged["occurrences"] == paged["transitions"] == []
    assert paged["netflow_context"] == closed["netflow_context"]
    trace = _detail(client, headers, project["id"], finding.id, trace_limit=1)
    assert len(trace["transitions"][0]["source_snapshot_ids"]) == 1

    historical = rerun(["192.0.2.10"])
    assert historical["status"] == "CLOSED"
    assert historical["netflow_context"]["status"] == "NOT_APPLICABLE"
    assert historical["netflow_context"]["activity"] is None
    assert (historical["occurrence_count"], historical["transition_count"]) == (2, 2)

    reopened = rerun([])
    assert (
        reopened["id"],
        reopened["status"],
        reopened["occurrence_count"],
        reopened["transition_count"],
    ) == (identity, "OPEN", 3, 3)
    assert reopened["transitions"][0]["transition_type"] == "REOPENED"
    assert reopened["netflow_context"]["status"] == "POSITIVE_ACTIVITY"


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("legacy", "INPUT_UNMODELED"),
        ("absent", "INPUT_ABSENT"),
    ],
)
def test_historical_and_explicit_absent_inputs_are_distinct(
    mode: str,
    expected: str,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_runner(tmp_path, monkeypatch)
    project = run_fixtures._create_project(client, superuser_token_headers)
    upload, source = run_fixtures._prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    _cloud_ips(monkeypatch, [])
    if mode == "legacy":
        environment = run_fixtures._runner_environment(
            project=project,
            upload=upload,
            source=source,
            trigger_id=f"legacy-{uuid.uuid4()}",
            session_seed=str(uuid.uuid4()),
        )
        for key, value in environment.items():
            monkeypatch.setenv(key, value)
    else:
        run_fixtures._trigger_stage5_run(
            client=client,
            headers=superuser_token_headers,
            monkeypatch=monkeypatch,
            project=project,
            trigger_id=f"absent-{uuid.uuid4()}",
        )
    assert run_runner() == 0
    response = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/findings",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    finding = response.json()["data"][0]
    detail = _detail(client, superuser_token_headers, project["id"], finding["id"])
    assert detail["netflow_context"] == {
        "governance_run_id": response.json()["latest_run_id"],
        "status": expected,
        "activity": None,
    }


@pytest.mark.parametrize("finding_run", ["empty"], indirect=True)
def test_present_empty_requires_verified_zero_receipt(
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project, finding = finding_run
    detail = _detail(client, superuser_token_headers, project["id"], finding.id)
    assert detail["netflow_context"]["status"] == "NO_POSITIVE_ACTIVITY"
    assert detail["netflow_context"]["activity"] is None


@contextmanager
def _damaged_publication() -> Iterator[Session]:
    # Use the same PostgreSQL fixture technique as #175, with rollback isolation.
    with Session(engine) as session:
        session.connection().exec_driver_sql(
            "SET LOCAL session_replication_role = replica"
        )

        def override() -> Iterator[Session]:
            session.expire_all()
            yield session

        app.dependency_overrides[_finding_read_session] = override
        try:
            yield session
        finally:
            app.dependency_overrides.pop(_finding_read_session, None)
            session.rollback()


def _replace_publication_payload(
    session: Session,
    run_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    run = session.get(GovernanceRun, run_id)
    assert run is not None
    steps = {
        item.step_code: item
        for item in session.exec(
            select(RunStep).where(RunStep.governance_run_id == run_id)
        ).all()
    }
    publication = session.exec(
        select(AuditEvent).where(
            AuditEvent.target_id == run_id,
            AuditEvent.action == "governance_run.published",
        )
    ).one()
    # This helper intentionally seals controlled historical/boundary fixtures.
    session.exec(
        update(AuditEvent)
        .where(col(AuditEvent.id) == publication.id)
        .values(after_data=payload)
    )
    publish_output = {
        "processing_contract_version": run.processing_contract_version,
        "check_findings_output_hash": steps["CHECK_FINDINGS"].output_hash,
        **(
            {"netflow_activity": payload["netflow_activity"]}
            if "netflow_activity" in payload
            else {}
        ),
    }
    if run.report_contract_version is not None:
        publish_output.update(
            validated_report_output_hash=steps["VALIDATE_REPORT"].output_hash,
            governance_report_id=payload["governance_report_id"],
        )
    session.exec(
        update(RunStep)
        .where(col(RunStep.id) == steps["PUBLISH"].id)
        .values(output_hash=_hash(publish_output))
    )


def _historical_activity_receipt(session: Session, run_id: uuid.UUID) -> None:
    publication = session.exec(
        select(AuditEvent).where(
            AuditEvent.target_id == run_id,
            AuditEvent.action == "governance_run.published",
        )
    ).one()
    payload = dict(publication.after_data or {})
    payload.pop("netflow_activity")
    _replace_publication_payload(session, run_id, payload)


@pytest.mark.parametrize("finding_run", ["empty", "active"], indirect=True)
def test_original_missing_activity_contract_is_not_a_missing_receipt_fallback(
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project, finding = finding_run
    before = _detail(client, superuser_token_headers, project["id"], finding.id)
    run_id = uuid.UUID(before["netflow_context"]["governance_run_id"])
    with _damaged_publication() as session:
        _historical_activity_receipt(session, run_id)
        response = client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}/findings/{finding.id}",
            headers=superuser_token_headers,
        )
        if before["netflow_context"]["activity"] is None:
            assert response.status_code == 200, response.text
            assert response.json()["netflow_context"] == {
                "governance_run_id": str(run_id),
                "status": "ACTIVITY_UNMODELED",
                "activity": None,
            }
        else:
            assert response.status_code == 500
            assert response.json() == {"detail": "Internal Server Error"}


def _workbook(ips: list[str]) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(run_fixtures.REQUIRED_HEADERS)
    for ip in ips:
        sheet.append([ip, 443, 443, "是", "example.test"])
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def _select_customer_ips(
    client: TestClient,
    headers: dict[str, str],
    project_id: object,
    ips: list[str],
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/projects/{project_id}/customer-uploads",
        headers=headers,
        files={"file": ("customer.xlsx", _workbook(ips), run_fixtures.XLSX_MEDIA_TYPE)},
    )
    assert response.status_code in (200, 201), response.text
    selected = client.post(
        f"{settings.API_V1_STR}/projects/{project_id}/customer-uploads/{response.json()['id']}/select",
        headers=headers,
    )
    assert selected.status_code == 200, selected.text


def test_all_findings_and_open_backlog_outside_report_sample_get_context(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    ips = [f"192.0.2.{index}" for index in range(1, 56)]
    monkeypatch.setattr(run_fixtures, "_workbook_bytes", lambda: _workbook(ips))
    project, _, _ = _prepare_present_run(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        content=(
            "IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
            + "".join(f"{ip},198.51.100.100,6,443,53000\n" for ip in ips)
        ).encode(),
        trigger_id=f"finding-many-{uuid.uuid4()}",
    )
    _cloud_ips(monkeypatch, [])
    assert run_runner() == 0
    url = f"{settings.API_V1_STR}/projects/{project['id']}"
    listing = client.get(f"{url}/findings", headers=superuser_token_headers).json()
    assert listing["count"] == 55
    original = listing["data"]
    for item in original:
        detail = _detail(
            client,
            superuser_token_headers,
            project["id"],
            item["id"],
            trace_limit=1,
            occurrence_skip=100,
            transition_skip=100,
        )
        assert detail["netflow_context"]["status"] == "POSITIVE_ACTIVITY"
        assert detail["netflow_context"]["activity"]["flow_count"] == 1
        assert detail["occurrences"] == detail["transitions"] == []

    _select_customer_ips(
        client, superuser_token_headers, project["id"], ["203.0.113.10"]
    )
    _start_rerun(
        client=client,
        headers=superuser_token_headers,
        monkeypatch=monkeypatch,
        project_id=project["id"],
        run_id=listing["latest_run_id"],
        trigger_id=f"finding-backlog-{uuid.uuid4()}",
    )
    latest = client.get(f"{url}/findings", headers=superuser_token_headers).json()
    assert latest["count"] == 56
    for item in original:
        detail = _detail(client, superuser_token_headers, project["id"], item["id"])
        assert detail["status"] == "OPEN"
        assert (detail["occurrence_count"], detail["transition_count"]) == (1, 1)
        assert detail["netflow_context"]["governance_run_id"] == latest["latest_run_id"]
        assert detail["netflow_context"]["status"] == "POSITIVE_ACTIVITY"
        assert all(
            event["governance_run_id"] == listing["latest_run_id"]
            for event in detail["occurrences"] + detail["transitions"]
        )
    unrelated = next(
        item for item in latest["data"] if item["canonical_ip"] == "203.0.113.10"
    )
    detail = _detail(client, superuser_token_headers, project["id"], unrelated["id"])
    assert detail["netflow_context"]["status"] == "NO_POSITIVE_ACTIVITY"
    assert detail["netflow_context"]["activity"] is None


def test_same_resource_finding_types_share_activity_but_not_eligibility(
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project, finding = finding_run
    headers = superuser_token_headers
    _select_customer_ips(client, headers, project["id"], ["203.0.113.10"])
    _cloud_ips(monkeypatch, ["192.0.2.10"])

    def publish() -> dict[str, Any]:
        previous = _detail(client, headers, project["id"], finding.id)
        _start_rerun(
            client=client,
            headers=headers,
            monkeypatch=monkeypatch,
            project_id=project["id"],
            run_id=previous["netflow_context"]["governance_run_id"],
            trigger_id=f"finding-types-{uuid.uuid4()}",
        )
        return _detail(client, headers, project["id"], finding.id)

    backlog = publish()
    listing = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/findings", headers=headers
    ).json()
    opposite = next(
        item
        for item in listing["data"]
        if item["canonical_ip"] == "192.0.2.10" and item["id"] != str(finding.id)
    )
    opposite_detail = _detail(client, headers, project["id"], opposite["id"])
    assert (backlog["occurrence_count"], backlog["transition_count"]) == (1, 1)
    assert backlog["status"] == opposite_detail["status"] == "OPEN"
    assert backlog["netflow_context"] == opposite_detail["netflow_context"]

    _select_customer_ips(client, headers, project["id"], ["192.0.2.10"])
    closed = publish()
    assert closed["status"] == "CLOSED"
    assert closed["netflow_context"]["status"] == "POSITIVE_ACTIVITY"
    _select_customer_ips(client, headers, project["id"], ["203.0.113.10"])
    old_closed = publish()
    reopened = _detail(client, headers, project["id"], opposite["id"])
    assert old_closed["status"] == "CLOSED"
    assert old_closed["netflow_context"]["status"] == "NOT_APPLICABLE"
    assert old_closed["netflow_context"]["activity"] is None
    assert reopened["status"] == "OPEN"
    assert reopened["netflow_context"]["status"] == "POSITIVE_ACTIVITY"


@pytest.mark.parametrize(
    "damage",
    [
        "missing_activity",
        "content",
        "identity",
        "snapshot_reference",
        "activity_contract",
        "activity_project",
        "activity_tenant",
        "activity_run",
        "missing_snapshot",
        "snapshot_hash",
        "load_hash",
        "input_hash",
        "pinned_hash",
        "dataset_contract",
        "legacy_with_netflow",
        "absent_with_netflow",
        "missing_receipt",
        "receipt_count",
        "receipt_hash",
        "receipt_contract",
        "publish_hash",
        "duplicate_publication",
    ],
)
def test_corrupted_facts_and_receipts_fail_closed_at_http_boundary(
    damage: str,
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project, finding = finding_run
    before = _detail(client, superuser_token_headers, project["id"], finding.id)
    run_id = uuid.UUID(before["netflow_context"]["governance_run_id"])
    activity_id = uuid.UUID(before["netflow_context"]["activity"]["activity_id"])
    with _damaged_publication() as session:
        if damage == "missing_activity":
            session.exec(
                delete(NetFlowIPActivity).where(
                    col(NetFlowIPActivity.id) == activity_id
                )
            )
        elif damage in {
            "content",
            "identity",
            "snapshot_reference",
            "activity_contract",
            "activity_project",
            "activity_tenant",
            "activity_run",
        }:
            field, value = {
                "content": ("flow_count", 2),
                "identity": ("id", uuid.uuid4()),
                "snapshot_reference": ("source_snapshot_id", uuid.uuid4()),
                "activity_contract": (
                    "aggregation_contract_version",
                    "unknown-contract",
                ),
                "activity_project": ("project_id", uuid.uuid4()),
                "activity_tenant": ("tenant_id", uuid.uuid4()),
                "activity_run": ("governance_run_id", uuid.uuid4()),
            }[damage]
            session.exec(
                update(NetFlowIPActivity)
                .where(col(NetFlowIPActivity.id) == activity_id)
                .values(**{field: value})
            )
        elif damage == "missing_snapshot":
            session.exec(
                delete(SourceSnapshot).where(
                    col(SourceSnapshot.governance_run_id) == run_id,
                    col(SourceSnapshot.source_type) == "NETFLOW",
                )
            )
        elif damage == "snapshot_hash":
            session.exec(
                update(SourceSnapshot)
                .where(
                    col(SourceSnapshot.governance_run_id) == run_id,
                    col(SourceSnapshot.source_type) == "NETFLOW",
                )
                .values(content_sha256="0" * 64)
            )
        elif damage in {"load_hash", "publish_hash"}:
            session.exec(
                update(RunStep)
                .where(
                    col(RunStep.governance_run_id) == run_id,
                    col(RunStep.step_code)
                    == ("LOAD_NETFLOW" if damage == "load_hash" else "PUBLISH"),
                )
                .values(output_hash="0" * 64)
            )
        elif damage in {"input_hash", "pinned_hash", "dataset_contract"}:
            field, value = {
                "input_hash": ("input_hash", "0" * 64),
                "pinned_hash": ("netflow_content_sha256", "0" * 64),
                "dataset_contract": (
                    "netflow_dataset_contract_version",
                    "unknown-contract",
                ),
            }[damage]
            session.exec(
                update(GovernanceRun)
                .where(col(GovernanceRun.id) == run_id)
                .values(**{field: value})
            )
        elif damage in {"legacy_with_netflow", "absent_with_netflow"}:
            values: dict[str, Any] = {
                "netflow_dataset_id": None,
                "netflow_content_sha256": None,
                "netflow_dataset_contract_version": None,
            }
            if damage == "legacy_with_netflow":
                values.update(input_contract_version=None, input_hash=None)
            session.exec(
                update(GovernanceRun)
                .where(col(GovernanceRun.id) == run_id)
                .values(**values)
            )
        else:
            audit = session.exec(
                select(AuditEvent).where(
                    AuditEvent.target_id == run_id,
                    AuditEvent.action == "governance_run.published",
                )
            ).one()
            if damage == "duplicate_publication":
                session.add(AuditEvent(**audit.model_dump(exclude={"id"})))
                session.flush()
            else:
                data = dict(audit.after_data or {})
                if damage == "missing_receipt":
                    data.pop("netflow_activity")
                else:
                    receipt = dict(data["netflow_activity"])
                    field, value = {
                        "receipt_count": ("activity_count", 0),
                        "receipt_hash": ("output_hash", "0" * 64),
                        "receipt_contract": ("contract_version", "unknown-contract"),
                    }[damage]
                    receipt[field] = value
                    data["netflow_activity"] = receipt
                session.exec(
                    update(AuditEvent)
                    .where(col(AuditEvent.id) == audit.id)
                    .values(after_data=data)
                )
                if damage != "missing_receipt":
                    _replace_publication_payload(session, run_id, data)
        response = client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}/findings/{finding.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 500, response.text
        assert response.json() == {"detail": "Internal Server Error"}


def test_other_resource_corruption_is_not_an_empty_or_positive_result(
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project, finding = finding_run
    before = _detail(client, superuser_token_headers, project["id"], finding.id)
    _cloud_ips(monkeypatch, ["198.51.100.20"])
    _start_rerun(
        client=client,
        headers=superuser_token_headers,
        monkeypatch=monkeypatch,
        project_id=project["id"],
        run_id=before["netflow_context"]["governance_run_id"],
        trigger_id=f"off-target-{uuid.uuid4()}",
    )
    latest = _detail(client, superuser_token_headers, project["id"], finding.id)
    run_id = uuid.UUID(latest["netflow_context"]["governance_run_id"])
    with _damaged_publication() as session:
        other = session.exec(
            select(NetFlowIPActivity).where(
                NetFlowIPActivity.governance_run_id == run_id,
                NetFlowIPActivity.resource_id != finding.resource_id,
            )
        ).one()
        assert "192.0.2.10" in {str(ip) for ip in other.peer_ips}
        session.exec(
            update(NetFlowIPActivity)
            .where(col(NetFlowIPActivity.id) == other.id)
            .values(flow_count=99)
        )
        response = client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}/findings/{finding.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal Server Error"}


def test_detail_is_read_only_minimal_and_validates_collection_once(
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project, finding = finding_run
    calls = 0
    original = read_published_netflow_activities

    def verified(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        connection = kwargs["session"].connection()
        assert (
            connection.exec_driver_sql("SHOW transaction_read_only").scalar_one()
            == "on"
        )
        assert (
            connection.exec_driver_sql("SHOW transaction_isolation").scalar_one()
            == "repeatable read"
        )
        return original(**kwargs)

    monkeypatch.setattr(ip_results, "read_published_netflow_activities", verified)

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("Finding detail must not read Artifacts or external sources")

    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(OctobusCloudAtlasClient, "list_ip_assets_page", forbidden)
    statements: list[str] = []
    commits: list[object] = []

    def trace(_connection: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement.lstrip().upper())

    def committed(session: Session) -> None:
        commits.append(session)

    event.listen(engine, "before_cursor_execute", trace)
    event.listen(Session, "after_commit", committed)
    try:
        detail = _detail(client, superuser_token_headers, project["id"], finding.id)
    finally:
        event.remove(engine, "before_cursor_execute", trace)
        event.remove(Session, "after_commit", committed)
    assert calls == 1
    assert commits == []
    assert not any(
        item.startswith(("INSERT", "UPDATE", "DELETE", "MERGE")) for item in statements
    )
    context = detail["netflow_context"]
    assert set(context) == {"governance_run_id", "status", "activity"}
    assert set(context["activity"]) == {
        "activity_id",
        "source_snapshot_id",
        "aggregation_contract_version",
        "content_sha256",
        "flow_count",
        "first_seen_utc",
        "last_seen_utc",
    }


def test_real_concurrent_publish_cannot_mix_run_activity_and_finding_state(
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project, finding = finding_run
    headers = superuser_token_headers
    before = _detail(client, headers, project["id"], finding.id)
    _cloud_ips(monkeypatch, ["192.0.2.10"])
    environment = _prepare_rerun(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=project["id"],
        run_id=before["netflow_context"]["governance_run_id"],
        trigger_id=f"concurrent-context-{uuid.uuid4()}",
    )
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    snapshot_ready = Event()
    publication_finished = Event()
    original = ip_results.published_run_view
    reader_pids: set[int] = set()
    writer_pids: set[int] = set()

    def pause_after_run_selection(**kwargs: Any) -> Any:
        result = original(**kwargs)
        connection = kwargs["session"].connection()
        reader_pids.add(
            connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
        )
        snapshot_ready.set()
        assert publication_finished.wait(30), "publisher blocked by a detail read"
        return result

    def writer_connection(_session: Any, _transaction: Any, connection: Any) -> None:
        if (
            connection.exec_driver_sql("SHOW transaction_read_only").scalar_one()
            == "off"
        ):
            writer_pids.add(
                connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            )

    def publish() -> int:
        assert snapshot_ready.wait(30), "detail did not establish a snapshot"
        try:
            return run_runner()
        finally:
            publication_finished.set()

    monkeypatch.setattr(ip_results, "published_run_view", pause_after_run_selection)
    event.listen(Session, "after_begin", writer_connection)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(publish)
            during = _detail(client, headers, project["id"], finding.id)
            assert future.result(timeout=30) == 0
    finally:
        snapshot_ready.set()
        event.remove(Session, "after_begin", writer_connection)
        monkeypatch.setattr(ip_results, "published_run_view", original)
    assert reader_pids and writer_pids and reader_pids.isdisjoint(writer_pids)
    assert during == before
    after = _detail(client, headers, project["id"], finding.id)
    assert after["status"] == "CLOSED"
    assert after["transition_count"] == before["transition_count"] + 1
    assert (
        after["netflow_context"]["governance_run_id"]
        != before["netflow_context"]["governance_run_id"]
    )
    assert after["netflow_context"]["status"] == "POSITIVE_ACTIVITY"


def test_roles_archive_revocation_and_cross_project_do_not_leak_context(
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project, finding = finding_run
    admin = superuser_token_headers
    expected = _detail(client, admin, project["id"], finding.id)
    members = [
        run_fixtures._create_member(
            client, admin, project_id=project["id"], roles=roles
        )
        for roles in [
            ["viewer"],
            ["operator"],
            ["approver"],
            ["viewer", "operator", "approver"],
        ]
    ]
    other = run_fixtures._create_project(client, admin)
    outsider = run_fixtures._create_member(
        client, admin, project_id=other["id"], roles=["viewer"]
    )
    url = f"{settings.API_V1_STR}/projects/{project['id']}"
    for headers in members:
        assert _detail(client, headers, project["id"], finding.id) == expected
    assert (
        client.get(f"{url}/findings/{finding.id}", headers=outsider).status_code == 404
    )
    assert (
        client.get(
            f"{settings.API_V1_STR}/projects/{other['id']}/findings/{finding.id}",
            headers=admin,
        ).status_code
        == 404
    )
    assert (
        client.get(f"{url}/findings/{uuid.uuid4()}", headers=admin).status_code == 404
    )
    assert client.get(f"{url}/findings/{finding.id}").status_code == 401
    memberships = client.get(f"{url}/memberships/", headers=admin).json()["data"]
    viewer = next(item for item in memberships if item["roles"] == ["viewer"])
    revoked = client.post(f"{url}/memberships/{viewer['id']}/revoke", headers=admin)
    assert revoked.status_code == 200, revoked.text
    assert (
        client.get(f"{url}/findings/{finding.id}", headers=members[0]).status_code
        == 404
    )
    archived = client.post(f"{url}/archive", headers=admin)
    assert archived.status_code == 200, archived.text
    for headers in [admin, *members[1:]]:
        assert _detail(client, headers, project["id"], finding.id) == expected


@pytest.mark.parametrize("status", ["RUNNING", "FAILED_DATA", "FAILED_PROCESSING"])
def test_detail_preserves_latest_compatible_read_gate(
    status: str,
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project, finding = finding_run
    before = _detail(client, superuser_token_headers, project["id"], finding.id)
    run_id = uuid.UUID(before["netflow_context"]["governance_run_id"])
    with _damaged_publication() as session:
        session.exec(
            update(GovernanceRun)
            .where(col(GovernanceRun.id) == run_id)
            .values(status=status)
        )
        response = client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}/findings/{finding.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 404


def test_detail_accepts_completed_with_warnings(
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project, finding = finding_run
    before = _detail(client, superuser_token_headers, project["id"], finding.id)
    run_id = uuid.UUID(before["netflow_context"]["governance_run_id"])
    with _damaged_publication() as session:
        session.exec(
            update(GovernanceRun)
            .where(col(GovernanceRun.id) == run_id)
            .values(status="COMPLETED_WITH_WARNINGS")
        )
        response = client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}/findings/{finding.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert response.json() == before


def test_running_and_failed_new_run_leave_previous_activity_visible(
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project, finding = finding_run
    headers = superuser_token_headers
    before = _detail(client, headers, project["id"], finding.id)
    environment = _prepare_rerun(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=project["id"],
        run_id=before["netflow_context"]["governance_run_id"],
        trigger_id=f"unfinished-context-{uuid.uuid4()}",
    )
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    pulling = Event()
    release = Event()

    def fail_source(
        _client: Any, _source: Any, *, capset_token: str, page: int, size: int
    ) -> dict[str, Any]:
        del capset_token
        pulling.set()
        assert release.wait(30)
        return {
            "items": [{"id": "bad", "ip": "192.0.2.10", "status": "stale"}],
            "page": page,
            "size": size,
            "total": 1,
        }

    monkeypatch.setattr(OctobusCloudAtlasClient, "list_ip_assets_page", fail_source)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_runner)
        try:
            assert pulling.wait(30)
            assert _detail(client, headers, project["id"], finding.id) == before
        finally:
            release.set()
        assert future.result(timeout=30) == 1
    assert _detail(client, headers, project["id"], finding.id) == before


@pytest.mark.parametrize("flow_count", [1, 2147483647])
@pytest.mark.parametrize(
    "times", [(None, None), ("first", None), (None, "last"), ("first", "last")]
)
def test_int32_boundary_and_nullable_times_are_exact_http_projections(
    flow_count: int,
    times: tuple[str | None, str | None],
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project, finding = finding_run
    before = _detail(client, superuser_token_headers, project["id"], finding.id)
    run_id = uuid.UUID(before["netflow_context"]["governance_run_id"])
    first = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC) if times[0] else None
    last = datetime(2026, 1, 2, 4, 5, 6, tzinfo=UTC) if times[1] else None
    # A sealed PostgreSQL boundary fixture, not a claim to publish 2B raw records.
    with _damaged_publication() as session:
        activity = session.exec(
            select(NetFlowIPActivity).where(
                NetFlowIPActivity.governance_run_id == run_id
            )
        ).one()
        aggregate = NetFlowIPActivityAggregate(
            canonical_ip="192.0.2.10",
            flow_count=flow_count,
            peer_ips=tuple(str(ip) for ip in activity.peer_ips),
            protocols=tuple(activity.protocols),
            first_seen_utc=first,
            last_seen_utc=last,
        )
        content_hash = netflow_activity_content_hash(aggregate)
        session.exec(
            update(NetFlowIPActivity)
            .where(col(NetFlowIPActivity.id) == activity.id)
            .values(
                flow_count=flow_count,
                first_seen_utc=first,
                last_seen_utc=last,
                content_sha256=content_hash,
            )
        )
        publication = session.exec(
            select(AuditEvent).where(
                AuditEvent.target_id == run_id,
                AuditEvent.action == "governance_run.published",
            )
        ).one()
        data = dict(publication.after_data or {})
        receipt = dict(data["netflow_activity"])
        receipt["output_hash"] = netflow_activity_output_hash((aggregate,))
        data["netflow_activity"] = receipt
        _replace_publication_payload(session, run_id, data)
        detail = _detail(client, superuser_token_headers, project["id"], finding.id)
        projected = detail["netflow_context"]["activity"]
        assert (
            type(projected["flow_count"]) is int
            and projected["flow_count"] == flow_count
        )
        assert projected["content_sha256"] == content_hash
        assert projected["first_seen_utc"] == (
            first.isoformat().replace("+00:00", "Z") if first else None
        )
        assert projected["last_seen_utc"] == (
            last.isoformat().replace("+00:00", "Z") if last else None
        )


def test_finding_netflow_openapi_exposes_only_the_exact_required_contract(
    client: TestClient,
) -> None:
    response = client.get(f"{settings.API_V1_STR}/openapi.json")
    assert response.status_code == 200
    schemas = response.json()["components"]["schemas"]
    detail = schemas["FindingDetailPublic"]
    assert "netflow_context" in detail["required"]
    context = schemas["FindingNetFlowContextPublic"]
    assert context["additionalProperties"] is False
    assert (
        set(context["properties"])
        == set(context["required"])
        == {"governance_run_id", "status", "activity"}
    )
    assert set(context["properties"]["status"]["enum"]) == {
        "NOT_APPLICABLE",
        "INPUT_UNMODELED",
        "INPUT_ABSENT",
        "ACTIVITY_UNMODELED",
        "NO_POSITIVE_ACTIVITY",
        "POSITIVE_ACTIVITY",
    }
    activity = schemas["FindingNetFlowActivityPublic"]
    assert activity["additionalProperties"] is False
    assert (
        set(activity["properties"])
        == set(activity["required"])
        == {
            "activity_id",
            "source_snapshot_id",
            "aggregation_contract_version",
            "content_sha256",
            "flow_count",
            "first_seen_utc",
            "last_seen_utc",
        }
    )
    count = activity["properties"]["flow_count"]
    assert (count["type"], count["minimum"], count["maximum"]) == (
        "integer",
        1,
        2147483647,
    )


def test_mapped_ips_duplicates_and_input_order_reuse_existing_activity_identity_rules(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        run_fixtures,
        "_workbook_bytes",
        lambda: _workbook(["::ffff:192.0.2.10", "192.0.2.10"]),
    )
    header = (
        "IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT,start_time,end_time\n"
    )
    rows = [
        "192.0.2.10,198.51.100.20,6,53000,443,2026-01-02 11:04:05,2026-01-02 12:05:06\n",
        "::ffff:192.0.2.10,198.51.100.20,6,53000,443,2026-01-02 11:04:05,2026-01-02 12:05:06\n",
        "192.0.2.10,192.0.2.10,1,0,2048,,\n",
    ]
    project, _, _ = _prepare_present_run(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        content=(header + "".join(rows)).encode(),
        trigger_id=f"canonical-context-{uuid.uuid4()}",
    )
    _cloud_ips(monkeypatch, [])
    assert run_runner() == 0
    url = f"{settings.API_V1_STR}/projects/{project['id']}"
    listing = client.get(f"{url}/findings", headers=superuser_token_headers).json()
    assert listing["count"] == 1
    finding = listing["data"][0]
    before = _detail(client, superuser_token_headers, project["id"], finding["id"])
    activity = before["netflow_context"]["activity"]
    assert finding["canonical_ip"] == "192.0.2.10"
    assert activity["flow_count"] == 3
    assert activity["first_seen_utc"] == "2026-01-02T03:04:05Z"
    assert activity["last_seen_utc"] == "2026-01-02T04:05:06Z"
    assert activity["activity_id"] == str(
        uuid.uuid5(
            uuid.UUID(listing["latest_run_id"]), "netflow-ip-activity-v1/192.0.2.10"
        )
    )
    dataset = _upload(
        client,
        superuser_token_headers,
        project["id"],
        (header + "".join(reversed(rows))).encode(),
    )
    assert dataset.status_code == 201, dataset.text
    selected = client.post(
        f"{url}/netflow-datasets/{dataset.json()['id']}/select",
        headers=superuser_token_headers,
    )
    assert selected.status_code == 200
    _start_rerun(
        client=client,
        headers=superuser_token_headers,
        monkeypatch=monkeypatch,
        project_id=project["id"],
        run_id=listing["latest_run_id"],
        trigger_id=f"canonical-reordered-{uuid.uuid4()}",
    )
    after = _detail(client, superuser_token_headers, project["id"], finding["id"])
    assert after["id"] == before["id"] and after["occurrence_count"] == 2
    second = after["netflow_context"]["activity"]
    assert second["content_sha256"] == activity["content_sha256"]
    assert second["flow_count"] == activity["flow_count"]
    assert second["activity_id"] != activity["activity_id"]
    assert second["source_snapshot_id"] != activity["source_snapshot_id"]
    assert second["activity_id"] == str(
        uuid.uuid5(
            uuid.UUID(after["netflow_context"]["governance_run_id"]),
            "netflow-ip-activity-v1/192.0.2.10",
        )
    )


def test_erased_receipt_cannot_masquerade_as_legacy_input(
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project, finding = finding_run
    before = _detail(client, superuser_token_headers, project["id"], finding.id)
    run_id = uuid.UUID(before["netflow_context"]["governance_run_id"])
    with _damaged_publication() as session:
        session.exec(
            delete(NetFlowIPActivity).where(
                col(NetFlowIPActivity.governance_run_id) == run_id
            )
        )
        session.exec(
            delete(SourceSnapshot).where(
                col(SourceSnapshot.governance_run_id) == run_id,
                col(SourceSnapshot.source_type) == "NETFLOW",
            )
        )
        session.exec(
            update(GovernanceRun)
            .where(col(GovernanceRun.id) == run_id)
            .values(
                input_contract_version=None,
                input_hash=None,
                netflow_dataset_id=None,
                netflow_content_sha256=None,
                netflow_dataset_contract_version=None,
            )
        )
        audit = session.exec(
            select(AuditEvent).where(
                AuditEvent.target_id == run_id,
                AuditEvent.action == "governance_run.published",
            )
        ).one()
        data = dict(audit.after_data or {})
        data.pop("netflow_activity")
        session.exec(
            update(AuditEvent)
            .where(col(AuditEvent.id) == audit.id)
            .values(after_data=data)
        )
        response = client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}/findings/{finding.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal Server Error"}


def test_extra_activity_is_rejected_even_when_target_row_is_untouched(
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project, finding = finding_run
    before = _detail(client, superuser_token_headers, project["id"], finding.id)
    run_id = uuid.UUID(before["netflow_context"]["governance_run_id"])
    with _damaged_publication() as session:
        source = session.exec(
            select(NetFlowIPActivity).where(
                NetFlowIPActivity.governance_run_id == run_id
            )
        ).one()
        resource = Resource(
            tenant_id=finding.tenant_id,
            project_id=finding.project_id,
            resource_type="IP",
            canonical_key="203.0.113.123",
        )
        session.add(resource)
        session.flush()
        aggregate = NetFlowIPActivityAggregate(
            canonical_ip="203.0.113.123",
            flow_count=1,
            peer_ips=("192.0.2.10",),
            protocols=(6,),
            first_seen_utc=None,
            last_seen_utc=None,
        )
        session.add(
            NetFlowIPActivity(
                id=uuid.uuid5(run_id, "netflow-ip-activity-v1/203.0.113.123"),
                tenant_id=finding.tenant_id,
                project_id=finding.project_id,
                governance_run_id=run_id,
                resource_id=resource.id,
                source_snapshot_id=source.source_snapshot_id,
                source_type="NETFLOW",
                aggregation_contract_version="netflow-ip-activity-v1",
                flow_count=1,
                peer_ips=["192.0.2.10"],
                protocols=[6],
                content_sha256=netflow_activity_content_hash(aggregate),
            )
        )
        session.flush()
        response = client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}/findings/{finding.id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal Server Error"}


def test_public_dto_rejects_coercions_unknown_fields_and_inconsistent_activity(
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project, finding = finding_run
    detail = _detail(client, superuser_token_headers, project["id"], finding.id)
    context = detail["netflow_context"]
    assert (
        FindingNetFlowContextPublic.model_validate(context).status
        == "POSITIVE_ACTIVITY"
    )
    missing = dict(detail)
    missing.pop("netflow_context")
    with pytest.raises(ValidationError):
        FindingDetailPublic.model_validate(missing)

    for value in (True, False, 0, -1, 2147483648, 1.0, "1"):
        invalid = deepcopy(context)
        invalid["activity"]["flow_count"] = value
        with pytest.raises(ValidationError):
            FindingNetFlowContextPublic.model_validate(invalid)
    for activity_field, activity_value in (
        ("activity_id", "not-a-uuid"),
        ("source_snapshot_id", "not-a-uuid"),
        ("aggregation_contract_version", "unknown"),
        ("content_sha256", "A" * 64),
        ("content_sha256", "a" * 63),
        ("first_seen_utc", "2026-01-01T00:00:00"),
        ("peer_ips", ["192.0.2.10"]),
    ):
        invalid = deepcopy(context)
        invalid["activity"][activity_field] = activity_value
        with pytest.raises(ValidationError):
            FindingNetFlowContextPublic.model_validate(invalid)
    for context_field, context_value in (
        ("governance_run_id", "not-a-uuid"),
        ("status", "UNKNOWN"),
        ("activity", None),
        ("download_url", "https://invalid.example"),
    ):
        invalid = deepcopy(context)
        invalid[context_field] = context_value
        with pytest.raises(ValidationError):
            FindingNetFlowContextPublic.model_validate(invalid)
    for status in (
        "NOT_APPLICABLE",
        "INPUT_UNMODELED",
        "INPUT_ABSENT",
        "ACTIVITY_UNMODELED",
        "NO_POSITIVE_ACTIVITY",
    ):
        invalid = deepcopy(context)
        invalid["status"] = status
        with pytest.raises(ValidationError):
            FindingNetFlowContextPublic.model_validate(invalid)
        invalid["activity"] = None
        assert FindingNetFlowContextPublic.model_validate(invalid).status == status


def test_database_prevents_multiple_activity_rows_for_one_run_resource(
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project, finding = finding_run
    before = _detail(client, superuser_token_headers, project["id"], finding.id)
    run_id = uuid.UUID(before["netflow_context"]["governance_run_id"])
    with _damaged_publication() as session:
        activity = session.exec(
            select(NetFlowIPActivity).where(
                NetFlowIPActivity.governance_run_id == run_id
            )
        ).one()
        with pytest.raises(IntegrityError) as error:
            with session.begin_nested():
                session.add(
                    NetFlowIPActivity(
                        id=uuid.uuid4(),
                        tenant_id=activity.tenant_id,
                        project_id=activity.project_id,
                        governance_run_id=activity.governance_run_id,
                        source_snapshot_id=activity.source_snapshot_id,
                        source_type=activity.source_type,
                        resource_id=activity.resource_id,
                        aggregation_contract_version=activity.aggregation_contract_version,
                        flow_count=activity.flow_count,
                        peer_ips=[str(ip) for ip in activity.peer_ips],
                        protocols=activity.protocols,
                        first_seen_utc=activity.first_seen_utc,
                        last_seen_utc=activity.last_seen_utc,
                        content_sha256=activity.content_sha256,
                    )
                )
                session.flush()
        assert isinstance(error.value.orig, UniqueViolation)
        assert (
            error.value.orig.diag.constraint_name
            == "uq_netflow_ip_activities_run_resource"
        )
        assert (
            _detail(client, superuser_token_headers, project["id"], finding.id)
            == before
        )


def test_zero_findings_do_not_get_created_by_positive_activity(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    project, _, _ = _prepare_present_run(
        client=client,
        headers=superuser_token_headers,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        content=(
            b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
            b"192.0.2.10,198.51.100.20,6,53000,443\n"
        ),
        trigger_id=f"zero-findings-{uuid.uuid4()}",
    )
    assert run_runner() == 0
    url = f"{settings.API_V1_STR}/projects/{project['id']}"
    response = client.get(f"{url}/findings", headers=superuser_token_headers)
    assert response.status_code == 200
    assert response.json()["data"] == [] and response.json()["count"] == 0
    assert (
        client.get(
            f"{url}/findings/{uuid.uuid4()}", headers=superuser_token_headers
        ).status_code
        == 404
    )


def test_detail_does_not_reuse_an_older_dependency_identity_map(
    finding_run: tuple[dict[str, object], Finding],
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project, finding = finding_run
    headers = superuser_token_headers
    before = _detail(client, headers, project["id"], finding.id)
    with Session(engine) as stale:
        old_project = stale.get(Project, uuid.UUID(str(project["id"])))
        old_finding = stale.get(Finding, finding.id)
        assert old_project is not None and old_finding is not None
        _cloud_ips(monkeypatch, ["192.0.2.10"])
        _start_rerun(
            client=client,
            headers=headers,
            monkeypatch=monkeypatch,
            project_id=project["id"],
            run_id=before["netflow_context"]["governance_run_id"],
            trigger_id=f"fresh-map-{uuid.uuid4()}",
        )
        assert old_finding.status == "OPEN"
        assert (
            str(old_project.latest_completed_run_id)
            == before["netflow_context"]["governance_run_id"]
        )

        def old_dependency() -> Iterator[Session]:
            yield stale

        app.dependency_overrides[get_db] = old_dependency
        try:
            after = _detail(client, headers, project["id"], finding.id)
        finally:
            app.dependency_overrides.pop(get_db, None)
    assert after["status"] == "CLOSED"
    assert after["netflow_context"]["status"] == "POSITIVE_ACTIVITY"
    assert (
        after["netflow_context"]["governance_run_id"]
        != before["netflow_context"]["governance_run_id"]
    )
