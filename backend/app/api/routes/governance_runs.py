import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Response, status
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep
from app.api.project_authorization import (
    PROJECT_READ_ROLES,
    get_authorized_project,
    project_access_filter,
)
from app.domain import governance_runs as governance_run_service
from app.domain.models import (
    GovernanceRun,
    GovernanceRunsPublic,
    GovernanceRunTriggerPublic,
    Project,
    ProjectRole,
)
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
)

router = APIRouter(prefix="/projects", tags=["governance-runs"])

_ERROR_MESSAGES = {
    "run_idempotency_key_required": "Provide a stable Idempotency-Key.",
    "run_customer_upload_not_ready": (
        "Select a validated CustomerUpload before triggering a Run."
    ),
    "run_cloudatlas_source_not_ready": (
        "Enable and validate a CloudAtlas SourceInstance before triggering a Run."
    ),
    "run_cloudatlas_credential_not_ready": (
        "Configure the CloudAtlas Run credential before triggering a Run."
    ),
    "agent_compose_unavailable": "The Governance Runner control plane is unavailable.",
    "agent_compose_start_failed": "The Governance Runner Session could not be started.",
    "agent_compose_response_contract_failed": (
        "The Governance Runner control plane returned an invalid response."
    ),
}


def _state_http_error(error: governance_run_service.GovernanceRunStateError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": error.code, "message": _ERROR_MESSAGES[error.code]},
    )


def _agent_compose_http_error(error: AgentComposeBoundaryError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": error.code, "message": _ERROR_MESSAGES[error.code]},
    )


def _trigger_id(value: str | None) -> str:
    if (
        value is None
        or not value.strip()
        or value != value.strip()
        or len(value) > 255
        or any(ord(character) < 32 for character in value)
    ):
        code = "run_idempotency_key_required"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": code, "message": _ERROR_MESSAGES[code]},
        )
    return value


@router.get(
    "/{project_id}/governance-runs",
    response_model=GovernanceRunsPublic,
)
def read_governance_runs(
    *, session: SessionDep, project_id: uuid.UUID, current_user: CurrentUser
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    has_operator_access = session.exec(
        select(func.count())
        .select_from(Project)
        .where(
            Project.id == project.id,
            project_access_filter(
                user=current_user, allowed_roles=(ProjectRole.OPERATOR,)
            ),
        )
    ).one()
    readiness_code: str | None = None
    if project.archived_at is not None:
        readiness_code = "run_project_archived"
    else:
        try:
            governance_run_service.require_trigger_readiness(
                session=session, project=project
            )
        except governance_run_service.GovernanceRunStateError as error:
            readiness_code = error.code
    runs = governance_run_service.list_project_runs(
        session=session, project_id=project.id
    )
    return GovernanceRunsPublic(
        data=[
            governance_run_service.governance_run_public(
                session=session, run=run
            )
            for run in runs
        ],
        count=len(runs),
        can_trigger=project.archived_at is None and has_operator_access > 0,
        ready=readiness_code is None,
        readiness_code=readiness_code,
    )


@router.post(
    "/{project_id}/governance-runs",
    response_model=GovernanceRunTriggerPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_governance_run(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    current_user: CurrentUser,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    trigger_id = _trigger_id(idempotency_key)
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=(ProjectRole.OPERATOR,),
        writable=True,
        lock=True,
    )
    existing = session.exec(
        select(GovernanceRun).where(
            GovernanceRun.project_id == project.id,
            GovernanceRun.trigger_id == trigger_id,
        )
    ).one_or_none()
    client_request_id = f"{project.id}:{trigger_id}"
    client = AgentComposeClient()
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return GovernanceRunTriggerPublic(
            accepted=False,
            agent_compose_run_id=client.expected_run_id(client_request_id),
            agent_compose_status="BUSINESS_RUN_ESTABLISHED",
            governance_run_id=existing.id,
        )
    try:
        pinned = governance_run_service.require_trigger_readiness(
            session=session, project=project
        )
        started = client.start_governance_run(
            client_request_id=client_request_id,
            environment=pinned.runner_environment(
                trigger_id=trigger_id,
                requested_by=str(current_user.id),
            ),
        )
    except governance_run_service.GovernanceRunStateError as error:
        session.rollback()
        raise _state_http_error(error)
    except AgentComposeBoundaryError as error:
        session.rollback()
        raise _agent_compose_http_error(error)
    session.commit()
    return GovernanceRunTriggerPublic(
        accepted=started.started,
        agent_compose_run_id=started.run_id,
        agent_compose_status=started.status,
        governance_run_id=None,
    )
