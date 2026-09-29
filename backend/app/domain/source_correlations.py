"""Read-through, immutable selections; source records never become another asset table."""
from __future__ import annotations

import ipaddress
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlmodel import Session, col, select

from app.core.time import get_datetime_utc
from app.domain import cloudatlas_ledger, customer_ledger, external_assets
from app.domain.external_asset_models import ExternalAssetRecord
from app.domain.ip_consistency import IPRecordContractError, normalize_ip
from app.domain.models import NetFlowDataset, ObservationResourceLink, Project, SourceInstance
from app.domain.netflow_common import deny, operation_result, record_operation, request_hash
from app.domain.netflow_models import NetFlowContextRevision, SourceCorrelationRevision
from app.domain.netflow_processing import analysis_for, analysis_material
from app.models import User

Source = Literal["CUSTOMER", "CLOUD", "NETFLOW"]
Scope = Literal["UNKNOWN", "CONFIRMED", "REVOKED"]
SOURCES: tuple[Source, ...] = ("CUSTOMER", "CLOUD", "NETFLOW")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CustomerSelection(Input):
    upload_id: uuid.UUID
    revision_id: uuid.UUID | None = None


class LegacySelection(Input):
    kind: Literal["legacy_snapshot"]
    source_snapshot_id: uuid.UUID
    ledger_revision: int = Field(ge=0)
    scope_revision: int = Field(ge=0)


class ExternalSelection(Input):
    kind: Literal["external_versions"]
    source_instance_id: uuid.UUID
    ip_version_id: uuid.UUID | None = None
    port_version_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def nonempty(self) -> ExternalSelection:
        if self.ip_version_id is None and self.port_version_id is None:
            raise ValueError("version_required")
        return self


class NetFlowSelection(Input):
    analysis_id: uuid.UUID


class Selection(Input):
    network_namespace: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    customer: CustomerSelection | None = None
    cloud: LegacySelection | ExternalSelection | None = Field(default=None, discriminator="kind")
    netflow: NetFlowSelection | None = None
    history_run_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def nonempty(self) -> Selection:
        if self.customer is None and self.cloud is None and self.netflow is None:
            raise ValueError("source_required")
        return self


class ScopeChange(Input):
    expected_parent_id: uuid.UUID
    scope_state: Scope
    evidence: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def meaningful(self) -> ScopeChange:
        if not self.evidence.strip():
            raise ValueError("evidence_required")
        return self


class Envelope(BaseModel):
    contract_version: Literal["netflow-correlation-v1"] = "netflow-correlation-v1"
    project_id: uuid.UUID
    correlation_revision_id: uuid.UUID
    network_namespace: str


class RevisionPublic(Envelope):
    root_id: uuid.UUID
    parent_id: uuid.UUID | None
    revision: int
    historical_scope_state: Scope
    current_scope_state: Scope
    selection: Selection
    pins: dict[str, Any]
    evidence: str | None
    created_at: datetime
    created_by: uuid.UUID


class RevisionPage(BaseModel):
    contract_version: Literal["netflow-correlation-v1"] = "netflow-correlation-v1"
    project_id: uuid.UUID
    data: list[RevisionPublic]
    count: int
    skip: int
    limit: int


class SourceState(BaseModel):
    source: Source
    state: Literal["VALID_NONEMPTY", "VALID_EMPTY", "NOT_PROVIDED", "READ_FAILED", "INSUFFICIENT_COVERAGE"]
    read_state: Literal["VALID_NONEMPTY", "VALID_EMPTY", "NOT_PROVIDED", "READ_FAILED"]
    coverage_state: Literal["SUFFICIENT", "INSUFFICIENT", "UNKNOWN", "NOT_APPLICABLE"]
    source_records: int | None = None
    source_addresses: int | None = None
    source_objects: int | None = None
    raw_records: int | None = None
    valid_records: int | None = None
    review_task_count: int | None = None
    limitations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskRef(BaseModel):
    analysis_id: uuid.UUID
    task_id: str


class HistoryLink(BaseModel):
    resource_id: uuid.UUID
    run_id: uuid.UUID


class AddressPublic(Envelope):
    address_key: str
    canonical_ip: str
    family: Literal[4, 6]
    positive_sources: list[Source]
    unmatched_netflow: bool
    source_record_count: int | None
    service_object_count: int | None
    source_counts: dict[Source, int | None]
    presence: dict[Source, str]
    reasons: list[str]
    task_refs: list[TaskRef]
    resource_id: uuid.UUID | None = None
    history_link: HistoryLink | None = None
    reachability: Literal["NOT_VERIFIED"] = "NOT_VERIFIED"
    test_fixture: bool = False


class AddressPage(Envelope):
    data: list[AddressPublic]
    count: int
    skip: int
    limit: int
    total_addresses: int
    source_totals: dict[Source, int | None]


class Summary(RevisionPublic):
    sources: list[SourceState]
    total_addresses: int
    positive_intersections: dict[str, int] | None
    test_fixture: bool
    limitations: list[str]


class EvidenceRecord(BaseModel):
    source: Source
    record_key: str
    version_id: str
    domain: str
    canonical_ip: str
    original: dict[str, Any]
    availability: dict[str, Literal["MISSING", "NULL", "EMPTY", "PRESENT"]]
    object_key: str | None = None
    side: Literal["source"] = "source"


class EvidencePage(Envelope):
    address_key: str
    source: Source
    data: list[EvidenceRecord]
    count: int
    retained_count: int
    omitted_count: int
    skip: int
    limit: int
    pins: dict[str, Any]


class Comparison(BaseModel):
    record_key: str
    protocol_relation: Literal["EQUAL", "DIFFERENT", "UNKNOWN", "NOT_APPLICABLE"]
    port_relation: Literal["IN_RANGE", "OUT_OF_RANGE", "EQUAL", "DIFFERENT", "UNKNOWN", "NOT_APPLICABLE"]
    time_relation: Literal["OVERLAP", "DISJOINT", "UNKNOWN"] = "UNKNOWN"
    reasons: list[str]


class ServicePublic(BaseModel):
    object_key: str
    source: Source
    protocol_number: int | None
    local_port: int | None
    original: dict[str, Any]
    customer_comparisons: list[Comparison]
    cloud_comparisons: list[Comparison]
    role_state: Literal["UNKNOWN"] = "UNKNOWN"
    assessment: Literal["INSUFFICIENT_EVIDENCE"] = "INSUFFICIENT_EVIDENCE"
    reachability: Literal["NOT_VERIFIED"] = "NOT_VERIFIED"
    reasons: list[str]


class ServicePage(Envelope):
    address_key: str
    data: list[ServicePublic]
    count: int
    skip: int
    limit: int


@dataclass
class Material:
    source: Source
    state: SourceState
    pins: dict[str, Any] = field(default_factory=dict)
    records: list[EvidenceRecord] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    test_fixture: bool = False
    legacy_valid: bool = False


def canonical(value: str) -> str:
    try:
        return normalize_ip(value)
    except (IPRecordContractError, ValueError):
        deny("netflow_context_invalid", 422)


def _record(source: Source, key: str, version: str, domain: str, ip: str, original: dict[str, Any], fields: tuple[str, ...] = ()) -> EvidenceRecord:
    values = {**original}
    if source == "CUSTOMER":
        values.update({f"fields.{k}": v for k, v in original["fields"].items()})
        fields = tuple(f"fields.{k}" for k in customer_ledger.FIELD_NAMES)
    return EvidenceRecord(source=source, record_key=key, version_id=version, domain=domain,
        canonical_ip=canonical(ip), original=original,
        availability={k: "MISSING" if k not in values else "NULL" if values[k] is None else "EMPTY" if values[k] == "" else "PRESENT" for k in set(values) | set(fields)})


def _state(source: Source, records: list[EvidenceRecord], coverage: Literal["SUFFICIENT", "INSUFFICIENT", "UNKNOWN"], **values: Any) -> SourceState:
    read: Literal["VALID_NONEMPTY", "VALID_EMPTY"] = "VALID_NONEMPTY" if records else "VALID_EMPTY"
    return SourceState(source=source, state=read if coverage == "SUFFICIENT" else "INSUFFICIENT_COVERAGE", read_state=read,
        coverage_state=coverage, source_records=len(records), source_addresses=len({r.canonical_ip for r in records}), source_objects=len(records), **values)


def _source(session: Session, project: Project, source_id: uuid.UUID, profile: str) -> SourceInstance:
    source = session.get(SourceInstance, source_id)
    if source is None or source.project_id != project.id or source.tenant_id != project.tenant_id or source.capability_profile != profile:
        deny("netflow_input_not_found", 404)
    if not source.data_access_enabled:
        deny("correlation_source_access_revoked", 403)
    return source


def _customer(session: Session, project: Project, selection: CustomerSelection) -> Material:
    try:
        upload, revision, rows = customer_ledger.load_rows(session, project, selection.upload_id, selection.revision_id)
        # A revision does not excuse integrity checking the pinned original artifact.
        if revision is not None:
            customer_ledger.load_rows(session, project, upload.id, None)
    except customer_ledger.LedgerError as error:
        deny("netflow_input_not_found" if error.status == 404 else "netflow_artifact_integrity_failed", 404 if error.status == 404 else 409)
    records = [_record("CUSTOMER", str(r.entry_id), str(revision.id if revision else upload.id), "customer", r.canonical_ip, r.model_dump(mode="json")) for r in rows if not r.archived]
    pins = {"upload_id": str(upload.id), "raw_sha256": upload.raw_sha256, "profile_id": str(upload.profile_id), "profile_version": upload.profile_version,
        "revision_id": str(revision.id) if revision else None, "rows_sha256": request_hash([r.model_dump(mode="json") for r in rows])}
    return Material("CUSTOMER", _state("CUSTOMER", records, "SUFFICIENT"), pins, records)


def _external(session: Session, project: Project, selection: ExternalSelection) -> Material:
    source = _source(session, project, selection.source_instance_id, "assets-v1")
    records: list[EvidenceRecord] = []
    domains: dict[str, Any] = {}
    sufficient = True
    for domain, version_id in (("ip", selection.ip_version_id), ("port", selection.port_version_id)):
        if version_id is None:
            continue
        try:
            version = external_assets.selected_version(session, source, domain, version_id)
        except HTTPException:
            deny("netflow_input_not_found", 404)
        assert version is not None
        if version.retain_until <= get_datetime_utc():
            deny("correlation_source_expired", 410)
        rows = session.exec(select(ExternalAssetRecord).where(ExternalAssetRecord.version_id == version.id).order_by(ExternalAssetRecord.source_id)).all()
        if len(rows) != version.record_count:
            deny("netflow_artifact_integrity_failed")
        domains[domain] = {**version.model_dump(mode="json"), "records_sha256": request_hash([r.model_dump(mode="json") for r in rows])}
        sufficient = sufficient and version.complete and not version.filter
        for row in rows:
            if row.canonical_ip is None or row.ip is None or canonical(row.ip) != canonical(row.canonical_ip):
                deny("netflow_artifact_integrity_failed")
            records.append(_record("CLOUD", row.source_id, str(version.id), domain, row.canonical_ip,
                {"source_id": row.source_id, "ip": row.ip, **row.fields}, ("protocol", "port", "update_time", "create_time")))
    pins = {"kind": selection.kind, "source_instance_id": str(source.id), "space_id": source.space_id, "domains": domains}
    return Material("CLOUD", _state("CLOUD", records, "SUFFICIENT" if sufficient else "INSUFFICIENT", metadata={"domains": domains}, limitations=[] if sufficient else ["CLOUD_SELECTED_BATCH_NOT_FULL_COVERAGE"]), pins, records)


def _legacy(session: Session, project: Project, selection: LegacySelection) -> Material:
    try:
        snapshot = cloudatlas_ledger._snapshot(session, project, selection.source_snapshot_id)
        assert snapshot.source_instance_id is not None
        source = _source(session, project, snapshot.source_instance_id, "legacy-ip-v1")
        page = cloudatlas_ledger.read_page(session, project, snapshot_id=snapshot.id, revision=selection.ledger_revision, limit=max(1, snapshot.record_count))
        scope = cloudatlas_ledger.read_page(session, project, snapshot_id=snapshot.id, revision=selection.scope_revision, limit=1)
    except cloudatlas_ledger.CloudLedgerError as error:
        deny("netflow_input_not_found" if error.status == 404 else "netflow_artifact_integrity_failed", 404 if error.status == 404 else 409)
    if scope.scope_revision != selection.scope_revision:
        deny("netflow_input_not_found", 404)
    records = [_record("CLOUD", row.source_record_key, str(snapshot.id), "legacy_snapshot", row.canonical_ip, row.model_dump(mode="json"), ("protocol", "port")) for row in page.data]
    pins = {"kind": selection.kind, "source_snapshot_id": str(snapshot.id), "source_instance_id": str(source.id), "run_id": str(snapshot.governance_run_id),
        "content_sha256": snapshot.content_sha256, "ledger_revision": selection.ledger_revision, "scope_revision": selection.scope_revision, "status_filter": "valid", "rows_sha256": request_hash([r.model_dump(mode="json") for r in records])}
    return Material("CLOUD", _state("CLOUD", records, "SUFFICIENT", limitations=["PORT_EVIDENCE_NOT_RETAINED"]), pins, records, legacy_valid=scope.association == "CONFIRMED_LEGACY")


def _netflow(session: Session, project: Project, selection: NetFlowSelection, namespace: str) -> Material:
    analysis = analysis_for(session, project, selection.analysis_id)
    if analysis.network_namespace != namespace:
        deny("netflow_input_not_found", 404)
    context = session.get(NetFlowContextRevision, analysis.context_revision_id)
    if context is None:
        deny("netflow_input_not_found", 404)
    current = session.exec(select(NetFlowContextRevision).where(NetFlowContextRevision.project_id == project.id, NetFlowContextRevision.tenant_id == project.tenant_id, NetFlowContextRevision.dataset_id == analysis.dataset_id).order_by(col(NetFlowContextRevision.revision).desc())).first()
    if current is None or current.state != "CONFIRMED" or current.network_namespace != namespace:
        deny("netflow_context_revoked")
    pins = {"analysis_id": str(analysis.id), "dataset_id": str(analysis.dataset_id), "context_revision_id": str(analysis.context_revision_id), "processing_identity_sha256": analysis.processing_identity_sha256, "identity": analysis.identity}
    pins.update(raw_sha256=context.raw_sha256, normalized_sha256=context.normalized_sha256)
    if analysis.status not in {"SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"}:
        return Material("NETFLOW", SourceState(source="NETFLOW", state="READ_FAILED", read_state="READ_FAILED", coverage_state="UNKNOWN", limitations=[analysis.error_code or "netflow_analysis_not_ready"], metadata={"status": analysis.status}), pins, test_fixture=analysis.test_fixture)
    analysis, bundle = analysis_material(session, project, analysis.id)
    observations = bundle.observations
    records = [_record("NETFLOW", str(row["object_key"]), str(analysis.id), "source_observation", str(row["ip"]), row) for row in observations]
    pins["result_sha256"] = request_hash(analysis.result)
    state = _state("NETFLOW", records, "UNKNOWN", limitations=["SOURCE_POSITION_ONLY", "SAMPLING_UNKNOWN", "VIEW_UNKNOWN"], metadata={"quality": analysis.quality}, review_task_count=len(bundle.tasks))
    state.source_records = sum(int(row["features"]["record_count"]) for row in observations)
    dataset = session.get(NetFlowDataset, analysis.dataset_id)
    if dataset is None or dataset.project_id != project.id or dataset.tenant_id != project.tenant_id:
        deny("netflow_input_not_found", 404)
    state.raw_records = dataset.raw_record_count
    state.valid_records = dataset.activity_valid_record_count
    if dataset.isolated_record_count:
        state.coverage_state = "INSUFFICIENT"
        state.limitations.append("INPUT_RECORDS_ISOLATED")
    return Material("NETFLOW", state, pins, records, observations, analysis.test_fixture)


def materials(session: Session, project: Project, selection: Selection) -> dict[Source, Material]:
    result = {s: Material(s, SourceState(source=s, state="NOT_PROVIDED", read_state="NOT_PROVIDED", coverage_state="NOT_APPLICABLE")) for s in SOURCES}
    if selection.customer is not None:
        result["CUSTOMER"] = _customer(session, project, selection.customer)
    if isinstance(selection.cloud, ExternalSelection):
        result["CLOUD"] = _external(session, project, selection.cloud)
    elif isinstance(selection.cloud, LegacySelection):
        result["CLOUD"] = _legacy(session, project, selection.cloud)
    if selection.netflow is not None:
        result["NETFLOW"] = _netflow(session, project, selection.netflow, selection.network_namespace)
    if selection.history_run_id is not None:
        cloud = result["CLOUD"]
        if selection.network_namespace != "legacy" or not cloud.legacy_valid or cloud.pins.get("run_id") != str(selection.history_run_id):
            deny("correlation_scope_unconfirmed")
    return result


def revision_for(session: Session, project: Project, revision_id: uuid.UUID) -> SourceCorrelationRevision:
    row = session.get(SourceCorrelationRevision, revision_id)
    if row is None or row.project_id != project.id or row.tenant_id != project.tenant_id:
        deny("correlation_not_found", 404)
    return row


def current_for(session: Session, row: SourceCorrelationRevision) -> SourceCorrelationRevision:
    current = session.exec(select(SourceCorrelationRevision).where(SourceCorrelationRevision.root_id == row.root_id, SourceCorrelationRevision.project_id == row.project_id, SourceCorrelationRevision.tenant_id == row.tenant_id).order_by(col(SourceCorrelationRevision.revision).desc())).first()
    assert current is not None
    return current


def public(row: SourceCorrelationRevision, current: SourceCorrelationRevision) -> RevisionPublic:
    return RevisionPublic(project_id=row.project_id, correlation_revision_id=row.id, network_namespace=row.network_namespace, root_id=row.root_id, parent_id=row.parent_id,
        revision=row.revision, historical_scope_state=cast(Scope, row.scope_state), current_scope_state=cast(Scope, current.scope_state), selection=Selection.model_validate(row.selection), pins=row.pins,
        evidence=row.evidence, created_at=row.created_at, created_by=row.created_by)


def read_material(session: Session, project: Project, row: SourceCorrelationRevision) -> tuple[SourceCorrelationRevision, dict[Source, Material]]:
    current = current_for(session, row)
    if current.scope_state == "REVOKED":
        deny("correlation_scope_unconfirmed")
    if row.scope_state == "CONFIRMED" and current.scope_state != "CONFIRMED":
        deny("correlation_scope_unconfirmed")
    loaded = materials(session, project, Selection.model_validate(row.selection))
    if row.scope_state == "CONFIRMED" and row.pins["CLOUD"].get("scope_revision", 0) and not loaded["CLOUD"].legacy_valid:
        deny("correlation_scope_unconfirmed")
    if request_hash({s: m.pins for s, m in loaded.items()}) != request_hash(row.pins):
        deny("netflow_artifact_integrity_failed")
    return current, loaded


def create(session: Session, project: Project, actor: User, selection: Selection, key: str) -> RevisionPublic:
    request = {"project_id": str(project.id), **selection.model_dump(mode="json")}
    recovered = operation_result(session, project, actor.id, "correlation:create", key, request)
    if recovered is not None:
        row = revision_for(session, project, recovered)
        current, _ = read_material(session, project, row)
        return public(row, current)
    loaded = materials(session, project, selection)
    identity = uuid.uuid4()
    row = SourceCorrelationRevision(id=identity, root_id=identity, tenant_id=project.tenant_id, project_id=project.id, revision=1, network_namespace=selection.network_namespace,
        selection=selection.model_dump(mode="json"), pins={s: m.pins for s, m in loaded.items()}, created_by=actor.id)
    session.add(row)
    record_operation(session, project, actor.id, "correlation:create", key, request, row.id)
    session.commit()
    return public(row, row)


def change_scope(session: Session, project: Project, actor: User, revision_id: uuid.UUID, change: ScopeChange, key: str) -> RevisionPublic:
    parent = revision_for(session, project, revision_id)
    operation = f"correlation:scope:{parent.root_id}"
    request = {"project_id": str(project.id), "revision_id": str(revision_id), **change.model_dump(mode="json")}
    recovered = operation_result(session, project, actor.id, operation, key, request)
    if recovered is not None:
        row = revision_for(session, project, recovered)
        loaded = materials(session, project, Selection.model_validate(row.selection))
        if request_hash({s: m.pins for s, m in loaded.items()}) != request_hash(row.pins):
            deny("netflow_artifact_integrity_failed")
        return public(row, current_for(session, row))
    current = current_for(session, parent)
    if parent.id != current.id or change.expected_parent_id != current.id:
        deny("netflow_revision_conflict")
    loaded = materials(session, project, Selection.model_validate(parent.selection))
    if request_hash({s: m.pins for s, m in loaded.items()}) != request_hash(parent.pins):
        deny("netflow_artifact_integrity_failed")
    row = SourceCorrelationRevision(root_id=parent.root_id, parent_id=parent.id, revision=parent.revision + 1, tenant_id=project.tenant_id, project_id=project.id,
        network_namespace=parent.network_namespace, scope_state=change.scope_state, selection=parent.selection, pins=parent.pins, evidence=change.evidence, created_by=actor.id)
    session.add(row)
    record_operation(session, project, actor.id, operation, key, request, row.id)
    session.commit()
    return public(row, row)


def _envelope(row: SourceCorrelationRevision) -> dict[str, Any]:
    return {"project_id": row.project_id, "correlation_revision_id": row.id, "network_namespace": row.network_namespace}


def addresses(session: Session, project: Project, row: SourceCorrelationRevision, loaded: dict[Source, Material]) -> list[AddressPublic]:
    confirmed = row.scope_state == "CONFIRMED"
    grouped: dict[tuple[str, Source | None], dict[Source, list[EvidenceRecord]]] = {}
    for source, material in loaded.items():
        for record in material.records:
            group = grouped.setdefault((record.canonical_ip, None if confirmed else source), {s: [] for s in SOURCES})
            group[source].append(record)
    result: list[AddressPublic] = []
    for (ip, isolated), groups in grouped.items():
        positive = [s for s in SOURCES if groups[s]]
        presence: dict[Source, str] = {}
        for source in SOURCES:
            state = loaded[source].state
            presence[source] = "MATCHED" if groups[source] else state.read_state if state.read_state in {"NOT_PROVIDED", "READ_FAILED"} else "SCOPE_UNCONFIRMED" if not confirmed else "NO_MATCH_IN_PINNED_INPUT" if state.coverage_state == "SUFFICIENT" else "NO_MATCH_COVERAGE_UNKNOWN"
        observations = [r.original for r in groups["NETFLOW"]]
        analysis_id = loaded["NETFLOW"].pins.get("analysis_id")
        tasks = sorted({str(t) for o in observations for t in o.get("review_task_ids", [])})
        key = "addr:" + request_hash([str(project.tenant_id), str(project.id), row.network_namespace, ip, isolated])
        history = None
        if confirmed and row.selection.get("history_run_id") and groups["CLOUD"] and loaded["CLOUD"].legacy_valid:
            observation_ids = [uuid.UUID(r.original["observation_id"]) for r in groups["CLOUD"]]
            link = session.exec(select(ObservationResourceLink).where(ObservationResourceLink.project_id == project.id, ObservationResourceLink.tenant_id == project.tenant_id,
                ObservationResourceLink.governance_run_id == uuid.UUID(row.selection["history_run_id"]), col(ObservationResourceLink.observation_id).in_(observation_ids))).first()
            if link is not None:
                history = HistoryLink(resource_id=link.resource_id, run_id=link.governance_run_id)
        result.append(AddressPublic(**_envelope(row), address_key=key, canonical_ip=ip, family=cast(Literal[4, 6], ipaddress.ip_address(ip).version), positive_sources=positive,
            unmatched_netflow="NETFLOW" in positive and len(positive) == 1, source_record_count=sum(int(o["features"]["record_count"]) for o in observations) if observations else None,
            service_object_count=len(observations) if observations else None, source_counts={s: (sum(int(o["features"]["record_count"]) for o in observations) if s == "NETFLOW" else len(groups[s])) if loaded[s].state.read_state.startswith("VALID") and (confirmed or s in positive) else None for s in SOURCES},
            presence=presence, reasons=(["CANONICAL_IP_EQUAL_WITH_CONFIRMED_SCOPE"] if confirmed and len(positive) > 1 else []) + [f"{s}_{presence[s]}" for s in SOURCES if presence[s] != "MATCHED"] + (["SOURCE_POSITION_ONLY"] if observations else []),
            task_refs=[TaskRef(analysis_id=analysis_id, task_id=t) for t in tasks], resource_id=history.resource_id if history else None, history_link=history, test_fixture=loaded["NETFLOW"].test_fixture))
    return sorted(result, key=lambda a: (a.family, int(ipaddress.ip_address(a.canonical_ip)), a.address_key))


def selected_address(session: Session, project: Project, row: SourceCorrelationRevision, loaded: dict[Source, Material], key: str) -> AddressPublic:
    for address in addresses(session, project, row, loaded):
        if address.address_key == key:
            return address
    deny("correlation_not_found", 404)


def address_records(address: AddressPublic, loaded: dict[Source, Material], source: Source) -> list[EvidenceRecord]:
    if source not in address.positive_sources:
        return []
    return [r for r in loaded[source].records if r.canonical_ip == address.canonical_ip]


def evidence(row: SourceCorrelationRevision, address: AddressPublic, loaded: dict[Source, Material], source: Source, skip: int, limit: int) -> EvidencePage:
    rows = address_records(address, loaded, source)
    omitted = 0
    if source == "NETFLOW":
        refs: list[EvidenceRecord] = []
        for record in rows:
            omitted += int(record.original["source_refs_omitted"])
            for index, ref in enumerate(record.original["source_refs"]):
                item = _record(source, f"{record.record_key}:{index}", record.version_id, "source_ref", record.canonical_ip, {"reference": ref})
                item.object_key = record.record_key
                refs.append(item)
        rows = refs
    return EvidencePage(**_envelope(row), address_key=address.address_key, source=source, data=rows[skip:skip + limit], count=len(rows), retained_count=len(rows), omitted_count=omitted, skip=skip, limit=limit, pins=loaded[source].pins)


def _protocol(value: Any) -> int | None:
    if isinstance(value, str):
        return {"tcp": 6, "udp": 17, "6": 6, "17": 17}.get(value.strip().lower())
    return value if type(value) is int and value in (6, 17) else None


def _port(value: Any) -> int | None:
    if type(value) is int and 0 <= value <= 65535:
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit() and 0 <= int(value) <= 65535:
        return int(value)
    return None


def _compare(protocol: int | None, port: int | None, record: EvidenceRecord) -> Comparison:
    customer = record.source == "CUSTOMER"
    fields = record.original["fields"] if customer else record.original
    other_protocol = None if customer else _protocol(fields.get("protocol"))
    protocol_relation = "UNKNOWN" if protocol is None or other_protocol is None else "EQUAL" if protocol == other_protocol else "DIFFERENT"
    relation = "UNKNOWN"
    if protocol is not None and protocol not in (6, 17):
        relation = "NOT_APPLICABLE"
    elif port is not None:
        if customer:
            start, end = _port(fields.get("start_port")), _port(fields.get("end_port"))
            if start is not None and end is not None:
                relation = "IN_RANGE" if start <= port <= end else "OUT_OF_RANGE"
        else:
            other_port = _port(fields.get("port"))
            if other_port is not None:
                relation = "EQUAL" if port == other_port else "DIFFERENT"
    return Comparison.model_validate({"record_key": record.record_key, "protocol_relation": protocol_relation, "port_relation": relation, "reasons": ["CUSTOMER_PROTOCOL_NOT_PROVIDED" if customer else "SOURCE_PROTOCOL_PRESERVED", "SOURCE_TIME_NOT_COMPARABLE", "SOURCE_ROLE_UNKNOWN"]})


def services(row: SourceCorrelationRevision, address: AddressPublic, loaded: dict[Source, Material], skip: int, limit: int) -> ServicePage:
    customer = address_records(address, loaded, "CUSTOMER")
    cloud = address_records(address, loaded, "CLOUD")
    netflow = address_records(address, loaded, "NETFLOW")
    result: list[ServicePublic] = []
    for source, records in (("NETFLOW", netflow), ("CUSTOMER", customer), ("CLOUD", cloud)):
        for record in records:
            protocol = record.original.get("protocol") if source == "NETFLOW" else _protocol(record.original.get("protocol")) if source == "CLOUD" else None
            port = _port(record.original.get("local_port" if source == "NETFLOW" else "port"))
            result.append(ServicePublic(object_key=record.record_key if source == "NETFLOW" else f"{source.lower()}:{record.version_id}:{record.domain}:{record.record_key}", source=record.source,
                protocol_number=protocol, local_port=port, original=record.original,
                customer_comparisons=[], cloud_comparisons=[],
                reasons=["SOURCE_ROLE_UNKNOWN", "SOURCE_TIME_NOT_COMPARABLE"] + (["PORT_EVIDENCE_NOT_RETAINED"] if record.domain == "legacy_snapshot" else [])))
    result.sort(key=lambda s: (s.protocol_number is None, s.protocol_number or 0, s.local_port is None, s.local_port or 0, s.object_key))
    page = result[skip:skip + limit]
    for item in page:
        if item.source != "CUSTOMER":
            item.customer_comparisons = [_compare(item.protocol_number, item.local_port, r) for r in customer]
        if item.source != "CLOUD":
            item.cloud_comparisons = [_compare(item.protocol_number, item.local_port, r) for r in cloud]
    return ServicePage(**_envelope(row), address_key=address.address_key, data=page, count=len(result), skip=skip, limit=limit)
