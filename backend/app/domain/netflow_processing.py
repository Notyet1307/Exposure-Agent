"""Persisted reservations and one agent-compose execution per fixed NetFlow attempt."""

import hashlib
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain.customer_ledger import Text
from app.domain.models import Artifact, AuditEvent, NetFlowDataset, Project
from app.domain.netflow_common import (
    deny,
    new_output_directory,
    operation_result,
    project_for,
    record_operation,
    request_hash,
    seal_artifacts,
    verify_receipt,
)
from app.domain.netflow_datasets import (
    NETFLOW_DATASET_CONTRACT_VERSION,
    SCHEMA_FINGERPRINT,
)
from app.domain.netflow_models import (
    CONTRACT_VERSION,
    NetFlowAnalysis,
    NetFlowContextRevision,
    NetFlowFeedbackRevision,
)
from app.integrations import netflow_processor as processor
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
    AgentComposeSessionObservation,
)
from app.models import User

SUCCESS = ("SUCCEEDED", "SUCCEEDED_WITH_WARNINGS")
UNFINISHED = ("PENDING", "RUNNING", "UNKNOWN")
Namespace = Annotated[Text, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]


class ObservationPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Text = Field(min_length=1, max_length=128)
    view: Literal["PUBLIC_EDGE", "INTERNAL", "UNKNOWN"]


class Sampling(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["unknown", "unsampled", "sampled"]
    rate: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_rate(self) -> Sampling:
        if (self.mode == "unknown") != (self.rate is None) or (
            self.mode == "unsampled" and self.rate != 1
        ):
            raise ValueError("netflow_context_invalid")
        return self


class ContextCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_parent_id: uuid.UUID | None
    network_namespace: Namespace
    state: Literal["CONFIRMED", "UNKNOWN", "CONFLICT", "REVOKED"]
    collection_scope: Text | None = Field(default=None, max_length=128)
    collection_scope_evidence: Text | None = Field(default=None, max_length=2048)
    endpoint_selection: Literal["declared_source"] = "declared_source"
    source_position_evidence: Text = Field(min_length=1, max_length=2048)
    nat_context: Literal["none", "mapped", "unknown"]
    nat_evidence: Text | None = Field(default=None, max_length=2048)
    observation_point: ObservationPoint
    sampling: Sampling

    @model_validator(mode="after")
    def evidence_required(self) -> ContextCreate:
        if not self.source_position_evidence.strip() or (
            self.nat_context != "unknown" and not (self.nat_evidence or "").strip()
        ):
            raise ValueError("netflow_context_invalid")
        if bool((self.collection_scope or "").strip()) != bool(
            (self.collection_scope_evidence or "").strip()
        ):
            raise ValueError("netflow_context_invalid")
        return self


class AnalysisCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context_revision_id: uuid.UUID
    retry_of_analysis_id: uuid.UUID | None = None


class ImportMetadata(AnalysisCreate):
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_config: dict[str, Any]
    binding_evidence: Text = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def rules_only(self) -> ImportMetadata:
        if (
            not self.binding_evidence.strip()
            or self.original_config.get("mode") != "rules"
            or self.original_config.get("laya") is not None
            or self.original_config.get("allow_rule_fallback") is not False
        ):
            raise ValueError("netflow_context_invalid")
        if set(self.original_config) != set(processor.default_config()):
            raise ValueError("netflow_context_invalid")
        request_hash(self.original_config)
        return self


class ContextPublic(BaseModel):
    contract_version: Literal["netflow-correlation-v1"] = CONTRACT_VERSION
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    context_revision_id: uuid.UUID
    parent_id: uuid.UUID | None
    revision: int
    network_namespace: str
    state: str
    collection_scope: str | None
    collection_scope_evidence: str | None
    current_context_revision_id: uuid.UUID
    current_state: str
    raw_sha256: str
    normalized_sha256: str
    declarations: dict[str, Any]
    created_by: uuid.UUID
    created_at: datetime


class ContextPage(BaseModel):
    contract_version: Literal["netflow-correlation-v1"] = CONTRACT_VERSION
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    data: list[ContextPublic]
    count: int
    skip: int
    limit: int


class AnalysisPublic(BaseModel):
    contract_version: Literal["netflow-correlation-v1"] = CONTRACT_VERSION
    project_id: uuid.UUID
    analysis_id: uuid.UUID
    dataset_id: uuid.UUID
    context_revision_id: uuid.UUID
    network_namespace: str
    # The persistence constraint and Pydantic both enforce the same public enum.
    status: Literal[
        "PENDING",
        "RUNNING",
        "SUCCEEDED",
        "SUCCEEDED_WITH_WARNINGS",
        "FAILED",
        "UNKNOWN",
    ]
    pipeline_complete: bool
    result: dict[str, Any] | None
    quality: dict[str, Any]
    provenance: dict[str, Any]
    context: dict[str, Any]
    observation_window: dict[str, str]
    current_context_state: str
    feedback_revision_id: uuid.UUID | None
    retry_of_analysis_id: uuid.UUID | None
    test_fixture: bool
    error_code: str | None
    can_read_result: bool
    created_by: uuid.UUID
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class AnalysisPage(BaseModel):
    contract_version: Literal["netflow-correlation-v1"] = CONTRACT_VERSION
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    data: list[AnalysisPublic]
    count: int
    skip: int
    limit: int


class CurrentNetFlowScope(BaseModel):
    scope_id: str
    network_namespace: str
    collection_scope: str | None
    label: str
    evidence: str | None


class CurrentNetFlowPublic(BaseModel):
    contract_version: Literal["netflow-correlation-v1"] = CONTRACT_VERSION
    project_id: uuid.UUID
    scope_id: str | None
    scopes: list[CurrentNetFlowScope]
    current: AnalysisPublic | None
    latest_attempt: AnalysisPublic | None


def dataset_for(
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
        deny("netflow_input_not_found", 404)
    if (
        row.dataset_contract_version != NETFLOW_DATASET_CONTRACT_VERSION
        or row.schema_fingerprint != SCHEMA_FINGERPRINT
    ):
        deny("netflow_artifact_schema_invalid", 422)
    return row


def context_for(
    session: Session, project: Project, dataset_id: uuid.UUID, context_id: uuid.UUID
) -> NetFlowContextRevision:
    row = session.exec(
        select(NetFlowContextRevision).where(
            NetFlowContextRevision.id == context_id,
            NetFlowContextRevision.project_id == project.id,
            NetFlowContextRevision.tenant_id == project.tenant_id,
            NetFlowContextRevision.dataset_id == dataset_id,
        )
    ).one_or_none()
    if row is None:
        deny("netflow_input_not_found", 404)
    return row


def current_context(
    session: Session, project: Project, dataset_id: uuid.UUID
) -> NetFlowContextRevision | None:
    return session.exec(
        select(NetFlowContextRevision)
        .where(
            NetFlowContextRevision.project_id == project.id,
            NetFlowContextRevision.tenant_id == project.tenant_id,
            NetFlowContextRevision.dataset_id == dataset_id,
        )
        .order_by(col(NetFlowContextRevision.revision).desc())
    ).first()


def validate_context(
    session: Session,
    project: Project,
    row: NetFlowContextRevision,
    *,
    write: bool = False,
) -> None:
    current = current_context(session, project, row.dataset_id)
    if (
        current is None
        or current.state != "CONFIRMED"
        or row.state != "CONFIRMED"
        or current.network_namespace != row.network_namespace
        or (write and current.id != row.id)
    ):
        deny("netflow_context_revoked")
    dataset = dataset_for(session, project, row.dataset_id)
    if (
        row.raw_sha256 != dataset.raw_sha256
        or row.normalized_sha256 != dataset.normalized_sha256
    ):
        deny("netflow_artifact_integrity_failed")


def context_public(
    session: Session, project: Project, row: NetFlowContextRevision
) -> ContextPublic:
    current = current_context(session, project, row.dataset_id)
    assert current is not None
    return ContextPublic(
        project_id=project.id,
        dataset_id=row.dataset_id,
        context_revision_id=row.id,
        parent_id=row.parent_id,
        revision=row.revision,
        network_namespace=row.network_namespace,
        state=row.state,
        collection_scope=row.collection_scope,
        collection_scope_evidence=row.collection_scope_evidence,
        current_context_revision_id=current.id,
        current_state=current.state,
        raw_sha256=row.raw_sha256,
        normalized_sha256=row.normalized_sha256,
        declarations=row.payload,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def save_context(
    session: Session,
    project: Project,
    actor: User,
    dataset_id: uuid.UUID,
    request: ContextCreate,
    key: str,
) -> NetFlowContextRevision:
    if not actor.is_superuser:
        deny("netflow_context_admin_required", 403)
    payload = request.model_dump(mode="json")
    operation = f"context:{dataset_id}"
    existing = operation_result(session, project, actor.id, operation, key, payload)
    if existing:
        return context_for(session, project, dataset_id, existing)
    dataset = dataset_for(session, project, dataset_id)
    parent = current_context(session, project, dataset_id)
    if request.expected_parent_id != (parent.id if parent else None):
        deny("netflow_revision_conflict")
    if settings.NETFLOW_ALLOW_TEST_FIXTURES and settings.ENVIRONMENT == "production":
        deny("netflow_test_fixture_forbidden", 422)
    component_context = {
        "tenant_id": str(project.tenant_id),
        "project_id": str(project.id),
        "dataset_id": str(dataset.id),
        "network_namespace": request.network_namespace,
        "scope_confirmation": request.state.lower()
        if request.state != "REVOKED"
        else "unknown",
        "managed_cidrs": [],
        "endpoint_selection": "declared_source",
        "scope_evidence": request.source_position_evidence,
        "observation_point": request.observation_point.model_dump()
        | {"nat_context": request.nat_context},
        "sampling": request.sampling.model_dump(),
        "input_timezone": "UTC",
        "test_fixture": settings.NETFLOW_ALLOW_TEST_FIXTURES,
        "context_contract": "netflow-context-v1",
        "fixture_notice": "Isolated synthetic integration material; not production evidence."
        if settings.NETFLOW_ALLOW_TEST_FIXTURES
        else "",
    }
    row = NetFlowContextRevision(
        tenant_id=project.tenant_id,
        project_id=project.id,
        dataset_id=dataset.id,
        parent_id=parent.id if parent else None,
        revision=parent.revision + 1 if parent else 1,
        network_namespace=request.network_namespace,
        state=request.state,
        collection_scope=request.collection_scope.strip()
        if request.collection_scope
        else None,
        collection_scope_evidence=request.collection_scope_evidence.strip()
        if request.collection_scope_evidence
        else None,
        raw_sha256=dataset.raw_sha256,
        normalized_sha256=dataset.normalized_sha256,
        payload=payload
        | {
            "component_context": component_context,
            "original_time_basis": "netflow-dataset-v1:UTC+08:00",
            "business_time_qualification": "UNKNOWN",
        },
        created_by=actor.id,
        operation_key=key,
        request_sha256=request_hash(payload),
    )
    session.add(row)
    record_operation(session, project, actor.id, operation, key, payload, row.id)
    session.commit()
    session.refresh(row)
    return row


def analysis_for(
    session: Session, project: Project, analysis_id: uuid.UUID
) -> NetFlowAnalysis:
    row = session.exec(
        select(NetFlowAnalysis).where(
            NetFlowAnalysis.id == analysis_id,
            NetFlowAnalysis.project_id == project.id,
            NetFlowAnalysis.tenant_id == project.tenant_id,
        )
    ).one_or_none()
    if row is None:
        deny("netflow_analysis_not_found", 404)
    return row


def _input_path(
    session: Session,
    project: Project,
    artifact_id: uuid.UUID,
    digest: str,
    expected_size: int | None = None,
) -> Path:
    artifact = session.exec(
        select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.project_id == project.id,
            Artifact.tenant_id == project.tenant_id,
        )
    ).one_or_none()
    if (
        artifact is None
        or artifact.sha256 != digest
        or (expected_size is not None and artifact.byte_size != expected_size)
    ):
        deny("netflow_artifact_integrity_failed")
    path = Path(artifact.storage_key)
    receipt = {
        "root": path.parent.as_posix(),
        "files": {
            path.name: {
                "artifact_id": str(artifact.id),
                "sha256": digest,
                "byte_size": artifact.byte_size,
            }
        },
    }
    return verify_receipt(session, project, receipt) / path.name


def _inputs(
    session: Session, project: Project, row: NetFlowAnalysis
) -> tuple[Path, Path]:
    dataset = dataset_for(session, project, row.dataset_id)
    fixed = row.identity["dataset"]
    if (
        str(dataset.id),
        dataset.raw_sha256,
        dataset.normalized_sha256,
        dataset.schema_fingerprint,
        dataset.dataset_contract_version,
    ) != (
        fixed["id"],
        fixed["raw_sha256"],
        fixed["normalized_sha256"],
        fixed["schema_fingerprint"],
        fixed["contract_version"],
    ):
        deny("netflow_artifact_integrity_failed")
    if (
        dataset.byte_size > settings.NETFLOW_MAX_BYTES
        or dataset.activity_valid_record_count > 100000
    ):
        deny("netflow_processing_limit", 413)
    return (
        _input_path(
            session,
            project,
            dataset.raw_artifact_id,
            dataset.raw_sha256,
            dataset.byte_size,
        ),
        _input_path(
            session, project, dataset.normalized_artifact_id, dataset.normalized_sha256
        ),
    )


def _bundle_binding(
    row: NetFlowAnalysis,
    context: NetFlowContextRevision,
    bundle: processor.ProcessorBundle,
) -> None:
    identity, manifest = row.identity, bundle.manifest
    config = identity["config"]
    declared = context.payload["component_context"]
    input_hash = identity["dataset"][
        "normalized_sha256" if config["input_profile"] == "exposure" else "raw_sha256"
    ]
    if (
        request_hash(identity) != row.processing_identity_sha256
        or identity["component"] != processor.COMPONENT_IDENTITY
        or identity["context_revision_id"] != str(context.id)
        or identity["context_sha256"] != request_hash(declared)
        or identity["config_sha256"] != request_hash(config)
        or identity["runner_build_version"] != row.runner_build_version
        or manifest["config_sha256"] != identity["config_sha256"]
        or manifest["input_profile"] != config["input_profile"]
        or manifest["input_sha256"] != input_hash
        or manifest["test_fixture"] != row.test_fixture
    ):
        deny("netflow_artifact_integrity_failed")
    if row.request["operation"] == "import":
        mapping = {"tenant_id", "project_id", "dataset_id", "input_timezone"}
        source = manifest["analysis_context"]
        if {k: v for k, v in source.items() if k not in mapping} != {
            k: v for k, v in declared.items() if k not in mapping
        } or hashlib.sha256(
            (bundle.root / "analysis/manifest.json").read_bytes()
        ).hexdigest() != identity["source_manifest_sha256"]:
            deny("netflow_artifact_integrity_failed")
    elif (
        manifest["analysis_context"] != declared
        or manifest["context_sha256"] != identity["context_sha256"]
    ):
        deny("netflow_artifact_integrity_failed")


def analysis_material(
    session: Session, project: Project, analysis_id: uuid.UUID
) -> tuple[NetFlowAnalysis, processor.ProcessorBundle]:
    row = analysis_for(session, project, analysis_id)
    context = context_for(session, project, row.dataset_id, row.context_revision_id)
    validate_context(session, project, context)
    if (
        row.status not in SUCCESS
        or row.result is None
        or row.initial_feedback_revision_id is None
    ):
        deny("netflow_analysis_not_ready")
    _inputs(session, project, row)
    try:
        root = verify_receipt(session, project, row.result["artifacts"])
        bundle = processor.load_bundle(
            root,
            namespace=row.network_namespace,
            allow_test=settings.NETFLOW_ALLOW_TEST_FIXTURES,
        )
        _bundle_binding(row, context, bundle)
        if (
            bundle.manifest != row.result["manifest"]
            or bundle.review_summary != row.result["review_summary"]
        ):
            deny("netflow_artifact_integrity_failed")
    except processor.ProcessorError as error:
        deny(error.code, error.status)
    initial = session.exec(
        select(NetFlowFeedbackRevision).where(
            NetFlowFeedbackRevision.id == row.initial_feedback_revision_id,
            NetFlowFeedbackRevision.analysis_id == row.id,
            NetFlowFeedbackRevision.project_id == project.id,
            NetFlowFeedbackRevision.tenant_id == project.tenant_id,
            NetFlowFeedbackRevision.system_generated == True,  # noqa: E712
        )
    ).one_or_none()
    if (
        initial is None
        or initial.revision != 1
        or initial.parent_id is not None
        or verify_receipt(session, project, initial.artifact_manifest)
        != root / "initial-feedback"
    ):
        deny("netflow_artifact_integrity_failed")
    return row, bundle


def analysis_public(
    session: Session,
    project: Project,
    row: NetFlowAnalysis,
    *,
    include_result: bool = True,
) -> AnalysisPublic:
    context = context_for(session, project, row.dataset_id, row.context_revision_id)
    current = current_context(session, project, row.dataset_id)
    readable = (
        row.status in SUCCESS
        and current is not None
        and current.state == "CONFIRMED"
        and current.network_namespace == row.network_namespace
    )
    result: dict[str, Any] | None = None
    if include_result and row.status in SUCCESS:
        _, bundle = analysis_material(session, project, row.id)
        assert row.result is not None
        result = {
            "counts": bundle.manifest["counts"],
            "input_state": bundle.manifest["input_state"],
            "review_task_count": len(bundle.tasks),
            "coverage_limitations": bundle.manifest["coverage_limitations"],
            "component_run_id": bundle.manifest["run_id"],
            "artifacts": [
                {"name": name, **entry}
                for name, entry in row.result["artifacts"]["files"].items()
            ],
        }
    return AnalysisPublic(
        project_id=project.id,
        analysis_id=row.id,
        dataset_id=row.dataset_id,
        context_revision_id=row.context_revision_id,
        network_namespace=row.network_namespace,
        status=cast(
            Literal[
                "PENDING",
                "RUNNING",
                "SUCCEEDED",
                "SUCCEEDED_WITH_WARNINGS",
                "FAILED",
                "UNKNOWN",
            ],
            row.status,
        ),
        pipeline_complete=row.status in SUCCESS,
        result=result,
        quality=row.quality,
        provenance=row.identity,
        context=context.payload,
        observation_window={
            "state": "NOT_PROVIDED",
            "reason": "The sealed processing result has no verified observation window.",
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


def current_netflow(
    session: Session,
    project: Project,
    collection_scope: str | None = None,
) -> CurrentNetFlowPublic:
    """Resolve one confirmed scope; legacy datasets remain separate scopes."""
    candidates = session.exec(
        select(NetFlowContextRevision).where(
            NetFlowContextRevision.project_id == project.id,
            NetFlowContextRevision.tenant_id == project.tenant_id,
            NetFlowContextRevision.state == "CONFIRMED",
        )
    ).all()
    contexts = [
        row
        for row in candidates
        if (current := current_context(session, project, row.dataset_id)) is not None
        and current.id == row.id
    ]
    def scope_id(row: NetFlowContextRevision) -> str:
        return request_hash(
            [
                row.network_namespace,
                "declared" if row.collection_scope is not None else "dataset",
                row.collection_scope or str(row.dataset_id),
            ]
        )

    scopes = {scope_id(row): row for row in contexts}
    chosen = collection_scope
    if chosen is None and project.current_netflow_dataset_id is not None:
        selected = next(
            (row for row in contexts if row.dataset_id == project.current_netflow_dataset_id),
            None,
        )
        if selected is not None:
            chosen = scope_id(selected)
    if chosen is None and len(scopes) == 1:
        chosen = next(iter(scopes))
    if chosen is None:
        return CurrentNetFlowPublic(
            project_id=project.id,
            scope_id=None,
            scopes=[
                CurrentNetFlowScope(
                    scope_id=name,
                    network_namespace=row.network_namespace,
                    collection_scope=row.collection_scope,
                    label=row.collection_scope or f"Dataset {row.dataset_id}",
                    evidence=row.collection_scope_evidence,
                )
                for name, row in sorted(scopes.items())
            ],
            current=None,
            latest_attempt=None,
        )
    selected = scopes.get(chosen)
    if selected is None:
        deny("netflow_input_not_found", 404)
    member_dataset_ids = {
        row.dataset_id
        for row in contexts
        if row.network_namespace == selected.network_namespace
        and row.collection_scope == selected.collection_scope
    }
    matching_context_ids = [
        row.id
        for row in candidates
        if row.dataset_id in member_dataset_ids
        and row.network_namespace == selected.network_namespace
        and (
            row.collection_scope == selected.collection_scope
            if selected.collection_scope is not None
            else row.dataset_id == selected.dataset_id
        )
    ]
    rows = session.exec(
        select(NetFlowAnalysis)
        .where(
            NetFlowAnalysis.project_id == project.id,
            NetFlowAnalysis.tenant_id == project.tenant_id,
            col(NetFlowAnalysis.context_revision_id).in_(matching_context_ids),
            NetFlowAnalysis.network_namespace == selected.network_namespace,
        )
        .order_by(col(NetFlowAnalysis.created_at).desc(), col(NetFlowAnalysis.id).desc())
    ).all()
    latest = rows[0] if rows else None
    current: AnalysisPublic | None = None
    for row in sorted(
        (row for row in rows if row.status in SUCCESS and row.completed_at is not None),
        key=lambda row: (row.completed_at, row.id),
        reverse=True,
    ):
        public = analysis_public(session, project, row)
        if public.can_read_result:
            current = public
            break
    return CurrentNetFlowPublic(
        project_id=project.id,
        scope_id=chosen,
        scopes=[
            CurrentNetFlowScope(
                scope_id=name,
                network_namespace=row.network_namespace,
                collection_scope=row.collection_scope,
                label=row.collection_scope or f"Dataset {row.dataset_id}",
                evidence=row.collection_scope_evidence,
            )
            for name, row in sorted(scopes.items())
        ],
        current=current,
        latest_attempt=analysis_public(session, project, latest, include_result=False)
        if latest is not None
        else None,
    )


def _client(row: NetFlowAnalysis) -> AgentComposeClient:
    client = AgentComposeClient()
    client.project_id = row.agent_project_id
    return client


def session_observation(
    row: NetFlowAnalysis,
) -> tuple[str | None, AgentComposeSessionObservation]:
    try:
        client = _client(row)
        run = client.get_run(row.agent_run_id)
        if (
            run is None
            or run.project_id != row.agent_project_id
            or run.agent_name != "netflow-processor"
            or not run.session_id
            or (row.session_id is not None and row.session_id != run.session_id)
        ):
            return row.session_id, AgentComposeSessionObservation.UNKNOWN
        observed = client.get_session(run.session_id)
        if observed is None:
            return run.session_id, AgentComposeSessionObservation.UNKNOWN
        return run.session_id, observed.observation
    except AgentComposeBoundaryError:
        return row.session_id, AgentComposeSessionObservation.UNKNOWN


def reserve_analysis(
    session: Session,
    project: Project,
    actor: User,
    dataset_id: uuid.UUID,
    request: AnalysisCreate | ImportMetadata,
    key: str,
    *,
    import_directory: Path | None = None,
    import_sha256: str | None = None,
) -> tuple[NetFlowAnalysis, bool]:
    imported = isinstance(request, ImportMetadata)
    if imported and not actor.is_superuser:
        deny("netflow_context_admin_required", 403)
    operation = f"{'import' if imported else 'analysis'}:{dataset_id}"
    payload = request.model_dump(mode="json")
    if imported:
        if import_sha256 is None or not re.fullmatch(r"[0-9a-f]{64}", import_sha256):
            deny("netflow_import_incomplete", 422)
        payload["archive_sha256"] = import_sha256
    existing = operation_result(session, project, actor.id, operation, key, payload)
    if existing:
        return analysis_for(session, project, existing), False
    dataset = dataset_for(session, project, dataset_id)
    context = context_for(session, project, dataset.id, request.context_revision_id)
    validate_context(session, project, context, write=True)
    config = (
        request.original_config
        if isinstance(request, ImportMetadata)
        else processor.default_config()
    )
    identity = {
        "dataset": {
            "id": str(dataset.id),
            "raw_sha256": dataset.raw_sha256,
            "normalized_sha256": dataset.normalized_sha256,
            "contract_version": dataset.dataset_contract_version,
            "schema_fingerprint": dataset.schema_fingerprint,
        },
        "context_revision_id": str(context.id),
        "context_sha256": request_hash(context.payload["component_context"]),
        "config": config,
        "config_sha256": request_hash(config),
        "component": processor.COMPONENT_IDENTITY,
        "runner_build_version": settings.governance_runner_build_version,
        "source_manifest_sha256": request.source_manifest_sha256
        if isinstance(request, ImportMetadata)
        else None,
    }
    fingerprint = request_hash(identity)
    if request.retry_of_analysis_id is not None:
        parent = analysis_for(session, project, request.retry_of_analysis_id)
        if (
            parent.processing_identity_sha256 != fingerprint
            or parent.status != "FAILED"
        ):
            deny("netflow_retry_not_allowed")
        _, observed = session_observation(parent)
        if observed != AgentComposeSessionObservation.TERMINAL:
            deny("netflow_retry_not_allowed")
        parent.terminal_confirmed = True
        session.add(parent)
        duplicate = session.exec(
            select(NetFlowAnalysis).where(
                NetFlowAnalysis.retry_of_analysis_id == parent.id,
                NetFlowAnalysis.project_id == project.id,
            )
        ).one_or_none()
    else:
        duplicate = session.exec(
            select(NetFlowAnalysis).where(
                NetFlowAnalysis.project_id == project.id,
                NetFlowAnalysis.processing_identity_sha256 == fingerprint,
                col(NetFlowAnalysis.retry_of_analysis_id).is_(None),
            )
        ).one_or_none()
    if duplicate is not None:
        record_operation(
            session, project, actor.id, operation, key, payload, duplicate.id
        )
        session.commit()
        return duplicate, False
    analysis_id = uuid.uuid4()
    output = new_output_directory(project.id, "analyses")
    persisted_request = payload | {
        "operation": "import" if imported else "process",
        "output_key": output.relative_to(settings.ARTIFACT_ROOT.resolve()).as_posix(),
    }
    if imported:
        if import_directory is None:
            deny("netflow_import_incomplete", 422)
        persisted_request["import_artifacts"] = seal_artifacts(
            session, project, import_directory, ["source.zip"]
        )
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
        request=persisted_request,
        quality={
            "raw_record_count": dataset.raw_record_count,
            "activity_valid_record_count": dataset.activity_valid_record_count,
            "isolated_record_count": dataset.isolated_record_count,
            "duplicate_record_count": dataset.duplicate_record_count,
            "duplicate_group_count": dataset.duplicate_group_count,
            "warnings": dataset.warnings,
        },
        test_fixture=context.payload["component_context"]["test_fixture"],
        created_by=actor.id,
        retry_of_analysis_id=request.retry_of_analysis_id,
        agent_run_id=client.expected_netflow_analysis_run_id(str(analysis_id)),
        agent_project_id=client.project_id,
        runner_build_version=settings.governance_runner_build_version,
    )
    _inputs(session, project, row)
    session.add(row)
    record_operation(session, project, actor.id, operation, key, payload, row.id)
    session.commit()  # A lost StartAgentRun response must never erase its reservation.
    session.refresh(row)
    return row, True


def _locked(
    session: Session, analysis_id: uuid.UUID
) -> tuple[Project, NetFlowAnalysis]:
    identity = session.exec(
        select(NetFlowAnalysis.project_id, NetFlowAnalysis.tenant_id).where(
            NetFlowAnalysis.id == analysis_id
        )
    ).one_or_none()
    if identity is None:
        deny("netflow_analysis_not_found", 404)
    project_id, tenant_id = identity
    project = session.exec(
        select(Project)
        .where(Project.id == project_id, Project.tenant_id == tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    row = session.exec(
        select(NetFlowAnalysis)
        .where(
            NetFlowAnalysis.id == analysis_id, NetFlowAnalysis.project_id == project.id
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    return project, row


def launch_analysis(session: Session, row: NetFlowAnalysis) -> NetFlowAnalysis:
    analysis_id = row.id
    try:
        started = _client(row).start_netflow_analysis(
            client_request_id=str(row.id), analysis_id=str(row.id)
        )
        if started.run_id != row.agent_run_id:
            raise AgentComposeBoundaryError("agent_compose_response_contract_failed")
        session_id = started.session_id
    except AgentComposeBoundaryError:
        session_id = None
    session.rollback()
    _, current = _locked(session, analysis_id)
    if current.status in UNFINISHED and current.started_at is None:
        if session_id and (
            current.session_id is None or current.session_id == session_id
        ):
            current.session_id = session_id
        else:
            current.status = "UNKNOWN"
            current.error_code = "netflow_execution_unavailable"
        session.add(current)
        session.commit()
    return current


def _actor_context(
    session: Session, project: Project, row: NetFlowAnalysis
) -> NetFlowContextRevision:
    actor = session.get(User, row.created_by)
    if actor is None:
        deny("netflow_write_forbidden", 403)
    project_for(
        session,
        actor,
        project.id,
        write=True,
        admin=row.request["operation"] == "import",
    )
    context = context_for(session, project, row.dataset_id, row.context_revision_id)
    validate_context(session, project, context, write=True)
    if (
        row.runner_build_version != settings.governance_runner_build_version
        or row.identity["component"] != processor.COMPONENT_IDENTITY
        or row.identity["context_sha256"]
        != request_hash(context.payload["component_context"])
        or row.identity["config_sha256"] != request_hash(row.identity["config"])
    ):
        deny("netflow_component_version_unsupported", 422)
    if row.test_fixture and (
        not settings.NETFLOW_ALLOW_TEST_FIXTURES or settings.ENVIRONMENT == "production"
    ):
        deny("netflow_test_fixture_forbidden", 422)
    return context


def _output(row: NetFlowAnalysis) -> Path:
    key = row.request.get("output_key")
    expected = f"netflow-processing/{row.project_id}/analyses/"
    if (
        not isinstance(key, str)
        or not key.startswith(expected)
        or not re.fullmatch(r"[0-9a-f-]{36}", key[len(expected) :])
    ):
        deny("netflow_artifact_integrity_failed")
    root = settings.ARTIFACT_ROOT.resolve()
    result = root / key
    if result.resolve().parent != (root / expected).resolve():
        deny("netflow_artifact_integrity_failed")
    return result


def _publish(
    session: Session, project: Project, row: NetFlowAnalysis, *, terminal: bool
) -> None:
    context = _actor_context(session, project, row)
    _inputs(session, project, row)
    session_id, observed = session_observation(row)
    if session_id != row.session_id or observed != (
        AgentComposeSessionObservation.TERMINAL
        if terminal
        else AgentComposeSessionObservation.RUNNING
    ):
        deny("netflow_execution_unavailable", 503)
    bundle = processor.load_bundle(
        _output(row),
        namespace=row.network_namespace,
        allow_test=settings.NETFLOW_ALLOW_TEST_FIXTURES,
    )
    _bundle_binding(row, context, bundle)
    initial = processor.load_feedback(
        bundle.root / "initial-feedback",
        namespace=row.network_namespace,
        allow_test=settings.NETFLOW_ALLOW_TEST_FIXTURES,
    )
    first = NetFlowFeedbackRevision(
        tenant_id=project.tenant_id,
        project_id=project.id,
        analysis_id=row.id,
        revision=1,
        system_generated=True,
        artifact_manifest=seal_artifacts(session, project, initial.root, initial.files),
    )
    session.add(first)
    if (bundle.root / "imported-feedback").is_dir():
        imported = processor.load_feedback(
            bundle.root / "imported-feedback",
            namespace=row.network_namespace,
            allow_test=settings.NETFLOW_ALLOW_TEST_FIXTURES,
        )
        imported_revision = NetFlowFeedbackRevision(
            tenant_id=project.tenant_id,
            project_id=project.id,
            analysis_id=row.id,
            parent_id=first.id,
            revision=2,
            created_by=row.created_by,
            artifact_manifest=seal_artifacts(
                session, project, imported.root, imported.files
            ),
        )
        imported_revision.provider_claim = {
            "origin": "imported",
            "response_authors": {
                response["task"]["task_id"]: {
                    "actor_id": str(row.created_by),
                    "submitted_at": imported_revision.created_at.isoformat(),
                    "feedback_revision_id": str(imported_revision.id),
                }
                for response in imported.submission["responses"]
            },
        }
        session.add(imported_revision)
    row.result = {
        "artifacts": seal_artifacts(session, project, bundle.root, bundle.files),
        "manifest": bundle.manifest,
        "review_summary": bundle.review_summary,
    }
    row.initial_feedback_revision_id = first.id
    row.status = (
        "SUCCEEDED_WITH_WARNINGS"
        if bundle.manifest["status"] == "success_with_warnings"
        or row.quality["isolated_record_count"]
        else "SUCCEEDED"
    )
    row.error_code = None
    row.completed_at = get_datetime_utc()
    row.terminal_confirmed = terminal
    session.add(row)
    session.add(
        AuditEvent(
            tenant_id=project.tenant_id,
            project_id=project.id,
            actor_subject=str(row.created_by),
            actor_type="user",
            action="netflow.analysis_published",
            target_type="netflow_analysis",
            target_id=row.id,
            after_data={
                "status": row.status,
                "identity_sha256": row.processing_identity_sha256,
                "manifest_sha256": request_hash(bundle.manifest),
                "initial_feedback_revision_id": str(first.id),
            },
        )
    )
    session.commit()


def _failed(
    session: Session,
    analysis_id: uuid.UUID,
    run_id: str,
    session_id: str,
    code: str,
    *,
    unknown: bool = False,
    terminal: bool = False,
) -> None:
    session.rollback()
    project, row = _locked(session, analysis_id)
    if (
        row.status not in UNFINISHED
        or row.agent_run_id != run_id
        or row.session_id != session_id
    ):
        return
    row.status = "UNKNOWN" if unknown else "FAILED"
    row.error_code = code
    row.completed_at = None if unknown else get_datetime_utc()
    row.terminal_confirmed = terminal
    session.add(row)
    session.add(
        AuditEvent(
            tenant_id=project.tenant_id,
            project_id=project.id,
            actor_subject=str(row.created_by),
            actor_type="user",
            action="netflow.analysis_failed",
            target_type="netflow_analysis",
            target_id=row.id,
            after_data={
                "status": row.status,
                "error_code": code,
                "identity_sha256": row.processing_identity_sha256,
            },
        )
    )
    session.commit()


def execute_analysis(
    session: Session, analysis_id: uuid.UUID, run_id: str, session_id: str
) -> None:
    project, row = _locked(session, analysis_id)
    if row.agent_run_id != run_id or (
        row.session_id is not None and row.session_id != session_id
    ):
        deny("netflow_execution_unavailable", 503)
    if row.status not in UNFINISHED or row.started_at is not None:
        return  # Never re-execute an interrupted/finished attempt in the same Session.
    observed_id, observation = session_observation(row)
    if (
        observed_id != session_id
        or observation != AgentComposeSessionObservation.RUNNING
    ):
        deny("netflow_execution_unavailable", 503)
    row.session_id = session_id
    row.started_at = get_datetime_utc()
    row.status, row.error_code = "RUNNING", None
    session.add(row)
    session.commit()
    try:
        project, row = _locked(session, analysis_id)
        context = _actor_context(session, project, row)
        raw_path, canonical_path = _inputs(session, project, row)
        if (
            row.quality["raw_record_count"] > 0
            and row.quality["activity_valid_record_count"] == 0
        ):
            deny("netflow_no_valid_records", 422)
        output = _output(row)
        identity = row.identity
        original = row.request
        target_context = context.payload["component_context"]
        # Immutable bytes and identities are captured under Project -> Analysis.
        # Do not hold a database transaction during bounded CPU/file processing.
        session.commit()
        if original["operation"] == "import":
            project, row = _locked(session, analysis_id)
            import_path = (
                verify_receipt(session, project, original["import_artifacts"])
                / "source.zip"
            )
            session.commit()
            processor.import_result(
                import_path,
                raw_path=raw_path,
                canonical_path=canonical_path,
                target_context=target_context,
                config=identity["config"],
                source_manifest_sha256=original["source_manifest_sha256"],
                output_dir=output,
                max_compressed_bytes=settings.NETFLOW_MAX_BYTES,
                allow_test=settings.NETFLOW_ALLOW_TEST_FIXTURES,
            )
        else:
            processor.process(
                canonical_path,
                context=target_context,
                config=identity["config"],
                output_dir=output,
                allow_test=settings.NETFLOW_ALLOW_TEST_FIXTURES,
            )
        project, row = _locked(session, analysis_id)
        if (
            row.status not in UNFINISHED
            or row.agent_run_id != run_id
            or row.session_id != session_id
        ):
            return
        _publish(session, project, row, terminal=False)
    except processor.ProcessorError as error:
        _failed(session, analysis_id, run_id, session_id, error.code)
    except HTTPException as error:
        code = (
            error.detail.get("code", "netflow_execution_unavailable")
            if isinstance(error.detail, dict)
            else "netflow_execution_unavailable"
        )
        _failed(
            session,
            analysis_id,
            run_id,
            session_id,
            code,
            unknown=error.status_code == 503,
        )
    except SQLAlchemyError, OSError:
        _failed(
            session,
            analysis_id,
            run_id,
            session_id,
            "netflow_execution_unavailable",
            unknown=True,
        )


def reconcile_analysis(
    session: Session, project: Project, actor: User, analysis_id: uuid.UUID, key: str
) -> NetFlowAnalysis:
    payload = {"analysis_id": str(analysis_id)}
    operation = f"reconcile:{analysis_id}"
    actor_id = actor.id
    analysis_for(session, project, analysis_id)
    project, row = _locked(session, analysis_id)
    if (
        operation_result(session, project, actor_id, operation, key, payload)
        is not None
    ):
        return row
    run_id = row.agent_run_id
    session_id, observed = session_observation(row)
    if session_id and row.session_id is None:
        row.session_id = session_id
        session.add(row)
        session.commit()  # Retain the authoritative Session even if publication rolls back.
        project, row = _locked(session, analysis_id)
    if row.status in SUCCESS:
        analysis_material(session, project, row.id)
    elif observed == AgentComposeSessionObservation.TERMINAL:
        assert session_id is not None
        if row.status == "FAILED":
            row.terminal_confirmed = True
            session.add(row)
        else:
            try:
                _publish(session, project, row, terminal=True)
            except processor.ProcessorError as error:
                _failed(
                    session, analysis_id, run_id, session_id, error.code, terminal=True
                )
            except HTTPException as error:
                code = (
                    error.detail.get("code", "netflow_execution_unavailable")
                    if isinstance(error.detail, dict)
                    else "netflow_execution_unavailable"
                )
                _failed(
                    session,
                    analysis_id,
                    run_id,
                    session_id,
                    code,
                    unknown=error.status_code == 503,
                    terminal=True,
                )
            except SQLAlchemyError, OSError:
                _failed(
                    session,
                    analysis_id,
                    run_id,
                    session_id,
                    "netflow_execution_unavailable",
                    unknown=True,
                    terminal=True,
                )
            project, row = _locked(session, analysis_id)
    elif row.status != "FAILED":
        row.status = (
            "RUNNING"
            if observed == AgentComposeSessionObservation.RUNNING and row.started_at
            else "UNKNOWN"
        )
        row.error_code = (
            None if row.status == "RUNNING" else "netflow_execution_unavailable"
        )
        session.add(row)
    # Publication releases its transaction. A concurrent same-key recovery may
    # already have recorded this operation; keep the single original receipt.
    if operation_result(session, project, actor_id, operation, key, payload) is None:
        record_operation(session, project, actor_id, operation, key, payload, row.id)
    session.commit()
    session.refresh(row)
    return row
