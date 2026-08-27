"""Add AI governance draft aggregate and sealed finding bindings.

Revision ID: a1b2c3d4e5f6
Revises: e3f4a5b6c7d8
Create Date: 2026-08-25 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a1b2c3d4e5f6"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None

_DRAFT_CHECKS = {
    "ck_ai_governance_drafts_status": "status IN ('GENERATING', 'REVIEWABLE', 'FAILED')",
    "ck_ai_governance_drafts_review_decision": "review_decision IS NULL OR review_decision IN ('ACCEPTED', 'EDITED', 'REJECTED')",
    "ck_ai_governance_drafts_report_sha256": "report_sha256 ~ '^[0-9a-f]{64}$'",
    "ck_ai_governance_drafts_config_fingerprint": "config_fingerprint ~ '^[0-9a-f]{64}$'",
    "ck_ai_governance_drafts_session_id": "session_id IS NULL OR session_id ~ '^[0-9a-f]{64}$'",
    "ck_ai_governance_drafts_agent_compose_run_id": "agent_compose_run_id IS NULL OR agent_compose_run_id ~ '^[0-9a-f]{64}$'",
    "ck_ai_governance_drafts_failure_code": "failure_code IS NULL OR failure_code ~ '^[a-z][a-z0-9_]{0,99}$'",
    "ck_ai_governance_drafts_identity_pins": "btrim(idempotency_key) <> '' AND btrim(initiated_by) <> '' AND btrim(model_identity) <> '' AND (failure_code IS NULL OR btrim(failure_code) <> '') AND (reviewed_by IS NULL OR btrim(reviewed_by) <> '')",
    "ck_ai_governance_drafts_session_binding": "(session_id IS NULL AND agent_compose_run_id IS NULL) OR (session_id IS NOT NULL AND agent_compose_run_id IS NOT NULL)",
    "ck_ai_governance_drafts_binding_seal": "bindings_sealed_at IS NULL OR bindings_sealed_at >= created_at",
    "ck_ai_governance_drafts_json_objects": "(model_output IS NULL OR jsonb_typeof(model_output) = 'object') AND (operator_edited_output IS NULL OR jsonb_typeof(operator_edited_output) = 'object')",
    "ck_ai_governance_drafts_generation_consistency": "(status = 'GENERATING' AND model_output IS NULL AND failure_code IS NULL AND generation_terminal_at IS NULL AND review_decision IS NULL) OR (status = 'REVIEWABLE' AND model_output IS NOT NULL AND failure_code IS NULL AND generation_terminal_at IS NOT NULL AND session_id IS NOT NULL) OR (status = 'FAILED' AND model_output IS NULL AND failure_code IS NOT NULL AND generation_terminal_at IS NOT NULL AND review_decision IS NULL)",
    "ck_ai_governance_drafts_review_consistency": "(review_decision IS NULL AND reviewed_by IS NULL AND reviewed_at IS NULL AND operator_edited_output IS NULL) OR (review_decision = 'EDITED' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND operator_edited_output IS NOT NULL) OR (review_decision IN ('ACCEPTED', 'REJECTED') AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND operator_edited_output IS NULL)",
}


def _install_draft_protection() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_independent_agent_compose_session() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.session_id IS NULL THEN RETURN NEW; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(NEW.session_id, 0));
            IF TG_TABLE_NAME = 'governance_runs' THEN
                IF EXISTS (SELECT 1 FROM ai_governance_drafts WHERE session_id = NEW.session_id) THEN
                    RAISE EXCEPTION 'agent-compose session must be independent';
                END IF;
            ELSIF EXISTS (SELECT 1 FROM governance_runs WHERE session_id = NEW.session_id) THEN
                RAISE EXCEPTION 'agent-compose session must be independent';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_ai_governance_draft_facts() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE project_archived_at timestamptz;
        BEGIN
            IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'ai_governance_drafts are immutable history'; END IF;
            SELECT archived_at INTO project_archived_at FROM projects WHERE id = NEW.project_id AND tenant_id = NEW.tenant_id FOR UPDATE;
            IF NOT FOUND OR project_archived_at IS NOT NULL THEN RAISE EXCEPTION 'archived projects are read-only'; END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'GENERATING' OR NEW.model_output IS NOT NULL OR NEW.failure_code IS NOT NULL
                   OR NEW.generation_terminal_at IS NOT NULL OR NEW.review_decision IS NOT NULL
                   OR NEW.agent_compose_run_id IS NOT NULL OR NEW.session_id IS NOT NULL OR NEW.bindings_sealed_at IS NOT NULL THEN
                    RAISE EXCEPTION 'ai_governance_drafts must start in GENERATING';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM governance_reports AS report
                    JOIN governance_runs AS run ON run.id = report.governance_run_id
                       AND run.project_id = report.project_id AND run.tenant_id = report.tenant_id
                    WHERE report.id = NEW.governance_report_id AND report.governance_run_id = NEW.governance_run_id
                      AND report.project_id = NEW.project_id AND report.tenant_id = NEW.tenant_id
                      AND run.status IN ('COMPLETED', 'COMPLETED_WITH_WARNINGS')
                      AND run.completed_at IS NOT NULL
                ) THEN
                    RAISE EXCEPTION 'ai_governance_drafts require a published report';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.review_decision IS NOT NULL OR OLD.status = 'FAILED' THEN RAISE EXCEPTION 'terminal ai_governance_drafts are immutable'; END IF;
            IF OLD.status = 'REVIEWABLE' THEN
                IF ROW(
                    NEW.tenant_id, NEW.project_id, NEW.governance_run_id, NEW.governance_report_id,
                    NEW.report_sha256, NEW.initiated_by, NEW.idempotency_key,
                    NEW.model_identity, NEW.config_fingerprint, NEW.agent_compose_run_id,
                    NEW.session_id, NEW.bindings_sealed_at, NEW.status, NEW.model_output,
                    NEW.failure_code, NEW.generation_terminal_at, NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.tenant_id, OLD.project_id, OLD.governance_run_id, OLD.governance_report_id,
                    OLD.report_sha256, OLD.initiated_by, OLD.idempotency_key,
                    OLD.model_identity, OLD.config_fingerprint, OLD.agent_compose_run_id,
                    OLD.session_id, OLD.bindings_sealed_at, OLD.status, OLD.model_output,
                    OLD.failure_code, OLD.generation_terminal_at, OLD.created_at
                ) THEN
                    RAISE EXCEPTION 'reviewable draft facts are immutable';
                END IF;
                IF NEW.review_decision IS NULL THEN RAISE EXCEPTION 'reviewable draft update must be a terminal review'; END IF;
                RETURN NEW;
            END IF;
            IF ROW(
                NEW.tenant_id, NEW.project_id, NEW.governance_run_id, NEW.governance_report_id,
                NEW.report_sha256, NEW.initiated_by, NEW.idempotency_key,
                NEW.model_identity, NEW.config_fingerprint, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.tenant_id, OLD.project_id, OLD.governance_run_id, OLD.governance_report_id,
                OLD.report_sha256, OLD.initiated_by, OLD.idempotency_key,
                OLD.model_identity, OLD.config_fingerprint, OLD.created_at
            ) THEN
                RAISE EXCEPTION 'ai_governance_draft input pins are immutable';
            END IF;
            IF OLD.bindings_sealed_at IS NULL THEN
                IF NEW.bindings_sealed_at IS NULL OR NEW.status <> 'GENERATING' OR NEW.agent_compose_run_id IS NOT NULL OR NEW.session_id IS NOT NULL THEN
                    RAISE EXCEPTION 'ai_governance_draft bindings must be sealed first';
                END IF;
            ELSIF NEW.bindings_sealed_at IS DISTINCT FROM OLD.bindings_sealed_at THEN
                RAISE EXCEPTION 'ai_governance_draft binding seal is immutable';
            END IF;
            IF OLD.session_id IS NOT NULL AND NEW.session_id IS DISTINCT FROM OLD.session_id THEN RAISE EXCEPTION 'ai_governance_draft session cannot be replaced'; END IF;
            IF OLD.agent_compose_run_id IS NOT NULL AND NEW.agent_compose_run_id IS DISTINCT FROM OLD.agent_compose_run_id THEN RAISE EXCEPTION 'ai_governance_draft agent-compose run cannot be replaced'; END IF;
            IF NEW.status = 'REVIEWABLE' AND NEW.review_decision IS NOT NULL THEN RAISE EXCEPTION 'generation and review require a separate transition'; END IF;
            IF NEW.status = 'REVIEWABLE' AND OLD.session_id IS NULL THEN RAISE EXCEPTION 'ai_governance_draft session must be bound before output'; END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_ai_governance_draft_finding_bindings() RETURNS trigger LANGUAGE plpgsql AS $$
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
                  AND plan_entry #>> '{evidence_reference,governance_run_id}' =
                      NEW.governance_run_id::text
                  AND (
                      (plan_entry #>> '{evidence_reference,fact_type}' = 'SOURCE_SNAPSHOT'
                       AND selected_evidence.source_snapshot_id::text =
                           plan_entry #>> '{evidence_reference,fact_id}') OR
                      (plan_entry #>> '{evidence_reference,fact_type}' = 'OBSERVATION'
                       AND selected_evidence.observation_id::text =
                           plan_entry #>> '{evidence_reference,fact_id}') OR
                      (plan_entry #>> '{evidence_reference,fact_type}' = 'FINDING_OCCURRENCE'
                       AND selected_evidence.finding_occurrence_id::text =
                           plan_entry #>> '{evidence_reference,fact_id}') OR
                      (plan_entry #>> '{evidence_reference,fact_type}' = 'FINDING_TRANSITION'
                       AND selected_evidence.finding_transition_id::text =
                           plan_entry #>> '{evidence_reference,fact_id}')
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
    op.execute(
        """
        CREATE FUNCTION require_ai_governance_draft_bindings() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE selected_finding_count integer; draft_bindings_sealed_at timestamptz;
        BEGIN
            SELECT bindings_sealed_at INTO draft_bindings_sealed_at FROM ai_governance_drafts WHERE id = NEW.id;
            IF draft_bindings_sealed_at IS NULL THEN RAISE EXCEPTION 'ai_governance_draft bindings must be sealed'; END IF;
            SELECT count(DISTINCT finding_id) INTO selected_finding_count FROM ai_governance_draft_finding_bindings WHERE draft_id = NEW.id;
            IF selected_finding_count < 1 OR selected_finding_count > 8 THEN RAISE EXCEPTION 'ai_governance_draft requires 1 to 8 finding bindings'; END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_project_ai_governance_draft_archival() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.archived_at IS NULL AND NEW.archived_at IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM ai_governance_drafts WHERE project_id = NEW.id
                      AND tenant_id = NEW.tenant_id AND status = 'GENERATING'
                ) THEN
                RAISE EXCEPTION 'projects with an active ai governance draft cannot be archived';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for name, event, table, function in (
        ("ai_governance_drafts_protect_facts", "INSERT OR UPDATE OR DELETE", "ai_governance_drafts", "protect_ai_governance_draft_facts"),
        ("ai_governance_draft_finding_bindings_protect", "INSERT OR UPDATE OR DELETE", "ai_governance_draft_finding_bindings", "protect_ai_governance_draft_finding_bindings"),
        ("projects_guard_active_ai_governance_draft", "UPDATE OF archived_at", "projects", "guard_project_ai_governance_draft_archival"),
        ("governance_runs_guard_independent_session", "INSERT", "governance_runs", "guard_independent_agent_compose_session"),
        ("ai_governance_drafts_guard_independent_session", "INSERT OR UPDATE OF session_id", "ai_governance_drafts", "guard_independent_agent_compose_session"),
    ):
        op.execute(f"CREATE TRIGGER {name} BEFORE {event} ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()")
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER ai_governance_drafts_require_findings
        AFTER INSERT OR UPDATE ON ai_governance_drafts DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION require_ai_governance_draft_bindings()
        """
    )


def upgrade() -> None:
    op.create_table(
        "ai_governance_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("governance_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("governance_report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_sha256", sa.String(length=64), nullable=False),
        sa.Column("initiated_by", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("model_identity", sa.String(length=255), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("agent_compose_run_id", sa.String(length=64), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("bindings_sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("model_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("review_decision", sa.String(length=20), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("operator_edited_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generation_terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *(sa.CheckConstraint(expression, name=name) for name, expression in _DRAFT_CHECKS.items()),
        sa.ForeignKeyConstraint(
            ("governance_report_id", "governance_run_id", "project_id", "tenant_id"),
            ("governance_reports.id", "governance_reports.governance_run_id", "governance_reports.project_id", "governance_reports.tenant_id"),
            name="fk_ai_governance_drafts_report_scope", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ("project_id", "tenant_id"), ("projects.id", "projects.tenant_id"),
            name="fk_ai_governance_drafts_project_scope", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "governance_run_id", "project_id", "tenant_id", name="uq_ai_governance_drafts_scope"),
        sa.UniqueConstraint("tenant_id", "project_id", "idempotency_key", name="uq_ai_governance_drafts_idempotency"),
        sa.UniqueConstraint("agent_compose_run_id", name="uq_ai_governance_drafts_agent_compose_run"),
        sa.UniqueConstraint("session_id", name="uq_ai_governance_drafts_session"),
    )
    for column in (
        "tenant_id",
        "project_id",
        "governance_run_id",
        "governance_report_id",
        "config_fingerprint",
        "status",
        "review_decision",
    ):
        op.create_index(f"ix_ai_governance_drafts_{column}", "ai_governance_drafts", [column])
    op.create_index(
        "uq_ai_governance_drafts_one_active_per_report",
        "ai_governance_drafts",
        ["tenant_id", "project_id", "governance_report_id"],
        unique=True,
        postgresql_where=sa.text("status = 'GENERATING'"),
    )

    op.create_table(
        "ai_governance_draft_finding_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("governance_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ("draft_id", "governance_run_id", "project_id", "tenant_id"),
            ("ai_governance_drafts.id", "ai_governance_drafts.governance_run_id", "ai_governance_drafts.project_id", "ai_governance_drafts.tenant_id"),
            name="fk_ai_governance_draft_finding_bindings_draft_scope", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ("finding_id", "project_id", "tenant_id"),
            ("findings.id", "findings.project_id", "findings.tenant_id"),
            name="fk_ai_governance_draft_finding_bindings_finding_scope", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ("evidence_id", "governance_run_id", "project_id", "tenant_id"),
            ("evidence.id", "evidence.governance_run_id", "evidence.project_id", "evidence.tenant_id"),
            name="fk_ai_governance_draft_finding_bindings_evidence_scope", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", "finding_id", name="uq_ai_governance_draft_finding_bindings_finding"),
        sa.UniqueConstraint("draft_id", "evidence_id", name="uq_ai_governance_draft_finding_bindings_evidence"),
    )
    for column in (
        "tenant_id",
        "project_id",
        "governance_run_id",
        "draft_id",
        "finding_id",
        "evidence_id",
    ):
        op.create_index(f"ix_ai_governance_draft_finding_bindings_{column}", "ai_governance_draft_finding_bindings", [column])

    _install_draft_protection()


def downgrade() -> None:
    op.execute("DROP TRIGGER projects_guard_active_ai_governance_draft ON projects")
    op.execute("DROP FUNCTION guard_project_ai_governance_draft_archival()")
    for table in ("governance_runs", "ai_governance_drafts"):
        op.execute(f"DROP TRIGGER {table}_guard_independent_session ON {table}")
    op.execute("DROP FUNCTION guard_independent_agent_compose_session()")
    op.execute("DROP TRIGGER ai_governance_drafts_require_findings ON ai_governance_drafts")
    op.execute("DROP FUNCTION require_ai_governance_draft_bindings()")
    op.execute("DROP TRIGGER ai_governance_draft_finding_bindings_protect ON ai_governance_draft_finding_bindings")
    op.execute("DROP FUNCTION protect_ai_governance_draft_finding_bindings()")
    op.execute("DROP TRIGGER ai_governance_drafts_protect_facts ON ai_governance_drafts")
    op.execute("DROP FUNCTION protect_ai_governance_draft_facts()")
    op.drop_table("ai_governance_draft_finding_bindings")
    op.drop_table("ai_governance_drafts")
