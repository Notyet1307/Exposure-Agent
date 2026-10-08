"""C/A publications reuse fixed SourceCorrelation inputs; auxiliary reads stay separate."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from app.api.project_authorization import project_access_filter
from app.core.time import get_datetime_utc
from app.domain import source_correlations as correlations
from app.domain.comparison_models import CoreComparisonResult, CoreComparisonSupplement
from app.domain.external_asset_models import ExternalAssetVersion
from app.domain.models import (
    AuditEvent,
    CustomerLedgerRevision,
    CustomerUpload,
    Project,
    ProjectRole,
    SourceInstance,
)
from app.domain.netflow_common import (
    deny,
    operation_result,
    record_operation,
    request_hash,
)
from app.domain.netflow_models import SourceCorrelationRevision
from app.domain.netflow_processing import analysis_material
from app.models import User

CONTRACT_VERSION: Literal["core-comparison-v2"] = "core-comparison-v2"
CORE_SOURCES: tuple[correlations.Source, ...] = ("CUSTOMER", "CLOUD")
RULE_VERSION = "canonical-ip-presence-v1"
Classification = Literal["all", "both", "cloud_only", "customer_only"]


class Envelope(BaseModel):
    contract_version: Literal["core-comparison-v2"] = CONTRACT_VERSION
    project_id: uuid.UUID


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfirmScope(Input):
    network_namespace: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    customer_upload_id: uuid.UUID
    customer_revision_id: uuid.UUID | None = None
    source_instance_id: uuid.UUID
    ip_version_id: uuid.UUID | None = None
    port_version_id: uuid.UUID | None = None
    evidence: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def nonempty(self) -> ConfirmScope:
        if (
            not (self.ip_version_id or self.port_version_id)
            or not self.evidence.strip()
        ):
            raise ValueError("comparison_scope_invalid")
        return self


class CreateResult(Input):
    selection: correlations.Selection
    scope_confirmation_id: uuid.UUID | None = None
    scope_evidence: str | None = Field(default=None, max_length=2048)
    purpose: Literal["regular", "custom"] = "regular"
    expected_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_current_result_id: uuid.UUID | None = None


class ResultPublic(Envelope):
    id: uuid.UUID
    scope_key: str
    scope_confirmation_id: uuid.UUID
    purpose: Literal["regular", "custom"]
    rule_version: str
    status: Literal["PUBLISHED"] = "PUBLISHED"
    published_at: datetime
    created_at: datetime
    customer_applied_at: datetime | None
    customer_filename: str
    source_name: str
    selection: correlations.Selection
    pins: dict[str, Any]
    input_sha256: str


class ConfirmationPublic(Envelope):
    id: uuid.UUID
    scope_key: str
    selection: correlations.Selection
    input_sha256: str


class ScopeChoice(BaseModel):
    scope_key: str
    network_namespace: str
    source_instance_id: uuid.UUID
    source_name: str
    space_id: str


class CloudChoice(BaseModel):
    source_instance_id: uuid.UUID
    source_name: str
    space_id: str
    state: Literal["PUBLISHED", "EXPIRED", "NOT_PUBLISHED"]
    selection: correlations.ExternalSelection | None


ReadinessState = Literal[
    "READY",
    "SCOPE_REQUIRED",
    "SCOPE_CONFIRMATION_REQUIRED",
    "CUSTOMER_NOT_READY",
    "CLOUD_NOT_READY",
    "INSUFFICIENT_COVERAGE",
    "EXPIRED",
    "ACCESS_DENIED",
    "READ_FAILED",
    "MULTIPLE_SCOPES",
    "METADATA_UNAVAILABLE",
]


class Readiness(Envelope):
    state: ReadinessState
    reason_code: str | None = None
    scope_key: str | None = None
    scope_confirmation_id: uuid.UUID | None = None
    selection: correlations.Selection | None = None
    input_sha256: str | None = None
    expected_current_result_id: uuid.UUID | None = None
    customer: correlations.CustomerSelection | None = None
    customer_filename: str | None = None
    customer_applied_at: datetime | None = None
    clouds: list[CloudChoice] = Field(default_factory=list)
    scope_choices: list[ScopeChoice] = Field(default_factory=list)
    can_generate: bool = False
    can_write: bool = False
    can_confirm_scope: bool = False
    sources: list[correlations.SourceState] = Field(default_factory=list)


class AttemptPublic(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime
    error_code: str | None


class CurrentResult(Envelope):
    state: Literal["AVAILABLE", "NO_RESULT", "MULTIPLE_SCOPES"]
    result: ResultPublic | None = None
    readiness: Readiness
    scope_choices: list[ScopeChoice] = Field(default_factory=list)
    latest_attempt: AttemptPublic | None = None


class ComparisonOperationPublic(Envelope):
    status: Literal["PUBLISHED", "FAILED"]
    result: ResultPublic | None = None
    error_code: str | None = None


class ResultSummary(ResultPublic):
    total_addresses: int
    comparison_state: str
    both: int | None
    cloud_only: int | None
    customer_only: int | None
    sources: list[correlations.SourceState]


class Address(BaseModel):
    address_key: str
    canonical_ip: str
    classification: Literal["both", "cloud_only", "customer_only"] | None
    customer_records: int
    cloud_records: int
    presence: dict[str, str]


class AddressPage(Envelope):
    result_id: uuid.UUID
    data: list[Address]
    count: int
    skip: int
    limit: int
    total_addresses: int


class ComparisonAddressDetail(Envelope):
    result_id: uuid.UUID
    address: Address


class EvidencePage(Envelope):
    result_id: uuid.UUID
    address_key: str
    source: Literal["customer", "cloud"]
    data: list[correlations.EvidenceRecord]
    count: int
    skip: int
    limit: int


class ResultHistory(Envelope):
    data: list[ResultPublic]
    count: int
    skip: int
    limit: int


class Updates(Envelope):
    result_id: uuid.UUID
    state: Literal["UNCHANGED", "UPDATED", "UNAVAILABLE"]
    reason_code: str | None
    latest_result_id: uuid.UUID | None
    readiness: Readiness
    latest_attempt: AttemptPublic | None


def _code(error: HTTPException) -> str:
    return (
        str(error.detail.get("code", "comparison_read_failed"))
        if isinstance(error.detail, dict)
        else "comparison_read_failed"
    )


def _known_unreadable(error: HTTPException) -> bool:
    return (error.status_code, _code(error)) in {
        (403, "correlation_source_access_revoked"),
        (410, "correlation_source_expired"),
        (409, "correlation_scope_unconfirmed"),
    }


def _selection(value: correlations.Selection) -> correlations.ExternalSelection:
    if (
        value.customer is None
        or not isinstance(value.cloud, correlations.ExternalSelection)
        or value.netflow is not None
        or value.history_run_id is not None
    ):
        deny("comparison_requires_customer_and_cloud", 422)
    return value.cloud


def _scope_key(selection: correlations.Selection, pins: dict[str, Any]) -> str:
    cloud = _selection(selection)
    domains = pins["CLOUD"]["domains"]
    # IP/port are the two possible domains of the same source. A newly published
    # optional domain changes the inputs, not this stable comparison scope.
    return request_hash(
        {
            "namespace": selection.network_namespace,
            "source": str(cloud.source_instance_id),
            "space": pins["CLOUD"]["space_id"],
            "filters": {
                name: domains.get(name, {}).get("filter", {}) for name in ("ip", "port")
            },
        }
    )


def _input_hash(selection: correlations.Selection, pins: dict[str, Any]) -> str:
    return request_hash({"selection": selection.model_dump(mode="json"), "pins": pins})


def _confirmation(
    session: Session, project: Project, identity: uuid.UUID
) -> tuple[SourceCorrelationRevision, dict[correlations.Source, correlations.Material]]:
    row = correlations.revision_for(session, project, identity)
    _selection(correlations.Selection.model_validate(row.selection))
    if row.scope_state != "CONFIRMED":
        deny("comparison_scope_confirmation_required")
    _current, loaded = correlations.read_material(session, project, row)
    return row, loaded


def _result(
    session: Session, project: Project, identity: uuid.UUID
) -> CoreComparisonResult:
    row = session.get(CoreComparisonResult, identity)
    if (
        row is None
        or row.project_id != project.id
        or row.tenant_id != project.tenant_id
    ):
        deny("comparison_result_not_found", 404)
    return row


def _read(
    session: Session, project: Project, row: CoreComparisonResult
) -> tuple[SourceCorrelationRevision, dict[correlations.Source, correlations.Material]]:
    if row.status != "PUBLISHED" or row.published_at is None:
        deny("comparison_result_not_published", 409)
    confirmation, loaded = _confirmation(session, project, row.scope_confirmation_id)
    selection = correlations.Selection.model_validate(row.selection)
    if (
        row.rule_version != RULE_VERSION
        or row.selection != confirmation.selection
        or row.pins != confirmation.pins
        or row.input_sha256 != _input_hash(selection, row.pins)
        or row.scope_key != _scope_key(selection, row.pins)
    ):
        deny("netflow_artifact_integrity_failed")
    return confirmation, loaded


def _public(
    session: Session, project: Project, row: CoreComparisonResult
) -> ResultPublic:
    _read(session, project, row)
    selection = correlations.Selection.model_validate(row.selection)
    assert selection.customer is not None and row.published_at is not None
    upload = session.get(CustomerUpload, selection.customer.upload_id)
    if upload is None:
        deny("netflow_input_not_found", 404)
    domains = row.pins["CLOUD"]["domains"]
    source_name = next(iter(domains.values()))["instance_id"]
    return ResultPublic(
        project_id=project.id,
        id=row.id,
        scope_key=row.scope_key,
        scope_confirmation_id=row.scope_confirmation_id,
        purpose=cast(Literal["regular", "custom"], row.purpose),
        rule_version=row.rule_version,
        published_at=row.published_at,
        created_at=row.created_at,
        customer_applied_at=row.customer_applied_at,
        customer_filename=upload.display_filename,
        source_name=source_name,
        selection=selection,
        pins=row.pins,
        input_sha256=row.input_sha256,
    )


def _readable_results(
    session: Session,
    project: Project,
    scope_key: str | None = None,
    *,
    regular: bool = True,
) -> list[CoreComparisonResult]:
    query = select(CoreComparisonResult).where(
        CoreComparisonResult.project_id == project.id,
        CoreComparisonResult.tenant_id == project.tenant_id,
        CoreComparisonResult.status == "PUBLISHED",
    )
    if scope_key is not None:
        query = query.where(CoreComparisonResult.scope_key == scope_key)
    if regular:
        query = query.where(CoreComparisonResult.purpose == "regular")
    rows = session.exec(
        query.order_by(
            col(CoreComparisonResult.published_at).desc(),
            col(CoreComparisonResult.id).desc(),
        ).execution_options(yield_per=100)
    )
    result = []
    for row in rows:
        try:
            _read(session, project, row)
        except HTTPException as error:
            if _known_unreadable(error):
                continue
            raise
        result.append(row)
    return result


def _scope_choice(row: CoreComparisonResult) -> ScopeChoice:
    cloud = cast(dict[str, Any], row.selection["cloud"])
    domains = row.pins["CLOUD"]["domains"]
    return ScopeChoice(
        scope_key=row.scope_key,
        network_namespace=row.selection["network_namespace"],
        source_instance_id=cloud["source_instance_id"],
        source_name=next(iter(domains.values()))["instance_id"],
        space_id=row.pins["CLOUD"]["space_id"],
    )


def _latest_attempt(
    session: Session, project: Project, scope_key: str | None
) -> AttemptPublic | None:
    if scope_key is None:
        return None
    row = session.exec(
        select(CoreComparisonResult)
        .where(
            CoreComparisonResult.project_id == project.id,
            CoreComparisonResult.tenant_id == project.tenant_id,
            CoreComparisonResult.scope_key == scope_key,
            CoreComparisonResult.purpose == "regular",
        )
        .order_by(
            col(CoreComparisonResult.created_at).desc(),
            col(CoreComparisonResult.id).desc(),
        )
    ).first()
    return (
        AttemptPublic(
            id=row.id,
            status=row.status,
            created_at=row.created_at,
            error_code=row.error_code,
        )
        if row
        else None
    )


def _applied_at(session: Session, project: Project) -> datetime | None:
    if project.current_customer_ledger_revision_id:
        revision = session.get(
            CustomerLedgerRevision, project.current_customer_ledger_revision_id
        )
        return revision.created_at if revision else None
    event = session.exec(
        select(AuditEvent)
        .where(
            AuditEvent.project_id == project.id,
            AuditEvent.tenant_id == project.tenant_id,
            col(AuditEvent.action).in_(
                ["customer_upload.replaced", "customer_upload.selected"]
            ),
        )
        .order_by(col(AuditEvent.created_at).desc(), col(AuditEvent.id).desc())
    ).first()
    return event.created_at if event else None


def _cloud_choices(
    session: Session,
    project: Project,
    source_id: uuid.UUID | None = None,
    expected_pins: dict[str, Any] | None = None,
) -> list[CloudChoice]:
    query = select(SourceInstance).where(
        SourceInstance.project_id == project.id,
        SourceInstance.tenant_id == project.tenant_id,
        SourceInstance.capability_profile == "assets-v1",
    )
    if source_id is not None:
        query = query.where(SourceInstance.id == source_id)
    rows = session.exec(
        query.order_by(col(SourceInstance.created_at).desc(), col(SourceInstance.id))
    ).all()
    if source_id is not None and not rows:
        deny("netflow_input_not_found", 404)
    choices = []
    for source in rows:
        if not source.data_access_enabled:
            if source_id is not None:
                deny("correlation_source_access_revoked", 403)
            continue
        versions: dict[str, uuid.UUID] = {}
        expired = False
        for domain in ("ip", "port"):
            candidates = session.exec(
                select(ExternalAssetVersion)
                .where(
                    ExternalAssetVersion.source_id == source.id,
                    ExternalAssetVersion.domain == domain,
                    ExternalAssetVersion.status == "PUBLISHED",
                )
                .order_by(
                    col(ExternalAssetVersion.published_at).desc(),
                    col(ExternalAssetVersion.id).desc(),
                )
            ).all()
            for version in candidates:
                if expected_pins is not None:
                    original = expected_pins["CLOUD"]["domains"].get(domain, {})
                    if version.space_id != expected_pins["CLOUD"][
                        "space_id"
                    ] or version.filter != original.get("filter", {}):
                        continue
                if version.retain_until <= get_datetime_utc():
                    expired = True
                    continue
                versions[domain] = version.id
                break
        selection = (
            correlations.ExternalSelection(
                kind="external_versions",
                source_instance_id=source.id,
                ip_version_id=versions.get("ip"),
                port_version_id=versions.get("port"),
            )
            if versions
            else None
        )
        choices.append(
            CloudChoice(
                source_instance_id=source.id,
                source_name=source.instance_id,
                space_id=source.space_id or "",
                state="PUBLISHED"
                if versions
                else "EXPIRED"
                if expired
                else "NOT_PUBLISHED",
                selection=selection,
            )
        )
    return choices


def _find_confirmation(
    session: Session,
    project: Project,
    selection: correlations.Selection,
    pins: dict[str, Any],
) -> SourceCorrelationRevision | None:
    rows = session.exec(
        select(SourceCorrelationRevision)
        .where(
            SourceCorrelationRevision.project_id == project.id,
            SourceCorrelationRevision.tenant_id == project.tenant_id,
            SourceCorrelationRevision.network_namespace == selection.network_namespace,
            SourceCorrelationRevision.scope_state == "CONFIRMED",
        )
        .order_by(
            col(SourceCorrelationRevision.created_at).desc(),
            col(SourceCorrelationRevision.id).desc(),
        )
    )
    for row in rows:
        if row.selection != selection.model_dump(mode="json") or row.pins != pins:
            continue
        try:
            _confirmation(session, project, row.id)
        except HTTPException as error:
            if _known_unreadable(error):
                continue
            raise
        return row
    return None


def _can_write(session: Session, project: Project, actor: User) -> bool:
    return (
        project.archived_at is None
        and session.exec(
            select(Project.id).where(
                Project.id == project.id,
                project_access_filter(
                    user=actor, allowed_roles=(ProjectRole.OPERATOR,)
                ),
            )
        ).first()
        is not None
    )


def _ready_error(error: HTTPException) -> ReadinessState:
    if error.status_code == 410:
        return "EXPIRED"
    if error.status_code == 403:
        return "ACCESS_DENIED"
    return "READ_FAILED"


def readiness(
    session: Session,
    project: Project,
    actor: User,
    *,
    source_instance_id: uuid.UUID | None = None,
    network_namespace: str | None = None,
    base: CoreComparisonResult | None = None,
) -> Readiness:
    can_write = _can_write(session, project, actor)
    value = Readiness(
        project_id=project.id,
        state="SCOPE_REQUIRED",
        can_write=can_write,
        can_confirm_scope=can_write and actor.is_superuser,
    )
    expected_pins = None
    if base is not None:
        selected = correlations.Selection.model_validate(base.selection)
        cloud = _selection(selected)
        if (
            source_instance_id is not None
            and source_instance_id != cloud.source_instance_id
        ) or (
            network_namespace is not None
            and network_namespace != selected.network_namespace
        ):
            deny("comparison_scope_conflict", 422)
        source_instance_id = cloud.source_instance_id
        network_namespace = selected.network_namespace
        expected_pins = base.pins
        value.scope_key = base.scope_key
        latest = _readable_results(session, project, base.scope_key)
        value.expected_current_result_id = latest[0].id if latest else None
    if project.current_customer_upload_id is None:
        value.state = "CUSTOMER_NOT_READY"
        value.reason_code = "comparison_customer_not_applied"
    else:
        value.customer = correlations.CustomerSelection(
            upload_id=project.current_customer_upload_id,
            revision_id=project.current_customer_ledger_revision_id,
        )
        upload = session.get(CustomerUpload, project.current_customer_upload_id)
        if (
            upload is None
            or upload.project_id != project.id
            or upload.tenant_id != project.tenant_id
        ):
            deny("netflow_artifact_integrity_failed")
        value.customer_filename = upload.display_filename
        value.customer_applied_at = _applied_at(session, project)
    try:
        value.clouds = _cloud_choices(
            session, project, source_instance_id, expected_pins
        )
    except HTTPException as error:
        value.state, value.reason_code = _ready_error(error), _code(error)
        return value
    if value.customer is None:
        return value
    if len(value.clouds) > 1 and source_instance_id is None:
        value.state = "MULTIPLE_SCOPES"
        value.reason_code = "comparison_cloud_source_required"
        return value
    chosen = value.clouds[0] if value.clouds else None
    if chosen is None or chosen.selection is None:
        value.state = (
            "EXPIRED" if chosen and chosen.state == "EXPIRED" else "CLOUD_NOT_READY"
        )
        value.reason_code = "comparison_no_readable_cloud_version"
        return value
    # An existing exact, currently valid two-source confirmation may supply the
    # namespace. Same project/source/IP alone never supplies that declaration.
    if network_namespace is None:
        namespaces = set()
        proofs = session.exec(
            select(SourceCorrelationRevision).where(
                SourceCorrelationRevision.project_id == project.id,
                SourceCorrelationRevision.tenant_id == project.tenant_id,
                SourceCorrelationRevision.scope_state == "CONFIRMED",
            )
        )
        for proof in proofs:
            if (
                proof.selection.get("customer")
                != value.customer.model_dump(mode="json")
                or proof.selection.get("cloud")
                != chosen.selection.model_dump(mode="json")
                or proof.selection.get("netflow") is not None
            ):
                continue
            try:
                _confirmation(session, project, proof.id)
            except HTTPException as error:
                if _known_unreadable(error):
                    continue
                raise
            namespaces.add(proof.network_namespace)
        if len(namespaces) != 1:
            value.state = "SCOPE_REQUIRED"
            return value
        network_namespace = next(iter(namespaces))
    selected = correlations.Selection(
        network_namespace=network_namespace,
        customer=value.customer,
        cloud=chosen.selection,
    )
    value.selection = selected
    try:
        loaded = correlations.materials(session, project, selected, write=True)
    except HTTPException as error:
        value.state, value.reason_code = _ready_error(error), _code(error)
        return value
    pins: dict[str, Any] = {
        source: material.pins for source, material in loaded.items()
    }
    value.input_sha256 = _input_hash(selected, pins)
    value.scope_key = _scope_key(selected, pins)
    value.sources = [loaded[source].state for source in CORE_SOURCES]
    matched_proof = _find_confirmation(session, project, selected, pins)
    value.scope_confirmation_id = matched_proof.id if matched_proof else None
    latest = _readable_results(session, project, value.scope_key)
    value.expected_current_result_id = latest[0].id if latest else None
    if matched_proof is None:
        value.state = "SCOPE_CONFIRMATION_REQUIRED"
    elif loaded["CLOUD"].state.coverage_state != "SUFFICIENT":
        value.state = "INSUFFICIENT_COVERAGE"
    else:
        value.state = "READY"
    value.can_generate = can_write and (matched_proof is not None or actor.is_superuser)
    return value


def _ready_safely(
    session: Session,
    project: Project,
    actor: User,
    base: CoreComparisonResult | None,
    source_instance_id: uuid.UUID | None = None,
    network_namespace: str | None = None,
) -> Readiness:
    try:
        return readiness(
            session,
            project,
            actor,
            base=base,
            source_instance_id=source_instance_id,
            network_namespace=network_namespace,
        )
    except HTTPException as error:
        # A failed update-status read is not a failure of already validated R_k.
        return Readiness(
            project_id=project.id,
            state="METADATA_UNAVAILABLE",
            reason_code=_code(error),
            scope_key=base.scope_key if base else None,
        )


def current(
    session: Session, project: Project, actor: User, scope_key: str | None = None
) -> CurrentResult:
    readable = _readable_results(session, project, scope_key)
    by_scope: dict[str, CoreComparisonResult] = {}
    for row in readable:
        by_scope.setdefault(row.scope_key, row)
    choices = [_scope_choice(row) for row in by_scope.values()]
    if len(by_scope) > 1:
        return CurrentResult(
            project_id=project.id,
            state="MULTIPLE_SCOPES",
            readiness=Readiness(
                project_id=project.id, state="MULTIPLE_SCOPES", scope_choices=choices
            ),
            scope_choices=choices,
        )
    selected = next(iter(by_scope.values()), None)
    ready = _ready_safely(session, project, actor, selected)
    ready.scope_choices = choices
    return CurrentResult(
        project_id=project.id,
        state="AVAILABLE" if selected else "NO_RESULT",
        result=_public(session, project, selected) if selected else None,
        readiness=ready,
        scope_choices=choices,
        latest_attempt=_latest_attempt(
            session, project, selected.scope_key if selected else scope_key
        ),
    )


def _new_confirmation(
    session: Session,
    project: Project,
    actor: User,
    selection: correlations.Selection,
    pins: dict[str, Any],
    evidence: str,
) -> SourceCorrelationRevision:
    if not actor.is_superuser or not evidence.strip():
        deny("comparison_scope_confirmation_required", 403)
    identity = uuid.uuid4()
    row = SourceCorrelationRevision(
        id=identity,
        root_id=identity,
        tenant_id=project.tenant_id,
        project_id=project.id,
        revision=1,
        network_namespace=selection.network_namespace,
        scope_state="CONFIRMED",
        selection=selection.model_dump(mode="json"),
        pins=pins,
        evidence=evidence.strip(),
        created_by=actor.id,
    )
    session.add(row)
    session.flush()
    return row


def confirm_scope(
    session: Session, project: Project, actor: User, body: ConfirmScope, key: str
) -> ConfirmationPublic:
    request = body.model_dump(mode="json")
    previous = operation_result(
        session, project, actor.id, "comparison:confirm", key, request
    )
    if previous:
        row, _loaded = _confirmation(session, project, previous)
        selected = correlations.Selection.model_validate(row.selection)
    else:
        selected = correlations.Selection(
            network_namespace=body.network_namespace,
            customer=correlations.CustomerSelection(
                upload_id=body.customer_upload_id, revision_id=body.customer_revision_id
            ),
            cloud=correlations.ExternalSelection(
                kind="external_versions",
                source_instance_id=body.source_instance_id,
                ip_version_id=body.ip_version_id,
                port_version_id=body.port_version_id,
            ),
        )
        loaded = correlations.materials(session, project, selected, write=True)
        row = _new_confirmation(
            session,
            project,
            actor,
            selected,
            {source: material.pins for source, material in loaded.items()},
            body.evidence,
        )
        record_operation(
            session, project, actor.id, "comparison:confirm", key, request, row.id
        )
        session.commit()
    return ConfirmationPublic(
        project_id=project.id,
        id=row.id,
        scope_key=_scope_key(selected, row.pins),
        selection=selected,
        input_sha256=_input_hash(selected, row.pins),
    )


def _publish_attempt(
    session: Session,
    project: Project,
    actor: User,
    proof: SourceCorrelationRevision,
    body: CreateResult,
    key: str,
    *,
    error_code: str | None = None,
) -> CoreComparisonResult:
    selection = correlations.Selection.model_validate(proof.selection)
    row = CoreComparisonResult(
        tenant_id=project.tenant_id,
        project_id=project.id,
        scope_key=_scope_key(selection, proof.pins),
        scope_confirmation_id=proof.id,
        purpose=body.purpose,
        rule_version=RULE_VERSION,
        status="FAILED" if error_code else "PUBLISHED",
        error_code=error_code,
        published_at=None if error_code else get_datetime_utc(),
        selection=proof.selection,
        pins=proof.pins,
        input_sha256=_input_hash(selection, proof.pins),
        customer_applied_at=_applied_at(session, project)
        if body.purpose == "regular"
        else None,
        created_by=actor.id,
    )
    session.add(row)
    record_operation(
        session,
        project,
        actor.id,
        "comparison:create",
        key,
        body.model_dump(mode="json"),
        row.id,
    )
    session.add(
        AuditEvent(
            tenant_id=project.tenant_id,
            project_id=project.id,
            actor_subject=str(actor.id),
            actor_type="user",
            action="comparison_result.failed"
            if error_code
            else "comparison_result.published",
            target_type="core_comparison_result",
            target_id=row.id,
            after_data={
                "scope_key": row.scope_key,
                "purpose": row.purpose,
                "error_code": error_code,
            },
        )
    )
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        # A transport failure can follow a successful commit. The original key
        # is authoritative; never create another result to recover that reply.
        recovered = operation_result(
            session,
            project,
            actor.id,
            "comparison:create",
            key,
            body.model_dump(mode="json"),
        )
        if recovered is None:
            deny("comparison_commit_unknown", 503)
        row = _result(session, project, recovered)
    return row


def create(
    session: Session, project: Project, actor: User, body: CreateResult, key: str
) -> ResultPublic:
    previous = operation_result(
        session,
        project,
        actor.id,
        "comparison:create",
        key,
        body.model_dump(mode="json"),
    )
    if previous:
        row = _result(session, project, previous)
        if row.status == "FAILED":
            deny(row.error_code or "comparison_update_failed")
        return _public(session, project, row)
    cloud = _selection(body.selection)
    loaded = correlations.materials(session, project, body.selection, write=True)
    pins: dict[str, Any] = {
        source: material.pins for source, material in loaded.items()
    }
    if body.expected_input_sha256 != _input_hash(body.selection, pins):
        deny("comparison_input_conflict")
    if body.scope_confirmation_id is not None:
        proof, _fixed = _confirmation(session, project, body.scope_confirmation_id)
        if (
            proof.selection != body.selection.model_dump(mode="json")
            or proof.pins != pins
        ):
            deny("comparison_scope_confirmation_required")
    else:
        proof = _new_confirmation(
            session, project, actor, body.selection, pins, body.scope_evidence or ""
        )
    if body.purpose == "regular":
        heads = _readable_results(session, project, _scope_key(body.selection, pins))
        actual = readiness(
            session,
            project,
            actor,
            source_instance_id=cloud.source_instance_id,
            network_namespace=body.selection.network_namespace,
            base=heads[0] if heads else None,
        )
        error = None
        if (
            actual.input_sha256 != body.expected_input_sha256
            or actual.selection != body.selection
        ):
            error = "comparison_input_conflict"
        elif actual.expected_current_result_id != body.expected_current_result_id:
            error = "comparison_publish_conflict"
        if error:
            _publish_attempt(
                session, project, actor, proof, body, key, error_code=error
            )
            deny(error)
    return _public(
        session, project, _publish_attempt(session, project, actor, proof, body, key)
    )


def operation(
    session: Session, project: Project, actor: User, key: str
) -> ComparisonOperationPublic:
    identity = operation_result(session, project, actor.id, "comparison:create", key)
    if identity is None:
        deny("comparison_operation_not_found", 404)
    row = _result(session, project, identity)
    return ComparisonOperationPublic(
        project_id=project.id,
        status=cast(Literal["PUBLISHED", "FAILED"], row.status),
        result=_public(session, project, row) if row.status == "PUBLISHED" else None,
        error_code=row.error_code,
    )


def _addresses(
    session: Session, project: Project, row: CoreComparisonResult
) -> tuple[
    dict[correlations.Source, correlations.Material],
    list[correlations.AddressPublic],
    correlations.ComparisonOverview,
]:
    proof, loaded = _read(session, project, row)
    rows = correlations.addresses(session, project, proof, loaded)
    return loaded, rows, correlations.comparison_overview(proof, loaded, rows)


def _address(value: correlations.AddressPublic, available: bool) -> Address:
    sources = value.positive_sources
    classification: Literal["both", "cloud_only", "customer_only"] | None = None
    if available:
        classification = (
            "both"
            if sources == ["CUSTOMER", "CLOUD"]
            else "customer_only"
            if "CUSTOMER" in sources
            else "cloud_only"
        )
    return Address(
        address_key=value.address_key,
        canonical_ip=value.canonical_ip,
        classification=classification,
        customer_records=value.source_counts["CUSTOMER"] or 0,
        cloud_records=value.source_counts["CLOUD"] or 0,
        presence={source: value.presence[source] for source in CORE_SOURCES},
    )


def summary(session: Session, project: Project, identity: uuid.UUID) -> ResultSummary:
    row = _result(session, project, identity)
    loaded, values, comparison = _addresses(session, project, row)
    available = comparison.state == "AVAILABLE"
    return ResultSummary(
        **_public(session, project, row).model_dump(),
        total_addresses=len(values),
        comparison_state=comparison.state,
        both=sum(value.positive_sources == ["CUSTOMER", "CLOUD"] for value in values)
        if available
        else None,
        cloud_only=sum(value.positive_sources == ["CLOUD"] for value in values)
        if available
        else None,
        customer_only=sum(value.positive_sources == ["CUSTOMER"] for value in values)
        if available
        else None,
        sources=[loaded[source].state for source in CORE_SOURCES],
    )


def addresses(
    session: Session,
    project: Project,
    identity: uuid.UUID,
    classification: Classification,
    ip: str | None,
    skip: int,
    limit: int,
    sort: str = "ip_asc",
) -> AddressPage:
    row = _result(session, project, identity)
    _loaded, values, comparison = _addresses(session, project, row)
    available = comparison.state == "AVAILABLE"
    if classification != "all" and not available:
        deny("comparison_coverage_insufficient", 422)
    canonical = correlations.canonical(ip) if ip is not None else None
    entries = [_address(value, available) for value in values]
    selected = [
        value
        for value in entries
        if (classification == "all" or value.classification == classification)
        and (canonical is None or canonical == value.canonical_ip)
    ]
    if sort == "ip_desc":
        selected.reverse()
    return AddressPage(
        project_id=project.id,
        result_id=row.id,
        data=selected[skip : skip + limit],
        count=len(selected),
        skip=skip,
        limit=limit,
        total_addresses=len(values),
    )


def address_detail(
    session: Session, project: Project, identity: uuid.UUID, address_key: str
) -> ComparisonAddressDetail:
    row = _result(session, project, identity)
    _loaded, values, comparison = _addresses(session, project, row)
    value = next((entry for entry in values if entry.address_key == address_key), None)
    if value is None:
        deny("comparison_address_not_found", 404)
    return ComparisonAddressDetail(
        project_id=project.id,
        result_id=row.id,
        address=_address(value, comparison.state == "AVAILABLE"),
    )


def evidence(
    session: Session,
    project: Project,
    identity: uuid.UUID,
    address_key: str,
    source: Literal["customer", "cloud"],
    skip: int,
    limit: int,
) -> EvidencePage:
    row = _result(session, project, identity)
    loaded, rows, _comparison = _addresses(session, project, row)
    address = next((value for value in rows if value.address_key == address_key), None)
    if address is None:
        deny("comparison_address_not_found", 404)
    records = [
        value
        for value in loaded["CUSTOMER" if source == "customer" else "CLOUD"].records
        if value.canonical_ip == address.canonical_ip
    ]
    return EvidencePage(
        project_id=project.id,
        result_id=row.id,
        address_key=address_key,
        source=source,
        data=records[skip : skip + limit],
        count=len(records),
        skip=skip,
        limit=limit,
    )


def history(
    session: Session, project: Project, scope_key: str | None, skip: int, limit: int
) -> ResultHistory:
    values = _readable_results(session, project, scope_key, regular=False)
    return ResultHistory(
        project_id=project.id,
        data=[_public(session, project, row) for row in values[skip : skip + limit]],
        count=len(values),
        skip=skip,
        limit=limit,
    )


def updates(
    session: Session, project: Project, actor: User, identity: uuid.UUID
) -> Updates:
    row = _result(session, project, identity)
    _read(session, project, row)
    ready = _ready_safely(session, project, actor, row)
    state: Literal["UNCHANGED", "UPDATED", "UNAVAILABLE"] = (
        "UNAVAILABLE"
        if ready.input_sha256 is None
        else "UNCHANGED"
        if ready.input_sha256 == row.input_sha256
        else "UPDATED"
    )
    return Updates(
        project_id=project.id,
        result_id=row.id,
        state=state,
        reason_code=ready.reason_code,
        latest_result_id=ready.expected_current_result_id,
        readiness=ready,
        latest_attempt=_latest_attempt(session, project, row.scope_key),
    )


class SupplementCreate(Input):
    analysis_id: uuid.UUID | None = None
    expected_binding_id: uuid.UUID | None = None
    qualification_confirmation_id: uuid.UUID | None = None
    scope_evidence: str | None = Field(default=None, max_length=2048)
    valid_until: AwareDatetime | None = None


class SupplementPublic(Envelope):
    result_id: uuid.UUID
    id: uuid.UUID | None
    parent_id: uuid.UUID | None = None
    revision: int | None = None
    state: Literal["NOT_PROVIDED", "ACTIVE", "REMOVED", "EXPIRED", "UNREADABLE"]
    reason_code: str | None = None
    analysis_id: uuid.UUID | None = None
    dataset_id: uuid.UUID | None = None
    created_at: datetime | None = None
    valid_until: datetime | None = None
    observation_window: dict[str, str] | None = None
    source_records: int | None = None
    observation_count: int | None = None
    total_addresses: int | None = None


class SupplementAddress(BaseModel):
    canonical_ip: str
    in_core: bool
    observation_count: int
    source_records: int


class SupplementAddresses(Envelope):
    result_id: uuid.UUID
    binding_id: uuid.UUID
    analysis_id: uuid.UUID
    data: list[SupplementAddress]
    count: int
    skip: int
    limit: int


class SupplementHistory(Envelope):
    result_id: uuid.UUID
    data: list[SupplementPublic]
    count: int
    skip: int
    limit: int


def _binding(
    session: Session,
    project: Project,
    result: CoreComparisonResult,
    binding_id: uuid.UUID | None = None,
) -> CoreComparisonSupplement | None:
    query = select(CoreComparisonSupplement).where(
        CoreComparisonSupplement.result_id == result.id,
        CoreComparisonSupplement.project_id == project.id,
        CoreComparisonSupplement.tenant_id == project.tenant_id,
    )
    if binding_id is not None:
        row = session.exec(
            query.where(CoreComparisonSupplement.id == binding_id)
        ).one_or_none()
        if row is None:
            deny("comparison_supplement_not_found", 404)
        return row
    return session.exec(
        query.order_by(col(CoreComparisonSupplement.revision).desc())
    ).first()


def _qualify_supplement(
    session: Session,
    project: Project,
    result: CoreComparisonResult,
    qualification_id: uuid.UUID,
    analysis_id: uuid.UUID,
) -> None:
    confirmation = correlations.revision_for(session, project, qualification_id)
    if confirmation.scope_state != "CONFIRMED":
        deny("comparison_supplement_scope_unconfirmed")
    correlations.read_material(session, project, confirmation)
    chosen = correlations.Selection.model_validate(confirmation.selection)
    core = correlations.Selection.model_validate(result.selection)
    if (
        chosen.customer != core.customer
        or chosen.cloud != core.cloud
        or chosen.network_namespace != core.network_namespace
        or chosen.netflow is None
        or chosen.netflow.analysis_id != analysis_id
        or confirmation.pins["CUSTOMER"] != result.pins["CUSTOMER"]
        or confirmation.pins["CLOUD"] != result.pins["CLOUD"]
    ):
        deny("comparison_supplement_scope_unconfirmed")


def _binding_material(
    session: Session,
    project: Project,
    result: CoreComparisonResult,
    binding: CoreComparisonSupplement,
) -> tuple[Any, Any]:
    # This gate is deliberately before any Analysis/Artifact read.
    if binding.analysis_id is None:
        deny("comparison_supplement_removed", 409)
    if binding.valid_until is None or binding.valid_until <= get_datetime_utc():
        deny("comparison_supplement_expired", 410)
    analysis, bundle = analysis_material(session, project, binding.analysis_id)
    if analysis.network_namespace != result.selection["network_namespace"]:
        deny("comparison_supplement_scope_unconfirmed")
    if binding.qualification_confirmation_id:
        _qualify_supplement(
            session, project, result, binding.qualification_confirmation_id, analysis.id
        )
    return analysis, bundle


def _supplement_public(
    session: Session,
    project: Project,
    result: CoreComparisonResult,
    row: CoreComparisonSupplement | None,
) -> SupplementPublic:
    if row is None:
        return SupplementPublic(
            project_id=project.id, result_id=result.id, id=None, state="NOT_PROVIDED"
        )
    public = SupplementPublic(
        project_id=project.id,
        result_id=result.id,
        id=row.id,
        parent_id=row.parent_id,
        revision=row.revision,
        state="REMOVED" if row.analysis_id is None else "ACTIVE",
        created_at=row.created_at,
        valid_until=row.valid_until,
    )
    if row.analysis_id is None:
        return public
    if row.valid_until is None or row.valid_until <= get_datetime_utc():
        public.state = "EXPIRED"
        public.reason_code = "comparison_supplement_expired"
        return public
    try:
        analysis, bundle = _binding_material(session, project, result, row)
    except HTTPException as error:
        public.state = "UNREADABLE"
        public.reason_code = _code(error)
        return public
    public.analysis_id, public.dataset_id = analysis.id, analysis.dataset_id
    public.observation_window = row.observation_window
    public.observation_count = len(bundle.observations)
    public.source_records = sum(
        int(value["features"]["record_count"]) for value in bundle.observations
    )
    public.total_addresses = len(
        {correlations.canonical(str(value["ip"])) for value in bundle.observations}
    )
    return public


def supplement(
    session: Session,
    project: Project,
    result_id: uuid.UUID,
    binding_id: uuid.UUID | None = None,
) -> SupplementPublic:
    result = _result(session, project, result_id)
    _read(session, project, result)
    return _supplement_public(
        session, project, result, _binding(session, project, result, binding_id)
    )


def bind(
    session: Session,
    project: Project,
    actor: User,
    result_id: uuid.UUID,
    body: SupplementCreate,
    key: str,
) -> SupplementPublic:
    result = _result(session, project, result_id)
    _read(session, project, result)
    request = {"result_id": str(result_id), **body.model_dump(mode="json")}
    operation_name = f"comparison:supplement:{result_id}"
    previous = operation_result(
        session, project, actor.id, operation_name, key, request
    )
    if previous:
        return _supplement_public(
            session, project, result, _binding(session, project, result, previous)
        )
    parent = _binding(session, project, result)
    if body.expected_binding_id != (parent.id if parent else None):
        deny("comparison_supplement_conflict")
    evidence_text = (body.scope_evidence or "").strip()
    if body.analysis_id is None:
        if (
            body.valid_until is not None
            or body.qualification_confirmation_id is not None
            or evidence_text
        ):
            deny("comparison_supplement_invalid", 422)
    else:
        if body.valid_until is None or body.valid_until <= get_datetime_utc():
            deny("comparison_supplement_valid_until_required", 422)
        analysis, _bundle = analysis_material(session, project, body.analysis_id)
        if analysis.network_namespace != result.selection["network_namespace"]:
            deny("comparison_supplement_scope_unconfirmed")
        if body.qualification_confirmation_id:
            _qualify_supplement(
                session,
                project,
                result,
                body.qualification_confirmation_id,
                analysis.id,
            )
        elif not (actor.is_superuser and evidence_text):
            deny("comparison_supplement_scope_unconfirmed", 403)
    row = CoreComparisonSupplement(
        tenant_id=project.tenant_id,
        project_id=project.id,
        result_id=result.id,
        parent_id=parent.id if parent else None,
        revision=parent.revision + 1 if parent else 1,
        analysis_id=body.analysis_id,
        qualification_confirmation_id=body.qualification_confirmation_id,
        qualification_evidence=evidence_text or None,
        valid_until=body.valid_until,
        observation_window={
            "state": "NOT_PROVIDED",
            "reason": "analysis_has_no_verified_observation_window",
        }
        if body.analysis_id
        else {},
        created_by=actor.id,
    )
    session.add(row)
    record_operation(session, project, actor.id, operation_name, key, request, row.id)
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        recovered = operation_result(
            session, project, actor.id, operation_name, key, request
        )
        if recovered is None:
            deny("comparison_commit_unknown", 503)
        row = cast(
            CoreComparisonSupplement, _binding(session, project, result, recovered)
        )
    return _supplement_public(session, project, result, row)


def supplement_operation(
    session: Session, project: Project, actor: User, result_id: uuid.UUID, key: str
) -> SupplementPublic:
    result = _result(session, project, result_id)
    _read(session, project, result)
    previous = operation_result(
        session, project, actor.id, f"comparison:supplement:{result_id}", key
    )
    if previous is None:
        deny("comparison_operation_not_found", 404)
    return _supplement_public(
        session, project, result, _binding(session, project, result, previous)
    )


def supplement_addresses(
    session: Session,
    project: Project,
    result_id: uuid.UUID,
    binding_id: uuid.UUID,
    *,
    only_supplemental: bool,
    ips: list[str] | None,
    skip: int,
    limit: int,
) -> SupplementAddresses:
    result = _result(session, project, result_id)
    _proof, loaded = _read(session, project, result)
    binding = _binding(session, project, result, binding_id)
    assert binding is not None
    analysis, bundle = _binding_material(session, project, result, binding)
    core = {
        record.canonical_ip
        for source in CORE_SOURCES
        for record in loaded[source].records
    }
    groups: dict[str, SupplementAddress] = {}
    for observation in bundle.observations:
        ip = correlations.canonical(str(observation["ip"]))
        entry = groups.setdefault(
            ip,
            SupplementAddress(
                canonical_ip=ip,
                in_core=ip in core,
                observation_count=0,
                source_records=0,
            ),
        )
        entry.observation_count += 1
        entry.source_records += int(observation["features"]["record_count"])
    selected_ips = (
        {correlations.canonical(ip) for ip in ips} if ips is not None else None
    )
    import ipaddress

    values = sorted(
        (
            entry
            for entry in groups.values()
            if (not only_supplemental or not entry.in_core)
            and (selected_ips is None or entry.canonical_ip in selected_ips)
        ),
        key=lambda entry: (
            ipaddress.ip_address(entry.canonical_ip).version,
            int(ipaddress.ip_address(entry.canonical_ip)),
        ),
    )
    return SupplementAddresses(
        project_id=project.id,
        result_id=result.id,
        binding_id=binding.id,
        analysis_id=analysis.id,
        data=values[skip : skip + limit],
        count=len(values),
        skip=skip,
        limit=limit,
    )


def supplement_history(
    session: Session, project: Project, result_id: uuid.UUID, skip: int, limit: int
) -> SupplementHistory:
    result = _result(session, project, result_id)
    _read(session, project, result)
    rows = session.exec(
        select(CoreComparisonSupplement)
        .where(
            CoreComparisonSupplement.result_id == result.id,
            CoreComparisonSupplement.project_id == project.id,
            CoreComparisonSupplement.tenant_id == project.tenant_id,
        )
        .order_by(col(CoreComparisonSupplement.revision).desc())
    ).all()
    return SupplementHistory(
        project_id=project.id,
        result_id=result.id,
        data=[
            _supplement_public(session, project, result, row)
            for row in rows[skip : skip + limit]
        ],
        count=len(rows),
        skip=skip,
        limit=limit,
    )
