"""Native published source rows and local revisions; never calls an external tool."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from app.domain import customer_ledger
from app.domain.customer_ledger import Text
from app.domain.governance_publication import published_run_predicate
from app.domain.ip_consistency import normalize_ip
from app.domain.ip_source_comparison import (
    IPSourceComparison,
    IPSourceComparisonError,
    _published_comparison_context,
    read_published_netflow_activities,
)
from app.domain.models import (
    AuditEvent,
    CloudAtlasLedgerRevision,
    GovernanceRun,
    Observation,
    Project,
    RunStep,
    SourceInstance,
    SourceSnapshot,
)

ScopeState = Literal["UNKNOWN", "SEPARATE", "CONFIRMED_LEGACY"]
Tag = Annotated[Text, Field(min_length=1, max_length=64)]


class CloudLedgerError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status


class CloudLedgerEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: uuid.UUID
    expected_revision: int = Field(ge=0)
    kind: Literal["management", "scope"]
    observation_id: uuid.UUID | None = None
    tags: list[Tag] = Field(default_factory=list, max_length=20)
    followed: bool = False
    scope_state: ScopeState | None = None
    reason: Text = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def check_kind(self) -> CloudLedgerEdit:
        if not self.reason.strip():
            raise ValueError("reason_required")
        if self.kind == "management":
            if self.observation_id is None or self.scope_state is not None:
                raise ValueError("management_scope_invalid")
        elif (
            self.observation_id is not None
            or self.tags
            or self.followed
            or self.scope_state is None
        ):
            raise ValueError("scope_confirmation_invalid")
        return self


class CloudRevisionPublic(BaseModel):
    id: uuid.UUID
    source_snapshot_id: uuid.UUID
    revision: int
    kind: str
    observation_id: uuid.UUID | None
    tags: list[str]
    followed: bool
    scope_state: ScopeState | None
    reason: str
    created_by: uuid.UUID
    created_at: datetime


class CloudLedgerEntry(BaseModel):
    observation_id: uuid.UUID
    source_record_key: str
    asset_id: str
    raw_ip: str
    canonical_ip: str
    source_status: str
    tags: list[str] = Field(default_factory=list)
    followed: bool = False
    management_revision: int = 0


class CloudSnapshotPublic(BaseModel):
    id: uuid.UUID
    source_instance_id: uuid.UUID
    governance_run_id: uuid.UUID
    created_at: datetime
    record_count: int
    content_sha256: str


class CloudLedgerPage(BaseModel):
    project_id: uuid.UUID
    source_instance_id: uuid.UUID | None = None
    snapshot_id: uuid.UUID | None = None
    governance_run_id: uuid.UUID | None = None
    source_created_at: datetime | None = None
    content_sha256: str | None = None
    state: str
    latest_attempt_state: str = "NOT_READ"
    latest_attempt_at: datetime | None = None
    latest_attempt_run_id: uuid.UUID | None = None
    revision: int = 0
    current_revision: int = 0
    scope_state: ScopeState = "UNKNOWN"
    scope_revision: int = 0
    current_scope_revision: int = 0
    association: str = "UNKNOWN"
    count: int | None = None
    total_records: int | None = None
    unique_ips: int | None = None
    status_filter: Literal["valid"] = "valid"
    risk_state: Literal["NOT_CONNECTED"] = "NOT_CONNECTED"
    data: list[CloudLedgerEntry] = Field(default_factory=list)
    can_manage: bool = False
    can_confirm_scope: bool = False


class CloudIPProfile(BaseModel):
    project_id: uuid.UUID
    canonical_ip: str
    governance_run_id: uuid.UUID | None
    association: str
    resource_id: uuid.UUID | None = None
    comparison: IPSourceComparison | None = None
    netflow_state: str = "ASSOCIATION_UNAVAILABLE"
    customer: customer_ledger.LedgerPage
    cloud: CloudLedgerPage
    risk_state: Literal["NOT_CONNECTED"] = "NOT_CONNECTED"


def public_revision(row: CloudAtlasLedgerRevision) -> CloudRevisionPublic:
    return CloudRevisionPublic.model_validate(row, from_attributes=True)


def _snapshot(
    session: Session, project: Project, snapshot_id: uuid.UUID
) -> SourceSnapshot:
    row = session.exec(
        select(SourceSnapshot).where(
            SourceSnapshot.id == snapshot_id,
            SourceSnapshot.project_id == project.id,
            SourceSnapshot.tenant_id == project.tenant_id,
            SourceSnapshot.source_type == "CLOUDATLAS",
        )
    ).one_or_none()
    if row is None:
        raise CloudLedgerError("cloud_ledger_snapshot_not_found", 404)
    return row


def _scope(
    session: Session, project: Project, snapshot: SourceSnapshot
) -> GovernanceRun:
    try:
        run, _, _ = _published_comparison_context(
            session=session, project=project, run_id=snapshot.governance_run_id
        )
    except IPSourceComparisonError as error:
        raise CloudLedgerError(
            "cloud_ledger_" + error.code,
            404 if error.code in {"run_not_found", "run_not_published"} else 500,
        ) from None
    steps = {
        s.step_code: s
        for s in session.exec(
            select(RunStep).where(
                RunStep.governance_run_id == run.id,
                RunStep.project_id == project.id,
                RunStep.tenant_id == project.tenant_id,
            )
        ).all()
    }
    method_hash = hashlib.sha256(
        json.dumps(
            {
                "method": run.cloudatlas_method,
                "package_sha256": run.package_sha256,
                "descriptor_sha256": run.descriptor_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    if (
        snapshot.source_instance_id != run.source_instance_id
        or snapshot.schema_fingerprint != run.descriptor_sha256
        or snapshot.method_fingerprint != method_hash
        or any(
            name not in steps or steps[name].status != "SUCCEEDED"
            for name in ("PULL_CLOUDATLAS", "NORMALIZE", "PUBLISH")
        )
        or steps["PULL_CLOUDATLAS"].output_hash != snapshot.content_sha256
    ):
        raise CloudLedgerError("cloud_ledger_snapshot_invalid", 500)
    return run


def _revisions(
    session: Session, project: Project, snapshot_id: uuid.UUID
) -> list[CloudAtlasLedgerRevision]:
    # ponytail: scan local revisions per snapshot; move to indexed per-row queries if edit history becomes large.
    return list(
        session.exec(
            select(CloudAtlasLedgerRevision)
            .where(
                CloudAtlasLedgerRevision.project_id == project.id,
                CloudAtlasLedgerRevision.tenant_id == project.tenant_id,
                CloudAtlasLedgerRevision.source_snapshot_id == snapshot_id,
            )
            .order_by(col(CloudAtlasLedgerRevision.revision))
        ).all()
    )


def snapshots(
    session: Session, project: Project, source_id: uuid.UUID, skip: int, limit: int
) -> list[CloudSnapshotPublic]:
    source = session.exec(
        select(SourceInstance).where(
            SourceInstance.id == source_id,
            SourceInstance.project_id == project.id,
            SourceInstance.tenant_id == project.tenant_id,
            SourceInstance.capability_profile == "legacy-ip-v1",
        )
    ).one_or_none()
    if source is None:
        raise CloudLedgerError("cloud_ledger_source_not_found", 404)
    rows = session.exec(
        select(SourceSnapshot)
        .join(GovernanceRun, col(GovernanceRun.id) == SourceSnapshot.governance_run_id)
        .where(
            SourceSnapshot.source_instance_id == source_id,
            SourceSnapshot.project_id == project.id,
            SourceSnapshot.tenant_id == project.tenant_id,
            SourceSnapshot.source_type == "CLOUDATLAS",
            published_run_predicate(),
        )
        .order_by(col(GovernanceRun.completed_at).desc(), col(SourceSnapshot.id).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return [CloudSnapshotPublic.model_validate(r, from_attributes=True) for r in rows]


def read_page(
    session: Session,
    project: Project,
    *,
    source_id: uuid.UUID | None = None,
    snapshot_id: uuid.UUID | None = None,
    revision: int | None = None,
    ip: str | None = None,
    asset_id: str | None = None,
    skip: int = 0,
    limit: int = 25,
) -> CloudLedgerPage:
    snapshot = _snapshot(session, project, snapshot_id) if snapshot_id else None
    if snapshot:
        if source_id is not None and source_id != snapshot.source_instance_id:
            raise CloudLedgerError("cloud_ledger_source_mismatch", 404)
        source_id = snapshot.source_instance_id
    source_query = select(SourceInstance).where(
        SourceInstance.project_id == project.id,
        SourceInstance.tenant_id == project.tenant_id,
        SourceInstance.capability_profile == "legacy-ip-v1",
    )
    source = session.exec(
        source_query.where(SourceInstance.id == source_id)
        if source_id
        else source_query.where(SourceInstance.enabled)
    ).one_or_none()
    page = CloudLedgerPage(project_id=project.id, state="NO_SOURCE")
    if source is None:
        if source_id or snapshot_id or revision:
            raise CloudLedgerError("cloud_ledger_source_not_found", 404)
        return page
    page.source_instance_id = source.id
    page.state = "NOT_READ"
    latest = session.exec(
        select(GovernanceRun)
        .where(
            GovernanceRun.project_id == project.id,
            GovernanceRun.tenant_id == project.tenant_id,
            GovernanceRun.source_instance_id == source.id,
        )
        .order_by(col(GovernanceRun.created_at).desc(), col(GovernanceRun.id).desc())
        .limit(1)
    ).first()
    if latest:
        step = session.exec(
            select(RunStep).where(
                RunStep.governance_run_id == latest.id,
                RunStep.step_code == "PULL_CLOUDATLAS",
            )
        ).one_or_none()
        page.latest_attempt_at, page.latest_attempt_run_id = (
            latest.created_at,
            latest.id,
        )
        page.latest_attempt_state = (
            "NOT_READ"
            if step is None
            else {
                "RUNNING": "READING",
                "FAILED": "READ_FAILED",
                "SUCCEEDED": "READ_UNPUBLISHED",
            }[step.status]
        )
        if latest.completed_at is not None and latest.status in {
            "COMPLETED",
            "COMPLETED_WITH_WARNINGS",
        }:
            page.latest_attempt_state = "PUBLISHED"
        if (
            step is not None
            and step.status == "SUCCEEDED"
            and latest.status in {"FAILED_DATA", "FAILED_PROCESSING"}
        ):
            page.latest_attempt_state = "DOWNSTREAM_FAILED"
        page.state = page.latest_attempt_state
    if snapshot is None:
        candidates = snapshots(session, project, source.id, 0, 1)
        if not candidates:
            if revision is not None:
                raise CloudLedgerError("cloud_ledger_snapshot_not_found", 404)
            return page
        snapshot = _snapshot(session, project, candidates[0].id)
    _scope(session, project, snapshot)
    rows_query = select(Observation).where(
        Observation.project_id == project.id,
        Observation.tenant_id == project.tenant_id,
        Observation.governance_run_id == snapshot.governance_run_id,
        Observation.source_snapshot_id == snapshot.id,
        Observation.source_type == "CLOUDATLAS",
    )
    # Native count is independent of comparison selection or report evidence bounds.
    native = rows_query.subquery()
    total, unique = session.exec(
        select(
            func.count(), func.count(func.distinct(native.c.canonical_ip))
        ).select_from(native)
    ).one()
    if total != snapshot.record_count:
        raise CloudLedgerError("cloud_ledger_record_count_mismatch", 500)
    events = _revisions(session, project, snapshot.id)
    current = events[-1].revision if events else 0
    selected = current if revision is None else revision
    if (
        selected < 0
        or selected > current
        or selected
        and not any(r.revision == selected for r in events)
    ):
        raise CloudLedgerError("cloud_ledger_revision_not_found", 404)
    selected_events = [r for r in events if r.revision <= selected]
    selected_scope = next(
        (r for r in reversed(selected_events) if r.kind == "scope"), None
    )
    current_scope = next((r for r in reversed(events) if r.kind == "scope"), None)
    page.scope_state = (
        cast(ScopeState, selected_scope.scope_state) if selected_scope else "UNKNOWN"
    )
    page.scope_revision = selected_scope.revision if selected_scope else 0
    page.current_scope_revision = current_scope.revision if current_scope else 0
    page.association = page.scope_state
    if (
        page.scope_state == "CONFIRMED_LEGACY"
        and page.scope_revision != page.current_scope_revision
    ):
        page.association = "REVOKED"
    managed = {r.observation_id: r for r in selected_events if r.kind == "management"}
    if ip is not None:
        rows_query = rows_query.where(Observation.canonical_ip == normalize_ip(ip))
    if asset_id is not None:
        rows_query = rows_query.where(Observation.cloudatlas_asset_id == asset_id)
    count = session.exec(select(func.count()).select_from(rows_query.subquery())).one()
    rows = session.exec(
        rows_query.order_by(col(Observation.source_record_key), col(Observation.id))
        .offset(skip)
        .limit(limit)
    ).all()
    page.data = [
        CloudLedgerEntry(
            observation_id=r.id,
            source_record_key=r.source_record_key,
            asset_id=r.cloudatlas_asset_id or "",
            raw_ip=r.raw_ip,
            canonical_ip=str(r.canonical_ip),
            source_status=r.cloudatlas_status or "",
            tags=managed[r.id].tags if r.id in managed else [],
            followed=managed[r.id].followed if r.id in managed else False,
            management_revision=managed[r.id].revision if r.id in managed else 0,
        )
        for r in rows
    ]
    page.snapshot_id, page.governance_run_id = snapshot.id, snapshot.governance_run_id
    page.source_created_at, page.content_sha256 = (
        snapshot.created_at,
        snapshot.content_sha256,
    )
    page.revision, page.current_revision = selected, current
    page.total_records, page.unique_ips, page.count = total, unique, count
    page.state = "EMPTY" if total == 0 else "PRESENT"
    return page


def recover(
    session: Session, project: Project, actor_id: uuid.UUID, key: str
) -> CloudAtlasLedgerRevision | None:
    return session.exec(
        select(CloudAtlasLedgerRevision).where(
            CloudAtlasLedgerRevision.project_id == project.id,
            CloudAtlasLedgerRevision.tenant_id == project.tenant_id,
            CloudAtlasLedgerRevision.created_by == actor_id,
            CloudAtlasLedgerRevision.operation_key == key,
        )
    ).one_or_none()


def save(
    session: Session,
    project: Project,
    *,
    actor_id: uuid.UUID,
    key: str,
    edit: CloudLedgerEdit,
    ip_address: str | None,
) -> CloudAtlasLedgerRevision:
    digest = hashlib.sha256(
        json.dumps(
            edit.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    existing = recover(session, project, actor_id, key)
    if existing:
        if existing.request_sha256 != digest:
            raise CloudLedgerError("cloud_ledger_key_conflict")
        return existing
    page = read_page(session, project, snapshot_id=edit.snapshot_id)
    if page.current_revision != edit.expected_revision:
        raise CloudLedgerError("cloud_ledger_version_conflict")
    if edit.observation_id:
        row = session.exec(
            select(Observation).where(
                Observation.id == edit.observation_id,
                Observation.source_snapshot_id == edit.snapshot_id,
                Observation.source_type == "CLOUDATLAS",
                Observation.project_id == project.id,
                Observation.tenant_id == project.tenant_id,
            )
        ).one_or_none()
        if row is None:
            raise CloudLedgerError("cloud_ledger_entry_not_found", 404)
    assert page.governance_run_id is not None
    record = CloudAtlasLedgerRevision(
        tenant_id=project.tenant_id,
        project_id=project.id,
        governance_run_id=page.governance_run_id,
        source_snapshot_id=edit.snapshot_id,
        observation_id=edit.observation_id,
        revision=page.current_revision + 1,
        kind=edit.kind,
        tags=list(edit.tags),
        followed=edit.followed,
        scope_state=edit.scope_state,
        created_by=actor_id,
        operation_key=key,
        request_sha256=digest,
        reason=edit.reason,
    )
    try:
        session.add(record)
        session.add(
            AuditEvent(
                tenant_id=project.tenant_id,
                project_id=project.id,
                actor_subject=str(actor_id),
                actor_type="user",
                action="cloudatlas_ledger." + edit.kind,
                target_type="cloudatlas_ledger_revision",
                target_id=record.id,
                before_data={"revision": edit.expected_revision},
                after_data={
                    "snapshot_id": str(edit.snapshot_id),
                    "revision": record.revision,
                    "kind": edit.kind,
                },
                ip_address=ip_address,
            )
        )
        session.commit()
        session.refresh(record)
    except SQLAlchemyError:
        session.rollback()
        raise CloudLedgerError("cloud_ledger_save_failed", 500) from None
    return record


def profile(
    session: Session,
    project: Project,
    *,
    ip: str,
    snapshot_id: uuid.UUID,
    revision: int | None,
    upload_id: uuid.UUID | None,
    customer_revision_id: uuid.UUID | None,
    customer_original: bool,
    customer_skip: int,
    cloud_skip: int,
    limit: int,
) -> CloudIPProfile:
    canonical = normalize_ip(ip)
    cloud = read_page(
        session,
        project,
        snapshot_id=snapshot_id,
        revision=revision,
        ip=canonical,
        skip=cloud_skip,
        limit=limit,
    )
    snapshot = _snapshot(session, project, snapshot_id)
    run = session.get(GovernanceRun, snapshot.governance_run_id)
    assert run is not None
    if upload_id is None and customer_revision_id is None:
        upload_id = run.customer_upload_id
        customer_original = True
    if upload_id is not None and customer_revision_id is not None:
        if (
            customer_ledger._revision(session, project, customer_revision_id).upload_id
            != upload_id
        ):
            raise CloudLedgerError("cloud_ledger_customer_revision_mismatch", 404)
    customer = customer_ledger.read_page(
        session,
        project,
        upload_id=upload_id,
        revision_id=customer_revision_id,
        original=customer_original,
        query="",
        ip=canonical,
        archived=False,
        skip=customer_skip,
        limit=limit,
        can_write=False,
    )
    result = CloudIPProfile(
        project_id=project.id,
        canonical_ip=canonical,
        governance_run_id=cloud.governance_run_id,
        association=cloud.association,
        customer=customer,
        cloud=cloud,
    )
    if cloud.association == "CONFIRMED_LEGACY":
        assert cloud.governance_run_id is not None
        _, _, facts = _published_comparison_context(
            session=session, project=project, run_id=cloud.governance_run_id
        )
        match = next((r for r in facts.results if r.canonical_ip == canonical), None)
        result.netflow_state, _ = read_published_netflow_activities(
            session=session, run=run
        )
        if match:
            result.resource_id, result.comparison = match.resource_id, match
    return result
