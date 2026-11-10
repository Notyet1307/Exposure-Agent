"""Real PostgreSQL HTTP regressions for the read-only input summary projection."""

from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain.comparison_models import CoreComparisonResult
from app.domain.external_asset_models import (
    ExternalAssetRecord,
    ExternalAssetVersion,
    ExternalSync,
)
from app.domain.models import (
    AuditEvent,
    CustomerLedgerRevision,
    CustomerUpload,
    NetFlowDataset,
    Project,
    SourceInstance,
)
from app.domain.netflow_models import NetFlowAnalysis, SourceCorrelationRevision
from tests.api.routes.test_core_comparisons import (
    _create_core,
    _setup_core,
    _workbook,
)
from tests.api.routes.test_netflow_datasets import _project, _upload
from tests.utils.netflow_processing import (
    ControlPlane,
    context_request,
    execute,
    reserve,
)

INVALID = "not-an-ip,198.51.100.1,6,443,51000\n"
VALID = "192.0.2.1,198.51.100.1,6,443,51000\n"
HEADER = "IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"


def _summary(
    client: TestClient, root: str, headers: dict[str, str]
) -> dict[str, Any]:
    response = client.get(root + "/input-summary", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    return cast(dict[str, Any], response.json())


def _count(
    db: Session, model: type[Any], project_id: uuid.UUID | None = None
) -> int:
    query = select(func.count()).select_from(model)
    if project_id is not None:
        query = query.where(model.project_id == project_id)
    return int(db.exec(query).one())


def _snapshot(db: Session, project_id: uuid.UUID) -> dict[str, Any]:
    db.expire_all()
    project = db.get(Project, project_id)
    assert project is not None
    scoped = (
        CustomerUpload,
        CustomerLedgerRevision,
        CoreComparisonResult,
        SourceCorrelationRevision,
        NetFlowDataset,
        NetFlowAnalysis,
        ExternalSync,
        SourceInstance,
        AuditEvent,
    )
    return {
        "current_customer_upload_id": project.current_customer_upload_id,
        "current_customer_ledger_revision_id": (
            project.current_customer_ledger_revision_id
        ),
        "current_netflow_dataset_id": project.current_netflow_dataset_id,
        "counts": {
            model.__name__: _count(db, model, project_id) for model in scoped
        }
        | {"ExternalAssetVersion": _count(db, ExternalAssetVersion)},
    }


def _apply_customer(
    client: TestClient,
    headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], str, dict[str, object]]:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    created = _project(client, headers)
    root = f"{settings.API_V1_STR}/projects/{created['id']}"
    upload = client.post(
        root + "/customer-uploads",
        headers=headers,
        files={"file": ("summary.xlsx", _workbook(("192.0.2.10",)))},
    )
    assert upload.status_code == 201, upload.text
    selected = client.post(
        root + f"/customer-uploads/{upload.json()['id']}/select", headers=headers
    )
    assert selected.status_code == 200, selected.text
    return created, root, cast(dict[str, object], upload.json())


def test_input_summary_requires_project_read_access(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    created = _project(client, superuser_token_headers)
    url = f"{settings.API_V1_STR}/projects/{created['id']}/input-summary"
    assert client.get(url).status_code == 401
    denied = client.get(url, headers=normal_user_token_headers)
    assert denied.status_code == 404
    assert denied.headers["Cache-Control"] == "private, no-store"


def test_input_summary_empty_project_is_not_ready_and_not_zero_data(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    created = _project(client, superuser_token_headers)
    body = _summary(
        client,
        f"{settings.API_V1_STR}/projects/{created['id']}",
        superuser_token_headers,
    )
    assert body["contract_version"] == "input-summary-v1"
    assert body["project_id"] == created["id"]
    assert body["customer"] == {
        "applied_upload_id": None,
        "applied_revision_id": None,
        "accepted_upload_count": 0,
        "unapplied_upload_count": 0,
    }
    assert body["cloud"] == {"sources": []}
    assert body["core_readiness"]["contract_version"] == "core-comparison-v2"
    assert body["core_readiness"]["state"] == "CUSTOMER_NOT_READY"
    assert body["core_readiness"]["sources"] == []
    assert body["netflow"] == {
        "read_state": "READ",
        "dataset_count": 0,
        "current_dataset_id": None,
        "scope_id": None,
        "scopes": [],
        "current_analysis_id": None,
        "latest_attempt_status": None,
        "latest_attempt_error_code": None,
    }


def test_input_summary_acceptance_is_not_application(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    created = _project(client, superuser_token_headers)
    root = f"{settings.API_V1_STR}/projects/{created['id']}"
    upload = client.post(
        root + "/customer-uploads",
        headers=superuser_token_headers,
        files={"file": ("accepted-only.xlsx", _workbook(("192.0.2.10",)))},
    )
    assert upload.status_code == 201, upload.text
    body = _summary(client, root, superuser_token_headers)
    assert body["customer"] == {
        "applied_upload_id": None,
        "applied_revision_id": None,
        "accepted_upload_count": 1,
        "unapplied_upload_count": 1,
    }
    assert body["core_readiness"]["state"] == "CUSTOMER_NOT_READY"


def test_input_summary_connection_is_not_a_readable_version(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, root, _upload_row = _apply_customer(
        client, superuser_token_headers, tmp_path, monkeypatch
    )
    project = db.get(Project, uuid.UUID(str(created["id"])))
    assert project is not None
    source = SourceInstance(
        project_id=project.id,
        tenant_id=project.tenant_id,
        capability_profile="assets-v1",
        instance_id="connected-only",
        capset_id="connected-only-assets",
        space_id="42",
        enabled=True,
        validated_fingerprint="f" * 64,
        data_access_enabled=True,
    )
    db.add(source)
    db.commit()
    body = _summary(client, root, superuser_token_headers)
    assert body["cloud"]["sources"] == [
        {
            "source_instance_id": str(source.id),
            "instance_id": "connected-only",
            "space_id": "42",
            "enabled": True,
            "data_access_enabled": True,
            "validation_status": "validated",
        }
    ]
    readiness = body["core_readiness"]
    assert readiness["state"] == "CLOUD_NOT_READY"
    assert [choice["state"] for choice in readiness["clouds"]] == ["NOT_PUBLISHED"]
    assert readiness["sources"] == []


def test_input_summary_ready_reports_counts_and_writes_nothing(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _setup_core(client, db, superuser_token_headers, tmp_path, monkeypatch)
    _create_core(client, core)
    before = _snapshot(db, core["project"].id)
    body = _summary(client, core["root"], core["headers"])
    after = _snapshot(db, core["project"].id)
    assert before == after
    readiness = body["core_readiness"]
    assert readiness["state"] == "READY"
    states = {row["source"]: row for row in readiness["sources"]}
    assert states["CUSTOMER"]["state"] == "VALID_NONEMPTY"
    assert states["CUSTOMER"]["read_state"] == "VALID_NONEMPTY"
    assert states["CUSTOMER"]["source_records"] == 2
    assert states["CLOUD"]["state"] == "VALID_NONEMPTY"
    assert states["CLOUD"]["read_state"] == "VALID_NONEMPTY"
    assert states["CLOUD"]["source_records"] == 2
    assert states["CLOUD"]["coverage_state"] == "SUFFICIENT"
    assert body["customer"]["accepted_upload_count"] == 1
    assert body["customer"]["unapplied_upload_count"] == 0
    assert body["customer"]["applied_upload_id"] == readiness["customer"]["upload_id"]
    assert body["cloud"]["sources"][0]["source_instance_id"] == str(
        core["source"].id
    )
    assert body["cloud"]["sources"][0]["validation_status"] == "not_validated"
    assert body["netflow"]["read_state"] == "READ"
    assert body["netflow"]["dataset_count"] == 0


def test_input_summary_distinguishes_valid_empty_from_unknown(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _setup_core(
        client, db, superuser_token_headers, tmp_path, monkeypatch, cloud_ips=()
    )
    _create_core(client, core)
    body = _summary(client, core["root"], core["headers"])
    assert body["core_readiness"]["state"] == "READY"
    states = {
        row["source"]: row for row in body["core_readiness"]["sources"]
    }
    assert states["CLOUD"]["state"] == "VALID_EMPTY"
    assert states["CLOUD"]["read_state"] == "VALID_EMPTY"
    assert states["CLOUD"]["source_records"] == 0
    assert states["CLOUD"]["source_addresses"] == 0


def test_input_summary_scope_pending_with_data_is_never_comparable(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _setup_core(client, db, superuser_token_headers, tmp_path, monkeypatch)
    body = _summary(client, core["root"], core["headers"])
    readiness = body["core_readiness"]
    assert readiness["state"] == "SCOPE_REQUIRED"
    assert [choice["state"] for choice in readiness["clouds"]] == ["PUBLISHED"]
    assert readiness["sources"] == []
    assert readiness["selection"] is None


def test_input_summary_reports_insufficient_coverage(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _setup_core(
        client,
        db,
        superuser_token_headers,
        tmp_path,
        monkeypatch,
        cloud_ips=("192.0.2.20",),
        complete=False,
    )
    _create_core(client, core)
    body = _summary(client, core["root"], core["headers"])
    readiness = body["core_readiness"]
    assert readiness["state"] == "INSUFFICIENT_COVERAGE"
    cloud = next(
        row for row in readiness["sources"] if row["source"] == "CLOUD"
    )
    assert cloud["state"] == "INSUFFICIENT_COVERAGE"
    assert cloud["read_state"] == "VALID_NONEMPTY"
    assert cloud["coverage_state"] == "INSUFFICIENT"
    assert readiness["can_generate"] is True


def test_input_summary_reports_expired_material(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, root, _upload_row = _apply_customer(
        client, superuser_token_headers, tmp_path, monkeypatch
    )
    project = db.get(Project, uuid.UUID(str(created["id"])))
    assert project is not None
    me = client.get(
        f"{settings.API_V1_STR}/users/me", headers=superuser_token_headers
    )
    assert me.status_code == 200, me.text
    now = get_datetime_utc()
    source = SourceInstance(
        project_id=project.id,
        tenant_id=project.tenant_id,
        capability_profile="assets-v1",
        instance_id="expiry-source",
        capset_id="expiry-source-assets",
        space_id="42",
        enabled=True,
        validated_fingerprint="e" * 64,
        data_access_enabled=True,
    )
    db.add(source)
    db.flush()
    sync = ExternalSync(
        source_id=source.id,
        project_id=project.id,
        actor_id=uuid.UUID(me.json()["id"]),
        idempotency_key=uuid.uuid4().hex,
        request_sha256="a" * 64,
        request={},
        fingerprint="b" * 64,
        token_sha256="c" * 64,
        status="SUCCEEDED",
        agent_run_id=uuid.uuid4().hex,
        agent_project_id="summary-expiry",
        retain_until=now - timedelta(minutes=1),
    )
    db.add(sync)
    db.flush()
    version = ExternalAssetVersion(
        sync_id=sync.id,
        source_id=source.id,
        domain="ip",
        space_id="42",
        instance_id=source.instance_id,
        capset_id=source.capset_id,
        status="RUNNING",
        record_count=1,
        expected_total=1,
        complete=True,
        filter={},
        fingerprint="d" * 64,
        fetched_at=now - timedelta(hours=2),
        published_at=now - timedelta(hours=2),
        retain_until=now - timedelta(minutes=1),
    )
    db.add(version)
    db.flush()
    db.add(
        ExternalAssetRecord(
            version_id=version.id,
            source_id="1",
            ip="192.0.2.20",
            canonical_ip="192.0.2.20",
            fields={},
        )
    )
    version.status = "PUBLISHED"
    db.add(version)
    db.commit()
    expired = _summary(client, root, superuser_token_headers)
    assert expired["core_readiness"]["state"] == "EXPIRED"
    assert expired["core_readiness"]["sources"] == []
    assert [choice["state"] for choice in expired["core_readiness"]["clouds"]] == [
        "EXPIRED"
    ]


def test_input_summary_degrades_to_metadata_unavailable_not_empty(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _setup_core(client, db, superuser_token_headers, tmp_path, monkeypatch)
    _create_core(client, core)
    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", unreadable)
    failed = _summary(client, core["root"], core["headers"])
    assert failed["core_readiness"]["state"] == "METADATA_UNAVAILABLE"
    assert (
        failed["core_readiness"]["reason_code"]
        == "netflow_artifact_integrity_failed"
    )
    assert failed["core_readiness"]["sources"] == []


def test_input_summary_netflow_absence_and_failures_do_not_gate_core(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _setup_core(client, db, superuser_token_headers, tmp_path, monkeypatch)
    _create_core(client, core)
    absent = _summary(client, core["root"], core["headers"])
    assert absent["core_readiness"]["state"] == "READY"
    assert absent["netflow"]["read_state"] == "READ"
    assert absent["netflow"]["dataset_count"] == 0

    def http_failure(_session: Any, _project: Any, _scope: Any = None) -> Any:
        raise HTTPException(
            status_code=403, detail={"code": "correlation_source_access_revoked"}
        )

    monkeypatch.setattr(
        "app.domain.netflow_processing.current_netflow", http_failure
    )
    failed_http = _summary(client, core["root"], core["headers"])
    assert failed_http["core_readiness"]["state"] == "READY"
    assert failed_http["netflow"]["read_state"] == "READ_FAILED"
    assert failed_http["netflow"]["error_status"] == 403
    assert (
        failed_http["netflow"]["error_code"]
        == "correlation_source_access_revoked"
    )
    assert failed_http["netflow"]["dataset_count"] == 0

    def unexpected_failure(
        _session: Any, _project: Any, _scope: Any = None
    ) -> Any:
        raise RuntimeError("raw internal detail")

    monkeypatch.setattr(
        "app.domain.netflow_processing.current_netflow", unexpected_failure
    )
    failed_other = _summary(client, core["root"], core["headers"])
    assert failed_other["core_readiness"]["state"] == "READY"
    assert failed_other["netflow"]["read_state"] == "READ_FAILED"
    assert failed_other["netflow"]["error_status"] is None
    assert failed_other["netflow"]["error_code"] == "netflow_summary_unavailable"
    assert "raw internal detail" not in str(failed_other)


def test_input_summary_netflow_current_success_with_newer_failed_attempt(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _setup_core(client, db, superuser_token_headers, tmp_path, monkeypatch)
    _create_core(client, core)
    monkeypatch.setattr(settings, "NETFLOW_ALLOW_TEST_FIXTURES", True)
    monkeypatch.setattr(settings, "GOVERNANCE_RUNNER_BUILD_VERSION", "summary-nf")
    control = ControlPlane(monkeypatch)
    project_id = str(core["project"].id)
    uploaded = _upload(
        client, core["headers"], project_id, (HEADER + VALID).encode()
    )
    assert uploaded.status_code == 201, uploaded.text
    setup: dict[str, Any] = {
        "root": core["root"],
        "headers": core["headers"],
        "control": control,
        "dataset_url": core["root"] + f"/netflow-datasets/{uploaded.json()['id']}",
    }
    context = client.post(
        setup["dataset_url"] + "/processing-contexts",
        headers=core["headers"] | {"Idempotency-Key": "summary-context"},
        json=context_request(
            network_namespace="summary-nf", collection_scope="edge-a"
        ),
    )
    assert context.status_code == 201, context.text
    setup["context_revision_id"] = context.json()["context_revision_id"]
    success = reserve(client, setup, key="summary-success")
    execute(db, setup, success["analysis_id"])

    later = _upload(
        client, core["headers"], project_id, (HEADER + INVALID).encode()
    )
    assert later.status_code == 201, later.text
    failed_setup = setup | {
        "dataset_url": core["root"] + f"/netflow-datasets/{later.json()['id']}",
        "context_revision_id": None,
    }
    later_context = client.post(
        failed_setup["dataset_url"] + "/processing-contexts",
        headers=core["headers"] | {"Idempotency-Key": "summary-later-context"},
        json=context_request(
            network_namespace="summary-nf", collection_scope="edge-a"
        ),
    )
    assert later_context.status_code == 201, later_context.text
    failed_setup["context_revision_id"] = later_context.json()[
        "context_revision_id"
    ]
    attempt = reserve(client, failed_setup, key="summary-failure")
    row = execute(db, failed_setup, attempt["analysis_id"])
    assert row.status == "FAILED"

    body = _summary(client, core["root"], core["headers"])
    assert body["core_readiness"]["state"] == "READY"
    netflow = body["netflow"]
    assert netflow["read_state"] == "READ"
    assert netflow["dataset_count"] == 2
    assert netflow["scope_id"] is not None
    assert [scope["collection_scope"] for scope in netflow["scopes"]] == ["edge-a"]
    assert netflow["current_analysis_id"] == success["analysis_id"]
    assert netflow["latest_attempt_status"] == "FAILED"
    assert netflow["latest_attempt_error_code"] is not None
