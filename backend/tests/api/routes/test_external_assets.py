"""Synthetic-only regression checks at the local HTTP/worker publication boundary."""

import hashlib
import sys
import uuid
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlmodel import Session, col, select

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
    AgentComposeClient,
    AgentComposeRunStart,
    AgentComposeSession,
    AgentComposeSessionObservation,
)
from app.integrations.cloudatlas_assets import OctobusCloudAtlasAssetsClient
from app.models import User


@pytest.fixture
def assets(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> SimpleNamespace:
    now = get_datetime_utc() - timedelta(days=2)
    monkeypatch.setattr(service, "get_datetime_utc", lambda: now)
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
    return state


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


@pytest.mark.parametrize(
    "fault",
    ["late_page", "duplicate", "total_changed", "early_empty", "budget", "fingerprint"],
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
    result = execute(
        assets,
        submit(assets, max_pages=3 if fault == "budget" else assets.body["max_pages"]),
    )
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
    user = assets.db.exec(
        select(User).where(User.email == settings.EMAIL_TEST_USER)
    ).one()
    member = ProjectMembership(
        project_id=uuid.UUID(assets.project_id), user_id=user.id, roles=["viewer"]
    )
    assets.db.add(member)
    assets.db.commit()
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


def test_terminal_same_session_recovers_complete_stage_without_source_retry(
    assets: SimpleNamespace, monkeypatch: MonkeyPatch
) -> None:
    publish = service.publish

    def interrupt(*_args: Any, **_kwargs: Any) -> None:
        raise service.SyncError("external_session_unknown", unknown=True)

    monkeypatch.setattr(service, "publish", interrupt)
    sync = submit(assets)
    assert execute(assets, sync)["status"] == "UNKNOWN"
    assert listing(assets)["state"] == "NOT_SYNCED"
    calls = list(assets.calls)
    monkeypatch.setattr(service, "publish", publish)
    assets.observation = AgentComposeSessionObservation.TERMINAL
    response = assets.client.post(
        assets.path + "/syncs/" + sync["id"] + "/reconcile", headers=assets.headers
    )
    assert response.json()["status"] == "PARTIAL_FAILED"
    assert listing(assets)["count"] == 2
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


def test_record_budget_prevents_an_unaffordable_next_domain_page(
    assets: SimpleNamespace,
) -> None:
    assets.pages["ip"] = [[record for page in assets.pages["ip"] for record in page]]
    assets.pages["port"] = [
        assets.pages["port"][0] + assets.pages["port"][1],
        assets.pages["port"][2],
    ]
    assert (
        execute(assets, submit(assets, page_size=2, max_records=6))["status"]
        == "SUCCEEDED"
    )
    previous_port = listing(assets, "port")["version"]["id"]
    assets.calls.clear()
    result = execute(assets, submit(assets, page_size=2, max_records=3))
    assert result["status"] == "PARTIAL_FAILED"
    assert assets.calls == [("ip", 1)]
    assert result["domains"][1]["error_code"] == "external_record_budget"
    assert listing(assets, "port")["version"]["id"] == previous_port
