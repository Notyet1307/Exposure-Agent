"""Add the recoverable project archival state.

Revision ID: 7e4a1b2c3d40
Revises: c9d4e2f7a105
Create Date: 2026-07-28 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "7e4a1b2c3d40"
down_revision = "c9d4e2f7a105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "archived_at")
