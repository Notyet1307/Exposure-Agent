import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.api.project_authorization import PROJECT_READ_ROLES, get_authorized_project
from app.api.request import get_request_ip_address
from app.domain import cloudatlas_sources as source_service
from app.domain.models import (
    CloudAtlasSourceCreate,
    CloudAtlasSourcePublic,
    CloudAtlasSourcesPublic,
    CloudAtlasSourceUpdate,
    CloudAtlasSourceValidationRequest,
    SourceInstance,
)

router = APIRouter(prefix="/projects", tags=["cloudatlas-source-instances"])

_ERROR_MESSAGES = {
    "octobus_authentication_failed": "OctoBus authentication failed.",
    "cloudatlas_authentication_failed": "CloudAtlas authentication failed.",
    "cloudatlas_authorization_failed": "CloudAtlas authorization failed.",
    "cloudatlas_connectivity_failed": "CloudAtlas could not be reached.",
    "cloudatlas_upstream_failed": "CloudAtlas returned an upstream failure.",
    "cloudatlas_response_contract_failed": (
        "CloudAtlas returned an invalid response contract."
    ),
    "cloudatlas_validation_required": (
        "The current CloudAtlas configuration must be validated before enabling."
    ),
    "cloudatlas_source_conflict": (
        "Only one CloudAtlas SourceInstance can be enabled for a Project."
    ),
}


def _source_or_404(
    *, session: SessionDep, project_id: uuid.UUID, source_id: uuid.UUID
) -> SourceInstance:
    source = session.exec(
        select(SourceInstance).where(
            SourceInstance.id == source_id,
            SourceInstance.project_id == project_id,
        )
    ).one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="SourceInstance not found")
    return source


def _boundary_http_error(error: source_service.CloudAtlasBoundaryError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": _ERROR_MESSAGES[error.code]},
    )


def _state_http_error(error: source_service.CloudAtlasStateError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": error.code, "message": _ERROR_MESSAGES[error.code]},
    )


def _conflict_http_error() -> HTTPException:
    code = "cloudatlas_source_conflict"
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": _ERROR_MESSAGES[code]},
    )


@router.get(
    "/{project_id}/cloudatlas-source-instances",
    response_model=CloudAtlasSourcesPublic,
)
def read_cloudatlas_sources(
    *, session: SessionDep, project_id: uuid.UUID, current_user: CurrentUser
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    sources = session.exec(
        select(SourceInstance)
        .where(SourceInstance.project_id == project.id)
        .order_by(col(SourceInstance.created_at).desc(), col(SourceInstance.id).desc())
    ).all()
    count = session.exec(
        select(func.count())
        .select_from(SourceInstance)
        .where(SourceInstance.project_id == project.id)
    ).one()
    return CloudAtlasSourcesPublic(
        data=[
            source_service.source_public(
                source,
                session=(
                    session
                    if current_user.is_superuser and project.archived_at is None
                    else None
                ),
            )
            for source in sources
        ],
        count=count,
        can_manage=current_user.is_superuser and project.archived_at is None,
    )


@router.post(
    "/{project_id}/cloudatlas-source-instances",
    response_model=CloudAtlasSourcePublic,
    status_code=status.HTTP_201_CREATED,
)
def create_cloudatlas_source(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    source_in: CloudAtlasSourceCreate,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None,
        writable=True,
    )
    try:
        source = source_service.create_source(
            session=session,
            project=project,
            source_in=source_in,
            actor_subject=str(current_user.id),
            ip_address=get_request_ip_address(request),
        )
    except source_service.ActiveSourceConflictError:
        raise _conflict_http_error()
    return source_service.source_public(source, check_current=False)


@router.patch(
    "/{project_id}/cloudatlas-source-instances/{source_id}",
    response_model=CloudAtlasSourcePublic,
)
def update_cloudatlas_source(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    source_in: CloudAtlasSourceUpdate,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None,
        writable=True,
    )
    source = _source_or_404(
        session=session, project_id=project.id, source_id=source_id
    )
    updated = source_service.update_source(
        session=session,
        source=source,
        source_in=source_in,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )
    return source_service.source_public(updated, check_current=False)


@router.post(
    "/{project_id}/cloudatlas-source-instances/{source_id}/validate",
    response_model=CloudAtlasSourcePublic,
)
def validate_cloudatlas_source(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    validation_in: CloudAtlasSourceValidationRequest,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None,
        writable=True,
    )
    source = _source_or_404(
        session=session, project_id=project.id, source_id=source_id
    )
    try:
        validated = source_service.validate_source(
            session=session,
            source=source,
            capset_token=validation_in.capset_token.get_secret_value(),
            actor_subject=str(current_user.id),
            ip_address=get_request_ip_address(request),
        )
    except source_service.CloudAtlasBoundaryError as error:
        raise _boundary_http_error(error)
    return source_service.source_public(validated, check_current=False)


@router.post(
    "/{project_id}/cloudatlas-source-instances/{source_id}/enable",
    response_model=CloudAtlasSourcePublic,
)
def enable_cloudatlas_source(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None,
        writable=True,
    )
    source = _source_or_404(
        session=session, project_id=project.id, source_id=source_id
    )
    try:
        enabled = source_service.set_source_enabled(
            session=session,
            source=source,
            enabled=True,
            actor_subject=str(current_user.id),
            ip_address=get_request_ip_address(request),
        )
    except source_service.CloudAtlasBoundaryError as error:
        raise _boundary_http_error(error)
    except source_service.CloudAtlasStateError as error:
        raise _state_http_error(error)
    except source_service.ActiveSourceConflictError:
        raise _conflict_http_error()
    return source_service.source_public(enabled, check_current=False)


@router.post(
    "/{project_id}/cloudatlas-source-instances/{source_id}/disable",
    response_model=CloudAtlasSourcePublic,
)
def disable_cloudatlas_source(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None,
        writable=True,
    )
    source = _source_or_404(
        session=session, project_id=project.id, source_id=source_id
    )
    disabled = source_service.set_source_enabled(
        session=session,
        source=source,
        enabled=False,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )
    return source_service.source_public(disabled, check_current=False)
