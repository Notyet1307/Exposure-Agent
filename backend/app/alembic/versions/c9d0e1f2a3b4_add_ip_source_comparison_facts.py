"""Add immutable IP source comparison facts and bounded Evidence targets.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-06 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def _install_ai_binding_guard(*, comparison_target: bool) -> None:
    comparison_check = (
        "AND selected_evidence.ip_source_comparison_fact_id IS NULL"
        if comparison_target
        else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION protect_ai_governance_draft_finding_bindings()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE draft_status text; draft_report_id uuid;
                draft_bindings_sealed_at timestamptz; selected_finding_count integer;
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN RAISE EXCEPTION 'ai_governance_draft finding bindings are immutable'; END IF;
            SELECT status, governance_report_id, bindings_sealed_at INTO draft_status, draft_report_id, draft_bindings_sealed_at
              FROM ai_governance_drafts WHERE id = NEW.draft_id AND governance_run_id = NEW.governance_run_id
              AND project_id = NEW.project_id AND tenant_id = NEW.tenant_id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'ai_governance_draft finding binding scope invalid'; END IF;
            IF draft_status <> 'GENERATING' OR draft_bindings_sealed_at IS NOT NULL THEN RAISE EXCEPTION 'ai_governance_draft finding bindings are sealed'; END IF;
            IF NOT EXISTS (
                SELECT 1 FROM findings AS selected_finding
                JOIN evidence AS selected_evidence ON selected_evidence.id = NEW.evidence_id
                   AND selected_evidence.governance_report_id = draft_report_id AND selected_evidence.governance_run_id = NEW.governance_run_id
                   AND selected_evidence.project_id = NEW.project_id AND selected_evidence.tenant_id = NEW.tenant_id
                JOIN governance_reports AS report ON report.id = draft_report_id AND report.governance_run_id = NEW.governance_run_id
                   AND report.project_id = NEW.project_id AND report.tenant_id = NEW.tenant_id
                CROSS JOIN LATERAL jsonb_array_elements(
                    CASE WHEN jsonb_typeof(
                        report.canonical_content -> 'evidence_plan' -> 'entries'
                    ) = 'array' THEN report.canonical_content -> 'evidence_plan' -> 'entries'
                    ELSE '[]'::jsonb END
                ) AS plan_entry
                WHERE selected_finding.id = NEW.finding_id
                  AND selected_finding.project_id = NEW.project_id AND selected_finding.tenant_id = NEW.tenant_id
                  AND selected_finding.finding_type = 'UNOBSERVED_ASSET' AND plan_entry ->> 'finding_id' = NEW.finding_id::text
                  AND plan_entry ->> 'finding_type' = 'UNOBSERVED_ASSET'
                  AND plan_entry #>> '{{evidence_reference,governance_run_id}}' = NEW.governance_run_id::text
                  {comparison_check}
                  AND (
                      (plan_entry #>> '{{evidence_reference,fact_type}}' = 'SOURCE_SNAPSHOT'
                       AND selected_evidence.source_snapshot_id::text = plan_entry #>> '{{evidence_reference,fact_id}}') OR
                      (plan_entry #>> '{{evidence_reference,fact_type}}' = 'OBSERVATION'
                       AND selected_evidence.observation_id::text = plan_entry #>> '{{evidence_reference,fact_id}}') OR
                      (plan_entry #>> '{{evidence_reference,fact_type}}' = 'FINDING_OCCURRENCE'
                       AND selected_evidence.finding_occurrence_id::text = plan_entry #>> '{{evidence_reference,fact_id}}') OR
                      (plan_entry #>> '{{evidence_reference,fact_type}}' = 'FINDING_TRANSITION'
                       AND selected_evidence.finding_transition_id::text = plan_entry #>> '{{evidence_reference,fact_id}}')
                  )
            ) THEN
                RAISE EXCEPTION 'ai_governance_draft finding binding scope invalid';
            END IF;
            SELECT count(DISTINCT finding_id) INTO selected_finding_count FROM ai_governance_draft_finding_bindings WHERE draft_id = NEW.draft_id;
            IF selected_finding_count >= 8 THEN RAISE EXCEPTION 'ai_governance_draft supports at most 8 findings'; END IF;
            RETURN NEW;
        END;
        $$
        """
    )


def upgrade() -> None:
    op.create_table(
        "ip_source_comparison_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("governance_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_version", sa.String(length=100), nullable=False),
        sa.Column("canonical_ip", sa.String(length=39), nullable=False),
        sa.Column("customer_upload_present", sa.Boolean(), nullable=False),
        sa.Column("cloudatlas_present", sa.Boolean(), nullable=False),
        sa.Column("netflow_status", sa.String(length=30), nullable=False),
        sa.Column("classification", sa.String(length=100), nullable=False),
        sa.Column("classification_reason", sa.String(length=100), nullable=False),
        sa.Column("netflow_reason", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "contract_version = 'ip-source-comparison/v1'",
            name="ck_ip_source_comparison_facts_contract",
        ),
        sa.CheckConstraint(
            "btrim(canonical_ip) <> ''",
            name="ck_ip_source_comparison_facts_ip_nonblank",
        ),
        sa.CheckConstraint(
            "(customer_upload_present AND cloudatlas_present "
            "AND classification = 'matched' "
            "AND classification_reason = 'observed_in_both_sources') OR "
            "(customer_upload_present AND NOT cloudatlas_present "
            "AND classification = 'customer_upload_only' "
            "AND classification_reason = 'observed_in_customer_upload_only') OR "
            "(NOT customer_upload_present AND cloudatlas_present "
            "AND classification = 'cloudatlas_only' "
            "AND classification_reason = 'observed_in_cloudatlas_only') OR "
            "(NOT customer_upload_present AND NOT cloudatlas_present "
            "AND classification = 'neither_source_observed' "
            "AND classification_reason = 'not_observed_in_either_source')",
            name="ck_ip_source_comparison_facts_classification",
        ),
        sa.CheckConstraint(
            "(netflow_status = 'ACTIVE' "
            "AND netflow_reason = 'positive_activity_observed') OR "
            "(netflow_status = 'UNKNOWN' AND netflow_reason IN "
            "('netflow_input_absent', 'no_positive_activity_evidence'))",
            name="ck_ip_source_comparison_facts_netflow",
        ),
        sa.CheckConstraint(
            "customer_upload_present OR cloudatlas_present OR netflow_status = 'ACTIVE'",
            name="ck_ip_source_comparison_facts_observed",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_ip_source_comparison_facts_hash_format",
        ),
        sa.ForeignKeyConstraint(
            ["governance_run_id", "project_id", "tenant_id"],
            [
                "governance_runs.id",
                "governance_runs.project_id",
                "governance_runs.tenant_id",
            ],
            name="fk_ip_source_comparison_facts_run_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id", "project_id", "tenant_id"],
            ["resources.id", "resources.project_id", "resources.tenant_id"],
            name="fk_ip_source_comparison_facts_resource_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            name="uq_ip_source_comparison_facts_scope",
        ),
        sa.UniqueConstraint(
            "governance_run_id",
            "resource_id",
            name="uq_ip_source_comparison_facts_run_resource",
        ),
        sa.UniqueConstraint(
            "governance_run_id",
            "canonical_ip",
            name="uq_ip_source_comparison_facts_run_ip",
        ),
    )
    for column in ("tenant_id", "project_id", "governance_run_id", "resource_id"):
        op.create_index(
            f"ix_ip_source_comparison_facts_{column}",
            "ip_source_comparison_facts",
            [column],
        )
    op.execute(
        "CREATE TRIGGER ip_source_comparison_facts_reject_completed_insert "
        "BEFORE INSERT ON ip_source_comparison_facts FOR EACH ROW "
        "EXECUTE FUNCTION reject_completed_run_report_fact_mutation()"
    )
    op.execute(
        "CREATE TRIGGER ip_source_comparison_facts_immutable "
        "BEFORE UPDATE OR DELETE ON ip_source_comparison_facts FOR EACH ROW "
        "EXECUTE FUNCTION reject_stage4_fact_mutation()"
    )
    op.add_column(
        "evidence",
        sa.Column(
            "ip_source_comparison_fact_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_index(
        "ix_evidence_ip_source_comparison_fact_id",
        "evidence",
        ["ip_source_comparison_fact_id"],
    )
    op.create_foreign_key(
        "fk_evidence_ip_source_comparison_scope",
        "evidence",
        "ip_source_comparison_facts",
        [
            "ip_source_comparison_fact_id",
            "governance_run_id",
            "project_id",
            "tenant_id",
        ],
        ["id", "governance_run_id", "project_id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_evidence_report_ip_source_comparison",
        "evidence",
        ["governance_report_id", "ip_source_comparison_fact_id"],
    )
    op.drop_constraint("ck_evidence_exactly_one_target", "evidence", type_="check")
    op.create_check_constraint(
        "ck_evidence_exactly_one_target",
        "evidence",
        "num_nonnulls(source_snapshot_id, observation_id, finding_occurrence_id, "
        "finding_transition_id, ip_source_comparison_fact_id) = 1",
    )
    _install_ai_binding_guard(comparison_target=True)


def downgrade() -> None:
    _install_ai_binding_guard(comparison_target=False)
    op.drop_constraint("ck_evidence_exactly_one_target", "evidence", type_="check")
    op.create_check_constraint(
        "ck_evidence_exactly_one_target",
        "evidence",
        "num_nonnulls(source_snapshot_id, observation_id, finding_occurrence_id, finding_transition_id) = 1",
    )
    op.drop_constraint(
        "uq_evidence_report_ip_source_comparison", "evidence", type_="unique"
    )
    op.drop_constraint(
        "fk_evidence_ip_source_comparison_scope", "evidence", type_="foreignkey"
    )
    op.drop_index("ix_evidence_ip_source_comparison_fact_id", table_name="evidence")
    op.drop_column("evidence", "ip_source_comparison_fact_id")
    op.drop_table("ip_source_comparison_facts")
