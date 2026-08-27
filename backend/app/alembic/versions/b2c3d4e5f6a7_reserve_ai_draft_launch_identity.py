"""Allow an AI draft to reserve its agent-compose Run before Session creation.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-27 00:00:00.000000

"""

from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_ai_governance_drafts_session_binding"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "ai_governance_drafts", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "ai_governance_drafts",
        "session_id IS NULL OR agent_compose_run_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "ai_governance_drafts", type_="check")
    # A reachable reserved-but-unbound row cannot satisfy the predecessor's
    # stricter rule without erasing its immutable launch identity. PostgreSQL's
    # NOT VALID form preserves those rows while restoring the predecessor rule
    # for new writes during a rollback. A later re-upgrade replaces this with
    # the fully validated forward-compatible constraint.
    op.execute(
        "ALTER TABLE ai_governance_drafts "
        f"ADD CONSTRAINT {_CONSTRAINT} CHECK ("
        "(session_id IS NULL AND agent_compose_run_id IS NULL) OR "
        "(session_id IS NOT NULL AND agent_compose_run_id IS NOT NULL)"
        ") NOT VALID"
    )
