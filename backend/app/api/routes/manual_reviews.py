import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.api.deps import CurrentUser, SessionDep, TokenDep, get_current_user
from app.api.project_authorization import (
    PROJECT_READ_ROLES,
    get_authorized_project,
    project_access_filter,
)
from app.api.routes.ip_results import _finding_read_session
from app.domain import manual_reviews as service
from app.domain.models import ManualReview, Project, ProjectRole

router = APIRouter(
    prefix="/projects/{project_id}/manual-reviews", tags=["manual-reviews"]
)


def _error(error: service.ManualReviewError) -> HTTPException:
    return HTTPException(
        status_code=404 if error.code == "manual_review_scope_not_found" else 409,
        detail={"code": error.code},
    )


@router.post("", response_model=service.ManualReviewPublic, status_code=201)
def create_manual_review(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    project_id: uuid.UUID,
    request_body: service.ManualReviewCreate,
) -> service.ManualReviewPublic:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=(ProjectRole.OPERATOR,),
        writable=True,
        lock=True,
    )
    try:
        _base, baseline = service.validate_scope(
            session=session,
            project=project,
            resource_id=request_body.resource_id,
            run_id=request_body.run_id,
            finding_id=request_body.finding_id,
        )
        current = session.exec(
            select(ManualReview)
            .where(
                ManualReview.tenant_id == project.tenant_id,
                ManualReview.project_id == project.id,
                ManualReview.resource_id == request_body.resource_id,
                ManualReview.run_id == request_body.run_id,
                ManualReview.finding_id == request_body.finding_id,
            )
            .order_by(col(ManualReview.version).desc())
            .limit(1)
        ).first()
        record = service.create(
            session=session,
            project=project,
            author=current_user,
            request=request_body,
            baseline=baseline,
            current=current,
        )
    except service.ManualReviewError as error:
        raise _error(error) from None
    response = service.ManualReviewPublic.model_validate(
        {
            **record.model_dump(),
            "is_current": True,
            "status": "PENDING",
            "verifications": [],
        }
    )
    session.commit()
    return response


@router.get("", response_model=service.ManualReviewsPublic)
def read_manual_reviews(
    *,
    session: Annotated[Session, Depends(_finding_read_session)],
    token: TokenDep,
    project_id: uuid.UUID,
    resource_id: uuid.UUID,
    run_id: uuid.UUID,
    finding_id: uuid.UUID | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
) -> service.ManualReviewsPublic:
    current_user = get_current_user(session=session, token=token)
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    try:
        base, _baseline = service.validate_scope(
            session=session,
            project=project,
            resource_id=resource_id,
            run_id=run_id,
            finding_id=finding_id,
        )
    except service.ManualReviewError as error:
        raise _error(error) from None
    filters = [
        ManualReview.tenant_id == project.tenant_id,
        ManualReview.project_id == project.id,
        ManualReview.resource_id == resource_id,
        ManualReview.run_id == run_id,
        ManualReview.finding_id == finding_id,
    ]
    count = session.exec(
        select(func.count()).select_from(ManualReview).where(*filters)
    ).one()
    current_id = session.exec(
        select(ManualReview.id)
        .where(*filters)
        .order_by(col(ManualReview.version).desc())
        .limit(1)
    ).first()
    records = session.exec(
        select(ManualReview)
        .where(*filters)
        .order_by(col(ManualReview.version).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    can_create = (
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
    return service.ManualReviewsPublic(
        data=service.public_records(
            session=session,
            project=project,
            base=base,
            records=list(records),
            current_id=current_id,
        ),
        count=count,
        can_create=can_create,
    )
