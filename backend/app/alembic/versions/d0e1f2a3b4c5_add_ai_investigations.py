"""Persist fixed-scope single-asset AI investigations.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_investigations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=True),
        sa.Column(
            "initiated_by",
            sa.Uuid(),
            sa.ForeignKey("user.id", ondelete="RESTRICT"),
            nullable=False,
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
        sa.Column("output", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("max_tool_calls", sa.Integer(), nullable=False),
        sa.Column("max_material_bytes", sa.Integer(), nullable=False),
        sa.Column("max_output_bytes", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("successful_tool_calls", sa.Integer(), nullable=False),
        sa.Column("material_bytes_read", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["projects.id", "projects.tenant_id"],
            name="fk_ai_investigations_project_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "tenant_id"],
            [
                "governance_runs.id",
                "governance_runs.project_id",
                "governance_runs.tenant_id",
            ],
            name="fk_ai_investigations_run_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id", "project_id", "tenant_id"],
            ["resources.id", "resources.project_id", "resources.tenant_id"],
            name="fk_ai_investigations_resource_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id", "project_id", "tenant_id"],
            ["findings.id", "findings.project_id", "findings.tenant_id"],
            name="fk_ai_investigations_finding_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "idempotency_key",
            name="uq_ai_investigations_idempotency",
        ),
        sa.UniqueConstraint(
            "agent_compose_run_id", name="uq_ai_investigations_compose_run"
        ),
        sa.UniqueConstraint("session_id", name="uq_ai_investigations_session"),
        sa.CheckConstraint(
            "(status = 'GENERATING' AND completed_at IS NULL AND output IS NULL) OR "
            "(status = 'FAILED' AND completed_at IS NOT NULL AND failure_code IS NOT NULL AND output IS NULL) OR "
            "(status = 'COMPLETED' AND completed_at IS NOT NULL AND failure_code IS NULL AND output IS NOT NULL AND successful_tool_calls > 0)",
            name="ck_ai_investigations_terminal",
        ),
        sa.CheckConstraint(
            "max_tool_calls > 0 AND max_material_bytes > 0 AND max_output_bytes > 0 AND timeout_seconds > 0 "
            "AND successful_tool_calls >= 0 AND successful_tool_calls <= max_tool_calls "
            "AND material_bytes_read >= 0 AND material_bytes_read <= max_material_bytes",
            name="ck_ai_investigations_budgets",
        ),
    )
    for column in ("tenant_id", "project_id", "resource_id", "run_id", "status"):
        op.create_index(f"ix_ai_investigations_{column}", "ai_investigations", [column])
    op.execute("""
        CREATE FUNCTION protect_ai_investigation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'AI investigation history cannot be deleted';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'GENERATING' OR NEW.execution_started_at IS NOT NULL
                   OR NEW.session_id IS NOT NULL OR NEW.successful_tool_calls <> 0
                   OR NEW.material_bytes_read <> 0 THEN
                    RAISE EXCEPTION 'AI investigation must begin unexecuted';
                END IF;
                IF NOT EXISTS (SELECT 1 FROM governance_runs r JOIN governance_reports p
                    ON p.governance_run_id = r.id AND p.project_id = r.project_id AND p.tenant_id = r.tenant_id
                    WHERE r.id = NEW.run_id AND r.project_id = NEW.project_id AND r.tenant_id = NEW.tenant_id
                    AND r.status IN ('COMPLETED', 'COMPLETED_WITH_WARNINGS')) THEN
                    RAISE EXCEPTION 'AI investigation requires a published Run';
                END IF;
                IF NEW.finding_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM findings f WHERE f.id = NEW.finding_id AND f.resource_id = NEW.resource_id
                    AND f.project_id = NEW.project_id AND f.tenant_id = NEW.tenant_id
                    AND (EXISTS (SELECT 1 FROM finding_occurrences o WHERE o.finding_id = f.id AND o.governance_run_id = NEW.run_id)
                         OR EXISTS (SELECT 1 FROM finding_transitions t WHERE t.finding_id = f.id AND t.governance_run_id = NEW.run_id))
                ) THEN
                    RAISE EXCEPTION 'AI investigation Finding must belong to its resource and published Run';
                END IF;
            ELSE
                IF OLD.status <> 'GENERATING' AND NEW IS DISTINCT FROM OLD THEN
                    RAISE EXCEPTION 'AI investigation terminal result is immutable';
                END IF;
                IF (to_jsonb(NEW) - ARRAY['session_id','execution_started_at','status','failure_code','output','successful_tool_calls','material_bytes_read','completed_at'])
                   IS DISTINCT FROM
                   (to_jsonb(OLD) - ARRAY['session_id','execution_started_at','status','failure_code','output','successful_tool_calls','material_bytes_read','completed_at']) THEN
                    RAISE EXCEPTION 'AI investigation scope, identity, material and limits are immutable';
                END IF;
                IF (OLD.session_id IS NOT NULL AND NEW.session_id IS DISTINCT FROM OLD.session_id)
                   OR (OLD.execution_started_at IS NOT NULL AND NEW.execution_started_at IS DISTINCT FROM OLD.execution_started_at) THEN
                    RAISE EXCEPTION 'AI investigation execution cannot be restarted or rebound';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER ai_investigations_protect
        BEFORE INSERT OR UPDATE OR DELETE ON ai_investigations
        FOR EACH ROW EXECUTE FUNCTION protect_ai_investigation();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM ai_investigations)"))
        .scalar_one()
    ):
        raise RuntimeError("cannot downgrade while AI investigation history exists")
    op.execute("DROP TRIGGER ai_investigations_protect ON ai_investigations")
    op.execute("DROP FUNCTION protect_ai_investigation()")
    op.drop_table("ai_investigations")
