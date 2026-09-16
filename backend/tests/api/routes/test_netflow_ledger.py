import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from tests.api.routes.test_netflow_datasets import _member, _project, _upload

HEADER = b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
ROWS = b"2001:0DB8:10::25,2001:db8:ffff::9,6,1234,443\n2001:db8:10::25,2001:db8:ffff::9,6,1234,443\n2001:db8:10::25,2001:db8:10::25,17,53,53\n::ffff:192.0.2.8,2001:db8:10::26,6,1,2\nbad-ip,2001:db8:10::25,6,1,2\n"


@pytest.fixture
def ledger(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    p = _project(client, superuser_token_headers)
    response = _upload(client, superuser_token_headers, p["id"], HEADER + ROWS)
    assert response.status_code == 201, response.text
    return f"/api/v1/projects/{p['id']}", superuser_token_headers, response.json()


def scope(dataset: dict[str, Any], revision: int = 0, **extra: Any) -> dict[str, Any]:
    return dict(
        dataset_id=dataset["id"],
        expected_revision=revision,
        kind="scope",
        namespace="lab",
        cidrs=["2001:db8:10::/64"],
        collector="synthetic",
        location="lab",
        evidence="synthetic documentation fixture",
        viewpoint="PUBLIC",
        scope_status="CONFIRMED",
        reason="synthetic only",
        **extra,
    )


def write(
    client: TestClient,
    root: str,
    headers: dict[str, str],
    body: dict[str, Any],
    key: str | None = None,
) -> Any:
    return client.post(
        root + "/netflow-ledger/revisions",
        headers={**headers, "Idempotency-Key": key or str(uuid.uuid4())},
        json=body,
    )


def read(
    client: TestClient,
    ledger: tuple[str, dict[str, str], dict[str, Any]],
    **params: Any,
) -> dict[str, Any]:
    root, headers, dataset = ledger
    r = client.get(
        root + "/netflow-ledger",
        headers=headers,
        params={"dataset_id": dataset["id"], **params},
    )
    assert r.status_code == 200, r.text
    return cast(dict[str, Any], r.json())


def test_native_counts_scope_revoke_and_profile(
    client: TestClient, ledger: tuple[str, dict[str, str], dict[str, Any]], db: Session
) -> None:
    root, headers, dataset = ledger
    before = db.execute(text("select count(*) from resources")).scalar_one()
    page = read(client, ledger)
    assert (
        page["raw_records"] == 5
        and page["valid_records"] == 4
        and page["isolated_records"] == 1
    )
    assert page["count"] == 4
    ipv6 = read(client, ledger, ip="2001:0db8:10::25")["data"][0]
    assert (
        ipv6["flow_count"] == 3
        and ipv6["roles"] == ["dst", "src"]
        and ipv6["source_record_keys"] == ["row:1", "row:2", "row:3"]
    )
    assert ipv6["first_seen_utc"] is None and ipv6["candidate_id"] is None
    assert write(client, root, headers, scope(dataset)).status_code == 201
    eligible = read(client, ledger, candidate=True)
    assert eligible["count"] == 2
    assert (
        read(client, ledger, ip="2001:db8:ffff::9")["data"][0]["candidate_state"]
        == "EXTERNAL_PEER"
    )
    assert (
        read(client, ledger, ip="::ffff:192.0.2.8")["data"][0]["candidate_state"]
        == "NOT_IPV6"
    )
    profile = client.get(
        root + "/netflow-ledger/profile",
        headers=headers,
        params={"dataset_id": dataset["id"], "ip": "2001:db8:10::25", "revision": 1},
    ).json()
    assert (
        profile["resource_id"] is None
        and profile["customer"] is None
        and profile["cloud"] is None
        and profile["risk_state"] == "NOT_CONNECTED"
    )
    revoke = {**scope(dataset, 1), "scope_status": "REVOKED"}
    assert write(client, root, headers, revoke).status_code == 201
    assert read(client, ledger, revision=1, candidate=True)["count"] == 0
    assert (
        read(client, ledger, revision=1, ip="2001:db8:10::25")["data"][0][
            "candidate_state"
        ]
        == "REVOKED"
    )
    historical = read(client, ledger, revision=1, ip="2001:db8:10::25")["data"][0]
    assert historical["historical_candidate_state"] == "CANDIDATE"
    assert historical["candidate_state"] == "REVOKED"
    assert db.execute(text("select count(*) from resources")).scalar_one() == before


def test_identity_cross_dataset_management_and_namespace(
    client: TestClient, ledger: tuple[str, dict[str, str], dict[str, Any]]
) -> None:
    root, headers, dataset = ledger
    assert write(client, root, headers, scope(dataset)).status_code == 201
    row = read(client, ledger, ip="2001:db8:10::25")["data"][0]
    manage = {
        "dataset_id": dataset["id"],
        "expected_revision": 1,
        "kind": "management",
        "namespace": "lab",
        "canonical_ip": row["canonical_ip"],
        "followed": True,
        "excluded": True,
        "reason": "local investigation",
    }
    assert write(client, root, headers, manage).status_code == 201
    d2 = _upload(
        client,
        headers,
        root.split("/")[-1],
        HEADER + b"2001:db8:10::25,2001:db8:ffff::9,6,1235,443\n",
    ).json()
    assert write(client, root, headers, scope(d2, 2)).status_code == 201
    fresh = read(client, (root, headers, d2), ip=row["canonical_ip"])["data"][0]
    assert (
        fresh["candidate_id"] == row["candidate_id"]
        and fresh["followed"]
        and fresh["candidate_state"] == "EXCLUDED"
    )
    assert read(client, (root, headers, d2), candidate=True)["count"] == 0
    assert (
        write(
            client, root, headers, {**scope(d2, 3), "namespace": "separate"}
        ).status_code
        == 201
    )
    changed = read(client, (root, headers, d2), ip=row["canonical_ip"])["data"][0]
    assert changed["candidate_id"] != row["candidate_id"] and not changed["followed"]
    assert read(client, (root, headers, d2), revision=3, candidate=True)["count"] == 0


def test_concurrency_replay_permissions_and_foreign_scope(
    client: TestClient, ledger: tuple[str, dict[str, str], dict[str, Any]]
) -> None:
    root, headers, dataset = ledger
    body = scope(dataset)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda _: write(client, root, headers, body), range(2))
        )
    assert sorted(r.status_code for r in responses) == [201, 409]
    key = str(uuid.uuid4())
    body = {**body, "expected_revision": 1, "scope_status": "UNKNOWN"}
    first = write(client, root, headers, body, key)
    assert first.status_code == 201
    assert write(client, root, headers, body, key).json() == first.json()
    assert (
        write(client, root, headers, {**body, "reason": "different"}, key).status_code
        == 409
    )
    assert (
        client.get(root + "/netflow-ledger/operations/" + key, headers=headers).json()
        == first.json()
    )
    for role in ["viewer", "approver", "operator"]:
        member = _member(client, headers, root.split("/")[-1], [role])
        assert (
            client.get(
                root + "/netflow-ledger",
                headers=member,
                params={"dataset_id": dataset["id"]},
            ).status_code
            == 200
        )
        assert (
            write(client, root, member, {**body, "expected_revision": 2}).status_code
            == 403
        )
        assert (
            client.get(
                root + "/netflow-ledger/operations/" + key, headers=member
            ).status_code
            == 404
        )
    foreign = _project(client, headers)
    assert (
        client.get(
            f"/api/v1/projects/{foreign['id']}/netflow-ledger",
            headers=headers,
            params={"dataset_id": dataset["id"]},
        ).status_code
        == 404
    )
    assert (
        write(
            client,
            root,
            headers,
            {**body, "expected_revision": 2, "cidrs": ["not-a-network"]},
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "content,state",
    [(HEADER, "EMPTY"), (HEADER + b"bad,also-bad,6,1,2\n", "NO_POSITIVE_EVIDENCE")],
)
def test_empty_and_isolated(
    client: TestClient,
    ledger: tuple[str, dict[str, str], dict[str, Any]],
    content: bytes,
    state: str,
) -> None:
    root, headers, _ = ledger
    dataset = _upload(client, headers, root.split("/")[-1], content).json()
    assert read(client, (root, headers, dataset))["state"] == state
    assert (
        client.get(
            root + "/netflow-ledger",
            headers=headers,
            params={"dataset_id": dataset["id"], "ip": "2001:db8:missing::1"},
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "address,expected",
    [
        ("::1", "INELIGIBLE_ADDRESS"),
        ("::", "INELIGIBLE_ADDRESS"),
        ("ff02::1", "INELIGIBLE_ADDRESS"),
        ("fe80::1", "INELIGIBLE_ADDRESS"),
        ("fd00::1", "INELIGIBLE_ADDRESS"),
        ("::ffff:192.0.2.8", "NOT_IPV6"),
    ],
)
def test_special_addresses(
    client: TestClient,
    ledger: tuple[str, dict[str, str], dict[str, Any]],
    address: str,
    expected: str,
) -> None:
    root, headers, _ = ledger
    d = _upload(
        client,
        headers,
        root.split("/")[-1],
        HEADER + f"{address},2001:db8:ffff::9,6,1234,443\n".encode(),
    ).json()
    assert (
        write(
            client, root, headers, {**scope(d), "cidrs": ["::/0", "0.0.0.0/0"]}
        ).status_code
        == 201
    )
    assert (
        read(client, (root, headers, d), ip=address)["data"][0]["candidate_state"]
        == expected
    )


@pytest.mark.parametrize(
    "status,viewpoint,expected",
    [
        ("UNKNOWN", "PUBLIC", "PENDING_SCOPE"),
        ("CONFLICT", "PUBLIC", "CONFLICT"),
        ("REVOKED", "PUBLIC", "REVOKED"),
        ("CONFIRMED", "INTERNAL", "VIEWPOINT_UNSUPPORTED"),
        ("CONFIRMED", "UNKNOWN", "PENDING_SCOPE"),
    ],
)
def test_scope_states(
    client: TestClient,
    ledger: tuple[str, dict[str, str], dict[str, Any]],
    status: str,
    viewpoint: str,
    expected: str,
) -> None:
    root, headers, d = ledger
    assert (
        write(
            client,
            root,
            headers,
            {**scope(d), "scope_status": status, "viewpoint": viewpoint},
        ).status_code
        == 201
    )
    assert (
        read(client, ledger, ip="2001:db8:10::25")["data"][0]["candidate_state"]
        == expected
    )
    assert read(client, ledger, candidate=True)["count"] == 0


def test_operator_management_page_two_archive_and_revoke(
    client: TestClient, ledger: tuple[str, dict[str, str], dict[str, Any]]
) -> None:
    root, headers, _ = ledger
    content = HEADER + b"".join(
        f"2001:db8:10::{i:x},2001:db8:ffff::9,6,1234,443\n".encode()
        for i in range(1, 61)
    )
    d = _upload(client, headers, root.split("/")[-1], content).json()
    assert write(client, root, headers, scope(d)).status_code == 201
    operator = _member(client, headers, root.split("/")[-1], ["operator"])
    body = {
        "dataset_id": d["id"],
        "expected_revision": 1,
        "kind": "management",
        "namespace": "lab",
        "canonical_ip": "2001:db8:10::3c",
        "followed": True,
        "excluded": True,
        "reason": "explicit operator handling",
    }
    assert write(client, root, operator, body).status_code == 201
    row = read(client, (root, headers, d), ip=body["canonical_ip"])["data"][0]
    assert row["followed"] and row["candidate_state"] == "EXCLUDED"
    viewer = _member(client, headers, root.split("/")[-1], ["viewer"])
    assert (
        write(client, root, viewer, {**body, "expected_revision": 2}).status_code == 404
    )
    assert (
        write(
            client,
            root,
            operator,
            {**body, "expected_revision": 2, "namespace": "other"},
        ).status_code
        == 409
    )
    assert client.post(root + "/archive", headers=headers).status_code == 200
    assert (
        write(client, root, operator, {**body, "expected_revision": 2}).status_code
        == 409
    )


def test_integrity_projection_failure_and_read_only(
    client: TestClient,
    ledger: tuple[str, dict[str, str], dict[str, Any]],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain import netflow_ledger as service
    from app.domain.models import Artifact, NetFlowDataset

    root, headers, d = ledger
    before = db.execute(
        text("select count(*) from netflow_ledger_revisions")
    ).scalar_one()
    assert read(client, ledger)["count"] == 4
    assert (
        db.execute(text("select count(*) from netflow_ledger_revisions")).scalar_one()
        == before
    )
    dataset = db.get(NetFlowDataset, uuid.UUID(d["id"]))
    assert dataset is not None
    artifact = db.get(Artifact, dataset.normalized_artifact_id)
    assert artifact is not None
    path = settings.ARTIFACT_ROOT / artifact.storage_key
    original = path.read_bytes()
    path.chmod(0o600)
    path.write_bytes(original + b"changed")
    failure = client.get(
        root + "/netflow-ledger", headers=headers, params={"dataset_id": d["id"]}
    )
    assert (
        failure.status_code == 500
        and failure.json()["detail"]["code"] == "netflow_ledger_artifact_invalid"
    )
    path.write_bytes(original)
    monkeypatch.setattr(service, "MAX_ROWS", 1)
    assert (
        client.get(
            root + "/netflow-ledger", headers=headers, params={"dataset_id": d["id"]}
        ).status_code
        == 422
    )


def test_zone_and_namespace_run_guard(
    client: TestClient, ledger: tuple[str, dict[str, str], dict[str, Any]], db: Session
) -> None:
    from app.domain import netflow_ledger as service
    from app.domain.models import Project

    root, headers, d = ledger
    p = db.get(Project, uuid.UUID(root.split("/")[-1]))
    assert p is not None
    service.require_legacy_run_scope(db, p, uuid.UUID(d["id"]))
    assert write(client, root, headers, scope(d)).status_code == 201
    with pytest.raises(service.LedgerError):
        service.require_legacy_run_scope(db, p, uuid.UUID(d["id"]))
    assert (
        write(client, root, headers, {**scope(d, 1), "namespace": "legacy"}).status_code
        == 201
    )
    service.require_legacy_run_scope(db, p, uuid.UUID(d["id"]))
    assert (
        write(
            client,
            root,
            headers,
            {**scope(d, 2), "namespace": "legacy", "scope_status": "REVOKED"},
        ).status_code
        == 201
    )
    with pytest.raises(service.LedgerError):
        service.require_legacy_run_scope(db, p, uuid.UUID(d["id"]))
    zoned = _upload(
        client,
        headers,
        root.split("/")[-1],
        HEADER + b"fe80::1%en0,2001:db8:10::25,6,1,2\n",
    )
    if zoned.status_code == 201 and zoned.json()["activity_valid_record_count"]:
        assert (
            client.get(
                root + "/netflow-ledger",
                headers=headers,
                params={"dataset_id": zoned.json()["id"]},
            ).status_code
            == 500
        )


@pytest.mark.parametrize("separate_build", [False, True])
def test_scope_drift_between_launch_and_new_run_keeps_old_resume(
    client: TestClient,
    ledger: tuple[str, dict[str, str], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    separate_build: bool,
) -> None:
    from pydantic import SecretStr

    from app.core.db import engine
    from app.domain.governance_runs import (
        GovernanceRunExecutionError,
        RunnerInputs,
        establish_governance_run,
    )
    from app.integrations.agent_compose import AgentComposeClient
    from tests.api.routes import test_governance_runs as rf

    root, headers, dataset = ledger
    project: dict[str, object] = {"id": root.split("/")[-1]}
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("synthetic-local-only")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    if separate_build:
        monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "unchanged-model-build")
        monkeypatch.setattr(
            settings, "GOVERNANCE_RUNNER_BUILD_VERSION", "test-runner-v1"
        )
    rf._mock_cloudatlas(monkeypatch)
    monkeypatch.setattr(AgentComposeClient, "get_run", lambda *_args, **_kwargs: None)
    rf._prepare_ready_project(client=client, headers=headers, project=project)
    assert (
        client.post(
            root + f"/netflow-datasets/{dataset['id']}/select", headers=headers
        ).status_code
        == 200
    )
    assert (
        write(
            client, root, headers, {**scope(dataset), "namespace": "legacy"}
        ).status_code
        == 201
    )
    env = rf._trigger_stage5_run(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project=project,
        trigger_id=str(uuid.uuid4()),
    )
    inputs = RunnerInputs.from_environment(env)
    assert inputs.runner_build_version == "test-runner-v1"
    if separate_build:
        assert settings.RUNNER_BUILD_VERSION == "unchanged-model-build"
    assert (
        write(
            client,
            root,
            headers,
            {**scope(dataset, 1), "namespace": "legacy", "scope_status": "REVOKED"},
        ).status_code
        == 201
    )
    with Session(engine) as session:
        with pytest.raises(GovernanceRunExecutionError) as error:
            establish_governance_run(session=session, inputs=inputs)
        assert error.value.code == "runner_netflow_namespace_not_legacy"
    assert (
        write(
            client, root, headers, {**scope(dataset, 2), "namespace": "legacy"}
        ).status_code
        == 201
    )
    with Session(engine) as session:
        run = establish_governance_run(session=session, inputs=inputs)
        run_id = run.id
        before_hash = run.input_hash
    assert (
        write(
            client,
            root,
            headers,
            {**scope(dataset, 3), "namespace": "legacy", "scope_status": "REVOKED"},
        ).status_code
        == 201
    )
    with Session(engine) as session:
        resumed = establish_governance_run(session=session, inputs=inputs)
        assert resumed.id == run_id and resumed.input_hash == before_hash
