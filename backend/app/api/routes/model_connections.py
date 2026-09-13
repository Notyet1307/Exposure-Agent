"""Authenticated management and a separate task-capability-only internal proxy."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlmodel import Session, col, select
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core.config import settings
from app.core.db import engine
from app.domain import model_connections as service
from app.domain.models import (
    DEPLOYMENT_TENANT_ID,
    AiGovernanceDraft,
    AiInvestigation,
    AnalysisReport,
    ModelConnectionOperation,
    ModelConnectionState,
    ModelQualificationResult,
)
from app.integrations import model_connection_runtime as runtime
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
    AgentComposeDraftNamespace,
    AgentComposeSessionObservation,
)
from app.models import User

router = APIRouter(prefix="/model-connections", tags=["model-connections"])
Admin = Annotated[User, Depends(get_current_active_superuser)]
Intent = Annotated[str, Header(alias="Idempotency-Key")]


def _error(error: service.ModelConnectionError) -> HTTPException:
    return HTTPException(
        status_code=404 if error.code == "model_connection_not_found" else 409,
        detail={
            "code": error.code,
            "message": "The model connection operation could not be completed.",
        },
    )


def _op(
    session: Session, operation_id: uuid.UUID, actor: User
) -> ModelConnectionOperation:
    op = session.get(ModelConnectionOperation, operation_id)
    if op is None or op.actor_id != actor.id or op.tenant_id != DEPLOYMENT_TENANT_ID:
        raise HTTPException(
            status_code=404, detail={"code": "model_connection_operation_not_found"}
        )
    return op


def _legacy_drained() -> None:
    """No old, unversioned execution may become unmanageable on first adoption."""
    with Session(engine) as session:
        jobs = []
        records: list[AiInvestigation | AnalysisReport | AiGovernanceDraft] = [
            *session.exec(select(AiInvestigation)).all(),
            *session.exec(select(AnalysisReport)).all(),
            *session.exec(select(AiGovernanceDraft)).all(),
        ]
        for record in records:
            if getattr(record, "connection_version_id", None) is not None:
                continue
            if record.status == "GENERATING":
                raise service.ModelConnectionError("legacy_binding_unknown")
            if record.session_id:
                jobs.append(
                    (
                        record.agent_compose_project_id,
                        record.agent_compose_agent_name,
                        record.session_id,
                    )
                )
        quals = list(
            session.exec(
                select(ModelQualificationResult).where(
                    col(ModelQualificationResult.agent_compose_run_id).is_not(None)
                )
            ).all()
        )
    try:
        for project, agent, sandbox in jobs:
            if not project or not agent:
                raise service.ModelConnectionError("legacy_binding_unknown")
            client = AgentComposeClient(
                ai_governance_draft_namespace=AgentComposeDraftNamespace(
                    project_id=project, agent_name=agent
                )
            )
            observed = client.get_session(sandbox)
            if (
                observed is None
                or observed.observation != AgentComposeSessionObservation.TERMINAL
            ):
                raise service.ModelConnectionError("legacy_binding_unknown")
        client = AgentComposeClient()
        for result in quals:
            if result.agent_compose_run_id is None:
                continue
            observed_run = client.get_run(result.agent_compose_run_id)
            if observed_run is None or not observed_run.is_terminal:
                raise service.ModelConnectionError("legacy_binding_unknown")
    except AgentComposeBoundaryError:
        raise service.ModelConnectionError("legacy_binding_unknown") from None


@router.get("/status", response_model=service.ConnectionStatus)
def status(session: SessionDep, _current_user: CurrentUser) -> service.ConnectionStatus:
    state = session.get(ModelConnectionState, DEPLOYMENT_TENANT_ID)
    if state is None or not state.adopted:
        configured = bool(settings.MODEL_API_KEY.get_secret_value())
        qualified = False
        if configured:
            from app.domain.model_qualification import (
                current_model_is_qualified,
                model_binding,
            )

            try:
                binding = model_binding(
                    endpoint=settings.MODEL_API_ENDPOINT,
                    model_identity=settings.MODEL_IDENTITY,
                    protocol=settings.MODEL_API_PROTOCOL,
                    config_revision=settings.MODEL_CONFIG_REVISION,
                    runner_build_version=settings.RUNNER_BUILD_VERSION,
                    agent_compose_runtime_version=settings.AGENT_COMPOSE_RUNTIME_VERSION,
                    allow_baizhi_test=settings.MODEL_QUALIFICATION_ALLOW_BAIZHI_TEST,
                )
                qualified = current_model_is_qualified(
                    session=session,
                    endpoint=binding.endpoint,
                    model_identity=binding.model_identity,
                    config_fingerprint=binding.config_fingerprint,
                )
            except ValueError:
                pass
        return service.ConnectionStatus(
            state="legacy" if configured else "unconfigured",
            configured=configured,
            ready=qualified,
            model_identity=settings.MODEL_IDENTITY or None,
            reason="legacy_connection_not_adopted" if configured else None,
        )
    if state.active_id is None:
        return service.ConnectionStatus(state="disabled", configured=False, ready=False)
    version = service.get_version(session, state.active_id)
    try:
        service.binding_for_task(session, "qualification")
        service.provider_key(session, version)
    except service.ModelConnectionError as error:
        return service.ConnectionStatus(
            state="unavailable",
            configured=True,
            ready=False,
            active_version_id=version.id,
            model_identity=version.model_identity,
            reason=error.code,
        )
    return service.ConnectionStatus(
        state="active",
        configured=True,
        ready=True,
        active_version_id=version.id,
        model_identity=version.model_identity,
    )


@router.get("", response_model=service.ConnectionStatePublic)
def read_connections(
    session: SessionDep, _current_user: Admin
) -> service.ConnectionStatePublic:
    return service.state_public(session)


@router.post("", response_model=service.ConnectionActionPublic, status_code=201)
def save(
    session: SessionDep,
    current_user: Admin,
    body: service.SaveConnection,
    response: Response,
    idempotency_key: Intent,
) -> service.ConnectionActionPublic:
    try:
        op, replayed = service.save_connection(
            session, current_user, body, idempotency_key
        )
    except service.ModelConnectionError as error:
        raise _error(error) from None
    response.status_code = 200 if replayed else 201
    return service.action_public(session, op)


@router.post(
    "/adopt-legacy", response_model=service.ConnectionActionPublic, status_code=201
)
def adopt_legacy(
    session: SessionDep,
    current_user: Admin,
    body: service.ExpectedGeneration,
    response: Response,
    idempotency_key: Intent,
) -> service.ConnectionActionPublic:
    if not settings.MODEL_API_KEY.get_secret_value():
        raise _error(service.ModelConnectionError("model_connection_legacy_missing"))
    try:
        request = service.SaveConnection(
            expected_generation=body.expected_generation,
            name="Imported deployment connection",
            endpoint=settings.MODEL_API_ENDPOINT,
            protocol=settings.MODEL_API_PROTOCOL,
            model_identity=settings.MODEL_IDENTITY,
            api_key=settings.MODEL_API_KEY,
        )
        op, replayed = service.save_connection(
            session, current_user, request, idempotency_key, adopt=True
        )
    except service.ModelConnectionError as error:
        raise _error(error) from None
    except ValueError:
        raise _error(
            service.ModelConnectionError("model_connection_legacy_invalid")
        ) from None
    response.status_code = 200 if replayed else 201
    return service.action_public(session, op)


@router.post("/{connection_id}/{action}", response_model=service.ConnectionActionPublic)
def action(
    session: SessionDep,
    current_user: Admin,
    connection_id: uuid.UUID,
    action: str,
    body: service.ExpectedGeneration,
    idempotency_key: Intent,
) -> service.ConnectionActionPublic:
    actions = {
        "validate": "VALIDATE",
        "activate": "ACTIVATE",
        "revoke": "REVOKE",
        "discard": "DISCARD",
    }
    if action not in actions:
        raise HTTPException(
            status_code=404, detail={"code": "model_connection_action_not_found"}
        )
    try:
        op, _ = service.begin_action(
            session, current_user, connection_id, actions[action], body, idempotency_key
        )
        if op.status not in {"SUCCEEDED", "FAILED"}:
            if action == "validate":
                runtime.start_validation(op.id)
            elif action == "activate":
                failure = None
                try:
                    state = session.get(ModelConnectionState, DEPLOYMENT_TENANT_ID)
                    if state is None or not state.adopted:
                        _legacy_drained()
                    runtime.ensure_project(
                        service.get_version(session, connection_id), create=False
                    )
                except (
                    service.ModelConnectionError,
                    AgentComposeBoundaryError,
                ) as error:
                    failure = error.code
                session.rollback()
                service.activate_after_attestation(session, op.id, failure=failure)
        session.expire_all()
        op = _op(session, op.id, current_user)
        return service.action_public(session, op)
    except service.ModelConnectionError as error:
        raise _error(error) from None


@router.get(
    "/operations/recover/{action}", response_model=service.ConnectionActionPublic
)
def recover_operation(
    session: SessionDep, current_user: Admin, action: str, idempotency_key: Intent
) -> service.ConnectionActionPublic:
    # Observation only: no Secret resolution, write lock, or runtime call.
    op = session.exec(
        select(ModelConnectionOperation).where(
            ModelConnectionOperation.tenant_id == DEPLOYMENT_TENANT_ID,
            ModelConnectionOperation.actor_id == current_user.id,
            ModelConnectionOperation.action == action.upper(),
            ModelConnectionOperation.idempotency_key == idempotency_key,
        )
    ).first()
    if op is None:
        raise HTTPException(
            status_code=404, detail={"code": "model_connection_operation_not_found"}
        )
    return service.action_public(session, op)


@router.get("/operations/{operation_id}", response_model=service.ConnectionActionPublic)
def operation(
    session: SessionDep, current_user: Admin, operation_id: uuid.UUID
) -> service.ConnectionActionPublic:
    _op(session, operation_id, current_user)
    runtime.reconcile_validation(operation_id)  # Observe only; never starts or applies.
    session.expire_all()
    return service.action_public(session, _op(session, operation_id, current_user))


@router.post("/internal/{lease_id}/{suffix:path}", include_in_schema=False)
async def proxy(lease_id: uuid.UUID, suffix: str, request: Request) -> Response:
    from app.domain.model_connection_proxy import MAX_PROXY_BODY, forward

    authorization = request.headers.get("Authorization", "")
    if (
        not authorization.startswith("Bearer ")
        or request.headers.get("Content-Encoding", "identity") != "identity"
        or request.url.query
    ):
        raise HTTPException(
            status_code=403, detail={"code": "model_connection_proxy_denied"}
        )
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_PROXY_BODY:
            raise HTTPException(
                status_code=413, detail={"code": "model_connection_request_too_large"}
            )
    try:
        data, content_type = await run_in_threadpool(
            forward, lease_id, authorization[7:], suffix, bytes(raw)
        )
    except ValueError:
        raise HTTPException(
            status_code=403, detail={"code": "model_connection_proxy_denied"}
        ) from None
    return Response(content=data, media_type=content_type)
