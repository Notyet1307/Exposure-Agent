"""Independent AI report captures and human-confirmed versions.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_by_id",
            sa.Uuid(),
            sa.ForeignKey("user.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "edited_by_id",
            sa.Uuid(),
            sa.ForeignKey("user.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "confirmed_by_id",
            sa.Uuid(),
            sa.ForeignKey("user.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("config_fingerprint", sa.String(64), nullable=False),
        sa.Column("material_sha256", sa.String(64), nullable=False),
        sa.Column("material", postgresql.JSONB(), nullable=False),
        sa.Column("sources", postgresql.JSONB(), nullable=False),
        sa.Column("agent_compose_run_id", sa.String(64), nullable=False),
        sa.Column("agent_compose_project_id", sa.String(64), nullable=False),
        sa.Column("agent_compose_agent_name", sa.String(255), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("execution_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column(
            "original_output", postgresql.JSONB(none_as_null=True), nullable=True
        ),
        sa.Column("text", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("max_tool_calls", sa.Integer(), nullable=False),
        sa.Column("max_material_bytes", sa.Integer(), nullable=False),
        sa.Column("max_output_bytes", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("successful_tool_calls", sa.Integer(), nullable=False),
        sa.Column("material_bytes_read", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["projects.id", "projects.tenant_id"],
            name="fk_analysis_reports_project_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "tenant_id"],
            [
                "governance_runs.id",
                "governance_runs.project_id",
                "governance_runs.tenant_id",
            ],
            name="fk_analysis_reports_run_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "idempotency_key",
            name="uq_analysis_reports_idempotency",
        ),
        sa.UniqueConstraint(
            "agent_compose_run_id", name="uq_analysis_reports_compose_run"
        ),
        sa.UniqueConstraint("session_id", name="uq_analysis_reports_session"),
        sa.CheckConstraint(
            "(status = 'GENERATING' AND completed_at IS NULL AND original_output IS NULL AND text IS NULL) OR "
            "(status = 'FAILED' AND completed_at IS NOT NULL AND failure_code IS NOT NULL AND original_output IS NULL AND text IS NULL) OR "
            "(status IN ('DRAFT', 'CONFIRMED') AND completed_at IS NOT NULL AND failure_code IS NULL "
            "AND original_output IS NOT NULL AND text IS NOT NULL AND successful_tool_calls > 0)",
            name="ck_analysis_reports_terminal",
        ),
        sa.CheckConstraint(
            "(status = 'CONFIRMED' AND confirmed_at IS NOT NULL AND confirmed_by_id IS NOT NULL) OR "
            "(status <> 'CONFIRMED' AND confirmed_at IS NULL AND confirmed_by_id IS NULL)",
            name="ck_analysis_reports_confirmation",
        ),
        sa.CheckConstraint(
            "revision > 0 AND max_tool_calls > 0 AND max_material_bytes > 0 AND max_output_bytes > 0 AND timeout_seconds > 0 "
            "AND successful_tool_calls >= 0 AND successful_tool_calls <= max_tool_calls "
            "AND material_bytes_read >= 0 AND material_bytes_read <= max_material_bytes",
            name="ck_analysis_reports_budgets",
        ),
    )
    for column in ("tenant_id", "project_id", "run_id", "status"):
        op.create_index(f"ix_analysis_reports_{column}", "analysis_reports", [column])
    op.execute("""
        CREATE FUNCTION protect_analysis_report() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Analysis report history cannot be deleted';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'GENERATING' OR NEW.revision <> 1 OR NEW.session_id IS NOT NULL
                   OR NEW.execution_started_at IS NOT NULL OR NEW.successful_tool_calls <> 0
                   OR NEW.material_bytes_read <> 0 OR NEW.edited_at IS NOT NULL OR NEW.edited_by_id IS NOT NULL THEN
                    RAISE EXCEPTION 'Analysis report must begin unexecuted';
                END IF;
                IF NOT EXISTS (SELECT 1 FROM governance_runs r JOIN governance_reports p
                    ON p.governance_run_id = r.id AND p.project_id = r.project_id AND p.tenant_id = r.tenant_id
                    WHERE r.id = NEW.run_id AND r.project_id = NEW.project_id AND r.tenant_id = NEW.tenant_id
                    AND r.status IN ('COMPLETED', 'COMPLETED_WITH_WARNINGS')) THEN
                    RAISE EXCEPTION 'Analysis report requires a published Run';
                END IF;
            ELSIF OLD.status IN ('CONFIRMED', 'FAILED') THEN
                IF NEW IS DISTINCT FROM OLD THEN
                    RAISE EXCEPTION 'Confirmed and failed analysis reports are immutable';
                END IF;
            ELSIF OLD.status = 'GENERATING' THEN
                IF NEW.status NOT IN ('GENERATING', 'DRAFT', 'FAILED') OR
                   (to_jsonb(NEW) - ARRAY['session_id','execution_started_at','status','failure_code','original_output','text','successful_tool_calls','material_bytes_read','completed_at'])
                   IS DISTINCT FROM
                   (to_jsonb(OLD) - ARRAY['session_id','execution_started_at','status','failure_code','original_output','text','successful_tool_calls','material_bytes_read','completed_at']) THEN
                    RAISE EXCEPTION 'Analysis report scope, identity, material and limits are immutable';
                END IF;
                IF (OLD.session_id IS NOT NULL AND NEW.session_id IS DISTINCT FROM OLD.session_id)
                   OR (OLD.execution_started_at IS NOT NULL AND NEW.execution_started_at IS DISTINCT FROM OLD.execution_started_at) THEN
                    RAISE EXCEPTION 'Analysis report execution cannot restart or rebind';
                END IF;
                IF NEW.status = 'DRAFT' AND (NEW.text IS DISTINCT FROM NEW.original_output->'text'
                   OR NEW.execution_started_at IS NULL OR NEW.session_id IS NULL) THEN
                    RAISE EXCEPTION 'Initial draft must preserve the executed AI original';
                END IF;
            ELSIF OLD.status = 'DRAFT' THEN
                IF NEW.revision <> OLD.revision + 1 THEN
                    RAISE EXCEPTION 'Analysis report revision must advance exactly once';
                END IF;
                IF NEW.status = 'CONFIRMED' THEN
                    IF (to_jsonb(NEW) - ARRAY['status','revision','confirmed_at','confirmed_by_id']) IS DISTINCT FROM
                       (to_jsonb(OLD) - ARRAY['status','revision','confirmed_at','confirmed_by_id']) THEN
                        RAISE EXCEPTION 'Confirmation is separate from editing';
                    END IF;
                ELSIF NEW.status = 'DRAFT' THEN
                    IF NEW.edited_at IS NULL OR NEW.edited_by_id IS NULL OR
                       (to_jsonb(NEW) - ARRAY['text','revision','edited_at','edited_by_id']) IS DISTINCT FROM
                       (to_jsonb(OLD) - ARRAY['text','revision','edited_at','edited_by_id']) THEN
                        RAISE EXCEPTION 'Only human text and edit identity can change';
                    END IF;
                ELSE
                    RAISE EXCEPTION 'Analysis report draft cannot return to generation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER analysis_reports_protect BEFORE INSERT OR UPDATE OR DELETE ON analysis_reports
        FOR EACH ROW EXECUTE FUNCTION protect_analysis_report();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM analysis_reports)"))
        .scalar_one()
    ):
        raise RuntimeError("cannot downgrade while analysis report history exists")
    op.execute("DROP TRIGGER analysis_reports_protect ON analysis_reports")
    op.execute("DROP FUNCTION protect_analysis_report()")
    op.drop_table("analysis_reports")
