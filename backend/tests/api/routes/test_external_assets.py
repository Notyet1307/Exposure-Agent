"""Synthetic-only regression checks at the local HTTP/worker publication boundary."""

import hashlib
import json
import sys
import uuid
from collections.abc import Generator
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, delete, select

from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain import external_assets as service
from app.domain.cloudatlas_sources import CloudAtlasBoundaryError, CloudAtlasFingerprint
from app.domain.external_asset_models import (
    ExternalAssetRecord,
    ExternalAssetVersion,
    ExternalSync,
)
from app.domain.models import Project, ProjectMembership, SourceInstance
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
    AgentComposeRunStart,
    AgentComposeSession,
    AgentComposeSessionObservation,
)
from app.integrations.cloudatlas_assets import OctobusCloudAtlasAssetsClient
from app.integrations.cloudatlas_dns import OctobusCloudAtlasDNSClient
from app.integrations.cloudatlas_root_domains import OctobusCloudAtlasRootDomainsClient
from app.models import User
from tests.integrations.test_cloudatlas_dns import dns_row


@pytest.fixture
def assets(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> Generator[SimpleNamespace]:
    now = get_datetime_utc() - timedelta(days=2)
    monkeypatch.setattr(service, "get_datetime_utc", lambda: now)
    monkeypatch.setattr(
        "app.api.routes.external_assets.get_datetime_utc",
        lambda: now,
    )
    token = "synthetic-assets-token"
    monkeypatch.setattr(settings, "CLOUDATLAS_ASSETS_CAPSET_TOKEN", SecretStr(token))
    monkeypatch.setattr(
        OctobusCloudAtlasAssetsClient,
        "validate_credentials",
        lambda *args, **kwargs: CloudAtlasFingerprint("a" * 64),
    )
    state = SimpleNamespace(
        now=now,
        client=client,
        db=db,
        headers=superuser_token_headers,
        runs={},
        starts=0,
        calls=[],
        pages={
            "ip": [
                [
                    {
                        "id": "9007199254740993",
                        "ip": "2001:0db8::1",
                        "status": "valid",
                        "bu": {"id": "9007199254740995", "name": "Synthetic"},
                        "subnet": None,
                    }
                ],
                [{"id": "2", "ip": "192.0.2.1", "status": "valid"}],
            ],
            "port": [
                [
                    {
                        "id": "3",
                        "ip": "2001:db8::1",
                        "port": 443,
                        "banner": "<script>synthetic</script>",
                    }
                ],
                [{"id": "4", "ip": "2001:db8::1", "port": 8443}],
                [{"id": "5", "ip": "198.51.100.99", "port": 80}],
            ],
        },
        observation=AgentComposeSessionObservation.RUNNING,
        failure=None,
    )

    def start(
        self: AgentComposeClient, *, client_request_id: str, sync_id: str
    ) -> AgentComposeRunStart:
        state.starts += 1
        run = AgentComposeRunStart(
            run_id=self.expected_cloudatlas_sync_run_id(client_request_id),
            started=True,
            status="running",
            session_id=hashlib.sha256(sync_id.encode()).hexdigest(),
            project_id=self.project_id,
            agent_name="cloudatlas-sync",
        )
        state.runs[run.run_id] = run
        return run

    def page(
        _self: OctobusCloudAtlasAssetsClient, source: SourceInstance, **kwargs: Any
    ) -> dict[str, Any]:
        domain, number = kwargs["domain"], kwargs["page"]
        state.calls.append((domain, number))
        if state.failure:
            result = state.failure(domain, number)
            if result is not None:
                return cast(dict[str, Any], result)
        pages = state.pages[domain]
        return {
            "page": number,
            "size": kwargs["size"],
            "total": sum(len(p) for p in pages),
            "space_id": source.space_id,
            "items": pages[number - 1],
        }

    monkeypatch.setattr(AgentComposeClient, "start_cloudatlas_sync", start)
    monkeypatch.setattr(
        AgentComposeClient, "get_run", lambda self, run_id: state.runs.get(run_id)
    )
    monkeypatch.setattr(
        AgentComposeClient,
        "get_session",
        lambda self, session_id: AgentComposeSession(
            session_id=session_id, observation=state.observation
        ),
    )
    monkeypatch.setattr(OctobusCloudAtlasAssetsClient, "list_page", page)
    response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=state.headers,
        json={"name": f"external-synthetic-{uuid.uuid4()}"},
    )
    assert response.status_code == 201
    state.project_id = response.json()["id"]
    state.base = f"{settings.API_V1_STR}/projects/{state.project_id}/external-assets"
    response = client.post(
        state.base + "/sources",
        headers=state.headers,
        json={
            "instance_id": "synthetic-assets",
            "capset_id": "synthetic-capset",
            "space_id": "7",
        },
    )
    assert response.status_code == 201
    state.source_id = response.json()["id"]
    state.path = state.base + "/sources/" + state.source_id
    assert (
        client.post(state.path + "/validate", headers=state.headers).json()[
            "validation_status"
        ]
        == "validated"
    )
    assert state.calls == []  # Configuration validation never consumes a source page.
    assert (
        client.patch(
            state.path, headers=state.headers, json={"enabled": True}
        ).status_code
        == 200
    )
    state.body = {
        "page_size": 1,
        "max_pages": 20,
        "max_records": 20,
        "max_response_bytes": 4096,
        "timeout_seconds": 60,
        "retain_until": (now + timedelta(hours=1)).isoformat(),
    }
    yield state
    db.rollback()
    db.exec(
        delete(ProjectMembership).where(
            col(ProjectMembership.project_id) == uuid.UUID(state.project_id)
        )
    )
    db.commit()


def submit(
    state: SimpleNamespace, key: str | None = None, **changes: Any
) -> dict[str, Any]:
    response = state.client.post(
        state.path + "/syncs",
        headers=state.headers | {"Idempotency-Key": key or str(uuid.uuid4())},
        json=state.body | changes,
    )
    assert response.status_code == 202, response.text
    return cast(dict[str, Any], response.json())


def execute(state: SimpleNamespace, sync: dict[str, Any]) -> dict[str, Any]:
    service.execute_sync(
        state.db, uuid.UUID(sync["id"]), sync["agent_run_id"], sync["session_id"]
    )
    response = state.client.get(
        state.path + "/syncs/" + sync["id"], headers=state.headers
    )
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


def add_member(state: SimpleNamespace, role: str) -> ProjectMembership:
    user = state.db.exec(
        select(User).where(User.email == settings.EMAIL_TEST_USER)
    ).one()
    member = ProjectMembership(
        project_id=uuid.UUID(state.project_id), user_id=user.id, roles=[role]
    )
    state.db.add(member)
    state.db.commit()
    return member


def listing(
    state: SimpleNamespace, domain: str = "ip", **params: Any
) -> dict[str, Any]:
    response = state.client.get(
        state.path + "/records",
        headers=state.headers,
        params={"domain": domain} | params,
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def test_immutable_domain_versions_identity_and_local_matching(
    assets: SimpleNamespace, monkeypatch: MonkeyPatch
) -> None:
    sync = submit(assets, "same-intent")
    assert submit(assets, "same-intent")["id"] == sync["id"]
    changed = assets.client.post(
        assets.path + "/syncs",
        headers=assets.headers | {"Idempotency-Key": "same-intent"},
        json=assets.body | {"max_pages": 19},
    )
    assert changed.status_code == 409
    assert assets.starts == 1
    assert execute(assets, sync)["status"] == "SUCCEEDED"
    first = listing(assets)
    ipv6 = next(r for r in first["data"] if r["canonical_ip"] == "2001:db8::1")
    assert ipv6["source_id"] == "9007199254740993"
    assert ipv6["fields"]["subnet"] is None and "subnet" not in next(
        r["fields"] for r in first["data"] if r["ip"] == "192.0.2.1"
    )
    assert ipv6["fields"]["bu"]["id"] == "9007199254740995"
    assert listing(assets, "port")["count"] == 3
    detail = assets.client.get(
        assets.path + f"/versions/{first['version']['id']}/records/{ipv6['id']}",
        headers=assets.headers,
    ).json()
    assert {r["fields"]["port"] for r in detail["matched_ports"]} == {443, 8443}
    assert detail["matched_port_count"] == 2
    assert execute(assets, submit(assets))["status"] == "SUCCEEDED"
    second = listing(assets)
    assert second["count"] == 2 and second["version"]["id"] != first["version"]["id"]
    assert listing(assets, version_id=first["version"]["id"])["data"] == first["data"]
    monkeypatch.setattr(
        OctobusCloudAtlasAssetsClient,
        "validate_credentials",
        lambda *a, **k: pytest.fail("local read called OctoBus"),
    )
    assert listing(assets)["version"]["id"] == second["version"]["id"]


def test_port_banner_nul_round_trips_without_breaking_published_reads(
    assets: SimpleNamespace,
) -> None:
    assets.pages["port"][0][0]["banner"] = "synthetic\0banner"

    assert execute(assets, submit(assets, "nul-banner"))["status"] == "SUCCEEDED"
    rows = listing(assets, "port")["data"]
    assert next(row for row in rows if row["source_id"] == "3")["fields"] == {
        "id": "3",
        "ip": "2001:db8::1",
        "port": 443,
        "banner": "synthetic\0banner",
    }


@pytest.mark.parametrize(
    "fault",
    ["late_page", "duplicate", "total_changed", "early_empty", "fingerprint"],
)
def test_failed_domain_never_overwrites_last_complete_version(
    assets: SimpleNamespace, monkeypatch: MonkeyPatch, fault: str
) -> None:
    assert execute(assets, submit(assets))["status"] == "SUCCEEDED"
    previous = listing(assets, "port")["version"]["id"]

    def failure(domain: str, number: int) -> dict[str, Any] | None:
        if domain != "port" or number != 2:
            return None
        if fault == "late_page":
            raise CloudAtlasBoundaryError("cloudatlas_upstream_failed")
        if fault == "fingerprint":
            monkeypatch.setattr(
                OctobusCloudAtlasAssetsClient,
                "validate_credentials",
                lambda *a, **k: CloudAtlasFingerprint("b" * 64),
            )
        if fault in ("duplicate", "total_changed", "early_empty"):
            return {
                "page": 2,
                "size": 1,
                "total": 4 if fault == "total_changed" else 3,
                "space_id": "7",
                "items": []
                if fault == "early_empty"
                else [{"id": "3", "ip": "2001:db8::1", "port": 443}],
            }
        return None

    assets.failure = failure
    result = execute(assets, submit(assets))
    assert result["status"] == "PARTIAL_FAILED"
    assert listing(assets, "port")["version"]["id"] == previous
    assert result["domains"][0]["status"] == "PUBLISHED"
    assert result["domains"][1]["status"] == "FAILED"


def test_unknown_session_blocks_replacement_and_only_terminal_reconcile_finishes(
    assets: SimpleNamespace,
) -> None:
    sync = submit(assets)
    assets.observation = AgentComposeSessionObservation.UNKNOWN
    result = execute(assets, sync)
    assert result["status"] == "UNKNOWN" and assets.calls == []
    response = assets.client.post(
        assets.path + "/syncs",
        headers=assets.headers | {"Idempotency-Key": "different"},
        json=assets.body,
    )
    assert response.status_code == 409 and assets.starts == 1
    assert (
        assets.client.get(
            assets.path + "/syncs/" + sync["id"], headers=assets.headers
        ).json()["status"]
        == "UNKNOWN"
    )
    assert assets.starts == 1 and assets.calls == []
    assets.observation = AgentComposeSessionObservation.TERMINAL
    response = assets.client.post(
        assets.path + "/syncs/" + sync["id"] + "/reconcile", headers=assets.headers
    )
    assert response.json()["status"] == "FAILED"
    assert assets.starts == 1 and assets.calls == []


def test_disabled_history_revocation_expiry_and_narrow_purge(
    assets: SimpleNamespace, monkeypatch: MonkeyPatch
) -> None:
    assert execute(assets, submit(assets))["status"] == "SUCCEEDED"
    first = listing(assets)
    assert (
        assets.client.patch(
            assets.path, headers=assets.headers, json={"enabled": False}
        ).status_code
        == 200
    )
    assert listing(assets)["count"] == 2
    assert (
        assets.client.patch(
            assets.path, headers=assets.headers, json={"data_access_enabled": False}
        ).status_code
        == 200
    )
    assert (
        assets.client.get(
            assets.path + "/records", headers=assets.headers, params={"domain": "ip"}
        ).status_code
        == 403
    )
    assert (
        assets.client.patch(
            assets.path, headers=assets.headers, json={"data_access_enabled": True}
        ).status_code
        == 200
    )
    monkeypatch.setattr(service, "get_datetime_utc", get_datetime_utc)
    expired = listing(assets)
    assert expired["state"] == "EXPIRED" and expired["data"] == []
    record = first["data"][0]
    assert (
        assets.client.get(
            assets.path + f"/versions/{first['version']['id']}/records/{record['id']}",
            headers=assets.headers,
        ).status_code
        == 410
    )
    response = assets.client.post(
        assets.path + "/purge-expired", headers=assets.headers
    )
    assert response.json() == {"deleted_records": 5}
    assert listing(assets)["state"] == "EXPIRED"
    assets.db.expire_all()
    assert (
        assets.db.get(ExternalAssetVersion, uuid.UUID(first["version"]["id"]))
        is not None
    )
    assert assets.db.get(ExternalAssetRecord, uuid.UUID(record["id"])) is None
    assert assets.db.get(SourceInstance, uuid.UUID(assets.source_id)) is not None


def test_legacy_selector_and_archived_writes_are_denied(
    assets: SimpleNamespace,
) -> None:
    prefix = f"{settings.API_V1_STR}/projects/{assets.project_id}"
    assert (
        assets.client.get(
            prefix + "/cloudatlas-source-instances", headers=assets.headers
        ).json()["data"]
        == []
    )
    assert (
        assets.client.post(
            prefix + f"/cloudatlas-source-instances/{assets.source_id}/enable",
            headers=assets.headers,
        ).status_code
        == 404
    )
    project = assets.db.get(Project, uuid.UUID(assets.project_id))
    assert project is not None
    project.archived_at = get_datetime_utc()
    assets.db.add(project)
    assets.db.commit()
    assert (
        assets.client.post(
            assets.path + "/syncs",
            headers=assets.headers | {"Idempotency-Key": "archived"},
            json=assets.body,
        ).status_code
        == 409
    )
    assert listing(assets)["state"] == "NOT_SYNCED"
    assert (
        assets.client.get(assets.base + "/sources", headers=assets.headers).json()[
            "can_manage"
        ]
        is False
    )


def test_viewer_revocation_and_cross_project_fixed_links(
    assets: SimpleNamespace, normal_user_token_headers: dict[str, str]
) -> None:
    assert execute(assets, submit(assets))["status"] == "SUCCEEDED"
    member = add_member(assets, "viewer")
    assert (
        assets.client.get(
            assets.path + "/records",
            headers=normal_user_token_headers,
            params={"domain": "ip"},
        ).status_code
        == 200
    )
    assert (
        assets.client.post(
            assets.path + "/syncs",
            headers=normal_user_token_headers | {"Idempotency-Key": "viewer"},
            json=assets.body,
        ).status_code
        == 404
    )
    member.revoked_at = get_datetime_utc()
    assets.db.add(member)
    assets.db.commit()
    record = listing(assets)["data"][0]
    assert (
        assets.client.get(
            assets.path + f"/versions/{record['version_id']}/records/{record['id']}",
            headers=normal_user_token_headers,
        ).status_code
        == 404
    )
    other = assets.client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=assets.headers,
        json={"name": f"other-{uuid.uuid4()}"},
    ).json()["id"]
    wrong = f"{settings.API_V1_STR}/projects/{other}/external-assets/sources/{assets.source_id}"
    assert (
        assets.client.get(
            wrong + "/records",
            headers=assets.headers,
            params={"domain": "ip", "version_id": record["version_id"]},
        ).status_code
        == 404
    )


@pytest.mark.parametrize("pages, count, complete", [(20, 2, True), (2, 1, False)])
def test_terminal_same_session_recovers_sealed_stage_without_source_retry(
    assets: SimpleNamespace,
    monkeypatch: MonkeyPatch,
    pages: int,
    count: int,
    complete: bool,
) -> None:
    publish = service.publish

    def interrupt(*_args: Any, **_kwargs: Any) -> None:
        raise service.SyncError("external_session_unknown", unknown=True)

    monkeypatch.setattr(service, "publish", interrupt)
    sync = submit(assets, max_pages=pages)
    assert execute(assets, sync)["status"] == "UNKNOWN"
    assert listing(assets)["state"] == "NOT_SYNCED"
    calls = list(assets.calls)
    monkeypatch.setattr(service, "publish", publish)
    assets.observation = AgentComposeSessionObservation.TERMINAL
    response = assets.client.post(
        assets.path + "/syncs/" + sync["id"] + "/reconcile", headers=assets.headers
    )
    assert response.json()["status"] == "PARTIAL_FAILED"
    assert listing(assets)["count"] == count
    assert listing(assets)["version"]["complete"] is complete
    assert listing(assets, "port")["state"] == "NOT_SYNCED"
    assert assets.starts == 1 and assets.calls == calls


def test_retention_maintenance_works_after_archival_and_access_revocation(
    assets: SimpleNamespace, monkeypatch: MonkeyPatch
) -> None:
    from app import cloudatlas_sync_runner

    assert execute(assets, submit(assets))["status"] == "SUCCEEDED"
    source = assets.db.get(SourceInstance, uuid.UUID(assets.source_id))
    project = assets.db.get(Project, uuid.UUID(assets.project_id))
    assert source is not None and project is not None
    source.data_access_enabled = False
    project.archived_at = get_datetime_utc()
    assets.db.add(source)
    assets.db.add(project)
    assets.db.commit()
    monkeypatch.setattr(service, "get_datetime_utc", get_datetime_utc)
    assert (
        assets.client.post(
            assets.path + "/purge-expired", headers=assets.headers
        ).status_code
        == 409
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["runner", "--purge-expired", "--source-id", assets.source_id],
    )
    assert cloudatlas_sync_runner.main() == 0
    assets.db.expire_all()
    versions = assets.db.exec(
        select(ExternalAssetVersion).where(ExternalAssetVersion.source_id == source.id)
    ).all()
    assert {v.record_count for v in versions} == {2, 3}
    assert (
        assets.db.exec(
            select(ExternalAssetRecord).where(
                col(ExternalAssetRecord.version_id).in_([v.id for v in versions])
            )
        ).all()
        == []
    )
    assert (
        assets.db.exec(select(ExternalSync).where(ExternalSync.source_id == source.id))
        .one()
        .status
        == "SUCCEEDED"
    )


def test_complete_empty_domain_is_published_not_unsynced(
    assets: SimpleNamespace,
) -> None:
    assets.pages = {"ip": [[]], "port": [[]]}
    assert execute(assets, submit(assets))["status"] == "SUCCEEDED"
    for domain in ("ip", "port"):
        result = listing(assets, domain)
        assert result["state"] == "PUBLISHED" and result["count"] == 0
        assert result["version"]["record_count"] == 0


def test_source_failure_stops_the_other_domain(
    assets: SimpleNamespace,
) -> None:
    def source_failed(_domain: str, _number: int) -> None:
        raise CloudAtlasBoundaryError("cloudatlas_upstream_failed")

    assets.failure = source_failed
    assert execute(assets, submit(assets))["status"] == "FAILED"
    assert assets.calls == [("ip", 1)]


@pytest.mark.parametrize(
    "budget", [{"max_pages": 1}, {"page_size": 2, "max_records": 3}]
)
def test_budget_must_reserve_a_page_for_each_domain_before_launch(
    assets: SimpleNamespace, budget: dict[str, int]
) -> None:
    response = assets.client.post(
        assets.path + "/syncs",
        headers=assets.headers | {"Idempotency-Key": str(uuid.uuid4())},
        json=assets.body | budget,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "external_two_domain_budget_required"
    assert assets.starts == 0 and assets.calls == []
    assert (
        assets.client.get(assets.path + "/syncs", headers=assets.headers).json()["data"]
        == []
    )


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ("membership_revoked", "external_permission_revoked"),
        ("retention_expired", "external_retention_expired"),
        ("credential_revalidated", "external_material_changed"),
    ],
)
def test_inflight_authority_change_cannot_publish_or_restart(
    assets: SimpleNamespace,
    monkeypatch: MonkeyPatch,
    normal_user_token_headers: dict[str, str],
    change: str,
    error: str,
) -> None:
    assert execute(assets, submit(assets))["status"] == "SUCCEEDED"
    previous = {domain: listing(assets, domain) for domain in ("ip", "port")}
    member = add_member(assets, "operator")
    response = assets.client.post(
        assets.path + "/syncs",
        headers=normal_user_token_headers | {"Idempotency-Key": "inflight"},
        json=assets.body
        | {"retain_until": (assets.now + timedelta(seconds=1)).isoformat()},
    )
    assert response.status_code == 202
    sync = response.json()

    def change_authority(domain: str, number: int) -> None:
        if (domain, number) != ("ip", 2):
            return
        if change == "membership_revoked":
            member.revoked_at = assets.now
            assets.db.add(member)
            assets.db.commit()
        elif change == "retention_expired":
            monkeypatch.setattr(
                service, "get_datetime_utc", lambda: assets.now + timedelta(seconds=1)
            )
        else:
            monkeypatch.setattr(
                settings, "CLOUDATLAS_ASSETS_CAPSET_TOKEN", SecretStr("rotated-token")
            )
            validated = assets.client.post(
                assets.path + "/validate", headers=assets.headers
            )
            assert validated.json()["validation_status"] == "validated"

    assets.calls.clear()
    assets.failure = change_authority
    result = execute(assets, sync)
    assert result["status"] == "FAILED"
    assert {domain["error_code"] for domain in result["domains"]} == {error}
    assert all(domain["version_id"] is None for domain in result["domains"])
    assert assets.calls == [("ip", 1), ("port", 1), ("ip", 2)]
    for domain in ("ip", "port"):
        assert listing(assets, domain) == previous[domain]
    assert execute(assets, sync) == result
    assert assets.calls == [("ip", 1), ("port", 1), ("ip", 2)] and assets.starts == 2


def test_ambiguous_start_reservation_replays_and_reconciles_without_relaunch(
    assets: SimpleNamespace, monkeypatch: MonkeyPatch
) -> None:
    start = AgentComposeClient.start_cloudatlas_sync

    def accepted_then_disconnected(
        client: AgentComposeClient, **kwargs: Any
    ) -> AgentComposeRunStart:
        start(client, **kwargs)
        raise AgentComposeBoundaryError("agent_compose_unavailable")

    monkeypatch.setattr(
        AgentComposeClient, "start_cloudatlas_sync", accepted_then_disconnected
    )
    sync = submit(assets, "uncertain-start")
    assert sync["status"] == "UNKNOWN"
    assert sync["error_code"] == "external_start_unknown"
    assert sync["session_id"] is None
    assert submit(assets, "uncertain-start") == sync
    blocked = assets.client.post(
        assets.path + "/syncs",
        headers=assets.headers | {"Idempotency-Key": "replacement"},
        json=assets.body,
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "external_sync_unresolved"
    reconcile_path = assets.path + "/syncs/" + sync["id"] + "/reconcile"
    running = assets.client.post(reconcile_path, headers=assets.headers).json()
    assert running["status"] == "UNKNOWN"
    assert running["session_id"] == assets.runs[sync["agent_run_id"]].session_id
    assets.observation = AgentComposeSessionObservation.TERMINAL
    terminal = assets.client.post(reconcile_path, headers=assets.headers).json()
    assert terminal["status"] == "FAILED"
    assert {domain["error_code"] for domain in terminal["domains"]} == {
        "external_execution_interrupted"
    }
    assert submit(assets, "uncertain-start") == terminal
    assert assets.client.post(reconcile_path, headers=assets.headers).json() == terminal
    assert listing(assets)["state"] == "NOT_SYNCED"
    assert assets.starts == 1 and assets.calls == []


def test_ambiguous_start_does_not_erase_a_worker_result(
    assets: SimpleNamespace, monkeypatch: MonkeyPatch
) -> None:
    start = AgentComposeClient.start_cloudatlas_sync

    def completed_then_disconnected(
        client: AgentComposeClient, **kwargs: Any
    ) -> AgentComposeRunStart:
        run = start(client, **kwargs)
        assert run.session_id is not None
        service.execute_sync(
            assets.db, uuid.UUID(kwargs["sync_id"]), run.run_id, run.session_id
        )
        raise AgentComposeBoundaryError("agent_compose_unavailable")

    monkeypatch.setattr(
        AgentComposeClient, "start_cloudatlas_sync", completed_then_disconnected
    )
    sync = submit(assets, "completed-start")
    assert sync["status"] == "SUCCEEDED" and sync["error_code"] is None
    assert listing(assets)["count"] == 2
    assert listing(assets, "port")["count"] == 3
    calls = list(assets.calls)
    assert submit(assets, "completed-start") == sync
    assert execute(assets, sync) == sync
    assert assets.starts == 1 and assets.calls == calls


def test_reconciliation_requires_the_original_authoritative_session(
    assets: SimpleNamespace, monkeypatch: MonkeyPatch
) -> None:
    assert execute(assets, submit(assets))["status"] == "SUCCEEDED"
    previous = listing(assets)
    publish = service.publish

    def interrupted(*_args: Any, **_kwargs: Any) -> None:
        raise service.SyncError("external_session_unknown", unknown=True)

    monkeypatch.setattr(service, "publish", interrupted)
    sync = submit(assets)
    assert execute(assets, sync)["status"] == "UNKNOWN"
    monkeypatch.setattr(service, "publish", publish)
    calls = list(assets.calls)
    run = assets.runs[sync["agent_run_id"]]
    assets.observation = AgentComposeSessionObservation.TERMINAL
    path = assets.path + "/syncs/" + sync["id"] + "/reconcile"
    assets.runs[run.run_id] = replace(run, session_id="different-session")
    refused = assets.client.post(path, headers=assets.headers).json()
    assert refused["status"] == "UNKNOWN"
    assert refused["session_id"] == run.session_id
    assert listing(assets) == previous
    assets.runs[run.run_id] = run
    recovered = assets.client.post(path, headers=assets.headers).json()
    assert recovered["status"] == "PARTIAL_FAILED"
    assert listing(assets)["version"]["id"] != previous["version"]["id"]
    assert assets.client.post(path, headers=assets.headers).json() == recovered
    assert assets.starts == 2 and assets.calls == calls


@pytest.mark.parametrize("failure", ["missing_token", "connectivity"])
def test_failed_validation_and_drift_require_explicit_revalidation(
    assets: SimpleNamespace, monkeypatch: MonkeyPatch, failure: str
) -> None:
    assert execute(assets, submit(assets))["status"] == "SUCCEEDED"
    previous = listing(assets)
    calls = list(assets.calls)
    if failure == "missing_token":
        monkeypatch.setattr(settings, "CLOUDATLAS_ASSETS_CAPSET_TOKEN", SecretStr(""))
        code = "external_credential_missing"
    else:

        def unavailable(*_args: Any, **_kwargs: Any) -> CloudAtlasFingerprint:
            raise CloudAtlasBoundaryError("cloudatlas_connectivity_failed")

        monkeypatch.setattr(
            OctobusCloudAtlasAssetsClient, "validate_credentials", unavailable
        )
        code = "cloudatlas_connectivity_failed"
    failed = assets.client.post(assets.path + "/validate", headers=assets.headers)
    assert failed.status_code == 200
    assert failed.json()["validation_status"] == "failed"
    assert failed.json()["validated_fingerprint"] is None
    enabled = assets.client.patch(
        assets.path, headers=assets.headers, json={"enabled": True}
    )
    assert enabled.status_code == 409
    assert enabled.json()["detail"]["code"] == code
    monkeypatch.setattr(
        settings, "CLOUDATLAS_ASSETS_CAPSET_TOKEN", SecretStr("replacement-token")
    )
    monkeypatch.setattr(
        OctobusCloudAtlasAssetsClient,
        "validate_credentials",
        lambda *a, **k: CloudAtlasFingerprint("b" * 64),
    )
    enabled = assets.client.patch(
        assets.path, headers=assets.headers, json={"enabled": True}
    )
    assert enabled.status_code == 409
    assert enabled.json()["detail"]["code"] == "external_validation_required"
    denied = assets.client.post(
        assets.path + "/syncs",
        headers=assets.headers | {"Idempotency-Key": "unvalidated"},
        json=assets.body,
    )
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "external_material_changed"
    assert listing(assets) == previous
    assert assets.starts == 1 and assets.calls == calls
    validated = assets.client.post(assets.path + "/validate", headers=assets.headers)
    assert validated.json()["validation_status"] == "validated"
    assert execute(assets, submit(assets, "unvalidated"))["status"] == "SUCCEEDED"
    assert listing(assets)["version"]["id"] != previous["version"]["id"]


def test_local_history_filters_and_fixed_details_remain_source_scoped(
    assets: SimpleNamespace,
    monkeypatch: MonkeyPatch,
    normal_user_token_headers: dict[str, str],
) -> None:
    first = execute(
        assets,
        submit(assets, retain_until=(assets.now + timedelta(seconds=1)).isoformat()),
    )
    assert first["status"] == "SUCCEEDED"
    old_ip = listing(assets)
    old_port = listing(assets, "port")
    monkeypatch.setattr(
        service, "get_datetime_utc", lambda: assets.now + timedelta(milliseconds=100)
    )
    assets.pages["port"] = [[{"id": "6", "ip": "2001:db8::1", "port": 9443}]]
    second = execute(assets, submit(assets))
    assert second["status"] == "SUCCEEDED"
    current = listing(assets)

    def unavailable(_domain: str, _number: int) -> None:
        raise CloudAtlasBoundaryError("cloudatlas_upstream_failed")

    assets.failure = unavailable
    failed = execute(assets, submit(assets))
    assert failed["status"] == "FAILED"
    assert (
        assets.client.patch(
            assets.path, headers=assets.headers, json={"enabled": False}
        ).status_code
        == 200
    )
    add_member(assets, "viewer")
    sources = assets.client.get(
        assets.base + "/sources", headers=normal_user_token_headers
    )
    assert sources.status_code == 200
    assert sources.json()["can_manage"] is False
    calls, starts = list(assets.calls), assets.starts

    def no_source_calls(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("local history contacted an external service")

    monkeypatch.setattr(
        OctobusCloudAtlasAssetsClient, "validate_credentials", no_source_calls
    )
    monkeypatch.setattr(OctobusCloudAtlasAssetsClient, "list_page", no_source_calls)
    monkeypatch.setattr(AgentComposeClient, "get_run", no_source_calls)
    history = assets.client.get(
        assets.path + "/syncs",
        headers=normal_user_token_headers,
        params={"skip": 1, "limit": 1},
    )
    assert history.status_code == 200
    assert history.json()["count"] == 3
    assert [sync["id"] for sync in history.json()["data"]] == [second["id"]]
    versions = assets.client.get(
        assets.path + "/versions",
        headers=normal_user_token_headers,
        params={"domain": "ip", "skip": 1, "limit": 1},
    )
    assert versions.status_code == 200
    assert versions.json()["count"] == 2
    assert [version["id"] for version in versions.json()["data"]] == [
        old_ip["version"]["id"]
    ]
    filtered = listing(
        assets,
        version_id=old_ip["version"]["id"],
        ip="2001:0db8:0:0:0:0:0:1",
        status="valid",
    )
    assert [row["source_id"] for row in filtered["data"]] == ["9007199254740993"]
    assert filtered["count"] == 1
    assert listing(assets, status="nonexistent")["count"] == 0
    page = listing(assets, version_id=old_ip["version"]["id"], skip=1, limit=1)
    assert page["count"] == 2 and page["data"] == [filtered["data"][0]]
    invalid = assets.client.get(
        assets.path + "/records",
        headers=normal_user_token_headers,
        params={"domain": "ip", "ip": "not-an-address"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "external_ip_filter_invalid"
    row = filtered["data"][0]
    detail_path = (
        assets.path + f"/versions/{old_ip['version']['id']}/records/{row['id']}"
    )
    pinned = assets.client.get(
        detail_path,
        headers=normal_user_token_headers,
        params={"port_version_id": old_port["version"]["id"], "skip": 1, "limit": 1},
    )
    assert pinned.status_code == 200
    assert pinned.json()["matched_port_count"] == 2
    assert [port["fields"]["port"] for port in pinned.json()["matched_ports"]] == [8443]
    latest = assets.client.get(detail_path, headers=normal_user_token_headers)
    assert [port["fields"]["port"] for port in latest.json()["matched_ports"]] == [9443]
    wrong_domain = assets.client.get(
        detail_path,
        headers=normal_user_token_headers,
        params={"port_version_id": old_ip["version"]["id"]},
    )
    assert wrong_domain.status_code == 404
    wrong_record = assets.client.get(
        assets.path + f"/versions/{current['version']['id']}/records/{row['id']}",
        headers=normal_user_token_headers,
    )
    assert wrong_record.status_code == 404
    other = assets.client.post(
        assets.base + "/sources",
        headers=assets.headers,
        json={
            "instance_id": "other-assets",
            "capset_id": "other-capset",
            "space_id": "7",
        },
    )
    assert other.status_code == 201
    other_path = assets.base + "/sources/" + other.json()["id"]
    for suffix, params in (
        ("/syncs/" + second["id"], {}),
        ("/records", {"domain": "ip", "version_id": old_ip["version"]["id"]}),
        (f"/versions/{old_ip['version']['id']}/records/{row['id']}", {}),
    ):
        assert (
            assets.client.get(
                other_path + suffix, headers=normal_user_token_headers, params=params
            ).status_code
            == 404
        )
    monkeypatch.setattr(
        service, "get_datetime_utc", lambda: assets.now + timedelta(seconds=1)
    )
    live_row = next(
        row for row in current["data"] if row["canonical_ip"] == "2001:db8::1"
    )
    expired_port = assets.client.get(
        assets.path + f"/versions/{current['version']['id']}/records/{live_row['id']}",
        headers=normal_user_token_headers,
        params={"port_version_id": old_port["version"]["id"]},
    )
    assert expired_port.status_code == 410
    assert expired_port.json()["detail"]["code"] == "external_version_expired"
    assert assets.calls == calls and assets.starts == starts


def test_partial_batches_are_readable_without_replacing_complete_history(
    assets: SimpleNamespace, monkeypatch: MonkeyPatch
) -> None:
    assert execute(assets, submit(assets))["status"] == "SUCCEEDED"
    complete = {domain: listing(assets, domain) for domain in ("ip", "port")}
    monkeypatch.setattr(
        service, "get_datetime_utc", lambda: assets.now + timedelta(seconds=1)
    )
    assets.calls.clear()
    task = execute(
        assets,
        submit(
            assets,
            max_pages=2,
            retain_until=(assets.now + timedelta(seconds=10)).isoformat(),
        ),
    )
    assert task["status"] == "PARTIAL_SUCCEEDED"
    assert assets.calls == [("ip", 1), ("port", 1)]
    partial = {domain: listing(assets, domain) for domain in ("ip", "port")}
    for domain, total in (("ip", 2), ("port", 3)):
        version = partial[domain]["version"]
        assert partial[domain]["count"] == 1
        assert version["complete"] is False and version["expected_total"] == total
        assert version["pages_read"] == 1 and version["stop_reason"] == "batch_limit"
        history = assets.client.get(
            assets.path + "/versions",
            headers=assets.headers,
            params={"domain": domain, "limit": 1},
        ).json()
        assert history["data"][0]["id"] == version["id"]
        assert (
            history["latest_complete_version"]["id"]
            == complete[domain]["version"]["id"]
        )
    ip = partial["ip"]
    detail_url = (
        assets.path + f"/versions/{ip['version']['id']}/records/{ip['data'][0]['id']}"
    )
    detail = assets.client.get(
        detail_url,
        headers=assets.headers,
        params={"port_version_id": partial["port"]["version"]["id"]},
    ).json()
    assert detail["matched_port_count"] == 1
    assert detail["port_version"]["complete"] is False
    monkeypatch.setattr(
        service, "get_datetime_utc", lambda: assets.now + timedelta(seconds=11)
    )
    for domain in ("ip", "port"):
        expired = listing(assets, domain)
        assert expired["state"] == "EXPIRED" and expired["data"] == []
        assert expired["version"]["id"] == partial[domain]["version"]["id"]
        assert (
            listing(assets, domain, version_id=complete[domain]["version"]["id"])[
                "data"
            ]
            == complete[domain]["data"]
        )
    assert assets.client.get(detail_url, headers=assets.headers).status_code == 410
    assert assets.calls == [("ip", 1), ("port", 1)]


def test_empty_ip_does_not_stop_ports_or_lend_them_unused_quota(
    assets: SimpleNamespace,
) -> None:
    assets.pages["ip"] = [[]]
    result = execute(assets, submit(assets, max_records=5))
    assert result["status"] == "PARTIAL_SUCCEEDED"
    assert assets.calls == [("ip", 1), ("port", 1), ("port", 2)]
    assert listing(assets)["version"]["complete"] is True
    assert listing(assets)["count"] == 0
    assert listing(assets, "port")["version"]["complete"] is False
    assert listing(assets, "port")["count"] == 2


def test_published_partial_domain_survives_sibling_source_failure(
    assets: SimpleNamespace,
) -> None:
    def fail_port(domain: str, _number: int) -> None:
        if domain == "port":
            raise CloudAtlasBoundaryError("cloudatlas_upstream_failed")

    assets.failure = fail_port
    result = execute(assets, submit(assets, max_pages=2))
    assert result["status"] == "PARTIAL_FAILED"
    assert listing(assets)["count"] == 1
    assert listing(assets)["version"]["complete"] is False
    assert listing(assets, "port")["state"] == "NOT_SYNCED"
    assert assets.calls == [("ip", 1), ("port", 1)]


def test_terminal_reconcile_never_publishes_unsealed_partial_staging(
    assets: SimpleNamespace,
) -> None:
    def disconnect_port(domain: str, _number: int) -> None:
        if domain == "port":
            raise CloudAtlasBoundaryError("cloudatlas_connectivity_failed")

    assets.failure = disconnect_port
    sync = submit(assets)
    assert execute(assets, sync)["status"] == "UNKNOWN"
    assets.observation = AgentComposeSessionObservation.TERMINAL
    result = assets.client.post(
        assets.path + "/syncs/" + sync["id"] + "/reconcile",
        headers=assets.headers,
    )
    assert result.json()["status"] == "FAILED"
    assert listing(assets)["state"] == "NOT_SYNCED"
    assert listing(assets, "port")["state"] == "NOT_SYNCED"
    assert assets.calls == [("ip", 1), ("port", 1)]


def test_legacy_reservation_replays_original_budget_and_remains_full_only(
    assets: SimpleNamespace,
) -> None:
    sync = submit(assets, "historical-intent")
    stored = assets.db.get(ExternalSync, uuid.UUID(sync["id"]))
    assert stored is not None
    payload = {k: v for k, v in stored.request.items() if k != "publication_mode"}
    payload["max_pages"] = 1
    stored.request = payload
    stored.request_sha256 = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assets.db.add(stored)
    assets.db.commit()
    assert submit(assets, "historical-intent", max_pages=1)["id"] == sync["id"]
    assert execute(assets, sync)["status"] == "FAILED"
    assert listing(assets)["state"] == "NOT_SYNCED"
    assert assets.calls == [("ip", 1)] and assets.starts == 1
    assert submit(assets, "historical-intent", max_pages=1)["id"] == sync["id"]
    assert assets.starts == 1


def test_odd_capacity_alternates_until_each_domain_reaches_its_own_boundary(
    assets: SimpleNamespace,
) -> None:
    result = execute(assets, submit(assets, max_records=3))
    assert result["status"] == "PARTIAL_SUCCEEDED"
    assert assets.calls == [("ip", 1), ("port", 1), ("ip", 2)]
    assert listing(assets)["version"]["complete"] is True
    assert listing(assets)["count"] == 2
    assert listing(assets, "port")["version"]["complete"] is False
    assert listing(assets, "port")["count"] == 1


def root_row(identity: int, name: str = "Example.test") -> dict[str, Any]:
    return {
        "id": str(identity),
        "root_domain": name,
        "status": "valid",
        "icp_date": None,
        "icp_num": "",
        "icp_official_name": None,
        "whois_registrant": "",
        "whois_email": None,
        "whois_expiration_time": None,
        "valid_subdomain": 7,
        "sources": [
            {"source": "synthetic", "reason": "<script>x</script>", "factor": ""}
        ],
        "created_at": "",
        "updated_at": "2026-09-25 12:00:00",
        "lastseen_at": "",
    }


@pytest.fixture
def roots(assets: SimpleNamespace, monkeypatch: MonkeyPatch) -> SimpleNamespace:
    assets.assets_path = assets.path
    assets.assets_source_id = assets.source_id
    assets.now = get_datetime_utc()
    monkeypatch.setattr(service, "get_datetime_utc", lambda: assets.now)
    monkeypatch.setattr(
        "app.api.routes.external_assets.get_datetime_utc", lambda: assets.now
    )
    assets.body["retain_until"] = (assets.now + timedelta(hours=1)).isoformat()
    monkeypatch.setattr(
        settings,
        "CLOUDATLAS_ROOT_DOMAINS_CAPSET_TOKEN",
        SecretStr("synthetic-root-token"),
    )

    def credentials(
        _self: Any, _source: SourceInstance, *, capset_token: str
    ) -> CloudAtlasFingerprint:
        assert capset_token == "synthetic-root-token"
        return CloudAtlasFingerprint("c" * 64)

    monkeypatch.setattr(
        OctobusCloudAtlasRootDomainsClient, "validate_credentials", credentials
    )
    monkeypatch.setattr(
        OctobusCloudAtlasRootDomainsClient,
        "list_page",
        OctobusCloudAtlasAssetsClient.list_page,
    )
    response = assets.client.post(
        assets.base + "/sources",
        headers=assets.headers,
        json={
            "instance_id": "synthetic-roots",
            "capset_id": "synthetic-root-capset",
            "space_id": "7",
            "capability_profile": "root-domains-v1",
        },
    )
    assert response.status_code == 201, response.text
    assets.source_id = response.json()["id"]
    assets.path = assets.base + "/sources/" + assets.source_id
    assert (
        assets.client.post(assets.path + "/validate", headers=assets.headers).json()[
            "validation_status"
        ]
        == "validated"
    )
    assert (
        assets.client.patch(
            assets.path, headers=assets.headers, json={"enabled": True}
        ).status_code
        == 200
    )
    assets.pages["root_domain"] = [[root_row(9007199254740993)], [root_row(2)]]
    return assets


def test_root_single_domain_batch_and_literal_local_search(
    roots: SimpleNamespace, monkeypatch: MonkeyPatch
) -> None:
    roots.pages["root_domain"] = [
        [
            root_row(9007199254740993 + n, "A%_\\B.test" if n < 2 else "other.test")
            for n in range(20)
        ],
        [root_row(30)],
    ]
    insufficient = roots.client.post(
        roots.path + "/syncs",
        headers=roots.headers | {"Idempotency-Key": "root-insufficient"},
        json=roots.body | {"page_size": 20, "max_pages": 1, "max_records": 19},
    )
    assert insufficient.status_code == 422 and roots.starts == 0
    sync = submit(roots, "root-batch", page_size=20, max_pages=1, max_records=20)
    assert (
        submit(roots, "root-batch", page_size=20, max_pages=1, max_records=20)["id"]
        == sync["id"]
    )
    task = execute(roots, sync)
    assert task["status"] == "PARTIAL_SUCCEEDED"
    assert [d["domain"] for d in task["domains"]] == ["root_domain"]
    assert roots.calls == [("root_domain", 1)] and roots.starts == 1
    batch = listing(roots, "root_domain")
    assert (
        batch["count"],
        batch["version"]["expected_total"],
        batch["version"]["complete"],
    ) == (20, 21, False)
    assert (batch["version"]["pages_read"], batch["version"]["stop_reason"]) == (
        1,
        "batch_limit",
    )
    for method in ("validate_credentials", "list_page"):
        monkeypatch.setattr(
            OctobusCloudAtlasRootDomainsClient,
            method,
            lambda *a, **k: pytest.fail("local read reached source"),
        )
    found = listing(roots, "root_domain", root_domain="a%_\\b", limit=1)
    assert found["count"] == 2 and len(found["data"]) == 1
    row = found["data"][0]
    assert row["source_id"] == "9007199254740993"
    assert row["ip"] is None and row["canonical_ip"] is None
    assert row["fields"] == root_row(9007199254740993, "A%_\\B.test")
    second = listing(roots, "root_domain", root_domain="a%_\\b", skip=1)["data"][0]
    assert second["source_id"] == "9007199254740994"
    assert listing(roots, "root_domain", root_domain="%missing")["count"] == 0
    url = roots.path + f"/versions/{batch['version']['id']}/records/{row['id']}"
    detail = roots.client.get(url, headers=roots.headers).json()
    assert detail["record"] == row and detail["matched_ports"] == []
    assert detail["port_version"] is None
    assert (
        roots.client.get(
            url,
            headers=roots.headers,
            params={"port_version_id": batch["version"]["id"]},
        ).status_code
        == 422
    )


def test_root_source_coexistence_scope_permissions_and_token_isolation(
    roots: SimpleNamespace,
    monkeypatch: MonkeyPatch,
    normal_user_token_headers: dict[str, str],
) -> None:
    sources = roots.client.get(roots.base + "/sources", headers=roots.headers).json()[
        "data"
    ]
    assert {s["capability_profile"] for s in sources if s["enabled"]} == {
        "assets-v1",
        "root-domains-v1",
    }
    monkeypatch.setattr(settings, "CLOUDATLAS_ASSETS_CAPSET_TOKEN", SecretStr(""))
    assert execute(roots, submit(roots))["status"] == "SUCCEEDED"
    batch = listing(roots, "root_domain")
    row = batch["data"][0]
    suffix = f"/versions/{batch['version']['id']}/records/{row['id']}"
    assert (
        roots.client.get(roots.assets_path + suffix, headers=roots.headers).status_code
        == 404
    )
    other = roots.client.post(
        roots.base + "/sources",
        headers=roots.headers,
        json={
            "instance_id": "other-roots",
            "capset_id": "other-root-capset",
            "space_id": "8",
            "capability_profile": "root-domains-v1",
        },
    )
    assert other.status_code == 201
    other_path = roots.base + "/sources/" + other.json()["id"]
    assert (
        roots.client.get(other_path + suffix, headers=roots.headers).status_code == 404
    )
    assert (
        roots.client.get(
            other_path + "/records",
            headers=roots.headers,
            params={"domain": "root_domain", "version_id": batch["version"]["id"]},
        ).status_code
        == 404
    )
    for path, domain in ((roots.path, "ip"), (roots.assets_path, "root_domain")):
        for endpoint in ("/versions", "/records"):
            assert (
                roots.client.get(
                    path + endpoint, headers=roots.headers, params={"domain": domain}
                ).status_code
                == 422
            )
    assert (
        roots.client.get(
            roots.path + "/records",
            headers=roots.headers,
            params={"domain": "root_domain", "ip": "192.0.2.1"},
        ).status_code
        == 422
    )
    add_member(roots, "viewer")
    assert (
        roots.client.get(
            roots.path + suffix, headers=normal_user_token_headers
        ).status_code
        == 200
    )
    calls = len(roots.calls)
    assert (
        roots.client.post(
            roots.path + "/syncs",
            headers=normal_user_token_headers | {"Idempotency-Key": "viewer-root"},
            json=roots.body,
        ).status_code
        == 404
    )
    assert len(roots.calls) == calls and roots.starts == 1
    monkeypatch.setattr(settings, "CLOUDATLAS_ROOT_DOMAINS_CAPSET_TOKEN", SecretStr(""))
    denied = roots.client.post(
        roots.path + "/syncs",
        headers=roots.headers | {"Idempotency-Key": "missing-root-token"},
        json=roots.body,
    )
    assert denied.status_code == 409 and roots.starts == 1
    assert (
        roots.client.patch(
            roots.path, headers=roots.headers, json={"enabled": False}
        ).status_code
        == 200
    )
    assert (
        roots.client.get(roots.path + suffix, headers=roots.headers).status_code == 200
    )
    assert (
        roots.client.patch(
            roots.path, headers=roots.headers, json={"data_access_enabled": False}
        ).status_code
        == 200
    )
    assert (
        roots.client.get(roots.path + suffix, headers=roots.headers).status_code == 403
    )


@pytest.mark.parametrize(
    "fault",
    ["required", "nested", "type", "duplicate", "total", "disconnect", "fingerprint"],
)
def test_root_unsealed_failure_keeps_prior_versions(
    roots: SimpleNamespace, monkeypatch: MonkeyPatch, fault: str
) -> None:
    assert execute(roots, submit(roots))["status"] == "SUCCEEDED"
    complete = listing(roots, "root_domain")["version"]["id"]
    roots.now += timedelta(seconds=1)
    assert execute(roots, submit(roots, max_pages=1))["status"] == "PARTIAL_SUCCEEDED"
    partial = listing(roots, "root_domain")["version"]["id"]
    roots.calls.clear()

    def fail(_domain: str, number: int) -> dict[str, Any] | None:
        if number != 2:
            return None
        row = root_row(2)
        if fault == "required":
            del row["icp_date"]
        elif fault == "nested":
            del row["sources"][0]["factor"]
        elif fault == "type":
            row["valid_subdomain"] = True
        elif fault == "duplicate":
            row["id"] = "9007199254740993"
        elif fault == "disconnect":
            raise CloudAtlasBoundaryError("cloudatlas_connectivity_failed")
        elif fault == "fingerprint":
            monkeypatch.setattr(
                OctobusCloudAtlasRootDomainsClient,
                "validate_credentials",
                lambda *a, **k: CloudAtlasFingerprint("d" * 64),
            )
        return {
            "page": 2,
            "size": 1,
            "total": 3 if fault == "total" else 2,
            "space_id": "7",
            "items": [row],
        }

    roots.failure = fail
    sync = submit(roots)
    result = execute(roots, sync)
    assert result["status"] == ("UNKNOWN" if fault == "disconnect" else "FAILED")
    assert roots.calls == [("root_domain", 1), ("root_domain", 2)]
    roots.observation = AgentComposeSessionObservation.TERMINAL
    reconciled = roots.client.post(
        roots.path + "/syncs/" + sync["id"] + "/reconcile", headers=roots.headers
    )
    assert reconciled.json()["status"] == "FAILED"
    assert listing(roots, "root_domain")["version"]["id"] == partial
    history = roots.client.get(
        roots.path + "/versions",
        headers=roots.headers,
        params={"domain": "root_domain"},
    ).json()
    assert (
        history["count"] == 2 and history["latest_complete_version"]["id"] == complete
    )
    assert roots.starts == 3 and len(roots.calls) == 2


def test_root_sealed_unknown_only_recovers_original_terminal_session(
    roots: SimpleNamespace, monkeypatch: MonkeyPatch
) -> None:
    publish = service.publish

    def interrupt(*_args: Any, **_kwargs: Any) -> None:
        raise service.SyncError("external_session_unknown", unknown=True)

    monkeypatch.setattr(service, "publish", interrupt)
    sync = submit(roots, "sealed-root", max_pages=1)
    assert execute(roots, sync)["status"] == "UNKNOWN"
    assert listing(roots, "root_domain")["state"] == "NOT_SYNCED"
    assert submit(roots, "sealed-root", max_pages=1)["id"] == sync["id"]
    assert (
        roots.client.post(
            roots.path + "/syncs",
            headers=roots.headers | {"Idempotency-Key": "replacement"},
            json=roots.body,
        ).status_code
        == 409
    )
    monkeypatch.setattr(service, "publish", publish)
    path = roots.path + "/syncs/" + sync["id"] + "/reconcile"
    assert roots.client.post(path, headers=roots.headers).json()["status"] == "UNKNOWN"
    roots.observation = AgentComposeSessionObservation.TERMINAL
    original = roots.runs[sync["agent_run_id"]]
    roots.runs[sync["agent_run_id"]] = replace(original, session_id="wrong")
    assert roots.client.post(path, headers=roots.headers).json()["status"] == "UNKNOWN"
    roots.runs[sync["agent_run_id"]] = original
    assert (
        roots.client.post(path, headers=roots.headers).json()["status"]
        == "PARTIAL_SUCCEEDED"
    )
    assert listing(roots, "root_domain")["count"] == 1
    assert roots.calls == [("root_domain", 1)] and roots.starts == 1


def test_root_complete_empty_and_expired_history_are_distinct(
    roots: SimpleNamespace,
) -> None:
    roots.pages["root_domain"] = [[]]
    assert listing(roots, "root_domain")["state"] == "NOT_SYNCED"
    assert execute(roots, submit(roots, max_pages=1))["status"] == "SUCCEEDED"
    empty = listing(roots, "root_domain")
    assert empty["state"] == "PUBLISHED" and empty["count"] == 0
    assert empty["version"]["complete"] is True
    roots.now += timedelta(seconds=1)
    roots.pages["root_domain"] = [[root_row(1)], [root_row(2)]]
    assert execute(roots, submit(roots, max_pages=1))["status"] == "PARTIAL_SUCCEEDED"
    batch = listing(roots, "root_domain")
    roots.now += timedelta(hours=2)
    expired = listing(roots, "root_domain")
    assert expired["state"] == "EXPIRED" and expired["data"] == []
    assert expired["version"]["id"] == batch["version"]["id"]
    detail = (
        roots.path
        + f"/versions/{batch['version']['id']}/records/{batch['data'][0]['id']}"
    )
    assert roots.client.get(detail, headers=roots.headers).status_code == 410
    history = roots.client.get(
        roots.path + "/versions",
        headers=roots.headers,
        params={"domain": "root_domain"},
    ).json()
    assert history["latest_complete_version"] is None


def test_root_database_guards_reject_contract_changes_and_untrusted_seals(
    roots: SimpleNamespace,
) -> None:
    sync = submit(roots, max_pages=1)
    version = roots.db.exec(
        select(ExternalAssetVersion).where(
            ExternalAssetVersion.sync_id == uuid.UUID(sync["id"])
        )
    ).one()
    parameters = {
        "version": version.id,
        "source": uuid.UUID(roots.source_id),
        "sync": uuid.UUID(sync["id"]),
    }
    statements = [
        "UPDATE source_instances SET source_type='cloudatlas' WHERE id=:source",
        "UPDATE source_instances SET source_type='cloudatlas', capability_profile='assets-v1' WHERE id=:source",
        "UPDATE external_syncs SET request=request - 'publication_mode' WHERE id=:sync",
        "UPDATE external_asset_versions SET domain='ip' WHERE id=:version",
        "UPDATE external_asset_versions SET status='PUBLISHED', complete=true, expected_total=0, pages_read=1, stop_reason='source_complete', fetched_at=now(), published_at=now() WHERE id=:version",
    ]
    for statement in statements:
        with pytest.raises(SQLAlchemyError), roots.db.begin_nested():
            roots.db.execute(text(statement), parameters)
    roots.db.execute(
        text("UPDATE external_asset_versions SET status='RUNNING' WHERE id=:version"),
        parameters,
    )
    for fields, ip in (
        (root_row(1), "192.0.2.1"),
        ({"id": "1", "root_domain": "missing.test"}, None),
    ):
        with pytest.raises(SQLAlchemyError), roots.db.begin_nested():
            roots.db.add(
                ExternalAssetRecord(
                    version_id=version.id, source_id="1", ip=ip, fields=fields
                )
            )
            roots.db.flush()
    roots.db.rollback()
    assert execute(roots, sync)["status"] == "PARTIAL_SUCCEEDED"
    batch = listing(roots, "root_domain")
    parameters["record"] = uuid.UUID(batch["data"][0]["id"])
    for statement in (
        "UPDATE external_asset_records SET fields='{}'::jsonb WHERE id=:record",
        "DELETE FROM external_asset_records WHERE id=:record",
        "UPDATE external_asset_versions SET complete=true WHERE id=:version",
    ):
        with pytest.raises(SQLAlchemyError), roots.db.begin_nested():
            roots.db.execute(text(statement), parameters)


def test_root_database_rejects_expired_seal_and_legacy_null_addresses(
    roots: SimpleNamespace,
) -> None:
    roots.path = roots.assets_path
    assets_sync = submit(roots)
    asset_version = roots.db.exec(
        select(ExternalAssetVersion).where(
            ExternalAssetVersion.sync_id == uuid.UUID(assets_sync["id"]),
            ExternalAssetVersion.domain == "ip",
        )
    ).one()
    asset_version.status = "RUNNING"
    roots.db.add(asset_version)
    roots.db.flush()
    with pytest.raises(SQLAlchemyError), roots.db.begin_nested():
        roots.db.add(
            ExternalAssetRecord(version_id=asset_version.id, source_id="1", fields={})
        )
        roots.db.flush()
    roots.db.rollback()
    roots.path = roots.base + "/sources/" + roots.source_id
    roots.now -= timedelta(days=2)
    sync = submit(roots, retain_until=(roots.now + timedelta(hours=1)).isoformat())
    version = roots.db.exec(
        select(ExternalAssetVersion).where(
            ExternalAssetVersion.sync_id == uuid.UUID(sync["id"])
        )
    ).one()
    version.status = "RUNNING"
    version.complete = True
    version.expected_total = 0
    version.pages_read = 1
    version.stop_reason = "source_complete"
    version.fetched_at = roots.now
    roots.db.add(version)
    roots.db.flush()
    with pytest.raises(SQLAlchemyError), roots.db.begin_nested():
        roots.db.add(
            ExternalAssetRecord(
                version_id=version.id, source_id="1", fields=root_row(1)
            )
        )
        roots.db.flush()
    with pytest.raises(SQLAlchemyError), roots.db.begin_nested():
        roots.db.execute(
            text(
                "UPDATE external_asset_versions SET status='PUBLISHED', published_at=now() WHERE id=:id"
            ),
            {"id": version.id},
        )


@pytest.fixture
def dns_assets(roots: SimpleNamespace, monkeypatch: MonkeyPatch) -> SimpleNamespace:
    roots.root_path = roots.path
    monkeypatch.setattr(
        settings, "CLOUDATLAS_DNS_CAPSET_TOKEN", SecretStr("synthetic-dns-token")
    )

    def credentials(
        _self: Any, _source: SourceInstance, *, capset_token: str
    ) -> CloudAtlasFingerprint:
        assert capset_token == "synthetic-dns-token"
        return CloudAtlasFingerprint("e" * 64)

    monkeypatch.setattr(OctobusCloudAtlasDNSClient, "validate_credentials", credentials)
    response = roots.client.post(
        roots.base + "/sources",
        headers=roots.headers,
        json={
            "instance_id": "synthetic-dns",
            "capset_id": "dns-only",
            "space_id": "7",
            "capability_profile": "dns-v1",
        },
    )
    assert response.status_code == 201, response.text
    roots.source_id = response.json()["id"]
    roots.path = roots.base + "/sources/" + roots.source_id
    assert (
        roots.client.post(roots.path + "/validate", headers=roots.headers).json()[
            "validation_status"
        ]
        == "validated"
    )
    assert (
        roots.client.patch(
            roots.path, headers=roots.headers, json={"enabled": True}
        ).status_code
        == 200
    )
    roots.pages["dns"] = [[dns_row()], [dns_row(2)]]
    return roots


def test_dns_single_domain_literal_search_identity_and_offline_detail(
    dns_assets: SimpleNamespace,
    monkeypatch: MonkeyPatch,
) -> None:
    state = dns_assets
    state.pages["dns"] = [
        [
            dns_row(9007199254740993 + n, "A%_\\B.test" if n < 2 else "other.test")
            for n in range(20)
        ],
        [dns_row(30)],
    ]
    sync = submit(state, "dns-batch", page_size=20, max_pages=1, max_records=20)
    assert (
        submit(state, "dns-batch", page_size=20, max_pages=1, max_records=20)["id"]
        == sync["id"]
    )
    reserved = state.db.get(ExternalSync, uuid.UUID(sync["id"]))
    assert reserved is not None and reserved.request["flat"] == "1"
    result = execute(state, sync)
    assert result["status"] == "PARTIAL_SUCCEEDED"
    assert [d["domain"] for d in result["domains"]] == ["dns"]
    assert state.calls == [("dns", 1)] and state.starts == 1
    batch = listing(state, "dns")
    assert (
        batch["count"],
        batch["version"]["expected_total"],
        batch["version"]["complete"],
    ) == (20, 21, False)
    assert batch["version"]["filter"] == {"flat": "1", "status": "valid"}
    for method in ("validate_credentials", "list_page"):
        monkeypatch.setattr(
            OctobusCloudAtlasDNSClient,
            method,
            lambda *a, **k: pytest.fail("local DNS read reached source"),
        )
    found = listing(state, "dns", subdomain="a%_\\b", limit=1)
    row = found["data"][0]
    assert found["count"] == 2 and row["fields"] == dns_row(
        9007199254740993, "A%_\\B.test"
    )
    assert row["ip"] is None and row["canonical_ip"] is None
    assert (
        listing(state, "dns", subdomain="a%_\\b", skip=1)["data"][0]["source_id"]
        == "9007199254740994"
    )
    assert listing(state, "dns", subdomain="2001:db8")["count"] == 0
    detail = state.client.get(
        state.path + f"/versions/{batch['version']['id']}/records/{row['id']}",
        headers=state.headers,
    ).json()
    assert (
        detail["record"] == row
        and detail["matched_ports"] == []
        and detail["port_version"] is None
    )


@pytest.mark.parametrize(
    "fault",
    [
        "bu",
        "missing",
        "tags",
        "duplicate",
        "total",
        "early-empty",
        "page",
        "overflow",
        "disconnect",
        "fingerprint",
    ],
)
def test_dns_unsealed_failure_preserves_complete_and_partial_history(
    dns_assets: SimpleNamespace,
    monkeypatch: MonkeyPatch,
    fault: str,
) -> None:
    state = dns_assets
    assert execute(state, submit(state))["status"] == "SUCCEEDED"
    complete = listing(state, "dns")["version"]["id"]
    state.now += timedelta(seconds=1)
    assert execute(state, submit(state, max_pages=1))["status"] == "PARTIAL_SUCCEEDED"
    partial = listing(state, "dns")["version"]["id"]
    state.calls.clear()

    def failure(_domain: str, number: int) -> dict[str, Any] | None:
        if number != 2:
            return None
        row = dns_row(2)
        if fault == "bu":
            row["bu"] = ""
        elif fault == "missing":
            del row["record"]
        elif fault == "tags":
            row["tags"] = [{"pk": "1"}]
        elif fault == "duplicate":
            row["id"] = "9007199254740993"
        elif fault == "disconnect":
            raise CloudAtlasBoundaryError("cloudatlas_connectivity_failed")
        elif fault == "fingerprint":
            monkeypatch.setattr(
                OctobusCloudAtlasDNSClient,
                "validate_credentials",
                lambda *a, **k: CloudAtlasFingerprint("f" * 64),
            )
        return {
            "page": 3 if fault == "page" else 2,
            "size": 1,
            "total": 3 if fault == "total" else 2,
            "space_id": "7",
            "items": []
            if fault == "early-empty"
            else [row, dns_row(3)]
            if fault == "overflow"
            else [row],
        }

    state.failure = failure
    sync = submit(state)
    assert execute(state, sync)["status"] == (
        "UNKNOWN" if fault == "disconnect" else "FAILED"
    )
    state.observation = AgentComposeSessionObservation.TERMINAL
    assert (
        state.client.post(
            state.path + "/syncs/" + sync["id"] + "/reconcile", headers=state.headers
        ).json()["status"]
        == "FAILED"
    )
    history = state.client.get(
        state.path + "/versions", headers=state.headers, params={"domain": "dns"}
    ).json()
    assert (
        history["count"] == 2 and history["latest_complete_version"]["id"] == complete
    )
    assert listing(state, "dns")["version"]["id"] == partial
    assert state.calls == [("dns", 1), ("dns", 2)] and state.starts == 3


def test_dns_original_session_only_recovers_trusted_seal(
    dns_assets: SimpleNamespace, monkeypatch: MonkeyPatch
) -> None:
    state = dns_assets
    publish = service.publish

    def interrupt(*_a: Any, **_k: Any) -> None:
        raise service.SyncError("external_session_unknown", unknown=True)

    monkeypatch.setattr(service, "publish", interrupt)
    sync = submit(state, "dns-sealed", max_pages=1)
    assert execute(state, sync)["status"] == "UNKNOWN"
    assert listing(state, "dns")["state"] == "NOT_SYNCED"
    assert submit(state, "dns-sealed", max_pages=1)["id"] == sync["id"]
    assert (
        state.client.post(
            state.path + "/syncs",
            headers=state.headers | {"Idempotency-Key": "replacement"},
            json=state.body,
        ).status_code
        == 409
    )
    monkeypatch.setattr(service, "publish", publish)
    path = state.path + "/syncs/" + sync["id"] + "/reconcile"
    assert state.client.post(path, headers=state.headers).json()["status"] == "UNKNOWN"
    state.observation = AgentComposeSessionObservation.TERMINAL
    original = state.runs[sync["agent_run_id"]]
    state.runs[sync["agent_run_id"]] = replace(original, session_id="wrong")
    assert state.client.post(path, headers=state.headers).json()["status"] == "UNKNOWN"
    state.runs[sync["agent_run_id"]] = original
    assert (
        state.client.post(path, headers=state.headers).json()["status"]
        == "PARTIAL_SUCCEEDED"
    )
    assert (
        listing(state, "dns")["count"] == 1
        and state.calls == [("dns", 1)]
        and state.starts == 1
    )


def test_dns_scope_roles_archival_and_separate_token(
    dns_assets: SimpleNamespace,
    monkeypatch: MonkeyPatch,
    normal_user_token_headers: dict[str, str],
) -> None:
    state = dns_assets
    profiles = state.client.get(state.base + "/sources", headers=state.headers).json()[
        "data"
    ]
    assert {s["capability_profile"] for s in profiles if s["enabled"]} == {
        "assets-v1",
        "root-domains-v1",
        "dns-v1",
    }
    monkeypatch.setattr(settings, "CLOUDATLAS_ASSETS_CAPSET_TOKEN", SecretStr(""))
    monkeypatch.setattr(settings, "CLOUDATLAS_ROOT_DOMAINS_CAPSET_TOKEN", SecretStr(""))
    assert execute(state, submit(state))["status"] == "SUCCEEDED"
    batch = listing(state, "dns")
    suffix = f"/versions/{batch['version']['id']}/records/{batch['data'][0]['id']}"
    for other_path in (state.assets_path, state.root_path):
        assert (
            state.client.get(other_path + suffix, headers=state.headers).status_code
            == 404
        )
        assert (
            state.client.get(
                other_path + "/records", headers=state.headers, params={"domain": "dns"}
            ).status_code
            == 422
        )
    for params in (
        {"domain": "ip"},
        {"domain": "root_domain"},
        {"domain": "dns", "ip": "192.0.2.1"},
        {"domain": "dns", "root_domain": "test"},
    ):
        assert (
            state.client.get(
                state.path + "/records", headers=state.headers, params=params
            ).status_code
            == 422
        )
    assert (
        state.client.get(
            state.path + suffix,
            headers=state.headers,
            params={"port_version_id": batch["version"]["id"]},
        ).status_code
        == 422
    )
    member = add_member(state, "viewer")
    assert (
        state.client.get(
            state.path + suffix, headers=normal_user_token_headers
        ).status_code
        == 200
    )
    assert (
        state.client.post(
            state.path + "/syncs",
            headers=normal_user_token_headers | {"Idempotency-Key": "viewer-dns"},
            json=state.body,
        ).status_code
        == 404
    )
    state.db.delete(member)
    state.db.commit()
    assert (
        state.client.get(
            state.path + suffix, headers=normal_user_token_headers
        ).status_code
        == 404
    )
    monkeypatch.setattr(settings, "CLOUDATLAS_DNS_CAPSET_TOKEN", SecretStr(""))
    assert (
        state.client.post(
            state.path + "/syncs",
            headers=state.headers | {"Idempotency-Key": "zero-token"},
            json=state.body,
        ).status_code
        == 409
    )
    assert (
        state.client.patch(
            state.path, headers=state.headers, json={"enabled": False}
        ).status_code
        == 200
    )
    assert (
        state.client.get(state.path + suffix, headers=state.headers).status_code == 200
    )
    project = state.db.get(Project, uuid.UUID(state.project_id))
    assert project is not None
    project.archived_at = get_datetime_utc()
    state.db.add(project)
    state.db.commit()
    assert (
        state.client.get(state.path + suffix, headers=state.headers).status_code == 200
    )
    assert (
        state.client.post(
            state.path + "/syncs",
            headers=state.headers | {"Idempotency-Key": "archived-dns"},
            json=state.body,
        ).status_code
        == 409
    )
    source = state.db.get(SourceInstance, uuid.UUID(state.source_id))
    assert source is not None
    source.data_access_enabled = False
    state.db.add(source)
    state.db.commit()
    assert (
        state.client.get(state.path + suffix, headers=state.headers).status_code == 403
    )
    assert state.starts == 1 and state.calls == [("dns", 1), ("dns", 2)]


def test_dns_empty_expiry_and_source_scoped_cleanup(
    dns_assets: SimpleNamespace,
) -> None:
    state = dns_assets
    dns_path = state.path
    state.path = state.root_path
    assert execute(state, submit(state))["status"] == "SUCCEEDED"
    root_version = uuid.UUID(listing(state, "root_domain")["version"]["id"])
    state.path = dns_path
    state.pages["dns"] = [[]]
    assert listing(state, "dns")["state"] == "NOT_SYNCED"
    assert execute(state, submit(state, max_pages=1))["status"] == "SUCCEEDED"
    empty = listing(state, "dns")
    assert (
        empty["state"] == "PUBLISHED"
        and empty["count"] == 0
        and empty["version"]["complete"]
    )
    state.pages["dns"] = [[dns_row()]]
    assert (
        execute(
            state,
            submit(
                state,
                max_pages=1,
                retain_until=(get_datetime_utc() + timedelta(seconds=2)).isoformat(),
            ),
        )["status"]
        == "SUCCEEDED"
    )
    batch = listing(state, "dns")
    state.db.execute(text("SELECT pg_sleep(2)"))
    state.db.commit()
    state.now += timedelta(hours=2)
    assert listing(state, "dns")["state"] == "EXPIRED"
    suffix = f"/versions/{batch['version']['id']}/records/{batch['data'][0]['id']}"
    assert (
        state.client.get(state.path + suffix, headers=state.headers).status_code == 410
    )
    assert state.client.post(
        state.path + "/purge-expired", headers=state.headers
    ).json() == {"deleted_records": 1}
    assert (
        state.db.exec(
            select(ExternalAssetRecord).where(
                ExternalAssetRecord.version_id == uuid.UUID(batch["version"]["id"])
            )
        ).all()
        == []
    )
    assert (
        len(
            state.db.exec(
                select(ExternalAssetRecord).where(
                    ExternalAssetRecord.version_id == root_version
                )
            ).all()
        )
        == 2
    )


def test_dns_database_guards_freeze_flat_scope_and_refuse_false_seals(
    dns_assets: SimpleNamespace,
) -> None:
    state = dns_assets
    sync = submit(state, max_pages=1)
    version = state.db.exec(
        select(ExternalAssetVersion).where(
            ExternalAssetVersion.sync_id == uuid.UUID(sync["id"])
        )
    ).one()
    params = {
        "source": uuid.UUID(state.source_id),
        "sync": uuid.UUID(sync["id"]),
        "version": version.id,
    }
    for statement in (
        "UPDATE source_instances SET source_type='cloudatlas', capability_profile='assets-v1' WHERE id=:source",
        "UPDATE external_syncs SET request=jsonb_set(request, '{flat}', '\"0\"') WHERE id=:sync",
        'UPDATE external_asset_versions SET filter=\'{"status":"valid"}\'::jsonb WHERE id=:version',
        "UPDATE external_asset_versions SET domain='root_domain' WHERE id=:version",
        "UPDATE external_asset_versions SET status='PUBLISHED', complete=true, expected_total=0, pages_read=1, stop_reason='source_complete', fetched_at=now(), published_at=now() WHERE id=:version",
    ):
        with pytest.raises(SQLAlchemyError), state.db.begin_nested():
            state.db.execute(text(statement), params)
    state.db.execute(
        text("UPDATE external_asset_versions SET status='RUNNING' WHERE id=:version"),
        params,
    )
    for fields, ip in (
        (dns_row(1), "2001:db8::1"),
        ({**dns_row(1), "bu": {}}, None),
        ({**dns_row(1), "bu": ""}, None),
        ({**dns_row(1), "bu": {"id": 1, "name": ""}}, None),
        ({**dns_row(1), "bu": {"id": "1", "name": None}}, None),
        ({**dns_row(1), "bu": {"id": "9" * 101, "name": ""}}, None),
        ({**dns_row(1), "tags": [{"pk": "1"}]}, None),
    ):
        with pytest.raises(SQLAlchemyError), state.db.begin_nested():
            state.db.add(
                ExternalAssetRecord(
                    version_id=version.id, source_id="1", ip=ip, fields=fields
                )
            )
            state.db.flush()
    state.db.rollback()
    assert execute(state, sync)["status"] == "PARTIAL_SUCCEEDED"


@pytest.mark.parametrize(
    ("fixture_name", "domain", "name_field"),
    [
        ("assets", "ip", None),
        ("assets", "port", None),
        ("roots", "root_domain", "root_domain"),
        ("dns_assets", "dns", "subdomain"),
    ],
)
def test_lossless_projection_guards_cover_all_writers_and_domains(
    request: pytest.FixtureRequest,
    fixture_name: str,
    domain: str,
    name_field: str | None,
) -> None:
    state = request.getfixturevalue(fixture_name)
    sync = submit(state)
    version = state.db.exec(
        select(ExternalAssetVersion).where(
            ExternalAssetVersion.sync_id == uuid.UUID(sync["id"]),
            ExternalAssetVersion.domain == domain,
        )
    ).one()
    fields = json.loads(json.dumps(state.pages[domain][0][0]))
    version.status = "RUNNING"
    state.db.add(version)
    state.db.flush()
    fields["id"] = "701"
    fields["status"] = "valid"
    if domain == "port":
        fields["banner"] = "synthetic\0\0banner"
    elif name_field:
        fields[name_field] = "a\x01%_\\\0\0B\x02.test"
    else:
        fields["bu"] = {"id": "1", "name": "synthetic\0tag"}
    ip = fields.get("ip")
    canonical = "2001:db8::1" if ip else None
    record = ExternalAssetRecord(
        version_id=version.id,
        source_id=fields["id"],
        ip=ip,
        canonical_ip=canonical,
        fields=fields,
    )
    state.db.add(record)
    state.db.flush()
    state.db.refresh(record)
    assert record.fields == fields
    assert record.status_segments == ["valid"]
    if name_field:
        assert getattr(record, f"{name_field}_segments") == fields[name_field].split(
            "\0"
        )
        for term, expected in [
            ("%_\\\0\0b", True),
            ("\0\0", True),
            ("\\u0000", False),
            ("aB", False),
        ]:
            result = state.db.execute(
                text(
                    f"SELECT external_asset_segments_icontains({name_field}_segments, "
                    "CAST(:query AS text[])) FROM external_asset_records WHERE id=:id"
                ),
                {"id": record.id, "query": term.split("\0")},
            ).scalar_one()
            assert result is expected

    # Raw legacy SQL callers also receive canonical single-segment projections.
    plain = json.loads(json.dumps(fields))
    plain["id"] = "702"
    if name_field:
        plain[name_field] = "plain.example"
    new_id = uuid.uuid4()
    statement = text(
        "INSERT INTO external_asset_records "
        "(id, version_id, source_id, ip, canonical_ip, fields, status_segments) "
        "VALUES (:id, :version, :source, :ip, :canonical, CAST(:fields AS json), "
        "CAST(:segments AS text[]))"
    )
    params = {
        "id": new_id,
        "version": version.id,
        "source": plain["id"],
        "ip": ip,
        "canonical": canonical,
        "fields": json.dumps(plain),
        "segments": None,
    }
    state.db.execute(statement, params)
    loaded = state.db.get(ExternalAssetRecord, new_id)
    assert loaded is not None and loaded.status_segments == ["valid"]
    if name_field:
        assert getattr(loaded, f"{name_field}_segments") == ["plain.example"]
    for false_projection in (["forged"], [], [None]):
        with (
            pytest.raises(SQLAlchemyError, match="projection mismatch"),
            state.db.begin_nested(),
        ):
            state.db.execute(
                statement,
                params
                | {
                    "id": uuid.uuid4(),
                    "source": "703",
                    "fields": json.dumps(plain | {"id": "703"}),
                    "segments": false_projection,
                },
            )
    state.db.rollback()
