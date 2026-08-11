from __future__ import annotations

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy import and_, func, or_
from sqlmodel import Session, col, select

from app.domain.models import (
    Evidence,
    EvidenceReferencePublic,
    GovernanceReport,
    GovernanceReportDetailPublic,
    GovernanceReportsPublic,
    GovernanceReportSummaryPublic,
    GovernanceRun,
    Project,
)

REPORT_LIST_DEFAULT_PAGE_SIZE: Final = 20
REPORT_LIST_MAX_PAGE_SIZE: Final = 50
REPORT_DETAIL_MAX_EVIDENCE: Final = 50


class ReportCursorError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReportCursor:
    completed_at: datetime
    report_id: uuid.UUID


def encode_report_cursor(cursor: ReportCursor) -> str:
    value = f"{cursor.completed_at.isoformat()}|{cursor.report_id}".encode("ascii")
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def decode_report_cursor(value: str) -> ReportCursor:
    try:
        padding = b"=" * (-len(value) % 4)
        decoded = base64.b64decode(
            value.encode("ascii") + padding,
            altchars=b"-_",
            validate=True,
        ).decode("ascii")
        completed_at_value, report_id_value = decoded.split("|", maxsplit=1)
        completed_at = datetime.fromisoformat(completed_at_value)
        report_id = uuid.UUID(report_id_value)
    except UnicodeError, ValueError, binascii.Error:
        raise ReportCursorError from None
    if completed_at.tzinfo is None or completed_at.utcoffset() is None:
        raise ReportCursorError
    return ReportCursor(completed_at=completed_at, report_id=report_id)


def _summary(
    report: GovernanceReport, *, run_completed_at: datetime
) -> GovernanceReportSummaryPublic:
    return GovernanceReportSummaryPublic(
        id=report.id,
        governance_run_id=report.governance_run_id,
        run_completed_at=run_completed_at,
        report_contract_version=report.report_contract_version,
        generation_mode=report.generation_mode,
        html_sha256=report.html_sha256,
        csv_sha256=report.csv_sha256,
        created_at=report.created_at,
    )


def _latest_completed_run(
    *, session: Session, project: Project
) -> GovernanceRun | None:
    if project.latest_completed_run_id is None:
        return None
    return session.exec(
        select(GovernanceRun).where(
            GovernanceRun.id == project.latest_completed_run_id,
            GovernanceRun.project_id == project.id,
            GovernanceRun.tenant_id == project.tenant_id,
        )
    ).one_or_none()


def list_reports(
    *,
    session: Session,
    project: Project,
    limit: int,
    cursor: ReportCursor | None,
) -> GovernanceReportsPublic:
    scope = (
        col(GovernanceReport.project_id) == project.id,
        col(GovernanceReport.tenant_id) == project.tenant_id,
        col(GovernanceRun.id) == col(GovernanceReport.governance_run_id),
        col(GovernanceRun.project_id) == project.id,
        col(GovernanceRun.tenant_id) == project.tenant_id,
        col(GovernanceRun.completed_at).is_not(None),
    )
    count = int(
        session.exec(
            select(func.count())
            .select_from(GovernanceReport)
            .join(
                GovernanceRun,
                col(GovernanceRun.id) == col(GovernanceReport.governance_run_id),
            )
            .where(*scope)
        ).one()
    )
    statement = (
        select(GovernanceReport, col(GovernanceRun.completed_at))
        .join(
            GovernanceRun,
            col(GovernanceRun.id) == col(GovernanceReport.governance_run_id),
        )
        .where(*scope)
    )
    if cursor is not None:
        statement = statement.where(
            or_(
                col(GovernanceRun.completed_at) < cursor.completed_at,
                and_(
                    col(GovernanceRun.completed_at) == cursor.completed_at,
                    col(GovernanceReport.id) < cursor.report_id,
                ),
            )
        )
    rows = session.exec(
        statement.order_by(
            col(GovernanceRun.completed_at).desc(),
            col(GovernanceReport.id).desc(),
        ).limit(limit + 1)
    ).all()
    page_rows = rows[:limit]
    data = [
        _summary(report, run_completed_at=run_completed_at)
        for report, run_completed_at in page_rows
        if run_completed_at is not None
    ]
    next_cursor = None
    if len(rows) > limit and data:
        last = data[-1]
        next_cursor = encode_report_cursor(
            ReportCursor(
                completed_at=last.run_completed_at,
                report_id=last.id,
            )
        )

    latest_run = _latest_completed_run(session=session, project=project)
    if count > 0:
        compatible = True
        compatibility_code = None
    else:
        compatible = False
        compatibility_code = (
            "stage5_run_required" if latest_run is None else "stage5_rerun_required"
        )
    return GovernanceReportsPublic(
        data=data,
        count=count,
        page_size=len(data),
        next_cursor=next_cursor,
        compatible=compatible,
        compatibility_code=compatibility_code,
        latest_completed_run_id=latest_run.id if latest_run is not None else None,
        latest_completed_run_at=(
            latest_run.completed_at if latest_run is not None else None
        ),
    )


def _evidence_reference(evidence: Evidence) -> EvidenceReferencePublic:
    targets = (
        ("SOURCE_SNAPSHOT", evidence.source_snapshot_id),
        ("OBSERVATION", evidence.observation_id),
        ("FINDING_OCCURRENCE", evidence.finding_occurrence_id),
        ("FINDING_TRANSITION", evidence.finding_transition_id),
    )
    fact_type, fact_id = next(
        (target_type, target_id)
        for target_type, target_id in targets
        if target_id is not None
    )
    return EvidenceReferencePublic(
        id=evidence.id,
        governance_run_id=evidence.governance_run_id,
        fact_type=fact_type,
        fact_id=fact_id,
    )


def get_report(
    *, session: Session, project: Project, report_id: uuid.UUID
) -> GovernanceReportDetailPublic | None:
    row = session.exec(
        select(GovernanceReport, col(GovernanceRun.completed_at))
        .join(
            GovernanceRun,
            col(GovernanceRun.id) == col(GovernanceReport.governance_run_id),
        )
        .where(
            GovernanceReport.id == report_id,
            GovernanceReport.project_id == project.id,
            GovernanceReport.tenant_id == project.tenant_id,
            GovernanceRun.project_id == project.id,
            GovernanceRun.tenant_id == project.tenant_id,
            col(GovernanceRun.completed_at).is_not(None),
        )
    ).one_or_none()
    if row is None:
        return None
    report, run_completed_at = row
    if run_completed_at is None:
        return None
    evidence_scope = (
        col(Evidence.governance_report_id) == report.id,
        col(Evidence.governance_run_id) == report.governance_run_id,
        col(Evidence.project_id) == project.id,
        col(Evidence.tenant_id) == project.tenant_id,
    )
    evidence_count = int(
        session.exec(
            select(func.count()).select_from(Evidence).where(*evidence_scope)
        ).one()
    )
    evidence = session.exec(
        select(Evidence)
        .where(*evidence_scope)
        .order_by(col(Evidence.created_at), col(Evidence.id))
        .limit(REPORT_DETAIL_MAX_EVIDENCE)
    ).all()
    summary = _summary(report, run_completed_at=run_completed_at)
    return GovernanceReportDetailPublic(
        **summary.model_dump(),
        canonical_content=report.canonical_content,
        evidence=[_evidence_reference(item) for item in evidence],
        evidence_count=evidence_count,
        evidence_max_entries=REPORT_DETAIL_MAX_EVIDENCE,
    )
