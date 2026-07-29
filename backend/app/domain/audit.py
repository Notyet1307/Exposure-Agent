from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, SQLModel

from app.domain.models import AuditEvent


def commit_with_audit[RecordT: SQLModel](
    *, session: Session, record: RecordT, audit_event: AuditEvent
) -> RecordT:
    session.add(record)
    try:
        session.flush()
        session.add(audit_event)
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(record)
    return record
