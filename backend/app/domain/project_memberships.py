import uuid

from sqlmodel import Session

from app.core.time import get_datetime_utc
from app.domain.audit import commit_with_audit
from app.domain.models import AuditEvent, ProjectMembership, ProjectRole


def _membership_snapshot(membership: ProjectMembership) -> dict[str, object]:
    return {
        "user_id": str(membership.user_id),
        "roles": membership.roles,
        "status": "revoked" if membership.revoked_at is not None else "active",
    }


def _membership_audit_event(
    *,
    membership: ProjectMembership,
    actor_subject: str,
    action: str,
    before_data: dict[str, object] | None,
    ip_address: str | None,
) -> AuditEvent:
    return AuditEvent(
        project_id=membership.project_id,
        actor_subject=actor_subject,
        actor_type="user",
        action=action,
        target_type="project_membership",
        target_id=membership.id,
        before_data=before_data,
        after_data=_membership_snapshot(membership),
        ip_address=ip_address,
    )


def _change_membership(
    *,
    session: Session,
    membership: ProjectMembership,
    roles: list[ProjectRole],
    actor_subject: str,
    action: str,
    ip_address: str | None,
    revoke: bool = False,
    regrant: bool = False,
) -> ProjectMembership:
    before_data = _membership_snapshot(membership)
    changed_at = get_datetime_utc()
    membership.roles = [role.value for role in roles]
    if revoke:
        membership.revoked_at = changed_at
    elif regrant:
        membership.revoked_at = None
    membership.updated_at = changed_at
    audit_event = _membership_audit_event(
        membership=membership,
        actor_subject=actor_subject,
        action=action,
        before_data=before_data,
        ip_address=ip_address,
    )
    return commit_with_audit(
        session=session, record=membership, audit_event=audit_event
    )


def change_membership_roles(
    *,
    session: Session,
    membership: ProjectMembership,
    roles: list[ProjectRole],
    actor_subject: str,
    ip_address: str | None,
) -> ProjectMembership:
    return _change_membership(
        session=session,
        membership=membership,
        roles=roles,
        actor_subject=actor_subject,
        action="project_membership.roles_changed",
        ip_address=ip_address,
    )


def revoke_membership(
    *,
    session: Session,
    membership: ProjectMembership,
    actor_subject: str,
    ip_address: str | None,
) -> ProjectMembership:
    return _change_membership(
        session=session,
        membership=membership,
        roles=[ProjectRole(role) for role in membership.roles],
        actor_subject=actor_subject,
        action="project_membership.revoked",
        ip_address=ip_address,
        revoke=True,
    )


def regrant_membership(
    *,
    session: Session,
    membership: ProjectMembership,
    roles: list[ProjectRole],
    actor_subject: str,
    ip_address: str | None,
) -> ProjectMembership:
    return _change_membership(
        session=session,
        membership=membership,
        roles=roles,
        actor_subject=actor_subject,
        action="project_membership.regranted",
        ip_address=ip_address,
        regrant=True,
    )


def grant_membership(
    *,
    session: Session,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    roles: list[ProjectRole],
    actor_subject: str,
    ip_address: str | None,
) -> ProjectMembership:
    membership = ProjectMembership(
        project_id=project_id,
        user_id=user_id,
        roles=[role.value for role in roles],
    )
    audit_event = _membership_audit_event(
        membership=membership,
        actor_subject=actor_subject,
        action="project_membership.granted",
        before_data=None,
        ip_address=ip_address,
    )
    return commit_with_audit(
        session=session, record=membership, audit_event=audit_event
    )
