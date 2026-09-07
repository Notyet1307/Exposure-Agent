from __future__ import annotations

from sqlalchemy import and_
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col

from app.domain.models import GovernanceRun, GovernanceRunStatus

COMPLETED_RUN_STATUSES = frozenset(
    {
        GovernanceRunStatus.COMPLETED.value,
        GovernanceRunStatus.COMPLETED_WITH_WARNINGS.value,
    }
)


def is_published_run(run: GovernanceRun) -> bool:
    return run.status in COMPLETED_RUN_STATUSES and run.completed_at is not None


def published_run_predicate() -> ColumnElement[bool]:
    return and_(
        col(GovernanceRun.status).in_(COMPLETED_RUN_STATUSES),
        col(GovernanceRun.completed_at).is_not(None),
    )
