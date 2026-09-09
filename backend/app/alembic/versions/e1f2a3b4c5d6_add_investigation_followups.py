"""Preserve scoped followups and append-only investigation reads.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_investigations",
        sa.Column("parent_investigation_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "ai_investigations", sa.Column("question", sa.String(2000), nullable=True)
    )
    op.add_column(
        "ai_investigations",
        sa.Column(
            "tool_reads",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_foreign_key(
        "fk_ai_investigations_parent",
        "ai_investigations",
        "ai_investigations",
        ["parent_investigation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_ai_investigations_question",
        "ai_investigations",
        "(parent_investigation_id IS NULL AND question IS NULL) OR (parent_investigation_id IS NOT NULL AND question IS NOT NULL AND length(btrim(question)) BETWEEN 1 AND 2000)",
    )
    op.create_check_constraint(
        "ck_ai_investigations_reads",
        "ai_investigations",
        "jsonb_typeof(tool_reads) = 'array'",
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION protect_ai_investigation() RETURNS trigger LANGUAGE plpgsql AS $$
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
                IF (to_jsonb(NEW) - ARRAY['session_id','execution_started_at','status','failure_code','output','successful_tool_calls','material_bytes_read','completed_at','tool_reads'])
                   IS DISTINCT FROM
                   (to_jsonb(OLD) - ARRAY['session_id','execution_started_at','status','failure_code','output','successful_tool_calls','material_bytes_read','completed_at','tool_reads']) THEN
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

        CREATE FUNCTION protect_ai_investigation_followups() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent ai_investigations%ROWTYPE;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.tool_reads <> '[]'::jsonb THEN
                    RAISE EXCEPTION 'Investigation reads must begin empty';
                END IF;
                IF NEW.parent_investigation_id IS NOT NULL THEN
                    SELECT * INTO parent FROM ai_investigations WHERE id = NEW.parent_investigation_id;
                    IF NOT FOUND OR parent.status <> 'COMPLETED' OR
                       ROW(parent.tenant_id,parent.project_id,parent.resource_id,parent.run_id,parent.finding_id)
                       IS DISTINCT FROM ROW(NEW.tenant_id,NEW.project_id,NEW.resource_id,NEW.run_id,NEW.finding_id) THEN
                        RAISE EXCEPTION 'Followup requires completed parent in identical scope';
                    END IF;
                END IF;
            ELSIF NEW.tool_reads IS DISTINCT FROM OLD.tool_reads THEN
                IF OLD.status <> 'GENERATING' OR NEW.status <> 'GENERATING' OR
                   jsonb_array_length(NEW.tool_reads) > NEW.max_tool_calls THEN
                    RAISE EXCEPTION 'Investigation read budget or terminal boundary violated';
                END IF;
                IF jsonb_array_length(NEW.tool_reads) = jsonb_array_length(OLD.tool_reads) + 1 THEN
                    IF NEW.tool_reads - (jsonb_array_length(NEW.tool_reads)-1) IS DISTINCT FROM OLD.tool_reads
                       OR NEW.tool_reads -> -1 ->> 'status' <> 'RUNNING' THEN
                        RAISE EXCEPTION 'Investigation reads must append a reservation';
                    END IF;
                ELSIF jsonb_array_length(NEW.tool_reads) = jsonb_array_length(OLD.tool_reads)
                      AND jsonb_array_length(OLD.tool_reads) > 0 THEN
                    IF OLD.tool_reads -> -1 ->> 'status' <> 'RUNNING'
                       OR NEW.tool_reads -> -1 ->> 'status' NOT IN ('SUCCEEDED','FAILED')
                       OR (NEW.tool_reads - (jsonb_array_length(NEW.tool_reads)-1)) IS DISTINCT FROM
                          (OLD.tool_reads - (jsonb_array_length(OLD.tool_reads)-1))
                       OR ((NEW.tool_reads -> -1) - ARRAY['completed_at','status','failure_code','items','result']) IS DISTINCT FROM
                          ((OLD.tool_reads -> -1) - ARRAY['completed_at','status','failure_code','items','result']) THEN
                        RAISE EXCEPTION 'Completed investigation reads are immutable';
                    END IF;
                ELSE
                    RAISE EXCEPTION 'Investigation reads cannot be removed or rewritten';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER ai_investigations_followups_protect
        BEFORE INSERT OR UPDATE ON ai_investigations
        FOR EACH ROW EXECUTE FUNCTION protect_ai_investigation_followups();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM ai_investigations WHERE parent_investigation_id IS NOT NULL OR tool_reads <> '[]'::jsonb)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError(
            "cannot downgrade while followup or tool-read history exists"
        )
    op.execute("DROP TRIGGER ai_investigations_followups_protect ON ai_investigations")
    op.execute("DROP FUNCTION protect_ai_investigation_followups()")
    op.execute("""
        CREATE OR REPLACE FUNCTION protect_ai_investigation() RETURNS trigger LANGUAGE plpgsql AS $$
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
    """)
    op.drop_constraint("ck_ai_investigations_reads", "ai_investigations", type_="check")
    op.drop_constraint(
        "ck_ai_investigations_question", "ai_investigations", type_="check"
    )
    op.drop_constraint(
        "fk_ai_investigations_parent", "ai_investigations", type_="foreignkey"
    )
    op.drop_column("ai_investigations", "tool_reads")
    op.drop_column("ai_investigations", "question")
    op.drop_column("ai_investigations", "parent_investigation_id")
