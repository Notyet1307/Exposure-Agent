"""Explicit report generation and independent human confirmation."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.api.project_authorization import (
    PROJECT_READ_ROLES,
    get_authorized_project,
    project_access_filter,
)
from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain import ai_analysis_reports as service
from app.domain.models import AnalysisReport, GovernanceRun, Project, ProjectRole
from app.integrations.agent_compose import AgentComposeClient

router = APIRouter(
    prefix="/projects/{project_id}/analysis-reports", tags=["analysis-reports"]
)


def _error(error: service.AnalysisReportError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": error.code,
            "message": "Analysis report cannot proceed with the fixed authorized material, version and model configuration.",
        },
    )


def _public(record: AnalysisReport) -> service.AnalysisReportPublic:
    return service.public(
        record,
        current_hash=service.current_material_hash(
            project_id=record.project_id,
            run_id=record.run_id,
            max_bytes=record.max_material_bytes,
        ),
    )


@router.post("", response_model=service.AnalysisReportPublic, status_code=201)
def create_analysis_report(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    request_body: service.AnalysisReportRequest,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> service.AnalysisReportPublic:
    if (
        not idempotency_key
        or idempotency_key.strip() != idempotency_key
        or len(idempotency_key) > 255
        or any(ord(char) < 32 for char in idempotency_key)
    ):
        raise HTTPException(
            status_code=400, detail={"code": "analysis_report_idempotency_key_invalid"}
        )
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=(ProjectRole.OPERATOR,),
        writable=True,
        lock=True,
    )
    existing = session.exec(
        select(AnalysisReport).where(
            AnalysisReport.project_id == project.id,
            AnalysisReport.tenant_id == project.tenant_id,
            AnalysisReport.idempotency_key == idempotency_key,
        )
    ).one_or_none()
    if existing is not None:
        if existing.run_id != request_body.run_id:
            raise _error(
                service.AnalysisReportError("analysis_report_idempotency_conflict")
            )
        session.expunge(existing)
        session.commit()
        response.status_code = 200
        return _public(service.reconcile(existing))
    try:
        material, sources, binding = service.load_material(
            project_id=project.id, user_id=current_user.id, run_id=request_body.run_id
        )
    except service.AnalysisReportError as error:
        raise _error(error) from None
    active = session.exec(
        select(AnalysisReport.id).where(
            AnalysisReport.project_id == project.id,
            AnalysisReport.tenant_id == project.tenant_id,
            AnalysisReport.run_id == request_body.run_id,
            AnalysisReport.status == "GENERATING",
        )
    ).first()
    if active is not None:
        raise _error(service.AnalysisReportError("analysis_report_already_generating"))
    record_id = uuid.uuid4()
    client = AgentComposeClient()
    record = AnalysisReport(
        id=record_id,
        tenant_id=project.tenant_id,
        project_id=project.id,
        run_id=request_body.run_id,
        created_by_id=current_user.id,
        idempotency_key=idempotency_key,
        config_fingerprint=binding.config_fingerprint,
        material_sha256=service.material_hash(material),
        material=material,
        sources=sources,
        agent_compose_run_id=client.expected_analysis_report_run_id(
            f"analysis-report:{record_id}"
        ),
        agent_compose_project_id=client.project_id,
        agent_compose_agent_name="ai-analysis-report",
        max_tool_calls=settings.AI_ANALYSIS_REPORT_MAX_TOOL_CALLS,
        max_material_bytes=settings.AI_ANALYSIS_REPORT_MAX_MATERIAL_BYTES,
        max_output_bytes=settings.AI_ANALYSIS_REPORT_MAX_OUTPUT_BYTES,
        timeout_seconds=settings.AI_ANALYSIS_REPORT_TIMEOUT_SECONDS,
    )
    session.add(record)
    service.audit(session, record, "analysis_report.requested", current_user.id)
    session.commit()
    session.refresh(record)
    session.expunge(record)
    session.commit()
    return _public(service.reconcile(record, launch=True))


@router.get("", response_model=service.AnalysisReportsPublic)
def read_analysis_reports(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
) -> service.AnalysisReportsPublic:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    if (
        session.exec(
            select(GovernanceRun.id).where(
                GovernanceRun.id == run_id,
                GovernanceRun.project_id == project.id,
                GovernanceRun.tenant_id == project.tenant_id,
            )
        ).first()
        is None
    ):
        raise HTTPException(status_code=404, detail="Run not found")
    can_create = (
        project.archived_at is None
        and session.exec(
            select(Project.id).where(
                Project.id == project.id,
                project_access_filter(
                    user=current_user, allowed_roles=(ProjectRole.OPERATOR,)
                ),
            )
        ).first()
        is not None
    )
    filters = (
        AnalysisReport.project_id == project.id,
        AnalysisReport.tenant_id == project.tenant_id,
        AnalysisReport.run_id == run_id,
    )
    count = session.exec(
        select(func.count()).select_from(AnalysisReport).where(*filters)
    ).one()
    records = session.exec(
        select(AnalysisReport)
        .where(*filters)
        .order_by(col(AnalysisReport.created_at).desc(), col(AnalysisReport.id).desc())
    ).all()
    for record in records:
        session.expunge(record)
    session.commit()
    hashes: dict[int, str | None] = {}
    data = []
    for record in records:
        if record.max_material_bytes not in hashes:
            hashes[record.max_material_bytes] = service.current_material_hash(
                project_id=project_id,
                run_id=run_id,
                max_bytes=record.max_material_bytes,
            )
        data.append(
            service.public(
                service.reconcile(record),
                current_hash=hashes[record.max_material_bytes],
            )
        )
    return service.AnalysisReportsPublic(data=data, count=count, can_create=can_create)


def _record(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_report_id: uuid.UUID,
    write: bool = False,
) -> AnalysisReport:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=(ProjectRole.OPERATOR,) if write else PROJECT_READ_ROLES,
        writable=write,
        lock=write,
    )
    statement = select(AnalysisReport).where(
        AnalysisReport.id == analysis_report_id,
        AnalysisReport.project_id == project.id,
        AnalysisReport.tenant_id == project.tenant_id,
    )
    if write:
        statement = statement.with_for_update().execution_options(
            populate_existing=True
        )
    record = session.exec(statement).one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Analysis report not found")
    return record


@router.get("/{analysis_report_id}", response_model=service.AnalysisReportPublic)
def read_analysis_report(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_report_id: uuid.UUID,
) -> service.AnalysisReportPublic:
    record = _record(
        session=session,
        current_user=current_user,
        project_id=project_id,
        analysis_report_id=analysis_report_id,
    )
    session.expunge(record)
    session.commit()
    return _public(service.reconcile(record))


def _require_revision(record: AnalysisReport, expected: int) -> None:
    if record.status != "DRAFT":
        raise _error(service.AnalysisReportError("analysis_report_not_editable"))
    if record.revision != expected:
        raise _error(service.AnalysisReportError("analysis_report_revision_conflict"))


@router.patch("/{analysis_report_id}", response_model=service.AnalysisReportPublic)
def update_analysis_report(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_report_id: uuid.UUID,
    request_body: service.AnalysisReportUpdate,
) -> service.AnalysisReportPublic:
    record = _record(
        session=session,
        current_user=current_user,
        project_id=project_id,
        analysis_report_id=analysis_report_id,
        write=True,
    )
    _require_revision(record, request_body.expected_revision)
    record.text = request_body.text.model_dump(mode="json")
    record.edited_by_id = current_user.id
    record.edited_at = get_datetime_utc()
    record.revision += 1
    session.add(record)
    service.audit(session, record, "analysis_report.edited", current_user.id)
    session.commit()
    session.refresh(record)
    session.expunge(record)
    session.commit()
    return _public(record)


@router.post(
    "/{analysis_report_id}/confirm", response_model=service.AnalysisReportPublic
)
def confirm_analysis_report(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_report_id: uuid.UUID,
    request_body: service.AnalysisReportRevision,
) -> service.AnalysisReportPublic:
    record = _record(
        session=session,
        current_user=current_user,
        project_id=project_id,
        analysis_report_id=analysis_report_id,
        write=True,
    )
    _require_revision(record, request_body.expected_revision)
    record.status = "CONFIRMED"
    record.confirmed_by_id = current_user.id
    record.confirmed_at = get_datetime_utc()
    record.revision += 1
    session.add(record)
    service.audit(session, record, "analysis_report.confirmed", current_user.id)
    session.commit()
    session.refresh(record)
    session.expunge(record)
    session.commit()
    return _public(record)
