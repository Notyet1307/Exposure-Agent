"""Fixed Run analysis versions; model prose never modifies deterministic facts."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from app.api.project_authorization import get_authorized_project
from app.core.config import settings
from app.core.db import engine
from app.core.time import get_datetime_utc
from app.domain import ai_investigations, manual_reviews
from app.domain.ai_investigations import (
    Citation,
    Digest,
    SyntheticSource,
    canonical_bytes,
)
from app.domain.governance_reports import (
    get_published_report_record,
    validate_published_report,
)
from app.domain.model_qualification import (
    ModelBinding,
    current_model_is_qualified,
    model_binding,
)
from app.domain.models import (
    AiInvestigation,
    AnalysisReport,
    AuditEvent,
    GovernanceReport,
    GovernanceRun,
    ManualReview,
    Project,
    ProjectRole,
    SourceSnapshot,
)
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
    AgentComposeDraftNamespace,
)
from app.models import User

Text = Annotated[
    str,
    StringConstraints(
        strict=True, strip_whitespace=True, min_length=1, max_length=8000
    ),
]


class AnalysisReportError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AnalysisReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: uuid.UUID


class AnalysisReportText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_summary: Text
    key_differences: Text
    investigation_progress: Text
    next_steps: Text


class AnalysisReportOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: AnalysisReportText
    citation_ids: list[Citation] = Field(min_length=1, max_length=64)
    gaps: list[ai_investigations.Text] = Field(max_length=32)


class AnalysisReportRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(strict=True, ge=1)


class AnalysisReportUpdate(AnalysisReportRevision):
    text: AnalysisReportText


class AnalysisReportMaterialItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    citation_id: str
    kind: str
    identity: str
    recorded_at: str | None
    data: dict[str, Any]


class AnalysisReportMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    captured_at: str
    report_id: str
    report_contract_version: str
    summary: dict[str, Any]
    items: list[AnalysisReportMaterialItem]
    gaps: list[str]
    truncated: bool


class AnalysisReportPublic(AnalysisReportRequest):
    id: uuid.UUID
    project_id: uuid.UUID
    status: Literal["GENERATING", "DRAFT", "CONFIRMED", "FAILED"]
    created_at: datetime
    completed_at: datetime | None
    edited_at: datetime | None
    confirmed_at: datetime | None
    created_by_id: uuid.UUID
    edited_by_id: uuid.UUID | None
    confirmed_by_id: uuid.UUID | None
    revision: int
    failure_code: str | None
    original_output: AnalysisReportOutput | None
    text: AnalysisReportText | None
    material: AnalysisReportMaterial
    materials_changed: bool


class AnalysisReportsPublic(BaseModel):
    data: list[AnalysisReportPublic]
    count: int
    can_create: bool


class SyntheticReportPermission(AnalysisReportRequest):
    project_id: uuid.UUID
    material_sha256: Digest
    sources: list[SyntheticSource] = Field(min_length=1)


def material_hash(material: dict[str, Any]) -> str:
    return ai_investigations.material_hash(
        {key: value for key, value in material.items() if key != "captured_at"}
    )


def prepare_material(
    *, session: Session, project: Project, run_id: uuid.UUID, max_bytes: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Project-authorized, repeatable snapshot. Never reads Artifact or raw inputs."""
    report = session.exec(
        select(GovernanceReport).where(
            GovernanceReport.governance_run_id == run_id,
            GovernanceReport.project_id == project.id,
            GovernanceReport.tenant_id == project.tenant_id,
        )
    ).one_or_none()
    if (
        report is None
        or get_published_report_record(
            session=session, project=project, report_id=report.id
        )
        is None
    ):
        raise AnalysisReportError("analysis_report_material_unavailable")
    try:
        validate_published_report(session=session, project=project, report=report)
        content = report.canonical_content["report"]
        # Keep all authoritative aggregates, never the unbounded matrix/export rows.
        summary = {
            key: content[key]
            for key in (
                "report_identity",
                "input_completeness",
                "ip_consistency_summary",
                "finding_type_directions_and_limitations",
                "provenance",
            )
        }
        for key, excluded in (
            ("current_run_lifecycle_changes", "changes"),
            ("open_backlog_as_of_run", "findings"),
        ):
            summary[key] = {
                name: value for name, value in content[key].items() if name != excluded
            }
        for key in ("input_capabilities", "ip_source_comparison_summary"):
            if key in content:
                summary[key] = content[key]
        sources = []
        for source in content["input_completeness"]["sources"]:
            snapshot = session.exec(
                select(SourceSnapshot).where(
                    SourceSnapshot.id == uuid.UUID(source["source_snapshot_id"]),
                    SourceSnapshot.governance_run_id == run_id,
                    SourceSnapshot.project_id == project.id,
                    SourceSnapshot.tenant_id == project.tenant_id,
                )
            ).one()
            if (snapshot.source_type, snapshot.content_sha256) != (
                source["source_type"],
                source["content_sha256"],
            ):
                raise ValueError("published source identity differs")
            sources.append(
                SyntheticSource.model_validate(
                    {
                        "source_type": snapshot.source_type,
                        "input_id": snapshot.customer_upload_id
                        or snapshot.source_instance_id
                        or snapshot.netflow_dataset_id,
                        "snapshot_id": snapshot.id,
                        "content_sha256": snapshot.content_sha256,
                    }
                ).model_dump(mode="json")
            )
    except ValueError, TypeError, KeyError, SQLAlchemyError:
        raise AnalysisReportError("analysis_report_material_invalid") from None
    sources.sort(key=lambda item: item["source_type"])
    material: dict[str, Any] = {
        "captured_at": get_datetime_utc().isoformat(),
        "report_id": str(report.id),
        "report_contract_version": report.report_contract_version,
        "summary": summary,
        "items": [
            {
                "citation_id": f"report:{report.id}",
                "kind": "BASE_RUN_SUMMARY",
                "identity": str(report.id),
                "recorded_at": summary["report_identity"]["run_completed_at"],
                "data": {
                    "run_id": str(run_id),
                    "report_contract_version": report.report_contract_version,
                },
            }
        ],
        "gaps": [
            "Only the fixed published Run supplies statistics. Later records do not revise its counts.",
            "NetFlow absence or no positive activity evidence is UNKNOWN, never zero risk. Coverage is unknown.",
        ],
        "truncated": False,
    }
    investigations = session.exec(
        select(AiInvestigation)
        .where(
            AiInvestigation.project_id == project.id,
            AiInvestigation.tenant_id == project.tenant_id,
            AiInvestigation.run_id == run_id,
        )
        .order_by(
            col(AiInvestigation.created_at).desc(), col(AiInvestigation.id).desc()
        )
        .limit(17)
    ).all()
    if not investigations:
        material["gaps"].append(
            "No investigation records have been obtained for this Run."
        )
    if len(investigations) > 16:
        material["truncated"] = True
    for investigation in investigations[:16]:
        identity = str(investigation.id)
        if investigation.status != "COMPLETED":
            material["gaps"].append(
                f"Investigation {identity} is {investigation.status}; no successful analysis is claimed."
            )
        else:
            material["items"].append(
                {
                    "citation_id": f"investigation:{identity}",
                    "kind": "INVESTIGATION",
                    "identity": identity,
                    "recorded_at": investigation.completed_at.isoformat()
                    if investigation.completed_at
                    else None,
                    "data": {
                        "resource_id": str(investigation.resource_id),
                        "run_id": str(run_id),
                        "created_at": investigation.created_at.isoformat(),
                        "parent_investigation_id": str(
                            investigation.parent_investigation_id
                        )
                        if investigation.parent_investigation_id
                        else None,
                        "output": investigation.output,
                        "interpretation": "AI explanation, not an independently established fact",
                    },
                }
            )
        for tool_read in investigation.tool_reads:
            if tool_read["status"] != "SUCCEEDED":
                material["gaps"].append(
                    f"Tool read {tool_read['id']} is {tool_read['status']}; no result is asserted."
                )
                continue
            material["items"].append(
                {
                    "citation_id": f"tool-read:{tool_read['id']}",
                    "kind": "OBTAINED_TOOL_READ",
                    "identity": tool_read["id"],
                    "recorded_at": tool_read["completed_at"],
                    "data": {
                        "investigation_id": identity,
                        "resource_id": str(investigation.resource_id),
                        "run_id": str(run_id),
                        "tool_name": tool_read["tool_name"],
                        "queried_at": tool_read["queried_at"],
                        "result": tool_read["result"],
                        "items": tool_read["items"],
                    },
                }
            )
            if not tool_read["items"]:
                material["gaps"].append(
                    f"Tool read {tool_read['id']} returned no evidence items."
                )
    reviews = session.exec(
        select(ManualReview)
        .where(
            ManualReview.project_id == project.id,
            ManualReview.tenant_id == project.tenant_id,
            ManualReview.run_id == run_id,
        )
        .order_by(col(ManualReview.created_at).desc(), col(ManualReview.id).desc())
        .limit(17)
    ).all()
    if not reviews:
        material["gaps"].append(
            "No human review records have been obtained for this Run."
        )
    if len(reviews) > 16:
        material["truncated"] = True
    base = session.get(GovernanceRun, run_id)
    assert base is not None
    for review in reviews[:16]:
        successor = session.exec(
            select(ManualReview.id).where(
                ManualReview.supersedes_id == review.id,
                ManualReview.project_id == project.id,
                ManualReview.tenant_id == project.tenant_id,
            )
        ).first()
        projection = manual_reviews.public_records(
            session=session,
            project=project,
            base=base,
            records=[review],
            current_id=review.id if successor is None else None,
        )[0].model_dump(mode="json")
        if len(projection["verifications"]) > 16:
            projection["verifications"] = projection["verifications"][:16]
            material["truncated"] = True
        material["items"].append(
            {
                "citation_id": f"manual-review:{review.id}:v{review.version}",
                "kind": "MANUAL_REVIEW",
                "identity": str(review.id),
                "recorded_at": review.created_at.isoformat(),
                "data": projection,
            }
        )
    # Keep freshness sensitive to obtained records even when their prose is omitted
    # by the byte budget. This digest is identity metadata, not a model statistic.
    material["items"][0]["data"]["material_selection_sha256"] = material_hash(material)
    # Never truncate aggregates. Optional material is bounded and omissions explicit.
    if material["truncated"]:
        material["gaps"].append(
            "Historical, investigation or manual material exceeds the bounded selection; omitted records are not analyzed."
        )
    while len(canonical_bytes(material)) > max_bytes and len(material["items"]) > 1:
        material["items"].pop()
        if not material["truncated"]:
            material["truncated"] = True
            material["gaps"].append(
                "Material byte budget omitted optional records; omitted records are not analyzed."
            )
    if len(canonical_bytes(material)) > max_bytes:
        raise AnalysisReportError("material_limit")
    return AnalysisReportMaterial.model_validate(material).model_dump(
        mode="json"
    ), sources


def require_model(
    session: Session, record: AnalysisReport | None = None
) -> ModelBinding:
    if not settings.MODEL_API_KEY.get_secret_value():
        raise AnalysisReportError("model_not_qualified")
    try:
        binding = model_binding(
            endpoint=settings.MODEL_API_ENDPOINT,
            model_identity=settings.MODEL_IDENTITY,
            protocol=settings.MODEL_API_PROTOCOL,
            config_revision=settings.MODEL_CONFIG_REVISION,
            runner_build_version=settings.RUNNER_BUILD_VERSION,
            agent_compose_runtime_version=settings.AGENT_COMPOSE_RUNTIME_VERSION,
            allow_baizhi_test=settings.AI_ANALYSIS_REPORT_ALLOW_BAIZHI_TEST,
        )
    except ValueError:
        raise AnalysisReportError("model_not_qualified") from None
    if record is not None and binding.config_fingerprint != record.config_fingerprint:
        raise AnalysisReportError("model_binding_changed")
    if not current_model_is_qualified(
        session=session,
        endpoint=binding.endpoint,
        model_identity=binding.model_identity,
        config_fingerprint=binding.config_fingerprint,
    ):
        raise AnalysisReportError("model_not_qualified")
    return binding


def authorize_material(
    *,
    binding: ModelBinding,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    material: dict[str, Any],
    sources: list[dict[str, Any]],
) -> None:
    if binding.endpoint != "https://ai-api-gateway.app.baizhi.cloud/api/openai":
        return
    if not settings.AI_ANALYSIS_REPORT_ALLOW_BAIZHI_TEST:
        raise AnalysisReportError("synthetic_material_denied")
    try:
        manifest = TypeAdapter(list[SyntheticReportPermission]).validate_json(
            settings.AI_ANALYSIS_REPORT_SYNTHETIC_MANIFEST
        )
        expected = SyntheticReportPermission(
            project_id=project_id,
            run_id=run_id,
            material_sha256=material_hash(material),
            sources=[SyntheticSource.model_validate(source) for source in sources],
        )
    except ValueError:
        raise AnalysisReportError("synthetic_manifest_invalid") from None
    if expected not in manifest:
        raise AnalysisReportError("synthetic_material_denied")


def load_material(
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    record: AnalysisReport | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], ModelBinding]:
    with Session(engine) as session:
        session.connection(
            execution_options={
                "isolation_level": "REPEATABLE READ",
                "postgresql_readonly": True,
            }
        )
        user = session.get(User, user_id)
        if user is None or not user.is_active:
            raise AnalysisReportError("analysis_report_scope_denied")
        try:
            project = get_authorized_project(
                session=session,
                user=user,
                project_id=project_id,
                allowed_roles=(ProjectRole.OPERATOR,),
            )
        except HTTPException:
            raise AnalysisReportError("analysis_report_scope_denied") from None
        if project.archived_at is not None or (
            record is not None and record.tenant_id != project.tenant_id
        ):
            raise AnalysisReportError("analysis_report_scope_denied")
        if record is None:
            material, sources = prepare_material(
                session=session,
                project=project,
                run_id=run_id,
                max_bytes=settings.AI_ANALYSIS_REPORT_MAX_MATERIAL_BYTES,
            )
        else:
            # The fixed capture, not newly available material, is the egress scope.
            current = session.get(AnalysisReport, record.id)
            if (
                current is None
                or current.status != "GENERATING"
                or current.session_id != record.session_id
                or (
                    current.project_id,
                    current.run_id,
                    current.created_by_id,
                    current.material_sha256,
                )
                != (project_id, run_id, user_id, record.material_sha256)
            ):
                raise AnalysisReportError("analysis_report_scope_denied")
            material, sources = current.material, current.sources
            if (
                material_hash(material) != record.material_sha256
                or sources != record.sources
            ):
                raise AnalysisReportError("analysis_report_material_changed")
        binding = require_model(session, record)
        authorize_material(
            binding=binding,
            project_id=project_id,
            run_id=run_id,
            material=material,
            sources=sources,
        )
        return material, sources, binding


def public(record: AnalysisReport, *, current_hash: str | None) -> AnalysisReportPublic:
    return AnalysisReportPublic.model_validate(
        {
            **record.model_dump(include=set(AnalysisReportPublic.model_fields)),
            "materials_changed": current_hash != record.material_sha256,
        }
    )


def current_material_hash(
    *, project_id: uuid.UUID, run_id: uuid.UUID, max_bytes: int
) -> str | None:
    with Session(engine) as session:
        session.connection(
            execution_options={
                "isolation_level": "REPEATABLE READ",
                "postgresql_readonly": True,
            }
        )
        project = session.get(Project, project_id)
        if project is None:
            return None
        try:
            material, _ = prepare_material(
                session=session, project=project, run_id=run_id, max_bytes=max_bytes
            )
        except AnalysisReportError, ValueError, SQLAlchemyError:
            return None
        return material_hash(material)


def audit(
    session: Session,
    record: AnalysisReport,
    action: str,
    actor_id: uuid.UUID | None = None,
) -> None:
    session.add(
        AuditEvent(
            tenant_id=record.tenant_id,
            project_id=record.project_id,
            actor_subject=str(actor_id) if actor_id else "ai-analysis-report-runner",
            actor_type="User" if actor_id else "Service",
            action=action,
            target_type="AnalysisReport",
            target_id=record.id,
            after_data={
                "run_id": str(record.run_id),
                "status": record.status,
                "revision": record.revision,
                "material_sha256": record.material_sha256,
                "failure_code": record.failure_code,
            },
        )
    )


def locked_record(session: Session, analysis_report_id: uuid.UUID) -> AnalysisReport:
    project_id = session.exec(
        select(AnalysisReport.project_id).where(AnalysisReport.id == analysis_report_id)
    ).one_or_none()
    if project_id is None:
        raise AnalysisReportError("analysis_report_not_found")
    session.exec(
        select(Project).where(Project.id == project_id).with_for_update()
    ).one()
    return session.exec(
        select(AnalysisReport)
        .where(AnalysisReport.id == analysis_report_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()


def validate_output(
    output: dict[str, Any], *, citation_ids: set[str], max_output_bytes: int
) -> dict[str, Any]:
    try:
        if len(canonical_bytes(output)) > max_output_bytes:
            raise AnalysisReportError("output_limit")
        parsed = AnalysisReportOutput.model_validate(output)
    except AnalysisReportError:
        raise
    except ValueError, TypeError:
        raise AnalysisReportError("model_output_invalid") from None
    if not set(parsed.citation_ids).issubset(citation_ids):
        raise AnalysisReportError("model_citation_invalid")
    return parsed.model_dump(mode="json")


def finish(
    *,
    analysis_report_id: uuid.UUID,
    failure_code: str | None = None,
    output: dict[str, Any] | None = None,
    successful_tool_calls: int = 0,
    material_bytes_read: int = 0,
) -> AnalysisReport:
    with Session(engine) as session:
        record = locked_record(session, analysis_report_id)
        if record.status == "GENERATING":
            record.status = "FAILED" if failure_code else "DRAFT"
            record.failure_code = failure_code
            record.original_output = output
            record.text = output["text"] if output else None
            record.successful_tool_calls = successful_tool_calls
            record.material_bytes_read = material_bytes_read
            record.completed_at = get_datetime_utc()
            session.add(record)
            audit(
                session,
                record,
                "analysis_report.failed"
                if failure_code
                else "analysis_report.generated",
            )
            session.commit()
        session.refresh(record)
        session.expunge(record)
        return record


def reconcile(record: AnalysisReport, *, launch: bool = False) -> AnalysisReport:
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
            load_material(
                project_id=record.project_id,
                user_id=record.created_by_id,
                run_id=record.run_id,
                record=record,
            )
            observation = client.start_analysis_report(
                client_request_id=f"analysis-report:{record.id}",
                analysis_report_id=str(record.id),
            )
        else:
            observation = client.get_run(record.agent_compose_run_id)
    except AnalysisReportError as error:
        return finish(analysis_report_id=record.id, failure_code=error.code)
    except AgentComposeBoundaryError:
        unknown_code = "agent_compose_unavailable"
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
                    current.status = "FAILED"
                    current.failure_code = (
                        "runner_result_missing"
                        if observation.succeeded
                        else "agent_compose_run_failed"
                    )
                    current.completed_at = get_datetime_utc()
                    audit(session, current, "analysis_report.failed")
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
