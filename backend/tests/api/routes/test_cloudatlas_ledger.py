import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.domain.models import GovernanceRun
from tests.api.routes.test_ip_source_comparison import comparison_run as comparison_run


@pytest.mark.parametrize("comparison_run", ["absent"], indirect=True)
def test_native_rows_versions_and_scoped_profile(
    comparison_run: GovernanceRun,
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    root = f"/api/v1/projects/{comparison_run.project_id}/cloudatlas-ledger"
    headers = superuser_token_headers
    response = client.get(root, headers=headers)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["governance_run_id"] == str(comparison_run.id)
    assert page["count"] == page["total_records"] > 0
    assert page["revision"] == 0
    row = page["data"][0]
    params = {
        "snapshot_id": page["snapshot_id"],
        "revision": 0,
        "ip": row["canonical_ip"],
    }
    profile = client.get(root + "/profile", headers=headers, params=params)
    assert profile.status_code == 200, profile.text
    assert profile.json()["resource_id"] is None
    assert profile.json()["association"] == "UNKNOWN"
    key = str(uuid.uuid4())
    body = {
        "snapshot_id": page["snapshot_id"],
        "expected_revision": 0,
        "kind": "management",
        "observation_id": row["observation_id"],
        "tags": ["关注对象"],
        "followed": True,
        "reason": "核对来源记录",
    }
    saved = client.post(
        root + "/revisions", headers={**headers, "Idempotency-Key": key}, json=body
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["revision"] == 1
    replay = client.post(
        root + "/revisions", headers={**headers, "Idempotency-Key": key}, json=body
    )
    assert replay.json()["id"] == saved.json()["id"]
    assert (
        client.get(root + "/operations/" + key, headers=headers).json()["id"]
        == saved.json()["id"]
    )
    changed = client.post(
        root + "/revisions",
        headers={**headers, "Idempotency-Key": key},
        json={**body, "followed": False},
    )
    assert changed.status_code == 409
    historic = client.get(
        root,
        headers=headers,
        params={"snapshot_id": page["snapshot_id"], "revision": 0},
    ).json()
    assert historic["data"] == page["data"]
    current = client.get(
        root, headers=headers, params={"snapshot_id": page["snapshot_id"]}
    ).json()
    assert current["data"][0]["tags"] == ["关注对象"]
    assert current["data"][0]["raw_ip"] == row["raw_ip"]
    confirm = {
        "snapshot_id": page["snapshot_id"],
        "expected_revision": 1,
        "kind": "scope",
        "scope_state": "CONFIRMED_LEGACY",
        "reason": "纯合成来源确认属于同一演示空间",
    }
    confirmed = client.post(
        root + "/revisions",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json=confirm,
    )
    assert confirmed.status_code == 201, confirmed.text
    profile = client.get(
        root + "/profile", headers=headers, params={**params, "revision": 2}
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["association"] == "CONFIRMED_LEGACY"
    assert profile.json()["resource_id"] is not None
    assert profile.json()["governance_run_id"] == str(comparison_run.id)
    revoked = client.post(
        root + "/revisions",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={**confirm, "expected_revision": 2, "scope_state": "UNKNOWN"},
    )
    assert revoked.status_code == 201, revoked.text
    old_profile = client.get(
        root + "/profile", headers=headers, params={**params, "revision": 2}
    ).json()
    assert old_profile["resource_id"] is None
    assert old_profile["association"] == "REVOKED"


def test_empty_project_is_not_zero_assets(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    from tests.api.routes.test_customer_uploads import _create_project

    project = _create_project(client, superuser_token_headers)
    r = client.get(
        f"/api/v1/projects/{project['id']}/cloudatlas-ledger",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "NO_SOURCE"
    assert r.json()["total_records"] is None


@pytest.mark.parametrize("count", [0, 207])
def test_full_native_snapshot_pagination_and_empty(
    count: int,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.domain.cloudatlas_sources import OctobusCloudAtlasClient
    from app.governance_runner import main as run_runner
    from tests.api.routes import test_governance_runs as rf
    from tests.api.routes.test_governance_report_reads import _configure_runner

    _configure_runner(tmp_path, monkeypatch)
    project = rf._create_project(client, superuser_token_headers)
    rf._prepare_ready_project(
        client=client, headers=superuser_token_headers, project=project
    )
    rf._trigger_stage5_run(
        client=client,
        headers=superuser_token_headers,
        monkeypatch=monkeypatch,
        project=project,
        trigger_id=str(uuid.uuid4()),
    )
    records = [
        {
            "id": "duplicate-id" if n < 2 else str(n),
            "ip": "::ffff:192.0.2.1" if n < 2 else f"2001:db8::{n:x}",
            "status": "valid",
        }
        for n in range(count)
    ]
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _c, _s, *, capset_token, page, size: {
            "items": records[(page - 1) * size : page * size],
            "page": page,
            "size": size,
            "total": count,
        },
    )
    assert run_runner() == 0

    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("reader must not call CloudAtlas")

    monkeypatch.setattr(OctobusCloudAtlasClient, "list_ip_assets_page", forbidden)
    root = f"/api/v1/projects/{project['id']}/cloudatlas-ledger"
    first = client.get(root, headers=superuser_token_headers)
    assert first.status_code == 200, first.text
    page = first.json()
    assert page["state"] == ("EMPTY" if count == 0 else "PRESENT")
    assert page["total_records"] == count
    assert page["unique_ips"] == max(0, count - 1)
    collected: list[str] = []
    for skip in range(0, count, 25):
        r = client.get(
            root,
            headers=superuser_token_headers,
            params={"snapshot_id": page["snapshot_id"], "revision": 0, "skip": skip},
        )
        assert r.status_code == 200, r.text
        assert r.json()["count"] == count
        collected.extend(row["observation_id"] for row in r.json()["data"])
    assert len(collected) == len(set(collected)) == count
    if count:
        duplicate = client.get(
            root,
            headers=superuser_token_headers,
            params={"snapshot_id": page["snapshot_id"], "ip": "192.0.2.1"},
        ).json()
        assert duplicate["count"] == 2
        assert all(r["canonical_ip"] == "192.0.2.1" for r in duplicate["data"])


@pytest.mark.parametrize("comparison_run", ["absent"], indirect=True)
def test_roles_scope_and_atomic_audit(
    comparison_run: GovernanceRun,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError
    from sqlmodel import select

    from app.domain.models import CloudAtlasLedgerRevision
    from tests.api.routes.test_customer_uploads import _create_member, _create_project
    from tests.utils.audit import reject_audit_inserts

    root = f"/api/v1/projects/{comparison_run.project_id}/cloudatlas-ledger"
    headers = superuser_token_headers
    original = client.get(root, headers=headers).json()
    snapshot = original["snapshot_id"]
    edit = {
        "snapshot_id": snapshot,
        "expected_revision": 0,
        "kind": "management",
        "observation_id": original["data"][0]["observation_id"],
        "reason": "本地管理",
        "tags": ["local"],
    }
    for role in ["viewer", "approver", "operator"]:
        member = _create_member(
            client, headers, project_id=comparison_run.project_id, roles=[role]
        )
        assert client.get(root, headers=member).status_code == 200
        scope = client.post(
            root + "/revisions",
            headers={**member, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "snapshot_id": snapshot,
                "expected_revision": 0,
                "kind": "scope",
                "scope_state": "CONFIRMED_LEGACY",
                "reason": "不能自行扩大范围",
            },
        )
        assert scope.status_code == 403
        if role != "operator":
            assert (
                client.post(
                    root + "/revisions",
                    headers={**member, "Idempotency-Key": str(uuid.uuid4())},
                    json=edit,
                ).status_code
                == 404
            )
    foreign = _create_project(client, headers)
    foreign_root = f"/api/v1/projects/{foreign['id']}/cloudatlas-ledger"
    assert (
        client.get(
            foreign_root, headers=headers, params={"snapshot_id": snapshot}
        ).status_code
        == 404
    )
    assert (
        client.post(
            foreign_root + "/revisions",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            json=edit,
        ).status_code
        == 404
    )
    # Use the existing session for the audit failure seam; no second reader lock.
    with reject_audit_inserts(db):
        failed = client.post(
            root + "/revisions",
            headers={**headers, "Idempotency-Key": "audit-failure"},
            json=edit,
        )
        assert failed.status_code == 500
    assert (
        client.get(root + "/operations/audit-failure", headers=headers).status_code
        == 404
    )
    assert client.get(root, headers=headers).json()["revision"] == 0
    saved = client.post(
        root + "/revisions",
        headers={**headers, "Idempotency-Key": "audit-failure"},
        json=edit,
    )
    assert saved.status_code == 201, saved.text
    stale = client.post(
        root + "/revisions",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json=edit,
    )
    assert stale.status_code == 409
    record = db.exec(
        select(CloudAtlasLedgerRevision).where(
            CloudAtlasLedgerRevision.id == uuid.UUID(saved.json()["id"])
        )
    ).one()
    with pytest.raises(SQLAlchemyError):
        db.execute(
            text("UPDATE cloudatlas_ledger_revisions SET followed=true WHERE id=:id"),
            {"id": record.id},
        )
        db.commit()
    db.rollback()


@pytest.mark.parametrize("comparison_run", ["absent"], indirect=True)
@pytest.mark.parametrize("upstream_failure", [True, False])
def test_failed_new_read_keeps_complete_old_snapshot(
    comparison_run: GovernanceRun,
    upstream_failure: bool,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.cloudatlas_sources import OctobusCloudAtlasClient
    from app.governance_runner import main as run_runner
    from tests.api.routes.test_governance_report_reads import (
        _prepare_rerun,
    )

    root = f"/api/v1/projects/{comparison_run.project_id}/cloudatlas-ledger"
    headers = superuser_token_headers
    first = client.get(root, headers=headers).json()
    environment = _prepare_rerun(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=comparison_run.project_id,
        run_id=comparison_run.id,
        trigger_id=str(uuid.uuid4()),
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _c, _s, *, capset_token, page, size: {
            "items": [
                {"id": "invalid-synthetic", "ip": "not-an-ip", "status": "valid"}
            ],
            "page": page,
            "size": size,
            "total": 0 if upstream_failure else 1,
        },
    )
    assert run_runner() != 0
    latest = client.get(root, headers=headers)
    assert latest.status_code == 200, latest.text
    assert latest.json()["snapshot_id"] == first["snapshot_id"]
    assert latest.json()["data"] == first["data"]
    assert latest.json()["latest_attempt_state"] == (
        "READ_FAILED" if upstream_failure else "DOWNSTREAM_FAILED"
    )


@pytest.mark.parametrize("comparison_run", ["absent"], indirect=True)
@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_writes_use_one_parent_and_operation(
    comparison_run: GovernanceRun,
    same_key: bool,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    root = f"/api/v1/projects/{comparison_run.project_id}/cloudatlas-ledger"
    page = client.get(root, headers=superuser_token_headers).json()
    body = {
        "snapshot_id": page["snapshot_id"],
        "expected_revision": 0,
        "kind": "management",
        "observation_id": page["data"][0]["observation_id"],
        "reason": "Concurrent synthetic edit",
        "followed": True,
    }
    key = str(uuid.uuid4())
    db.rollback()

    def save(index: int) -> tuple[int, Any]:
        response = client.post(
            root + "/revisions",
            headers={
                **superuser_token_headers,
                "Idempotency-Key": key if same_key else key + str(index),
            },
            json=body,
        )
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [0, 1]))
    assert sorted(r[0] for r in results) == ([201, 201] if same_key else [201, 409])
    if same_key:
        assert results[0][1]["id"] == results[1][1]["id"]
    assert client.get(root, headers=superuser_token_headers).json()["revision"] == 1


@pytest.mark.parametrize("comparison_run", ["absent"], indirect=True)
def test_new_snapshot_does_not_inherit_management_or_scope(
    comparison_run: GovernanceRun,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.governance_runner import main as run_runner
    from tests.api.routes.test_governance_report_reads import _start_rerun

    root = f"/api/v1/projects/{comparison_run.project_id}/cloudatlas-ledger"
    headers = superuser_token_headers
    first = client.get(root, headers=headers).json()
    row = first["data"][0]
    for revision, body in enumerate(
        [
            {
                "kind": "management",
                "observation_id": row["observation_id"],
                "tags": ["first-snapshot"],
                "followed": True,
            },
            {"kind": "scope", "scope_state": "CONFIRMED_LEGACY"},
        ]
    ):
        response = client.post(
            root + "/revisions",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "snapshot_id": first["snapshot_id"],
                "expected_revision": revision,
                "reason": "Synthetic first snapshot only",
                **body,
            },
        )
        assert response.status_code == 201, response.text
    _start_rerun(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=comparison_run.project_id,
        run_id=comparison_run.id,
        trigger_id=str(uuid.uuid4()),
    )
    assert run_runner() == 0
    newer = client.get(root, headers=headers).json()
    assert newer["snapshot_id"] != first["snapshot_id"]
    assert newer["source_instance_id"] == first["source_instance_id"]
    assert newer["data"][0]["asset_id"] == row["asset_id"]
    assert newer["revision"] == 0 and newer["association"] == "UNKNOWN"
    assert all(not item["tags"] and not item["followed"] for item in newer["data"])
    history = client.get(
        root,
        headers=headers,
        params={"snapshot_id": first["snapshot_id"], "revision": 2},
    ).json()
    assert history["data"][0]["tags"] == ["first-snapshot"]
    assert history["association"] == "CONFIRMED_LEGACY"
