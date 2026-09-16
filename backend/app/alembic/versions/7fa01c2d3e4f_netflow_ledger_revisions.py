"""Add immutable local NetFlow scope and handling revisions.

Revision ID: 7fa01c2d3e4f
Revises: 6ed2962462de
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "7fa01c2d3e4f"
down_revision = "6ed2962462de"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "netflow_ledger_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("namespace", sa.String(128), nullable=False),
        sa.Column("canonical_ip", sa.String(45)),
        sa.Column("cidrs", postgresql.JSONB(), nullable=False),
        sa.Column("collector", sa.String(255), nullable=False),
        sa.Column("location", sa.String(255), nullable=False),
        sa.Column("evidence", sa.String(1000), nullable=False),
        sa.Column("viewpoint", sa.String(20)),
        sa.Column("scope_status", sa.String(20)),
        sa.Column("followed", sa.Boolean(), nullable=False),
        sa.Column("excluded", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("operation_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_id", "project_id", "tenant_id"],
            [
                "netflow_datasets.id",
                "netflow_datasets.project_id",
                "netflow_datasets.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "project_id", "revision", name="uq_netflow_ledger_revision"
        ),
        sa.UniqueConstraint(
            "project_id",
            "created_by",
            "operation_key",
            name="uq_netflow_ledger_operation",
        ),
        sa.CheckConstraint("revision > 0", name="ck_netflow_ledger_revision"),
        sa.CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'", name="ck_netflow_ledger_request_hash"
        ),
        sa.CheckConstraint(
            "(kind = 'scope' AND canonical_ip IS NULL AND namespace IS NOT NULL AND jsonb_array_length(cidrs) > 0 AND scope_status IN ('CONFIRMED','UNKNOWN','CONFLICT','REVOKED')) OR (kind = 'management' AND canonical_ip IS NOT NULL AND namespace IS NOT NULL AND jsonb_array_length(cidrs) = 0 AND scope_status IS NULL)",
            name="ck_netflow_ledger_kind",
        ),
    )
    for field in ("project_id", "dataset_id", "canonical_ip"):
        op.create_index(
            "ix_netflow_ledger_revisions_" + field, "netflow_ledger_revisions", [field]
        )
    op.execute(
        "CREATE FUNCTION guard_netflow_ledger_revision() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'netflow ledger revision is immutable'; END $$"
    )
    op.execute(
        "CREATE TRIGGER netflow_ledger_revision_immutable BEFORE UPDATE OR DELETE ON netflow_ledger_revisions FOR EACH ROW EXECUTE FUNCTION guard_netflow_ledger_revision()"
    )


def downgrade():
    op.drop_table("netflow_ledger_revisions")
    op.execute("DROP FUNCTION guard_netflow_ledger_revision()")
