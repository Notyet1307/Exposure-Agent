"""Add deployment model qualification results.

Revision ID: b1c2d3e4f5a6
Revises: a2b3c4d5e6f7
Create Date: 2026-08-20 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b1c2d3e4f5a6"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_qualification_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_endpoint_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_identity", sa.String(length=255), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("fixture_version", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("availability_numerator", sa.Integer(), nullable=False),
        sa.Column("availability_denominator", sa.Integer(), nullable=False),
        sa.Column("traceable_citations", sa.Integer(), nullable=False),
        sa.Column("total_citations", sa.Integer(), nullable=False),
        sa.Column("hallucination_count", sa.Integer(), nullable=False),
        sa.Column("finding_modification_count", sa.Integer(), nullable=False),
        sa.Column("unauthorized_side_effect_count", sa.Integer(), nullable=False),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("agent_compose_run_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PASS', 'FAIL')",
            name="ck_model_qualification_results_status",
        ),
        sa.CheckConstraint(
            "availability_numerator >= 0 AND availability_denominator > 0 "
            "AND availability_numerator <= availability_denominator",
            name="ck_model_qualification_results_availability",
        ),
        sa.CheckConstraint(
            "traceable_citations >= 0 AND total_citations >= 0 "
            "AND traceable_citations <= total_citations",
            name="ck_model_qualification_results_citations",
        ),
        sa.CheckConstraint(
            "hallucination_count >= 0 AND finding_modification_count >= 0 "
            "AND unauthorized_side_effect_count >= 0",
            name="ck_model_qualification_results_violation_counts",
        ),
        sa.CheckConstraint(
            "(status = 'PASS' AND availability_numerator * 4 >= "
            "availability_denominator * 3 AND total_citations > 0 AND "
            "traceable_citations = total_citations AND hallucination_count = 0 "
            "AND finding_modification_count = 0 AND "
            "unauthorized_side_effect_count = 0 AND failure_code IS NULL) OR "
            "(status = 'FAIL' AND failure_code IS NOT NULL)",
            name="ck_model_qualification_results_verdict",
        ),
        sa.CheckConstraint(
            "model_endpoint_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_model_qualification_results_endpoint_fingerprint",
        ),
        sa.CheckConstraint(
            "config_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_model_qualification_results_config_fingerprint",
        ),
        sa.CheckConstraint(
            "agent_compose_run_id ~ '^[0-9a-f]{64}$'",
            name="ck_model_qualification_results_run_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_compose_run_id",
            name="uq_model_qualification_results_agent_compose_run",
        ),
    )
    op.create_index(
        "ix_model_qualification_results_model_endpoint_sha256",
        "model_qualification_results",
        ["model_endpoint_sha256"],
    )
    op.create_index(
        "ix_model_qualification_results_config_fingerprint",
        "model_qualification_results",
        ["config_fingerprint"],
    )
    op.create_index(
        "ix_model_qualification_results_status",
        "model_qualification_results",
        ["status"],
    )
    op.execute(
        """
        CREATE FUNCTION protect_model_qualification_results()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'model qualification results are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER model_qualification_results_immutable
        BEFORE UPDATE OR DELETE ON model_qualification_results
        FOR EACH ROW EXECUTE FUNCTION protect_model_qualification_results()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER model_qualification_results_immutable "
        "ON model_qualification_results"
    )
    op.execute("DROP FUNCTION protect_model_qualification_results()")
    op.drop_index(
        "ix_model_qualification_results_status",
        table_name="model_qualification_results",
    )
    op.drop_index(
        "ix_model_qualification_results_config_fingerprint",
        table_name="model_qualification_results",
    )
    op.drop_index(
        "ix_model_qualification_results_model_endpoint_sha256",
        table_name="model_qualification_results",
    )
    op.drop_table("model_qualification_results")
