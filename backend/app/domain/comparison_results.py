"""V2 two-source comparison reads; NetFlow is deliberately absent here."""

from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlmodel import Session, col, select

from app.core.time import get_datetime_utc
from app.domain import source_correlations as correlations
from app.domain.comparison_models import CoreComparisonResult, CoreComparisonSupplement
from app.domain.external_asset_models import ExternalAssetHead, ExternalAssetVersion
from app.domain.models import AuditEvent, Project, SourceInstance
from app.domain.netflow_common import (
    deny,
    operation_result,
    record_operation,
    request_hash,
)
from app.domain.netflow_models import SourceCorrelationRevision
from app.domain.netflow_processing import analysis_material
from app.models import User

CONTRACT_VERSION = "core-comparison-v2"


class ConfirmScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    network_namespace: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    customer_upload_id: uuid.UUID
    customer_revision_id: uuid.UUID | None = None
    source_instance_id: uuid.UUID
    ip_version_id: uuid.UUID | None = None
    port_version_id: uuid.UUID | None = None
    evidence: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def versions_and_evidence(self) -> ConfirmScope:
        if (self.ip_version_id is None and self.port_version_id is None) or not self.evidence.strip():
            raise ValueError("scope_confirmation_invalid")
        return self


class CreateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_confirmation_id: uuid.UUID
    purpose: Literal["regular", "custom"] = "regular"
    expected_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_current_result_id: uuid.UUID | None = None


class ResultPublic(BaseModel):
    contract_version: Literal["core-comparison-v2"] = CONTRACT_VERSION
    project_id: uuid.UUID
    id: uuid.UUID
    scope_key: str
    scope_confirmation_id: uuid.UUID
    purpose: Literal["regular", "custom", "confirmation"]
    status: str
    published_at: datetime | None
    created_at: datetime
    selection: dict[str, Any]
    pins: dict[str, Any]
    input_sha256: str


class ScopeDomain(BaseModel):
    domain: Literal["ip", "port"]
    space_id: str
    filter: dict[str, str]


class ScopeChoice(BaseModel):
    scope_key: str
    scope_confirmation_id: uuid.UUID
    network_namespace: str
    source_instance_id: uuid.UUID
    domains: list[ScopeDomain]
    selection: dict[str, Any]
    input_sha256: str


ReadinessState = Literal["READY", "NO_RESULT", "SCOPE_CONFIRMATION_REQUIRED", "CUSTOMER_NOT_READY", "CLOUD_NOT_READY", "INPUTS_INSUFFICIENT", "METADATA_UNAVAILABLE", "MULTIPLE_SCOPES", "UNKNOWN"]


class Readiness(BaseModel):
    state: ReadinessState
    reason_code: str | None = None
    scope_key: str | None = None
    scope_confirmation_id: uuid.UUID | None = None
    selection: dict[str, Any] | None = None
    input_sha256: str | None = None
    expected_current_result_id: uuid.UUID | None = None
    scope_choices: list[ScopeChoice] = Field(default_factory=list)


class CurrentResult(BaseModel):
    contract_version: Literal["core-comparison-v2"] = CONTRACT_VERSION
    project_id: uuid.UUID
    state: Literal["AVAILABLE", "NO_RESULT", "SCOPE_CONFIRMATION_REQUIRED", "CUSTOMER_NOT_READY", "CLOUD_NOT_READY", "INPUTS_INSUFFICIENT", "METADATA_UNAVAILABLE", "MULTIPLE_SCOPES", "UNKNOWN"]
    result: ResultPublic | None = None
    readiness: Readiness


class ResultSummary(ResultPublic):
    total_addresses: int | None
    both: int | None
    cloud_only: int | None
    customer_only: int | None
    source_states: dict[correlations.Source, correlations.SourceState]


class Address(BaseModel):
    address_key: str
    canonical_ip: str
    classification: Literal["both", "cloud_only", "customer_only"]
    customer_records: int
    cloud_records: int


class AddressPage(BaseModel):
    result_id: uuid.UUID
    data: list[Address]
    count: int
    skip: int
    limit: int
    total_addresses: int


class SupplementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_id: uuid.UUID | None = None
    expected_binding_id: uuid.UUID | None = None
    qualification_confirmation_id: uuid.UUID | None = None
    scope_evidence: str | None = Field(default=None, max_length=2048)
    valid_until: datetime | None = None


class SupplementPublic(BaseModel):
    id: uuid.UUID
    result_id: uuid.UUID
    parent_id: uuid.UUID | None
    revision: int
    analysis_id: uuid.UUID | None
    valid_until: datetime | None
    state: Literal["ACTIVE", "REMOVED", "EXPIRED"]
    created_at: datetime


def _scope_key(session: Session, project: Project, selection: correlations.Selection) -> str:
    cloud = selection.cloud
    if not isinstance(cloud, correlations.ExternalSelection):
        deny("comparison_scope_invalid", 422)
    source = session.get(SourceInstance, cloud.source_instance_id)
    if source is None or source.project_id != project.id or source.tenant_id != project.tenant_id:
        deny("comparison_scope_invalid", 422)
    domains = _scope_domains(session, cloud)
    return request_hash({"namespace": selection.network_namespace, "source": str(cloud.source_instance_id), "domains": domains})


def _scope_domains(session: Session, cloud: correlations.ExternalSelection) -> list[dict[str, Any]]:
    domains: list[dict[str, Any]] = []
    for domain, version_id in (("ip", cloud.ip_version_id), ("port", cloud.port_version_id)):
        if version_id is None:
            continue
        version = session.get(ExternalAssetVersion, version_id)
        if version is None or version.source_id != cloud.source_instance_id or version.domain != domain:
            deny("comparison_scope_invalid", 422)
        # Scope describes comparable source space, never a changing version identity.
        domains.append({"domain": domain, "space_id": version.space_id, "filter": version.filter})
    return domains


def _confirmation(session: Session, project: Project, value: uuid.UUID) -> SourceCorrelationRevision:
    row = correlations.revision_for(session, project, value)
    if row.scope_state != "CONFIRMED":
        deny("comparison_scope_confirmation_required", 409)
    selection = correlations.Selection.model_validate(row.selection)
    if selection.netflow is not None or selection.customer is None or not isinstance(selection.cloud, correlations.ExternalSelection):
        deny("comparison_scope_invalid", 422)
    loaded = correlations.materials(session, project, selection)
    if request_hash({s: item.pins for s, item in loaded.items()}) != request_hash(row.pins):
        deny("netflow_artifact_integrity_failed")
    return row


def _current_selection(session: Session, project: Project, confirmation: SourceCorrelationRevision) -> tuple[correlations.Selection, dict[Any, Any], str]:
    pinned = correlations.Selection.model_validate(confirmation.selection)
    assert isinstance(pinned.cloud, correlations.ExternalSelection)
    if project.current_customer_upload_id is None:
        deny("comparison_customer_not_ready", 409)
    ip_head = session.get(ExternalAssetHead, (pinned.cloud.source_instance_id, "ip")) if pinned.cloud.ip_version_id else None
    port_head = session.get(ExternalAssetHead, (pinned.cloud.source_instance_id, "port")) if pinned.cloud.port_version_id else None
    if (pinned.cloud.ip_version_id and ip_head is None) or (pinned.cloud.port_version_id and port_head is None):
        deny("comparison_cloud_not_ready", 409)
    selection = correlations.Selection(
        network_namespace=pinned.network_namespace,
        customer=correlations.CustomerSelection(upload_id=project.current_customer_upload_id, revision_id=project.current_customer_ledger_revision_id),
        cloud=correlations.ExternalSelection(kind="external_versions", source_instance_id=pinned.cloud.source_instance_id, ip_version_id=ip_head.version_id if ip_head else None, port_version_id=port_head.version_id if port_head else None),
    )
    loaded = correlations.materials(session, project, selection, write=True)
    if loaded["CUSTOMER"].state.read_state != "VALID_NONEMPTY" or loaded["CLOUD"].state.coverage_state != "SUFFICIENT":
        deny("comparison_inputs_not_ready", 409)
    pins = {key: value.pins for key, value in loaded.items()}
    return selection, pins, request_hash({"selection": selection.model_dump(mode="json"), "pins": pins})


def confirm_scope(session: Session, project: Project, actor: User, body: ConfirmScope, key: str) -> ResultPublic:
    if not actor.is_superuser:
        deny("comparison_scope_admin_required", 403)
    selection = correlations.Selection(network_namespace=body.network_namespace, customer=correlations.CustomerSelection(upload_id=body.customer_upload_id, revision_id=body.customer_revision_id), cloud=correlations.ExternalSelection(kind="external_versions", source_instance_id=body.source_instance_id, ip_version_id=body.ip_version_id, port_version_id=body.port_version_id))
    request = body.model_dump(mode="json")
    recovered = operation_result(session, project, actor.id, "comparison:confirm", key, request)
    if recovered:
        row = _confirmation(session, project, recovered)
        return ResultPublic(project_id=project.id, id=row.id, scope_key=_scope_key(session, project, correlations.Selection.model_validate(row.selection)), scope_confirmation_id=row.id, purpose="confirmation", status="CONFIRMED", published_at=row.created_at, selection=row.selection, pins=row.pins, created_at=row.created_at, input_sha256=request_hash(row.pins))
    loaded = correlations.materials(session, project, selection, write=True)
    identity = uuid.uuid4()
    row = SourceCorrelationRevision(id=identity, root_id=identity, tenant_id=project.tenant_id, project_id=project.id, revision=1, network_namespace=body.network_namespace, scope_state="CONFIRMED", selection=selection.model_dump(mode="json"), pins={s: item.pins for s, item in loaded.items()}, evidence=body.evidence.strip(), created_by=actor.id)
    session.add(row)
    record_operation(session, project, actor.id, "comparison:confirm", key, request, row.id)
    session.commit()
    return ResultPublic(project_id=project.id, id=row.id, scope_key=_scope_key(session, project, selection), scope_confirmation_id=row.id, purpose="confirmation", status="CONFIRMED", published_at=row.created_at, selection=row.selection, pins=row.pins, created_at=row.created_at, input_sha256=request_hash(row.pins))


def _result(session: Session, project: Project, result_id: uuid.UUID) -> CoreComparisonResult:
    row = session.get(CoreComparisonResult, result_id)
    if row is None or row.project_id != project.id or row.tenant_id != project.tenant_id:
        deny("comparison_result_not_found", 404)
    return row


def _read(session: Session, project: Project, row: CoreComparisonResult) -> tuple[correlations.Selection, dict[correlations.Source, correlations.Material]]:
    confirmation = _confirmation(session, project, row.scope_confirmation_id)
    correlations.read_material(session, project, confirmation)
    selection = correlations.Selection.model_validate(row.selection)
    loaded = correlations.materials(session, project, selection)
    if request_hash({s: item.pins for s, item in loaded.items()}) != request_hash(row.pins):
        deny("netflow_artifact_integrity_failed")
    return selection, loaded


def _public(row: CoreComparisonResult) -> ResultPublic:
    return ResultPublic(project_id=row.project_id, id=row.id, scope_key=row.scope_key, scope_confirmation_id=row.scope_confirmation_id, purpose=cast(Literal["regular", "custom"], row.purpose), status=row.status, published_at=row.published_at, created_at=row.created_at, selection=row.selection, pins=row.pins, input_sha256=row.input_sha256)


def create(session: Session, project: Project, actor: User, body: CreateResult, key: str) -> ResultPublic:
    request = body.model_dump(mode="json")
    recovered = operation_result(session, project, actor.id, "comparison:create", key, request)
    if recovered:
        return _public(_result(session, project, recovered))
    confirmation = _confirmation(session, project, body.scope_confirmation_id)
    selection, pins, input_hash = _current_selection(session, project, confirmation)
    if body.expected_input_sha256 != input_hash:
        deny("comparison_input_conflict")
    scope_key = _scope_key(session, project, selection)
    current = _latest(session, project, scope_key)
    if body.purpose == "regular" and body.expected_current_result_id != (current.id if current else None):
        deny("comparison_publish_conflict")
    # A regular publication must use a confirmation for the exact current C/A pins.
    if body.purpose == "regular" and request_hash(confirmation.pins) != request_hash(pins):
        deny("comparison_scope_confirmation_required")
    row = CoreComparisonResult(tenant_id=project.tenant_id, project_id=project.id, scope_key=scope_key, scope_confirmation_id=confirmation.id, purpose=body.purpose, status="PUBLISHED", published_at=get_datetime_utc(), selection=selection.model_dump(mode="json"), pins=pins, input_sha256=input_hash, created_by=actor.id)
    session.add(row)
    record_operation(session, project, actor.id, "comparison:create", key, request, row.id)
    session.add(AuditEvent(tenant_id=project.tenant_id, project_id=project.id, actor_subject=str(actor.id), actor_type="user", action="comparison_result.published", target_type="core_comparison_result", target_id=row.id, after_data={"scope_key": scope_key, "purpose": body.purpose}))
    session.commit()
    return _public(row)


def _latest(session: Session, project: Project, scope_key: str) -> CoreComparisonResult | None:
    rows = session.exec(select(CoreComparisonResult).where(CoreComparisonResult.project_id == project.id, CoreComparisonResult.tenant_id == project.tenant_id, CoreComparisonResult.scope_key == scope_key, CoreComparisonResult.purpose == "regular", CoreComparisonResult.status == "PUBLISHED").order_by(col(CoreComparisonResult.published_at).desc(), col(CoreComparisonResult.id).desc())).all()
    for row in rows:
        try:
            _read(session, project, row)
        except HTTPException as error:
            detail: dict[str, Any] = cast(dict[str, Any], error.detail) if isinstance(error.detail, dict) else {}
            if (error.status_code, detail.get("code")) in {(403, "correlation_source_access_revoked"), (410, "correlation_source_expired")}:
                continue
            raise
        return row
    return None


def _current_choices(session: Session, project: Project) -> list[dict[str, Any]]:
    rows = session.exec(
        select(SourceCorrelationRevision)
        .where(
            SourceCorrelationRevision.project_id == project.id,
            SourceCorrelationRevision.tenant_id == project.tenant_id,
            SourceCorrelationRevision.scope_state == "CONFIRMED",
        )
        .order_by(
            col(SourceCorrelationRevision.created_at).desc(),
            col(SourceCorrelationRevision.id).desc(),
        )
    ).all()
    choices_by_scope: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            # Keep scope revocation/readability checks separate from present C/A selection.
            correlations.read_material(session, project, row)
            selection, _pins, digest = _current_selection(session, project, row)
            scope_key = _scope_key(session, project, selection)
        except (ValueError, HTTPException):
            continue
        cloud = cast(correlations.ExternalSelection, selection.cloud)
        choices_by_scope.setdefault(
            scope_key,
            ScopeChoice(scope_key=scope_key, scope_confirmation_id=row.id, network_namespace=selection.network_namespace, source_instance_id=cloud.source_instance_id, domains=[ScopeDomain.model_validate(value) for value in _scope_domains(session, cloud)], selection=selection.model_dump(mode="json"), input_sha256=digest),
        )
    return list(choices_by_scope.values())


def _readiness_failure(error: HTTPException) -> tuple[ReadinessState, str | None]:
    detail = error.detail if isinstance(error.detail, dict) else {}
    code = detail.get("code") if isinstance(detail.get("code"), str) else None
    return ({
        "comparison_customer_not_ready": "CUSTOMER_NOT_READY",
        "comparison_cloud_not_ready": "CLOUD_NOT_READY",
        "comparison_inputs_not_ready": "INPUTS_INSUFFICIENT",
        "comparison_scope_confirmation_required": "SCOPE_CONFIRMATION_REQUIRED",
        "correlation_scope_unconfirmed": "SCOPE_CONFIRMATION_REQUIRED",
    }.get(code, "METADATA_UNAVAILABLE"), code)


def readiness(session: Session, project: Project, scope_confirmation_id: uuid.UUID | None = None) -> Readiness:
    choices = _current_choices(session, project)
    if scope_confirmation_id is None:
        if len(choices) == 0:
            return Readiness(state="SCOPE_CONFIRMATION_REQUIRED")
        if len(choices) != 1:
            return Readiness(state="MULTIPLE_SCOPES", scope_choices=choices)
        scope_confirmation_id = choices[0].scope_confirmation_id
    confirmation = _confirmation(session, project, scope_confirmation_id)
    try:
        selection, pins, digest = _current_selection(session, project, confirmation)
    except HTTPException as error:
        state, code = _readiness_failure(error)
        return Readiness(
            state=state,
            reason_code=code,
            scope_key=_scope_key(session, project, correlations.Selection.model_validate(confirmation.selection)),
            scope_confirmation_id=confirmation.id,
            scope_choices=choices,
        )
    scope_key = _scope_key(session, project, selection)
    if request_hash(confirmation.pins) != request_hash(pins):
        return Readiness(
            state="SCOPE_CONFIRMATION_REQUIRED",
            scope_key=scope_key,
            scope_confirmation_id=confirmation.id,
            selection=selection.model_dump(mode="json"),
            input_sha256=digest,
            scope_choices=choices,
        )
    current = _latest(session, project, scope_key)
    return Readiness(
        state="READY" if current else "NO_RESULT",
        scope_key=scope_key,
        scope_confirmation_id=confirmation.id,
        selection=selection.model_dump(mode="json"),
        input_sha256=digest,
        expected_current_result_id=current.id if current else None,
        scope_choices=choices,
    )


def _rows(row: CoreComparisonResult, loaded: dict[correlations.Source, correlations.Material]) -> list[Address]:
    groups: dict[str, dict[str, int]] = {}
    for source in ("CUSTOMER", "CLOUD"):
        for record in loaded[source].records:
            groups.setdefault(record.canonical_ip, {"CUSTOMER": 0, "CLOUD": 0})[source] += 1
    values = []
    for ip, counts in groups.items():
        classification: Literal["both", "cloud_only", "customer_only"] = "both" if counts["CUSTOMER"] and counts["CLOUD"] else "cloud_only" if counts["CLOUD"] else "customer_only"
        values.append(Address(address_key="addr:" + request_hash([str(row.id), ip]), canonical_ip=ip, classification=classification, customer_records=counts["CUSTOMER"], cloud_records=counts["CLOUD"]))
    return sorted(values, key=lambda value: (ipaddress.ip_address(value.canonical_ip).version, int(ipaddress.ip_address(value.canonical_ip)), value.address_key))


def summary(session: Session, project: Project, result_id: uuid.UUID) -> ResultSummary:
    row = _result(session, project, result_id)
    _selection, loaded = _read(session, project, row)
    rows = _rows(row, loaded)
    return ResultSummary(**_public(row).model_dump(), total_addresses=len(rows), both=sum(item.classification == "both" for item in rows), cloud_only=sum(item.classification == "cloud_only" for item in rows), customer_only=sum(item.classification == "customer_only" for item in rows), source_states={source: material.state for source, material in loaded.items() if source in {"CUSTOMER", "CLOUD"}})


def addresses(session: Session, project: Project, result_id: uuid.UUID, classification: str, ip: str | None, skip: int, limit: int) -> AddressPage:
    row = _result(session, project, result_id)
    _selection, loaded = _read(session, project, row)
    all_rows = _rows(row, loaded)
    if ip is not None:
        ip = str(ipaddress.ip_address(ip))
    values = [item for item in all_rows if (classification == "all" or item.classification == classification) and (ip is None or item.canonical_ip == ip)]
    return AddressPage(result_id=row.id, data=values[skip:skip + limit], count=len(values), skip=skip, limit=limit, total_addresses=len(all_rows))


def _binding(session: Session, result: CoreComparisonResult, binding_id: uuid.UUID | None = None) -> CoreComparisonSupplement | None:
    query = select(CoreComparisonSupplement).where(CoreComparisonSupplement.result_id == result.id)
    if binding_id is not None:
        return session.exec(query.where(CoreComparisonSupplement.id == binding_id)).one_or_none()
    return session.exec(query.order_by(col(CoreComparisonSupplement.revision).desc())).first()


def _binding_public(row: CoreComparisonSupplement) -> SupplementPublic:
    state: Literal["ACTIVE", "REMOVED", "EXPIRED"] = "REMOVED" if row.analysis_id is None else "EXPIRED" if row.valid_until and row.valid_until <= get_datetime_utc() else "ACTIVE"
    return SupplementPublic(id=row.id, result_id=row.result_id, parent_id=row.parent_id, revision=row.revision, analysis_id=row.analysis_id, valid_until=row.valid_until, state=state, created_at=row.created_at)


def bind(session: Session, project: Project, actor: User, result_id: uuid.UUID, body: SupplementCreate, key: str) -> SupplementPublic:
    result = _result(session, project, result_id)
    request = {"result_id": str(result_id), **body.model_dump(mode="json")}
    existing = operation_result(session, project, actor.id, f"comparison:supplement:{result_id}", key, request)
    if existing:
        row = _binding(session, result, existing)
        assert row is not None
        return _binding_public(row)
    parent = _binding(session, result)
    if body.expected_binding_id != (parent.id if parent else None):
        deny("comparison_supplement_conflict")
    evidence = (body.scope_evidence or "").strip()
    if body.analysis_id is None:
        if body.valid_until is not None or body.qualification_confirmation_id is not None or evidence:
            deny("comparison_supplement_invalid", 422)
    else:
        if body.valid_until is None or body.valid_until <= get_datetime_utc():
            deny("comparison_supplement_valid_until_required", 422)
        analysis, _bundle = analysis_material(session, project, body.analysis_id)
        selection = correlations.Selection.model_validate(result.selection)
        if analysis.network_namespace != selection.network_namespace:
            deny("comparison_supplement_scope_unconfirmed")
        if body.qualification_confirmation_id is not None:
            confirmation = _confirmation(session, project, body.qualification_confirmation_id)
            qselection = correlations.Selection.model_validate(confirmation.selection)
            if qselection.netflow is None or qselection.netflow.analysis_id != analysis.id or _scope_key(session, project, qselection) != result.scope_key:
                deny("comparison_supplement_scope_unconfirmed")
        elif not (actor.is_superuser and evidence):
            deny("comparison_supplement_scope_unconfirmed", 403)
        row_window = {"state": "UNKNOWN", "reason": "analysis_has_no_verified_observation_window"}
        row = CoreComparisonSupplement(result_id=result.id, parent_id=parent.id if parent else None, revision=(parent.revision + 1 if parent else 1), analysis_id=analysis.id, qualification_confirmation_id=body.qualification_confirmation_id, qualification_evidence=evidence or None, valid_until=body.valid_until, observation_window=row_window, created_by=actor.id, operation_key=key, request_sha256=request_hash(request))
        session.add(row)
        record_operation(session, project, actor.id, f"comparison:supplement:{result_id}", key, request, row.id)
        session.commit()
        return _binding_public(row)
    row = CoreComparisonSupplement(result_id=result.id, parent_id=parent.id if parent else None, revision=(parent.revision + 1 if parent else 1), analysis_id=None, qualification_confirmation_id=None, qualification_evidence=None, valid_until=None, observation_window={}, created_by=actor.id, operation_key=key, request_sha256=request_hash(request))
    session.add(row)
    record_operation(
        session, project, actor.id, f"comparison:supplement:{result_id}", key, request, row.id
    )
    session.commit()
    return _binding_public(row)


def supplements(session: Session, project: Project, result_id: uuid.UUID) -> list[SupplementPublic]:
    result = _result(session, project, result_id)
    return [_binding_public(row) for row in session.exec(select(CoreComparisonSupplement).where(CoreComparisonSupplement.result_id == result.id).order_by(col(CoreComparisonSupplement.revision).desc())).all()]
