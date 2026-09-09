"""Append-only human records; verification is a projection, never a Publish input."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlmodel import Session, col, select

from app.domain.governance_publication import is_published_run
from app.domain.ip_source_comparison import (
    IPSourceComparison,
    IPSourceComparisonError,
    read_ip_source_comparison,
)
from app.domain.models import (
    AuditEvent,
    Finding,
    FindingOccurrence,
    FindingTransition,
    GovernanceRun,
    ManualReview,
    Project,
)
from app.models import User

ReviewText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
ReviewStatus = Literal["PENDING", "RESOLVED", "UNRESOLVED", "INSUFFICIENT_EVIDENCE"]
VerificationStatus = Literal[
    "RESOLVED", "UNRESOLVED", "INSUFFICIENT_EVIDENCE", "NO_NEW_CONCLUSION"
]


class ManualReviewError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ManualReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_id: uuid.UUID
    run_id: uuid.UUID
    finding_id: uuid.UUID | None = None
    conclusion: ReviewText
    pending_verification: ReviewText
    supersedes_id: uuid.UUID | None = None


class ManualReviewVerification(BaseModel):
    run_id: uuid.UUID
    run_status: str
    completed_at: datetime | None
    observed_at: datetime
    status: VerificationStatus
    reason: str


class ManualReviewPublic(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    resource_id: uuid.UUID
    run_id: uuid.UUID
    finding_id: uuid.UUID | None
    author_id: uuid.UUID
    author_name: str
    created_at: datetime
    conclusion: str
    pending_verification: str
    supersedes_id: uuid.UUID | None
    version: int
    is_current: bool
    status: ReviewStatus
    verifications: list[ManualReviewVerification]


class ManualReviewsPublic(BaseModel):
    data: list[ManualReviewPublic]
    count: int
    can_create: bool


def validate_scope(
    *,
    session: Session,
    project: Project,
    resource_id: uuid.UUID,
    run_id: uuid.UUID,
    finding_id: uuid.UUID | None,
) -> tuple[GovernanceRun, IPSourceComparison]:
    run = session.exec(
        select(GovernanceRun).where(
            GovernanceRun.id == run_id,
            GovernanceRun.project_id == project.id,
            GovernanceRun.tenant_id == project.tenant_id,
        )
    ).one_or_none()
    if run is None:
        raise ManualReviewError("manual_review_scope_not_found")
    try:
        comparison = read_ip_source_comparison(
            session=session,
            tenant_id=project.tenant_id,
            project_id=project.id,
            run_id=run.id,
        )
    except IPSourceComparisonError:
        raise ManualReviewError("manual_review_base_evidence_unavailable") from None
    baseline = next(
        (item for item in comparison.results if item.resource_id == resource_id), None
    )
    if baseline is None:
        raise ManualReviewError("manual_review_scope_not_found")
    if finding_id is not None:
        finding = session.exec(
            select(Finding).where(
                Finding.id == finding_id,
                Finding.resource_id == resource_id,
                Finding.project_id == project.id,
                Finding.tenant_id == project.tenant_id,
            )
        ).one_or_none()
        occurrence = session.exec(
            select(FindingOccurrence.id).where(
                FindingOccurrence.finding_id == finding_id,
                FindingOccurrence.governance_run_id == run.id,
                FindingOccurrence.project_id == project.id,
                FindingOccurrence.tenant_id == project.tenant_id,
            )
        ).first()
        transition = session.exec(
            select(FindingTransition.id).where(
                FindingTransition.finding_id == finding_id,
                FindingTransition.governance_run_id == run.id,
                FindingTransition.project_id == project.id,
                FindingTransition.tenant_id == project.tenant_id,
            )
        ).first()
        if finding is None or (occurrence is None and transition is None):
            raise ManualReviewError("manual_review_scope_not_found")
    return run, baseline


def create(
    *,
    session: Session,
    project: Project,
    author: User,
    request: ManualReviewCreate,
    baseline: IPSourceComparison,
    current: ManualReview | None,
) -> ManualReview:
    """The caller holds the authorized Project lock, also used by Publish."""
    if (current is None and request.supersedes_id is not None) or (
        current is not None and request.supersedes_id != current.id
    ):
        raise ManualReviewError("manual_review_version_conflict")
    record = ManualReview(
        tenant_id=project.tenant_id,
        project_id=project.id,
        **request.model_dump(),
        author_id=author.id,
        author_name=author.full_name or author.email,
        version=current.version + 1 if current else 1,
        baseline_classification=current.baseline_classification
        if current
        else baseline.classification,
    )
    session.add(record)
    session.flush()
    # The database assigns wall-clock time after the Project lock, not transaction start.
    session.refresh(record)
    session.add(
        AuditEvent(
            tenant_id=project.tenant_id,
            project_id=project.id,
            actor_subject=str(author.id),
            actor_type="User",
            action="manual_review.corrected" if current else "manual_review.created",
            target_type="ManualReview",
            target_id=record.id,
            after_data={
                "run_id": str(record.run_id),
                "resource_id": str(record.resource_id),
                "finding_id": str(record.finding_id) if record.finding_id else None,
                "supersedes_id": str(record.supersedes_id)
                if record.supersedes_id
                else None,
                "version": record.version,
            },
        )
    )
    return record


def public_records(
    *,
    session: Session,
    project: Project,
    base: GovernanceRun,
    records: list[ManualReview],
    current_id: uuid.UUID | None,
) -> list[ManualReviewPublic]:
    if not records:
        return []
    earliest = min(record.created_at for record in records)
    cutoffs = {
        successor.supersedes_id: successor.created_at
        for successor in session.exec(
            select(ManualReview).where(
                col(ManualReview.supersedes_id).in_([record.id for record in records]),
                ManualReview.project_id == project.id,
                ManualReview.tenant_id == project.tenant_id,
            )
        ).all()
    }
    assert base.completed_at is not None
    # Keep every real Run identity; failed/running Runs are limitations, not evidence.
    statement = select(GovernanceRun).where(
        GovernanceRun.project_id == project.id,
        GovernanceRun.tenant_id == project.tenant_id,
        GovernanceRun.created_at > earliest,
        GovernanceRun.created_at > base.completed_at,
    )
    if all(record.id in cutoffs for record in records):
        statement = statement.where(GovernanceRun.created_at < max(cutoffs.values()))
    runs = session.exec(
        statement.order_by(col(GovernanceRun.created_at), col(GovernanceRun.id))
    ).all()
    failures: dict[uuid.UUID, list[AuditEvent]] = {}
    for event in session.exec(
        select(AuditEvent)
        .where(
            AuditEvent.project_id == project.id,
            AuditEvent.tenant_id == project.tenant_id,
            AuditEvent.target_type == "governance_run",
            col(AuditEvent.action).in_(
                (
                    "governance_run.failed",
                    "governance_run.session_terminal_converged",
                    "governance_run.retry_rejected",
                )
            ),
            col(AuditEvent.target_id).in_([run.id for run in runs]),
        )
        .order_by(col(AuditEvent.occurred_at), col(AuditEvent.id))
    ).all():
        if event.after_data is not None and event.after_data.get("status") in {
            "FAILED_DATA",
            "FAILED_PROCESSING",
        }:
            failures.setdefault(event.target_id, []).append(event)
    comparisons: dict[uuid.UUID, IPSourceComparison | None] = {}
    for run in runs:
        if not is_published_run(run):
            continue
        if not any(
            record.id not in cutoffs
            or (run.completed_at is not None and run.completed_at < cutoffs[record.id])
            for record in records
        ):
            continue
        try:
            facts = read_ip_source_comparison(
                session=session,
                tenant_id=project.tenant_id,
                project_id=project.id,
                run_id=run.id,
            )
        except IPSourceComparisonError:
            continue
        else:
            comparisons[run.id] = next(
                (
                    item
                    for item in facts.results
                    if item.resource_id == records[0].resource_id
                ),
                None,
            )
    result = []
    for record in records:
        status: ReviewStatus = "PENDING"
        verifications = []
        for run in runs:
            if run.created_at <= record.created_at:
                continue
            cutoff = cutoffs.get(record.id)
            failure = next(
                (
                    event
                    for event in reversed(failures.get(run.id, []))
                    if cutoff is None or event.occurred_at < cutoff
                ),
                None,
            )
            completed_at = run.completed_at
            run_status = run.status
            observed_at = run.completed_at or run.created_at
            # Failures have no Run.completed_at. Their immutable audit event, not
            # mutable updated_at, preserves the failure even after a later retry.
            historical_failure = cutoff is not None and (
                run.completed_at is None or run.completed_at >= cutoff
            )
            if historical_failure:
                if failure is None:
                    continue
                assert failure.after_data is not None
                run_status = str(failure.after_data["status"])
                completed_at = None
            if historical_failure or (
                failure is not None
                and run.status in {"FAILED_DATA", "FAILED_PROCESSING"}
            ):
                assert failure is not None
                observed_at = failure.occurred_at
                outcome: VerificationStatus = "NO_NEW_CONCLUSION"
                reason = "run_not_successful"
            else:
                outcome, reason = _verify(
                    record,
                    run,
                    comparisons.get(run.id),
                    available=run.id in comparisons,
                )
            if outcome != "NO_NEW_CONCLUSION":
                status = outcome
            verifications.append(
                ManualReviewVerification(
                    run_id=run.id,
                    run_status=run_status,
                    completed_at=completed_at,
                    observed_at=observed_at,
                    status=outcome,
                    reason=reason,
                )
            )
        result.append(
            ManualReviewPublic.model_validate(
                {
                    **record.model_dump(),
                    "is_current": record.id == current_id,
                    "status": status,
                    "verifications": list(reversed(verifications)),
                }
            )
        )
    return result


def _verify(
    record: ManualReview,
    run: GovernanceRun,
    comparison: IPSourceComparison | None,
    *,
    available: bool,
) -> tuple[VerificationStatus, str]:
    if not is_published_run(run):
        return "NO_NEW_CONCLUSION", "run_not_successful"
    if not available:
        return "INSUFFICIENT_EVIDENCE", "comparison_evidence_unavailable"
    if record.baseline_classification not in {
        "customer_upload_only",
        "cloudatlas_only",
    }:
        return "INSUFFICIENT_EVIDENCE", "original_difference_not_established"
    if comparison is None or comparison.classification == "neither_source_observed":
        return "INSUFFICIENT_EVIDENCE", "resource_not_observed"
    # Exactly Publish's closure condition. NetFlow activity/absence is irrelevant.
    if comparison.customer_upload_present and comparison.cloudatlas_present:
        return "RESOLVED", "both_sources_observed"
    if comparison.classification == record.baseline_classification:
        return "UNRESOLVED", "original_difference_persists"
    return "INSUFFICIENT_EVIDENCE", "difference_direction_changed"
