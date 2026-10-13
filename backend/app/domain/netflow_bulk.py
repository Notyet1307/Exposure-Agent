"""Bulk admission and execution, reusing Analysis/Context and agent-compose."""

import os
import resource
import sys
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import Field
from sqlalchemy import delete, func, insert, tuple_
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain import netflow_processing as legacy
from app.domain.models import Artifact, AuditEvent, NetFlowDataset, Project
from app.domain.netflow_bulk_models import (
    BulkAddress,
    BulkDataset,
    BulkJob,
    BulkMember,
    BulkObject,
    BulkShard,
)
from app.domain.netflow_common import (
    deny,
    operation_result,
    project_for,
    record_operation,
    request_hash,
)
from app.domain.netflow_models import NetFlowAnalysis, NetFlowFeedbackRevision
from app.integrations.agent_compose import (
    AgentComposeClient,
    AgentComposeSessionObservation,
)
from app.models import User
from app.netflow_bulk import engine
from app.netflow_bulk.contracts import (
    ENGINE,
    NORMALIZER,
    POLICY,
    SCHEMA,
    VERSION,
    Budget,
    BulkError,
    Filter,
    Ready,
    Strict,
    digest,
)
from app.netflow_bulk.storage import atomic_json, file_hash, read_ready, safe_file


class Register(Strict):
    source_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    ready_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class Analyze(legacy.AnalysisCreate):
    bulk_filter: Filter = Field(default_factory=Filter)


def budget() -> Budget:
    return Budget(
        memory_mb=settings.NETFLOW_BULK_MEMORY_MB,
        threads=settings.NETFLOW_BULK_THREADS,
        temp_bytes=settings.NETFLOW_BULK_TEMP_BYTES,
        disk_reserve_bytes=settings.NETFLOW_BULK_DISK_RESERVE_BYTES,
        rss_bytes=settings.NETFLOW_BULK_RSS_BYTES,
        timeout_seconds=settings.NETFLOW_BULK_TIMEOUT_SECONDS,
    )


def is_bulk(row: NetFlowAnalysis) -> bool:
    return row.identity.get("backend") == VERSION


def register(
    session: Session, project: Project, actor: User, body: Register, key: str
) -> NetFlowDataset:
    if settings.NETFLOW_BULK_ROOT is None:
        deny("bulk_not_configured", 503)
    payload = body.model_dump()
    existing = operation_result(
        session, project, actor.id, "bulk:register", key, payload
    )
    if existing:
        return legacy.dataset_for(session, project, existing)
    ready = read_ready(
        settings.NETFLOW_BULK_ROOT,
        str(project.tenant_id),
        str(project.id),
        body.source_id,
        body.ready_id,
    )
    previous = session.exec(
        select(BulkDataset).where(
            BulkDataset.project_id == project.id,
            BulkDataset.tenant_id == project.tenant_id,
            BulkDataset.source_id == body.source_id,
            BulkDataset.ready_id == body.ready_id,
        )
    ).first()
    if previous:
        if previous.invalidated:
            deny("bulk_integrity_invalidated")
        row = legacy.dataset_for(session, project, previous.dataset_id)
    else:
        identity = uuid.uuid4()
        directory = (
            settings.ARTIFACT_ROOT / "netflow-bulk" / str(project.id) / str(identity)
        )
        directory.mkdir(parents=True, mode=0o750)
        artifacts: list[Artifact] = []
        # These are explicitly manifest/normalization-plan artifacts, never CSVs.
        for name, content in (
            ("input-manifest.json", ready.model_dump(mode="json")),
            (
                "normalization-plan.json",
                {"version": NORMALIZER, "input": body.ready_id, "schema": SCHEMA},
            ),
        ):
            path = directory / name
            atomic_json(path, content)
            item = Artifact(
                tenant_id=project.tenant_id,
                project_id=project.id,
                storage_key=path.relative_to(settings.ARTIFACT_ROOT).as_posix(),
                media_type="application/json",
                byte_size=path.stat().st_size,
                sha256=file_hash(path),
            )
            session.add(item)
            artifacts.append(item)
        session.flush()
        row = NetFlowDataset(
            id=identity,
            tenant_id=project.tenant_id,
            project_id=project.id,
            raw_artifact_id=artifacts[0].id,
            normalized_artifact_id=artifacts[1].id,
            display_filename=f"bulk:{body.source_id}",
            raw_sha256=artifacts[0].sha256,
            normalized_sha256=artifacts[1].sha256,
            dataset_contract_version=VERSION,
            schema_fingerprint=SCHEMA,
            encoding="utf-8-sig",
            byte_size=sum(m.size for m in ready.files),
            raw_record_count=0,
            activity_valid_record_count=0,
            isolated_record_count=0,
            duplicate_group_count=0,
            duplicate_record_count=0,
            warnings=[
                {
                    "code": "bulk_manifest_identity_only",
                    "counts_state": "NOT_IN_THIS_RECORD",
                    "count_source": "netflow_bulk_members",
                }
            ],
        )
        session.add(row)
        session.flush()
        session.add(
            BulkDataset(
                dataset_id=identity,
                tenant_id=project.tenant_id,
                project_id=project.id,
                source_id=body.source_id,
                ready_id=body.ready_id,
                manifest=ready.model_dump(mode="json"),
                normalizer=NORMALIZER,
            )
        )
        session.flush()
        for member in ready.files:
            session.add(
                BulkMember(
                    dataset_id=identity, file_id=member.sha256, byte_size=member.size
                )
            )
    record_operation(session, project, actor.id, "bulk:register", key, payload, row.id)
    session.commit()
    return row


def reserve(
    session: Session,
    project: Project,
    actor: User,
    dataset_id: uuid.UUID,
    body: Analyze,
    key: str,
) -> tuple[NetFlowAnalysis, bool]:
    payload = body.model_dump(mode="json")
    existing = operation_result(
        session, project, actor.id, f"analysis:{dataset_id}", key, payload
    )
    if existing:
        return legacy.analysis_for(session, project, existing), False
    dataset = legacy.dataset_for(session, project, dataset_id)
    bulk = session.get(BulkDataset, dataset.id)
    if bulk is None or bulk.invalidated:
        deny("bulk_input_not_found", 404)
    context = legacy.context_for(session, project, dataset.id, body.context_revision_id)
    legacy.validate_context(session, project, context, write=True)
    identity = {
        "backend": VERSION,
        "engine": ENGINE,
        "policy": POLICY,
        "normalizer": NORMALIZER,
        "ready_id": bulk.ready_id,
        "source_id": bulk.source_id,
        "dataset": {
            "id": str(dataset.id),
            "raw_sha256": dataset.raw_sha256,
            "normalized_sha256": dataset.normalized_sha256,
            "contract_version": VERSION,
            "schema_fingerprint": SCHEMA,
        },
        "context_revision_id": str(context.id),
        "context_sha256": request_hash(context.payload),
        "config": body.bulk_filter.model_dump(mode="json"),
        "runner_build_version": settings.governance_runner_build_version,
    }
    fingerprint = request_hash(identity)
    parent = None
    if body.retry_of_analysis_id is not None:
        parent = legacy.analysis_for(session, project, body.retry_of_analysis_id)
        if (
            not is_bulk(parent)
            or parent.processing_identity_sha256 != fingerprint
            or parent.status != "FAILED"
        ):
            deny("netflow_retry_not_allowed")
        _, observed = legacy.session_observation(parent)
        if observed != AgentComposeSessionObservation.TERMINAL:
            deny("netflow_retry_not_allowed")
        parent.terminal_confirmed = True
        session.add(parent)
        previous = session.exec(
            select(NetFlowAnalysis).where(
                NetFlowAnalysis.retry_of_analysis_id == parent.id
            )
        ).first()
    else:
        previous = session.exec(
            select(NetFlowAnalysis).where(
                NetFlowAnalysis.project_id == project.id,
                NetFlowAnalysis.processing_identity_sha256 == fingerprint,
                col(NetFlowAnalysis.retry_of_analysis_id).is_(None),
            )
        ).first()
    if previous:
        record_operation(
            session,
            project,
            actor.id,
            f"analysis:{dataset_id}",
            key,
            payload,
            previous.id,
        )
        session.commit()
        return previous, False
    session.exec(select(func.pg_advisory_xact_lock(304, 1)))
    pending = session.exec(
        select(BulkJob.analysis_id)
        .join(NetFlowAnalysis, BulkJob.analysis_id == NetFlowAnalysis.id)
        .where(col(NetFlowAnalysis.status).in_(legacy.UNFINISHED))
    ).first()
    if pending is not None:
        deny("bulk_capacity_busy", 409)
    analysis_id = uuid.uuid4()
    client = AgentComposeClient()
    row = NetFlowAnalysis(
        id=analysis_id,
        tenant_id=project.tenant_id,
        project_id=project.id,
        dataset_id=dataset.id,
        context_revision_id=context.id,
        network_namespace=context.network_namespace,
        processing_identity_sha256=fingerprint,
        identity=identity,
        request=payload,
        quality={"counts_state": "PENDING", "policy": POLICY},
        test_fixture=context.payload["component_context"]["test_fixture"],
        created_by=actor.id,
        retry_of_analysis_id=parent.id if parent else None,
        agent_run_id=client.expected_netflow_analysis_run_id(str(analysis_id)),
        agent_project_id=client.project_id,
        runner_build_version=settings.governance_runner_build_version,
    )
    session.add(row)
    session.flush()
    session.add(
        BulkJob(
            analysis_id=row.id,
            tenant_id=project.tenant_id,
            project_id=project.id,
            dataset_id=dataset.id,
            selection=identity["config"],
        )
    )
    record_operation(
        session, project, actor.id, f"analysis:{dataset_id}", key, payload, row.id
    )
    session.commit()
    return row, True


def _actor_context(session: Session, project: Project, row: NetFlowAnalysis) -> None:
    actor = session.get(User, row.created_by)
    if actor is None:
        deny("netflow_write_forbidden", 403)
    project_for(session, actor, project.id, write=True)
    context = legacy.context_for(
        session, project, row.dataset_id, row.context_revision_id
    )
    legacy.validate_context(session, project, context, write=True)
    if (
        row.runner_build_version != settings.governance_runner_build_version
        or row.identity.get("engine") != ENGINE
        or row.identity.get("policy") != POLICY
        or row.identity.get("context_sha256") != request_hash(context.payload)
        or request_hash(row.identity) != row.processing_identity_sha256
    ):
        deny("netflow_component_version_unsupported", 422)
    if row.test_fixture and (
        not settings.NETFLOW_ALLOW_TEST_FIXTURES or settings.ENVIRONMENT == "production"
    ):
        deny("netflow_test_fixture_forbidden", 422)


def _job(session: Session, analysis_id: uuid.UUID, fence: int | None = None) -> BulkJob:
    job = session.exec(
        select(BulkJob)
        .where(BulkJob.analysis_id == analysis_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    if fence is not None and (
        job.fence != fence
        or job.lease_until is None
        or job.lease_until <= get_datetime_utc()
        or job.cancel_requested
        or job.invalidated
    ):
        raise BulkError("bulk_lease_lost_or_cancelled")
    return job


def claim(
    session: Session, analysis_id: uuid.UUID, run_id: str, session_id: str
) -> int | None:
    # One bulk analysis at a time. This is a capacity gate, not a scheduler.
    project, row = legacy._locked(session, analysis_id)
    session.exec(select(func.pg_advisory_xact_lock(304, 1)))
    job = _job(session, analysis_id)
    now = get_datetime_utc()
    if row.agent_run_id != run_id or (
        row.session_id is not None and row.session_id != session_id
    ):
        raise BulkError("bulk_execution_identity")
    if row.status not in legacy.UNFINISHED or job.cancel_requested or job.invalidated:
        return None
    if job.lease_until and job.lease_until > now:
        return None
    active = session.exec(
        select(BulkJob.analysis_id).where(
            BulkJob.analysis_id != analysis_id, col(BulkJob.lease_until) > now
        )
    ).first()
    if active is not None:
        raise BulkError("bulk_capacity_busy")
    _actor_context(session, project, row)
    job.fence += 1
    job.heartbeat_at = now
    job.lease_until = now + timedelta(seconds=settings.NETFLOW_BULK_LEASE_SECONDS)
    job.phase = "NORMALIZING"
    row.session_id = session_id
    row.started_at = row.started_at or now
    row.status = "RUNNING"
    session.add(job)
    session.add(row)
    session.commit()
    return job.fence


def heartbeat(session: Session, analysis_id: uuid.UUID, fence: int) -> None:
    job = _job(session, analysis_id, fence)
    job.heartbeat_at = get_datetime_utc()
    job.lease_until = job.heartbeat_at + timedelta(
        seconds=settings.NETFLOW_BULK_LEASE_SECONDS
    )
    session.add(job)
    session.commit()


def _checkpoint(
    session: Session,
    analysis_id: uuid.UUID,
    fence: int,
    file_id: str,
    value: dict[str, Any],
) -> None:
    job = _job(session, analysis_id, fence)
    path = Path(value["path"])
    session.add(
        BulkShard(
            dataset_id=job.dataset_id,
            file_id=file_id,
            ordinal=value["ordinal"],
            storage_key=path.relative_to(settings.ARTIFACT_ROOT).as_posix(),
            sha256=value["sha256"],
            size=value["size"],
            first_row=value["first_row"],
            last_row=value["last_row"],
            rows=value["rows"],
            invalid=value["invalid"],
        )
    )
    session.commit()


def execute(
    session: Session, analysis_id: uuid.UUID, run_id: str, session_id: str
) -> None:
    row = session.get(NetFlowAnalysis, analysis_id)
    if row is None:
        raise BulkError("bulk_input_not_found")
    observed_id, observed = legacy.session_observation(row)
    if observed_id != session_id or observed != AgentComposeSessionObservation.RUNNING:
        raise BulkError("bulk_execution_identity")
    wait_started = time.monotonic()
    while True:
        try:
            fence = claim(session, analysis_id, run_id, session_id)
            break
        except BulkError as error:
            session.rollback()
            if (
                error.code != "bulk_capacity_busy"
                or time.monotonic() - wait_started
                > settings.NETFLOW_BULK_TIMEOUT_SECONDS
            ):
                raise
            job = _job(session, analysis_id)
            job.phase = "WAITING_CAPACITY"
            session.add(job)
            session.commit()
            time.sleep(1)
    if fence is None:
        return
    run_engine(session, analysis_id, fence)


def run_engine(session: Session, analysis_id: uuid.UUID, fence: int) -> None:
    """The test harness can inject a claimed execution without any external runtime."""
    job = _job(session, analysis_id, fence)
    row = session.get(NetFlowAnalysis, analysis_id)
    assert row is not None
    bulk = session.get(BulkDataset, job.dataset_id)
    assert bulk is not None
    ready = Ready.model_validate(bulk.manifest)
    if bulk.invalidated or settings.NETFLOW_BULK_ROOT is None:
        raise BulkError("bulk_input_not_found")
    limits = budget()
    root = (
        settings.ARTIFACT_ROOT
        / "netflow-bulk"
        / str(job.project_id)
        / str(job.dataset_id)
        / "attempts"
        / str(analysis_id)
        / str(fence)
    )
    root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    stop = threading.Event()
    errors: list[str] = []
    bind = session.get_bind()
    analysis_dataset = job.dataset_id
    metrics: dict[str, Any] = {
        "read_bytes": 0,
        "parsed_records": 0,
        "reused_files": 0,
        "fence": fence,
    }

    def monitor() -> None:
        while not stop.wait(3):
            try:
                with Session(bind) as own:
                    heartbeat(own, analysis_id, fence)
                if time.monotonic() - started > limits.timeout_seconds:
                    raise BulkError("bulk_timeout")
            except Exception as error:
                errors.append(
                    error.code
                    if isinstance(error, BulkError)
                    else "bulk_lease_lost_or_cancelled"
                )
                return

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()

    def pulse() -> None:
        if errors:
            raise BulkError(errors[0])
        if time.monotonic() - started > limits.timeout_seconds:
            raise BulkError("bulk_timeout")
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_bytes = int(peak if sys.platform == "darwin" else peak * 1024)
        metrics["peak_rss_bytes"] = max(
            int(metrics.get("peak_rss_bytes", 0)), rss_bytes
        )
        if rss_bytes > limits.rss_bytes:
            raise BulkError("bulk_rss_budget")
        import shutil

        if shutil.disk_usage(root).free < limits.disk_reserve_bytes:
            raise BulkError("bulk_disk_budget")

    session.commit()
    try:
        if not bulk.complete:
            disk_ready = read_ready(
                settings.NETFLOW_BULK_ROOT,
                ready.tenant_id,
                ready.project_id,
                ready.source_id,
                bulk.ready_id,
            )
            if disk_ready != ready:
                raise BulkError("bulk_input_changed")
        for member in ready.files:
            pulse()
            status = session.get(BulkMember, (analysis_dataset, member.sha256))
            assert status is not None
            if status.complete:
                metrics["reused_files"] += 1
                session.commit()
                continue
            input_path = safe_file(
                settings.NETFLOW_BULK_ROOT,
                f"{ready.tenant_id}/{ready.project_id}/{ready.source_id}/{bulk.ready_id}/{member.sha256}",
            )

            def committed(
                ordinal: int, file_id: str = member.sha256
            ) -> dict[str, Any] | None:
                stored = session.get(BulkShard, (analysis_dataset, file_id, ordinal))
                if stored is None:
                    return None
                return {
                    "path": str(safe_file(settings.ARTIFACT_ROOT, stored.storage_key)),
                    "sha256": stored.sha256,
                    "first_row": stored.first_row,
                    "last_row": stored.last_row,
                }

            def save_checkpoint(
                value: dict[str, Any], file_id: str = member.sha256
            ) -> None:
                _checkpoint(session, analysis_id, fence, file_id, value)

            result = engine.normalize_file(
                input_path,
                member,
                root / "new-shards" / member.sha256,
                limits,
                checkpoint=save_checkpoint,
                committed=committed,
                pulse=pulse,
            )
            _job(session, analysis_id, fence)
            status = session.get(BulkMember, (analysis_dataset, member.sha256))
            assert status is not None
            (
                status.complete,
                status.raw_count,
                status.invalid_count,
                status.shard_count,
            ) = True, result["raw"], result["invalid"], result["shards"]
            session.add(status)
            session.commit()
            metrics["read_bytes"] += result["read_bytes"]
            metrics["parsed_records"] += result["raw"]
        # Build one immutable normalized directory per dataset. Refilters only
        # stat the sealed shards; no rehashing whole Parquet files defeats pruning.
        normalized = (
            settings.ARTIFACT_ROOT
            / "netflow-bulk"
            / str(job.project_id)
            / str(analysis_dataset)
            / "normalized"
        )
        normalized.mkdir(parents=True, exist_ok=True)
        last: tuple[str, int] | None = None
        shard_total = 0
        while True:
            query = select(BulkShard).where(BulkShard.dataset_id == analysis_dataset)
            if last is not None:
                query = query.where(
                    tuple_(col(BulkShard.file_id), col(BulkShard.ordinal)) > last
                )
            shards = session.exec(
                query.order_by(col(BulkShard.file_id), col(BulkShard.ordinal)).limit(
                    100
                )
            ).all()
            if not shards:
                break
            for shard in shards:
                pulse()
                target = normalized / shard.file_id / f"{shard.ordinal:08d}.parquet"
                if shard.sealed_inode is None:
                    path = safe_file(settings.ARTIFACT_ROOT, shard.storage_key)
                    if (
                        path.stat().st_size != shard.size
                        or file_hash(path) != shard.sha256
                    ):
                        raise BulkError("bulk_checkpoint_integrity")
                    target.parent.mkdir(exist_ok=True)
                    if not target.exists():
                        os.link(path, target)
                    if target.is_symlink() or file_hash(target) != shard.sha256:
                        raise BulkError("bulk_checkpoint_integrity")
                    state = target.stat()
                    shard.sealed_inode, shard.sealed_mtime_ns, shard.sealed_ctime_ns = (
                        state.st_ino,
                        state.st_mtime_ns,
                        state.st_ctime_ns,
                    )
                    session.add(shard)
                else:
                    target = safe_file(
                        normalized, f"{shard.file_id}/{shard.ordinal:08d}.parquet"
                    )
                    state = target.stat()
                    if (
                        state.st_ino,
                        state.st_size,
                        state.st_mtime_ns,
                        state.st_ctime_ns,
                    ) != (
                        shard.sealed_inode,
                        shard.size,
                        shard.sealed_mtime_ns,
                        shard.sealed_ctime_ns,
                    ):
                        raise BulkError("bulk_checkpoint_integrity")
                shard_total += 1
                last = (shard.file_id, shard.ordinal)
            with session.no_autoflush:
                _job(session, analysis_id, fence)
            session.commit()
        if sum(1 for _ in normalized.glob("*/*.parquet")) != shard_total:
            raise BulkError("bulk_checkpoint_integrity")
        _job(session, analysis_id, fence)
        bulk = session.get(BulkDataset, analysis_dataset)
        assert bulk is not None
        bulk.complete = True
        session.add(bulk)
        session.commit()
        metrics["normalization_seconds"] = time.monotonic() - started
        current = _job(session, analysis_id, fence)
        current.phase = "COMPUTING"
        session.add(current)
        session.commit()
        output = engine.compute(
            normalized,
            root / "result",
            Filter.model_validate(job.selection),
            limits,
            pulse=pulse,
        )
        pulse()
        publish(
            session,
            analysis_id,
            fence,
            output,
            metrics | {"elapsed_seconds": time.monotonic() - started},
        )
    except Exception as error:
        session.rollback()
        legacy._locked(session, analysis_id)
        current = _job(session, analysis_id)
        if current.fence == fence:
            if isinstance(error, BulkError) and error.code in (
                "bulk_input_changed",
                "bulk_checkpoint_integrity",
            ):
                damaged = session.get(BulkDataset, current.dataset_id)
                if damaged is not None:
                    damaged.invalidated = True
                    session.add(damaged)
            current.phase = "CANCELLED" if current.cancel_requested else "FAILED"
            current.lease_until = None
            current.metrics = metrics | {
                "error_code": error.code
                if isinstance(error, BulkError)
                else "bulk_processing_failed"
            }
            row = session.get(NetFlowAnalysis, analysis_id)
            assert row is not None
            if row.status in legacy.UNFINISHED:
                row.status = "FAILED"
                row.error_code = str(current.metrics["error_code"])
                row.completed_at = get_datetime_utc()
                session.add(row)
            session.add(current)
            session.commit()
        raise
    finally:
        stop.set()
        thread.join(timeout=5)


def publish(
    session: Session,
    analysis_id: uuid.UUID,
    fence: int,
    output: dict[str, Any],
    metrics: dict[str, Any],
) -> None:
    # Projections are staged in bounded batches; readability requires final commit.
    publication_started = time.monotonic()
    admitted = _job(session, analysis_id, fence)
    expected = (
        settings.ARTIFACT_ROOT
        / "netflow-bulk"
        / str(admitted.project_id)
        / str(admitted.dataset_id)
        / "attempts"
        / str(analysis_id)
        / str(fence)
        / "result"
    )
    for name, descriptor in output["files"].items():
        path = Path(descriptor["path"])
        if path.parent != expected or path.name != f"{name}.parquet":
            raise BulkError("bulk_unsafe_path")
        safe_file(
            settings.ARTIFACT_ROOT, path.relative_to(settings.ARTIFACT_ROOT).as_posix()
        )
    _job(session, analysis_id, fence)
    session.exec(delete(BulkObject).where(col(BulkObject.analysis_id) == analysis_id))
    session.exec(delete(BulkAddress).where(col(BulkAddress.analysis_id) == analysis_id))
    session.commit()
    for table, model in (("observations", BulkObject), ("addresses", BulkAddress)):
        descriptor = output["files"][table]
        path = Path(descriptor["path"])
        if file_hash(path) != descriptor["sha256"]:
            raise BulkError("bulk_result_integrity")
        for batch in engine.batches(path):
            _job(session, analysis_id, fence)
            session.exec(
                insert(model),
                params=[{"analysis_id": analysis_id, **value} for value in batch],
            )
            session.commit()
    project, analysis = legacy._locked(session, analysis_id)
    job = _job(session, analysis_id, fence)
    _actor_context(session, project, analysis)
    counts = output["counts"]
    member_counts = session.exec(
        select(
            func.sum(BulkMember.raw_count), func.sum(BulkMember.invalid_count)
        ).where(BulkMember.dataset_id == job.dataset_id)
    ).one()
    if tuple(member_counts) != (counts["raw"], counts["invalid"]):
        raise BulkError("bulk_count_mismatch")
    for model, name in ((BulkObject, "observations"), (BulkAddress, "addresses")):
        actual = session.exec(
            select(func.count())
            .select_from(model)
            .where(model.analysis_id == analysis_id)
        ).one()
        if actual != output["files"][name]["rows"]:
            raise BulkError("bulk_projection_mismatch")
    receipt = dict(output)
    receipt["files"] = {}
    for name, descriptor in output["files"].items():
        path = Path(descriptor["path"])
        if file_hash(path) != descriptor["sha256"]:
            raise BulkError("bulk_result_integrity")
        st = path.stat()
        receipt["files"][name] = {
            **descriptor,
            "path": path.relative_to(settings.ARTIFACT_ROOT).as_posix(),
            "inode": st.st_ino,
            "mtime_ns": st.st_mtime_ns,
            "ctime_ns": st.st_ctime_ns,
        }
    if job.lease_until is None or job.lease_until <= get_datetime_utc():
        raise BulkError("bulk_lease_lost_or_cancelled")
    receipt["identity_sha256"] = analysis.processing_identity_sha256
    receipt["receipt_sha256"] = digest(receipt)
    initial = NetFlowFeedbackRevision(
        tenant_id=project.tenant_id,
        project_id=project.id,
        analysis_id=analysis.id,
        revision=1,
        system_generated=True,
        artifact_manifest={
            "backend": VERSION,
            "tasks": 0,
            "capability": "deterministic_observations_only",
        },
    )
    session.add(initial)
    analysis.initial_feedback_revision_id = initial.id
    analysis.result = receipt
    analysis.status = "SUCCEEDED_WITH_WARNINGS" if counts["invalid"] else "SUCCEEDED"
    analysis.completed_at = get_datetime_utc()
    analysis.error_code = None
    job.phase, job.lease_until = "SUCCEEDED", None
    projection_seconds = time.monotonic() - publication_started
    job.metrics = metrics | {
        "projection_seconds": projection_seconds,
        "elapsed_seconds": metrics.get("elapsed_seconds", 0) + projection_seconds,
    }
    session.add(analysis)
    session.add(job)
    session.add(
        AuditEvent(
            tenant_id=project.tenant_id,
            project_id=project.id,
            actor_subject=str(analysis.created_by),
            actor_type="user",
            action="netflow.bulk_published",
            target_type="netflow_analysis",
            target_id=analysis.id,
            after_data={
                "identity_sha256": analysis.processing_identity_sha256,
                "receipt_sha256": receipt["receipt_sha256"],
                "counts": counts,
            },
        )
    )
    session.commit()


def reconcile(
    session: Session, project: Project, actor: User, row: NetFlowAnalysis, key: str
) -> NetFlowAnalysis:
    operation = f"reconcile:{row.id}"
    payload = {"analysis_id": str(row.id)}
    if operation_result(session, project, actor.id, operation, key, payload):
        return row
    project, row = legacy._locked(session, row.id)
    job = _job(session, row.id)
    if row.status in legacy.SUCCESS:
        from app.domain.netflow_bulk_queries import gate

        gate(session, project, row.id)
    else:
        _, observed = legacy.session_observation(row)
        if observed == AgentComposeSessionObservation.TERMINAL:
            if row.status in legacy.UNFINISHED:
                row.status = "FAILED"
                row.error_code = "bulk_interrupted"
                row.completed_at = get_datetime_utc()
            row.terminal_confirmed = True
            job.lease_until = None
            job.fence += 1
            job.phase = "CANCELLED" if job.cancel_requested else "FAILED"
            session.add(row)
            session.add(job)
        elif job.lease_until is not None and job.lease_until <= get_datetime_utc():
            # Fencing stops an expired worker. Terminal Session proof is still
            # required before an explicit retry can reserve another execution.
            job.fence += 1
            row.status, row.error_code = "UNKNOWN", "bulk_lease_expired"
            session.add(row)
            session.add(job)
    record_operation(session, project, actor.id, operation, key, payload, row.id)
    session.commit()
    return row


def invalidate(
    session: Session, project: Project, actor: User, analysis_id: uuid.UUID
) -> None:
    row = legacy.analysis_for(session, project, analysis_id)
    job = _job(session, row.id)
    job.invalidated = True
    job.cancel_requested = True
    job.fence += 1
    session.add(job)
    session.add(
        AuditEvent(
            tenant_id=project.tenant_id,
            project_id=project.id,
            actor_subject=str(actor.id),
            actor_type="user",
            action="netflow.bulk_invalidated",
            target_type="netflow_analysis",
            target_id=row.id,
            after_data={"identity_sha256": row.processing_identity_sha256},
        )
    )
    session.commit()
