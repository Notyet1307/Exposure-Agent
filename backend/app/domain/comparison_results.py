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
from app.domain.comparison_models import CoreComparisonResult
from app.domain.external_asset_models import ExternalAssetHead
from app.domain.models import AuditEvent, Project
from app.domain.netflow_common import (
    deny,
    operation_result,
    record_operation,
    request_hash,
)
from app.domain.netflow_models import SourceCorrelationRevision
from app.models import User


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
    id: uuid.UUID
    scope_key: str
    scope_confirmation_id: uuid.UUID
    purpose: str
    status: str
    published_at: datetime | None
    selection: dict[str, Any]
    input_sha256: str


class Readiness(BaseModel):
    state: Literal["READY", "NO_RESULT", "SCOPE_CONFIRMATION_REQUIRED", "MULTIPLE_SCOPES"]
    scope_key: str | None = None
    scope_confirmation_id: uuid.UUID | None = None
    selection: dict[str, Any] | None = None
    input_sha256: str | None = None
    expected_current_result_id: uuid.UUID | None = None
    scope_choices: list[dict[str, Any]] = Field(default_factory=list)


class ResultSummary(ResultPublic):
    total_addresses: int
    both: int
    cloud_only: int
    customer_only: int


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


def _scope_key(selection: correlations.Selection) -> str:
    cloud = selection.cloud
    if not isinstance(cloud, correlations.ExternalSelection):
        deny("comparison_scope_invalid", 422)
    return request_hash({"namespace": selection.network_namespace, "source": str(cloud.source_instance_id), "ip": cloud.ip_version_id is not None, "port": cloud.port_version_id is not None})


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
        return ResultPublic(id=row.id, scope_key=_scope_key(correlations.Selection.model_validate(row.selection)), scope_confirmation_id=row.id, purpose="confirmation", status="CONFIRMED", published_at=row.created_at, selection=row.selection, input_sha256=request_hash(row.pins))
    loaded = correlations.materials(session, project, selection, write=True)
    identity = uuid.uuid4()
    row = SourceCorrelationRevision(id=identity, root_id=identity, tenant_id=project.tenant_id, project_id=project.id, revision=1, network_namespace=body.network_namespace, scope_state="CONFIRMED", selection=selection.model_dump(mode="json"), pins={s: item.pins for s, item in loaded.items()}, evidence=body.evidence.strip(), created_by=actor.id)
    session.add(row)
    record_operation(session, project, actor.id, "comparison:confirm", key, request, row.id)
    session.commit()
    return ResultPublic(id=row.id, scope_key=_scope_key(selection), scope_confirmation_id=row.id, purpose="confirmation", status="CONFIRMED", published_at=row.created_at, selection=row.selection, input_sha256=request_hash(row.pins))


def _result(session: Session, project: Project, result_id: uuid.UUID) -> CoreComparisonResult:
    row = session.get(CoreComparisonResult, result_id)
    if row is None or row.project_id != project.id or row.tenant_id != project.tenant_id:
        deny("comparison_result_not_found", 404)
    return row


def _read(session: Session, project: Project, row: CoreComparisonResult) -> tuple[correlations.Selection, dict[correlations.Source, correlations.Material]]:
    selection = correlations.Selection.model_validate(row.selection)
    loaded = correlations.materials(session, project, selection)
    if request_hash({s: item.pins for s, item in loaded.items()}) != request_hash(row.pins):
        deny("netflow_artifact_integrity_failed")
    return selection, loaded


def _public(row: CoreComparisonResult) -> ResultPublic:
    return ResultPublic(id=row.id, scope_key=row.scope_key, scope_confirmation_id=row.scope_confirmation_id, purpose=row.purpose, status=row.status, published_at=row.published_at, selection=row.selection, input_sha256=row.input_sha256)


def create(session: Session, project: Project, actor: User, body: CreateResult, key: str) -> ResultPublic:
    request = body.model_dump(mode="json")
    recovered = operation_result(session, project, actor.id, "comparison:create", key, request)
    if recovered:
        return _public(_result(session, project, recovered))
    confirmation = _confirmation(session, project, body.scope_confirmation_id)
    selection, pins, input_hash = _current_selection(session, project, confirmation)
    if body.expected_input_sha256 != input_hash:
        deny("comparison_input_conflict")
    scope_key = _scope_key(selection)
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


def readiness(session: Session, project: Project, scope_confirmation_id: uuid.UUID | None = None) -> Readiness:
    confirmations = session.exec(select(SourceCorrelationRevision).where(SourceCorrelationRevision.project_id == project.id, SourceCorrelationRevision.tenant_id == project.tenant_id, SourceCorrelationRevision.scope_state == "CONFIRMED").order_by(col(SourceCorrelationRevision.created_at).desc(), col(SourceCorrelationRevision.id).desc())).all()
    choices: list[dict[str, Any]] = []
    for row in confirmations:
        try:
            selection = correlations.Selection.model_validate(row.selection)
            if selection.netflow is None and selection.customer and isinstance(selection.cloud, correlations.ExternalSelection):
                choices.append({"scope_key": _scope_key(selection), "scope_confirmation_id": str(row.id), "network_namespace": selection.network_namespace, "source_instance_id": str(selection.cloud.source_instance_id)})
        except (ValueError, HTTPException):
            continue
    if scope_confirmation_id is None:
        unique = {item["scope_key"] for item in choices}
        if len(unique) != 1:
            return Readiness(state="MULTIPLE_SCOPES", scope_choices=choices)
        scope_confirmation_id = uuid.UUID(choices[0]["scope_confirmation_id"])
    confirmation = _confirmation(session, project, scope_confirmation_id)
    try:
        selection, _pins, digest = _current_selection(session, project, confirmation)
    except HTTPException:
        return Readiness(state="SCOPE_CONFIRMATION_REQUIRED", scope_key=_scope_key(correlations.Selection.model_validate(confirmation.selection)), scope_confirmation_id=confirmation.id, scope_choices=choices)
    if request_hash(confirmation.pins) != request_hash(_pins):
        return Readiness(state="SCOPE_CONFIRMATION_REQUIRED", scope_key=_scope_key(selection), scope_confirmation_id=confirmation.id, selection=selection.model_dump(mode="json"), input_sha256=digest, scope_choices=choices)
    current = _latest(session, project, _scope_key(selection))
    return Readiness(state="READY" if current else "NO_RESULT", scope_key=_scope_key(selection), scope_confirmation_id=confirmation.id, selection=selection.model_dump(mode="json"), input_sha256=digest, expected_current_result_id=current.id if current else None, scope_choices=choices)


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
    return ResultSummary(**_public(row).model_dump(), total_addresses=len(rows), both=sum(item.classification == "both" for item in rows), cloud_only=sum(item.classification == "cloud_only" for item in rows), customer_only=sum(item.classification == "customer_only" for item in rows))


def addresses(session: Session, project: Project, result_id: uuid.UUID, classification: str, ip: str | None, skip: int, limit: int) -> AddressPage:
    row = _result(session, project, result_id)
    _selection, loaded = _read(session, project, row)
    all_rows = _rows(row, loaded)
    if ip is not None:
        ip = str(ipaddress.ip_address(ip))
    values = [item for item in all_rows if (classification == "all" or item.classification == classification) and (ip is None or item.canonical_ip == ip)]
    return AddressPage(result_id=row.id, data=values[skip:skip + limit], count=len(values), skip=skip, limit=limit, total_addresses=len(all_rows))
