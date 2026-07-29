import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.project_authorization import (
    PROJECT_READ_ROLES,
    get_authorized_project,
    project_access_filter,
)
from app.api.request import get_request_ip_address
from app.domain import projects as project_service
from app.domain.models import (
    Project,
    ProjectCreate,
    ProjectPublic,
    ProjectsPublic,
    ProjectUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "/",
    response_model=ProjectPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_active_superuser)],
)
def create_project(
    *,
    session: SessionDep,
    project_in: ProjectCreate,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    return project_service.create_project(
        session=session,
        project_in=project_in,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )


@router.get("/", response_model=ProjectsPublic)
def read_projects(
    session: SessionDep,
    current_user: CurrentUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> Any:
    access_filter = project_access_filter(
        user=current_user, allowed_roles=PROJECT_READ_ROLES
    )
    count_statement = select(func.count()).select_from(Project).where(access_filter)
    statement = select(Project).where(access_filter)
    count = session.exec(count_statement).one()
    statement = (
        statement.order_by(col(Project.created_at).desc(), col(Project.id).desc())
        .offset(skip)
        .limit(limit)
    )
    projects = session.exec(statement).all()
    return ProjectsPublic(
        data=[ProjectPublic.model_validate(project) for project in projects],
        count=count,
    )


@router.get("/{project_id}", response_model=ProjectPublic)
def read_project(
    *, session: SessionDep, project_id: uuid.UUID, current_user: CurrentUser
) -> Any:
    return get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )


@router.post(
    "/{project_id}/archive",
    response_model=ProjectPublic,
)
def archive_project(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None,
        lock=True,
    )

    return project_service.archive_project(
        session=session,
        project=project,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )


@router.post(
    "/{project_id}/reactivate",
    response_model=ProjectPublic,
)
def reactivate_project(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None,
        lock=True,
    )

    return project_service.reactivate_project(
        session=session,
        project=project,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )


@router.patch(
    "/{project_id}",
    response_model=ProjectPublic,
)
def rename_project(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    project_in: ProjectUpdate,
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

    return project_service.rename_project(
        session=session,
        project=project,
        project_in=project_in,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )
