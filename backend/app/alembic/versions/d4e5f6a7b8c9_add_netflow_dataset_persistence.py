"""Add immutable project-scoped NetFlowDataset persistence.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_artifacts_project_scope", "artifacts", ["id", "project_id", "tenant_id"]
    )
    op.create_unique_constraint(
        "uq_artifacts_project_scope_hash", "artifacts", ["id", "project_id", "tenant_id", "sha256"]
    )
    op.create_table(
        "netflow_datasets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalized_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_filename", sa.String(length=128), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("normalized_sha256", sa.String(length=64), nullable=False),
        sa.Column("dataset_contract_version", sa.String(length=100), nullable=False),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("encoding", sa.String(length=32), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("raw_record_count", sa.Integer(), nullable=False),
        sa.Column("activity_valid_record_count", sa.Integer(), nullable=False),
        sa.Column("isolated_record_count", sa.Integer(), nullable=False),
        sa.Column("valid_time_start_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_time_end_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duplicate_group_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_record_count", sa.Integer(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id", "tenant_id"], ["projects.id", "projects.tenant_id"], name="fk_netflow_datasets_project_scope", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["raw_artifact_id", "project_id", "tenant_id", "raw_sha256"], ["artifacts.id", "artifacts.project_id", "artifacts.tenant_id", "artifacts.sha256"], name="fk_netflow_datasets_raw_artifact_scope_hash", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["normalized_artifact_id", "project_id", "tenant_id", "normalized_sha256"], ["artifacts.id", "artifacts.project_id", "artifacts.tenant_id", "artifacts.sha256"], name="fk_netflow_datasets_normalized_artifact_scope_hash", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "tenant_id", name="uq_netflow_datasets_scope"),
        sa.UniqueConstraint("project_id", "tenant_id", "raw_sha256", "dataset_contract_version", name="uq_netflow_datasets_idempotency"),
        sa.CheckConstraint("raw_artifact_id <> normalized_artifact_id", name="ck_netflow_datasets_distinct_artifacts"),
        sa.CheckConstraint("byte_size > 0", name="ck_netflow_datasets_byte_size_positive"),
        sa.CheckConstraint("raw_record_count = activity_valid_record_count + isolated_record_count", name="ck_netflow_datasets_count_sum"),
        sa.CheckConstraint("dataset_contract_version <> ''", name="ck_netflow_datasets_contract_nonblank"),
        sa.CheckConstraint("raw_sha256 ~ '^[0-9a-f]{64}$' AND normalized_sha256 ~ '^[0-9a-f]{64}$'", name="ck_netflow_datasets_hash_format"),
        sa.CheckConstraint("raw_record_count >= 0 AND activity_valid_record_count >= 0 AND isolated_record_count >= 0", name="ck_netflow_datasets_counts_nonnegative"),
        sa.CheckConstraint("encoding IN ('utf-8-sig', 'gb18030')", name="ck_netflow_datasets_encoding"),
        sa.CheckConstraint("schema_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_netflow_datasets_schema_hash_format"),
        sa.CheckConstraint("duplicate_group_count >= 0 AND duplicate_record_count >= 0", name="ck_netflow_datasets_duplicate_counts_nonnegative"),
    )
    for column in ("project_id", "tenant_id", "raw_sha256"):
        op.create_index(f"ix_netflow_datasets_{column}", "netflow_datasets", [column])
    op.execute("""
        CREATE FUNCTION reject_netflow_dataset_update()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'netflow_datasets records are immutable'; END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER netflow_datasets_immutable
        BEFORE UPDATE ON netflow_datasets FOR EACH ROW
        EXECUTE FUNCTION reject_netflow_dataset_update()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER netflow_datasets_immutable ON netflow_datasets")
    op.execute("DROP FUNCTION reject_netflow_dataset_update()")
    for column in ("project_id", "tenant_id", "raw_sha256"):
        op.drop_index(f"ix_netflow_datasets_{column}", table_name="netflow_datasets")
    op.drop_table("netflow_datasets")
    op.drop_constraint("uq_artifacts_project_scope_hash", "artifacts", type_="unique")
    op.drop_constraint("uq_artifacts_project_scope", "artifacts", type_="unique")
