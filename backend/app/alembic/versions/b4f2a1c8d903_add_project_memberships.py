"""Add recoverable project memberships and constrained roles.

Revision ID: b4f2a1c8d903
Revises: 7e4a1b2c3d40
Create Date: 2026-07-29 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b4f2a1c8d903"
down_revision = "7e4a1b2c3d40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("roles", postgresql.ARRAY(sa.String(length=20)), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "cardinality(roles) > 0", name="ck_project_memberships_roles_nonempty"
        ),
        sa.CheckConstraint(
            "roles <@ ARRAY['viewer', 'operator', 'approver']::varchar[]",
            name="ck_project_memberships_roles_known",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "user_id", name="uq_project_memberships_project_user"
        ),
    )
    op.create_index(
        op.f("ix_project_memberships_project_id"),
        "project_memberships",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_project_memberships_tenant_id"),
        "project_memberships",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_project_memberships_user_id"),
        "project_memberships",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_project_memberships_user_id"), table_name="project_memberships"
    )
    op.drop_index(
        op.f("ix_project_memberships_tenant_id"), table_name="project_memberships"
    )
    op.drop_index(
        op.f("ix_project_memberships_project_id"), table_name="project_memberships"
    )
    op.drop_table("project_memberships")
