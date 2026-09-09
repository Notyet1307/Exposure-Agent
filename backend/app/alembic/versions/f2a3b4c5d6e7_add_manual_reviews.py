"""Preserve fixed-scope manual review versions.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""

import sqlalchemy as sa
from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manual_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=True),
        sa.Column(
            "author_id",
            sa.Uuid(),
            sa.ForeignKey("user.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("author_name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conclusion", sa.String(4000), nullable=False),
        sa.Column("pending_verification", sa.String(4000), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("baseline_classification", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["projects.id", "projects.tenant_id"],
            name="fk_manual_reviews_project_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "id",
            "resource_id",
            "run_id",
            "project_id",
            "tenant_id",
            name="uq_manual_reviews_scope",
        ),
        sa.UniqueConstraint(
            "project_id",
            "resource_id",
            "run_id",
            "finding_id",
            "version",
            name="uq_manual_reviews_scope_version",
            postgresql_nulls_not_distinct=True,
        ),
        sa.UniqueConstraint("supersedes_id", name="uq_manual_reviews_successor"),
        sa.CheckConstraint(
            "(version = 1 AND supersedes_id IS NULL) OR (version > 1 AND supersedes_id IS NOT NULL)",
            name="ck_manual_reviews_version",
        ),
        sa.CheckConstraint(
            "btrim(conclusion) <> '' AND btrim(pending_verification) <> ''",
            name="ck_manual_reviews_text",
        ),
        sa.CheckConstraint(
            "baseline_classification IN ('matched', 'customer_upload_only', 'cloudatlas_only', 'neither_source_observed')",
            name="ck_manual_reviews_baseline",
        ),
    )
    for column, table, name in (
        ("run_id", "governance_runs", "run"),
        ("resource_id", "resources", "resource"),
        ("finding_id", "findings", "finding"),
    ):
        op.create_foreign_key(
            f"fk_manual_reviews_{name}_scope",
            "manual_reviews",
            table,
            [column, "project_id", "tenant_id"],
            ["id", "project_id", "tenant_id"],
            ondelete="RESTRICT",
        )
    op.create_foreign_key(
        "fk_manual_reviews_predecessor_scope",
        "manual_reviews",
        "manual_reviews",
        ["supersedes_id", "resource_id", "run_id", "project_id", "tenant_id"],
        ["id", "resource_id", "run_id", "project_id", "tenant_id"],
        ondelete="RESTRICT",
    )
    for column in ("tenant_id", "project_id"):
        op.create_index(f"ix_manual_reviews_{column}", "manual_reviews", [column])
    op.execute("""
        CREATE FUNCTION protect_manual_review() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE previous manual_reviews%ROWTYPE;
                customer_present boolean;
                cloud_present boolean;
                expected_classification text;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Manual review history is append-only';
            END IF;
            PERFORM 1 FROM projects WHERE id = NEW.project_id AND tenant_id = NEW.tenant_id FOR UPDATE;
            NEW.created_at := clock_timestamp();
            IF NOT EXISTS (
                SELECT 1 FROM governance_runs r JOIN governance_reports p
                ON p.governance_run_id = r.id AND p.project_id = r.project_id AND p.tenant_id = r.tenant_id
                WHERE r.id = NEW.run_id AND r.project_id = NEW.project_id AND r.tenant_id = NEW.tenant_id
                AND r.status IN ('COMPLETED', 'COMPLETED_WITH_WARNINGS')
                AND r.completed_at < NEW.created_at
            ) THEN
                RAISE EXCEPTION 'Manual review requires a published base Run';
            END IF;
            SELECT EXISTS (
                SELECT 1 FROM observation_resource_links l JOIN observations o ON o.id = l.observation_id
                WHERE l.resource_id = NEW.resource_id AND l.governance_run_id = NEW.run_id
                AND l.project_id = NEW.project_id AND l.tenant_id = NEW.tenant_id
                AND o.source_type = 'CUSTOMER_UPLOAD'
            ), EXISTS (
                SELECT 1 FROM observation_resource_links l JOIN observations o ON o.id = l.observation_id
                WHERE l.resource_id = NEW.resource_id AND l.governance_run_id = NEW.run_id
                AND l.project_id = NEW.project_id AND l.tenant_id = NEW.tenant_id
                AND o.source_type = 'CLOUDATLAS'
            ) INTO customer_present, cloud_present;
            IF NOT customer_present AND NOT cloud_present AND NOT EXISTS (
                SELECT 1 FROM netflow_ip_activities a WHERE a.resource_id = NEW.resource_id
                AND a.governance_run_id = NEW.run_id AND a.project_id = NEW.project_id AND a.tenant_id = NEW.tenant_id
            ) THEN
                RAISE EXCEPTION 'Manual review resource must occur in its base Run';
            END IF;
            expected_classification := CASE
                WHEN customer_present AND cloud_present THEN 'matched'
                WHEN customer_present THEN 'customer_upload_only'
                WHEN cloud_present THEN 'cloudatlas_only'
                ELSE 'neither_source_observed' END;
            IF NEW.baseline_classification <> expected_classification THEN
                RAISE EXCEPTION 'Manual review baseline must match its immutable base Run';
            END IF;
            IF NEW.finding_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM findings f WHERE f.id = NEW.finding_id AND f.resource_id = NEW.resource_id
                AND f.project_id = NEW.project_id AND f.tenant_id = NEW.tenant_id
                AND (EXISTS (SELECT 1 FROM finding_occurrences o WHERE o.finding_id = f.id AND o.governance_run_id = NEW.run_id)
                    OR EXISTS (SELECT 1 FROM finding_transitions t WHERE t.finding_id = f.id AND t.governance_run_id = NEW.run_id))
            ) THEN
                RAISE EXCEPTION 'Manual review Finding must belong to its resource and base Run';
            END IF;
            SELECT * INTO previous FROM manual_reviews
                WHERE project_id = NEW.project_id AND tenant_id = NEW.tenant_id
                AND resource_id = NEW.resource_id AND run_id = NEW.run_id
                AND finding_id IS NOT DISTINCT FROM NEW.finding_id
                ORDER BY version DESC LIMIT 1;
            IF FOUND THEN
                IF NEW.supersedes_id IS DISTINCT FROM previous.id OR NEW.version <> previous.version + 1
                   OR NEW.baseline_classification <> previous.baseline_classification THEN
                    RAISE EXCEPTION 'Manual review correction must append to the current version';
                END IF;
            ELSIF NEW.supersedes_id IS NOT NULL OR NEW.version <> 1 THEN
                RAISE EXCEPTION 'Manual review chain must start at version one';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER manual_reviews_protect BEFORE INSERT OR UPDATE OR DELETE ON manual_reviews
        FOR EACH ROW EXECUTE FUNCTION protect_manual_review();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM manual_reviews)"))
        .scalar_one()
    ):
        raise RuntimeError("cannot downgrade while manual review history exists")
    op.execute("DROP TRIGGER manual_reviews_protect ON manual_reviews")
    op.execute("DROP FUNCTION protect_manual_review()")
    op.drop_table("manual_reviews")
