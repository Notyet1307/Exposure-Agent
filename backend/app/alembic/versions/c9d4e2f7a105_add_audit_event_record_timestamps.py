"""Add standard record timestamps to audit events.

Revision ID: c9d4e2f7a105
Revises: 8b1e6a7d2f30
Create Date: 2026-07-28 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "c9d4e2f7a105"
down_revision = "8b1e6a7d2f30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "audit_events",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.alter_column("audit_events", "created_at", server_default=None)
    op.alter_column("audit_events", "updated_at", server_default=None)


def downgrade() -> None:
    op.drop_column("audit_events", "updated_at")
    op.drop_column("audit_events", "created_at")
