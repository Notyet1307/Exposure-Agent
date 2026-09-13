"""Read-only, fixed-scope AI investigations; PostgreSQL owns every execution identity."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.api.project_authorization import get_authorized_project
from app.core.config import settings
from app.core.db import engine
from app.core.time import get_datetime_utc
from app.domain import model_connections
from app.domain.ip_source_comparison import IPSourceComparisonError
from app.domain.lineage import read_governance_run_lineage
from app.domain.model_qualification import (
    ModelBinding,
    current_model_is_qualified,
    model_binding,
)
from app.domain.models import (
    AiInvestigation,
    AuditEvent,
    LineageComparisonNodePublic,
    LineageFindingNodePublic,
    LineageSnapshotNodePublic,
    LineageSourceNodePublic,
    Project,
    ProjectRole,
)
from app.domain.report_comparison_evidence import ReportComparisonEvidenceError
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
    AgentComposeDraftNamespace,
)
from app.models import User

Text = Annotated[
    str,
    StringConstraints(
        strict=True, strip_whitespace=True, min_length=1, max_length=2000
    ),
]
Citation = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=255)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class InvestigationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_id: uuid.UUID
    run_id: uuid.UUID
    finding_id: uuid.UUID | None = None


class InvestigationFollowupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: Text


class InvestigationToolRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    tool_name: Literal[
        "read_asset_facts", "read_asset_history", "read_cloudatlas_asset"
    ]
    queried_at: datetime
    completed_at: datetime | None
    status: Literal["RUNNING", "SUCCEEDED", "FAILED"]
    failure_code: str | None
    project_id: uuid.UUID
    resource_id: uuid.UUID
    run_id: uuid.UUID
    items: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)


class InvestigationFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Text
    citation_ids: list[Citation] = Field(min_length=1, max_length=8)


class InvestigationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facts: list[InvestigationFact] = Field(min_length=1, max_length=16)
    explanations: list[Text] = Field(max_length=16)
    gaps: list[Text] = Field(max_length=16)
    next_steps: list[Text] = Field(max_length=16)


class InvestigationMaterialItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    citation_id: Citation
    fact: Annotated[
        LineageSourceNodePublic
        | LineageSnapshotNodePublic
        | LineageComparisonNodePublic
        | LineageFindingNodePublic,
        Field(discriminator="kind"),
    ]


class InvestigationMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["ai-investigation-material/v1"] = "ai-investigation-material/v1"
    scope: InvestigationRequest
    project_id: uuid.UUID
    published_at: datetime
    report_id: uuid.UUID
    report_contract_version: Literal[
        "deterministic-report-v1", "deterministic-report-v2"
    ]
    truncated: bool
    items: list[InvestigationMaterialItem] = Field(min_length=1, max_length=28)


class InvestigationPublic(InvestigationRequest):
    id: uuid.UUID
    project_id: uuid.UUID
    status: Literal["GENERATING", "COMPLETED", "FAILED"]
    created_at: datetime
    completed_at: datetime | None
    failure_code: str | None
    output: InvestigationOutput | None
    material: InvestigationMaterial
    parent_investigation_id: uuid.UUID | None
    question: str | None
    connection_version_id: uuid.UUID | None
    tool_reads: list[InvestigationToolRead]


class InvestigationsPublic(BaseModel):
    data: list[InvestigationPublic]
    count: int
    can_create: bool


class SyntheticSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_type: Literal["CUSTOMER_UPLOAD", "CLOUDATLAS", "NETFLOW"]
    input_id: uuid.UUID
    snapshot_id: uuid.UUID
    content_sha256: Digest


class SyntheticCloudAtlasReadPermission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_instance_id: uuid.UUID
    instance_id: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    capset_id: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    fingerprint: Digest
    content_sha256: Digest


class SyntheticPermission(InvestigationRequest):
    project_id: uuid.UUID
    material_sha256: Digest
    sources: list[SyntheticSource] = Field(min_length=1, max_length=3)
    cloudatlas_reads: list[SyntheticCloudAtlasReadPermission] = Field(
        default_factory=list, max_length=16
    )
    question_sha256s: list[Digest] = Field(default_factory=list, max_length=16)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def material_hash(material: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(material)).hexdigest()


def public(record: AiInvestigation) -> InvestigationPublic:
    return InvestigationPublic.model_validate(
        record.model_dump(include=set(InvestigationPublic.model_fields))
    )


def require_model(
    session: Session, record: AiInvestigation | None = None
) -> ModelBinding:
    try:
        managed = model_connections.binding_for_task(session, "investigation", record)
    except model_connections.ModelConnectionError as error:
        raise InvestigationError(error.code) from None
    if managed is not None:
        return managed
    if not settings.MODEL_API_KEY.get_secret_value():
        raise InvestigationError("model_not_qualified")
    try:
        binding = model_binding(
            endpoint=settings.MODEL_API_ENDPOINT,
            model_identity=settings.MODEL_IDENTITY,
            protocol=settings.MODEL_API_PROTOCOL,
            config_revision=settings.MODEL_CONFIG_REVISION,
            runner_build_version=settings.RUNNER_BUILD_VERSION,
            agent_compose_runtime_version=settings.AGENT_COMPOSE_RUNTIME_VERSION,
            allow_baizhi_test=settings.AI_INVESTIGATION_ALLOW_BAIZHI_TEST,
        )
    except ValueError:
        raise InvestigationError("model_not_qualified") from None
    if record is not None and binding.config_fingerprint != record.config_fingerprint:
        raise InvestigationError("model_binding_changed")
    if not current_model_is_qualified(
        session=session,
        endpoint=binding.endpoint,
        model_identity=binding.model_identity,
        config_fingerprint=binding.config_fingerprint,
    ):
        raise InvestigationError("model_not_qualified")
    return binding


def authorize_material(
    *,
    binding: ModelBinding,
    project_id: uuid.UUID,
    scope: InvestigationRequest,
    material: dict[str, Any],
    sources: list[dict[str, Any]],
    questions: tuple[str, ...] = (),
) -> None:
    if binding.endpoint != "https://ai-api-gateway.app.baizhi.cloud/api/openai":
        return
    if not settings.AI_INVESTIGATION_ALLOW_BAIZHI_TEST:
        raise InvestigationError("synthetic_material_denied")
    expected = SyntheticPermission(
        project_id=project_id,
        **scope.model_dump(),
        material_sha256=material_hash(material),
        sources=[SyntheticSource.model_validate(source) for source in sources],
    )
    try:
        manifest = TypeAdapter(list[SyntheticPermission]).validate_json(
            settings.AI_INVESTIGATION_SYNTHETIC_MANIFEST
        )
    except ValueError:
        raise InvestigationError("synthetic_manifest_invalid") from None
    if not any(
        entry.model_dump(exclude={"cloudatlas_reads", "question_sha256s"})
        == expected.model_dump(exclude={"cloudatlas_reads", "question_sha256s"})
        and all(
            hashlib.sha256(question.encode("utf-8")).hexdigest()
            in entry.question_sha256s
            for question in questions
        )
        for entry in manifest
    ):
        raise InvestigationError("synthetic_material_denied")


def authorize_cloudatlas(
    *, record: AiInvestigation, binding: ModelBinding, content: dict[str, Any]
) -> str:
    digest = material_hash(content)
    if binding.endpoint != "https://ai-api-gateway.app.baizhi.cloud/api/openai":
        return digest
    if not settings.AI_INVESTIGATION_ALLOW_BAIZHI_TEST:
        raise InvestigationError("synthetic_material_denied")
    try:
        manifest = TypeAdapter(list[SyntheticPermission]).validate_json(
            settings.AI_INVESTIGATION_SYNTHETIC_MANIFEST
        )
    except ValueError:
        raise InvestigationError("synthetic_manifest_invalid") from None
    source = content["source"]
    expected = SyntheticCloudAtlasReadPermission(
        source_instance_id=source["source_instance_id"],
        instance_id=source["instance_id"],
        capset_id=source["capset_id"],
        fingerprint=source["fingerprint"],
        content_sha256=digest,
    )
    base = SyntheticPermission(
        project_id=record.project_id,
        resource_id=record.resource_id,
        run_id=record.run_id,
        finding_id=record.finding_id,
        material_sha256=record.material_sha256,
        sources=[SyntheticSource.model_validate(source) for source in record.sources],
    ).model_dump(exclude={"cloudatlas_reads", "question_sha256s"})
    if not any(
        entry.model_dump(exclude={"cloudatlas_reads", "question_sha256s"}) == base
        and expected in entry.cloudatlas_reads
        for entry in manifest
    ):
        raise InvestigationError("synthetic_material_denied")
    return digest


def prepare_material(
    *, session: Session, project: Project, scope: InvestigationRequest
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build deployment-manifest material without a model call.

    Caller owns project authorization and a fresh read-only REPEATABLE READ
    Session. This grants no permission to send the result to any provider.
    """
    try:
        lineage = read_governance_run_lineage(
            session=session,
            project=project,
            run_id=scope.run_id,
            resource_id=scope.resource_id,
        )
    except (
        IPSourceComparisonError,
        ReportComparisonEvidenceError,
        ValueError,
        TypeError,
        KeyError,
        SQLAlchemyError,
    ):
        raise InvestigationError("investigation_material_invalid") from None
    # Always retain EVERY source, independently of finding selection/truncation.
    source_nodes = {
        node.source_type: node
        for node in lineage.nodes
        if isinstance(node, LineageSourceNodePublic)
    }
    snapshots = [
        node for node in lineage.nodes if isinstance(node, LineageSnapshotNodePublic)
    ]
    sources = []
    for node in snapshots:
        input_id = source_nodes[node.source_type].input_id
        if input_id is None:
            raise InvestigationError("investigation_material_invalid")
        sources.append(
            SyntheticSource(
                source_type=node.source_type,
                input_id=input_id,
                snapshot_id=node.snapshot_id,
                content_sha256=node.content_sha256,
            ).model_dump(mode="json")
        )
    sources.sort(key=lambda item: item["source_type"])
    selected = [
        node
        for node in lineage.nodes
        if isinstance(
            node,
            (
                LineageSourceNodePublic,
                LineageSnapshotNodePublic,
                LineageComparisonNodePublic,
                LineageFindingNodePublic,
            ),
        )
    ]
    if scope.finding_id is not None and not any(
        isinstance(node, LineageFindingNodePublic)
        and node.finding_id == scope.finding_id
        for node in selected
    ):
        raise InvestigationError("investigation_finding_not_in_run")
    if (
        "finding_limit" in lineage.truncation_reasons
        or "comparison_limit" in lineage.truncation_reasons
    ):
        raise InvestigationError("investigation_material_truncated")
    material = InvestigationMaterial(
        scope=scope,
        project_id=project.id,
        published_at=lineage.completed_at,
        report_id=lineage.governance_report_id,
        report_contract_version=lineage.report_contract_version,
        truncated=lineage.truncated,
        items=[
            InvestigationMaterialItem(citation_id=node.key, fact=node)
            for node in selected
        ],
    ).model_dump(mode="json")
    return material, sources


def load_material(
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    scope: InvestigationRequest,
    record: AiInvestigation | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], ModelBinding]:
    # A new snapshot and identity map on EVERY read, including model tool threads.
    with Session(engine) as session:
        session.connection(
            execution_options={
                "isolation_level": "REPEATABLE READ",
                "postgresql_readonly": True,
            }
        )
        user = session.get(User, user_id)
        if user is None:
            raise InvestigationError("investigation_scope_denied")
        try:
            project = get_authorized_project(
                session=session,
                user=user,
                project_id=project_id,
                allowed_roles=(ProjectRole.OPERATOR,),
            )
        except HTTPException:
            raise InvestigationError("investigation_scope_denied") from None
        if project.archived_at is not None or (
            record is not None and project.tenant_id != record.tenant_id
        ):
            raise InvestigationError("investigation_scope_denied")
        material, sources = prepare_material(
            session=session, project=project, scope=scope
        )
        maximum = (
            record.max_material_bytes
            if record
            else settings.AI_INVESTIGATION_MAX_MATERIAL_BYTES
        )
        if len(canonical_bytes(material)) > maximum:
            raise InvestigationError("material_limit")
        if record is not None and (
            material_hash(material) != record.material_sha256
            or sources != record.sources
        ):
            raise InvestigationError("investigation_material_changed")
        binding = require_model(session, record)
        authorize_material(
            binding=binding,
            project_id=project.id,
            scope=scope,
            material=material,
            sources=sources,
        )
        return material, sources, binding


def conversation(record: AiInvestigation) -> dict[str, Any] | None:
    """Reload bounded ancestors; saved model prose is context, never new evidence."""
    if record.parent_investigation_id is None:
        return None
    with Session(engine) as session:
        binding = require_model(session, record)
        turns: list[dict[str, Any]] = []
        parent_id: uuid.UUID | None = record.parent_investigation_id
        while parent_id is not None:
            if len(turns) >= 7:
                raise InvestigationError("investigation_turn_limit")
            parent = session.get(AiInvestigation, parent_id)
            if (
                parent is None
                or parent.status != "COMPLETED"
                or (
                    parent.tenant_id,
                    parent.project_id,
                    parent.resource_id,
                    parent.run_id,
                    parent.finding_id,
                )
                != (
                    record.tenant_id,
                    record.project_id,
                    record.resource_id,
                    record.run_id,
                    record.finding_id,
                )
            ):
                raise InvestigationError("investigation_scope_denied")
            for read in parent.tool_reads:
                if read["status"] != "SUCCEEDED":
                    continue
                if read["tool_name"] == "read_cloudatlas_asset" and not read["items"]:
                    content = {
                        key: read["result"][key]
                        for key in (
                            "schema",
                            "project_id",
                            "resource_id",
                            "run_id",
                            "base_published_at",
                            "source",
                            "canonical_ip",
                            "result",
                        )
                    }
                    authorize_cloudatlas(
                        record=parent,
                        binding=binding,
                        content={**content, "assets": []},
                    )
                for item in read["items"]:
                    fact = item["fact"]
                    if read["tool_name"] == "read_asset_history":
                        historical = fact["material"]
                        authorize_material(
                            binding=binding,
                            project_id=parent.project_id,
                            scope=InvestigationRequest.model_validate(
                                historical["scope"]
                            ),
                            material=historical,
                            sources=fact["sources"],
                        )
                    elif read["tool_name"] == "read_cloudatlas_asset":
                        authorize_cloudatlas(
                            record=parent,
                            binding=binding,
                            content={
                                key: value
                                for key, value in fact.items()
                                if key not in {"queried_at", "completed_at"}
                            },
                        )
            turns.append({"question": parent.question, "output": parent.output})
            parent_id = parent.parent_investigation_id
        context = {"question": record.question, "previous_turns": list(reversed(turns))}
        authorize_material(
            binding=binding,
            project_id=record.project_id,
            scope=InvestigationRequest.model_validate(record.material["scope"]),
            material=record.material,
            sources=record.sources,
            questions=tuple(
                question
                for question in [record.question, *(turn["question"] for turn in turns)]
                if question is not None
            ),
        )
        if len(canonical_bytes(context)) > record.max_material_bytes:
            raise InvestigationError("material_limit")
        return context


def save_tool_read(
    record: AiInvestigation, read: InvestigationToolRead, *, complete: bool = False
) -> None:
    with Session(engine) as session:
        current = locked_record(session, record.id)
        if current.status != "GENERATING" or current.session_id != record.session_id:
            raise InvestigationError("investigation_scope_denied")
        reads = list(current.tool_reads)
        if complete:
            if not reads or reads[-1]["id"] != str(read.id):
                raise InvestigationError("investigation_scope_denied")
            reads[-1] = read.model_dump(mode="json")
        else:
            if len(reads) >= current.max_tool_calls:
                raise InvestigationError("tool_call_limit")
            reads.append(read.model_dump(mode="json"))
        current.tool_reads = reads
        session.add(current)
        audit(session, current, "ai_investigation.tool_read")
        session.commit()


def audit(session: Session, record: AiInvestigation, action: str) -> None:
    session.add(
        AuditEvent(
            tenant_id=record.tenant_id,
            project_id=record.project_id,
            actor_subject=str(record.initiated_by)
            if action == "ai_investigation.requested"
            else "ai-investigation-runner",
            actor_type="User" if action == "ai_investigation.requested" else "Service",
            action=action,
            target_type="AiInvestigation",
            target_id=record.id,
            after_data={
                "status": record.status,
                "failure_code": record.failure_code,
                "run_id": str(record.run_id),
                "resource_id": str(record.resource_id),
                "material_sha256": record.material_sha256,
                "max_tool_calls": record.max_tool_calls,
                "max_material_bytes": record.max_material_bytes,
                "max_output_bytes": record.max_output_bytes,
                "timeout_seconds": record.timeout_seconds,
                "successful_tool_calls": record.successful_tool_calls,
                "material_bytes_read": record.material_bytes_read,
            },
        )
    )


def locked_record(session: Session, investigation_id: uuid.UUID) -> AiInvestigation:
    # Project first: audit insertion also takes the Project FK lock.
    scope = session.exec(
        select(AiInvestigation.project_id).where(AiInvestigation.id == investigation_id)
    ).one_or_none()
    if scope is None:
        raise InvestigationError("investigation_not_found")
    session.exec(select(Project).where(Project.id == scope).with_for_update()).one()
    return session.exec(
        select(AiInvestigation)
        .where(AiInvestigation.id == investigation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()


def _fail_pending_read(session: Session, record: AiInvestigation) -> None:
    if record.tool_reads and record.tool_reads[-1]["status"] == "RUNNING":
        pending = {
            **record.tool_reads[-1],
            "status": "FAILED",
            "failure_code": "investigation_interrupted",
            "completed_at": get_datetime_utc().isoformat(),
        }
        record.tool_reads = [*record.tool_reads[:-1], pending]
        session.add(record)
        # Seal the read while GENERATING, then independently seal the execution.
        session.flush()


def finish(
    *,
    investigation_id: uuid.UUID,
    failure_code: str | None = None,
    output: dict[str, Any] | None = None,
    successful_tool_calls: int = 0,
    material_bytes_read: int = 0,
) -> AiInvestigation:
    with Session(engine) as session:
        record = locked_record(session, investigation_id)
        if record.status == "GENERATING":
            _fail_pending_read(session, record)
            record.status = "FAILED" if failure_code else "COMPLETED"
            record.failure_code = failure_code
            record.output = output
            record.successful_tool_calls = successful_tool_calls
            record.material_bytes_read = material_bytes_read
            record.completed_at = get_datetime_utc()
            audit(
                session,
                record,
                "ai_investigation.failed"
                if failure_code
                else "ai_investigation.completed",
            )
            session.add(record)
            session.commit()
        session.refresh(record)
        session.expunge(record)
        return record


def reconcile(record: AiInvestigation, *, launch: bool = False) -> AiInvestigation:
    if record.status != "GENERATING":
        return record
    client = AgentComposeClient(
        ai_governance_draft_namespace=AgentComposeDraftNamespace(
            project_id=record.agent_compose_project_id,
            agent_name=record.agent_compose_agent_name,
        )
    )
    observation = None
    unknown_code = "agent_compose_run_unknown"
    try:
        if launch:
            # Only the creator can reach this branch; replay and GET NEVER start.
            load_material(
                project_id=record.project_id,
                user_id=record.initiated_by,
                scope=InvestigationRequest(
                    resource_id=record.resource_id,
                    run_id=record.run_id,
                    finding_id=record.finding_id,
                ),
                record=record,
            )
            if record.connection_version_id is not None:
                from app.integrations.model_connection_runtime import (
                    start_business_task,
                )
                observation = start_business_task(record, "investigation")
            else:
                observation = client.start_ai_investigation(
                    client_request_id=f"ai-investigation:{record.id}",
                    investigation_id=str(record.id),
                )
        else:
            observation = client.get_run(record.agent_compose_run_id)
    except (InvestigationError, model_connections.ModelConnectionError) as error:
        return finish(investigation_id=record.id, failure_code=error.code)
    except AgentComposeBoundaryError:
        unknown_code = "agent_compose_unavailable"
    # No database transaction spans a control-plane request.
    with Session(engine) as session:
        current = locked_record(session, record.id)
        if current.status == "GENERATING":
            if (
                observation is not None
                and observation.run_id == current.agent_compose_run_id
            ):
                if observation.session_id is not None:
                    if not re.fullmatch(r"[0-9a-f]{64}", observation.session_id) or (
                        current.session_id is not None
                        and current.session_id != observation.session_id
                    ):
                        unknown_code = "agent_compose_session_mismatch"
                        observation = None
                    else:
                        current.session_id = observation.session_id
                if observation is not None and observation.is_terminal:
                    _fail_pending_read(session, current)
                    current.status = "FAILED"
                    current.failure_code = (
                        "runner_result_missing"
                        if observation.succeeded
                        else "agent_compose_run_failed"
                    )
                    current.completed_at = get_datetime_utc()
                    audit(session, current, "ai_investigation.failed")
                elif observation is not None and observation.is_active:
                    current.failure_code = None
                else:
                    current.failure_code = unknown_code
            else:
                current.failure_code = unknown_code
            session.add(current)
            session.commit()
        session.refresh(current)
        session.expunge(current)
        return current


def validate_output(
    output: dict[str, Any], *, citation_ids: set[str], max_output_bytes: int
) -> dict[str, Any]:
    try:
        if len(canonical_bytes(output)) > max_output_bytes:
            raise InvestigationError("output_limit")
        parsed = InvestigationOutput.model_validate(output)
    except InvestigationError:
        raise
    except ValueError, TypeError:
        raise InvestigationError("model_output_invalid") from None
    if any(
        citation not in citation_ids
        for fact in parsed.facts
        for citation in fact.citation_ids
    ):
        raise InvestigationError("model_citation_invalid")
    return parsed.model_dump(mode="json")
