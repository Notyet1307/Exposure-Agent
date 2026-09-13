"""Manual single-asset investigations. Read/replay never schedules execution."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Response
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.api.project_authorization import (
    PROJECT_READ_ROLES,
    get_authorized_project,
    project_access_filter,
)
from app.core.config import settings
from app.domain import ai_investigations as service
from app.domain.model_connections import ConnectionBinding, client_for_binding
from app.domain.models import (
    AiInvestigation,
    Finding,
    GovernanceRun,
    Project,
    ProjectRole,
    Resource,
)
from app.integrations.agent_compose import AgentComposeClient

router = APIRouter(
    prefix="/projects/{project_id}/ai-investigations", tags=["ai-investigations"]
)


def _error(error: service.InvestigationError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": error.code,
            "message": "Investigation cannot proceed with the fixed authorized materials and model configuration.",
        },
    )


@router.post("", response_model=service.InvestigationPublic, status_code=201)
def create_ai_investigation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    request_body: service.InvestigationRequest,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> service.InvestigationPublic:
    return _create_investigation(
        session=session,
        current_user=current_user,
        project_id=project_id,
        request_body=request_body,
        response=response,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/{investigation_id}/followups",
    response_model=service.InvestigationPublic,
    status_code=201,
)
def create_ai_investigation_followup(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    investigation_id: uuid.UUID,
    request_body: service.InvestigationFollowupRequest,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> service.InvestigationPublic:
    return _create_investigation(
        session=session,
        current_user=current_user,
        project_id=project_id,
        request_body=None,
        response=response,
        idempotency_key=idempotency_key,
        parent_id=investigation_id,
        question=request_body.question,
    )


def _create_investigation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    request_body: service.InvestigationRequest | None,
    response: Response,
    idempotency_key: str,
    parent_id: uuid.UUID | None = None,
    question: str | None = None,
) -> service.InvestigationPublic:
    if (
        not idempotency_key
        or idempotency_key.strip() != idempotency_key
        or len(idempotency_key) > 255
        or any(ord(char) < 32 for char in idempotency_key)
    ):
        raise HTTPException(
            status_code=400, detail={"code": "investigation_idempotency_key_invalid"}
        )
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=(ProjectRole.OPERATOR,),
        writable=True,
        lock=True,
    )
    parent = None
    if parent_id is not None:
        parent = session.exec(
            select(AiInvestigation).where(
                AiInvestigation.id == parent_id,
                AiInvestigation.project_id == project.id,
                AiInvestigation.tenant_id == project.tenant_id,
            )
        ).one_or_none()
        if parent is None:
            raise HTTPException(status_code=404, detail="Investigation not found")
        if parent.status != "COMPLETED":
            raise _error(
                service.InvestigationError("investigation_parent_not_completed")
            )
        request_body = service.InvestigationRequest(
            resource_id=parent.resource_id,
            run_id=parent.run_id,
            finding_id=parent.finding_id,
        )
    assert request_body is not None
    existing = session.exec(
        select(AiInvestigation).where(
            AiInvestigation.project_id == project.id,
            AiInvestigation.tenant_id == project.tenant_id,
            AiInvestigation.idempotency_key == idempotency_key,
        )
    ).one_or_none()
    if existing is not None:
        if (
            existing.resource_id,
            existing.run_id,
            existing.finding_id,
            existing.parent_investigation_id,
            existing.question,
        ) != (
            request_body.resource_id,
            request_body.run_id,
            request_body.finding_id,
            parent_id,
            question,
        ):
            raise _error(
                service.InvestigationError("investigation_idempotency_conflict")
            )
        session.expunge(existing)
        session.commit()
        response.status_code = 200
        return service.public(service.reconcile(existing))
    try:
        material, sources, binding = service.load_material(
            project_id=project.id, user_id=current_user.id, scope=request_body
        )
    except service.InvestigationError as error:
        raise _error(error) from None
    active = session.exec(
        select(AiInvestigation.id).where(
            AiInvestigation.project_id == project.id,
            AiInvestigation.tenant_id == project.tenant_id,
            AiInvestigation.resource_id == request_body.resource_id,
            AiInvestigation.run_id == request_body.run_id,
            AiInvestigation.status == "GENERATING",
        )
    ).first()
    if active is not None:
        raise _error(service.InvestigationError("investigation_already_generating"))
    record_id = uuid.uuid4()
    client = (
        client_for_binding(binding)
        if isinstance(binding, ConnectionBinding)
        else AgentComposeClient()
    )
    record = AiInvestigation(
        id=record_id,
        tenant_id=project.tenant_id,
        project_id=project.id,
        **request_body.model_dump(),
        initiated_by=current_user.id,
        parent_investigation_id=parent_id,
        question=question,
        idempotency_key=idempotency_key,
        config_fingerprint=binding.config_fingerprint,
        connection_version_id=getattr(binding, "connection_version_id", None),
        material_sha256=service.material_hash(material),
        material=material,
        sources=sources,
        agent_compose_run_id=client.expected_ai_investigation_run_id(
            f"ai-investigation:{record_id}"
        ),
        agent_compose_project_id=client.project_id,
        agent_compose_agent_name="ai-investigation",
        max_tool_calls=settings.AI_INVESTIGATION_MAX_TOOL_CALLS,
        max_material_bytes=settings.AI_INVESTIGATION_MAX_MATERIAL_BYTES,
        max_output_bytes=settings.AI_INVESTIGATION_MAX_OUTPUT_BYTES,
        timeout_seconds=(
            settings.AI_INVESTIGATION_FOLLOWUP_TIMEOUT_SECONDS
            if parent is not None
            else settings.AI_INVESTIGATION_TIMEOUT_SECONDS
        ),
    )
    if parent is not None:
        try:
            service.conversation(record)
        except service.InvestigationError as error:
            raise _error(error) from None
    session.add(record)
    service.audit(session, record, "ai_investigation.requested")
    # One durable launch reservation before any control-plane I/O. Losing replays
    # can observe this identity but are never entitled to start it again.
    session.commit()
    session.refresh(record)
    session.expunge(record)
    session.commit()
    return service.public(service.reconcile(record, launch=True))


@router.get("", response_model=service.InvestigationsPublic)
def read_ai_investigations(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    resource_id: uuid.UUID,
    run_id: uuid.UUID,
    finding_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
) -> service.InvestigationsPublic:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    resource = session.exec(
        select(Resource.id).where(
            Resource.id == resource_id,
            Resource.project_id == project.id,
            Resource.tenant_id == project.tenant_id,
        )
    ).first()
    run = session.exec(
        select(GovernanceRun.id).where(
            GovernanceRun.id == run_id,
            GovernanceRun.project_id == project.id,
            GovernanceRun.tenant_id == project.tenant_id,
        )
    ).first()
    if resource is None or run is None:
        raise HTTPException(status_code=404, detail="Investigation scope not found")
    if (
        finding_id is not None
        and session.exec(
            select(Finding.id).where(
                Finding.id == finding_id,
                Finding.resource_id == resource_id,
                Finding.project_id == project.id,
                Finding.tenant_id == project.tenant_id,
            )
        ).first()
        is None
    ):
        raise HTTPException(status_code=404, detail="Investigation scope not found")
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
    filters = [
        AiInvestigation.project_id == project.id,
        AiInvestigation.tenant_id == project.tenant_id,
        AiInvestigation.resource_id == resource_id,
        AiInvestigation.run_id == run_id,
    ]
    filters.append(AiInvestigation.finding_id == finding_id)
    count = session.exec(
        select(func.count()).select_from(AiInvestigation).where(*filters)
    ).one()
    records = session.exec(
        select(AiInvestigation)
        .where(*filters)
        .order_by(
            col(AiInvestigation.created_at).desc(), col(AiInvestigation.id).desc()
        )
        .limit(limit)
    ).all()
    for record in records:
        session.expunge(record)
    session.commit()
    return service.InvestigationsPublic(
        data=[service.public(service.reconcile(record)) for record in records],
        count=count,
        can_create=can_create,
    )


@router.get("/{investigation_id}", response_model=service.InvestigationPublic)
def read_ai_investigation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    investigation_id: uuid.UUID,
) -> service.InvestigationPublic:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    record = session.exec(
        select(AiInvestigation).where(
            AiInvestigation.id == investigation_id,
            AiInvestigation.project_id == project.id,
            AiInvestigation.tenant_id == project.tenant_id,
        )
    ).one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    session.expunge(record)
    session.commit()
    return service.public(service.reconcile(record))
