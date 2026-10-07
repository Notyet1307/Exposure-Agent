"""Read-only component facts and append-only human feedback endpoints."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.netflow_http import ERROR_RESPONSES, NetFlowRoute
from app.domain import netflow_reviews as service
from app.domain.ip_consistency import IPRecordContractError
from app.domain.netflow_common import project_for
from app.integrations.netflow_processor import ProcessorError

router = APIRouter(
    prefix="/projects/{project_id}/netflow-analyses/{analysis_id}",
    tags=["netflow-reviews"],
    route_class=NetFlowRoute,
    responses=ERROR_RESPONSES,
)
Key = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]
Skip = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except ProcessorError as error:
        raise HTTPException(
            status_code=error.status, detail={"code": error.code}
        ) from None
    except IPRecordContractError:
        raise HTTPException(
            status_code=422, detail={"code": "netflow_artifact_schema_invalid"}
        ) from None


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


@router.get("/peers", response_model=service.PeerPage)
def read_peers(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
    response: Response,
    ip: Annotated[str | None, Query(max_length=45)] = None,
    protocol: Annotated[int | None, Query(ge=0, le=255)] = None,
    peer_port: Annotated[int | None, Query(ge=0, le=65535)] = None,
    sort: Literal["ip_asc", "ip_desc"] = "ip_asc",
    skip: Skip = 0,
    limit: Limit = 25,
) -> service.PeerPage:
    _private(response)
    project = project_for(session, current_user, project_id)
    with _errors():
        return service.read_peers(
            session,
            project,
            analysis_id,
            ip=ip,
            protocol=protocol,
            peer_port=peer_port,
            sort=sort,
            skip=skip,
            limit=limit,
        )


@router.get("/observations", response_model=service.ObservationPage)
def read_observations(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
    response: Response,
    ip: Annotated[str | None, Query(max_length=45)] = None,
    protocol: Annotated[int | None, Query(ge=0, le=255)] = None,
    source_port: Annotated[int | None, Query(ge=0, le=65535)] = None,
    sort: Literal["ip_asc", "ip_desc"] = "ip_asc",
    skip: Skip = 0,
    limit: Limit = 25,
) -> service.ObservationPage:
    _private(response)
    project = project_for(session, current_user, project_id)
    with _errors():
        return service.read_observations(
            session,
            project,
            analysis_id,
            ip=ip,
            protocol=protocol,
            source_port=source_port,
            sort=sort,
            skip=skip,
            limit=limit,
        )


@router.get("/observations/{object_key}", response_model=service.ObservationDetail)
def read_observation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
    object_key: str,
    response: Response,
) -> service.ObservationDetail:
    _private(response)
    project = project_for(session, current_user, project_id)
    with _errors():
        return service.read_observation(session, project, analysis_id, object_key)


@router.get("/review-tasks", response_model=service.TaskPage)
def read_tasks(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
    response: Response,
    feedback_revision_id: uuid.UUID | None = None,
    task_scope: Literal["object", "dataset"] | None = None,
    task_kind: Annotated[str | None, Query(max_length=128)] = None,
    material_status: service.MaterialStatus | None = None,
    object_key: Annotated[str | None, Query(max_length=256)] = None,
    skip: Skip = 0,
    limit: Limit = 25,
) -> service.TaskPage:
    _private(response)
    project = project_for(session, current_user, project_id)
    with _errors():
        return service.read_tasks(
            session,
            project,
            analysis_id,
            feedback_revision_id=feedback_revision_id,
            task_scope=task_scope,
            task_kind=task_kind,
            material_status=material_status,
            object_key=object_key,
            skip=skip,
            limit=limit,
        )


@router.get("/review-tasks/{task_id}", response_model=service.TaskDetail)
def read_task(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
    task_id: str,
    response: Response,
    feedback_revision_id: uuid.UUID | None = None,
) -> service.TaskDetail:
    _private(response)
    project = project_for(session, current_user, project_id)
    with _errors():
        return service.read_task(
            session, project, analysis_id, task_id, feedback_revision_id
        )


@router.get("/feedback", response_model=service.FeedbackPublic)
def read_feedback(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
    response: Response,
    feedback_revision_id: uuid.UUID | None = None,
) -> service.FeedbackPublic:
    _private(response)
    project = project_for(session, current_user, project_id)
    with _errors():
        return service.read_feedback(
            session, project, analysis_id, feedback_revision_id
        )


@router.post("/feedback", response_model=service.FeedbackPublic, status_code=201)
def append_feedback(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
    body: service.FeedbackPatch,
    idempotency_key: Key,
) -> service.FeedbackPublic:
    project = project_for(session, current_user, project_id, write=True)
    with _errors():
        return service.append_feedback(
            session,
            project,
            analysis_id,
            actor_id=current_user.id,
            key=idempotency_key,
            body=body,
        )


@router.get("/feedback/operations/{key}", response_model=service.FeedbackPublic)
def read_operation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
    key: str,
    response: Response,
) -> service.FeedbackPublic:
    _private(response)
    project = project_for(session, current_user, project_id)
    with _errors():
        return service.read_operation(
            session, project, analysis_id, current_user.id, key
        )


@router.get("/evidence", response_model=service.EvidencePage)
def read_evidence(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    analysis_id: uuid.UUID,
    response: Response,
    request: Request,
    object_key: Annotated[str | None, Query(max_length=256)] = None,
    peer_key: Annotated[str | None, Query(max_length=256)] = None,
    skip: Skip = 0,
    limit: Limit = 25,
) -> service.EvidencePage:
    _private(response)
    project = project_for(session, current_user, project_id)
    if set(request.query_params) - {"object_key", "peer_key", "skip", "limit"}:
        raise HTTPException(
            status_code=422, detail={"code": "netflow_artifact_schema_invalid"}
        )
    with _errors():
        return service.read_evidence(
            session,
            project,
            analysis_id,
            object_key=object_key,
            peer_key=peer_key,
            skip=skip,
            limit=limit,
        )
