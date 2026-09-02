from __future__ import annotations

import uuid
from typing import Self

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.api.project_authorization import get_authorized_project
from app.domain import ai_governance_drafts as draft_service
from app.domain import governance_reports as report_service
from app.domain.ai_governance_drafts import (
    AiDraftEditedOutput,
    AiDraftModelOutput,
)
from app.domain.models import (
    AiGovernanceDraft,
    AiGovernanceDraftPublic,
    AiGovernanceDraftReviewDecision,
    Project,
    ProjectRole,
)

router = APIRouter(prefix="/projects", tags=["ai-governance-draft-reviews"])


class AiGovernanceDraftReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: AiGovernanceDraftReviewDecision
    edited_output: AiDraftEditedOutput | None = None

    @model_validator(mode="after")
    def require_exact_editorial_projection(self) -> Self:
        if self.decision == AiGovernanceDraftReviewDecision.EDITED:
            if self.edited_output is None:
                raise ValueError("EDITED requires edited_output")
        elif self.edited_output is not None:
            raise ValueError("Only EDITED accepts edited_output")
        return self


class AiGovernanceDraftReviewPublic(AiGovernanceDraftPublic):
    governance_run_id: uuid.UUID
    model_output: AiDraftModelOutput | None = None
    review_decision: AiGovernanceDraftReviewDecision | None = None
    operator_edited_output: AiDraftEditedOutput | None = None
    reviewed_by: str | None = None
    reviewed_at: object | None = None
    generation_terminal_at: object | None = None


def _draft_in_scope(
    *,
    session: SessionDep,
    project: Project,
    report_id: uuid.UUID,
    draft_id: uuid.UUID,
) -> AiGovernanceDraft:
    draft = session.exec(
        select(AiGovernanceDraft).where(
            AiGovernanceDraft.id == draft_id,
            AiGovernanceDraft.governance_report_id == report_id,
            AiGovernanceDraft.project_id == project.id,
            AiGovernanceDraft.tenant_id == project.tenant_id,
        )
    ).one_or_none()
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ai_governance_draft_not_found",
        )
    return draft


def _public_draft(
    *, session: SessionDep, draft: AiGovernanceDraft
) -> AiGovernanceDraftReviewPublic:
    summary = report_service.ai_governance_draft_public(session=session, draft=draft)
    return AiGovernanceDraftReviewPublic(
        **summary.model_dump(),
        governance_run_id=draft.governance_run_id,
        model_output=draft.model_output,
        review_decision=draft.review_decision,
        operator_edited_output=draft.operator_edited_output,
        reviewed_by=draft.reviewed_by,
        reviewed_at=draft.reviewed_at,
        generation_terminal_at=draft.generation_terminal_at,
    )


@router.get(
    "/{project_id}/governance-reports/{report_id}/ai-governance-drafts/{draft_id}",
    response_model=AiGovernanceDraftReviewPublic,
)
def read_ai_governance_draft(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    draft_id: uuid.UUID,
    current_user: CurrentUser,
) -> AiGovernanceDraftReviewPublic:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=(ProjectRole.OPERATOR,),
        writable=True,
    )
    draft = _draft_in_scope(
        session=session,
        project=project,
        report_id=report_id,
        draft_id=draft_id,
    )
    return _public_draft(session=session, draft=draft)


@router.post(
    "/{project_id}/governance-reports/{report_id}/ai-governance-drafts/{draft_id}/review",
    response_model=AiGovernanceDraftReviewPublic,
)
def review_ai_governance_draft(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    draft_id: uuid.UUID,
    request_body: AiGovernanceDraftReviewRequest,
    current_user: CurrentUser,
) -> AiGovernanceDraftReviewPublic:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=(ProjectRole.OPERATOR,),
        writable=True,
        lock=True,
    )
    draft = _draft_in_scope(
        session=session,
        project=project,
        report_id=report_id,
        draft_id=draft_id,
    )
    try:
        reviewed = draft_service.review_draft(
            session=session,
            draft=draft,
            reviewer=str(current_user.id),
            decision=request_body.decision,
            edited_output=request_body.edited_output,
        )
    except draft_service.AiGovernanceDraftStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error.code,
        ) from None
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="review_storage_unavailable",
        ) from None
    return _public_draft(session=session, draft=reviewed)
