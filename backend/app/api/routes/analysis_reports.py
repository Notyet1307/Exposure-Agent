"""Explicit report generation and independent human confirmation."""

import hmac
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
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
from app.domain import v2_analysis_reports as v2
from app.domain.ai_investigations import canonical_bytes
from app.domain.model_connections import ConnectionBinding, client_for_binding
from app.domain.models import (
    DEPLOYMENT_TENANT_ID,
    AnalysisReport,
    AnalysisReportRevisionRecord,
    GovernanceRun,
    ModelConnectionState,
    Project,
    ProjectRole,
)
from app.integrations.agent_compose import AgentComposeClient

router = APIRouter(
    prefix="/projects/{project_id}/analysis-reports", tags=["analysis-reports"]
)


def _runner_record(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    analysis_report_id: uuid.UUID,
    agent_run_id: str,
    session_id: str,
    capability: str,
) -> AnalysisReport:
    record = session.get(AnalysisReport, analysis_report_id)
    if (
        record is None
        or record.subject_kind != "core_comparison_v2"
        or record.project_id != project_id
        or record.status != "GENERATING"
        or record.execution_started_at is None
        or get_datetime_utc()
        >= record.execution_started_at + timedelta(seconds=record.timeout_seconds)
        or record.agent_compose_run_id != agent_run_id
        or record.session_id != session_id
        or not hmac.compare_digest(capability, service.runner_material_token(record))
    ):
        raise HTTPException(status_code=403, detail={"code": "runner_material_denied"})
    return record


@router.post("/internal/{analysis_report_id}/material", include_in_schema=False)
def read_runner_material(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    analysis_report_id: uuid.UUID,
    agent_run_id: Annotated[str, Header(alias="X-Analysis-Report-Run")],
    session_id: Annotated[str, Header(alias="X-Analysis-Report-Session")],
    capability: Annotated[str, Header(alias="X-Analysis-Report-Capability")],
) -> dict[str, object]:
    """Return only a freshly reauthorized fixed V2 DTO to its bound runner."""
    record = _runner_record(
        session=session,
        project_id=project_id,
        analysis_report_id=analysis_report_id,
        agent_run_id=agent_run_id,
        session_id=session_id,
        capability=capability,
    )
    try:
        material, _sources, _binding = service.load_material(
            project_id=record.project_id,
            user_id=record.created_by_id,
            run_id=record.run_id,
            record=record,
        )
    except service.AnalysisReportError as error:
        raise _error(error) from None
    return {"material": material}


class RunnerCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    output: v2.Output
    successful_tool_calls: int = Field(strict=True, ge=1)
    material_bytes_read: int = Field(strict=True, ge=1)


@router.post("/internal/{analysis_report_id}/completion", include_in_schema=False)
def complete_runner_report(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    analysis_report_id: uuid.UUID,
    request_body: RunnerCompletion,
    agent_run_id: Annotated[str, Header(alias="X-Analysis-Report-Run")],
    session_id: Annotated[str, Header(alias="X-Analysis-Report-Session")],
    capability: Annotated[str, Header(alias="X-Analysis-Report-Capability")],
) -> dict[str, str]:
    record = _runner_record(
        session=session,
        project_id=project_id,
        analysis_report_id=analysis_report_id,
        agent_run_id=agent_run_id,
        session_id=session_id,
        capability=capability,
    )
    try:
        if request_body.successful_tool_calls > record.max_tool_calls:
            raise service.AnalysisReportError("tool_call_limit")
        if request_body.material_bytes_read > record.max_material_bytes:
            raise service.AnalysisReportError("material_limit")
        if (
            request_body.material_bytes_read
            != len(canonical_bytes(record.material))
            * request_body.successful_tool_calls
        ):
            raise service.AnalysisReportError("v2_report_material_invalid")
        proposal = request_body.output.model_dump(mode="json")
        # The runner already appended these trusted limits; check model prose again.
        proposal["text"]["limitations"] = [
            limit
            for limit in proposal["text"]["limitations"]
            if limit not in record.material["limitations"]
        ]
        output = v2.validate_output(
            proposal,
            record.material,
            {item["citation_id"] for item in record.material["items"]},
            record.max_output_bytes,
        )
        # Only the backend can recheck Artifact integrity before persisting output.
        completed = service.finish(
            analysis_report_id=record.id,
            output=output,
            successful_tool_calls=request_body.successful_tool_calls,
            material_bytes_read=request_body.material_bytes_read,
        )
        if completed.status != "DRAFT":
            raise service.AnalysisReportError(
                completed.failure_code or "model_run_failed"
            )
    except service.AnalysisReportError as error:
        raise _error(error) from None
    return {"status": completed.status}


def _error(error: service.AnalysisReportError) -> HTTPException:
    return HTTPException(
        status_code=410 if error.code == "v2_report_material_expired" else 409,
        detail={
            "code": error.code,
            "message": "Analysis report cannot proceed with the fixed authorized material, version and model configuration.",
        },
    )


def _public(record: AnalysisReport) -> service.AnalysisReportPublic:
    assert record.run_id is not None and record.subject_kind == "governance_run"
    return service.public(
        record,
        current_hash=service.current_material_hash(
            project_id=record.project_id,
            run_id=record.run_id,
            max_bytes=record.max_material_bytes,
        ),
    )


def _create_report(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    request_body: service.AnalysisReportRequest | v2.Request,
    response: Response,
    idempotency_key: str,
) -> service.AnalysisReportPublic | v2.Public:
    if (
        not idempotency_key
        or idempotency_key.strip() != idempotency_key
        or len(idempotency_key) > 255
        or any(ord(char) < 32 for char in idempotency_key)
    ):
        raise HTTPException(
            status_code=400, detail={"code": "analysis_report_idempotency_key_invalid"}
        )
    core_request = request_body if isinstance(request_body, v2.Request) else None
    run_id = (
        request_body.run_id
        if isinstance(request_body, service.AnalysisReportRequest)
        else None
    )
    subject_kind = "core_comparison_v2" if core_request else "governance_run"
    request_hash = (
        service.material_hash(core_request.model_dump(mode="json"))
        if core_request
        else None
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
        if (
            existing.run_id != run_id
            or existing.subject_kind != subject_kind
            or (
                core_request is not None
                and (
                    existing.request_sha256 != request_hash
                    or existing.created_by_id != current_user.id
                )
            )
        ):
            raise _error(
                service.AnalysisReportError("analysis_report_idempotency_conflict")
            )
        session.expunge(existing)
        session.commit()
        response.status_code = 200
        record = service.reconcile(existing)
        return v2.public(record, current_user) if core_request else _public(record)
    try:
        if core_request:
            material, sources, binding = service.load_material(
                project_id=project.id,
                user_id=current_user.id,
                core_request=core_request,
            )
        else:
            material, sources, binding = service.load_material(
                project_id=project.id, user_id=current_user.id, run_id=run_id
            )
    except service.AnalysisReportError as error:
        raise _error(error) from None
    active = session.exec(
        select(AnalysisReport.id).where(
            AnalysisReport.project_id == project.id,
            AnalysisReport.tenant_id == project.tenant_id,
            AnalysisReport.run_id == run_id,
            AnalysisReport.subject_kind == subject_kind,
            *([AnalysisReport.request_sha256 == request_hash] if core_request else []),
            AnalysisReport.status == "GENERATING",
        )
    ).first()
    if active is not None:
        raise _error(service.AnalysisReportError("analysis_report_already_generating"))
    record_id = uuid.uuid4()
    client = (
        client_for_binding(binding)
        if isinstance(binding, ConnectionBinding)
        else AgentComposeClient()
    )
    record = AnalysisReport(
        id=record_id,
        tenant_id=project.tenant_id,
        project_id=project.id,
        run_id=run_id,
        subject_kind=subject_kind,
        core_result_id=core_request.result_id if core_request else None,
        supplement_binding_id=core_request.supplement_binding_id
        if core_request
        else None,
        audience=core_request.audience if core_request else None,
        language=core_request.language if core_request else None,
        address_key=core_request.address_key if core_request else None,
        request_sha256=request_hash,
        created_by_id=current_user.id,
        idempotency_key=idempotency_key,
        config_fingerprint=binding.config_fingerprint,
        connection_version_id=getattr(binding, "connection_version_id", None),
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
    record = service.reconcile(record, launch=True)
    return v2.public(record, current_user) if core_request else _public(record)


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
    result = _create_report(
        session=session,
        current_user=current_user,
        project_id=project_id,
        request_body=request_body,
        response=response,
        idempotency_key=idempotency_key,
    )
    assert isinstance(result, service.AnalysisReportPublic)
    return result


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
    subject_kind: str = "governance_run",
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
        AnalysisReport.subject_kind == subject_kind,
    )
    if write:
        statement = statement.with_for_update().execution_options(
            populate_existing=True
        )
    record = session.exec(statement).one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Analysis report not found")
    if write and subject_kind == "core_comparison_v2":
        try:
            v2.check_record(session, project, record)
        except service.AnalysisReportError as error:
            raise _error(error) from None
    return record


@router.post("/v2", response_model=v2.Public, status_code=201)
def create_v2_analysis_report(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    request_body: v2.Request,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> v2.Public:
    result = _create_report(
        session=session,
        current_user=current_user,
        project_id=project_id,
        request_body=request_body,
        response=response,
        idempotency_key=idempotency_key,
    )
    assert isinstance(result, v2.Public)
    return result


@router.get("/v2/readiness", response_model=v2.Readiness)
def read_v2_report_readiness(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    supplement_binding_id: uuid.UUID | None = None,
    audience: str = "management",
    language: str = "zh",
    address_key: str | None = None,
) -> v2.Readiness:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    try:
        body = v2.Request.model_validate(
            {
                "result_id": result_id,
                "supplement_binding_id": supplement_binding_id,
                "audience": audience,
                "language": language,
                "address_key": address_key,
            }
        )
    except ValueError:
        raise HTTPException(
            status_code=422, detail={"code": "v2_report_request_invalid"}
        ) from None
    result = v2.Readiness(
        project_id=project.id,
        result_id=result_id,
        supplement_binding_id=supplement_binding_id,
        state="NO_PERMISSION",
        can_create=False,
    )
    if (
        project.archived_at is not None
        or session.exec(
            select(Project.id).where(
                Project.id == project.id,
                project_access_filter(
                    user=current_user, allowed_roles=(ProjectRole.OPERATOR,)
                ),
            )
        ).first()
        is None
    ):
        return result
    try:
        v2.read_scope(session, project, body)
    except service.AnalysisReportError as error:
        result.state, result.reason_code = "MATERIAL_UNAVAILABLE", error.code
        return result
    state = session.get(ModelConnectionState, DEPLOYMENT_TENANT_ID)
    if (
        state is not None
        and state.active_id is None
        and (state.adopted or state.pending_id is not None)
    ):
        result.state = "NOT_ENABLED"
        return result
    if (
        state is None or not state.adopted
    ) and not settings.MODEL_API_KEY.get_secret_value():
        result.state = "NOT_CONFIGURED"
        return result
    try:
        _material, _sources, binding = service.load_material(
            project_id=project.id, user_id=current_user.id, core_request=body
        )
    except service.AnalysisReportError as error:
        result.state = (
            "MATERIAL_UNAVAILABLE"
            if error.code.startswith(("v2_report_", "synthetic_", "material_"))
            else "NOT_QUALIFIED"
            if "qualified" in error.code
            else "MODEL_UNAVAILABLE"
        )
        result.reason_code = error.code
        return result
    result.state, result.can_create = "READY", True
    result.connection_version_id = getattr(binding, "connection_version_id", None)
    return result


@router.get("/v2", response_model=v2.Listing)
def read_v2_analysis_reports(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    result_id: uuid.UUID,
    supplement_binding_id: uuid.UUID | None = None,
    audience: str = "management",
    language: str = "zh",
    address_key: str | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=25)] = 25,
) -> v2.Listing:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    try:
        body = v2.Request.model_validate(
            {
                "result_id": result_id,
                "supplement_binding_id": supplement_binding_id,
                "audience": audience,
                "language": language,
                "address_key": address_key,
            }
        )
    except ValueError:
        raise HTTPException(
            status_code=422, detail={"code": "v2_report_request_invalid"}
        ) from None
    filters = (
        AnalysisReport.project_id == project.id,
        AnalysisReport.tenant_id == project.tenant_id,
        AnalysisReport.subject_kind == "core_comparison_v2",
        AnalysisReport.core_result_id == body.result_id,
        AnalysisReport.supplement_binding_id == body.supplement_binding_id,
        AnalysisReport.audience == body.audience,
        AnalysisReport.language == body.language,
        AnalysisReport.address_key == body.address_key,
    )
    count = session.exec(
        select(func.count()).select_from(AnalysisReport).where(*filters)
    ).one()
    records = session.exec(
        select(AnalysisReport)
        .where(*filters)
        .order_by(col(AnalysisReport.created_at).desc(), col(AnalysisReport.id).desc())
        .offset(skip)
        .limit(limit)
    ).all()
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
    for record in records:
        session.expunge(record)
    session.commit()
    return v2.Listing(
        data=[
            v2.public(service.reconcile(record), current_user, include_content=False)
            for record in records
        ],
        count=count,
        can_create=can_create,
    )


@router.get("/v2/operations/{key}", response_model=v2.Public)
def read_v2_report_operation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    key: str,
) -> v2.Public:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    record = session.exec(
        select(AnalysisReport).where(
            AnalysisReport.project_id == project.id,
            AnalysisReport.tenant_id == project.tenant_id,
            AnalysisReport.subject_kind == "core_comparison_v2",
            AnalysisReport.idempotency_key == key,
            AnalysisReport.created_by_id == current_user.id,
        )
    ).one_or_none()
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "v2_report_operation_not_found"}
        )
    session.expunge(record)
    session.commit()
    return v2.public(service.reconcile(record), current_user)


@router.get("/v2/{analysis_report_id}", response_model=v2.Public)
def read_v2_analysis_report(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_report_id: uuid.UUID,
) -> v2.Public:
    record = _record(
        session=session,
        current_user=current_user,
        project_id=project_id,
        analysis_report_id=analysis_report_id,
        subject_kind="core_comparison_v2",
    )
    session.expunge(record)
    session.commit()
    return v2.public(service.reconcile(record), current_user)


@router.patch("/v2/{analysis_report_id}", response_model=v2.Public)
def update_v2_analysis_report(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_report_id: uuid.UUID,
    request_body: v2.Update,
) -> v2.Public:
    record = _record(
        session=session,
        current_user=current_user,
        project_id=project_id,
        analysis_report_id=analysis_report_id,
        write=True,
        subject_kind="core_comparison_v2",
    )
    _require_revision(record, request_body.expected_revision)
    try:
        record.text = v2.edit_text(record, request_body)
    except service.AnalysisReportError as error:
        raise _error(error) from None
    record.edited_by_id, record.edited_at = current_user.id, get_datetime_utc()
    record.revision += 1
    session.add(record)
    service.append_revision(session, record, current_user.id)
    service.audit(session, record, "analysis_report.edited", current_user.id)
    session.commit()
    session.refresh(record)
    session.expunge(record)
    session.commit()
    return v2.public(record, current_user)


@router.post("/v2/{analysis_report_id}/confirm", response_model=v2.Public)
def confirm_v2_analysis_report(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_report_id: uuid.UUID,
    request_body: service.AnalysisReportRevision,
) -> v2.Public:
    record = _record(
        session=session,
        current_user=current_user,
        project_id=project_id,
        analysis_report_id=analysis_report_id,
        write=True,
        subject_kind="core_comparison_v2",
    )
    _require_revision(record, request_body.expected_revision)
    record.status, record.confirmed_by_id, record.confirmed_at = (
        "CONFIRMED",
        current_user.id,
        get_datetime_utc(),
    )
    record.revision += 1
    session.add(record)
    service.append_revision(session, record, current_user.id)
    service.audit(session, record, "analysis_report.confirmed", current_user.id)
    session.commit()
    session.refresh(record)
    session.expunge(record)
    session.commit()
    return v2.public(record, current_user)


@router.get("/v2/{analysis_report_id}/revisions")
def read_v2_report_revisions(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_report_id: uuid.UUID,
) -> list[dict[str, object]]:
    record = _record(
        session=session,
        current_user=current_user,
        project_id=project_id,
        analysis_report_id=analysis_report_id,
        subject_kind="core_comparison_v2",
    )
    project = session.get(Project, project_id)
    assert project is not None
    try:
        v2.check_record(session, project, record)
    except service.AnalysisReportError as error:
        raise _error(error) from None
    return [
        row.model_dump(mode="json")
        for row in session.exec(
            select(AnalysisReportRevisionRecord)
            .where(AnalysisReportRevisionRecord.report_id == record.id)
            .order_by(col(AnalysisReportRevisionRecord.revision).desc())
        ).all()
    ]


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
