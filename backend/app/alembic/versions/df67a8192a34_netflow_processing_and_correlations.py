"""Add immutable NetFlow processing receipts and fixed source correlations.

Revision ID: df67a8192a34
Revises: ce56f7081923
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "df67a8192a34"
down_revision = "ce56f7081923"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "netflow_context_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("network_namespace", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("raw_sha256", sa.String(64), nullable=False),
        sa.Column("normalized_sha256", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("operation_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_id", "project_id", "tenant_id"],
            ["netflow_datasets.id", "netflow_datasets.project_id", "netflow_datasets.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "dataset_id", "project_id", "tenant_id", name="uq_nf_context_scope"),
        sa.ForeignKeyConstraint(
            ["parent_id", "dataset_id", "project_id", "tenant_id"],
            ["netflow_context_revisions.id", "netflow_context_revisions.dataset_id", "netflow_context_revisions.project_id", "netflow_context_revisions.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("dataset_id", "revision", name="uq_nf_context_revision"),
        sa.UniqueConstraint("project_id", "dataset_id", "created_by", "operation_key", name="uq_nf_context_operation"),
        sa.UniqueConstraint("parent_id", name="uq_nf_context_successor"),
        sa.CheckConstraint("revision > 0 AND state IN ('CONFIRMED','UNKNOWN','CONFLICT','REVOKED')", name="ck_nf_context_state"),
        sa.CheckConstraint("network_namespace ~ '^[a-z][a-z0-9_-]{0,63}$'", name="ck_nf_context_namespace"),
        sa.CheckConstraint("raw_sha256 ~ '^[0-9a-f]{64}$' AND normalized_sha256 ~ '^[0-9a-f]{64}$' AND request_sha256 ~ '^[0-9a-f]{64}$'", name="ck_nf_context_hashes"),
    )
    for field in ("project_id", "dataset_id"):
        op.create_index("ix_netflow_context_revisions_" + field, "netflow_context_revisions", [field])
    op.create_index("uq_nf_context_root", "netflow_context_revisions", ["dataset_id"], unique=True, postgresql_where=sa.text("parent_id IS NULL"))

    op.create_table(
        "netflow_analyses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("context_revision_id", sa.Uuid(), nullable=False),
        sa.Column("network_namespace", sa.String(64), nullable=False),
        sa.Column("processing_identity_sha256", sa.String(64), nullable=False),
        sa.Column("identity", postgresql.JSONB(), nullable=False),
        sa.Column("request", postgresql.JSONB(), nullable=False),
        sa.Column("quality", postgresql.JSONB(), nullable=False),
        sa.Column("test_fixture", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("retry_of_analysis_id", sa.Uuid()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("agent_run_id", sa.String(64), nullable=False),
        sa.Column("agent_project_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(255)),
        sa.Column("runner_build_version", sa.String(255), nullable=False),
        sa.Column("result", postgresql.JSONB(none_as_null=True)),
        sa.Column("initial_feedback_revision_id", sa.Uuid()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("terminal_confirmed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["context_revision_id", "dataset_id", "project_id", "tenant_id"],
            ["netflow_context_revisions.id", "netflow_context_revisions.dataset_id", "netflow_context_revisions.project_id", "netflow_context_revisions.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "project_id", "tenant_id", name="uq_nf_analysis_scope"),
        sa.UniqueConstraint("id", "processing_identity_sha256", "project_id", "tenant_id", name="uq_nf_analysis_identity_scope"),
        sa.ForeignKeyConstraint(
            ["retry_of_analysis_id", "processing_identity_sha256", "project_id", "tenant_id"],
            ["netflow_analyses.id", "netflow_analyses.processing_identity_sha256", "netflow_analyses.project_id", "netflow_analyses.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("retry_of_analysis_id", name="uq_nf_analysis_retry"),
        sa.UniqueConstraint("agent_run_id"),
        sa.CheckConstraint("status IN ('PENDING','RUNNING','SUCCEEDED','SUCCEEDED_WITH_WARNINGS','FAILED','UNKNOWN')", name="ck_nf_analysis_status"),
        sa.CheckConstraint("processing_identity_sha256 ~ '^[0-9a-f]{64}$' AND agent_run_id ~ '^[0-9a-f]{64}$' AND agent_project_id ~ '^[0-9a-f]{64}$'", name="ck_nf_analysis_identity"),
        sa.CheckConstraint("network_namespace ~ '^[a-z][a-z0-9_-]{0,63}$'", name="ck_nf_analysis_namespace"),
        sa.CheckConstraint("(status IN ('SUCCEEDED','SUCCEEDED_WITH_WARNINGS') AND result IS NOT NULL AND completed_at IS NOT NULL AND initial_feedback_revision_id IS NOT NULL AND session_id IS NOT NULL) OR (status NOT IN ('SUCCEEDED','SUCCEEDED_WITH_WARNINGS') AND result IS NULL AND initial_feedback_revision_id IS NULL)", name="ck_nf_analysis_publication"),
    )
    for field in ("project_id", "dataset_id"):
        op.create_index("ix_netflow_analyses_" + field, "netflow_analyses", [field])
    op.create_index("uq_nf_analysis_identity_root", "netflow_analyses", ["project_id", "processing_identity_sha256"], unique=True, postgresql_where=sa.text("retry_of_analysis_id IS NULL"))

    op.create_table(
        "netflow_feedback_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid()),
        sa.Column("system_generated", sa.Boolean(), nullable=False),
        sa.Column("human_note", sa.String(2048)),
        sa.Column("artifact_manifest", postgresql.JSONB(), nullable=False),
        sa.Column("provider_claim", postgresql.JSONB(none_as_null=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id", "project_id", "tenant_id"],
            ["netflow_analyses.id", "netflow_analyses.project_id", "netflow_analyses.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "analysis_id", "project_id", "tenant_id", name="uq_nf_feedback_scope"),
        sa.ForeignKeyConstraint(
            ["parent_id", "analysis_id", "project_id", "tenant_id"],
            ["netflow_feedback_revisions.id", "netflow_feedback_revisions.analysis_id", "netflow_feedback_revisions.project_id", "netflow_feedback_revisions.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("analysis_id", "revision", name="uq_nf_feedback_revision"),
        sa.UniqueConstraint("parent_id", name="uq_nf_feedback_successor"),
        sa.CheckConstraint("revision > 0 AND (parent_id IS NOT NULL OR revision = 1)", name="ck_nf_feedback_revision"),
        sa.CheckConstraint("NOT system_generated OR (created_by IS NULL AND parent_id IS NULL)", name="ck_nf_feedback_system_author"),
    )
    for field in ("project_id", "analysis_id"):
        op.create_index("ix_netflow_feedback_revisions_" + field, "netflow_feedback_revisions", [field])
    op.create_index("uq_nf_feedback_root", "netflow_feedback_revisions", ["analysis_id"], unique=True, postgresql_where=sa.text("parent_id IS NULL"))
    op.create_foreign_key(
        "fk_nf_analysis_initial_feedback", "netflow_analyses", "netflow_feedback_revisions",
        ["initial_feedback_revision_id", "id", "project_id", "tenant_id"],
        ["id", "analysis_id", "project_id", "tenant_id"],
        ondelete="RESTRICT", deferrable=True, initially="DEFERRED",
    )

    op.create_table(
        "source_correlation_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("root_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("network_namespace", sa.String(64), nullable=False),
        sa.Column("scope_state", sa.String(16), nullable=False),
        sa.Column("selection", postgresql.JSONB(), nullable=False),
        sa.Column("pins", postgresql.JSONB(), nullable=False),
        sa.Column("evidence", sa.String(2048)),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "tenant_id"], ["projects.id", "projects.tenant_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "root_id", "project_id", "tenant_id", name="uq_nf_correlation_scope"),
        sa.ForeignKeyConstraint(
            ["parent_id", "root_id", "project_id", "tenant_id"],
            ["source_correlation_revisions.id", "source_correlation_revisions.root_id", "source_correlation_revisions.project_id", "source_correlation_revisions.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("root_id", "revision", name="uq_nf_correlation_revision"),
        sa.UniqueConstraint("parent_id", name="uq_nf_correlation_successor"),
        sa.CheckConstraint("revision > 0 AND ((parent_id IS NULL AND root_id = id AND revision = 1) OR parent_id IS NOT NULL)", name="ck_nf_correlation_root"),
        sa.CheckConstraint("scope_state IN ('UNKNOWN','CONFIRMED','REVOKED')", name="ck_nf_correlation_state"),
        sa.CheckConstraint("network_namespace ~ '^[a-z][a-z0-9_-]{0,63}$'", name="ck_nf_correlation_namespace"),
    )
    for field in ("project_id", "root_id"):
        op.create_index("ix_source_correlation_revisions_" + field, "source_correlation_revisions", [field])
    op.create_index("uq_nf_correlation_root", "source_correlation_revisions", ["root_id"], unique=True, postgresql_where=sa.text("parent_id IS NULL"))

    # Reuse the existing append-only audit stream, not another operation table.
    op.execute("""
        CREATE UNIQUE INDEX uq_netflow_operation_key ON audit_events
          (tenant_id, project_id, actor_subject,
           (after_data->>'operation'), (after_data->>'operation_key'))
          WHERE action = 'netflow.operation'
    """)
    op.execute("""
        CREATE FUNCTION guard_netflow_revision_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'netflow revisions are immutable';
        END;
        $$
    """)
    for table in ("netflow_context_revisions", "netflow_feedback_revisions", "source_correlation_revisions"):
        op.execute(f"CREATE TRIGGER netflow_revision_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION guard_netflow_revision_mutation()")

    op.execute("""
        CREATE FUNCTION guard_netflow_context_chain() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE parent netflow_context_revisions%ROWTYPE;
        BEGIN
          IF NEW.parent_id IS NULL THEN
            IF NEW.revision <> 1 THEN
              RAISE EXCEPTION 'netflow context root must be revision one';
            END IF;
          ELSE
            SELECT * INTO parent FROM netflow_context_revisions
              WHERE id = NEW.parent_id;
            IF NOT FOUND OR
               ROW(NEW.dataset_id, NEW.project_id, NEW.tenant_id, NEW.revision,
                   NEW.raw_sha256, NEW.normalized_sha256)
               IS DISTINCT FROM
               ROW(parent.dataset_id, parent.project_id, parent.tenant_id,
                   parent.revision + 1, parent.raw_sha256, parent.normalized_sha256) THEN
              RAISE EXCEPTION 'invalid netflow context revision chain';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute("CREATE TRIGGER netflow_context_chain BEFORE INSERT ON netflow_context_revisions FOR EACH ROW EXECUTE FUNCTION guard_netflow_context_chain()")
    op.execute("""
        CREATE FUNCTION guard_netflow_feedback_chain() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE parent netflow_feedback_revisions%ROWTYPE;
        BEGIN
          IF NEW.parent_id IS NULL THEN
            IF NEW.revision <> 1 OR NOT NEW.system_generated OR
               NEW.created_by IS NOT NULL OR NEW.human_note IS NOT NULL OR
               NEW.provider_claim IS NOT NULL THEN
              RAISE EXCEPTION 'netflow initial feedback must be system blank';
            END IF;
          ELSE
            SELECT * INTO parent FROM netflow_feedback_revisions
              WHERE id = NEW.parent_id;
            IF NOT FOUND OR NEW.system_generated OR NEW.created_by IS NULL OR
               ROW(NEW.analysis_id, NEW.project_id, NEW.tenant_id, NEW.revision)
               IS DISTINCT FROM
               ROW(parent.analysis_id, parent.project_id, parent.tenant_id,
                   parent.revision + 1) THEN
              RAISE EXCEPTION 'invalid netflow feedback revision chain';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute("CREATE TRIGGER netflow_feedback_chain BEFORE INSERT ON netflow_feedback_revisions FOR EACH ROW EXECUTE FUNCTION guard_netflow_feedback_chain()")
    op.execute("""
        CREATE FUNCTION guard_netflow_correlation_chain() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE parent source_correlation_revisions%ROWTYPE;
        BEGIN
          IF NEW.parent_id IS NOT NULL THEN
            SELECT * INTO parent FROM source_correlation_revisions
              WHERE id = NEW.parent_id;
            IF NOT FOUND OR
               ROW(NEW.root_id, NEW.project_id, NEW.tenant_id, NEW.revision,
                   NEW.network_namespace, NEW.selection, NEW.pins)
               IS DISTINCT FROM
               ROW(parent.root_id, parent.project_id, parent.tenant_id,
                   parent.revision + 1, parent.network_namespace,
                   parent.selection, parent.pins) THEN
              RAISE EXCEPTION 'invalid or changed netflow correlation inputs';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute("CREATE TRIGGER netflow_correlation_chain BEFORE INSERT ON source_correlation_revisions FOR EACH ROW EXECUTE FUNCTION guard_netflow_correlation_chain()")

    op.execute("""
        CREATE FUNCTION guard_netflow_analysis() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE parent netflow_analyses%ROWTYPE;
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'netflow analyses cannot be deleted';
          END IF;
          IF TG_OP = 'INSERT' THEN
            IF NEW.status <> 'PENDING' OR NEW.session_id IS NOT NULL OR
               NEW.started_at IS NOT NULL OR NEW.completed_at IS NOT NULL OR
               NEW.terminal_confirmed OR NEW.error_code IS NOT NULL THEN
              RAISE EXCEPTION 'netflow analysis must begin with a pending reservation';
            END IF;
            IF NOT EXISTS (
              SELECT 1 FROM netflow_context_revisions c
              WHERE c.id = NEW.context_revision_id
                AND c.dataset_id = NEW.dataset_id AND c.project_id = NEW.project_id
                AND c.tenant_id = NEW.tenant_id
                AND c.network_namespace = NEW.network_namespace
            ) THEN
              RAISE EXCEPTION 'netflow analysis context scope differs';
            END IF;
            IF NEW.retry_of_analysis_id IS NOT NULL THEN
              SELECT * INTO parent FROM netflow_analyses
                WHERE id = NEW.retry_of_analysis_id FOR UPDATE;
              IF NOT FOUND OR parent.status <> 'FAILED' OR
                 NOT parent.terminal_confirmed OR
                 ROW(NEW.processing_identity_sha256, NEW.identity, NEW.dataset_id,
                     NEW.context_revision_id, NEW.project_id, NEW.tenant_id,
                     NEW.network_namespace, NEW.quality, NEW.test_fixture,
                     NEW.runner_build_version)
                 IS DISTINCT FROM
                 ROW(parent.processing_identity_sha256, parent.identity, parent.dataset_id,
                     parent.context_revision_id, parent.project_id, parent.tenant_id,
                     parent.network_namespace, parent.quality, parent.test_fixture,
                     parent.runner_build_version) THEN
                RAISE EXCEPTION 'netflow retry requires the same terminal failed identity';
              END IF;
            END IF;
          ELSE
            IF ROW(NEW.id, NEW.tenant_id, NEW.project_id, NEW.dataset_id,
                   NEW.context_revision_id, NEW.network_namespace,
                   NEW.processing_identity_sha256, NEW.identity, NEW.request,
                   NEW.quality, NEW.test_fixture, NEW.created_by,
                   NEW.retry_of_analysis_id, NEW.agent_run_id, NEW.agent_project_id,
                   NEW.runner_build_version, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.tenant_id, OLD.project_id, OLD.dataset_id,
                   OLD.context_revision_id, OLD.network_namespace,
                   OLD.processing_identity_sha256, OLD.identity, OLD.request,
                   OLD.quality, OLD.test_fixture, OLD.created_by,
                   OLD.retry_of_analysis_id, OLD.agent_run_id, OLD.agent_project_id,
                   OLD.runner_build_version, OLD.created_at) THEN
              RAISE EXCEPTION 'netflow analysis identity is immutable';
            END IF;
            IF (OLD.session_id IS NOT NULL AND NEW.session_id IS DISTINCT FROM OLD.session_id)
               OR (OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at)
               OR (OLD.terminal_confirmed AND NOT NEW.terminal_confirmed) THEN
              RAISE EXCEPTION 'netflow analysis execution binding is immutable';
            END IF;
            IF OLD.status IN ('SUCCEEDED','SUCCEEDED_WITH_WARNINGS','FAILED') AND
               (to_jsonb(NEW) - 'terminal_confirmed') IS DISTINCT FROM
               (to_jsonb(OLD) - 'terminal_confirmed') THEN
              RAISE EXCEPTION 'netflow terminal analysis is immutable';
            END IF;
            IF OLD.status <> 'PENDING' AND NEW.status = 'PENDING' THEN
              RAISE EXCEPTION 'netflow analysis cannot return to pending';
            END IF;
          END IF;
          IF (NEW.started_at IS NOT NULL AND NEW.session_id IS NULL) OR
             (NEW.status = 'RUNNING' AND (NEW.started_at IS NULL OR NEW.session_id IS NULL)) OR
             (NEW.status IN ('PENDING','RUNNING','UNKNOWN') AND NEW.completed_at IS NOT NULL) OR
             (NEW.status = 'FAILED' AND NEW.completed_at IS NULL) OR
             (NEW.status IN ('SUCCEEDED','SUCCEEDED_WITH_WARNINGS') AND
               (NEW.started_at IS NULL OR NEW.error_code IS NOT NULL OR
                jsonb_typeof(NEW.result) IS DISTINCT FROM 'object')) THEN
            RAISE EXCEPTION 'invalid netflow analysis execution state';
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute("CREATE TRIGGER netflow_analysis_guard BEFORE INSERT OR UPDATE OR DELETE ON netflow_analyses FOR EACH ROW EXECUTE FUNCTION guard_netflow_analysis()")

    # Both triggers inspect committed-candidate rows, not the intermediate NEW
    # snapshot: publication may flush feedback while its Analysis is RUNNING.
    op.execute("""
        CREATE FUNCTION guard_netflow_analysis_publication() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE analysis netflow_analyses%ROWTYPE;
        BEGIN
          SELECT * INTO analysis FROM netflow_analyses WHERE id = NEW.id;
          IF analysis.status IN ('SUCCEEDED','SUCCEEDED_WITH_WARNINGS') AND NOT EXISTS (
            SELECT 1 FROM netflow_feedback_revisions f
            WHERE f.id = analysis.initial_feedback_revision_id
              AND f.analysis_id = analysis.id AND f.project_id = analysis.project_id
              AND f.tenant_id = analysis.tenant_id AND f.parent_id IS NULL
              AND f.revision = 1 AND f.system_generated AND f.created_by IS NULL
          ) THEN
            RAISE EXCEPTION 'netflow publication requires its initial system feedback';
          END IF;
          RETURN NULL;
        END;
        $$
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER netflow_analysis_publication
        AFTER INSERT OR UPDATE ON netflow_analyses DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION guard_netflow_analysis_publication()
    """)
    op.execute("""
        CREATE FUNCTION guard_netflow_feedback_publication() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM netflow_analyses a
            WHERE a.id = NEW.analysis_id AND a.project_id = NEW.project_id
              AND a.tenant_id = NEW.tenant_id
              AND a.status IN ('SUCCEEDED','SUCCEEDED_WITH_WARNINGS')
              AND (NEW.parent_id IS NOT NULL OR a.initial_feedback_revision_id = NEW.id)
          ) THEN
            RAISE EXCEPTION 'netflow feedback requires a published analysis';
          END IF;
          RETURN NULL;
        END;
        $$
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER netflow_feedback_publication
        AFTER INSERT ON netflow_feedback_revisions DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION guard_netflow_feedback_publication()
    """)


def downgrade() -> None:
    # Lock before the emptiness check so a concurrent insert cannot be dropped.
    op.execute("""
        LOCK TABLE netflow_context_revisions, netflow_analyses,
          netflow_feedback_revisions, source_correlation_revisions
          IN ACCESS EXCLUSIVE MODE
    """)
    if op.get_bind().scalar(sa.text("""
        SELECT EXISTS (SELECT 1 FROM netflow_context_revisions)
          OR EXISTS (SELECT 1 FROM netflow_analyses)
          OR EXISTS (SELECT 1 FROM netflow_feedback_revisions)
          OR EXISTS (SELECT 1 FROM source_correlation_revisions)
    """)):
        raise RuntimeError("Cannot remove NetFlow processing while immutable facts exist")
    op.drop_index("uq_netflow_operation_key", table_name="audit_events")
    op.drop_constraint("fk_nf_analysis_initial_feedback", "netflow_analyses", type_="foreignkey")
    op.drop_table("source_correlation_revisions")
    op.drop_table("netflow_feedback_revisions")
    op.drop_table("netflow_analyses")
    op.drop_table("netflow_context_revisions")
    op.execute("DROP FUNCTION guard_netflow_feedback_publication()")
    op.execute("DROP FUNCTION guard_netflow_analysis_publication()")
    op.execute("DROP FUNCTION guard_netflow_analysis()")
    op.execute("DROP FUNCTION guard_netflow_correlation_chain()")
    op.execute("DROP FUNCTION guard_netflow_feedback_chain()")
    op.execute("DROP FUNCTION guard_netflow_context_chain()")
    op.execute("DROP FUNCTION guard_netflow_revision_mutation()")
