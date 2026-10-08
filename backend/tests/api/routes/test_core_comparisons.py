"""Real PostgreSQL HTTP regressions for V2 core comparison and optional NetFlow evidence."""

from __future__ import annotations

import io
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook  # type: ignore[import-untyped]
from sqlmodel import Session, select

from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain import customer_ledger
from app.domain.external_asset_models import (
    ExternalAssetRecord,
    ExternalAssetVersion,
    ExternalSync,
)
from app.domain.models import NetFlowDataset, Project, SourceInstance
from app.domain.netflow_models import NetFlowAnalysis, NetFlowContextRevision
from tests.api.routes.test_netflow_datasets import _project, _upload
from tests.utils.netflow_processing import (
    ControlPlane,
    context_request,
    execute,
    reserve,
)


def _workbook(ips: tuple[str, ...]) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(list(customer_ledger.HEADERS))
    for index, ip in enumerate(ips, 1):
        sheet.append([ip, 443, 443, "是", "example.test", "HTTPS", "owner", "dept", "owner", "dept", index])
    data = io.BytesIO()
    book.save(data)
    book.close()
    return data.getvalue()


def _post(client: TestClient, url: str, headers: dict[str, str], body: dict[str, Any], key: str) -> dict[str, Any]:
    response = client.post(url, headers=headers | {"Idempotency-Key": key}, json=body)
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _setup_core(client: TestClient, db: Session, headers: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project_public = _project(client, headers)
    project_id = uuid.UUID(str(project_public["id"]))
    root = f"{settings.API_V1_STR}/projects/{project_id}"
    upload = client.post(root + "/customer-uploads", headers=headers, files={"file": ("core.xlsx", _workbook(("192.0.2.10", "192.0.2.20")))})
    assert upload.status_code == 201, upload.text
    selected = client.post(root + f"/customer-uploads/{upload.json()['id']}/select", headers=headers)
    assert selected.status_code == 200, selected.text
    project = db.get(Project, project_id)
    assert project is not None
    me = client.get(f"{settings.API_V1_STR}/users/me", headers=headers)
    assert me.status_code == 200, me.text
    now = get_datetime_utc()
    source = SourceInstance(project_id=project.id, tenant_id=project.tenant_id, capability_profile="assets-v1", instance_id="synthetic-core", capset_id="synthetic-core-assets", space_id="42", data_access_enabled=True)
    db.add(source)
    db.flush()
    sync = ExternalSync(source_id=source.id, project_id=project.id, actor_id=uuid.UUID(me.json()["id"]), idempotency_key=uuid.uuid4().hex, request_sha256="a" * 64, request={}, fingerprint="b" * 64, token_sha256="c" * 64, status="SUCCEEDED", agent_run_id=uuid.uuid4().hex, agent_project_id="synthetic-core", retain_until=now + timedelta(days=2))
    db.add(sync)
    db.flush()
    version = ExternalAssetVersion(sync_id=sync.id, source_id=source.id, domain="ip", space_id="42", instance_id=source.instance_id, capset_id=source.capset_id, status="RUNNING", record_count=2, expected_total=2, complete=True, filter={}, fingerprint="d" * 64, fetched_at=now, published_at=now, retain_until=now + timedelta(days=2))
    db.add(version)
    db.flush()
    for index, ip in enumerate(("192.0.2.20", "192.0.2.30"), 1):
        db.add(ExternalAssetRecord(version_id=version.id, source_id=str(index), ip=ip, canonical_ip=ip, fields={"status": "valid"}))
    version.status = "PUBLISHED"
    db.add(version)
    db.commit()
    return {"project": project, "root": root, "headers": headers, "source": source, "version": version}


def _create_core(client: TestClient, core: dict[str, Any]) -> dict[str, Any]:
    url = core["root"] + "/comparison-results"
    ready = client.get(url + "/readiness", headers=core["headers"], params={"source_instance_id": str(core["source"].id), "network_namespace": "synthetic-core"})
    assert ready.status_code == 200, ready.text
    payload = ready.json()
    assert payload["state"] == "SCOPE_CONFIRMATION_REQUIRED", payload
    result = _post(client, url, core["headers"], {"selection": payload["selection"], "expected_input_sha256": payload["input_sha256"], "expected_current_result_id": payload["expected_current_result_id"], "scope_evidence": "Synthetic administrator confirms this exact C/A space."}, "core-create")
    return result


def test_two_source_core_http_is_fixed_and_has_no_netflow(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _setup_core(client, db, superuser_token_headers, tmp_path, monkeypatch)
    result = _create_core(client, core)
    base = core["root"] + f"/comparison-results/{result['id']}"
    summary = client.get(base + "/summary", headers=core["headers"])
    assert summary.status_code == 200, summary.text
    assert {key: summary.json()[key] for key in ("total_addresses", "both", "customer_only", "cloud_only")} == {"total_addresses": 3, "both": 1, "customer_only": 1, "cloud_only": 1}
    addresses = client.get(base + "/addresses", headers=core["headers"], params={"limit": 2})
    assert addresses.status_code == 200, addresses.text
    assert addresses.json()["count"] == addresses.json()["total_addresses"] == 3
    assert [entry["canonical_ip"] for entry in addresses.json()["data"]] == ["192.0.2.10", "192.0.2.20"]
    fixed = client.get(base + "/summary", headers=core["headers"])
    assert fixed.json()["pins"] == summary.json()["pins"]
    project_id = core["project"].id
    assert db.exec(select(NetFlowDataset).where(NetFlowDataset.project_id == project_id)).all() == []
    assert db.exec(select(NetFlowContextRevision).where(NetFlowContextRevision.project_id == project_id)).all() == []
    assert db.exec(select(NetFlowAnalysis).where(NetFlowAnalysis.project_id == project_id)).all() == []


def test_supplement_expiry_and_context_revocation_do_not_change_core(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _setup_core(client, db, superuser_token_headers, tmp_path, monkeypatch)
    result = _create_core(client, core)
    raw = "IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n192.0.2.20,203.0.113.1,6,50000,443\n192.0.2.40,203.0.113.1,6,50001,443\n"
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "NETFLOW_ALLOW_TEST_FIXTURES", True)
    monkeypatch.setattr(settings, "GOVERNANCE_RUNNER_BUILD_VERSION", "synthetic-core")
    control = ControlPlane(monkeypatch)
    dataset = _upload(client, core["headers"], str(core["project"].id), raw.encode())
    assert dataset.status_code == 201, dataset.text
    dataset_url = core["root"] + f"/netflow-datasets/{dataset.json()['id']}"
    context = _post(client, dataset_url + "/processing-contexts", core["headers"], context_request(network_namespace="synthetic-core"), "core-nf-context")
    setup = {"dataset_url": dataset_url, "context_revision_id": context["context_revision_id"], "headers": core["headers"], "control": control}
    queued = reserve(client, setup, key="core-nf-analysis")
    execute(db, setup, queued["analysis_id"])
    until = get_datetime_utc() + timedelta(minutes=5)
    binding = _post(client, core["root"] + f"/comparison-results/{result['id']}/supplements", core["headers"], {"analysis_id": queued["analysis_id"], "valid_until": until.isoformat(), "scope_evidence": "Administrator confirms optional synthetic N scope.", "expected_binding_id": None}, "core-supplement")
    summary_url = core["root"] + f"/comparison-results/{result['id']}/summary"
    assert client.get(summary_url, headers=core["headers"]).json()["total_addresses"] == 3
    addresses_url = core["root"] + f"/comparison-results/{result['id']}/supplements/{binding['id']}/addresses"
    supplemental = client.get(addresses_url, headers=core["headers"], params={"only_supplemental": True})
    assert supplemental.status_code == 200, supplemental.text
    assert [entry["canonical_ip"] for entry in supplemental.json()["data"]] == ["192.0.2.40"]

    # Build a fixed V1 correlation with this same N before revoking its Context.
    selection = result["selection"] | {"netflow": {"analysis_id": queued["analysis_id"]}}
    v1 = _post(client, core["root"] + "/source-correlations", core["headers"], selection, "core-v1-n")
    confirmed = _post(client, core["root"] + f"/source-correlations/{v1['correlation_revision_id']}/scope-revisions", core["headers"], {"expected_parent_id": v1["correlation_revision_id"], "scope_state": "CONFIRMED", "evidence": "Synthetic fixed V1 N scope."}, "core-v1-n-confirm")

    real_now = get_datetime_utc
    monkeypatch.setattr("app.domain.comparison_results.get_datetime_utc", lambda: until + timedelta(seconds=1))
    expired = client.get(core["root"] + f"/comparison-results/{result['id']}/supplements/{binding['id']}", headers=core["headers"])
    assert expired.status_code == 200 and expired.json()["state"] == "EXPIRED"
    assert client.get(addresses_url, headers=core["headers"], params={"only_supplemental": True}).status_code == 410
    assert client.get(summary_url, headers=core["headers"]).status_code == 200
    monkeypatch.setattr("app.domain.comparison_results.get_datetime_utc", real_now)

    revoked = client.post(dataset_url + "/processing-contexts", headers=core["headers"] | {"Idempotency-Key": "core-nf-revoke"}, json=context_request(context["context_revision_id"], state="REVOKED", network_namespace="synthetic-core"))
    assert revoked.status_code == 201, revoked.text
    unreadable = client.get(core["root"] + f"/comparison-results/{result['id']}/supplements/{binding['id']}", headers=core["headers"])
    assert unreadable.status_code == 200 and unreadable.json()["state"] == "UNREADABLE"
    assert client.get(addresses_url, headers=core["headers"], params={"only_supplemental": True}).status_code == 409
    assert client.get(summary_url, headers=core["headers"]).status_code == 200
    legacy = client.get(core["root"] + f"/source-correlations/{confirmed['correlation_revision_id']}", headers=core["headers"])
    assert legacy.status_code == 409 and legacy.json()["detail"]["code"] == "netflow_context_revoked"
