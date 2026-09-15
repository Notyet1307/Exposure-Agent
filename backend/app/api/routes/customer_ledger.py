import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.api.project_authorization import (
    PROJECT_READ_ROLES,
    get_authorized_project,
    project_access_filter,
)
from app.api.request import get_request_ip_address
from app.domain import customer_ledger as service
from app.domain.ip_consistency import IPRecordContractError
from app.domain.models import CustomerLedgerRevision, Project, ProjectRole

router = APIRouter(
    prefix="/projects/{project_id}/customer-ledger", tags=["customer-ledger"]
)
Key = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]


def _error(error: service.LedgerError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"code": error.code})


@router.get("", response_model=service.LedgerPage)
def read_customer_ledger(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    upload_id: uuid.UUID | None = None,
    revision_id: uuid.UUID | None = None,
    original: bool = False,
    query: Annotated[str, Query(max_length=200)] = "",
    ip: Annotated[str | None, Query(max_length=45)] = None,
    archived: bool = False,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> service.LedgerPage:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    can_write = (
        project.archived_at is None
        and session.exec(
            select(Project.id).where(
                Project.id == project.id,
                project_access_filter(
                    user=current_user, allowed_roles=(ProjectRole.OPERATOR,)
                ),
            )
        ).first()
        is not None
    )
    try:
        return service.read_page(
            session,
            project,
            upload_id=upload_id,
            revision_id=revision_id,
            original=original,
            query=query,
            ip=ip,
            archived=archived,
            skip=skip,
            limit=limit,
            can_write=can_write,
        )
    except service.LedgerError as error:
        raise _error(error) from None
    except ValueError, IPRecordContractError:
        raise HTTPException(
            status_code=422, detail={"code": "ledger_ip_invalid"}
        ) from None


@router.get("/revisions", response_model=list[service.RevisionPublic])
def read_customer_ledger_revisions(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[service.RevisionPublic]:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    rows = session.exec(
        select(CustomerLedgerRevision)
        .where(
            CustomerLedgerRevision.project_id == project.id,
            CustomerLedgerRevision.tenant_id == project.tenant_id,
        )
        .order_by(
            col(CustomerLedgerRevision.created_at).desc(),
            col(CustomerLedgerRevision.id).desc(),
        )
        .offset(skip)
        .limit(limit)
    ).all()
    return [service.public_revision(row) for row in rows]


@router.post("/revisions", response_model=service.RevisionPublic, status_code=201)
def create_customer_ledger_revision(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    request: Request,
    idempotency_key: Key,
    body: service.LedgerEdit,
) -> service.RevisionPublic:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=(ProjectRole.OPERATOR,),
        writable=True,
    )
    try:
        return service.public_revision(
            service.save(
                session,
                project,
                actor_id=current_user.id,
                key=idempotency_key,
                edit=body,
                ip_address=get_request_ip_address(request),
            )
        )
    except service.LedgerError as error:
        raise _error(error) from None


@router.get("/operations/{operation_key}", response_model=service.RevisionPublic)
def read_customer_ledger_operation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    operation_key: str,
) -> service.RevisionPublic:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    record = service.recover(session, project, current_user.id, operation_key)
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "ledger_operation_not_found"}
        )
    return service.public_revision(record)
