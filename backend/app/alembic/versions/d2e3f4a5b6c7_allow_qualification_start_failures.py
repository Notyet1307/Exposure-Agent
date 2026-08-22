"""Allow qualification failures without a nonexistent agent-compose run.

Revision ID: d2e3f4a5b6c7
Revises: c2d3e4f5a6b7
Create Date: 2026-08-22 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "model_qualification_results",
        "agent_compose_run_id",
        existing_type=sa.String(length=64),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "model_qualification_results",
        "agent_compose_run_id",
        existing_type=sa.String(length=64),
        nullable=False,
    )
