import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.api.project_authorization import get_authorized_project
from app.api.request import get_request_ip_address
from app.domain import project_memberships as membership_service
from app.domain.models import (
    ProjectMembership,
    ProjectMembershipCreate,
    ProjectMembershipPublic,
    ProjectMembershipsPublic,
    ProjectMembershipUpdate,
)
from app.models import User

router = APIRouter(
    prefix="/projects/{project_id}/memberships",
    tags=["project-memberships"],
)


def _lock_membership(
    *, session: SessionDep, project_id: uuid.UUID, membership_id: uuid.UUID
) -> ProjectMembership:
    membership = session.exec(
        select(ProjectMembership)
        .where(
            ProjectMembership.id == membership_id,
            ProjectMembership.project_id == project_id,
        )
        .with_for_update()
    ).one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    return membership


@router.get("/", response_model=ProjectMembershipsPublic)
def read_project_memberships(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    current_user: CurrentUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> Any:
    get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None,
    )
    filters = ProjectMembership.project_id == project_id
    count = session.exec(
        select(func.count()).select_from(ProjectMembership).where(filters)
    ).one()
    memberships = session.exec(
        select(ProjectMembership)
        .where(filters)
        .order_by(col(ProjectMembership.created_at), col(ProjectMembership.id))
        .offset(skip)
        .limit(limit)
    ).all()
    return ProjectMembershipsPublic(
        data=[
            ProjectMembershipPublic.model_validate(membership)
            for membership in memberships
        ],
        count=count,
    )


@router.post(
    "/", response_model=ProjectMembershipPublic, status_code=status.HTTP_201_CREATED
)
def grant_project_membership(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    membership_in: ProjectMembershipCreate,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None,
        writable=True,
    )
    user = session.get(User, membership_in.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_superuser:
        raise HTTPException(
            status_code=409, detail="Global Admin cannot have a project membership"
        )
    try:
        return membership_service.grant_membership(
            session=session,
            project_id=project_id,
            user_id=user.id,
            roles=membership_in.roles,
            actor_subject=str(current_user.id),
            ip_address=get_request_ip_address(request),
        )
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Membership already exists")


@router.patch("/{membership_id}", response_model=ProjectMembershipPublic)
def change_project_membership_roles(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    membership_id: uuid.UUID,
    membership_in: ProjectMembershipUpdate,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None,
        writable=True,
    )
    membership = _lock_membership(
        session=session, project_id=project_id, membership_id=membership_id
    )
    if membership.revoked_at is not None:
        raise HTTPException(status_code=409, detail="Membership is revoked")
    requested_roles = [role.value for role in membership_in.roles]
    if membership.roles == requested_roles:
        return membership
    return membership_service.change_membership_roles(
        session=session,
        membership=membership,
        roles=membership_in.roles,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )


@router.post("/{membership_id}/revoke", response_model=ProjectMembershipPublic)
def revoke_project_membership(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    membership_id: uuid.UUID,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None,
        writable=True,
    )
    membership = _lock_membership(
        session=session, project_id=project_id, membership_id=membership_id
    )
    if membership.revoked_at is not None:
        return membership
    return membership_service.revoke_membership(
        session=session,
        membership=membership,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )


@router.post("/{membership_id}/regrant", response_model=ProjectMembershipPublic)
def regrant_project_membership(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    membership_id: uuid.UUID,
    membership_in: ProjectMembershipUpdate,
    current_user: CurrentUser,
    request: Request,
) -> Any:
    get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None,
        writable=True,
    )
    membership = _lock_membership(
        session=session, project_id=project_id, membership_id=membership_id
    )
    if membership.revoked_at is None:
        raise HTTPException(status_code=409, detail="Membership is already active")
    return membership_service.regrant_membership(
        session=session,
        membership=membership,
        roles=membership_in.roles,
        actor_subject=str(current_user.id),
        ip_address=get_request_ip_address(request),
    )
