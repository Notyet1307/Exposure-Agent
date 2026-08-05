import uuid

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.core.time import get_datetime_utc
from app.domain.audit import commit_with_audit
from app.domain.customer_upload_profiles import (
    default_customer_upload_profile_definition,
)
from app.domain.models import (
    AuditEvent,
    CustomerUploadProfile,
    GovernanceRun,
    GovernanceRunStatus,
    Project,
    ProjectCreate,
    ProjectUpdate,
)


def _project_audit_event(
    *,
    project: Project,
    actor_subject: str,
    action: str,
    before_name: str | None,
    ip_address: str | None,
) -> AuditEvent:
    return AuditEvent(
        project_id=project.id,
        actor_subject=actor_subject,
        actor_type="user",
        action=action,
        target_type="project",
        target_id=project.id,
        before_data=None if before_name is None else {"name": before_name},
        after_data={"name": project.name},
        ip_address=ip_address,
    )


def _project_lifecycle_audit_event(
    *,
    project: Project,
    actor_subject: str,
    action: str,
    before_archived_at: str | None,
    ip_address: str | None,
) -> AuditEvent:
    after_archived_at = (
        project.archived_at.isoformat() if project.archived_at is not None else None
    )
    return AuditEvent(
        project_id=project.id,
        actor_subject=actor_subject,
        actor_type="user",
        action=action,
        target_type="project",
        target_id=project.id,
        before_data={"name": project.name, "archived_at": before_archived_at},
        after_data={"name": project.name, "archived_at": after_archived_at},
        ip_address=ip_address,
    )


def create_project(
    *,
    session: Session,
    project_in: ProjectCreate,
    actor_subject: str,
    ip_address: str | None,
) -> Project:
    profile_id = uuid.uuid4()
    project = Project.model_validate(
        project_in,
        update={"current_customer_upload_profile_id": profile_id},
    )
    profile = CustomerUploadProfile(
        id=profile_id,
        tenant_id=project.tenant_id,
        project_id=project.id,
        version=1,
        definition=default_customer_upload_profile_definition().model_dump(),
    )
    audit_event = _project_audit_event(
        project=project,
        actor_subject=actor_subject,
        action="project.created",
        before_name=None,
        ip_address=ip_address,
    )

    try:
        session.add(project)
        session.flush()
        session.add(profile)
        session.flush()
        session.add(audit_event)
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(project)
    return project


class ActiveGovernanceRunError(Exception):
    pass


def archive_project(
    *,
    session: Session,
    project: Project,
    actor_subject: str,
    ip_address: str | None,
) -> Project:
    if project.archived_at is not None:
        return project
    active_run = session.exec(
        select(GovernanceRun).where(
            GovernanceRun.project_id == project.id,
            GovernanceRun.status == GovernanceRunStatus.RUNNING.value,
        )
    ).first()
    if active_run is not None or project.governance_launch_trigger_id is not None:
        raise ActiveGovernanceRunError

    changed_at = get_datetime_utc()
    project.archived_at = changed_at
    project.updated_at = changed_at
    audit_event = _project_lifecycle_audit_event(
        project=project,
        actor_subject=actor_subject,
        action="project.archived",
        before_archived_at=None,
        ip_address=ip_address,
    )
    return commit_with_audit(
        session=session, record=project, audit_event=audit_event
    )


def reactivate_project(
    *,
    session: Session,
    project: Project,
    actor_subject: str,
    ip_address: str | None,
) -> Project:
    if project.archived_at is None:
        return project

    before_archived_at = project.archived_at.isoformat()
    changed_at = get_datetime_utc()
    project.archived_at = None
    project.updated_at = changed_at
    audit_event = _project_lifecycle_audit_event(
        project=project,
        actor_subject=actor_subject,
        action="project.reactivated",
        before_archived_at=before_archived_at,
        ip_address=ip_address,
    )
    return commit_with_audit(
        session=session, record=project, audit_event=audit_event
    )


def rename_project(
    *,
    session: Session,
    project: Project,
    project_in: ProjectUpdate,
    actor_subject: str,
    ip_address: str | None,
) -> Project:
    previous_name = project.name
    project.name = project_in.name
    project.updated_at = get_datetime_utc()
    audit_event = _project_audit_event(
        project=project,
        actor_subject=actor_subject,
        action="project.renamed",
        before_name=previous_name,
        ip_address=ip_address,
    )
    return commit_with_audit(
        session=session, record=project, audit_event=audit_event
    )
