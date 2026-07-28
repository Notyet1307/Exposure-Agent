from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.core.time import get_datetime_utc
from app.domain.models import AuditEvent, Project, ProjectCreate, ProjectUpdate


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


def _commit_project_change(
    *, session: Session, project: Project, audit_event: AuditEvent
) -> Project:
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
    project = Project.model_validate(project_in)
    audit_event = _project_audit_event(
        project=project,
        actor_subject=actor_subject,
        action="project.created",
        before_name=None,
        ip_address=ip_address,
    )
    return _commit_project_change(
        session=session, project=project, audit_event=audit_event
    )


def archive_project(
    *,
    session: Session,
    project: Project,
    actor_subject: str,
    ip_address: str | None,
) -> Project:
    if project.archived_at is not None:
        return project

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
    return _commit_project_change(
        session=session, project=project, audit_event=audit_event
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
    return _commit_project_change(
        session=session, project=project, audit_event=audit_event
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
    return _commit_project_change(
        session=session, project=project, audit_event=audit_event
    )
