"""Add Run-scoped Evidence and completed report fact guards.

Revision ID: a2b3c4d5e6f7
Revises: f5a6b7c8d9e0
Create Date: 2026-08-15 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a2b3c4d5e6f7"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def _install_governance_run_protection(*, all_completed_statuses: bool) -> None:
    completed_predicate = (
        "OLD.status LIKE 'COMPLETED%'"
        if all_completed_statuses
        else "OLD.status = 'COMPLETED'"
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION protect_governance_run_facts()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF {completed_predicate} THEN
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


def _create_completed_run_guards() -> None:
    # The row lock serializes report-fact writes with Run publication. A write
    # that wins the lock is part of the pre-completion transaction history; a
    # write that loses observes the committed completed status and is rejected.
    op.execute(
        """
        CREATE FUNCTION reject_completed_run_report_fact_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            scoped_run_ids uuid[];
            run_status text;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                scoped_run_ids := ARRAY[NEW.governance_run_id];
            ELSIF TG_OP = 'DELETE' THEN
                scoped_run_ids := ARRAY[OLD.governance_run_id];
            ELSE
                scoped_run_ids := ARRAY[
                    OLD.governance_run_id,
                    NEW.governance_run_id
                ];
            END IF;

            FOR run_status IN
                SELECT status
                FROM governance_runs
                WHERE id = ANY(scoped_run_ids)
                ORDER BY id
                FOR UPDATE
            LOOP
                IF run_status LIKE 'COMPLETED%' THEN
                    RAISE EXCEPTION
                        'completed governance_runs cannot mutate % records',
                        TG_TABLE_NAME;
                END IF;
            END LOOP;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table_name in ("governance_reports", "evidence"):
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_reject_completed_mutation
            BEFORE INSERT OR UPDATE OR DELETE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION reject_completed_run_report_fact_mutation()
            """
        )


def upgrade() -> None:
    op.drop_constraint("ck_governance_runs_status", "governance_runs", type_="check")
    op.create_check_constraint(
        "ck_governance_runs_status",
        "governance_runs",
        "status IN ('RUNNING', 'FAILED_DATA', 'FAILED_PROCESSING', "
        "'COMPLETED', 'COMPLETED_WITH_WARNINGS')",
    )

    op.create_table(
        "evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "governance_run_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "governance_report_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "source_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "finding_occurrence_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "finding_transition_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
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
            "num_nonnulls(source_snapshot_id, observation_id, "
            "finding_occurrence_id, finding_transition_id) = 1",
            name="ck_evidence_exactly_one_target",
        ),
        sa.ForeignKeyConstraint(
            [
                "governance_report_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
            ],
            [
                "governance_reports.id",
                "governance_reports.governance_run_id",
                "governance_reports.project_id",
                "governance_reports.tenant_id",
            ],
            name="fk_evidence_governance_report_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "source_snapshot_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
            ],
            [
                "source_snapshots.id",
                "source_snapshots.governance_run_id",
                "source_snapshots.project_id",
                "source_snapshots.tenant_id",
            ],
            name="fk_evidence_source_snapshot_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id", "governance_run_id", "project_id", "tenant_id"],
            [
                "observations.id",
                "observations.governance_run_id",
                "observations.project_id",
                "observations.tenant_id",
            ],
            name="fk_evidence_observation_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "finding_occurrence_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
            ],
            [
                "finding_occurrences.id",
                "finding_occurrences.governance_run_id",
                "finding_occurrences.project_id",
                "finding_occurrences.tenant_id",
            ],
            name="fk_evidence_finding_occurrence_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "finding_transition_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
            ],
            [
                "finding_transitions.id",
                "finding_transitions.governance_run_id",
                "finding_transitions.project_id",
                "finding_transitions.tenant_id",
            ],
            name="fk_evidence_finding_transition_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            name="uq_evidence_scope",
        ),
    )
    for column in (
        "tenant_id",
        "project_id",
        "governance_run_id",
        "governance_report_id",
        "source_snapshot_id",
        "observation_id",
        "finding_occurrence_id",
        "finding_transition_id",
    ):
        op.create_index(f"ix_evidence_{column}", "evidence", [column])

    _install_governance_run_protection(all_completed_statuses=True)
    _create_completed_run_guards()


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER governance_reports_reject_completed_mutation "
        "ON governance_reports"
    )
    op.drop_table("evidence")
    op.execute("DROP FUNCTION reject_completed_run_report_fact_mutation()")
    _install_governance_run_protection(all_completed_statuses=False)
    op.drop_constraint("ck_governance_runs_status", "governance_runs", type_="check")
    op.create_check_constraint(
        "ck_governance_runs_status",
        "governance_runs",
        "status IN ('RUNNING', 'FAILED_DATA', 'FAILED_PROCESSING', 'COMPLETED')",
    )
