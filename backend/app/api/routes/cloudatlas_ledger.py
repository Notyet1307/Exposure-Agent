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
from app.domain import cloudatlas_ledger as service
from app.domain.customer_ledger import LedgerError
from app.domain.ip_consistency import IPRecordContractError
from app.domain.models import Project, ProjectRole

router = APIRouter(
    prefix="/projects/{project_id}/cloudatlas-ledger", tags=["cloudatlas-ledger"]
)
Skip = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]
Revision = Annotated[int | None, Query(ge=0)]
IP = Annotated[str | None, Query(max_length=45)]


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (service.CloudLedgerError, LedgerError) as error:
        raise HTTPException(
            status_code=error.status, detail={"code": error.code}
        ) from None
    except IPRecordContractError, ValueError:
        raise HTTPException(
            status_code=422, detail={"code": "cloud_ledger_input_invalid"}
        ) from None


@router.get("", response_model=service.CloudLedgerPage)
def read_cloudatlas_ledger(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    response: Response,
    source_id: uuid.UUID | None = None,
    snapshot_id: uuid.UUID | None = None,
    revision: Revision = None,
    ip: IP = None,
    asset_id: Annotated[str | None, Query(max_length=255)] = None,
    skip: Skip = 0,
    limit: Limit = 25,
) -> service.CloudLedgerPage:
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
            source_id=source_id,
            snapshot_id=snapshot_id,
            revision=revision,
            ip=ip,
            asset_id=asset_id,
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


@router.get("/snapshots", response_model=list[service.CloudSnapshotPublic])
def read_cloudatlas_ledger_snapshots(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    response: Response,
    skip: Skip = 0,
    limit: Limit = 25,
) -> list[service.CloudSnapshotPublic]:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    response.headers["Cache-Control"] = "private, no-store"
    with _errors():
        return service.snapshots(session, project, source_id, skip, limit)


@router.get("/revisions", response_model=list[service.CloudRevisionPublic])
def read_cloudatlas_ledger_revisions(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    response: Response,
    skip: Skip = 0,
    limit: Limit = 25,
) -> list[service.CloudRevisionPublic]:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    response.headers["Cache-Control"] = "private, no-store"
    with _errors():
        service.read_page(session, project, snapshot_id=snapshot_id, limit=1)
        return [
            service.public_revision(r)
            for r in list(reversed(service._revisions(session, project, snapshot_id)))[
                skip : skip + limit
            ]
        ]


@router.post("/revisions", response_model=service.CloudRevisionPublic, status_code=201)
def create_cloudatlas_ledger_revision(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    body: service.CloudLedgerEdit,
    idempotency_key: Key,
    request: Request,
) -> service.CloudRevisionPublic:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=None if body.kind == "scope" else (ProjectRole.OPERATOR,),
        writable=True,
    )
    with _errors():
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


@router.get("/operations/{operation_key}", response_model=service.CloudRevisionPublic)
def read_cloudatlas_ledger_operation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    operation_key: str,
    response: Response,
) -> service.CloudRevisionPublic:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    response.headers["Cache-Control"] = "private, no-store"
    record = service.recover(session, project, current_user.id, operation_key)
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "cloud_ledger_operation_not_found"}
        )
    return service.public_revision(record)


@router.get("/profile", response_model=service.CloudIPProfile)
def read_cloudatlas_ip_profile(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    ip: Annotated[str, Query(min_length=1, max_length=45)],
    snapshot_id: uuid.UUID,
    response: Response,
    revision: Revision = None,
    upload_id: uuid.UUID | None = None,
    customer_revision_id: uuid.UUID | None = None,
    customer_original: bool = False,
    customer_skip: Skip = 0,
    cloud_skip: Skip = 0,
    limit: Limit = 25,
) -> service.CloudIPProfile:
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
            ip=ip,
            snapshot_id=snapshot_id,
            revision=revision,
            upload_id=upload_id,
            customer_revision_id=customer_revision_id,
            customer_original=customer_original,
            customer_skip=customer_skip,
            cloud_skip=cloud_skip,
            limit=limit,
        )
