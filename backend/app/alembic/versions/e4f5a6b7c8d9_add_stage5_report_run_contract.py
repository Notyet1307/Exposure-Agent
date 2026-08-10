"""Add the Stage 5 report contract to GovernanceRun and RunStep.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-08-13 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def _install_governance_run_protection(*, include_report_contract: bool) -> None:
    report_contract_new = (
        ", NEW.report_contract_version" if include_report_contract else ""
    )
    report_contract_old = (
        ", OLD.report_contract_version" if include_report_contract else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION protect_governance_run_facts()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status = 'COMPLETED' THEN
                RAISE EXCEPTION 'completed governance_runs are immutable';
            END IF;
            IF ROW(
                NEW.tenant_id, NEW.project_id, NEW.trigger_id, NEW.session_id,
                NEW.requested_by, NEW.customer_upload_id,
                NEW.customer_upload_sha256, NEW.customer_upload_profile_id,
                NEW.customer_upload_profile_version, NEW.source_instance_id,
                NEW.cloudatlas_validated_fingerprint, NEW.cloudatlas_capset_id,
                NEW.cloudatlas_method, NEW.package_sha256,
                NEW.descriptor_sha256, NEW.runner_build_version,
                NEW.processing_contract_version{report_contract_new}, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.tenant_id, OLD.project_id, OLD.trigger_id, OLD.session_id,
                OLD.requested_by, OLD.customer_upload_id,
                OLD.customer_upload_sha256, OLD.customer_upload_profile_id,
                OLD.customer_upload_profile_version, OLD.source_instance_id,
                OLD.cloudatlas_validated_fingerprint, OLD.cloudatlas_capset_id,
                OLD.cloudatlas_method, OLD.package_sha256,
                OLD.descriptor_sha256, OLD.runner_build_version,
                OLD.processing_contract_version{report_contract_old}, OLD.created_at
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
        "governance_runs",
        sa.Column("report_contract_version", sa.String(length=100), nullable=True),
    )
    op.create_check_constraint(
        "ck_governance_runs_report_contract_version",
        "governance_runs",
        "report_contract_version IS NULL OR btrim(report_contract_version) <> ''",
    )

    op.drop_constraint("ck_run_steps_code", "run_steps", type_="check")
    op.create_check_constraint(
        "ck_run_steps_code",
        "run_steps",
        "step_code IN ('LOAD_CUSTOMER', 'PULL_CLOUDATLAS', 'NORMALIZE', "
        "'RESOLVE', 'CHECK_FINDINGS', 'BUILD_REPORT', 'VALIDATE_REPORT', "
        "'PUBLISH')",
    )

    _install_governance_run_protection(include_report_contract=True)


def downgrade() -> None:
    _install_governance_run_protection(include_report_contract=False)

    op.drop_constraint("ck_run_steps_code", "run_steps", type_="check")
    op.create_check_constraint(
        "ck_run_steps_code",
        "run_steps",
        "step_code IN ('LOAD_CUSTOMER', 'PULL_CLOUDATLAS', 'NORMALIZE', "
        "'RESOLVE', 'CHECK_FINDINGS', 'PUBLISH')",
    )
    op.drop_constraint(
        "ck_governance_runs_report_contract_version",
        "governance_runs",
        type_="check",
    )
    op.drop_column("governance_runs", "report_contract_version")
