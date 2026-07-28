from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlmodel import col, func, select

from app.api.deps import SessionDep, get_current_active_superuser
from app.models import AuditEvent, AuditEventPublic, AuditEventsPublic

router = APIRouter(
    prefix="/audit-events",
    tags=["audit-events"],
    dependencies=[Depends(get_current_active_superuser)],
)


@router.get("/", response_model=AuditEventsPublic)
def read_audit_events(
    session: SessionDep,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> Any:
    count = session.exec(select(func.count()).select_from(AuditEvent)).one()
    statement = (
        select(AuditEvent)
        .order_by(col(AuditEvent.occurred_at).desc(), col(AuditEvent.id).desc())
        .offset(skip)
        .limit(limit)
    )
    events = session.exec(statement).all()
    return AuditEventsPublic(
        data=[AuditEventPublic.model_validate(event) for event in events],
        count=count,
    )
