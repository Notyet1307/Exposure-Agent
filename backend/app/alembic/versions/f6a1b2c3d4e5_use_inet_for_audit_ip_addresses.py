"""Use PostgreSQL inet for audit IP addresses.

Revision ID: f6a1b2c3d4e5
Revises: b4f2a1c8d903
Create Date: 2026-07-29 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f6a1b2c3d4e5"
down_revision = "b4f2a1c8d903"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "audit_events",
        "ip_address",
        existing_type=sa.String(length=45),
        type_=postgresql.INET(),
        existing_nullable=True,
        postgresql_using="ip_address::inet",
    )


def downgrade() -> None:
    op.alter_column(
        "audit_events",
        "ip_address",
        existing_type=postgresql.INET(),
        type_=sa.String(length=45),
        existing_nullable=True,
        postgresql_using="ip_address::text",
    )
