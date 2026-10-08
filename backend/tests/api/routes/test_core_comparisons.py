"""Real PostgreSQL HTTP regressions for V2 core comparison and optional NetFlow evidence."""

from __future__ import annotations

import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook  # type: ignore[import-untyped]
from sqlmodel import Session, select

from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain import customer_ledger
from app.domain.comparison_models import CoreComparisonResult
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
        sheet.append(
            [
                ip,
                443,
                443,
                "是",
                "example.test",
                "HTTPS",
                "owner",
                "dept",
                "owner",
                "dept",
                index,
            ]
        )
    data = io.BytesIO()
    book.save(data)
    book.close()
    return data.getvalue()


def _post(
    client: TestClient,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    key: str,
) -> dict[str, Any]:
    response = client.post(url, headers=headers | {"Idempotency-Key": key}, json=body)
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _setup_core(
    client: TestClient,
    db: Session,
    headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cloud_ips: tuple[str, ...] = ("192.0.2.20", "192.0.2.30"),
    complete: bool = True,
) -> dict[str, Any]:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project_public = _project(client, headers)
    project_id = uuid.UUID(str(project_public["id"]))
    root = f"{settings.API_V1_STR}/projects/{project_id}"
    upload = client.post(
        root + "/customer-uploads",
        headers=headers,
        files={"file": ("core.xlsx", _workbook(("192.0.2.10", "192.0.2.20")))},
    )
    assert upload.status_code == 201, upload.text
    selected = client.post(
        root + f"/customer-uploads/{upload.json()['id']}/select", headers=headers
    )
    assert selected.status_code == 200, selected.text
    project = db.get(Project, project_id)
    assert project is not None
    me = client.get(f"{settings.API_V1_STR}/users/me", headers=headers)
    assert me.status_code == 200, me.text
    now = get_datetime_utc()
    source = SourceInstance(
        project_id=project.id,
        tenant_id=project.tenant_id,
        capability_profile="assets-v1",
        instance_id="synthetic-core",
        capset_id="synthetic-core-assets",
        space_id="42",
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
        agent_project_id="synthetic-core",
        retain_until=now + timedelta(days=2),
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
        record_count=len(cloud_ips),
        expected_total=len(cloud_ips),
        complete=True,
        filter={} if complete else {"ip": "192.0.2.20"},
        fingerprint="d" * 64,
        fetched_at=now,
        published_at=now,
        retain_until=now + timedelta(days=2),
    )
    db.add(version)
    db.flush()
    for index, ip in enumerate(cloud_ips, 1):
        db.add(
            ExternalAssetRecord(
                version_id=version.id,
                source_id=str(index),
                ip=ip,
                canonical_ip=ip,
                fields={"status": "valid"},
            )
        )
    version.status = "PUBLISHED"
    db.add(version)
    db.commit()
    return {
        "project": project,
        "root": root,
        "headers": headers,
        "source": source,
        "version": version,
    }


def _create_core(client: TestClient, core: dict[str, Any]) -> dict[str, Any]:
    url = core["root"] + "/comparison-results"
    ready = client.get(
        url + "/readiness",
        headers=core["headers"],
        params={
            "source_instance_id": str(core["source"].id),
            "network_namespace": "synthetic-core",
        },
    )
    assert ready.status_code == 200, ready.text
    payload = ready.json()
    assert payload["state"] == "SCOPE_CONFIRMATION_REQUIRED", payload
    result = _post(
        client,
        url,
        core["headers"],
        {
            "selection": payload["selection"],
            "expected_input_sha256": payload["input_sha256"],
            "expected_current_result_id": payload["expected_current_result_id"],
            "scope_evidence": "Synthetic administrator confirms this exact C/A space.",
        },
        "core-create",
    )
    return result


def test_two_source_core_http_is_fixed_and_has_no_netflow(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _setup_core(client, db, superuser_token_headers, tmp_path, monkeypatch)
    result = _create_core(client, core)
    base = core["root"] + f"/comparison-results/{result['id']}"
    summary = client.get(base + "/summary", headers=core["headers"])
    assert summary.status_code == 200, summary.text
    assert {
        key: summary.json()[key]
        for key in ("total_addresses", "both", "customer_only", "cloud_only")
    } == {"total_addresses": 3, "both": 1, "customer_only": 1, "cloud_only": 1}
    addresses = client.get(
        base + "/addresses", headers=core["headers"], params={"limit": 2}
    )
    assert addresses.status_code == 200, addresses.text
    assert addresses.json()["count"] == addresses.json()["total_addresses"] == 3
    assert [entry["canonical_ip"] for entry in addresses.json()["data"]] == [
        "192.0.2.10",
        "192.0.2.20",
    ]
    fixed = client.get(base + "/summary", headers=core["headers"])
    assert fixed.json()["pins"] == summary.json()["pins"]
    project_id = core["project"].id
    assert (
        db.exec(
            select(NetFlowDataset).where(NetFlowDataset.project_id == project_id)
        ).all()
        == []
    )
    assert (
        db.exec(
            select(NetFlowContextRevision).where(
                NetFlowContextRevision.project_id == project_id
            )
        ).all()
        == []
    )
    assert (
        db.exec(
            select(NetFlowAnalysis).where(NetFlowAnalysis.project_id == project_id)
        ).all()
        == []
    )


def test_supplement_expiry_and_context_revocation_do_not_change_core(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    context = _post(
        client,
        dataset_url + "/processing-contexts",
        core["headers"],
        context_request(network_namespace="synthetic-core"),
        "core-nf-context",
    )
    setup = {
        "dataset_url": dataset_url,
        "context_revision_id": context["context_revision_id"],
        "headers": core["headers"],
        "control": control,
    }
    queued = reserve(client, setup, key="core-nf-analysis")
    execute(db, setup, queued["analysis_id"])
    until = get_datetime_utc() + timedelta(minutes=5)
    binding = _post(
        client,
        core["root"] + f"/comparison-results/{result['id']}/supplements",
        core["headers"],
        {
            "analysis_id": queued["analysis_id"],
            "valid_until": until.isoformat(),
            "scope_evidence": "Administrator confirms optional synthetic N scope.",
            "expected_binding_id": None,
        },
        "core-supplement",
    )
    summary_url = core["root"] + f"/comparison-results/{result['id']}/summary"
    assert (
        client.get(summary_url, headers=core["headers"]).json()["total_addresses"] == 3
    )
    addresses_url = (
        core["root"]
        + f"/comparison-results/{result['id']}/supplements/{binding['id']}/addresses"
    )
    supplemental = client.get(
        addresses_url, headers=core["headers"], params={"only_supplemental": True}
    )
    assert supplemental.status_code == 200, supplemental.text
    assert [entry["canonical_ip"] for entry in supplemental.json()["data"]] == [
        "192.0.2.40"
    ]

    # Build a fixed V1 correlation with this same N before revoking its Context.
    selection = result["selection"] | {
        "netflow": {"analysis_id": queued["analysis_id"]}
    }
    v1 = _post(
        client,
        core["root"] + "/source-correlations",
        core["headers"],
        selection,
        "core-v1-n",
    )
    confirmed = _post(
        client,
        core["root"]
        + f"/source-correlations/{v1['correlation_revision_id']}/scope-revisions",
        core["headers"],
        {
            "expected_parent_id": v1["correlation_revision_id"],
            "scope_state": "CONFIRMED",
            "evidence": "Synthetic fixed V1 N scope.",
        },
        "core-v1-n-confirm",
    )

    real_now = get_datetime_utc
    monkeypatch.setattr(
        "app.domain.comparison_results.get_datetime_utc",
        lambda: until + timedelta(seconds=1),
    )
    expired = client.get(
        core["root"]
        + f"/comparison-results/{result['id']}/supplements/{binding['id']}",
        headers=core["headers"],
    )
    assert expired.status_code == 200 and expired.json()["state"] == "EXPIRED"
    assert (
        client.get(
            addresses_url, headers=core["headers"], params={"only_supplemental": True}
        ).status_code
        == 410
    )
    assert client.get(summary_url, headers=core["headers"]).status_code == 200
    assert (
        client.get(
            core["root"] + f"/netflow-analyses/{queued['analysis_id']}",
            headers=core["headers"],
        ).status_code
        == 200
    )
    monkeypatch.setattr("app.domain.comparison_results.get_datetime_utc", real_now)

    revoked = client.post(
        dataset_url + "/processing-contexts",
        headers=core["headers"] | {"Idempotency-Key": "core-nf-revoke"},
        json=context_request(
            context["context_revision_id"],
            state="REVOKED",
            network_namespace="synthetic-core",
        ),
    )
    assert revoked.status_code == 201, revoked.text
    unreadable = client.get(
        core["root"]
        + f"/comparison-results/{result['id']}/supplements/{binding['id']}",
        headers=core["headers"],
    )
    assert unreadable.status_code == 200 and unreadable.json()["state"] == "UNREADABLE"
    assert (
        client.get(
            addresses_url, headers=core["headers"], params={"only_supplemental": True}
        ).status_code
        == 409
    )
    assert client.get(summary_url, headers=core["headers"]).status_code == 200
    legacy = client.get(
        core["root"] + f"/source-correlations/{confirmed['correlation_revision_id']}",
        headers=core["headers"],
    )
    assert (
        legacy.status_code == 409
        and legacy.json()["detail"]["code"] == "netflow_context_revoked"
    )
    removed = _post(
        client,
        core["root"] + f"/comparison-results/{result['id']}/supplements",
        core["headers"],
        {"analysis_id": None, "expected_binding_id": binding["id"]},
        "core-supplement-remove",
    )
    assert removed["state"] == "REMOVED"
    fixed = client.get(summary_url, headers=core["headers"]).json()
    assert (
        fixed["total_addresses"],
        fixed["both"],
        fixed["customer_only"],
        fixed["cloud_only"],
    ) == (3, 1, 1, 1)


def test_failed_attempt_history_does_not_replace_regular_current(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _setup_core(client, db, superuser_token_headers, tmp_path, monkeypatch)
    regular = _create_core(client, core)
    endpoint = core["root"] + "/comparison-results"
    body = {
        "selection": regular["selection"],
        "scope_confirmation_id": regular["scope_confirmation_id"],
        "expected_input_sha256": regular["input_sha256"],
        "expected_current_result_id": None,
    }

    def stale(number: int) -> tuple[int, dict[str, Any]]:
        response = client.post(
            endpoint,
            headers=core["headers"] | {"Idempotency-Key": f"core-stale-{number}"},
            json=body,
        )
        return response.status_code, cast(dict[str, Any], response.json())

    with ThreadPoolExecutor(max_workers=8) as pool:
        failures = list(pool.map(stale, range(101)))
    assert all(
        status == 409 and value["detail"]["code"] == "comparison_publish_conflict"
        for status, value in failures
    )
    custom_body = {
        **body,
        "purpose": "custom",
        "expected_current_result_id": regular["id"],
    }
    _post(client, endpoint, core["headers"], custom_body, "core-later-custom")
    with ThreadPoolExecutor(max_workers=8) as pool:
        customs = list(
            pool.map(
                lambda number: _post(
                    client,
                    endpoint,
                    core["headers"],
                    custom_body,
                    f"core-custom-{number}",
                ),
                range(101),
            )
        )
    assert len({value["id"] for value in customs}) == 101
    current = client.get(endpoint + "/current", headers=core["headers"])
    assert (
        current.status_code == 200 and current.json()["result"]["id"] == regular["id"]
    )
    assert current.json()["latest_attempt"]["status"] == "FAILED"
    history = client.get(
        endpoint + "/history", headers=core["headers"], params={"limit": 100}
    )
    assert history.status_code == 200 and history.json()["count"] == 103
    second = client.get(
        endpoint + "/history",
        headers=core["headers"],
        params={"skip": 100, "limit": 100},
    )
    assert second.status_code == 200 and len(second.json()["data"]) == 3
    rows = db.exec(
        select(CoreComparisonResult).where(
            CoreComparisonResult.project_id == core["project"].id
        )
    ).all()
    assert sum(row.status == "PUBLISHED" for row in rows) == 103
    assert sum(row.status == "FAILED" for row in rows) == 101


def test_concurrent_compare_create_uses_cas_and_same_key_recovery(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _setup_core(client, db, superuser_token_headers, tmp_path, monkeypatch)
    endpoint = core["root"] + "/comparison-results"
    ready = client.get(
        endpoint + "/readiness",
        headers=core["headers"],
        params={
            "source_instance_id": str(core["source"].id),
            "network_namespace": "synthetic-core",
        },
    )
    assert ready.status_code == 200
    body = {
        "selection": ready.json()["selection"],
        "expected_input_sha256": ready.json()["input_sha256"],
        "expected_current_result_id": None,
        "scope_evidence": "Concurrent exact-scope confirmation.",
    }
    barrier = Barrier(2)

    def post(key: str) -> tuple[int, dict[str, Any]]:
        barrier.wait()
        response = client.post(
            endpoint, headers=core["headers"] | {"Idempotency-Key": key}, json=body
        )
        return response.status_code, cast(dict[str, Any], response.json())

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(post, ("core-cas-a", "core-cas-b")))
    assert sorted([first[0], second[0]]) == [201, 409]
    winner = first[1] if first[0] == 201 else second[1]
    assert (
        client.get(endpoint + "/current", headers=core["headers"]).json()["result"][
            "id"
        ]
        == winner["id"]
    )

    replay_body = {
        **body,
        "expected_current_result_id": winner["id"],
        "purpose": "custom",
    }
    replay_barrier = Barrier(2)

    def replay(_: int) -> tuple[int, dict[str, Any]]:
        replay_barrier.wait()
        response = client.post(
            endpoint,
            headers=core["headers"] | {"Idempotency-Key": "core-same-key"},
            json=replay_body,
        )
        return response.status_code, cast(dict[str, Any], response.json())

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(replay, range(2)))
    assert [status for status, _value in replies] == [201, 201]
    assert replies[0][1]["id"] == replies[1][1]["id"]
    recovered = client.get(
        endpoint + "/operations/core-same-key", headers=core["headers"]
    )
    assert (
        recovered.status_code == 200
        and recovered.json()["result"]["id"] == replies[0][1]["id"]
    )
    rows = db.exec(
        select(CoreComparisonResult).where(
            CoreComparisonResult.project_id == core["project"].id
        )
    ).all()
    assert sum(row.status == "PUBLISHED" for row in rows) == 2
    assert sum(row.status == "FAILED" for row in rows) == 1
    assert (
        client.get(endpoint + "/current", headers=core["headers"]).json()["result"][
            "id"
        ]
        == winner["id"]
    )


@pytest.mark.parametrize("complete,cloud_ips", [(True, ()), (False, ("192.0.2.20",))])
def test_core_distinguishes_empty_and_partial_coverage(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    complete: bool,
    cloud_ips: tuple[str, ...],
) -> None:
    core = _setup_core(
        client,
        db,
        superuser_token_headers,
        tmp_path,
        monkeypatch,
        cloud_ips=cloud_ips,
        complete=complete,
    )
    result = _create_core(client, core)
    base = core["root"] + f"/comparison-results/{result['id']}"
    summary = client.get(base + "/summary", headers=core["headers"])
    assert summary.status_code == 200, summary.text
    value = summary.json()
    assert value["total_addresses"] == 2
    if complete:
        assert (value["both"], value["customer_only"], value["cloud_only"]) == (0, 2, 0)
    else:
        assert (value["both"], value["customer_only"], value["cloud_only"]) == (
            None,
            None,
            None,
        )
        assert value["comparison_state"] == "INSUFFICIENT_COVERAGE"
        assert (
            client.get(
                base + "/addresses?classification=both", headers=core["headers"]
            ).status_code
            == 422
        )
        rows = client.get(base + "/addresses", headers=core["headers"]).json()["data"]
        assert all(row["classification"] is None for row in rows)


def test_current_input_update_permissions_integrity_and_unsafe_downgrade(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from fastapi import HTTPException

    from app.domain import comparison_results
    from tests.api.routes.test_customer_uploads import _create_member

    core = _setup_core(client, db, superuser_token_headers, tmp_path, monkeypatch)
    result = _create_core(client, core)
    endpoint = core["root"] + "/comparison-results"
    base = endpoint + "/" + result["id"]
    original = client.get(base + "/summary", headers=core["headers"]).json()
    viewer = _create_member(
        client, core["headers"], project_id=str(core["project"].id), roles=["viewer"]
    )
    assert client.get(base + "/summary", headers=viewer).status_code == 200
    current = client.get(endpoint + "/current", headers=viewer).json()
    assert current["readiness"]["can_write"] is False
    payload = {
        "selection": result["selection"],
        "scope_confirmation_id": result["scope_confirmation_id"],
        "expected_input_sha256": result["input_sha256"],
        "expected_current_result_id": result["id"],
    }
    assert (
        client.post(
            endpoint, headers=viewer | {"Idempotency-Key": "viewer"}, json=payload
        ).status_code
        == 403
    )
    other = _project(client, core["headers"])
    assert (
        client.get(
            f"{settings.API_V1_STR}/projects/{other['id']}/comparison-results/{result['id']}/summary",
            headers=core["headers"],
        ).status_code
        == 404
    )
    uploaded = client.post(
        core["root"] + "/customer-uploads",
        headers=core["headers"],
        files={"file": ("changed.xlsx", _workbook(("192.0.2.10", "192.0.2.50")))},
    )
    assert uploaded.status_code == 201
    before = client.get(
        core["root"] + "/customer-ledger", headers=core["headers"]
    ).json()
    _post(
        client,
        core["root"] + "/customer-ledger/replacements",
        core["headers"],
        {
            "candidate_upload_id": uploaded.json()["id"],
            "expected_upload_id": before["current_upload_id"],
            "expected_revision_id": before["current_revision_id"],
            "expected_profile_id": before["current_profile_id"],
        },
        "new-input",
    )
    assert (
        client.get(base + "/updates", headers=core["headers"]).json()["state"]
        == "UPDATED"
    )
    assert client.get(base + "/summary", headers=core["headers"]).json() == original
    assert (
        client.post(
            endpoint,
            headers=core["headers"] | {"Idempotency-Key": "stale-input"},
            json=payload,
        ).status_code
        == 409
    )
    assert (
        client.get(endpoint + "/current", headers=core["headers"]).json()["result"][
            "id"
        ]
        == result["id"]
    )
    with monkeypatch.context() as patch:

        def damaged(*_args: Any, **_kwargs: Any) -> Any:
            raise HTTPException(
                409, detail={"code": "netflow_artifact_integrity_failed"}
            )

        patch.setattr(comparison_results, "_read", damaged)
        rejected = client.get(endpoint + "/current", headers=core["headers"])
        assert rejected.status_code == 409, rejected.text
    migration = importlib.import_module(
        "app.alembic.versions.cp2920000001_add_core_comparison_results"
    )
    with Operations.context(MigrationContext.configure(db.connection())):
        with pytest.raises(RuntimeError, match="Cannot remove immutable core"):
            migration.downgrade()
    db.rollback()
    assert client.get(base + "/summary", headers=core["headers"]).json() == original
    assert (
        client.post(core["root"] + "/archive", headers=core["headers"]).status_code
        == 200
    )
    assert (
        client.post(
            endpoint,
            headers=core["headers"] | {"Idempotency-Key": "archived"},
            json=payload,
        ).status_code
        == 409
    )
    assert client.get(base + "/summary", headers=core["headers"]).status_code == 200
