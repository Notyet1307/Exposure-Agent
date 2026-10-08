"""Fixed V2 report subjects and append-only human revisions; retain old Run guards.

Revision ID: ai2980000001
Revises: cp2920000001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ai2980000001"
down_revision = "cp2920000001"
branch_labels = None
depends_on = None

GUARD = """
CREATE OR REPLACE FUNCTION protect_analysis_report() RETURNS trigger LANGUAGE plpgsql AS $$
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
__PUBLICATION_CHECK__
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
"""

RUN_PUBLICATION = """
                IF NOT EXISTS (SELECT 1 FROM governance_runs r JOIN governance_reports p
                    ON p.governance_run_id = r.id AND p.project_id = r.project_id AND p.tenant_id = r.tenant_id
                    WHERE r.id = NEW.run_id AND r.project_id = NEW.project_id AND r.tenant_id = NEW.tenant_id
                    AND r.status IN ('COMPLETED', 'COMPLETED_WITH_WARNINGS')) THEN
                    RAISE EXCEPTION 'Analysis report requires a published Run';
                END IF;

"""

V2_PUBLICATION = """
                IF NEW.subject_kind = 'governance_run' THEN
                IF NOT EXISTS (SELECT 1 FROM governance_runs r JOIN governance_reports p
                    ON p.governance_run_id = r.id AND p.project_id = r.project_id AND p.tenant_id = r.tenant_id
                    WHERE r.id = NEW.run_id AND r.project_id = NEW.project_id AND r.tenant_id = NEW.tenant_id
                    AND r.status IN ('COMPLETED', 'COMPLETED_WITH_WARNINGS')) THEN
                    RAISE EXCEPTION 'Analysis report requires a published Run';
                END IF;
                ELSE
                    IF NOT EXISTS (SELECT 1 FROM core_comparison_results r
                        WHERE r.id = NEW.core_result_id AND r.project_id = NEW.project_id
                        AND r.tenant_id = NEW.tenant_id AND r.status = 'PUBLISHED' AND r.published_at IS NOT NULL) THEN
                        RAISE EXCEPTION 'V2 analysis report requires a published core result';
                    END IF;
                    IF NEW.supplement_binding_id IS NOT NULL AND NOT EXISTS (
                        SELECT 1 FROM core_comparison_supplements b WHERE b.id = NEW.supplement_binding_id
                        AND b.result_id = NEW.core_result_id AND b.project_id = NEW.project_id AND b.tenant_id = NEW.tenant_id
                        AND b.analysis_id IS NOT NULL AND b.valid_until > statement_timestamp()) THEN
                        RAISE EXCEPTION 'V2 analysis report requires the exact active supplement';
                    END IF;
                    IF NEW.material->'subject'->>'subject_kind' IS DISTINCT FROM 'core_comparison_v2'
                        OR NEW.material->'subject'->>'result_id' IS DISTINCT FROM NEW.core_result_id::text
                        OR NEW.material->'subject'->>'project_id' IS DISTINCT FROM NEW.project_id::text
                        OR NOT (NEW.material->'subject' ? 'supplement_binding_id')
                        OR NEW.material->'subject'->>'supplement_binding_id' IS DISTINCT FROM NEW.supplement_binding_id::text
                        OR NEW.material->'subject'->>'audience' IS DISTINCT FROM NEW.audience
                        OR NEW.material->'subject'->>'language' IS DISTINCT FROM NEW.language
                        OR NEW.material->'subject'->>'address_key' IS DISTINCT FROM NEW.address_key THEN
                        RAISE EXCEPTION 'V2 analysis report material must match its fixed subject';
                    END IF;
                END IF;
"""


def upgrade() -> None:
    op.alter_column("analysis_reports", "run_id", nullable=True)
    op.add_column(
        "analysis_reports",
        sa.Column(
            "subject_kind",
            sa.String(32),
            server_default="governance_run",
            nullable=False,
        ),
    )
    for name in ("core_result_id", "supplement_binding_id"):
        op.add_column("analysis_reports", sa.Column(name, sa.Uuid(), nullable=True))
    for name, size in (
        ("audience", 16),
        ("language", 8),
        ("address_key", 69),
        ("request_sha256", 64),
    ):
        op.add_column(
            "analysis_reports", sa.Column(name, sa.String(size), nullable=True)
        )
    op.create_index(
        "ix_analysis_reports_core_result_id", "analysis_reports", ["core_result_id"]
    )
    op.create_foreign_key(
        "fk_analysis_reports_core_scope",
        "analysis_reports",
        "core_comparison_results",
        ["core_result_id", "project_id", "tenant_id"],
        ["id", "project_id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_analysis_reports_supplement_scope",
        "analysis_reports",
        "core_comparison_supplements",
        ["supplement_binding_id", "core_result_id", "project_id", "tenant_id"],
        ["id", "result_id", "project_id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_analysis_report_subject",
        "analysis_reports",
        "(subject_kind = 'governance_run' AND run_id IS NOT NULL AND core_result_id IS NULL AND supplement_binding_id IS NULL AND audience IS NULL AND language IS NULL AND address_key IS NULL AND request_sha256 IS NULL) OR "
        "(subject_kind = 'core_comparison_v2' AND run_id IS NULL AND core_result_id IS NOT NULL AND audience IS NOT NULL AND language IS NOT NULL AND request_sha256 IS NOT NULL AND audience IN ('management','operations') AND language IN ('zh','en') AND request_sha256 ~ '^[a-f0-9]{64}$' AND (address_key IS NULL OR address_key ~ '^addr:[a-f0-9]{64}$'))",
    )
    op.execute(GUARD.replace("__PUBLICATION_CHECK__", V2_PUBLICATION))
    op.create_table(
        "analysis_report_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "report_id",
            sa.Uuid(),
            sa.ForeignKey("analysis_reports.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("text", postgresql.JSONB(), nullable=False),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("user.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "report_id", "revision", name="uq_analysis_report_revision"
        ),
        sa.CheckConstraint(
            "revision > 0 AND status IN ('DRAFT','CONFIRMED')",
            name="ck_analysis_report_revision",
        ),
    )
    op.create_index(
        "ix_analysis_report_revisions_report_id",
        "analysis_report_revisions",
        ["report_id"],
    )
    op.execute("""
        CREATE FUNCTION protect_analysis_report_revision() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Report revisions are immutable'; END IF;
            IF NOT EXISTS (SELECT 1 FROM analysis_reports r WHERE r.id = NEW.report_id
                AND r.subject_kind = 'core_comparison_v2' AND r.revision = NEW.revision
                AND r.status = NEW.status AND r.text = NEW.text
                AND NEW.actor_id = coalesce(r.confirmed_by_id,r.edited_by_id,r.created_by_id)) THEN
                RAISE EXCEPTION 'Report revision must preserve the current fixed version';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER analysis_report_revisions_protect BEFORE INSERT OR UPDATE OR DELETE ON analysis_report_revisions
        FOR EACH ROW EXECUTE FUNCTION protect_analysis_report_revision();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM analysis_reports WHERE subject_kind = 'core_comparison_v2')"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("cannot downgrade while V2 analysis report history exists")
    op.execute(
        "DROP TRIGGER analysis_report_revisions_protect ON analysis_report_revisions"
    )
    op.execute("DROP FUNCTION protect_analysis_report_revision()")
    op.drop_table("analysis_report_revisions")
    op.execute(GUARD.replace("__PUBLICATION_CHECK__", RUN_PUBLICATION))
    op.drop_constraint("ck_analysis_report_subject", "analysis_reports", type_="check")
    op.drop_constraint(
        "fk_analysis_reports_supplement_scope", "analysis_reports", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_analysis_reports_core_scope", "analysis_reports", type_="foreignkey"
    )
    op.drop_index("ix_analysis_reports_core_result_id", table_name="analysis_reports")
    for name in (
        "subject_kind",
        "core_result_id",
        "supplement_binding_id",
        "audience",
        "language",
        "address_key",
        "request_sha256",
    ):
        op.drop_column("analysis_reports", name)
    op.alter_column("analysis_reports", "run_id", nullable=False)
