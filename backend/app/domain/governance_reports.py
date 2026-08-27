from __future__ import annotations

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, cast

from sqlalchemy import and_, func, or_, true
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Bundle
from sqlmodel import Session, col, select
from sqlmodel.sql.expression import Select

from app.domain.models import (
    AiGovernanceDraft,
    AiGovernanceDraftFindingBinding,
    AiGovernanceDraftPublic,
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


def list_reports(
    *,
    session: Session,
    project: Project,
    limit: int,
    cursor: ReportCursor | None,
) -> GovernanceReportsPublic:
    report_scope = (
        sa_select(
            col(GovernanceReport.id).label("report_id"),
            col(GovernanceReport.governance_run_id).label("governance_run_id"),
            col(GovernanceRun.completed_at).label("run_completed_at"),
            col(GovernanceReport.report_contract_version).label(
                "report_contract_version"
            ),
            col(GovernanceReport.generation_mode).label("generation_mode"),
            col(GovernanceReport.html_sha256).label("html_sha256"),
            col(GovernanceReport.csv_sha256).label("csv_sha256"),
            col(GovernanceReport.created_at).label("report_created_at"),
        )
        .join(
            GovernanceRun,
            col(GovernanceRun.id) == col(GovernanceReport.governance_run_id),
        )
        .where(
            col(GovernanceReport.project_id) == project.id,
            col(GovernanceReport.tenant_id) == project.tenant_id,
            col(GovernanceRun.project_id) == project.id,
            col(GovernanceRun.tenant_id) == project.tenant_id,
            col(GovernanceRun.completed_at).is_not(None),
        )
        .cte("report_scope")
    )
    page_statement = sa_select(report_scope)
    if cursor is not None:
        page_statement = page_statement.where(
            or_(
                report_scope.c.run_completed_at < cursor.completed_at,
                and_(
                    report_scope.c.run_completed_at == cursor.completed_at,
                    report_scope.c.report_id < cursor.report_id,
                ),
            )
        )
    report_page = (
        page_statement.order_by(
            report_scope.c.run_completed_at.desc(),
            report_scope.c.report_id.desc(),
        )
        .limit(limit + 1)
        .cte("report_page")
    )
    latest_completed_run_at = (
        sa_select(col(GovernanceRun.completed_at))
        .where(
            col(GovernanceRun.id) == col(Project.latest_completed_run_id),
            col(GovernanceRun.project_id) == col(Project.id),
            col(GovernanceRun.tenant_id) == col(Project.tenant_id),
        )
        .scalar_subquery()
    )
    count = sa_select(func.count()).select_from(report_scope).scalar_subquery()
    report_summary: Bundle[Any] = Bundle(
        "report_summary",
        report_page.c.report_id,
        report_page.c.governance_run_id,
        report_page.c.run_completed_at,
        report_page.c.report_contract_version,
        report_page.c.generation_mode,
        report_page.c.html_sha256,
        report_page.c.csv_sha256,
        report_page.c.report_created_at,
    )
    statement = (
        sa_select(
            col(Project.latest_completed_run_id),
            latest_completed_run_at.label("latest_completed_run_at"),
            count.label("report_count"),
            report_summary,
        )
        .select_from(Project)
        .outerjoin(report_page, true())
        .where(
            col(Project.id) == project.id,
            col(Project.tenant_id) == project.tenant_id,
        )
        .order_by(
            report_page.c.run_completed_at.desc(),
            report_page.c.report_id.desc(),
        )
    )
    rows = session.exec(cast(Select[Any], statement)).all()
    if not rows:
        return GovernanceReportsPublic(
            data=[],
            count=0,
            page_size=0,
            next_cursor=None,
            compatible=False,
            compatibility_code="stage5_run_required",
            latest_completed_run_id=None,
            latest_completed_run_at=None,
        )

    latest_run_id, latest_run_at, report_count, _ = rows[0]
    data = [
        GovernanceReportSummaryPublic(
            id=report_summary.report_id,
            governance_run_id=report_summary.governance_run_id,
            run_completed_at=report_summary.run_completed_at,
            report_contract_version=report_summary.report_contract_version,
            generation_mode=report_summary.generation_mode,
            html_sha256=report_summary.html_sha256,
            csv_sha256=report_summary.csv_sha256,
            created_at=report_summary.report_created_at,
        )
        for _, _, _, report_summary in rows[:limit]
        if report_summary.report_id is not None
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

    compatible = report_count > 0
    return GovernanceReportsPublic(
        data=data,
        count=report_count,
        page_size=len(data),
        next_cursor=next_cursor,
        compatible=compatible,
        compatibility_code=(
            None
            if compatible
            else (
                "stage5_run_required"
                if latest_run_id is None
                else "stage5_rerun_required"
            )
        ),
        latest_completed_run_id=latest_run_id,
        latest_completed_run_at=latest_run_at,
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


def ai_governance_draft_public(
    *, session: Session, draft: AiGovernanceDraft
) -> AiGovernanceDraftPublic:
    finding_ids = session.exec(
        select(AiGovernanceDraftFindingBinding.finding_id)
        .where(AiGovernanceDraftFindingBinding.draft_id == draft.id)
        .order_by(col(AiGovernanceDraftFindingBinding.finding_id))
    ).all()
    return AiGovernanceDraftPublic(
        id=draft.id,
        governance_report_id=draft.governance_report_id,
        report_sha256=draft.report_sha256,
        finding_ids=list(finding_ids),
        status=draft.status,
        failure_code=draft.failure_code,
        agent_compose_run_id=draft.agent_compose_run_id,
        session_id=draft.session_id,
        created_at=draft.created_at,
    )


def get_report(
    *,
    session: Session,
    project: Project,
    report_id: uuid.UUID,
    can_request_ai_governance_draft: bool,
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
    drafts = session.exec(
        select(AiGovernanceDraft)
        .where(
            AiGovernanceDraft.governance_report_id == report.id,
            AiGovernanceDraft.governance_run_id == report.governance_run_id,
            AiGovernanceDraft.project_id == project.id,
            AiGovernanceDraft.tenant_id == project.tenant_id,
        )
        .order_by(col(AiGovernanceDraft.created_at).desc())
    ).all()
    summary = _summary(report, run_completed_at=run_completed_at)
    return GovernanceReportDetailPublic(
        **summary.model_dump(),
        canonical_content=report.canonical_content,
        evidence=[_evidence_reference(item) for item in evidence],
        evidence_count=evidence_count,
        evidence_max_entries=REPORT_DETAIL_MAX_EVIDENCE,
        can_request_ai_governance_draft=can_request_ai_governance_draft,
        ai_governance_drafts=[
            ai_governance_draft_public(session=session, draft=draft) for draft in drafts
        ],
    )
