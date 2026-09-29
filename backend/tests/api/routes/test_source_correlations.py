"""Synthetic HTTP regressions: fixed sources, full sets, and current read gates."""
import io
import ipaddress
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook  # type: ignore[import-untyped]
from sqlalchemy import text
from sqlmodel import Session, delete

from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain import customer_ledger, source_correlations
from app.domain.external_asset_models import ExternalAssetRecord, ExternalAssetVersion, ExternalSync
from app.domain.models import SourceInstance
from app.domain.netflow_models import SourceCorrelationRevision
from tests.api.routes.test_netflow_datasets import _member, _project
from tests.utils.netflow_processing import published_analysis


def _post(client: TestClient, url: str, headers: dict[str, str], body: dict[str, Any], key: str | None = None) -> dict[str, Any]:
    response = client.post(url, headers={**headers, "Idempotency-Key": key or uuid.uuid4().hex}, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _get(client: TestClient, url: str, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    response = client.get(url, headers=headers, params=params)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    return response.json()


@pytest.fixture
def correlation(client: TestClient, db: Session, superuser_token_headers: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    ips = ["192.0.2.3", "192.0.2.5", "192.0.2.6", "192.0.2.7"] + [f"198.51.100.{n}" for n in range(1, 32)]
    raw = "IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n" + "".join(f"{ip},203.0.113.250,6,443,62000\n" for ip in ips)
    # A duplicate contributes once on the source side; the peer never joins the source set.
    raw += "192.0.2.7,192.0.2.7,6,443,62000\n192.0.2.7,203.0.113.250,17,440,53\n192.0.2.7,203.0.113.250,6,450,443\n192.0.2.7,203.0.113.250,6,451,443\n"
    setup = published_analysis(client, db, superuser_token_headers, tmp_path, monkeypatch, raw_text=raw)
    project, actor = setup["project"], setup["actor"]
    root = f"{settings.API_V1_STR}/projects/{project.id}"
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(list(customer_ledger.HEADERS))
    for number in (1, 4, 5, 7):
        sheet.append([f"192.0.2.{number}", 440, 450, "是", "example.net", "HTTPS", "Synthetic owner", "Synthetic department", "Synthetic port owner", "Synthetic department", number])
    # More than one evidence page for one address, not a sampled comparison list.
    for number in range(30):
        sheet.append(["192.0.2.7", 440, 450, "否", "", "", "Synthetic owner", "Synthetic department", "Synthetic port owner", "Synthetic department", number + 10])
    stream = io.BytesIO()
    book.save(stream)
    book.close()
    uploaded = client.post(root + "/customer-uploads", headers=superuser_token_headers, files={"file": ("synthetic.xlsx", stream.getvalue())})
    assert uploaded.status_code == 201, uploaded.text
    source = SourceInstance(project_id=project.id, tenant_id=project.tenant_id, capability_profile="assets-v1", instance_id="synthetic", capset_id="synthetic-assets", space_id="42", data_access_enabled=True)
    db.add(source)
    db.flush()
    now = get_datetime_utc()
    sync = ExternalSync(source_id=source.id, project_id=project.id, actor_id=actor.id, idempotency_key=uuid.uuid4().hex, request_sha256="a" * 64, request={}, fingerprint="b" * 64, token_sha256="c" * 64,
        status="SUCCEEDED", agent_run_id=uuid.uuid4().hex, agent_project_id="synthetic", retain_until=now + timedelta(days=2))
    db.add(sync)
    db.flush()
    versions = {}
    for domain, addresses in (("ip", (2, 4, 6)), ("port", (7,))):
        version = ExternalAssetVersion(sync_id=sync.id, source_id=source.id, domain=domain, space_id="42", instance_id=source.instance_id, capset_id=source.capset_id,
            status="RUNNING", record_count=len(addresses), expected_total=len(addresses), complete=True, filter={}, fingerprint="d" * 64, fetched_at=now, published_at=now, retain_until=now + timedelta(days=2))
        db.add(version)
        db.flush()
        for number in addresses:
            db.add(ExternalAssetRecord(version_id=version.id, source_id=str(9007199254740993 + number), ip=f"192.0.2.{number}", canonical_ip=f"192.0.2.{number}", fields={"protocol": "tcp", "port": 443, "banner": "", "service": None} if domain == "port" else {"status": "valid"}))
        db.flush()
        version.status = "PUBLISHED"
        db.add(version)
        db.flush()
        versions[domain] = version
    db.commit()
    body = {"network_namespace": setup["namespace"], "customer": {"upload_id": uploaded.json()["id"], "revision_id": None},
        "cloud": {"kind": "external_versions", "source_instance_id": str(source.id), "ip_version_id": str(versions["ip"].id), "port_version_id": str(versions["port"].id)}, "netflow": {"analysis_id": setup["analysis_id"]}}
    base = root + "/source-correlations"
    original = _post(client, base, superuser_token_headers, body, "synthetic-correlation")
    confirmed = _post(client, base + f"/{original['correlation_revision_id']}/scope-revisions", superuser_token_headers,
        {"expected_parent_id": original["correlation_revision_id"], "scope_state": "CONFIRMED", "evidence": "Synthetic exact selected input same-space evidence"}, "synthetic-confirmation")
    return {**setup, "base": base, "body": body, "original": original, "confirmed": confirmed, "source": source, "versions": versions, "now": now, "headers": superuser_token_headers}


def test_full_intersections_filters_order_evidence_services(client: TestClient, correlation: dict[str, Any]) -> None:
    c = correlation
    url = c["base"] + "/" + c["confirmed"]["correlation_revision_id"]
    summary = _get(client, url, c["headers"])
    assert summary["positive_intersections"] == {"CUSTOMER": 1, "CLOUD": 1, "NETFLOW": 32, "CUSTOMER+CLOUD": 1, "CUSTOMER+NETFLOW": 1, "CLOUD+NETFLOW": 1, "CUSTOMER+CLOUD+NETFLOW": 1}
    first = _get(client, url + "/addresses", c["headers"], limit=25)
    second = _get(client, url + "/addresses", c["headers"], skip=25, limit=25)
    assert first["count"] == second["count"] == 38
    rows = first["data"] + second["data"]
    assert [a["canonical_ip"] for a in rows] == sorted([a["canonical_ip"] for a in rows], key=lambda ip: (ipaddress.ip_address(ip).version, int(ipaddress.ip_address(ip))))
    assert "203.0.113.250" not in {a["canonical_ip"] for a in rows}
    unmatched = _get(client, url + "/addresses", c["headers"], unmatched_netflow=True, sort="ip_desc", limit=100)
    assert unmatched["count"] == 32
    assert all(a["resource_id"] is None and a["history_link"] is None for a in unmatched["data"])
    selected = _get(client, url + "/addresses", c["headers"], ip="::ffff:192.0.2.7", positive_sources="CUSTOMER,CLOUD,NETFLOW")
    assert selected["count"] == 1
    address = selected["data"][0]
    assert address["source_record_count"] == 5
    assert address["source_counts"] == {"CUSTOMER": 31, "CLOUD": 1, "NETFLOW": 5}
    detail = url + "/addresses/" + address["address_key"]
    assert _get(client, detail, c["headers"])["service_object_count"] == 4
    evidence = _get(client, detail + "/evidence", c["headers"], source="customer", limit=25, skip=25)
    assert evidence["count"] == evidence["retained_count"] == 31
    assert len(evidence["data"]) == 6 and evidence["omitted_count"] == 0
    cloud = _get(client, detail + "/evidence", c["headers"], source="cloud")["data"][0]
    assert cloud["domain"] == "port" and cloud["record_key"] == "9007199254741000"
    assert cloud["availability"]["service"] == "NULL" and cloud["availability"]["banner"] == "EMPTY" and cloud["availability"]["update_time"] == "MISSING"
    flows = _get(client, detail + "/evidence", c["headers"], source="netflow")
    assert flows["retained_count"] + flows["omitted_count"] == 5
    services = _get(client, detail + "/services", c["headers"], limit=100)
    flow_services = [s for s in services["data"] if s["source"] == "NETFLOW"]
    for row in flow_services:
        comparison = row["customer_comparisons"][0]
        assert comparison["port_relation"] == ("IN_RANGE" if row["local_port"] <= 450 else "OUT_OF_RANGE")
        assert comparison["protocol_relation"] == comparison["time_relation"] == "UNKNOWN"
        assert row["assessment"] == "INSUFFICIENT_EVIDENCE" and row["role_state"] == "UNKNOWN" and row["reachability"] == "NOT_VERIFIED"
    udp = next(s for s in flow_services if s["protocol_number"] == 17)
    assert udp["cloud_comparisons"][0]["protocol_relation"] == "DIFFERENT"
    assert udp["cloud_comparisons"][0]["time_relation"] == "UNKNOWN"


def test_unknown_scope_recovery_immutable_pins_and_revocation(client: TestClient, db: Session, correlation: dict[str, Any]) -> None:
    c = correlation
    old_url = c["base"] + "/" + c["original"]["correlation_revision_id"]
    isolated = _get(client, old_url + "/addresses", c["headers"], ip="192.0.2.7")
    assert isolated["count"] == 3
    assert {tuple(a["positive_sources"]) for a in isolated["data"]} == {("CUSTOMER",), ("CLOUD",), ("NETFLOW",)}
    assert _get(client, old_url, c["headers"])["positive_intersections"] is None
    assert _get(client, c["base"] + "/operations/synthetic-correlation", c["headers"])["correlation_revision_id"] == c["original"]["correlation_revision_id"]
    assert _get(client, old_url + "/scope-revisions/operations/synthetic-confirmation", c["headers"])["correlation_revision_id"] == c["confirmed"]["correlation_revision_id"]
    assert _post(client, c["base"], c["headers"], c["body"], "synthetic-correlation")["correlation_revision_id"] == c["original"]["correlation_revision_id"]
    conflict = client.post(c["base"], headers={**c["headers"], "Idempotency-Key": "synthetic-correlation"}, json={**c["body"], "cloud": None})
    assert conflict.status_code == 409
    before = db.get(SourceCorrelationRevision, uuid.UUID(c["original"]["correlation_revision_id"]))
    assert before is not None
    pins = before.pins
    current_url = c["base"] + "/" + c["confirmed"]["correlation_revision_id"]
    revoked = _post(client, current_url + "/scope-revisions", c["headers"], {"expected_parent_id": c["confirmed"]["correlation_revision_id"], "scope_state": "REVOKED", "evidence": "Synthetic correction"}, "synthetic-revoke")
    assert revoked["parent_id"] == c["confirmed"]["correlation_revision_id"]
    assert revoked["pins"] == pins
    assert client.get(current_url, headers=c["headers"]).status_code == 409
    recovered = _get(client, current_url + "/scope-revisions/operations/synthetic-revoke", c["headers"])
    assert recovered["correlation_revision_id"] == revoked["correlation_revision_id"]


@pytest.mark.parametrize("gate,expected", [("revoked", 403), ("expired", 410), ("purged", 409), ("space", 404)])
def test_all_combined_paths_recheck_source_gates(client: TestClient, db: Session, correlation: dict[str, Any], monkeypatch: pytest.MonkeyPatch, gate: str, expected: int) -> None:
    c = correlation
    url = c["base"] + "/" + c["confirmed"]["correlation_revision_id"]
    address = _get(client, url + "/addresses", c["headers"], ip="192.0.2.7")["data"][0]
    if gate == "revoked":
        c["source"].data_access_enabled = False
        db.add(c["source"])
    elif gate == "space":
        # Deliberate corruption injection; production immutability is not weakened.
        db.connection().execute(text("SET LOCAL session_replication_role = replica"))
        c["source"].space_id = "43"
        db.add(c["source"])
    elif gate == "expired":
        monkeypatch.setattr(source_correlations, "get_datetime_utc", lambda: c["now"] + timedelta(days=3))
    else:
        # Missing retained records must fail closed even after storage corruption.
        db.connection().execute(text("SET LOCAL session_replication_role = replica"))
        db.exec(delete(ExternalAssetRecord).where(ExternalAssetRecord.version_id == c["versions"]["port"].id))
    db.commit()
    detail = url + "/addresses/" + address["address_key"]
    for path in (url, url + "/addresses", detail, detail + "/services", detail + "/evidence?source=cloud", c["base"]):
        response = client.get(path, headers=c["headers"])
        assert response.status_code == expected, response.text
    # Correlation persistence contains identities/hashes, not copied source fields.
    stored = db.get(SourceCorrelationRevision, uuid.UUID(c["confirmed"]["correlation_revision_id"]))
    assert stored is not None
    assert "banner" not in str(stored.pins) and "192.0.2.7" not in str(stored.pins)


def test_project_roles_and_exact_input_scope(client: TestClient, correlation: dict[str, Any]) -> None:
    c = correlation
    viewer = _member(client, c["headers"], c["project_id"], ["viewer"])
    url = c["base"] + "/" + c["confirmed"]["correlation_revision_id"]
    assert _get(client, url, viewer)["correlation_revision_id"] == c["confirmed"]["correlation_revision_id"]
    denied = client.post(c["base"], headers={**viewer, "Idempotency-Key": "viewer"}, json=c["body"])
    assert denied.status_code in (403, 404)
    assert client.get(c["base"] + "/operations/synthetic-correlation", headers=viewer).status_code == 404
    other = _project(client, c["headers"])
    other_base = f"{settings.API_V1_STR}/projects/{other['id']}/source-correlations"
    assert client.get(other_base + "/" + c["confirmed"]["correlation_revision_id"], headers=c["headers"]).status_code == 404
    assert client.post(other_base, headers={**c["headers"], "Idempotency-Key": "cross"}, json=c["body"]).status_code == 404
    assert client.post(c["base"], headers={**c["headers"], "Idempotency-Key": "namespace"}, json={**c["body"], "network_namespace": "different"}).status_code == 404
    assert client.post(url + "/scope-revisions", headers={**viewer, "Idempotency-Key": "scope-viewer"}, json={"expected_parent_id": c["confirmed"]["correlation_revision_id"], "scope_state": "REVOKED", "evidence": "Synthetic"}).status_code in (403, 404)


def test_expired_rows_can_be_purged_without_correlation_foreign_keys(client: TestClient, db: Session, correlation: dict[str, Any]) -> None:
    c = correlation
    version = c["versions"]["port"]
    # Move only this synthetic immutable receipt's clock for retention testing.
    db.connection().execute(text("SET LOCAL session_replication_role = replica"))
    version.retain_until = get_datetime_utc() - timedelta(seconds=1)
    db.add(version)
    db.commit()
    # Normal trigger/FK enforcement is restored for the actual purge.
    db.exec(delete(ExternalAssetRecord).where(ExternalAssetRecord.version_id == version.id))
    db.commit()
    url = c["base"] + "/" + c["confirmed"]["correlation_revision_id"]
    response = client.get(url, headers=c["headers"])
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "correlation_source_expired"


def test_netflow_valid_empty_is_not_missing_input(client: TestClient, db: Session, superuser_token_headers: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = published_analysis(client, db, superuser_token_headers, tmp_path, monkeypatch,
        raw_text="IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n")
    base = f"{settings.API_V1_STR}/projects/{c['project_id']}/source-correlations"
    created = _post(client, base, superuser_token_headers, {"network_namespace": c["namespace"], "netflow": {"analysis_id": c["analysis_id"]}})
    summary = _get(client, base + "/" + created["correlation_revision_id"], superuser_token_headers)
    states = {state["source"]: state for state in summary["sources"]}
    assert states["NETFLOW"]["read_state"] == "VALID_EMPTY"
    assert states["NETFLOW"]["source_records"] == states["NETFLOW"]["raw_records"] == 0
    assert states["NETFLOW"]["coverage_state"] == "UNKNOWN"
    assert states["CUSTOMER"]["read_state"] == states["CLOUD"]["read_state"] == "NOT_PROVIDED"
    assert states["CUSTOMER"]["source_records"] is None
    assert summary["total_addresses"] == 0


def test_numeric_families_mapped_equivalence_and_stable_address_keys(client: TestClient, db: Session, superuser_token_headers: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = "IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
    raw += "".join(f"{ip},203.0.113.8,6,443,53000\n" for ip in ("2001:db8::10", "192.0.2.10", "::ffff:192.0.2.2", "2001:db8::2", "192.0.2.2"))
    c = published_analysis(client, db, superuser_token_headers, tmp_path, monkeypatch, raw_text=raw)
    base = f"{settings.API_V1_STR}/projects/{c['project_id']}/source-correlations"
    body = {"network_namespace": c["namespace"], "netflow": {"analysis_id": c["analysis_id"]}}
    revisions = [_post(client, base, superuser_token_headers, body) for _ in range(2)]
    pages = [_get(client, base + "/" + r["correlation_revision_id"] + "/addresses", superuser_token_headers) for r in revisions]
    assert [r["canonical_ip"] for r in pages[0]["data"]] == ["192.0.2.2", "192.0.2.10", "2001:db8::2", "2001:db8::10"]
    assert [r["address_key"] for r in pages[0]["data"]] == [r["address_key"] for r in pages[1]["data"]]
    assert pages[0]["data"][0]["source_record_count"] == 2
    url = base + "/" + revisions[0]["correlation_revision_id"] + "/addresses"
    assert client.get(url, headers=superuser_token_headers, params={"ip": "fe80::1%eth0"}).status_code == 422
