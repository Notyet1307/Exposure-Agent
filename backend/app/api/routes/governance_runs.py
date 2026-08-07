import uuid
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.api.project_authorization import (
    PROJECT_READ_ROLES,
    get_authorized_project,
    project_access_filter,
)
from app.api.request import get_request_ip_address
from app.domain import governance_runs as governance_run_service
from app.domain.models import (
    AuditEvent,
    GovernanceRun,
    GovernanceRunActionPublic,
    GovernanceRunsPublic,
    GovernanceRunStatus,
    GovernanceRunTriggerPublic,
    Project,
    ProjectRole,
    RunStep,
    RunStepStatus,
)
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
    AgentComposeSessionObservation,
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
    "run_project_archived": "This Project is archived and read-only.",
    "run_already_active": "This Project already has an active GovernanceRun.",
    "run_retry_newer_run_exists": "A newer GovernanceRun makes this Run historical.",
    "run_retry_completed": "A completed GovernanceRun cannot be retried.",
    "run_retry_customer_input_changed": "The fixed CustomerUpload input changed.",
    "run_retry_cloudatlas_input_changed": "The fixed CloudAtlas input changed.",
    "run_retry_cloudatlas_input_unavailable": (
        "The fixed CloudAtlas input cannot be verified."
    ),
    "run_retry_no_failed_step": "The GovernanceRun has no failed step to retry.",
    "run_session_still_running": "The original Session is still running.",
    "run_session_state_unknown": "The original Session terminal state is unknown.",
    "run_session_not_recoverable": "The original Session cannot be recovered.",
    "run_rerun_required": "Use Rerun with a new Trigger ID for this failed Run.",
    "run_launch_in_progress": "A Governance Runner launch is already in progress.",
    "run_launch_terminal_use_new_trigger": (
        "The previous launch ended before creating a Run; use a new Trigger ID."
    ),
    "run_rerun_newer_run_exists": "Only the latest GovernanceRun can be rerun.",
    "run_rerun_trigger_conflict": (
        "This Trigger ID already belongs to another GovernanceRun."
    ),
    "run_retry_in_progress": "Retry recovery is already in progress.",
    "agent_compose_unavailable": "The Governance Runner control plane is unavailable.",
    "agent_compose_start_failed": "The Governance Runner Session could not be started.",
    "agent_compose_response_contract_failed": (
        "The Governance Runner control plane returned an invalid response."
    ),
    "agent_compose_session_not_recoverable": (
        "The original Governance Runner Session cannot be recovered."
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


def _run_action_error(code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": _ERROR_MESSAGES[code]},
    )


def _reject_run_action(
    *,
    session: SessionDep,
    run: GovernanceRun,
    action: str,
    code: str,
    actor_subject: str,
    request_ip: str | None,
) -> NoReturn:
    governance_run_service.record_run_action(
        session=session,
        run=run,
        action=action,
        actor_subject=actor_subject,
        request_ip=request_ip,
        after_data={"reason": code},
    )
    raise _run_action_error(code)


def _retry_request_id(run: GovernanceRun, attempt: int) -> str:
    return f"{run.project_id}:{run.trigger_id}:retry:{attempt}"


def _running_attempt(session: SessionDep, run: GovernanceRun) -> int | None:
    attempts = session.exec(
        select(RunStep.attempt).where(
            RunStep.governance_run_id == run.id,
            RunStep.status == RunStepStatus.RUNNING.value,
        )
    ).all()
    return max(attempts, default=None)


@router.get(
    "/{project_id}/governance-runs",
    response_model=GovernanceRunsPublic,
)
def read_governance_runs(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    current_user: CurrentUser,
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
    launch_blocking_code = (
        "run_launch_in_progress"
        if project.governance_launch_trigger_id is not None
        else None
    )
    readiness_code: str | None = None
    if project.archived_at is not None:
        readiness_code = "run_project_archived"
    else:
        try:
            governance_run_service.require_trigger_readiness(
                session=session,
                project=project,
                verify_current_fingerprint=False,
            )
        except governance_run_service.GovernanceRunStateError as error:
            readiness_code = error.code
    runs = governance_run_service.list_project_runs(
        session=session, project_id=project.id
    )
    run_views = [
        governance_run_service.governance_run_public(
            session=session, run=run
        )
        for run in runs
    ]
    if (
        run_views
        and has_operator_access > 0
        and project.archived_at is None
        and runs[0].status not in governance_run_service.COMPLETED_RUN_STATUSES
    ):
        latest = runs[0]
        blocking_code: str | None = None
        can_retry = False
        can_rerun = False
        try:
            control_session = AgentComposeClient().get_session(latest.session_id)
        except AgentComposeBoundaryError:
            control_session = None
        if (
            control_session is None
            or control_session.observation is AgentComposeSessionObservation.UNKNOWN
        ):
            if (
                latest.session_terminal_at is not None
                and latest.session_recovery_code == "run_session_not_recoverable"
            ):
                can_rerun = (
                    latest.status != GovernanceRunStatus.RUNNING.value
                    and readiness_code is None
                    and project.governance_launch_trigger_id is None
                )
                blocking_code = (
                    "run_launch_in_progress"
                    if project.governance_launch_trigger_id is not None
                    else latest.session_recovery_code
                )
            else:
                blocking_code = "run_session_state_unknown"
        elif control_session.observation is AgentComposeSessionObservation.RUNNING:
            blocking_code = "run_session_still_running"
        else:
            can_rerun = (
                latest.status != GovernanceRunStatus.RUNNING.value
                and readiness_code is None
                and project.governance_launch_trigger_id is None
            )
            if latest.session_recovery_code == "run_session_not_recoverable":
                blocking_code = latest.session_recovery_code
            else:
                try:
                    governance_run_service.require_retry_readiness(
                        session=session,
                        project=project,
                        run=latest,
                        verify_current_fingerprint=False,
                    )
                    can_retry = True
                except governance_run_service.GovernanceRunStateError as error:
                    blocking_code = error.code
                    if (
                        latest.status == GovernanceRunStatus.RUNNING.value
                        and error.code
                        in {
                            "run_retry_customer_input_changed",
                            "run_retry_cloudatlas_input_changed",
                        }
                    ):
                        can_rerun = (
                            readiness_code is None
                            and project.governance_launch_trigger_id is None
                        )
        run_views[0] = run_views[0].model_copy(
            update={
                "can_retry": can_retry,
                "can_rerun": can_rerun,
                "blocking_code": blocking_code,
            }
        )
    can_trigger = (
        project.archived_at is None
        and project.governance_launch_trigger_id is None
        and has_operator_access > 0
        and (
            not runs
            or runs[0].status in governance_run_service.COMPLETED_RUN_STATUSES
        )
    )
    return GovernanceRunsPublic(
        data=run_views,
        count=len(runs),
        can_trigger=can_trigger,
        ready=readiness_code is None,
        readiness_code=readiness_code,
        launch_blocking_code=launch_blocking_code,
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
    request: Request,
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
    expected_run_id = client.expected_run_id(client_request_id)
    try:
        reconciled_trigger = governance_run_service.reconcile_launch_reservation(
            session=session,
            project=project,
            client=client,
            actor_subject=str(current_user.id),
            request_ip=get_request_ip_address(request),
        )
    except AgentComposeBoundaryError:
        reconciled_trigger = None
    if reconciled_trigger is not None:
        session.commit()
    if reconciled_trigger == trigger_id:
        governance_run_service.record_project_action(
            session=session,
            project=project,
            action="governance_run.new_trigger_rejected",
            actor_subject=str(current_user.id),
            request_ip=get_request_ip_address(request),
            after_data={"reason": "run_launch_terminal_use_new_trigger"},
        )
        raise _state_http_error(
            governance_run_service.GovernanceRunStateError(
                "run_launch_terminal_use_new_trigger"
            )
        )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return GovernanceRunTriggerPublic(
            accepted=False,
            agent_compose_run_id=expected_run_id,
            agent_compose_status="BUSINESS_RUN_ESTABLISHED",
            governance_run_id=existing.id,
        )
    active_run = session.exec(
        select(GovernanceRun).where(
            GovernanceRun.project_id == project.id,
            GovernanceRun.status == GovernanceRunStatus.RUNNING.value,
        )
    ).first()
    if active_run is not None:
        session.rollback()
        code = "run_already_active"
        governance_run_service.record_run_action(
            session=session,
            run=active_run,
            action="governance_run.new_trigger_rejected",
            actor_subject=str(current_user.id),
            request_ip=get_request_ip_address(request),
            after_data={"reason": code},
        )
        raise _run_action_error(code)
    latest_run = session.exec(
        select(GovernanceRun)
        .where(GovernanceRun.project_id == project.id)
        .order_by(
            col(GovernanceRun.created_at).desc(),
            col(GovernanceRun.id).desc(),
        )
    ).first()
    if latest_run is not None and latest_run.status in {
        GovernanceRunStatus.FAILED_DATA.value,
        GovernanceRunStatus.FAILED_PROCESSING.value,
    }:
        try:
            previous_session = client.get_session(latest_run.session_id)
        except AgentComposeBoundaryError as error:
            session.rollback()
            governance_run_service.record_run_action(
                session=session,
                run=latest_run,
                action="governance_run.new_trigger_rejected",
                actor_subject=str(current_user.id),
                request_ip=get_request_ip_address(request),
                after_data={"reason": error.code},
            )
            raise _agent_compose_http_error(error)
        session.rollback()
        actor_subject = str(current_user.id)
        request_ip = get_request_ip_address(request)
        if previous_session is None or (
            previous_session.observation is AgentComposeSessionObservation.UNKNOWN
        ):
            _reject_run_action(
                session=session,
                run=latest_run,
                action="governance_run.new_trigger_rejected",
                code="run_session_state_unknown",
                actor_subject=actor_subject,
                request_ip=request_ip,
            )
        if previous_session.observation is AgentComposeSessionObservation.RUNNING:
            _reject_run_action(
                session=session,
                run=latest_run,
                action="governance_run.new_trigger_rejected",
                code="run_session_still_running",
                actor_subject=actor_subject,
                request_ip=request_ip,
            )
        _reject_run_action(
            session=session,
            run=latest_run,
            action="governance_run.new_trigger_rejected",
            code="run_rerun_required",
            actor_subject=actor_subject,
            request_ip=request_ip,
        )
    try:
        pinned = governance_run_service.require_trigger_readiness(
            session=session, project=project
        )
    except governance_run_service.GovernanceRunStateError as readiness_error:
        try:
            existing_session = client.get_run(expected_run_id)
        except AgentComposeBoundaryError:
            existing_session = None
        if existing_session is not None:
            response.status_code = status.HTTP_200_OK
            session.commit()
            return GovernanceRunTriggerPublic(
                accepted=False,
                agent_compose_run_id=existing_session.run_id,
                agent_compose_status=existing_session.status,
                governance_run_id=None,
            )
        session.rollback()
        governance_run_service.record_project_action(
            session=session,
            project=project,
            action="governance_run.trigger_rejected",
            actor_subject=str(current_user.id),
            request_ip=get_request_ip_address(request),
            after_data={"reason": readiness_error.code},
        )
        raise _state_http_error(readiness_error)
    try:
        launch_reserved = governance_run_service.reserve_run_launch(
            session=session,
            project=project,
            trigger_id=trigger_id,
            control_run_id=expected_run_id,
            pinned=pinned,
        )
        if launch_reserved:
            session.add(
                AuditEvent(
                    tenant_id=project.tenant_id,
                    project_id=project.id,
                    actor_subject=str(current_user.id),
                    actor_type="user",
                    action="governance_run.trigger_requested",
                    target_type="project",
                    target_id=project.id,
                    after_data={"trigger_id": trigger_id},
                    ip_address=get_request_ip_address(request),
                )
            )
        session.commit()
    except governance_run_service.GovernanceRunStateError as launch_error:
        session.rollback()
        if launch_error.code == "run_launch_in_progress":
            governance_run_service.record_project_action(
                session=session,
                project=project,
                action="governance_run.new_trigger_rejected",
                actor_subject=str(current_user.id),
                request_ip=get_request_ip_address(request),
                after_data={"reason": launch_error.code},
            )
        raise _state_http_error(launch_error)
    try:
        started = client.start_governance_run(
            client_request_id=client_request_id,
            environment=pinned.runner_environment(
                trigger_id=trigger_id,
                requested_by=str(current_user.id),
            ),
        )
    except AgentComposeBoundaryError as error:
        raise _agent_compose_http_error(error)
    return GovernanceRunTriggerPublic(
        accepted=started.started,
        agent_compose_run_id=started.run_id,
        agent_compose_status=started.status,
        governance_run_id=None,
    )


@router.post(
    "/{project_id}/governance-runs/{run_id}/retry",
    response_model=GovernanceRunActionPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_governance_run(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
    response: Response,
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=(ProjectRole.OPERATOR,),
        writable=True,
        lock=True,
    )
    run = session.exec(
        select(GovernanceRun).where(
            GovernanceRun.id == run_id,
            GovernanceRun.project_id == project.id,
            GovernanceRun.tenant_id == project.tenant_id,
        ).with_for_update()
    ).one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    actor_subject = str(current_user.id)
    request_ip = get_request_ip_address(request)
    if run.session_recovery_code == "run_session_not_recoverable":
        _reject_run_action(
            session=session,
            run=run,
            action="governance_run.retry_rejected",
            code="run_session_not_recoverable",
            actor_subject=actor_subject,
            request_ip=request_ip,
        )
    attempt = _running_attempt(session, run)
    client = AgentComposeClient()
    prepared_retry = (
        run.status == GovernanceRunStatus.RUNNING.value
        and attempt is not None
        and run.session_recovery_code == "retry_prepared"
    )
    if prepared_retry:
        assert attempt is not None
        prepared_request_id = _retry_request_id(run, attempt)
        try:
            existing_attempt = client.get_run(
                client.expected_run_id(prepared_request_id)
            )
        except AgentComposeBoundaryError as error:
            session.rollback()
            governance_run_service.record_run_action(
                session=session,
                run=run,
                action="governance_run.retry_rejected",
                actor_subject=actor_subject,
                request_ip=request_ip,
                after_data={"reason": error.code},
            )
            raise _agent_compose_http_error(error)
        if existing_attempt is not None:
            if existing_attempt.session_id != run.session_id:
                session.rollback()
                boundary_error = AgentComposeBoundaryError(
                    "agent_compose_response_contract_failed"
                )
                governance_run_service.record_run_action(
                    session=session,
                    run=run,
                    action="governance_run.retry_rejected",
                    actor_subject=actor_subject,
                    request_ip=request_ip,
                    after_data={"reason": boundary_error.code},
                )
                raise _agent_compose_http_error(boundary_error)
            if existing_attempt.is_terminal:
                prepared_retry = False
            else:
                response.status_code = status.HTTP_200_OK
                return GovernanceRunActionPublic(
                    accepted=False,
                    action="retry",
                    governance_run_id=run.id,
                    session_id=run.session_id,
                    agent_compose_run_id=existing_attempt.run_id,
                    agent_compose_status=existing_attempt.status,
                    code="run_retry_in_progress",
                )
    runner_reentered = (
        run.status == GovernanceRunStatus.RUNNING.value
        and attempt is not None
        and attempt > 1
        and run.session_recovery_code is None
    )

    try:
        reconciled_trigger = governance_run_service.reconcile_launch_reservation(
            session=session,
            project=project,
            client=client,
            actor_subject=actor_subject,
            request_ip=request_ip,
        )
        if reconciled_trigger is not None:
            session.commit()
    except AgentComposeBoundaryError as error:
        session.rollback()
        governance_run_service.record_run_action(
            session=session,
            run=run,
            action="governance_run.retry_rejected",
            actor_subject=actor_subject,
            request_ip=request_ip,
            after_data={"reason": error.code},
        )
        raise _agent_compose_http_error(error)

    try:
        pinned = governance_run_service.require_retry_readiness(
            session=session, project=project, run=run
        )
    except governance_run_service.GovernanceRunStateError as error:
        session.rollback()
        governance_run_service.record_run_action(
            session=session,
            run=run,
            action="governance_run.retry_rejected",
            actor_subject=actor_subject,
            request_ip=request_ip,
            after_data={"reason": error.code},
        )
        raise _state_http_error(error)

    try:
        control_session = client.get_session(run.session_id)
    except AgentComposeBoundaryError as error:
        session.rollback()
        governance_run_service.record_run_action(
            session=session,
            run=run,
            action="governance_run.retry_rejected",
            actor_subject=actor_subject,
            request_ip=request_ip,
            after_data={"reason": error.code},
        )
        raise _agent_compose_http_error(error)
    if control_session is None or (
        control_session.observation is AgentComposeSessionObservation.UNKNOWN
    ):
        session.rollback()
        _reject_run_action(
            session=session,
            run=run,
            action="governance_run.retry_rejected",
            code="run_session_state_unknown",
            actor_subject=actor_subject,
            request_ip=request_ip,
        )
    if control_session.observation is AgentComposeSessionObservation.RUNNING:
        if runner_reentered:
            assert attempt is not None
            response.status_code = status.HTTP_200_OK
            request_id = _retry_request_id(run, attempt)
            return GovernanceRunActionPublic(
                accepted=False,
                action="retry",
                governance_run_id=run.id,
                session_id=run.session_id,
                agent_compose_run_id=client.expected_run_id(request_id),
                agent_compose_status="RETRY_IN_PROGRESS",
                code="run_retry_in_progress",
            )
        if not prepared_retry:
            session.rollback()
            _reject_run_action(
                session=session,
                run=run,
                action="governance_run.retry_rejected",
                code="run_session_still_running",
                actor_subject=actor_subject,
                request_ip=request_ip,
            )

    if prepared_retry:
        assert attempt is not None
        request_id = _retry_request_id(run, attempt)
    else:
        try:
            governance_run_service.converge_terminal_run(
                session=session,
                run=run,
                actor_subject=actor_subject,
                request_ip=request_ip,
            )
            step = governance_run_service.prepare_retry(
                session=session,
                run=run,
                actor_subject=actor_subject,
                request_ip=request_ip,
            )
        except governance_run_service.GovernanceRunStateError as error:
            session.rollback()
            governance_run_service.record_run_action(
                session=session,
                run=run,
                action="governance_run.retry_rejected",
                actor_subject=actor_subject,
                request_ip=request_ip,
                after_data={"reason": error.code},
            )
            raise _state_http_error(error)
        request_id = _retry_request_id(run, step.attempt)
    try:
        if control_session.observation is AgentComposeSessionObservation.TERMINAL:
            resumed = client.resume_session(run.session_id)
            if resumed.observation is not AgentComposeSessionObservation.RUNNING:
                raise AgentComposeBoundaryError(
                    "agent_compose_response_contract_failed"
                )
        started = client.start_governance_run(
            client_request_id=request_id,
            environment=pinned.runner_environment(
                trigger_id=run.trigger_id,
                requested_by=run.requested_by,
            ),
            session_id=run.session_id,
        )
        if started.session_id != run.session_id:
            raise AgentComposeBoundaryError(
                "agent_compose_response_contract_failed"
            )
    except AgentComposeBoundaryError as error:
        if error.code == "agent_compose_session_not_recoverable":
            governance_run_service.fail_retry_start(
                session=session,
                run=run,
                actor_subject=actor_subject,
                request_ip=request_ip,
            )
            raise _run_action_error("run_session_not_recoverable")
        session.rollback()
        governance_run_service.record_run_action(
            session=session,
            run=run,
            action="governance_run.retry_rejected",
            actor_subject=actor_subject,
            request_ip=request_ip,
            after_data={"reason": error.code},
        )
        raise _agent_compose_http_error(error)
    return GovernanceRunActionPublic(
        accepted=started.started,
        action="retry",
        governance_run_id=run.id,
        session_id=run.session_id,
        agent_compose_run_id=started.run_id,
        agent_compose_status=started.status,
    )


@router.post(
    "/{project_id}/governance-runs/{run_id}/rerun",
    response_model=GovernanceRunActionPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
def rerun_governance_run(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
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
    source_run = session.exec(
        select(GovernanceRun).where(
            GovernanceRun.id == run_id,
            GovernanceRun.project_id == project.id,
            GovernanceRun.tenant_id == project.tenant_id,
        ).with_for_update()
    ).one_or_none()
    if source_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    actor_subject = str(current_user.id)
    request_ip = get_request_ip_address(request)
    latest_run = session.exec(
        select(GovernanceRun)
        .where(GovernanceRun.project_id == project.id)
        .order_by(
            col(GovernanceRun.created_at).desc(),
            col(GovernanceRun.id).desc(),
        )
        .with_for_update()
    ).first()
    if latest_run is None or latest_run.id != source_run.id:
        existing_rerun = session.exec(
            select(GovernanceRun).where(
                GovernanceRun.project_id == project.id,
                GovernanceRun.trigger_id == trigger_id,
            )
        ).one_or_none()
        if existing_rerun is not None:
            if not governance_run_service.rerun_request_was_recorded(
                session=session,
                source_run=source_run,
                trigger_id=trigger_id,
            ):
                _reject_run_action(
                    session=session,
                    run=source_run,
                    action="governance_run.rerun_rejected",
                    code="run_rerun_trigger_conflict",
                    actor_subject=actor_subject,
                    request_ip=request_ip,
                )
            rerun_request_id = f"{project.id}:{trigger_id}"
            response.status_code = status.HTTP_200_OK
            return GovernanceRunActionPublic(
                accepted=False,
                action="rerun",
                governance_run_id=existing_rerun.id,
                source_governance_run_id=source_run.id,
                session_id=existing_rerun.session_id,
                agent_compose_run_id=AgentComposeClient().expected_run_id(
                    rerun_request_id
                ),
                agent_compose_status="BUSINESS_RUN_ESTABLISHED",
            )
        _reject_run_action(
            session=session,
            run=source_run,
            action="governance_run.rerun_rejected",
            code="run_rerun_newer_run_exists",
            actor_subject=actor_subject,
            request_ip=request_ip,
        )
    if trigger_id == source_run.trigger_id:
        _reject_run_action(
            session=session,
            run=source_run,
            action="governance_run.rerun_rejected",
            code="run_rerun_required",
            actor_subject=actor_subject,
            request_ip=request_ip,
        )

    client = AgentComposeClient()
    client_request_id = f"{project.id}:{trigger_id}"
    expected_run_id = client.expected_run_id(client_request_id)
    try:
        reconciled_trigger = governance_run_service.reconcile_launch_reservation(
            session=session,
            project=project,
            client=client,
            actor_subject=actor_subject,
            request_ip=request_ip,
        )
        if reconciled_trigger is not None:
            session.commit()
    except AgentComposeBoundaryError:
        reconciled_trigger = None
    if reconciled_trigger == trigger_id:
        _reject_run_action(
            session=session,
            run=source_run,
            action="governance_run.rerun_rejected",
            code="run_launch_terminal_use_new_trigger",
            actor_subject=actor_subject,
            request_ip=request_ip,
        )
    existing = session.exec(
        select(GovernanceRun).where(
            GovernanceRun.project_id == project.id,
            GovernanceRun.trigger_id == trigger_id,
        )
    ).one_or_none()
    if existing is not None:
        if not governance_run_service.rerun_request_was_recorded(
            session=session,
            source_run=source_run,
            trigger_id=trigger_id,
        ):
            _reject_run_action(
                session=session,
                run=source_run,
                action="governance_run.rerun_rejected",
                code="run_rerun_trigger_conflict",
                actor_subject=actor_subject,
                request_ip=request_ip,
            )
        response.status_code = status.HTTP_200_OK
        return GovernanceRunActionPublic(
            accepted=False,
            action="rerun",
            governance_run_id=existing.id,
            source_governance_run_id=source_run.id,
            session_id=existing.session_id,
            agent_compose_run_id=expected_run_id,
            agent_compose_status="BUSINESS_RUN_ESTABLISHED",
        )

    known_unrecoverable = (
        source_run.session_terminal_at is not None
        and source_run.session_recovery_code == "run_session_not_recoverable"
    )
    control_session = None
    if not known_unrecoverable:
        try:
            control_session = client.get_session(source_run.session_id)
        except AgentComposeBoundaryError as error:
            session.rollback()
            governance_run_service.record_run_action(
                session=session,
                run=source_run,
                action="governance_run.rerun_rejected",
                actor_subject=actor_subject,
                request_ip=request_ip,
                after_data={"reason": error.code},
            )
            raise _agent_compose_http_error(error)
    if (
        control_session is None
        and not known_unrecoverable
    ) or (
        control_session is not None
        and control_session.observation is AgentComposeSessionObservation.UNKNOWN
    ):
        session.rollback()
        _reject_run_action(
            session=session,
            run=source_run,
            action="governance_run.rerun_rejected",
            code="run_session_state_unknown",
            actor_subject=actor_subject,
            request_ip=request_ip,
        )
    if (
        control_session is not None
        and control_session.observation is AgentComposeSessionObservation.RUNNING
    ):
        session.rollback()
        _reject_run_action(
            session=session,
            run=source_run,
            action="governance_run.rerun_rejected",
            code="run_session_still_running",
            actor_subject=actor_subject,
            request_ip=request_ip,
        )
    if source_run.status == GovernanceRunStatus.RUNNING.value:
        try:
            governance_run_service.require_retry_readiness(
                session=session, project=project, run=source_run
            )
        except governance_run_service.GovernanceRunStateError as error:
            if error.code not in {
                "run_retry_customer_input_changed",
                "run_retry_cloudatlas_input_changed",
            }:
                session.rollback()
                _reject_run_action(
                    session=session,
                    run=source_run,
                    action="governance_run.rerun_rejected",
                    code=error.code,
                    actor_subject=actor_subject,
                    request_ip=request_ip,
                )
        else:
            session.rollback()
            _reject_run_action(
                session=session,
                run=source_run,
                action="governance_run.rerun_rejected",
                code="run_retry_in_progress",
                actor_subject=actor_subject,
                request_ip=request_ip,
            )

    governance_run_service.converge_terminal_run(
        session=session,
        run=source_run,
        actor_subject=actor_subject,
        request_ip=request_ip,
    )
    try:
        pinned = governance_run_service.require_trigger_readiness(
            session=session, project=project
        )
    except governance_run_service.GovernanceRunStateError as error:
        governance_run_service.record_run_action(
            session=session,
            run=source_run,
            action="governance_run.rerun_rejected",
            actor_subject=actor_subject,
            request_ip=request_ip,
            after_data={"reason": error.code},
        )
        raise _state_http_error(error)
    try:
        governance_run_service.reserve_run_launch(
            session=session,
            project=project,
            trigger_id=trigger_id,
            control_run_id=expected_run_id,
            pinned=pinned,
        )
    except governance_run_service.GovernanceRunStateError as error:
        governance_run_service.record_run_action(
            session=session,
            run=source_run,
            action="governance_run.rerun_rejected",
            actor_subject=actor_subject,
            request_ip=request_ip,
            after_data={"reason": error.code},
        )
        raise _state_http_error(error)
    governance_run_service.record_run_action(
        session=session,
        run=source_run,
        action="governance_run.rerun_requested",
        actor_subject=actor_subject,
        request_ip=request_ip,
        after_data={"trigger_id": trigger_id},
    )
    try:
        started = client.start_governance_run(
            client_request_id=client_request_id,
            environment=pinned.runner_environment(
                trigger_id=trigger_id,
                requested_by=actor_subject,
            ),
        )
    except AgentComposeBoundaryError as error:
        session.rollback()
        governance_run_service.record_run_action(
            session=session,
            run=source_run,
            action="governance_run.rerun_rejected",
            actor_subject=actor_subject,
            request_ip=request_ip,
            after_data={"reason": error.code},
        )
        raise _agent_compose_http_error(error)
    return GovernanceRunActionPublic(
        accepted=started.started,
        action="rerun",
        governance_run_id=None,
        source_governance_run_id=source_run.id,
        session_id=None,
        agent_compose_run_id=started.run_id,
        agent_compose_status=started.status,
    )
