"""Add Project-scoped CloudAtlas SourceInstance records.

Revision ID: a9b8c7d6e5f4
Revises: f8d9e0a1b2c3
Create Date: 2026-08-09 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a9b8c7d6e5f4"
down_revision = "f8d9e0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("instance_id", sa.String(length=255), nullable=False),
        sa.Column("capset_id", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("validated_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validation_error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "validated_fingerprint IS NULL OR "
            "validated_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_source_instances_fingerprint_format",
        ),
        sa.CheckConstraint(
            "source_type = 'cloudatlas'", name="ck_source_instances_type"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_source_instances_id_project"
        ),
    )
    op.create_index(
        op.f("ix_source_instances_project_id"),
        "source_instances",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_instances_tenant_id"),
        "source_instances",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "uq_source_instances_one_enabled_type_per_project",
        "source_instances",
        ["project_id", "source_type"],
        unique=True,
        postgresql_where=sa.text("enabled"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_source_instances_one_enabled_type_per_project",
        table_name="source_instances",
        postgresql_where=sa.text("enabled"),
    )
    op.drop_index(
        op.f("ix_source_instances_tenant_id"), table_name="source_instances"
    )
    op.drop_index(
        op.f("ix_source_instances_project_id"), table_name="source_instances"
    )
    op.drop_table("source_instances")
