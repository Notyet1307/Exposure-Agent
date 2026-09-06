"""Add NETFLOW SourceSnapshot persistence.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_snapshots",
        sa.Column("netflow_dataset_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "source_snapshots",
        sa.Column("valid_time_start_utc", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "source_snapshots",
        sa.Column("valid_time_end_utc", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_source_snapshots_netflow_dataset_id",
        "source_snapshots",
        ["netflow_dataset_id"],
    )
    op.create_foreign_key(
        "fk_source_snapshots_netflow_dataset_scope",
        "source_snapshots",
        "netflow_datasets",
        ["netflow_dataset_id", "project_id", "tenant_id"],
        ["id", "project_id", "tenant_id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "ck_source_snapshots_source_reference", "source_snapshots", type_="check"
    )
    op.drop_constraint("ck_source_snapshots_type", "source_snapshots", type_="check")
    op.create_check_constraint(
        "ck_source_snapshots_type",
        "source_snapshots",
        "source_type IN ('CUSTOMER_UPLOAD', 'CLOUDATLAS', 'NETFLOW')",
    )
    op.create_check_constraint(
        "ck_source_snapshots_source_reference",
        "source_snapshots",
        "(source_type = 'CUSTOMER_UPLOAD' AND customer_upload_id IS NOT NULL "
        "AND source_instance_id IS NULL AND netflow_dataset_id IS NULL "
        "AND method_fingerprint IS NULL AND valid_time_start_utc IS NULL "
        "AND valid_time_end_utc IS NULL) OR "
        "(source_type = 'CLOUDATLAS' AND customer_upload_id IS NULL "
        "AND source_instance_id IS NOT NULL AND netflow_dataset_id IS NULL "
        "AND method_fingerprint IS NOT NULL AND valid_time_start_utc IS NULL "
        "AND valid_time_end_utc IS NULL) OR "
        "(source_type = 'NETFLOW' AND customer_upload_id IS NULL "
        "AND source_instance_id IS NULL AND netflow_dataset_id IS NOT NULL "
        "AND method_fingerprint IS NULL)",
    )

    op.drop_constraint("ck_run_steps_code", "run_steps", type_="check")
    op.create_check_constraint(
        "ck_run_steps_code",
        "run_steps",
        "step_code IN ('LOAD_CUSTOMER', 'PULL_CLOUDATLAS', 'LOAD_NETFLOW', "
        "'NORMALIZE', 'RESOLVE', 'CHECK_FINDINGS', 'BUILD_REPORT', "
        "'VALIDATE_REPORT', 'PUBLISH')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_run_steps_code", "run_steps", type_="check")
    op.create_check_constraint(
        "ck_run_steps_code",
        "run_steps",
        "step_code IN ('LOAD_CUSTOMER', 'PULL_CLOUDATLAS', 'NORMALIZE', "
        "'RESOLVE', 'CHECK_FINDINGS', 'BUILD_REPORT', 'VALIDATE_REPORT', "
        "'PUBLISH')",
    )

    op.drop_constraint(
        "ck_source_snapshots_source_reference", "source_snapshots", type_="check"
    )
    op.drop_constraint("ck_source_snapshots_type", "source_snapshots", type_="check")
    op.drop_constraint(
        "fk_source_snapshots_netflow_dataset_scope",
        "source_snapshots",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_source_snapshots_netflow_dataset_id", table_name="source_snapshots"
    )
    op.drop_column("source_snapshots", "valid_time_end_utc")
    op.drop_column("source_snapshots", "valid_time_start_utc")
    op.drop_column("source_snapshots", "netflow_dataset_id")
    op.create_check_constraint(
        "ck_source_snapshots_type",
        "source_snapshots",
        "source_type IN ('CUSTOMER_UPLOAD', 'CLOUDATLAS')",
    )
    op.create_check_constraint(
        "ck_source_snapshots_source_reference",
        "source_snapshots",
        "(source_type = 'CUSTOMER_UPLOAD' AND customer_upload_id IS NOT NULL "
        "AND source_instance_id IS NULL AND method_fingerprint IS NULL) OR "
        "(source_type = 'CLOUDATLAS' AND customer_upload_id IS NULL "
        "AND source_instance_id IS NOT NULL AND method_fingerprint IS NOT NULL)",
    )
