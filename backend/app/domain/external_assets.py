"""Local reads and bounded, independently published CloudAtlas domain versions."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import uuid
from datetime import timedelta
from typing import Any, NoReturn, cast

from fastapi import HTTPException
from sqlalchemy import delete
from sqlmodel import Session, col, func, select

from app.api.project_authorization import get_authorized_project
from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain.cloudatlas_sources import CloudAtlasBoundaryError
from app.domain.external_asset_models import (
    Domain,
    DomainStatus,
    ExternalAssetHead,
    ExternalAssetRecord,
    ExternalAssetVersion,
    ExternalDomainPublic,
    ExternalRecordDetailPublic,
    ExternalRecordPublic,
    ExternalRecordsPublic,
    ExternalSourcePublic,
    ExternalSync,
    ExternalSyncCreate,
    ExternalSyncPublic,
    ExternalVersionPublic,
)
from app.domain.models import AuditEvent, Project, ProjectRole, SourceInstance
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
    AgentComposeSessionObservation,
)
from app.integrations.cloudatlas_assets import OctobusCloudAtlasAssetsClient
from app.models import User

UNFINISHED = ("PENDING", "RUNNING", "UNKNOWN")


class SyncError(Exception):
    def __init__(self, code: str, *, unknown: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.unknown = unknown


def deny(code: str, status: int = 409) -> NoReturn:
    raise HTTPException(status_code=status, detail={"code": code})


def source_for(
    session: Session,
    project: Project,
    source_id: uuid.UUID,
    *,
    data: bool = True,
    lock: bool = False,
) -> SourceInstance:
    query = select(SourceInstance).where(
        SourceInstance.id == source_id,
        SourceInstance.project_id == project.id,
        SourceInstance.tenant_id == project.tenant_id,
        SourceInstance.capability_profile == "assets-v1",
    )
    if lock:
        query = query.with_for_update()
    source = session.exec(query).one_or_none()
    if source is None:
        deny("external_source_not_found", 404)
    assert source is not None
    if data and not source.data_access_enabled:
        deny("external_data_access_revoked", 403)
    return source


def can_manage(session: Session, user: User, project: Project) -> bool:
    if project.archived_at is not None:
        return False
    try:
        get_authorized_project(
            session=session,
            user=user,
            project_id=project.id,
            allowed_roles=(ProjectRole.OPERATOR,),
        )
    except HTTPException:
        return False
    return True


def audit(
    session: Session,
    source: SourceInstance,
    actor_id: uuid.UUID,
    action: str,
    target_id: uuid.UUID,
    after: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            tenant_id=source.tenant_id,
            project_id=source.project_id,
            actor_subject=str(actor_id),
            actor_type="user",
            action=action,
            target_type="external_assets",
            target_id=target_id,
            after_data=after,
        )
    )


def source_public(source: SourceInstance) -> ExternalSourcePublic:
    return ExternalSourcePublic(
        **source.model_dump(),
        validation_status=(
            "failed"
            if source.validation_error_code
            else "validated"
            if source.validated_fingerprint
            else "not_validated"
        ),
    )


def credentials(source: SourceInstance) -> tuple[str, str]:
    token = settings.CLOUDATLAS_ASSETS_CAPSET_TOKEN.get_secret_value()
    if not token:
        raise SyncError("external_credential_missing")
    try:
        fingerprint = (
            OctobusCloudAtlasAssetsClient()
            .validate_credentials(source, capset_token=token)
            .value
        )
    except CloudAtlasBoundaryError as error:
        raise SyncError(
            error.code, unknown=error.code == "cloudatlas_connectivity_failed"
        ) from None
    return fingerprint, hashlib.sha256(token.encode()).hexdigest()


def ready(source: SourceInstance) -> tuple[str, str]:
    if not source.enabled or not source.data_access_enabled:
        raise SyncError("external_source_disabled")
    fingerprint, token_hash = credentials(source)
    if (
        source.validated_fingerprint != fingerprint
        or source.assets_token_sha256 != token_hash
        or source.validation_error_code
    ):
        raise SyncError("external_material_changed")
    return fingerprint, token_hash


def sync_public(session: Session, sync: ExternalSync) -> ExternalSyncPublic:
    versions = session.exec(
        select(ExternalAssetVersion)
        .where(ExternalAssetVersion.sync_id == sync.id)
        .order_by(ExternalAssetVersion.domain)
    ).all()
    return ExternalSyncPublic(
        **sync.model_dump(),
        domains=[
            ExternalDomainPublic(
                domain=cast(Domain, version.domain),
                status=cast(DomainStatus, version.status),
                version_id=version.id if version.status == "PUBLISHED" else None,
                record_count=version.record_count
                if version.status == "PUBLISHED"
                else 0,
                error_code=version.error_code,
            )
            for version in versions
        ],
    )


def version_public(version: ExternalAssetVersion) -> ExternalVersionPublic:
    values = version.model_dump()
    values["status"] = (
        "EXPIRED" if version.retain_until <= get_datetime_utc() else "PUBLISHED"
    )
    return ExternalVersionPublic.model_validate(values)


def selected_version(
    session: Session,
    source: SourceInstance,
    domain: Domain,
    version_id: uuid.UUID | None,
) -> ExternalAssetVersion | None:
    if version_id is None:
        head = session.get(ExternalAssetHead, (source.id, domain))
        if head is None:
            return None
        version_id = head.version_id
    version = session.get(ExternalAssetVersion, version_id)
    if (
        version is None
        or version.source_id != source.id
        or version.domain != domain
        or version.status != "PUBLISHED"
        or version.space_id != source.space_id
    ):
        deny("external_version_not_found", 404)
    return version


def records(
    session: Session,
    source: SourceInstance,
    *,
    domain: Domain,
    version_id: uuid.UUID | None,
    ip: str | None,
    status: str | None,
    skip: int,
    limit: int,
) -> ExternalRecordsPublic:
    version = selected_version(session, source, domain, version_id)
    if version is None:
        return ExternalRecordsPublic(data=[], count=0, version=None, state="NOT_SYNCED")
    public = version_public(version)
    if public.status == "EXPIRED":
        return ExternalRecordsPublic(data=[], count=0, version=public, state="EXPIRED")
    query = select(ExternalAssetRecord).where(
        ExternalAssetRecord.version_id == version.id
    )
    if ip is not None:
        try:
            canonical_ip = str(ipaddress.ip_address(ip))
        except ValueError:
            deny("external_ip_filter_invalid", 422)
        query = query.where(ExternalAssetRecord.canonical_ip == canonical_ip)
    if status is not None:
        query = query.where(ExternalAssetRecord.fields["status"].astext == status)
    count = session.exec(select(func.count()).select_from(query.subquery())).one()
    rows = session.exec(
        query.order_by(ExternalAssetRecord.canonical_ip, ExternalAssetRecord.source_id)
        .offset(skip)
        .limit(limit)
    ).all()
    return ExternalRecordsPublic(
        data=[ExternalRecordPublic.model_validate(row) for row in rows],
        count=count,
        version=public,
        state="PUBLISHED",
    )


def detail(
    session: Session,
    source: SourceInstance,
    version_id: uuid.UUID,
    record_id: uuid.UUID,
    port_version_id: uuid.UUID | None,
    skip: int,
    limit: int,
) -> ExternalRecordDetailPublic:
    version = session.get(ExternalAssetVersion, version_id)
    if version is None or version.domain not in ("ip", "port"):
        deny("external_version_not_found", 404)
    assert version is not None
    version = selected_version(
        session, source, cast(Domain, version.domain), version_id
    )
    assert version is not None
    if version.retain_until <= get_datetime_utc():
        deny("external_version_expired", 410)
    row = session.get(ExternalAssetRecord, record_id)
    if row is None or row.version_id != version.id:
        deny("external_record_not_found", 404)
    assert row is not None
    matched = ExternalRecordsPublic(data=[], count=0, version=None, state="NOT_SYNCED")
    if version.domain == "ip":
        matched = records(
            session,
            source,
            domain="port",
            version_id=port_version_id,
            ip=row.canonical_ip,
            status=None,
            skip=skip,
            limit=limit,
        )
        if matched.state == "EXPIRED" and port_version_id is not None:
            deny("external_version_expired", 410)
    return ExternalRecordDetailPublic(
        record=ExternalRecordPublic.model_validate(row),
        version=version_public(version),
        matched_ports=matched.data,
        matched_port_count=matched.count,
        port_version=matched.version,
    )


def reserve_sync(
    session: Session,
    source: SourceInstance,
    actor: User,
    request: ExternalSyncCreate,
    key: str,
) -> tuple[ExternalSync, bool]:
    if not key.strip() or len(key) > 128 or any(ord(c) < 32 for c in key):
        deny("external_idempotency_key_invalid", 422)
    payload = request.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    existing = session.exec(
        select(ExternalSync).where(
            ExternalSync.source_id == source.id,
            ExternalSync.project_id == source.project_id,
            ExternalSync.actor_id == actor.id,
            ExternalSync.idempotency_key == key,
        )
    ).one_or_none()
    if existing:
        if existing.request_sha256 != digest:
            deny("external_idempotency_conflict")
        return existing, False
    if request.retain_until <= get_datetime_utc():
        deny("external_retention_expired", 422)
    pending = session.exec(
        select(ExternalSync.id).where(
            ExternalSync.source_id == source.id,
            col(ExternalSync.status).in_(UNFINISHED),
        )
    ).first()
    if pending is not None:
        deny("external_sync_unresolved")
    fingerprint, token_hash = ready(source)
    if source.space_id is None:
        deny("external_source_scope_invalid")
    sync_id = uuid.uuid4()
    client = AgentComposeClient()
    sync = ExternalSync(
        id=sync_id,
        source_id=source.id,
        project_id=source.project_id,
        actor_id=actor.id,
        idempotency_key=key,
        request_sha256=digest,
        request=payload,
        fingerprint=fingerprint,
        token_sha256=token_hash,
        agent_run_id=client.expected_cloudatlas_sync_run_id(str(sync_id)),
        agent_project_id=client.project_id,
        retain_until=request.retain_until,
    )
    session.add(sync)
    session.flush()
    for domain in ("ip", "port"):
        session.add(
            ExternalAssetVersion(
                sync_id=sync.id,
                source_id=source.id,
                domain=domain,
                space_id=source.space_id,
                instance_id=source.instance_id,
                capset_id=source.capset_id,
                filter={"status": "valid"} if domain == "ip" else {},
                fingerprint=fingerprint,
                retain_until=request.retain_until,
            )
        )
    audit(session, source, actor.id, "external_sync.reserved", sync.id)
    session.commit()  # Reservation must survive an ambiguous StartAgentRun response.
    session.refresh(sync)
    return sync, True


def launch_sync(session: Session, sync: ExternalSync) -> ExternalSync:
    try:
        start = AgentComposeClient().start_cloudatlas_sync(
            client_request_id=str(sync.id), sync_id=str(sync.id)
        )
        if start.run_id != sync.agent_run_id:
            raise AgentComposeBoundaryError("agent_compose_response_contract_failed")
    except AgentComposeBoundaryError:
        session.rollback()
        current = session.exec(
            select(ExternalSync).where(ExternalSync.id == sync.id).with_for_update()
        ).one()
        if current.status in UNFINISHED and current.started_at is None:
            current.status, current.error_code = "UNKNOWN", "external_start_unknown"
            session.add(current)
            session.commit()
        return current
    session.expire_all()
    current = session.exec(
        select(ExternalSync).where(ExternalSync.id == sync.id).with_for_update()
    ).one()
    if current.status in UNFINISHED and current.started_at is None:
        if current.session_id is not None and current.session_id != start.session_id:
            current.status, current.error_code = "UNKNOWN", "external_session_mismatch"
        elif start.session_id:
            current.session_id = start.session_id
        else:
            current.status, current.error_code = "UNKNOWN", "external_session_unknown"
        session.add(current)
        session.commit()
    return current


def authoritative(sync: ExternalSync, *, terminal: bool = False) -> None:
    client = AgentComposeClient()
    client.project_id = sync.agent_project_id
    try:
        run = client.get_run(sync.agent_run_id)
        if (
            run is None
            or run.session_id != sync.session_id
            or not sync.session_id
            or run.project_id != sync.agent_project_id
            or run.agent_name != "cloudatlas-sync"
        ):
            raise SyncError("external_session_unknown", unknown=True)
        observation = client.get_session(sync.session_id)
    except AgentComposeBoundaryError:
        raise SyncError("external_session_unknown", unknown=True) from None
    expected = (
        AgentComposeSessionObservation.TERMINAL
        if terminal
        else AgentComposeSessionObservation.RUNNING
    )
    if observation is None or observation.observation != expected:
        raise SyncError("external_session_unknown", unknown=True)


def execution_source(
    session: Session, sync: ExternalSync, *, terminal: bool = False
) -> SourceInstance:
    actor = session.get(User, sync.actor_id)
    if actor is None:
        raise SyncError("external_permission_revoked")
    try:
        project = get_authorized_project(
            session=session,
            user=actor,
            project_id=sync.project_id,
            allowed_roles=(ProjectRole.OPERATOR,),
            writable=True,
        )
        source = source_for(session, project, sync.source_id, lock=True)
    except HTTPException:
        raise SyncError("external_permission_revoked") from None
    if sync.retain_until <= get_datetime_utc():
        raise SyncError("external_retention_expired")
    fingerprint, token_hash = ready(source)
    if fingerprint != sync.fingerprint or token_hash != sync.token_sha256:
        raise SyncError("external_material_changed")
    authoritative(sync, terminal=terminal)
    return source


def finish_task(session: Session, sync: ExternalSync) -> None:
    versions = session.exec(
        select(ExternalAssetVersion).where(ExternalAssetVersion.sync_id == sync.id)
    ).all()
    states = {v.status for v in versions}
    if states & {"PENDING", "RUNNING", "UNKNOWN"}:
        sync.status = "UNKNOWN" if "UNKNOWN" in states else "RUNNING"
    else:
        sync.status = (
            "SUCCEEDED"
            if states == {"PUBLISHED"}
            else "PARTIAL_FAILED"
            if "PUBLISHED" in states
            else "FAILED"
        )
        sync.completed_at = get_datetime_utc()
    session.add(sync)


def publish(
    session: Session,
    sync: ExternalSync,
    version: ExternalAssetVersion,
    *,
    terminal: bool = False,
) -> None:
    source = execution_source(session, sync, terminal=terminal)
    count = session.exec(
        select(func.count())
        .select_from(ExternalAssetRecord)
        .where(ExternalAssetRecord.version_id == version.id)
    ).one()
    if (
        not version.complete
        or version.expected_total != count
        or version.record_count != count
    ):
        raise SyncError("external_incomplete_stage")
    version.status, version.published_at, version.error_code = (
        "PUBLISHED",
        get_datetime_utc(),
        None,
    )
    session.add(version)
    head = session.get(ExternalAssetHead, (source.id, version.domain))
    if head is None:
        head = ExternalAssetHead(
            source_id=source.id, domain=version.domain, version_id=version.id
        )
    else:
        head.version_id = version.id
    session.add(head)
    audit(
        session,
        source,
        sync.actor_id,
        "external_domain.published",
        version.id,
        {"domain": version.domain, "record_count": count},
    )
    session.flush()


def validate_page(
    page: dict[str, Any],
    *,
    number: int,
    size: int,
    total: int | None,
    seen: set[str],
    remaining: int,
) -> tuple[int, list[tuple[str, str, str, dict[str, Any]]]]:
    if (
        any(type(page.get(name)) is not int for name in ("page", "size", "total"))
        or page["page"] != number
        or page["size"] != size
        or page["total"] < 0
    ):
        raise SyncError("external_page_invalid")
    if total is not None and page["total"] != total:
        raise SyncError("external_total_changed")
    total = page["total"]
    items = page.get("items")
    if (
        not isinstance(items, list)
        or len(items) > size
        or len(items) > remaining
        or len(seen) + len(items) > total
    ):
        raise SyncError("external_page_invalid")
    if not items and len(seen) < total:
        raise SyncError("external_early_empty_page")
    rows = []
    for item in items:
        if not isinstance(item, dict):
            raise SyncError("external_record_invalid")
        source_id, ip = item.get("id"), item.get("ip")
        if (
            not isinstance(source_id, str)
            or len(source_id) > 100
            or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", source_id)
            or not isinstance(ip, str)
            or "%" in ip
        ):
            raise SyncError("external_record_invalid")
        if source_id in seen:
            raise SyncError("external_duplicate_id")
        try:
            canonical = str(ipaddress.ip_address(ip))
        except ValueError:
            raise SyncError("external_record_invalid") from None
        seen.add(source_id)
        rows.append((source_id, ip, canonical, item))
    return total, rows


def execute_sync(
    session: Session, sync_id: uuid.UUID, run_id: str, session_id: str
) -> None:
    sync: ExternalSync | None = session.exec(
        select(ExternalSync).where(ExternalSync.id == sync_id).with_for_update()
    ).one()
    assert sync is not None
    if (
        sync.agent_run_id != run_id
        or not session_id
        or (sync.session_id is not None and sync.session_id != session_id)
    ):
        raise SyncError("external_session_mismatch", unknown=True)
    if sync.status not in UNFINISHED or sync.started_at is not None:
        return  # A restarted command must never issue a second source traversal.
    sync.session_id = session_id
    sync.started_at, sync.status, sync.error_code = get_datetime_utc(), "RUNNING", None
    session.add(sync)
    session.commit()
    version_ids = list(
        session.exec(
            select(ExternalAssetVersion.id)
            .where(ExternalAssetVersion.sync_id == sync.id)
            .order_by(ExternalAssetVersion.domain)
        ).all()
    )
    deadline = sync.started_at + timedelta(seconds=sync.request["timeout_seconds"])
    halted: SyncError | None = None
    for version_id in version_ids:
        try:
            session.expire_all()
            sync = session.get(ExternalSync, sync_id)
            version = session.get(ExternalAssetVersion, version_id)
            assert sync is not None and version is not None
            if halted is not None:
                raise halted
            source = execution_source(session, sync)
            version.status = "RUNNING"
            version.fetched_at = get_datetime_utc()
            session.add(version)
            session.commit()
            seen: set[str] = set()
            total: int | None = None
            number = 1
            while True:
                session.expire_all()
                sync = session.get(ExternalSync, sync_id)
                version = session.get(ExternalAssetVersion, version_id)
                assert sync is not None and version is not None
                source = execution_source(session, sync)
                remaining_seconds = (deadline - get_datetime_utc()).total_seconds()
                if remaining_seconds <= 0:
                    raise SyncError("external_timeout", unknown=True)
                if sync.pages_read >= sync.request["max_pages"]:
                    raise SyncError("external_page_budget")
                if (
                    sync.records_read + sync.request["page_size"]
                    > sync.request["max_records"]
                ):
                    raise SyncError("external_record_budget")
                sync.pages_read += 1
                session.add(sync)
                session.commit()  # Count attempted calls durably; never retry them.
                page = OctobusCloudAtlasAssetsClient().list_page(
                    source,
                    capset_token=settings.CLOUDATLAS_ASSETS_CAPSET_TOKEN.get_secret_value(),
                    domain=version.domain,
                    page=number,
                    size=sync.request["page_size"],
                    max_response_bytes=sync.request["max_response_bytes"],
                    timeout_seconds=max(1, min(300, math.ceil(remaining_seconds))),
                )
                session.expire_all()
                sync = session.get(ExternalSync, sync_id)
                version = session.get(ExternalAssetVersion, version_id)
                assert sync is not None and version is not None
                execution_source(session, sync)
                if get_datetime_utc() >= deadline:
                    raise SyncError("external_timeout", unknown=True)
                if page.get("space_id") != source.space_id:
                    raise SyncError("external_space_mismatch")
                total, rows = validate_page(
                    page,
                    number=number,
                    size=sync.request["page_size"],
                    total=total,
                    seen=seen,
                    remaining=sync.request["max_records"] - sync.records_read,
                )
                if (
                    total
                    > sync.request["max_records"]
                    - sync.records_read
                    + version.record_count
                ):
                    raise SyncError("external_record_budget")
                for upstream_id, ip, canonical, fields in rows:
                    session.add(
                        ExternalAssetRecord(
                            version_id=version.id,
                            source_id=upstream_id,
                            ip=ip,
                            canonical_ip=canonical,
                            fields=fields,
                        )
                    )
                sync.records_read += len(rows)
                version.record_count += len(rows)
                version.expected_total = total
                version.complete = len(seen) == total
                session.add(sync)
                session.add(version)
                session.commit()
                if version.complete:
                    publish(session, sync, version)
                    session.commit()
                    break
                number += 1
        except (SyncError, CloudAtlasBoundaryError) as error:
            session.rollback()
            sync = session.get(ExternalSync, sync_id)
            version = session.get(ExternalAssetVersion, version_id)
            assert sync is not None and version is not None
            code = error.code
            unknown = (
                isinstance(error, SyncError) and error.unknown
            ) or code == "cloudatlas_connectivity_failed"
            version.status = "UNKNOWN" if unknown else "FAILED"
            version.error_code = code
            sync.error_code = code
            session.add(version)
            session.add(sync)
            session.commit()
            halted = SyncError(code, unknown=unknown)
    sync = session.get(ExternalSync, sync_id)
    assert sync is not None
    finish_task(session, sync)
    session.commit()


def reconcile(session: Session, sync: ExternalSync) -> ExternalSync:
    if sync.status not in UNFINISHED:
        return sync
    client = AgentComposeClient()
    client.project_id = sync.agent_project_id
    try:
        run = client.get_run(sync.agent_run_id)
        if (
            run is not None
            and sync.session_id is None
            and run.project_id == sync.agent_project_id
            and run.agent_name == "cloudatlas-sync"
        ):
            sync.session_id = run.session_id
        authoritative(sync, terminal=True)
    except AgentComposeBoundaryError, SyncError:
        sync.status, sync.error_code = "UNKNOWN", "external_session_unknown"
        session.add(sync)
        session.commit()
        return sync
    versions = session.exec(
        select(ExternalAssetVersion)
        .where(ExternalAssetVersion.sync_id == sync.id)
        .order_by(ExternalAssetVersion.domain)
    ).all()
    for version in versions:
        if version.status == "PUBLISHED" or version.status == "FAILED":
            continue
        try:
            if not version.complete:
                raise SyncError("external_execution_interrupted")
            publish(session, sync, version, terminal=True)
        except SyncError as error:
            version.status = "UNKNOWN" if error.unknown else "FAILED"
            version.error_code = error.code
            sync.error_code = error.code
            session.add(version)
    finish_task(session, sync)
    session.commit()
    return sync


def purge_expired(session: Session, source: SourceInstance, actor: User | None) -> int:
    if source.capability_profile != "assets-v1":
        deny("external_source_not_found", 404)
    expired = select(ExternalAssetVersion.id).where(
        ExternalAssetVersion.source_id == source.id,
        ExternalAssetVersion.retain_until <= get_datetime_utc(),
    )
    result = session.exec(
        delete(ExternalAssetRecord).where(
            col(ExternalAssetRecord.version_id).in_(expired)
        )
    )
    count = result.rowcount
    if actor is not None:
        audit(
            session,
            source,
            actor.id,
            "external_records.purged",
            source.id,
            {"deleted_records": count},
        )
    else:
        session.add(
            AuditEvent(
                tenant_id=source.tenant_id,
                project_id=source.project_id,
                actor_subject="system:external-retention",
                actor_type="system",
                action="external_records.purged",
                target_type="external_assets",
                target_id=source.id,
                after_data={"deleted_records": count},
            )
        )
    session.commit()
    return count
