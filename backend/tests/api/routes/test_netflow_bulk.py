"""Real PG + HTTP + Parquet engine; only agent-compose control is simulated."""

import csv
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.domain import netflow_bulk as bulk
from app.domain.models import Project
from app.domain.netflow_models import NetFlowAnalysis
from app.netflow_bulk.storage import file_hash, seal
from tests.api.routes.test_netflow_datasets import _project
from tests.domain.test_netflow_bulk_engine import BASE, HEADERS
from tests.utils.netflow_processing import ControlPlane, context_request


@pytest.fixture
def ready(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    artifact = tmp_path / "artifacts"
    artifact.mkdir()
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", artifact)
    monkeypatch.setattr(settings, "NETFLOW_BULK_ROOT", snapshots)
    monkeypatch.setattr(settings, "NETFLOW_BULK_DISK_RESERVE_BYTES", 0)
    monkeypatch.setattr(settings, "NETFLOW_ALLOW_TEST_FIXTURES", True)
    control = ControlPlane(monkeypatch)
    project_id = uuid.UUID(str(_project(client, superuser_token_headers)["id"]))
    project = db.get(Project, project_id)
    assert project is not None
    tenant = project.tenant_id
    db.commit()
    source = tmp_path / "source"
    source.mkdir()
    for number in range(2):
        with (source / f"file{number}.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(HEADERS)
            writer.writerow(BASE)
            for i in range(1, 32):
                row = BASE.copy()
                row[0], row[1] = f"192.0.2.{i + 1}", f"2001:db8::{i + number + 1:x}"
                writer.writerow(row)
    ready_id, _ = seal(
        source,
        snapshots,
        tenant=str(tenant),
        project=str(project_id),
        source_id="fixture",
        reserve_bytes=0,
    )
    root = f"/api/v1/projects/{project_id}"
    headers = superuser_token_headers
    response = client.post(
        root + "/netflow-bulk/datasets",
        json={"source_id": "fixture", "ready_id": ready_id},
        headers=headers | {"Idempotency-Key": "register"},
    )
    assert response.status_code == 201, response.text
    dataset_id = response.json()["dataset_id"]
    context = client.post(
        root + f"/netflow-datasets/{dataset_id}/processing-contexts",
        json=context_request(collection_scope="fixture"),
        headers=headers | {"Idempotency-Key": "context"},
    )
    assert context.status_code == 201, context.text
    return {
        "root": root,
        "project_id": project_id,
        "dataset_id": dataset_id,
        "context_id": context.json()["context_revision_id"],
        "headers": headers,
        "control": control,
        "ready_id": ready_id,
    }


def start(
    client: TestClient,
    ready: dict[str, Any],
    *,
    key: str = "start",
    selection: dict[str, Any] | None = None,
) -> str:
    response = client.post(
        ready["root"] + f"/netflow-bulk/datasets/{ready['dataset_id']}/analyses",
        json={
            "context_revision_id": ready["context_id"],
            "bulk_filter": selection or {},
        },
        headers=ready["headers"] | {"Idempotency-Key": key},
    )
    assert response.status_code == 202, response.text
    return str(response.json()["analysis_id"])


def execute(db: Session, ready: dict[str, Any], analysis_id: str) -> NetFlowAnalysis:
    db.expire_all()
    row = db.get(NetFlowAnalysis, uuid.UUID(analysis_id))
    assert row is not None
    run = ready["control"].runs[row.agent_run_id]
    bulk.execute(db, row.id, row.agent_run_id, run.session_id)
    db.refresh(row)
    db.commit()
    return row


def test_real_bulk_publication_queries_and_reuse(
    client: TestClient,
    db: Session,
    ready: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.integrations import netflow_processor
    from app.netflow_bulk import engine

    analysis_id = start(client, ready)
    root = ready["root"] + f"/netflow-analyses/{analysis_id}"
    assert (
        client.get(root + "/observations", headers=ready["headers"]).status_code == 409
    )
    row = execute(db, ready, analysis_id)
    assert row.status == "SUCCEEDED"
    assert row.result is not None
    assert row.result["counts"] == {
        "raw": 64,
        "invalid": 0,
        "filtered": 0,
        "retained": 64,
        "unique": 63,
        "duplicate": 1,
    }
    monkeypatch.setattr(
        netflow_processor,
        "load_bundle",
        lambda *a, **k: pytest.fail("bulk used legacy bundle"),
    )

    def fail_parse(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("CSV parsed again")

    monkeypatch.setattr(engine, "normalize_file", fail_parse)
    assert settings.NETFLOW_BULK_ROOT is not None
    settings.NETFLOW_BULK_ROOT.rename(
        settings.NETFLOW_BULK_ROOT.with_name("offline-snapshots")
    )
    page = client.get(root + "/observations?limit=2", headers=ready["headers"])
    assert page.status_code == 200, page.text
    assert page.json()["count"] == 32
    assert page.json()["next_cursor"]
    second = client.get(
        root + "/observations",
        params={"limit": 2, "cursor": page.json()["next_cursor"]},
        headers=ready["headers"],
    )
    assert second.status_code == 200, second.text
    assert {v["object_key"] for v in page.json()["data"]}.isdisjoint(
        {v["object_key"] for v in second.json()["data"]}
    )
    wrong_filter = client.get(
        root + "/observations",
        params={"protocol": 17, "cursor": page.json()["next_cursor"]},
        headers=ready["headers"],
    )
    assert wrong_filter.status_code == 422
    evidence = client.get(
        root + "/evidence",
        params={"object_key": page.json()["data"][0]["object_key"]},
        headers=ready["headers"],
    )
    assert evidence.status_code == 200, evidence.text
    record = client.get(
        ready["root"] + f"/netflow-bulk/analyses/{analysis_id}/record",
        params={"reference": evidence.json()["data"][0]["reference"]},
        headers=ready["headers"],
    )
    assert record.status_code == 200, record.text
    assert record.json()["record"]["valid"]
    peer = client.get(root + "/peers?limit=2", headers=ready["headers"])
    assert peer.status_code == 200, peer.text
    zero_id = start(client, ready, key="filter", selection={"protocols": [17]})
    zero = execute(db, ready, zero_id)
    assert zero.result is not None and zero.result["counts"]["filtered"] == 64
    assert zero.result["counts"]["unique"] == 0
    assert (
        client.get(root, headers=ready["headers"]).json()["result"]["counts"]["unique"]
        == 63
    )


def test_revoke_and_project_isolation(
    client: TestClient, db: Session, ready: dict[str, Any]
) -> None:
    analysis_id = start(client, ready)
    execute(db, ready, analysis_id)
    another = _project(client, ready["headers"])
    wrong = client.get(
        f"/api/v1/projects/{another['id']}/netflow-analyses/{analysis_id}/observations",
        headers=ready["headers"],
    )
    assert wrong.status_code == 404
    revoke = client.post(
        ready["root"] + f"/netflow-datasets/{ready['dataset_id']}/processing-contexts",
        json=context_request(
            ready["context_id"], state="REVOKED", collection_scope="fixture"
        ),
        headers=ready["headers"] | {"Idempotency-Key": "revoke"},
    )
    assert revoke.status_code == 201, revoke.text
    assert (
        client.get(
            ready["root"] + f"/netflow-analyses/{analysis_id}/observations",
            headers=ready["headers"],
        ).status_code
        == 409
    )


@pytest.mark.parametrize("failure", ["checkpoint", "publish", "disk", "enospc"])
def test_interrupted_attempt_reuses_only_committed_shards(
    client: TestClient,
    db: Session,
    ready: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    import pyarrow.parquet as pq  # type: ignore[import-untyped]

    from app.integrations.agent_compose import AgentComposeSessionObservation
    from app.netflow_bulk.contracts import BulkError

    analysis_id = start(client, ready)
    with monkeypatch.context() as patch:
        if failure == "checkpoint":

            def reject_checkpoint(*_args: Any, **_kwargs: Any) -> None:
                raise BulkError("injected_after_file_before_checkpoint")

            patch.setattr(bulk, "_checkpoint", reject_checkpoint)
        elif failure == "publish":

            def reject_publish(*_args: Any, **_kwargs: Any) -> None:
                raise BulkError("injected_before_publication")

            patch.setattr(bulk, "publish", reject_publish)
        elif failure == "enospc":

            def no_space(*_args: Any, **_kwargs: Any) -> None:
                raise OSError(28, "Synthetic ENOSPC")

            patch.setattr(pq, "write_table", no_space)
        else:
            patch.setattr(settings, "NETFLOW_BULK_DISK_RESERVE_BYTES", 2**62)
        with pytest.raises((BulkError, OSError)):
            execute(db, ready, analysis_id)
    db.expire_all()
    parent = db.get(NetFlowAnalysis, uuid.UUID(analysis_id))
    assert parent is not None and parent.status == "FAILED" and parent.result is None
    ready["control"].observe(parent, AgentComposeSessionObservation.TERMINAL)
    response = client.post(
        ready["root"] + f"/netflow-bulk/datasets/{ready['dataset_id']}/analyses",
        json={
            "context_revision_id": ready["context_id"],
            "retry_of_analysis_id": analysis_id,
        },
        headers=ready["headers"] | {"Idempotency-Key": "retry"},
    )
    assert response.status_code == 202, response.text
    result = execute(db, ready, response.json()["analysis_id"])
    assert result.result is not None and result.result["counts"]["unique"] == 63
    assert result.result["counts"]["raw"] == 64
    assert (
        client.get(
            ready["root"] + f"/netflow-analyses/{analysis_id}/observations",
            headers=ready["headers"],
        ).status_code
        == 409
    )


def test_claim_competition_expiry_and_fencing(
    client: TestClient, db: Session, ready: dict[str, Any]
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta

    from app.core.time import get_datetime_utc
    from app.domain.netflow_bulk_models import BulkJob
    from app.netflow_bulk.contracts import BulkError

    analysis_id = uuid.UUID(start(client, ready))
    row = db.get(NetFlowAnalysis, analysis_id)
    assert row is not None and row.session_id is not None
    run_id, session_id = row.agent_run_id, row.session_id
    bind = db.get_bind()
    db.commit()

    def contender() -> int | None:
        with Session(bind) as own:
            return bulk.claim(own, analysis_id, run_id, session_id)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: contender(), range(2)))
    assert sorted(x for x in results if x is not None) == [1]
    job = db.get(BulkJob, analysis_id)
    assert job is not None
    job.lease_until = get_datetime_utc() - timedelta(seconds=1)
    db.add(job)
    db.commit()
    fence = contender()
    assert fence == 2
    with pytest.raises(BulkError):
        bulk.heartbeat(db, analysis_id, 1)
    db.rollback()
    bulk.run_engine(db, analysis_id, fence)
    db.commit()


def test_actual_sigkill_then_explicit_retry(
    client: TestClient, db: Session, ready: dict[str, Any], record_property: Any
) -> None:
    import os
    import subprocess
    import sys

    from app.integrations.agent_compose import AgentComposeSessionObservation

    analysis_id = uuid.UUID(start(client, ready))
    row = db.get(NetFlowAnalysis, analysis_id)
    assert row is not None and row.session_id is not None
    fence = bulk.claim(db, analysis_id, row.agent_run_id, row.session_id)
    assert fence is not None
    child = """
import os,signal,uuid
from sqlmodel import Session
from app.core.db import engine
from app.domain import netflow_bulk as bulk
original=bulk._checkpoint
def checkpoint(*args,**kwargs):
    original(*args,**kwargs)
    os.kill(os.getpid(),signal.SIGKILL)
bulk._checkpoint=checkpoint
with Session(engine) as session:
    bulk.run_engine(session,uuid.UUID(os.environ['BULK_TEST_ANALYSIS']),int(os.environ['BULK_TEST_FENCE']))
"""
    result = subprocess.run(
        [sys.executable, "-c", child],
        env=os.environ
        | {
            "ARTIFACT_ROOT": str(settings.ARTIFACT_ROOT),
            "NETFLOW_BULK_ROOT": str(settings.NETFLOW_BULK_ROOT),
            "BULK_TEST_ANALYSIS": str(analysis_id),
            "BULK_TEST_FENCE": str(fence),
            "NETFLOW_ALLOW_TEST_FIXTURES": "true",
            "NETFLOW_BULK_DISK_RESERVE_BYTES": "0",
        },
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == -9, result.stderr.decode()
    db.expire_all()
    row = db.get(NetFlowAnalysis, analysis_id)
    assert row is not None and row.status == "RUNNING" and row.result is None
    ready["control"].observe(row, AgentComposeSessionObservation.TERMINAL)
    reconciled = client.post(
        ready["root"] + f"/netflow-analyses/{analysis_id}/reconcile",
        headers=ready["headers"] | {"Idempotency-Key": "reconcile-kill"},
    )
    assert reconciled.status_code == 200, reconciled.text
    response = client.post(
        ready["root"] + f"/netflow-datasets/{ready['dataset_id']}/analyses",
        json={
            "context_revision_id": ready["context_id"],
            "retry_of_analysis_id": str(analysis_id),
        },
        headers=ready["headers"] | {"Idempotency-Key": "retry-kill"},
    )
    assert response.status_code == 202, response.text
    import time

    recovery_started = time.monotonic()
    recovered = execute(db, ready, response.json()["analysis_id"])
    record_property("recovery_seconds", time.monotonic() - recovery_started)
    assert recovered.result is not None and recovered.result["counts"]["raw"] == 64
    assert recovered.result["counts"]["unique"] == 63


def test_bulk_is_optional_v2_evidence(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import timedelta

    from app.core.time import get_datetime_utc
    from tests.api.routes.test_core_comparisons import _create_core, _setup_core

    core = _setup_core(
        client, db, superuser_token_headers, tmp_path / "core", monkeypatch
    )
    result = _create_core(client, core)
    source = tmp_path / "source"
    source.mkdir()
    with (source / "input.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADERS)
        writer.writerow(BASE)
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    monkeypatch.setattr(settings, "NETFLOW_BULK_ROOT", snapshots)
    monkeypatch.setattr(settings, "NETFLOW_BULK_DISK_RESERVE_BYTES", 0)
    monkeypatch.setattr(settings, "NETFLOW_ALLOW_TEST_FIXTURES", True)
    control = ControlPlane(monkeypatch)
    project = core["project"]
    identifier, _ = seal(
        source,
        snapshots,
        tenant=str(project.tenant_id),
        project=str(project.id),
        source_id="fixture",
        reserve_bytes=0,
    )
    db.commit()
    response = client.post(
        core["root"] + "/netflow-bulk/datasets",
        json={"source_id": "fixture", "ready_id": identifier},
        headers=core["headers"] | {"Idempotency-Key": "register-bulk"},
    )
    assert response.status_code == 201, response.text
    dataset_id = response.json()["dataset_id"]
    context_url = core["root"] + f"/netflow-datasets/{dataset_id}/processing-contexts"
    context = client.post(
        context_url,
        json=context_request(
            network_namespace="synthetic-core", collection_scope="fixture"
        ),
        headers=core["headers"] | {"Idempotency-Key": "context-bulk"},
    )
    assert context.status_code == 201, context.text
    fixture = core | {
        "dataset_id": dataset_id,
        "context_id": context.json()["context_revision_id"],
        "control": control,
    }
    analysis = start(client, fixture)
    execute(db, fixture, analysis)
    binding = client.post(
        core["root"] + f"/comparison-results/{result['id']}/supplements",
        json={
            "analysis_id": analysis,
            "expected_binding_id": None,
            "scope_evidence": "Synthetic administrator confirms optional bulk N scope.",
            "valid_until": (get_datetime_utc() + timedelta(minutes=5)).isoformat(),
        },
        headers=core["headers"] | {"Idempotency-Key": "bind-bulk"},
    )
    assert binding.status_code == 201, binding.text
    address_url = (
        core["root"]
        + f"/comparison-results/{result['id']}/supplements/{binding.json()['id']}/addresses"
    )
    addresses = client.get(
        address_url, params={"only_supplemental": True}, headers=core["headers"]
    )
    assert addresses.status_code == 200, addresses.text
    assert addresses.json()["data"][0]["canonical_ip"] == "192.0.2.1"
    summary_url = core["root"] + f"/comparison-results/{result['id']}/summary"
    before = client.get(summary_url, headers=core["headers"])
    revoked = client.post(
        context_url,
        json=context_request(
            fixture["context_id"],
            state="REVOKED",
            network_namespace="synthetic-core",
            collection_scope="fixture",
        ),
        headers=core["headers"] | {"Idempotency-Key": "revoke-bulk"},
    )
    assert revoked.status_code == 201
    assert client.get(address_url, headers=core["headers"]).status_code == 409
    after = client.get(summary_url, headers=core["headers"])
    assert before.status_code == after.status_code == 200
    assert before.json()["total_addresses"] == after.json()["total_addresses"] == 3


def test_final_database_publication_failure_is_not_readable(
    client: TestClient, db: Session, ready: dict[str, Any]
) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    from tests.utils.audit import reject_audit_inserts

    analysis_id = start(client, ready)
    with reject_audit_inserts(db):
        with pytest.raises(SQLAlchemyError):
            execute(db, ready, analysis_id)
    db.expire_all()
    row = db.get(NetFlowAnalysis, uuid.UUID(analysis_id))
    assert (
        row is not None and row.status in ("RUNNING", "UNKNOWN") and row.result is None
    )
    from app.integrations.agent_compose import AgentComposeSessionObservation

    ready["control"].observe(row, AgentComposeSessionObservation.TERMINAL)
    db.commit()
    response = client.post(
        ready["root"] + f"/netflow-analyses/{analysis_id}/reconcile",
        headers=ready["headers"] | {"Idempotency-Key": "recover-publication"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "FAILED"
    assert (
        client.get(
            ready["root"] + f"/netflow-analyses/{analysis_id}/observations",
            headers=ready["headers"],
        ).status_code
        == 409
    )


def test_publication_hashes_do_not_block_heartbeat(
    client: TestClient,
    db: Session,
    ready: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.netflow_bulk_models import BulkJob

    original = file_hash
    analysis_id = uuid.UUID(start(client, ready))
    checked = []

    def hashing(path: Path, **kwargs: Any) -> str:
        if "result" in path.parts:
            with Session(db.get_bind()) as own:
                own.exec(
                    select(BulkJob)
                    .where(BulkJob.analysis_id == analysis_id)
                    .with_for_update(nowait=True)
                ).one()
                checked.append(path.name)
        return original(path, **kwargs)

    monkeypatch.setattr(bulk, "file_hash", hashing)
    execute(db, ready, str(analysis_id))
    assert "peers.parquet" in checked


def test_tampered_result_invalidates_publication(
    client: TestClient, db: Session, ready: dict[str, Any]
) -> None:
    analysis_id = start(client, ready)
    row = execute(db, ready, analysis_id)
    assert row.result is not None
    descriptor = row.result["files"]["peers"]
    path = settings.ARTIFACT_ROOT / descriptor["path"]
    path.chmod(0o640)
    with path.open("r+b") as stream:
        stream.write(b"BROKEN")
    response = client.get(
        ready["root"] + f"/netflow-analyses/{analysis_id}/observations",
        headers=ready["headers"],
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "bulk_integrity_invalidated"


def test_bulk_json_body_is_bounded_before_parsing(
    client: TestClient, ready: dict[str, Any]
) -> None:
    response = client.post(
        ready["root"] + "/netflow-bulk/datasets",
        headers=ready["headers"]
        | {"Idempotency-Key": "oversized", "Content-Type": "application/json"},
        content=b'{"source_id":"' + b"x" * (2 * 1024 * 1024) + b'"}',
    )
    assert response.status_code == 413, response.text
    assert response.json()["detail"]["code"] == "bulk_request_limit"


def test_revocation_before_claim_does_not_leave_global_capacity_reserved(
    client: TestClient, db: Session, ready: dict[str, Any]
) -> None:
    from fastapi import HTTPException

    from app.core.time import get_datetime_utc

    analysis_id = start(client, ready)
    project = db.get(Project, ready["project_id"])
    assert project is not None
    project.archived_at = get_datetime_utc()
    db.add(project)
    db.commit()
    with pytest.raises(HTTPException):
        execute(db, ready, analysis_id)
    db.expire_all()
    row = db.get(NetFlowAnalysis, uuid.UUID(analysis_id))
    assert row is not None and row.status == "FAILED" and row.result is None
    db.commit()


@pytest.mark.parametrize("drift", ["missing", "symlink"])
def test_missing_evidence_persistently_invalidates_dependents(
    client: TestClient, db: Session, ready: dict[str, Any], drift: str
) -> None:
    from app.domain.netflow_bulk_models import BulkDataset, BulkShard

    analysis_id = start(client, ready)
    row = execute(db, ready, analysis_id)
    root = ready["root"] + f"/netflow-analyses/{analysis_id}"
    page = client.get(
        root + "/observations", params={"limit": 1}, headers=ready["headers"]
    ).json()
    evidence = client.get(
        root + "/evidence",
        params={"object_key": page["data"][0]["object_key"]},
        headers=ready["headers"],
    ).json()
    reference = evidence["data"][0]["reference"]
    file_id, record_number = reference.split(":")[1], int(reference.split(":")[3])
    shard = db.exec(
        select(BulkShard).where(
            BulkShard.dataset_id == row.dataset_id,
            BulkShard.file_id == file_id,
            BulkShard.first_row <= record_number,
            BulkShard.last_row >= record_number,
        )
    ).one()
    path = settings.ARTIFACT_ROOT / shard.storage_key
    path.unlink()
    if drift == "symlink":
        target = path.parent / "outside.txt"
        target.write_text("synthetic")
        path.symlink_to(target)
    db.commit()
    response = client.get(
        ready["root"] + f"/netflow-bulk/analyses/{analysis_id}/record",
        params={"reference": reference},
        headers=ready["headers"],
    )
    assert response.status_code == 409, response.text
    db.expire_all()
    dataset = db.get(BulkDataset, row.dataset_id)
    assert dataset is not None and dataset.invalidated
    db.commit()
    assert (
        client.get(root + "/observations", headers=ready["headers"]).status_code == 409
    )


def test_pending_cancellation_is_audited_and_never_publishes(
    client: TestClient, db: Session, ready: dict[str, Any]
) -> None:
    from app.domain.models import AuditEvent

    analysis_id = start(client, ready)
    response = client.post(
        ready["root"] + f"/netflow-bulk/analyses/{analysis_id}/cancel",
        headers=ready["headers"],
    )
    assert response.status_code == 200 and response.json()["cancel_requested"]
    db.expire_all()
    row = db.get(NetFlowAnalysis, uuid.UUID(analysis_id))
    assert row is not None and row.status == "FAILED" and row.result is None
    events = db.exec(
        select(AuditEvent).where(
            AuditEvent.target_id == row.id,
            AuditEvent.action == "netflow.bulk_cancel_requested",
        )
    ).all()
    assert len(events) == 1
    db.commit()
    assert (
        client.get(
            ready["root"] + f"/netflow-analyses/{analysis_id}/observations",
            headers=ready["headers"],
        ).status_code
        == 409
    )


@pytest.mark.parametrize("known_identity", [False, True])
def test_legacy_rule_count_subset_and_explicit_dedup_difference(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    known_identity: bool,
) -> None:
    import io

    from app.netflow_bulk import engine as bulk_engine
    from app.netflow_bulk.contracts import Budget, Filter, Member
    from app.netflow_bulk.storage import file_hash
    from tests.utils.netflow_processing import published_analysis

    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    if known_identity:
        writer.writerow(HEADERS)
        writer.writerows([BASE, BASE])
    else:
        writer.writerow(HEADERS[:5])
        writer.writerows([BASE[:5], BASE[:5]])
    raw = stream.getvalue()
    legacy = published_analysis(
        client,
        db,
        superuser_token_headers,
        tmp_path / "legacy",
        monkeypatch,
        raw_text=raw,
    )
    response = client.get(
        f"/api/v1/projects/{legacy['project_id']}/netflow-analyses/{legacy['analysis_id']}/observations",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200, response.text
    original = response.json()["data"][0]
    path = tmp_path / "source.csv"
    path.write_text(raw)
    member = Member(sha256=file_hash(path), size=path.stat().st_size, name=path.name)
    limits = Budget(disk_reserve_bytes=0)
    bulk_engine.normalize_file(
        path,
        member,
        tmp_path / "normalized" / member.sha256,
        limits,
        checkpoint=lambda _: None,
        committed=lambda _: None,
        pulse=lambda: None,
    )
    result = bulk_engine.compute(
        tmp_path / "normalized",
        tmp_path / "result",
        Filter(),
        limits,
        pulse=lambda: None,
    )
    value = next(bulk_engine.batches(Path(result["files"]["observations"]["path"])))[0]
    assert (value["ip"], value["protocol"], value["port"]) == (
        original["canonical_ip"],
        original["protocol_number"],
        original["source_port"],
    )
    assert original["source_record_count"] == 2
    assert value["record_count"] == (1 if known_identity else 2)
    assert result["counts"]["raw"] == 2
