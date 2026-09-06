"""Add deterministic managed-IP NetFlow activity facts.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-06 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "netflow_ip_activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("governance_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "aggregation_contract_version", sa.String(length=100), nullable=False
        ),
        sa.Column("flow_count", sa.Integer(), nullable=False),
        sa.Column("peer_ips", postgresql.ARRAY(postgresql.INET()), nullable=False),
        sa.Column("protocols", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("first_seen_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_type = 'NETFLOW'", name="ck_netflow_ip_activities_source_type"
        ),
        sa.CheckConstraint(
            "flow_count > 0", name="ck_netflow_ip_activities_flow_count_positive"
        ),
        sa.CheckConstraint(
            "btrim(aggregation_contract_version) <> ''",
            name="ck_netflow_ip_activities_contract_nonblank",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_netflow_ip_activities_hash_format",
        ),
        sa.ForeignKeyConstraint(
            ["governance_run_id", "project_id", "tenant_id"],
            [
                "governance_runs.id",
                "governance_runs.project_id",
                "governance_runs.tenant_id",
            ],
            name="fk_netflow_ip_activities_run_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "source_snapshot_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
                "source_type",
            ],
            [
                "source_snapshots.id",
                "source_snapshots.governance_run_id",
                "source_snapshots.project_id",
                "source_snapshots.tenant_id",
                "source_snapshots.source_type",
            ],
            name="fk_netflow_ip_activities_snapshot_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id", "project_id", "tenant_id"],
            ["resources.id", "resources.project_id", "resources.tenant_id"],
            name="fk_netflow_ip_activities_resource_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            name="uq_netflow_ip_activities_scope",
        ),
        sa.UniqueConstraint(
            "governance_run_id",
            "resource_id",
            name="uq_netflow_ip_activities_run_resource",
        ),
    )
    for column in (
        "tenant_id",
        "project_id",
        "governance_run_id",
        "source_snapshot_id",
        "resource_id",
    ):
        op.create_index(
            f"ix_netflow_ip_activities_{column}",
            "netflow_ip_activities",
            [column],
        )
    for suffix, function in (
        ("reject_completed_insert", "reject_completed_run_child_insert"),
        ("require_processing_contract", "require_stage4_processing_contract"),
        ("immutable", "reject_stage4_fact_mutation"),
    ):
        operation = "INSERT" if suffix != "immutable" else "UPDATE OR DELETE"
        op.execute(
            f"CREATE TRIGGER netflow_ip_activities_{suffix} "
            f"BEFORE {operation} ON netflow_ip_activities FOR EACH ROW "
            f"EXECUTE FUNCTION {function}()"
        )


def downgrade() -> None:
    for suffix in (
        "immutable",
        "require_processing_contract",
        "reject_completed_insert",
    ):
        op.execute(
            f"DROP TRIGGER netflow_ip_activities_{suffix} ON netflow_ip_activities"
        )
    op.drop_table("netflow_ip_activities")
