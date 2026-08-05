"""Add GovernanceRun Session recovery facts.

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
Create Date: 2026-08-11 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def _replace_protect_function(completed_statuses: str) -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION protect_governance_run_facts()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status IN ({completed_statuses}) THEN
                RAISE EXCEPTION 'completed governance_runs are immutable';
            END IF;
            IF ROW(
                NEW.tenant_id, NEW.project_id, NEW.trigger_id, NEW.session_id,
                NEW.requested_by, NEW.customer_upload_id,
                NEW.customer_upload_sha256, NEW.customer_upload_profile_id,
                NEW.customer_upload_profile_version, NEW.source_instance_id,
                NEW.cloudatlas_validated_fingerprint, NEW.cloudatlas_capset_id,
                NEW.cloudatlas_method, NEW.package_sha256,
                NEW.descriptor_sha256, NEW.runner_build_version, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.tenant_id, OLD.project_id, OLD.trigger_id, OLD.session_id,
                OLD.requested_by, OLD.customer_upload_id,
                OLD.customer_upload_sha256, OLD.customer_upload_profile_id,
                OLD.customer_upload_profile_version, OLD.source_instance_id,
                OLD.cloudatlas_validated_fingerprint, OLD.cloudatlas_capset_id,
                OLD.cloudatlas_method, OLD.package_sha256,
                OLD.descriptor_sha256, OLD.runner_build_version, OLD.created_at
            ) THEN
                RAISE EXCEPTION 'governance_run pinned facts are immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("governance_launch_trigger_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column(
            "governance_launch_control_run_id", sa.String(length=64), nullable=True
        ),
    )
    op.add_column(
        "projects",
        sa.Column("governance_launch_input_hash", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_projects_governance_launch_complete",
        "projects",
        "(governance_launch_trigger_id IS NULL AND "
        "governance_launch_control_run_id IS NULL AND "
        "governance_launch_input_hash IS NULL) OR "
        "(governance_launch_trigger_id IS NOT NULL AND "
        "governance_launch_control_run_id IS NOT NULL AND "
        "governance_launch_input_hash IS NOT NULL)",
    )
    op.add_column(
        "governance_runs",
        sa.Column("session_terminal_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "governance_runs",
        sa.Column("session_recovery_code", sa.String(length=100), nullable=True),
    )
    op.drop_constraint(
        "ck_governance_runs_status", "governance_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_governance_runs_status",
        "governance_runs",
        "status IN ('RUNNING', 'FAILED_DATA', 'FAILED_PROCESSING', "
        "'COMPLETED', 'COMPLETED_WITH_WARNINGS')",
    )
    _replace_protect_function("'COMPLETED', 'COMPLETED_WITH_WARNINGS'")


def downgrade() -> None:
    _replace_protect_function("'COMPLETED'")
    op.execute(
        "UPDATE governance_runs SET status = 'COMPLETED' "
        "WHERE status = 'COMPLETED_WITH_WARNINGS'"
    )
    op.drop_constraint(
        "ck_governance_runs_status", "governance_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_governance_runs_status",
        "governance_runs",
        "status IN ('RUNNING', 'FAILED_DATA', 'FAILED_PROCESSING', 'COMPLETED')",
    )
    op.drop_column("governance_runs", "session_recovery_code")
    op.drop_column("governance_runs", "session_terminal_at")
    op.drop_constraint(
        "ck_projects_governance_launch_complete", "projects", type_="check"
    )
    op.drop_column("projects", "governance_launch_input_hash")
    op.drop_column("projects", "governance_launch_control_run_id")
    op.drop_column("projects", "governance_launch_trigger_id")
