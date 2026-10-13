"""Versioned bulk read repository. Never opens raw input or the legacy bundle."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import tempfile
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from app.domain.netflow_reviews import (
        EvidencePage,
        ObservationDetail,
        ObservationPage,
        PeerPage,
    )

from sqlalchemy import func, tuple_
from sqlmodel import Session, col, select

from app.core.config import settings
from app.domain import netflow_processing as legacy
from app.domain.models import Project
from app.domain.netflow_bulk_models import (
    BulkDataset,
    BulkJob,
    BulkObject,
    BulkShard,
)
from app.domain.netflow_common import deny, request_hash
from app.domain.netflow_models import NetFlowAnalysis
from app.netflow_bulk.contracts import (
    ENGINE,
    POLICY,
    VERSION,
    Budget,
    BulkError,
    canonical_json,
    digest,
)
from app.netflow_bulk.engine import connection, sql_literal
from app.netflow_bulk.storage import file_hash, safe_file


def gate(
    session: Session, project: Project, analysis_id: uuid.UUID
) -> tuple[NetFlowAnalysis, dict[str, Any]]:
    row = legacy.analysis_for(session, project, analysis_id)
    context = legacy.context_for(
        session, project, row.dataset_id, row.context_revision_id
    )
    legacy.validate_context(session, project, context)
    job = session.get(BulkJob, row.id)
    dataset = session.get(BulkDataset, row.dataset_id)
    if (
        row.status not in legacy.SUCCESS
        or row.result is None
        or job is None
        or job.phase != "SUCCEEDED"
    ):
        deny("netflow_analysis_not_ready")
    if (
        dataset is None
        or not dataset.complete
        or dataset.invalidated
        or job.invalidated
    ):
        deny("bulk_integrity_invalidated")
    receipt = row.result
    if (
        row.identity.get("backend") != VERSION
        or row.identity.get("engine") != ENGINE
        or receipt.get("policy") != POLICY
        or receipt.get("identity_sha256") != row.processing_identity_sha256
        or request_hash(row.identity) != row.processing_identity_sha256
        or row.identity.get("context_sha256") != request_hash(context.payload)
        or receipt.get("receipt_sha256")
        != digest({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    ):
        deny("netflow_artifact_integrity_failed")
    if row.test_fixture and (
        not settings.NETFLOW_ALLOW_TEST_FIXTURES or settings.ENVIRONMENT == "production"
    ):
        deny("netflow_test_fixture_forbidden", 422)
    try:
        # Inodes are mount-local (e.g. macOS vs a Linux guest). The sealed
        # hash and portable size/mtime/ctime remain the integrity boundary.
        for descriptor in receipt["files"].values():
            path = safe_file(settings.ARTIFACT_ROOT, descriptor["path"])
            st = path.stat()
            if (st.st_size, st.st_mtime_ns, st.st_ctime_ns) != (
                descriptor["size"],
                descriptor["mtime_ns"],
                descriptor["ctime_ns"],
            ):
                raise BulkError("bulk_result_integrity")
    except OSError, BulkError, KeyError:
        job.invalidated = True
        session.add(job)
        session.commit()
        deny("bulk_integrity_invalidated")
    return row, receipt


def public_analysis(
    session: Session, project: Project, row: NetFlowAnalysis, *, include_result: bool
) -> legacy.AnalysisPublic:
    context = legacy.context_for(
        session, project, row.dataset_id, row.context_revision_id
    )
    current = legacy.current_context(session, project, row.dataset_id)
    job = session.get(BulkJob, row.id)
    dataset = session.get(BulkDataset, row.dataset_id)
    readable = (
        row.status in legacy.SUCCESS
        and current is not None
        and current.state == "CONFIRMED"
        and current.network_namespace == row.network_namespace
        and job is not None
        and not job.invalidated
        and dataset is not None
        and dataset.complete
        and not dataset.invalidated
    )
    receipt = None
    if include_result and row.status in legacy.SUCCESS:
        _, receipt = gate(session, project, row.id)
    counts = (row.result or {}).get("counts")
    result = (
        None
        if receipt is None
        else {
            "counts": receipt["counts"],
            "input_state": "empty" if receipt["counts"]["raw"] == 0 else "present",
            "review_task_count": 0,
            "coverage_limitations": [
                "bulk_export_row_dedup_not_network_event_identity",
                "ownership_listening_and_reachability_unknown",
                "cross_dataset_dedup_not_implemented",
                "legacy_review_rules_not_applied",
            ],
            "component_run_id": str(row.id),
            "artifacts": [],
            "backend": VERSION,
        }
    )
    return legacy.AnalysisPublic(
        project_id=project.id,
        analysis_id=row.id,
        dataset_id=row.dataset_id,
        context_revision_id=row.context_revision_id,
        network_namespace=row.network_namespace,
        status=cast(Any, row.status),
        pipeline_complete=row.status in legacy.SUCCESS,
        result=result,
        quality={
            "counts_state": "KNOWN" if counts else "PENDING",
            "counts": counts,
            "policy": POLICY,
            "phase": job.phase if job else "UNKNOWN",
            "metrics": job.metrics if job else {},
        },
        provenance=row.identity,
        context=context.payload,
        observation_window={
            "state": "NOT_VERIFIED",
            "reason": "Per-file declared timestamps are not verified business coverage.",
        },
        current_context_state=current.state if current else "UNKNOWN",
        feedback_revision_id=row.initial_feedback_revision_id,
        retry_of_analysis_id=row.retry_of_analysis_id,
        test_fixture=row.test_fixture,
        error_code=row.error_code,
        can_read_result=readable,
        created_by=row.created_by,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def identity(row: NetFlowAnalysis) -> dict[str, Any]:
    return {
        "project_id": row.project_id,
        "analysis_id": row.id,
        "dataset_id": row.dataset_id,
        "context_revision_id": row.context_revision_id,
        "network_namespace": row.network_namespace,
        "test_fixture": row.test_fixture,
        "provenance": {
            "backend": VERSION,
            "engine": ENGINE,
            "policy": POLICY,
            "identity_sha256": row.processing_identity_sha256,
        },
    }


def _token(row: NetFlowAnalysis, filters: Any, last: list[Any]) -> str:
    raw = canonical_json(
        {
            "analysis": str(row.id),
            "identity": row.processing_identity_sha256,
            "filters": filters,
            "last": last,
        }
    ).encode()
    signature = hmac.new(settings.SECRET_KEY.encode(), raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(signature + raw).decode()


def _last(row: NetFlowAnalysis, filters: Any, cursor: str | None) -> list[Any] | None:
    if cursor is None:
        return None
    try:
        if len(cursor) > 4096:
            raise ValueError()
        value = base64.urlsafe_b64decode(cursor)
        raw, signature = value[32:], value[:32]
        if not hmac.compare_digest(
            signature,
            hmac.new(settings.SECRET_KEY.encode(), raw, hashlib.sha256).digest(),
        ):
            raise ValueError()
        decoded = json.loads(raw)
        if (
            decoded["analysis"] != str(row.id)
            or decoded["identity"] != row.processing_identity_sha256
            or decoded["filters"] != filters
            or len(decoded["last"]) != 3
        ):
            raise ValueError()
        return list(decoded["last"])
    except ValueError, TypeError, KeyError:
        deny("bulk_cursor_invalid", 422)


_QUERY_SLOTS = threading.BoundedSemaphore(2)


def _sql(
    receipt: dict[str, Any], table: str, query: str, params: list[Any]
) -> list[dict[str, Any]]:
    import duckdb

    if not _QUERY_SLOTS.acquire(blocking=False):
        deny("bulk_query_busy", 503)
    try:
        path = safe_file(settings.ARTIFACT_ROOT, receipt["files"][table]["path"])
        with tempfile.TemporaryDirectory(prefix="netflow-query-") as temporary:
            con = connection(
                Path(temporary),
                Budget(
                    memory_mb=64,
                    threads=1,
                    temp_bytes=256 * 1024**2,
                    disk_reserve_bytes=0,
                ),
                persistent=False,
                allowed=[path.parent],
            )
            timer = threading.Timer(10, con.interrupt)
            timer.start()
            try:
                result = con.execute(
                    query.replace(
                        "BULK_TABLE", f"read_parquet({sql_literal(str(path))})"
                    ),
                    params,
                )
                names = [d[0] for d in result.description]
                return [
                    dict(zip(names, values, strict=True))
                    for values in result.fetchmany(101)
                ]
            except duckdb.Error:
                deny("bulk_query_budget_or_integrity", 503)
            finally:
                timer.cancel()
                timer.join(timeout=1)
                con.close()
    finally:
        _QUERY_SLOTS.release()


def _original(value: dict[str, Any], *, peer: bool = False) -> dict[str, Any]:
    count = value["record_count"]
    return {
        "peer_key" if peer else "object_key": value["object_key"],
        "ip": value["ip"],
        "protocol": value["protocol"],
        "peer_port" if peer else "local_port": value["port"],
        "features": {"record_count": count},
        "record_count": count,
        "source_refs_omitted": max(0, count - 20),
        "ownership": "UNKNOWN",
        "service_role": "UNKNOWN",
        "external_reachability": "NOT_VERIFIED",
        "policy": POLICY,
    }


def observations(
    session: Session,
    project: Project,
    analysis_id: uuid.UUID,
    *,
    ip: str | None,
    protocol: int | None,
    source_port: int | None,
    sort: str,
    skip: int,
    limit: int,
    cursor: str | None = None,
) -> ObservationPage:
    from app.domain.ip_consistency import normalize_ip
    from app.domain.netflow_reviews import Observation, ObservationPage

    row, receipt = gate(session, project, analysis_id)
    ip = normalize_ip(ip) if ip else None
    filters = ["source", ip, protocol, source_port, sort]
    last = _last(row, filters, cursor)
    if cursor and skip:
        deny("bulk_cursor_invalid", 422)
    where: list[Any] = [BulkObject.analysis_id == row.id]
    if ip is not None:
        where.append(BulkObject.ip == ip)
    if protocol is not None:
        where.append(BulkObject.protocol == protocol)
    if source_port is not None:
        where.append(BulkObject.port == source_port)
    count = (
        receipt["files"]["observations"]["rows"]
        if ip is None and protocol is None and source_port is None
        else session.exec(
            select(func.count()).select_from(BulkObject).where(*where)
        ).one()
    )
    descending = sort == "ip_desc"
    if last is not None:
        key = tuple_(
            col(BulkObject.family), col(BulkObject.ip_sort), col(BulkObject.object_key)
        )
        where.append(key < tuple(last) if descending else key > tuple(last))
    order = [
        col(BulkObject.family),
        col(BulkObject.ip_sort),
        col(BulkObject.object_key),
    ]
    values = session.exec(
        select(BulkObject)
        .where(*where)
        .order_by(*(x.desc() if descending else x for x in order))
        .offset(skip)
        .limit(limit + 1)
    ).all()
    data = [
        Observation(
            object_key=v.object_key,
            canonical_ip=v.ip,
            family=cast(Any, v.family),
            protocol_number=v.protocol,
            source_port=v.port,
            source_record_count=v.record_count,
            retained_count=min(v.record_count, 20),
            omitted_count=max(0, v.record_count - 20),
            original=_original(v.model_dump()),
        )
        for v in values[:limit]
    ]
    tail = values[limit - 1] if len(values) > limit else None
    return ObservationPage(
        **identity(row),
        data=data,
        count=count,
        skip=skip,
        limit=limit,
        next_cursor=_token(row, filters, [tail.family, tail.ip_sort, tail.object_key])
        if tail
        else None,
        raw_record_count=receipt["counts"]["raw"],
        total_observations=receipt["files"]["observations"]["rows"],
        total_source_records=receipt["counts"]["unique"],
        total_addresses=receipt["files"]["addresses"]["rows"],
        batch_created_at=row.created_at,
        batch_completed_at=row.completed_at,
        original_time_basis="bulk:per-file-declared-timezone",
        business_time_qualification="UNKNOWN",
    )


def peers(
    session: Session,
    project: Project,
    analysis_id: uuid.UUID,
    *,
    ip: str | None,
    protocol: int | None,
    peer_port: int | None,
    sort: str,
    skip: int,
    limit: int,
    cursor: str | None = None,
) -> PeerPage:
    from app.domain.ip_consistency import normalize_ip
    from app.domain.netflow_reviews import Peer, PeerPage

    row, receipt = gate(session, project, analysis_id)
    ip = normalize_ip(ip) if ip else None
    filters = ["peer", ip, protocol, peer_port, sort]
    last = _last(row, filters, cursor)
    if last and skip:
        deny("bulk_cursor_invalid", 422)
    clauses, params = [], []
    for name, value in (("ip", ip), ("protocol", protocol), ("port", peer_port)):
        if value is not None:
            clauses.append(f"{name} = ?")
            params.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    count = (
        receipt["files"]["peers"]["rows"]
        if not clauses
        else _sql(
            receipt, "peers", "SELECT count(*) AS n FROM BULK_TABLE" + where, params
        )[0]["n"]
    )
    if last:
        clauses.append(
            f"(family,ip_sort,object_key) {'<' if sort == 'ip_desc' else '>'} (?, ?, ?)"
        )
        params.extend(last)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    direction = "DESC" if sort == "ip_desc" else "ASC"
    values = _sql(
        receipt,
        "peers",
        f"SELECT * FROM BULK_TABLE{where} ORDER BY family {direction},ip_sort {direction},object_key {direction} LIMIT ? OFFSET ?",
        params + [limit + 1, skip],
    )
    data = [
        Peer(
            peer_key=v["object_key"],
            canonical_ip=v["ip"],
            family=v["family"],
            protocol_number=v["protocol"],
            peer_port=v["port"],
            source_record_count=v["record_count"],
            retained_count=min(v["record_count"], 20),
            omitted_count=max(0, v["record_count"] - 20),
            original=_original(v, peer=True),
        )
        for v in values[:limit]
    ]
    tail = values[limit - 1] if len(values) > limit else None
    return PeerPage(
        **identity(row),
        data=data,
        count=count,
        skip=skip,
        limit=limit,
        next_cursor=_token(
            row, filters, [tail["family"], tail["ip_sort"], tail["object_key"]]
        )
        if tail
        else None,
        total_peers=receipt["files"]["peers"]["rows"],
        total_peer_records=receipt["counts"]["unique"],
    )


def observation(
    session: Session, project: Project, analysis_id: uuid.UUID, object_key: str
) -> ObservationDetail:
    from app.domain.netflow_reviews import ObservationDetail

    row, _ = gate(session, project, analysis_id)
    value = session.get(BulkObject, (row.id, object_key))
    if value is None:
        deny("netflow_input_not_found", 404)
    context = legacy.context_for(
        session, project, row.dataset_id, row.context_revision_id
    )
    return ObservationDetail(
        **identity(row),
        object_key=object_key,
        canonical_ip=value.ip,
        family=cast(Literal[4, 6], value.family),
        protocol_number=value.protocol,
        source_port=value.port,
        source_record_count=value.record_count,
        retained_count=min(value.record_count, 20),
        omitted_count=max(0, value.record_count - 20),
        original=_original(value.model_dump()),
        batch_created_at=row.created_at,
        batch_completed_at=row.completed_at,
        original_time_basis="bulk:per-file-declared-timezone",
        business_time_qualification="UNKNOWN",
        context=context.payload,
    )


def evidence(
    session: Session,
    project: Project,
    analysis_id: uuid.UUID,
    *,
    object_key: str | None,
    peer_key: str | None,
    skip: int,
    limit: int,
) -> EvidencePage:
    from app.domain.netflow_reviews import EvidencePage, EvidenceRef

    if (object_key is None) == (peer_key is None):
        deny("netflow_artifact_schema_invalid", 422)
    row, receipt = gate(session, project, analysis_id)
    side: Literal["source", "peer"] = "source" if object_key else "peer"
    key = object_key or peer_key
    if object_key:
        value = session.get(BulkObject, (row.id, object_key))
        if value is None:
            deny("netflow_input_not_found", 404)
        count = value.record_count
    else:
        values = _sql(
            receipt,
            "peers",
            "SELECT record_count FROM BULK_TABLE WHERE object_key=? LIMIT 1",
            [key],
        )
        if not values:
            deny("netflow_input_not_found", 404)
        count = values[0]["record_count"]
    refs = _sql(
        receipt,
        f"{side}_samples",
        "SELECT source_ref,file_id,row_number FROM BULK_TABLE WHERE object_key=? ORDER BY source_ref LIMIT ? OFFSET ?",
        [key, limit, skip],
    )
    return EvidencePage(
        **identity(row),
        side=side,
        object_key=object_key,
        peer_key=peer_key,
        data=[
            EvidenceRef(
                reference=v["source_ref"],
                side=side,
                object_key=object_key,
                peer_key=peer_key,
            )
            for v in refs
        ],
        count=min(count, 20),
        skip=skip,
        limit=limit,
        retained_count=min(count, 20),
        omitted_count=max(0, count - 20),
        source_record_count=count,
        input_sha256=row.identity["ready_id"],
        artifact_sha256=receipt["files"][f"{side}_samples"]["sha256"],
        component_binding=identity(row),
    )


def record(
    session: Session, project: Project, analysis_id: uuid.UUID, reference: str
) -> dict[str, Any]:
    import re

    import pyarrow.parquet as pq  # type: ignore[import-untyped]

    row, _ = gate(session, project, analysis_id)
    match = re.fullmatch(r"sha256:([0-9a-f]{64}):row:([0-9]{20})", reference)
    if not match:
        deny("bulk_invalid_reference", 422)
    file_id, number = match[1], int(match[2])
    if number < 1 or number > 2**63 - 1:
        deny("bulk_invalid_reference", 422)
    shard = session.exec(
        select(BulkShard).where(
            BulkShard.dataset_id == row.dataset_id,
            BulkShard.file_id == file_id,
            BulkShard.first_row <= number,
            BulkShard.last_row >= number,
        )
    ).one_or_none()
    if shard is None:
        deny("netflow_input_not_found", 404)
    try:
        path = safe_file(settings.ARTIFACT_ROOT, shard.storage_key)
        if file_hash(path) != shard.sha256:
            raise BulkError("bulk_checkpoint_integrity")
        parquet = pq.ParquetFile(path)
        offset = number - shard.first_row
        for index in range(parquet.metadata.num_row_groups):
            rows = parquet.metadata.row_group(index).num_rows
            if offset < rows:
                value = parquet.read_row_group(index).slice(offset, 1).to_pylist()[0]
                return identity(row) | {
                    "reference": reference,
                    "record": value,
                    "shard_sha256": shard.sha256,
                }
            offset -= rows
    except BulkError, OSError, ValueError:
        # A discovered missing, unsafe, unreadable or corrupt committed shard
        # invalidates every dependent result; subsequent lists cannot hide it.
        pass
    dataset = session.get(BulkDataset, row.dataset_id)
    assert dataset is not None
    dataset.invalidated = True
    session.add(dataset)
    session.commit()
    deny("bulk_integrity_invalidated")
