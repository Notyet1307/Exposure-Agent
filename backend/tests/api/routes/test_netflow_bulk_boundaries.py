"""Small HTTP/PG checks for bulk admission, read and cancellation boundaries."""

import resource
import sys
import time
import uuid
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain import netflow_bulk as bulk
from app.domain.models import AuditEvent
from app.domain.netflow_bulk_models import BulkDataset, BulkJob, BulkShard
from app.domain.netflow_models import NetFlowAnalysis
from app.integrations.agent_compose import AgentComposeSessionObservation
from app.netflow_bulk import engine as bulk_engine
from app.netflow_bulk.contracts import BulkError
from tests.api.routes.test_netflow_bulk import execute, start
from tests.api.routes.test_netflow_bulk import ready as ready


def test_admission_replays_before_parse_and_rejects_disabled_or_busy_sources(
    client: TestClient,
    db: Session,
    ready: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"source_id": "fixture", "ready_id": ready["ready_id"]}
    url = ready["root"] + "/netflow-bulk/datasets"
    with monkeypatch.context() as patch:

        def unexpected(*_args: Any, **_kwargs: Any) -> Any:
            pytest.fail("Idempotent operation reread the source")

        patch.setattr(bulk, "read_ready", unexpected)
        replay = client.post(
            url, json=body, headers=ready["headers"] | {"Idempotency-Key": "register"}
        )
    assert (
        replay.status_code == 201 and replay.json()["dataset_id"] == ready["dataset_id"]
    )
    duplicate = client.post(
        url, json=body, headers=ready["headers"] | {"Idempotency-Key": "same-source"}
    )
    assert (
        duplicate.status_code == 201
        and duplicate.json()["dataset_id"] == ready["dataset_id"]
    )
    missing = client.post(
        url,
        json=body | {"ready_id": "0" * 64},
        headers=ready["headers"] | {"Idempotency-Key": "missing-source"},
    )
    assert missing.status_code == 422
    assert str(settings.NETFLOW_BULK_ROOT) not in missing.text
    analysis_id = start(client, ready)
    assert start(client, ready) == analysis_id
    assert start(client, ready, key="same-identity") == analysis_id
    endpoint = ready["root"] + f"/netflow-bulk/datasets/{ready['dataset_id']}/analyses"
    for index, invalid in enumerate(
        [
            {"protocols": [256]},
            {"start": "2026-01-01T00:00:00"},
            {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:00:00Z"},
        ]
    ):
        response = client.post(
            endpoint,
            json={"context_revision_id": ready["context_id"], "bulk_filter": invalid},
            headers=ready["headers"] | {"Idempotency-Key": f"invalid-filter-{index}"},
        )
        assert response.status_code == 422
    busy = client.post(
        endpoint,
        json={
            "context_revision_id": ready["context_id"],
            "bulk_filter": {"protocols": [17]},
        },
        headers=ready["headers"] | {"Idempotency-Key": "busy"},
    )
    assert (
        busy.status_code == 409
        and busy.json()["detail"]["code"] == "bulk_capacity_busy"
    )
    execute(db, ready, analysis_id)
    retry = client.post(
        endpoint,
        json={
            "context_revision_id": ready["context_id"],
            "retry_of_analysis_id": analysis_id,
        },
        headers=ready["headers"] | {"Idempotency-Key": "successful-retry"},
    )
    assert retry.status_code == 409
    with monkeypatch.context() as patch:
        patch.setattr(settings, "NETFLOW_BULK_ROOT", None)
        assert (
            client.post(
                url,
                json=body,
                headers=ready["headers"] | {"Idempotency-Key": "disabled"},
            ).status_code
            == 503
        )
        disabled = client.post(
            endpoint,
            json={"context_revision_id": ready["context_id"]},
            headers=ready["headers"] | {"Idempotency-Key": "disabled-analysis"},
        )
        assert disabled.status_code == 422


def test_progress_filters_peer_evidence_and_explicit_invalidation(
    client: TestClient, db: Session, ready: dict[str, Any]
) -> None:
    analysis_id = start(client, ready)
    headers = ready["headers"]
    root = ready["root"] + f"/netflow-analyses/{analysis_id}"
    bulk_root = ready["root"] + f"/netflow-bulk/analyses/{analysis_id}"
    pending = client.get(bulk_root + "/progress", headers=headers)
    assert pending.status_code == 200
    assert pending.json()["files_total"] == 2 and pending.json()["files_completed"] == 0
    assert pending.json()["rows_normalized"] == 0
    execute(db, ready, analysis_id)
    complete = client.get(bulk_root + "/progress", headers=headers)
    assert (
        complete.json()["rows_normalized"] == 64
        and complete.json()["files_completed"] == 2
    )
    assert complete.headers["cache-control"] == "private, no-store"
    observations = client.get(
        root + "/observations",
        params={"ip": "::ffff:192.0.2.1", "protocol": 6, "source_port": 443},
        headers=headers,
    )
    assert observations.status_code == 200 and observations.json()["count"] == 1
    obj = observations.json()["data"][0]
    detail = client.get(root + f"/observations/{obj['object_key']}", headers=headers)
    assert detail.status_code == 200 and detail.json()["source_record_count"] == 1
    assert detail.json()["business_time_qualification"] == "UNKNOWN"
    assert client.get(root + "/observations/absent", headers=headers).status_code == 404
    peers = client.get(
        root + "/peers",
        params={"ip": "2001:db8::2", "protocol": 6, "peer_port": 50000},
        headers=headers,
    )
    assert peers.status_code == 200 and peers.json()["count"] == 1
    peer = peers.json()["data"][0]
    evidence = client.get(
        root + "/evidence", params={"peer_key": peer["peer_key"]}, headers=headers
    )
    assert evidence.status_code == 200 and len(evidence.json()["data"]) == 1
    for params, status in [
        ({}, 422),
        ({"object_key": "absent"}, 404),
        ({"peer_key": "absent"}, 404),
        ({"object_key": obj["object_key"], "peer_key": peer["peer_key"]}, 422),
    ]:
        assert (
            client.get(root + "/evidence", params=params, headers=headers).status_code
            == status
        )
    for side, key in [("observations", "object_key"), ("peers", "peer_key")]:
        first = client.get(
            root + f"/{side}", params={"limit": 2, "sort": "ip_desc"}, headers=headers
        ).json()
        second = client.get(
            root + f"/{side}",
            params={"limit": 2, "sort": "ip_desc", "cursor": first["next_cursor"]},
            headers=headers,
        )
        assert second.status_code == 200
        assert {x[key] for x in first["data"]}.isdisjoint(
            {x[key] for x in second.json()["data"]}
        )
        assert (
            client.get(
                root + f"/{side}",
                params={"cursor": first["next_cursor"], "sort": "ip_desc", "skip": 1},
                headers=headers,
            ).status_code
            == 422
        )
        assert (
            client.get(
                root + f"/{side}", params={"cursor": "corrupted"}, headers=headers
            ).status_code
            == 422
        )
    for reference, status in [
        ("invalid", 422),
        ("sha256:" + "0" * 64 + ":row:" + "0" * 20, 422),
        ("sha256:" + "0" * 64 + ":row:" + f"{1:020}", 404),
    ]:
        assert (
            client.get(
                bulk_root + "/record", params={"reference": reference}, headers=headers
            ).status_code
            == status
        )
    for _ in range(2):
        assert (
            client.post(
                root + "/reconcile",
                headers=headers | {"Idempotency-Key": "success-reconcile"},
            ).status_code
            == 200
        )
    invalidated = client.post(bulk_root + "/invalidate", headers=headers)
    assert invalidated.status_code == 200 and invalidated.json()["invalidated"]
    assert client.get(root + "/observations", headers=headers).status_code == 409
    db.expire_all()
    audit = db.exec(
        select(AuditEvent).where(
            AuditEvent.target_id == uuid.UUID(analysis_id),
            AuditEvent.action == "netflow.bulk_invalidated",
        )
    ).all()
    assert len(audit) == 1


def test_expired_lease_requires_terminal_proof_before_retry(
    client: TestClient, db: Session, ready: dict[str, Any]
) -> None:
    analysis_id = uuid.UUID(start(client, ready))
    row = db.get(NetFlowAnalysis, analysis_id)
    assert row is not None and row.session_id is not None
    fence = bulk.claim(db, row.id, row.agent_run_id, row.session_id)
    assert fence is not None
    job = db.get(BulkJob, row.id)
    assert job is not None
    job.lease_until = get_datetime_utc() - timedelta(seconds=1)
    db.add(job)
    db.commit()
    url = ready["root"] + f"/netflow-analyses/{analysis_id}/reconcile"
    result = client.post(url, headers=ready["headers"] | {"Idempotency-Key": "expired"})
    assert result.status_code == 200 and result.json()["status"] == "UNKNOWN"
    endpoint = ready["root"] + f"/netflow-bulk/datasets/{ready['dataset_id']}/analyses"
    payload = {
        "context_revision_id": ready["context_id"],
        "retry_of_analysis_id": str(analysis_id),
    }
    assert (
        client.post(
            endpoint,
            json=payload,
            headers=ready["headers"] | {"Idempotency-Key": "unproven-retry"},
        ).status_code
        == 409
    )
    db.refresh(row)
    ready["control"].observe(row, AgentComposeSessionObservation.TERMINAL)
    assert (
        client.post(
            url, headers=ready["headers"] | {"Idempotency-Key": "terminal"}
        ).status_code
        == 200
    )
    retried = client.post(
        endpoint,
        json=payload,
        headers=ready["headers"] | {"Idempotency-Key": "proven-retry"},
    )
    assert retried.status_code == 202
    recovered = execute(db, ready, retried.json()["analysis_id"])
    assert recovered.result is not None and recovered.result["counts"]["unique"] == 63


def test_wrong_worker_and_corrupt_shard_fail_without_publishing(
    client: TestClient, db: Session, ready: dict[str, Any]
) -> None:
    analysis_id = uuid.UUID(start(client, ready))
    row = db.get(NetFlowAnalysis, analysis_id)
    assert row is not None and row.session_id is not None
    with pytest.raises(BulkError, match="bulk_execution_identity"):
        bulk.execute(db, row.id, "0" * 64, row.session_id)
    with pytest.raises(BulkError, match="bulk_execution_identity"):
        bulk.execute(db, row.id, row.agent_run_id, "0" * 64)
    execute(db, ready, str(analysis_id))
    shard = db.exec(
        select(BulkShard).where(BulkShard.dataset_id == row.dataset_id)
    ).first()
    assert shard is not None
    path = settings.ARTIFACT_ROOT / shard.storage_key
    # Fault injection into this test's sealed evidence; production stays read-only.
    path.chmod(0o640)
    path.write_bytes(b"corrupted synthetic shard")
    reference = f"sha256:{shard.file_id}:row:{shard.first_row:020}"
    bad = client.get(
        ready["root"] + f"/netflow-bulk/analyses/{analysis_id}/record",
        params={"reference": reference},
        headers=ready["headers"],
    )
    assert bad.status_code == 409
    db.expire_all()
    dataset = db.get(BulkDataset, row.dataset_id)
    assert dataset is not None and dataset.invalidated
    repeated = client.post(
        ready["root"] + "/netflow-bulk/datasets",
        json={"source_id": "fixture", "ready_id": ready["ready_id"]},
        headers=ready["headers"] | {"Idempotency-Key": "corrupt-source"},
    )
    assert repeated.status_code == 409


@pytest.mark.parametrize("failure", ["rss", "timeout", "unexpected", "cancelled"])
def test_worker_resource_or_cancel_failure_never_publishes(
    client: TestClient,
    db: Session,
    ready: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    analysis_id = start(client, ready)
    expected = {
        "rss": "bulk_rss_budget",
        "timeout": "bulk_timeout",
        "unexpected": "bulk_processing_failed",
        "cancelled": "bulk_lease_lost_or_cancelled",
    }[failure]
    if failure == "rss":
        monkeypatch.setattr(
            resource,
            "getrusage",
            lambda _: SimpleNamespace(
                ru_maxrss=3 * 1024**3 if sys.platform == "darwin" else 3 * 1024**2
            ),
        )
    elif failure == "timeout":
        original = bulk_engine.normalize_file

        def delayed(*args: Any, **kwargs: Any) -> Any:
            time.sleep(1.1)
            return original(*args, **kwargs)

        monkeypatch.setattr(settings, "NETFLOW_BULK_TIMEOUT_SECONDS", 1)
        monkeypatch.setattr(bulk_engine, "normalize_file", delayed)
    elif failure == "unexpected":

        def fail(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("secret-must-not-leak")

        monkeypatch.setattr(bulk_engine, "compute", fail)
    else:
        original_compute = bulk_engine.compute

        def cancelled(*args: Any, **kwargs: Any) -> Any:
            response = client.post(
                ready["root"] + f"/netflow-bulk/analyses/{analysis_id}/cancel",
                headers=ready["headers"],
            )
            assert response.status_code == 200
            time.sleep(3.2)
            return original_compute(*args, **kwargs)

        monkeypatch.setattr(bulk_engine, "compute", cancelled)
    with pytest.raises((BulkError, RuntimeError)):
        execute(db, ready, analysis_id)
    db.expire_all()
    row = db.get(NetFlowAnalysis, uuid.UUID(analysis_id))
    assert row is not None and row.status == "FAILED" and row.result is None
    assert row.error_code == expected
    response = client.get(
        ready["root"] + f"/netflow-analyses/{analysis_id}/observations",
        headers=ready["headers"],
    )
    assert response.status_code == 409 and "secret-must-not-leak" not in response.text
