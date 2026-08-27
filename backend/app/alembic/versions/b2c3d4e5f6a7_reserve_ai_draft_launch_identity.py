"""Allow an AI draft to reserve its agent-compose Run before Session creation.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-27 00:00:00.000000

"""

import sqlalchemy as sa
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
    reserved_unbound = op.get_bind().execute(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM ai_governance_drafts "
            "WHERE agent_compose_run_id IS NOT NULL AND session_id IS NULL"
            ")"
        )
    ).scalar_one()
    if reserved_unbound:
        raise RuntimeError(
            "cannot downgrade while an AI draft has a reserved unbound Run identity"
        )
    op.drop_constraint(_CONSTRAINT, "ai_governance_drafts", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "ai_governance_drafts",
        "(session_id IS NULL AND agent_compose_run_id IS NULL) OR "
        "(session_id IS NOT NULL AND agent_compose_run_id IS NOT NULL)",
    )
