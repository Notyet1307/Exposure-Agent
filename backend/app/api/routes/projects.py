import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_
from sqlmodel import Session, col, func, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.request import get_request_ip_address
from app.domain import projects as project_service
from app.domain.models import (
    Project,
    ProjectCreate,
    ProjectMembership,
    ProjectPublic,
    ProjectsPublic,
    ProjectUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def _lock_project(*, session: Session, project_id: uuid.UUID) -> Project:
    project = session.exec(
        select(Project).where(Project.id == project_id).with_for_update()
    ).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


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
    count_statement = select(func.count()).select_from(Project)
    statement = select(Project)
    if not current_user.is_superuser:
        membership_filter = and_(
            col(ProjectMembership.user_id) == current_user.id,
            col(ProjectMembership.revoked_at).is_(None),
        )
        count_statement = count_statement.join(ProjectMembership).where(
            membership_filter
        )
        statement = statement.join(ProjectMembership).where(membership_filter)
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
    statement = select(Project).where(Project.id == project_id)
    if not current_user.is_superuser:
        statement = statement.join(ProjectMembership).where(
            col(ProjectMembership.user_id) == current_user.id,
            col(ProjectMembership.revoked_at).is_(None),
        )
    project = session.exec(statement).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post(
    "/{project_id}/archive",
    response_model=ProjectPublic,
    dependencies=[Depends(get_current_active_superuser)],
)
def archive_project(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = _lock_project(session=session, project_id=project_id)

    return project_service.archive_project(
        session=session,
        project=project,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )


@router.post(
    "/{project_id}/reactivate",
    response_model=ProjectPublic,
    dependencies=[Depends(get_current_active_superuser)],
)
def reactivate_project(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = _lock_project(session=session, project_id=project_id)

    return project_service.reactivate_project(
        session=session,
        project=project,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )


@router.patch(
    "/{project_id}",
    response_model=ProjectPublic,
    dependencies=[Depends(get_current_active_superuser)],
)
def rename_project(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    project_in: ProjectUpdate,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = _lock_project(session=session, project_id=project_id)
    if project.archived_at is not None:
        raise HTTPException(status_code=409, detail="Archived project is read-only")

    return project_service.rename_project(
        session=session,
        project=project,
        project_in=project_in,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )
