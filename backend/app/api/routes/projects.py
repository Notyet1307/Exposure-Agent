import ipaddress
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.models import (
    AuditEvent,
    Project,
    ProjectCreate,
    ProjectPublic,
    ProjectsPublic,
    ProjectUpdate,
    get_datetime_utc,
)

router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    dependencies=[Depends(get_current_active_superuser)],
)


def _request_ip_address(request: Request) -> str | None:
    # Nginx is the only public entry point and replaces this header at the boundary.
    candidates = [request.headers.get("x-real-ip")]
    if request.client is not None:
        candidates.append(request.client.host)
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return None


@router.post("/", response_model=ProjectPublic, status_code=status.HTTP_201_CREATED)
def create_project(
    *,
    session: SessionDep,
    project_in: ProjectCreate,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = Project.model_validate(project_in)
    audit_event = AuditEvent(
        project_id=project.id,
        actor_subject=str(current_user.id),
        actor_type="user",
        action="project.created",
        target_type="project",
        target_id=project.id,
        after_data={"name": project.name},
        ip_address=_request_ip_address(request),
    )
    session.add(project)
    try:
        session.flush()
        session.add(audit_event)
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(project)
    return project


@router.get("/", response_model=ProjectsPublic)
def read_projects(
    session: SessionDep,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> Any:
    count = session.exec(select(func.count()).select_from(Project)).one()
    statement = (
        select(Project)
        .order_by(col(Project.created_at).desc(), col(Project.id).desc())
        .offset(skip)
        .limit(limit)
    )
    projects = session.exec(statement).all()
    return ProjectsPublic(
        data=[ProjectPublic.model_validate(project) for project in projects],
        count=count,
    )


@router.get("/{project_id}", response_model=ProjectPublic)
def read_project(*, session: SessionDep, project_id: uuid.UUID) -> Any:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectPublic)
def rename_project(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    project_in: ProjectUpdate,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    previous_name = project.name
    project.name = project_in.name
    project.updated_at = get_datetime_utc()
    audit_event = AuditEvent(
        project_id=project.id,
        actor_subject=str(current_user.id),
        actor_type="user",
        action="project.renamed",
        target_type="project",
        target_id=project.id,
        before_data={"name": previous_name},
        after_data={"name": project.name},
        ip_address=_request_ip_address(request),
    )
    session.add(project)
    session.add(audit_event)
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(project)
    return project
