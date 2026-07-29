import uuid
from collections.abc import Collection

from fastapi import HTTPException
from sqlalchemy import false, true
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session, col, select

from app.domain.models import Project, ProjectMembership, ProjectRole
from app.models import User

PROJECT_READ_ROLES = tuple(ProjectRole)


def project_access_filter(
    *, user: User, allowed_roles: Collection[ProjectRole] | None
) -> ColumnElement[bool]:
    if not user.is_active:
        return false()
    if user.is_superuser:
        return true()
    if not allowed_roles:
        return false()
    return (
        select(ProjectMembership.id)
        .where(
            col(ProjectMembership.project_id) == col(Project.id),
            col(ProjectMembership.user_id) == user.id,
            col(ProjectMembership.revoked_at).is_(None),
            col(ProjectMembership.roles).op("&&")(
                [role.value for role in allowed_roles]
            ),
        )
        .exists()
    )


def get_authorized_project(
    *,
    session: Session,
    user: User,
    project_id: uuid.UUID,
    allowed_roles: Collection[ProjectRole] | None,
    writable: bool = False,
    lock: bool = False,
) -> Project:
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    if not user.is_superuser and not allowed_roles:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )

    statement = select(Project).where(
        Project.id == project_id,
        project_access_filter(user=user, allowed_roles=allowed_roles),
    )
    if writable or lock:
        statement = statement.with_for_update()
    project = session.exec(statement).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if writable and project.archived_at is not None:
        raise HTTPException(status_code=409, detail="Archived project is read-only")
    return project
