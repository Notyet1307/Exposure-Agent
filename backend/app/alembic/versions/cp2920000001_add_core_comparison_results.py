"""Add immutable V2 core result and optional NetFlow binding identities."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "cp2920000001"
down_revision = "ca2810000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "core_comparison_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("scope_confirmation_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("selection", postgresql.JSONB, nullable=False),
        sa.Column("pins", postgresql.JSONB, nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("purpose IN ('regular','custom')", name="ck_core_result_purpose"),
        sa.CheckConstraint("status IN ('PUBLISHED','FAILED','UNKNOWN')", name="ck_core_result_status"),
        sa.CheckConstraint("(status = 'PUBLISHED' AND published_at IS NOT NULL) OR (status IN ('FAILED','UNKNOWN') AND published_at IS NULL)", name="ck_core_result_publication"),
        sa.CheckConstraint("input_sha256 ~ '^[0-9a-f]{64}$'", name="ck_core_result_input_hash"),
        sa.ForeignKeyConstraint(["project_id", "tenant_id"], ["projects.id", "projects.tenant_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["scope_confirmation_id"], ["source_correlation_revisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_core_result_scope_published", "core_comparison_results", ["project_id", "scope_key", "published_at", "id"])
    op.create_table(
        "core_comparison_supplements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("result_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("analysis_id", sa.Uuid()),
        sa.Column("qualification_confirmation_id", sa.Uuid()),
        sa.Column("qualification_evidence", sa.String(2048)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("observation_window", postgresql.JSONB, nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("operation_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["result_id"], ["core_comparison_results.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["analysis_id"], ["netflow_analyses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["qualification_confirmation_id"], ["source_correlation_revisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("result_id", "revision", name="uq_core_supplement_revision"),
        sa.UniqueConstraint("result_id", "parent_id", name="uq_core_supplement_successor"),
    )
    op.create_index("uq_core_supplement_root", "core_comparison_supplements", ["result_id"], unique=True, postgresql_where=sa.text("parent_id IS NULL"))
    op.execute("""
        CREATE FUNCTION guard_core_comparison_result() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'core comparison results are immutable';
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM source_correlation_revisions r
            WHERE r.id = NEW.scope_confirmation_id
              AND r.project_id = NEW.project_id
              AND r.tenant_id = NEW.tenant_id
              AND r.scope_state = 'CONFIRMED'
          ) THEN
            RAISE EXCEPTION 'core comparison result scope is invalid';
          END IF;
          RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER core_comparison_results_protect
        BEFORE INSERT OR UPDATE OR DELETE ON core_comparison_results
        FOR EACH ROW EXECUTE FUNCTION guard_core_comparison_result()
    """)
    op.execute("""
        CREATE FUNCTION guard_core_comparison_supplement() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE result_project uuid; result_tenant uuid;
        BEGIN
          IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'core comparison supplements are immutable';
          END IF;
          SELECT project_id, tenant_id INTO result_project, result_tenant
          FROM core_comparison_results WHERE id = NEW.result_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'core comparison supplement result is invalid';
          END IF;
          IF NEW.parent_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM core_comparison_supplements p
            WHERE p.id = NEW.parent_id AND p.result_id = NEW.result_id
          ) THEN
            RAISE EXCEPTION 'core comparison supplement parent is invalid';
          END IF;
          IF NEW.analysis_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM netflow_analyses a
            WHERE a.id = NEW.analysis_id AND a.project_id = result_project AND a.tenant_id = result_tenant
          ) THEN
            RAISE EXCEPTION 'core comparison supplement analysis scope is invalid';
          END IF;
          IF NEW.qualification_confirmation_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM source_correlation_revisions r
            WHERE r.id = NEW.qualification_confirmation_id AND r.project_id = result_project AND r.tenant_id = result_tenant
          ) THEN
            RAISE EXCEPTION 'core comparison supplement confirmation scope is invalid';
          END IF;
          RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER core_comparison_supplements_protect
        BEFORE INSERT OR UPDATE OR DELETE ON core_comparison_supplements
        FOR EACH ROW EXECUTE FUNCTION guard_core_comparison_supplement()
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM core_comparison_results)
             OR EXISTS (SELECT 1 FROM core_comparison_supplements) THEN
            RAISE EXCEPTION 'core comparison facts prevent downgrade';
          END IF;
        END $$;
    """)
    op.execute("DROP TRIGGER core_comparison_supplements_protect ON core_comparison_supplements")
    op.execute("DROP FUNCTION guard_core_comparison_supplement()")
    op.execute("DROP TRIGGER core_comparison_results_protect ON core_comparison_results")
    op.execute("DROP FUNCTION guard_core_comparison_result()")
    op.drop_index("uq_core_supplement_root", table_name="core_comparison_supplements")
    op.drop_table("core_comparison_supplements")
    op.drop_index("ix_core_result_scope_published", table_name="core_comparison_results")
    op.drop_table("core_comparison_results")
