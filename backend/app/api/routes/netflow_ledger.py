import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.api.project_authorization import (
    PROJECT_READ_ROLES,
    get_authorized_project,
    project_access_filter,
)
from app.api.request import get_request_ip_address
from app.api.routes.customer_ledger import Key
from app.domain import netflow_ledger as service
from app.domain.cloudatlas_ledger import CloudLedgerError
from app.domain.customer_ledger import LedgerError as CustomerLedgerError
from app.domain.ip_consistency import IPRecordContractError
from app.domain.models import NetFlowLedgerRevision, Project, ProjectRole

router = APIRouter(
    prefix="/projects/{project_id}/netflow-ledger", tags=["netflow-ledger"]
)


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (service.LedgerError, CustomerLedgerError, CloudLedgerError) as error:
        raise HTTPException(
            status_code=error.status, detail={"code": error.code}
        ) from None
    except ValueError, IPRecordContractError:
        raise HTTPException(
            status_code=422, detail={"code": "netflow_ledger_input_invalid"}
        ) from None


@router.get("", response_model=service.Page)
def read_netflow_ledger(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    response: Response,
    dataset_id: uuid.UUID | None = None,
    revision: Annotated[int | None, Query(ge=0)] = None,
    ip: Annotated[str | None, Query(max_length=45)] = None,
    candidate: bool = False,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> service.Page:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    response.headers["Cache-Control"] = "private, no-store"
    with _errors():
        page = service.read_page(
            session,
            project,
            dataset_id=dataset_id,
            revision=revision,
            ip=ip,
            candidate=candidate,
            skip=skip,
            limit=limit,
        )
    page.can_manage = (
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
    page.can_confirm_scope = project.archived_at is None and current_user.is_superuser
    return page


@router.post("/revisions", response_model=service.RevisionPublic, status_code=201)
def create_netflow_ledger_revision(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    body: service.Edit,
    idempotency_key: Key,
    request: Request,
) -> service.RevisionPublic:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None if body.kind == "scope" else (ProjectRole.OPERATOR,),
        writable=True,
        lock=True,
    )
    if body.kind == "scope" and not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail={"code": "netflow_ledger_scope_admin_required"}
        )
    with _errors():
        return service.RevisionPublic.model_validate(
            service.save(
                session,
                project,
                actor_id=current_user.id,
                key=idempotency_key,
                edit=body,
                ip_address=get_request_ip_address(request),
            ),
            from_attributes=True,
        )


@router.get("/operations/{operation_key}", response_model=service.RevisionPublic)
def read_netflow_ledger_operation(
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
    row = session.exec(
        select(NetFlowLedgerRevision).where(
            NetFlowLedgerRevision.project_id == project.id,
            NetFlowLedgerRevision.tenant_id == project.tenant_id,
            NetFlowLedgerRevision.created_by == current_user.id,
            NetFlowLedgerRevision.operation_key == operation_key,
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404, detail={"code": "netflow_ledger_operation_not_found"}
        )
    return service.RevisionPublic.model_validate(row, from_attributes=True)


@router.get("/revisions", response_model=list[service.RevisionPublic])
def read_netflow_ledger_revisions(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[service.RevisionPublic]:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    with _errors():
        if dataset_id is not None:
            service._dataset(session, project, dataset_id)
        records = service._events(session, project)
        if dataset_id is not None:
            records = [r for r in records if r.dataset_id == dataset_id]
        return [
            service.RevisionPublic.model_validate(r)
            for r in list(reversed(records))[skip : skip + limit]
        ]


@router.get("/profile", response_model=service.Profile)
def read_netflow_ledger_profile(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    response: Response,
    dataset_id: uuid.UUID,
    ip: Annotated[str, Query(min_length=1, max_length=45)],
    revision: Annotated[int | None, Query(ge=0)] = None,
    upload_id: uuid.UUID | None = None,
    customer_revision_id: uuid.UUID | None = None,
    snapshot_id: uuid.UUID | None = None,
    cloud_revision: Annotated[int | None, Query(ge=0)] = None,
) -> service.Profile:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    response.headers["Cache-Control"] = "private, no-store"
    with _errors():
        return service.profile(
            session,
            project,
            dataset_id=dataset_id,
            ip=ip,
            revision=revision,
            upload_id=upload_id,
            customer_revision_id=customer_revision_id,
            snapshot_id=snapshot_id,
            cloud_revision=cloud_revision,
        )
