"""Pin optional NetFlow input facts on GovernanceRun.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def _install_governance_run_protection() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_governance_run_facts()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status LIKE 'COMPLETED%' THEN
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
                NEW.input_contract_version, NEW.input_hash,
                NEW.netflow_dataset_id, NEW.netflow_content_sha256,
                NEW.netflow_dataset_contract_version,
                NEW.processing_contract_version, NEW.report_contract_version,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.tenant_id, OLD.project_id, OLD.trigger_id, OLD.session_id,
                OLD.requested_by, OLD.customer_upload_id,
                OLD.customer_upload_sha256, OLD.customer_upload_profile_id,
                OLD.customer_upload_profile_version, OLD.source_instance_id,
                OLD.cloudatlas_validated_fingerprint, OLD.cloudatlas_capset_id,
                OLD.cloudatlas_method, OLD.package_sha256,
                OLD.descriptor_sha256, OLD.runner_build_version,
                OLD.input_contract_version, OLD.input_hash,
                OLD.netflow_dataset_id, OLD.netflow_content_sha256,
                OLD.netflow_dataset_contract_version,
                OLD.processing_contract_version, OLD.report_contract_version,
                OLD.created_at
            ) THEN
                RAISE EXCEPTION 'governance_run pinned facts are immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )

def _restore_previous_governance_run_protection() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_governance_run_facts()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status LIKE 'COMPLETED%' THEN
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
                NEW.processing_contract_version, NEW.report_contract_version,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.tenant_id, OLD.project_id, OLD.trigger_id, OLD.session_id,
                OLD.requested_by, OLD.customer_upload_id,
                OLD.customer_upload_sha256, OLD.customer_upload_profile_id,
                OLD.customer_upload_profile_version, OLD.source_instance_id,
                OLD.cloudatlas_validated_fingerprint, OLD.cloudatlas_capset_id,
                OLD.cloudatlas_method, OLD.package_sha256,
                OLD.descriptor_sha256, OLD.runner_build_version,
                OLD.processing_contract_version, OLD.report_contract_version,
                OLD.created_at
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
        sa.Column("input_contract_version", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "governance_runs",
        sa.Column("input_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "governance_runs",
        sa.Column("netflow_dataset_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "governance_runs",
        sa.Column("netflow_content_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "governance_runs",
        sa.Column(
            "netflow_dataset_contract_version", sa.String(length=100), nullable=True
        ),
    )
    op.create_check_constraint(
        "ck_governance_runs_input_contract",
        "governance_runs",
        "((input_contract_version IS NULL AND input_hash IS NULL AND "
        "netflow_dataset_id IS NULL AND netflow_content_sha256 IS NULL AND "
        "netflow_dataset_contract_version IS NULL) OR ("
        "input_contract_version = 'governance-run-input-v1' AND input_hash IS NOT NULL AND "
        "((netflow_dataset_id IS NULL AND netflow_content_sha256 IS NULL AND "
        "netflow_dataset_contract_version IS NULL) OR ("
        "netflow_dataset_id IS NOT NULL AND netflow_content_sha256 IS NOT NULL AND "
        "netflow_dataset_contract_version IS NOT NULL))))",
    )
    op.create_check_constraint(
        "ck_governance_runs_input_hash",
        "governance_runs",
        "input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'",
    )
    op.create_foreign_key(
        "fk_governance_runs_netflow_dataset_scope",
        "governance_runs",
        "netflow_datasets",
        ["netflow_dataset_id", "project_id", "tenant_id"],
        ["id", "project_id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_governance_runs_netflow_content_scope",
        "governance_runs",
        "netflow_datasets",
        [
            "project_id",
            "tenant_id",
            "netflow_content_sha256",
            "netflow_dataset_contract_version",
        ],
        ["project_id", "tenant_id", "raw_sha256", "dataset_contract_version"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_governance_runs_netflow_dataset_id"),
        "governance_runs",
        ["netflow_dataset_id"],
    )
    _install_governance_run_protection()


def downgrade() -> None:
    _restore_previous_governance_run_protection()
    op.drop_index(
        op.f("ix_governance_runs_netflow_dataset_id"), table_name="governance_runs"
    )
    op.drop_constraint(
        "fk_governance_runs_netflow_content_scope",
        "governance_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_governance_runs_netflow_dataset_scope",
        "governance_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_governance_runs_input_hash", "governance_runs", type_="check"
    )
    op.drop_constraint(
        "ck_governance_runs_input_contract", "governance_runs", type_="check"
    )
    op.drop_column("governance_runs", "netflow_dataset_contract_version")
    op.drop_column("governance_runs", "netflow_content_sha256")
    op.drop_column("governance_runs", "netflow_dataset_id")
    op.drop_column("governance_runs", "input_hash")
    op.drop_column("governance_runs", "input_contract_version")
