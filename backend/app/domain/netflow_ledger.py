"""Read immutable Dataset evidence; append local scope and handling revisions."""

from __future__ import annotations

import csv
import hashlib
import io
import ipaddress
import json
import os
import stat
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from app.core.config import settings
from app.domain import cloudatlas_ledger, customer_ledger
from app.domain.customer_ledger import Text
from app.domain.ip_consistency import IPRecordContractError, normalize_ip
from app.domain.models import (
    Artifact,
    AuditEvent,
    NetFlowDataset,
    NetFlowLedgerRevision,
    Project,
)
from app.domain.netflow_activity import NetFlowActivityContractError, _protocol, _time
from app.domain.netflow_datasets import (
    CANONICAL_COLUMNS,
    NETFLOW_DATASET_CONTRACT_VERSION,
    SCHEMA_FINGERPRINT,
)

CONTRACT = "netflow-native-endpoints-v1"
# ponytail: bounded file scan; use a versioned projection cache only if measured latency requires it.
MAX_ROWS = 100_000
MAX_BYTES = 100 * 1024 * 1024
Namespace = Annotated[Text, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]


class LedgerError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status


class Edit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: uuid.UUID
    expected_revision: int = Field(ge=0)
    kind: Literal["scope", "management"]
    namespace: Namespace
    cidrs: list[Annotated[Text, Field(max_length=50)]] = Field(
        default_factory=list, max_length=64
    )
    canonical_ip: Annotated[Text, Field(max_length=45)] | None = None
    collector: Text = Field(default="", max_length=255)
    location: Text = Field(default="", max_length=255)
    evidence: Text = Field(default="", max_length=1000)
    viewpoint: Literal["PUBLIC", "INTERNAL", "UNKNOWN"] | None = None
    scope_status: Literal["CONFIRMED", "UNKNOWN", "CONFLICT", "REVOKED"] | None = None
    followed: bool = False
    excluded: bool = False
    reason: Text = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_kind(self) -> Edit:
        if not self.reason.strip():
            raise ValueError("reason_required")
        if self.kind == "scope":
            if (
                not self.cidrs
                or self.canonical_ip
                or not self.viewpoint
                or not self.scope_status
                or self.followed
                or self.excluded
            ):
                raise ValueError("scope_invalid")
            if self.scope_status == "CONFIRMED" and not all(
                v.strip() for v in (self.collector, self.location, self.evidence)
            ):
                raise ValueError("scope_evidence_required")
            networks = []
            for value in self.cidrs:
                if "%" in value:
                    raise ValueError("scoped_network_invalid")
                network = ipaddress.ip_network(value, strict=True)
                if (
                    isinstance(network, ipaddress.IPv6Network)
                    and network.network_address.ipv4_mapped
                ):
                    network = ipaddress.ip_network(
                        f"{network.network_address.ipv4_mapped}/{network.prefixlen - 96}"
                    )
                networks.append(str(network))
            self.cidrs = sorted(set(networks))
        else:
            if (
                not self.canonical_ip
                or self.cidrs
                or self.scope_status
                or self.viewpoint
                or any((self.collector, self.location, self.evidence))
            ):
                raise ValueError("management_invalid")
            try:
                self.canonical_ip = normalize_ip(self.canonical_ip)
            except IPRecordContractError:
                raise ValueError("management_ip_invalid") from None
        return self


class RevisionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    dataset_id: uuid.UUID
    revision: int
    kind: str
    namespace: str
    canonical_ip: str | None
    cidrs: list[str]
    collector: str
    location: str
    evidence: str
    viewpoint: str | None
    scope_status: str | None
    followed: bool
    excluded: bool
    reason: str
    created_by: uuid.UUID
    created_at: datetime


class Endpoint(BaseModel):
    canonical_ip: str
    family: int
    candidate_id: uuid.UUID | None = None
    namespace: str | None = None
    roles: list[str]
    flow_count: int = 0
    protocols: list[int] = Field(default_factory=list)
    first_seen_utc: str | None = None
    last_seen_utc: str | None = None
    source_record_keys: list[str] = Field(default_factory=list)
    candidate_state: str = "PENDING_SCOPE"
    historical_candidate_state: str = "PENDING_SCOPE"
    management_revision: int = 0
    followed: bool = False
    excluded: bool = False


class Page(BaseModel):
    project_id: uuid.UUID
    dataset_id: uuid.UUID | None = None
    dataset_sha256: str | None = None
    raw_sha256: str | None = None
    contract_version: str = CONTRACT
    state: str
    revision: int = 0
    current_revision: int = 0
    scope: RevisionPublic | None = None
    current_scope: RevisionPublic | None = None
    count: int = 0
    total_endpoints: int = 0
    raw_records: int = 0
    valid_records: int = 0
    isolated_records: int = 0
    data: list[Endpoint] = Field(default_factory=list)
    can_manage: bool = False
    can_confirm_scope: bool = False


class Profile(BaseModel):
    canonical_ip: str
    netflow: Page
    customer: customer_ledger.LedgerPage | None = None
    cloud: cloudatlas_ledger.CloudLedgerPage | None = None
    association: str = "UNKNOWN"
    resource_id: uuid.UUID | None = None
    governance_run_id: uuid.UUID | None = None
    risk_state: Literal["NOT_CONNECTED"] = "NOT_CONNECTED"
    processing_state: str = "NO_RESOURCE_HISTORY"


def _dataset(
    session: Session, project: Project, dataset_id: uuid.UUID
) -> NetFlowDataset:
    row = session.exec(
        select(NetFlowDataset).where(
            NetFlowDataset.id == dataset_id,
            NetFlowDataset.project_id == project.id,
            NetFlowDataset.tenant_id == project.tenant_id,
        )
    ).one_or_none()
    if row is None:
        raise LedgerError("netflow_ledger_dataset_not_found", 404)
    return row


def _verified_bytes(
    session: Session,
    project: Project,
    artifact_id: uuid.UUID,
    expected_hash: str,
    expected_size: int | None = None,
) -> bytes:
    artifact = session.exec(
        select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.project_id == project.id,
            Artifact.tenant_id == project.tenant_id,
            Artifact.sha256 == expected_hash,
        )
    ).one_or_none()
    if (
        artifact is None
        or artifact.byte_size > MAX_BYTES
        or (expected_size is not None and artifact.byte_size != expected_size)
    ):
        raise LedgerError("netflow_ledger_artifact_invalid", 500)
    root = settings.ARTIFACT_ROOT.resolve()
    path = (root / artifact.storage_key).resolve()
    if root not in path.parents:
        raise LedgerError("netflow_ledger_artifact_invalid", 500)
    try:
        with path.open("rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise LedgerError("netflow_ledger_artifact_invalid", 500)
            content = source.read(artifact.byte_size + 1)
    except OSError:
        raise LedgerError("netflow_ledger_artifact_unavailable", 500) from None
    if (
        len(content) != artifact.byte_size
        or hashlib.sha256(content).hexdigest() != expected_hash
    ):
        raise LedgerError("netflow_ledger_artifact_invalid", 500)
    return content


def project_endpoints(
    session: Session, project: Project, dataset: NetFlowDataset
) -> list[Endpoint]:
    if (
        dataset.dataset_contract_version != NETFLOW_DATASET_CONTRACT_VERSION
        or dataset.schema_fingerprint != SCHEMA_FINGERPRINT
    ):
        raise LedgerError("netflow_ledger_contract_unsupported", 500)
    if dataset.activity_valid_record_count > MAX_ROWS:
        raise LedgerError("netflow_ledger_projection_limit", 422)
    if (
        dataset.raw_record_count
        != dataset.activity_valid_record_count + dataset.isolated_record_count
    ):
        raise LedgerError("netflow_ledger_projection_failed", 500)
    _verified_bytes(
        session, project, dataset.raw_artifact_id, dataset.raw_sha256, dataset.byte_size
    )
    content = _verified_bytes(
        session, project, dataset.normalized_artifact_id, dataset.normalized_sha256
    )
    grouped: dict[str, Endpoint] = {}
    previous_key = 0
    count = 0
    try:
        reader = csv.DictReader(
            io.StringIO(content.decode("utf-8"), newline=""), strict=True
        )
        if tuple(reader.fieldnames or ()) != CANONICAL_COLUMNS:
            raise ValueError("schema")
        for row in reader:
            count += 1
            if (
                count > MAX_ROWS
                or set(row) != set(CANONICAL_COLUMNS)
                or any(v is None for v in row.values())
            ):
                raise ValueError("record")
            key = row["source_record_key"]
            key_number = int(key.removeprefix("row:"))
            if (
                key != f"row:{key_number}"
                or not previous_key < key_number <= dataset.raw_record_count
            ):
                raise ValueError("source_key")
            previous_key = key_number
            src, dst = normalize_ip(row["src_ip"]), normalize_ip(row["dst_ip"])
            if src != row["src_ip"] or dst != row["dst_ip"]:
                raise ValueError("noncanonical_ip")
            protocol = _protocol(row["protocol"])
            start, end = _time(row["start_time_utc"]), _time(row["end_time_utc"])
            if start and end and start > end:
                raise ValueError("time_range")
            times = [row[k] for k in ("start_time_utc", "end_time_utc") if row[k]]
            for value in {src, dst}:
                endpoint = grouped.setdefault(
                    value,
                    Endpoint(
                        canonical_ip=value,
                        family=ipaddress.ip_address(value).version,
                        roles=[],
                    ),
                )
                endpoint.flow_count += 1
                endpoint.roles = sorted(
                    set(endpoint.roles)
                    | ({"src"} if value == src else set())
                    | ({"dst"} if value == dst else set())
                )
                if protocol not in endpoint.protocols:
                    endpoint.protocols.append(protocol)
                    endpoint.protocols.sort()
                if len(endpoint.source_record_keys) < 20:
                    endpoint.source_record_keys.append(key)
                if times:
                    endpoint.first_seen_utc = min(
                        [
                            *times,
                            *(
                                [endpoint.first_seen_utc]
                                if endpoint.first_seen_utc
                                else []
                            ),
                        ]
                    )
                    endpoint.last_seen_utc = max(
                        [
                            *times,
                            *(
                                [endpoint.last_seen_utc]
                                if endpoint.last_seen_utc
                                else []
                            ),
                        ]
                    )
        if count != dataset.activity_valid_record_count:
            raise ValueError("count")
    except (
        ValueError,
        UnicodeError,
        csv.Error,
        IPRecordContractError,
        NetFlowActivityContractError,
    ):
        raise LedgerError("netflow_ledger_projection_failed", 500) from None
    return sorted(
        grouped.values(),
        key=lambda row: (row.family, int(ipaddress.ip_address(row.canonical_ip))),
    )


def _events(session: Session, project: Project) -> list[NetFlowLedgerRevision]:
    return list(
        session.exec(
            select(NetFlowLedgerRevision)
            .where(
                NetFlowLedgerRevision.project_id == project.id,
                NetFlowLedgerRevision.tenant_id == project.tenant_id,
            )
            .order_by(col(NetFlowLedgerRevision.revision))
        ).all()
    )


def _scope(
    events: list[NetFlowLedgerRevision], dataset_id: uuid.UUID
) -> NetFlowLedgerRevision | None:
    return next(
        (
            r
            for r in reversed(events)
            if r.dataset_id == dataset_id and r.kind == "scope"
        ),
        None,
    )


def _eligibility(value: str, scope: NetFlowLedgerRevision | None) -> str:
    address = ipaddress.ip_address(value)
    if address.version != 6:
        return "NOT_IPV6"
    if (
        address.is_loopback
        or address.is_unspecified
        or address.is_multicast
        or address.is_link_local
        or address in ipaddress.ip_network("fc00::/7")
    ):
        return "INELIGIBLE_ADDRESS"
    if scope is None or scope.scope_status == "UNKNOWN":
        return "PENDING_SCOPE"
    if scope.scope_status in {"REVOKED", "CONFLICT"}:
        return str(scope.scope_status)
    if not any(address in ipaddress.ip_network(cidr) for cidr in scope.cidrs):
        return "EXTERNAL_PEER"
    if scope.viewpoint != "PUBLIC":
        return (
            "PENDING_SCOPE" if scope.viewpoint == "UNKNOWN" else "VIEWPOINT_UNSUPPORTED"
        )
    return "CANDIDATE"


def read_page(
    session: Session,
    project: Project,
    *,
    dataset_id: uuid.UUID | None = None,
    revision: int | None = None,
    ip: str | None = None,
    candidate: bool = False,
    skip: int = 0,
    limit: int = 25,
) -> Page:
    events = _events(session, project)
    current = events[-1].revision if events else 0
    chosen = current if revision is None else revision
    if (
        chosen < 0
        or chosen > current
        or (chosen and not any(r.revision == chosen for r in events))
    ):
        raise LedgerError("netflow_ledger_revision_not_found", 404)
    canonical = normalize_ip(ip) if ip is not None else None
    selected_id = dataset_id or project.current_netflow_dataset_id
    if selected_id is None:
        if revision:
            raise LedgerError("netflow_ledger_dataset_not_found", 404)
        return Page(
            project_id=project.id,
            state="NO_DATASET",
            revision=chosen,
            current_revision=current,
        )
    dataset = _dataset(session, project, selected_id)
    data = project_endpoints(session, project, dataset)
    history = [r for r in events if r.revision <= chosen]
    scope, current_scope = _scope(history, dataset.id), _scope(events, dataset.id)
    management = {
        (r.namespace, r.canonical_ip): r for r in history if r.kind == "management"
    }
    current_management = {
        (r.namespace, r.canonical_ip): r for r in events if r.kind == "management"
    }
    total = len(data)
    for endpoint in data:
        endpoint.candidate_state = _eligibility(endpoint.canonical_ip, scope)
        if scope and scope.scope_status == "CONFIRMED":
            endpoint.namespace = scope.namespace
            endpoint.candidate_id = uuid.uuid5(
                project.tenant_id,
                f"{project.id}/{scope.namespace}/{endpoint.family}/{endpoint.canonical_ip}",
            )
            record = management.get((scope.namespace, endpoint.canonical_ip))
            if record:
                endpoint.management_revision = record.revision
                endpoint.followed, endpoint.excluded = record.followed, record.excluded
            if endpoint.candidate_state == "CANDIDATE" and endpoint.excluded:
                endpoint.candidate_state = "EXCLUDED"
        endpoint.historical_candidate_state = endpoint.candidate_state
        if endpoint.candidate_state in {"CANDIDATE", "EXCLUDED"}:
            active = _eligibility(endpoint.canonical_ip, current_scope)
            if (
                not current_scope
                or not scope
                or current_scope.namespace != scope.namespace
            ):
                active = "PENDING_SCOPE"
            if active != "CANDIDATE":
                endpoint.candidate_state = active
            elif current_scope:
                current_record = current_management.get(
                    (current_scope.namespace, endpoint.canonical_ip)
                )
                if current_record and current_record.excluded:
                    endpoint.candidate_state = "EXCLUDED"
    if canonical:
        data = [r for r in data if r.canonical_ip == canonical]
    if candidate:
        data = [r for r in data if r.candidate_state == "CANDIDATE"]
    state = "PRESENT"
    if dataset.raw_record_count == 0:
        state = "EMPTY"
    elif not dataset.activity_valid_record_count:
        state = "NO_POSITIVE_EVIDENCE"
    elif canonical and not data:
        state = "NOT_COVERED"
    return Page(
        project_id=project.id,
        dataset_id=dataset.id,
        dataset_sha256=dataset.normalized_sha256,
        raw_sha256=dataset.raw_sha256,
        state=state,
        revision=chosen,
        current_revision=current,
        scope=RevisionPublic.model_validate(scope) if scope else None,
        current_scope=RevisionPublic.model_validate(current_scope)
        if current_scope
        else None,
        count=len(data),
        total_endpoints=total,
        raw_records=dataset.raw_record_count,
        valid_records=dataset.activity_valid_record_count,
        isolated_records=dataset.isolated_record_count,
        data=data[skip : skip + limit],
    )


def save(
    session: Session,
    project: Project,
    *,
    actor_id: uuid.UUID,
    key: str,
    edit: Edit,
    ip_address: str | None,
) -> NetFlowLedgerRevision:
    digest = hashlib.sha256(
        json.dumps(
            edit.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    events = _events(session, project)
    existing = next(
        (r for r in events if r.created_by == actor_id and r.operation_key == key), None
    )
    if existing:
        if existing.request_sha256 != digest:
            raise LedgerError("netflow_ledger_key_conflict")
        return existing
    if edit.expected_revision != (events[-1].revision if events else 0):
        raise LedgerError("netflow_ledger_version_conflict")
    _dataset(session, project, edit.dataset_id)
    if edit.kind == "management":
        scope = _scope(events, edit.dataset_id)
        if (
            not scope
            or scope.scope_status != "CONFIRMED"
            or scope.namespace != edit.namespace
        ):
            raise LedgerError("netflow_ledger_namespace_unconfirmed")
        page = read_page(
            session, project, dataset_id=edit.dataset_id, ip=edit.canonical_ip
        )
        if not page.data:
            raise LedgerError("netflow_ledger_endpoint_not_found", 404)
    record = NetFlowLedgerRevision(
        tenant_id=project.tenant_id,
        project_id=project.id,
        revision=edit.expected_revision + 1,
        **edit.model_dump(exclude={"expected_revision"}),
        created_by=actor_id,
        operation_key=key,
        request_sha256=digest,
    )
    try:
        session.add(record)
        session.add(
            AuditEvent(
                tenant_id=project.tenant_id,
                project_id=project.id,
                actor_subject=str(actor_id),
                actor_type="user",
                action="netflow_ledger." + edit.kind,
                target_type="netflow_ledger_revision",
                target_id=record.id,
                before_data={"revision": edit.expected_revision},
                after_data={
                    "dataset_id": str(edit.dataset_id),
                    "revision": record.revision,
                },
                ip_address=ip_address,
            )
        )
        session.commit()
        session.refresh(record)
    except SQLAlchemyError:
        session.rollback()
        raise LedgerError("netflow_ledger_save_failed", 500) from None
    return record


def require_legacy_run_scope(
    session: Session, project: Project, dataset_id: uuid.UUID | None
) -> None:
    if dataset_id is None:
        return
    scope = _scope(_events(session, project), dataset_id)
    if scope and (scope.scope_status != "CONFIRMED" or scope.namespace != "legacy"):
        raise LedgerError("run_netflow_namespace_not_legacy")


def profile(
    session: Session,
    project: Project,
    *,
    dataset_id: uuid.UUID,
    ip: str,
    revision: int | None = None,
    upload_id: uuid.UUID | None = None,
    customer_revision_id: uuid.UUID | None = None,
    snapshot_id: uuid.UUID | None = None,
    cloud_revision: int | None = None,
) -> Profile:
    canonical = normalize_ip(ip)
    netflow = read_page(
        session, project, dataset_id=dataset_id, revision=revision, ip=canonical
    )
    result = Profile(canonical_ip=canonical, netflow=netflow)
    if upload_id is not None or customer_revision_id is not None:
        if (
            upload_id
            and customer_revision_id
            and customer_ledger._revision(
                session, project, customer_revision_id
            ).upload_id
            != upload_id
        ):
            raise LedgerError("netflow_ledger_customer_revision_mismatch", 404)
        result.customer = customer_ledger.read_page(
            session,
            project,
            upload_id=upload_id,
            revision_id=customer_revision_id,
            original=customer_revision_id is None,
            query="",
            ip=canonical,
            archived=False,
            skip=0,
            limit=100,
            can_write=False,
        )
    if snapshot_id is not None:
        result.cloud = cloudatlas_ledger.read_page(
            session,
            project,
            snapshot_id=snapshot_id,
            revision=cloud_revision,
            ip=canonical,
            skip=0,
            limit=100,
        )
        scope, current = netflow.scope, netflow.current_scope
        if (
            scope
            and current
            and scope.namespace == current.namespace == "legacy"
            and scope.scope_status == current.scope_status == "CONFIRMED"
            and result.cloud.association == "CONFIRMED_LEGACY"
        ):
            # Reuse the existing fixed-Run reader; never attach arbitrary latest history.
            combined = cloudatlas_ledger.profile(
                session,
                project,
                ip=canonical,
                snapshot_id=snapshot_id,
                revision=cloud_revision,
                upload_id=upload_id,
                customer_revision_id=customer_revision_id,
                customer_original=customer_revision_id is None,
                customer_skip=0,
                cloud_skip=0,
                limit=100,
            )
            result.association = combined.association
            result.resource_id, result.governance_run_id = (
                combined.resource_id,
                combined.governance_run_id,
            )
            if combined.resource_id:
                result.processing_state = "FIXED_RUN_HISTORY"
    return result
