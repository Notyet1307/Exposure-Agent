"""Add V2 core result and optional NetFlow binding identities."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c0a2b3d4e5f6"
down_revision = "ca2810000001"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("core_comparison_results",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("tenant_id", sa.Uuid(), nullable=False), sa.Column("project_id", sa.Uuid(), nullable=False), sa.Column("scope_key", sa.String(64), nullable=False), sa.Column("scope_confirmation_id", sa.Uuid(), nullable=False), sa.Column("purpose", sa.String(16), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("selection", postgresql.JSONB, nullable=False), sa.Column("pins", postgresql.JSONB, nullable=False), sa.Column("input_sha256", sa.String(64), nullable=False), sa.Column("created_by", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("purpose IN ('regular','custom')", name="ck_core_result_purpose"), sa.CheckConstraint("status IN ('PUBLISHED','FAILED','UNKNOWN')", name="ck_core_result_status"), sa.CheckConstraint("input_sha256 ~ '^[0-9a-f]{64}$'", name="ck_core_result_input_hash"),
        sa.ForeignKeyConstraint(["project_id", "tenant_id"], ["projects.id", "projects.tenant_id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["scope_confirmation_id"], ["source_correlation_revisions.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="RESTRICT"))
    op.create_index("ix_core_result_scope_published", "core_comparison_results", ["project_id", "scope_key", "published_at", "id"])
    op.create_table("core_comparison_supplements",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("result_id", sa.Uuid(), nullable=False), sa.Column("parent_id", sa.Uuid()), sa.Column("revision", sa.Integer(), nullable=False), sa.Column("analysis_id", sa.Uuid()), sa.Column("qualification_confirmation_id", sa.Uuid()), sa.Column("valid_until", sa.DateTime(timezone=True)), sa.Column("observation_window", postgresql.JSONB, nullable=False), sa.Column("created_by", sa.Uuid(), nullable=False), sa.Column("operation_key", sa.String(128), nullable=False), sa.Column("request_sha256", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["result_id"], ["core_comparison_results.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["analysis_id"], ["netflow_analyses.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["qualification_confirmation_id"], ["source_correlation_revisions.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="RESTRICT"), sa.UniqueConstraint("result_id", "revision", name="uq_core_supplement_revision"), sa.UniqueConstraint("result_id", "parent_id", name="uq_core_supplement_successor"))
    op.create_index("uq_core_supplement_root", "core_comparison_supplements", ["result_id"], unique=True, postgresql_where=sa.text("parent_id IS NULL"))

def downgrade() -> None:
    op.drop_index("uq_core_supplement_root", table_name="core_comparison_supplements")
    op.drop_table("core_comparison_supplements")
    op.drop_index("ix_core_result_scope_published", table_name="core_comparison_results")
    op.drop_table("core_comparison_results")
