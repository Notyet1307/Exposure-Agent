"""Terminal Operator review for immutable AI governance drafts."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.api.project_authorization import get_authorized_project
from app.domain import ai_governance_drafts as draft_service
from app.domain.models import (
    AiGovernanceDraft,
    AiGovernanceDraftFindingBinding,
    AiGovernanceDraftReviewDecision,
    AiGovernanceDraftReviewPublic,
    GovernanceReport,
    ProjectRole,
)

router = APIRouter(prefix="/projects", tags=["ai-governance-draft-reviews"])

_REVIEW_ERROR_MESSAGES = {
    "draft_already_reviewed": "This draft already has a terminal review.",
    "draft_not_reviewable": "This draft is not available for review.",
    "review_requires_edited_output": "An EDITED review requires editorial output.",
    "invalid_review_decision": "Editorial output is only valid for an EDITED review.",
    "draft_model_output_invalid": "The persisted draft output is invalid.",
}


def _review_state_error(
    error: draft_service.AiGovernanceDraftStateError,
) -> HTTPException:
    if error.code == "draft_already_reviewed":
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error.code,
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": error.code,
            "message": _REVIEW_ERROR_MESSAGES.get(error.code, "Draft review failed."),
        },
    )


def _review_public(
    *, session: SessionDep, draft: AiGovernanceDraft
) -> AiGovernanceDraftReviewPublic:
    """Project only fields committed by the atomic domain transition."""
    assert draft.model_output is not None
    assert draft.review_decision is not None
    assert draft.reviewed_by is not None
    assert draft.reviewed_at is not None
    finding_ids = session.exec(
        select(AiGovernanceDraftFindingBinding.finding_id)
        .where(AiGovernanceDraftFindingBinding.draft_id == draft.id)
        .order_by(col(AiGovernanceDraftFindingBinding.finding_id))
    ).all()
    return AiGovernanceDraftReviewPublic(
        id=draft.id,
        governance_report_id=draft.governance_report_id,
        report_sha256=draft.report_sha256,
        finding_ids=list(finding_ids),
        status=draft.status,
        failure_code=draft.failure_code,
        agent_compose_run_id=draft.agent_compose_run_id,
        session_id=draft.session_id,
        created_at=draft.created_at,
        model_output=draft.model_output,
        review_decision=AiGovernanceDraftReviewDecision(draft.review_decision),
        reviewed_by=draft.reviewed_by,
        reviewed_at=draft.reviewed_at,
        operator_edited_output=draft.operator_edited_output,
    )


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
    request_body: draft_service.AiGovernanceDraftReviewRequest,
    current_user: CurrentUser,
) -> AiGovernanceDraftReviewPublic:
    """Record exactly one review; the caller never supplies factual draft data."""
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=(ProjectRole.OPERATOR,),
        writable=True,
        lock=True,
    )
    report = session.exec(
        select(GovernanceReport)
        .where(
            GovernanceReport.id == report_id,
            GovernanceReport.project_id == project.id,
            GovernanceReport.tenant_id == project.tenant_id,
        )
        .with_for_update()
    ).one_or_none()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    draft = session.exec(
        select(AiGovernanceDraft).where(
            AiGovernanceDraft.id == draft_id,
            AiGovernanceDraft.governance_report_id == report.id,
            AiGovernanceDraft.governance_run_id == report.governance_run_id,
            AiGovernanceDraft.project_id == project.id,
            AiGovernanceDraft.tenant_id == project.tenant_id,
        )
    ).one_or_none()
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if draft.report_sha256 != draft_service.report_identity_hash(report):
        raise _review_state_error(
            draft_service.AiGovernanceDraftStateError("draft_report_hash_mismatch")
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
        raise _review_state_error(error) from None
    return _review_public(session=session, draft=reviewed)
