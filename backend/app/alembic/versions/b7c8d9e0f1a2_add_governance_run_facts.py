"""Add the minimal GovernanceRun, RunStep, and SourceSnapshot facts.

Revision ID: b7c8d9e0f1a2
Revises: a9b8c7d6e5f4
Create Date: 2026-08-10 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b7c8d9e0f1a2"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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
    )


def upgrade() -> None:
    op.create_unique_constraint("uq_projects_id_tenant", "projects", ["id", "tenant_id"])
    op.create_unique_constraint(
        "uq_customer_uploads_scope",
        "customer_uploads",
        ["id", "project_id", "tenant_id"],
    )
    op.create_unique_constraint(
        "uq_source_instances_scope",
        "source_instances",
        ["id", "project_id", "tenant_id"],
    )
    op.create_unique_constraint(
        "uq_artifacts_id_tenant", "artifacts", ["id", "tenant_id"]
    )

    op.create_table(
        "governance_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("customer_upload_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_upload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "customer_upload_profile_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("customer_upload_profile_version", sa.Integer(), nullable=False),
        sa.Column("source_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "cloudatlas_validated_fingerprint", sa.String(length=64), nullable=False
        ),
        sa.Column("cloudatlas_capset_id", sa.String(length=255), nullable=False),
        sa.Column("cloudatlas_method", sa.String(length=255), nullable=False),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("descriptor_sha256", sa.String(length=64), nullable=False),
        sa.Column("runner_build_version", sa.String(length=255), nullable=False),
        *_timestamps(),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'FAILED_DATA', 'FAILED_PROCESSING', "
            "'COMPLETED')",
            name="ck_governance_runs_status",
        ),
        sa.CheckConstraint(
            "customer_upload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_governance_runs_customer_sha256",
        ),
        sa.CheckConstraint(
            "cloudatlas_validated_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_governance_runs_cloudatlas_fingerprint",
        ),
        sa.CheckConstraint(
            "package_sha256 ~ '^[0-9a-f]{64}$' AND "
            "descriptor_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_governance_runs_package_fingerprints",
        ),
        sa.CheckConstraint(
            "customer_upload_profile_version > 0",
            name="ck_governance_runs_profile_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["projects.id", "projects.tenant_id"],
            name="fk_governance_runs_project_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["customer_upload_id", "project_id", "tenant_id"],
            ["customer_uploads.id", "customer_uploads.project_id", "customer_uploads.tenant_id"],
            name="fk_governance_runs_customer_upload_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_instance_id", "project_id", "tenant_id"],
            ["source_instances.id", "source_instances.project_id", "source_instances.tenant_id"],
            name="fk_governance_runs_source_instance_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "customer_upload_profile_id",
                "project_id",
                "customer_upload_profile_version",
            ],
            [
                "customer_upload_profiles.id",
                "customer_upload_profiles.project_id",
                "customer_upload_profiles.version",
            ],
            name="fk_governance_runs_profile_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "project_id", "tenant_id", name="uq_governance_runs_scope"
        ),
        sa.UniqueConstraint(
            "project_id", "trigger_id", name="uq_governance_runs_trigger"
        ),
        sa.UniqueConstraint("session_id", name="uq_governance_runs_session"),
    )
    for column in (
        "tenant_id",
        "project_id",
        "customer_upload_id",
        "customer_upload_profile_id",
        "source_instance_id",
    ):
        op.create_index(
            op.f(f"ix_governance_runs_{column}"),
            "governance_runs",
            [column],
            unique=False,
        )
    op.create_index(
        "uq_governance_runs_one_active_per_project",
        "governance_runs",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("status = 'RUNNING'"),
    )

    op.create_table(
        "run_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("governance_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_code", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("output_hash", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "step_code IN ('LOAD_CUSTOMER', 'PULL_CLOUDATLAS', 'PUBLISH')",
            name="ck_run_steps_code",
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_run_steps_status",
        ),
        sa.CheckConstraint("attempt > 0", name="ck_run_steps_attempt_positive"),
        sa.CheckConstraint(
            "input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_run_steps_input_hash",
        ),
        sa.CheckConstraint(
            "output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'",
            name="ck_run_steps_output_hash",
        ),
        sa.ForeignKeyConstraint(
            ["governance_run_id", "project_id", "tenant_id"],
            ["governance_runs.id", "governance_runs.project_id", "governance_runs.tenant_id"],
            name="fk_run_steps_governance_run_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "governance_run_id", "step_code", name="uq_run_steps_run_code"
        ),
    )
    for column in ("tenant_id", "project_id", "governance_run_id"):
        op.create_index(
            op.f(f"ix_run_steps_{column}"), "run_steps", [column], unique=False
        )

    op.create_table(
        "source_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("governance_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("customer_upload_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_instance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("method_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "source_type IN ('CUSTOMER_UPLOAD', 'CLOUDATLAS')",
            name="ck_source_snapshots_type",
        ),
        sa.CheckConstraint(
            "(source_type = 'CUSTOMER_UPLOAD' AND customer_upload_id IS NOT NULL "
            "AND source_instance_id IS NULL AND method_fingerprint IS NULL) OR "
            "(source_type = 'CLOUDATLAS' AND customer_upload_id IS NULL "
            "AND source_instance_id IS NOT NULL AND method_fingerprint IS NOT NULL)",
            name="ck_source_snapshots_source_reference",
        ),
        sa.CheckConstraint(
            "record_count >= 0", name="ck_source_snapshots_record_count"
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$' AND "
            "schema_fingerprint ~ '^[0-9a-f]{64}$' AND "
            "(method_fingerprint IS NULL OR method_fingerprint ~ '^[0-9a-f]{64}$')",
            name="ck_source_snapshots_fingerprints",
        ),
        sa.ForeignKeyConstraint(
            ["governance_run_id", "project_id", "tenant_id"],
            ["governance_runs.id", "governance_runs.project_id", "governance_runs.tenant_id"],
            name="fk_source_snapshots_governance_run_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["customer_upload_id", "project_id", "tenant_id"],
            ["customer_uploads.id", "customer_uploads.project_id", "customer_uploads.tenant_id"],
            name="fk_source_snapshots_customer_upload_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_instance_id", "project_id", "tenant_id"],
            ["source_instances.id", "source_instances.project_id", "source_instances.tenant_id"],
            name="fk_source_snapshots_source_instance_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id", "tenant_id"],
            ["artifacts.id", "artifacts.tenant_id"],
            name="fk_source_snapshots_artifact_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "governance_run_id", "source_type", name="uq_source_snapshots_run_type"
        ),
    )
    for column in (
        "tenant_id",
        "project_id",
        "governance_run_id",
        "customer_upload_id",
        "source_instance_id",
        "artifact_id",
    ):
        op.create_index(
            op.f(f"ix_source_snapshots_{column}"),
            "source_snapshots",
            [column],
            unique=False,
        )

    op.add_column(
        "projects",
        sa.Column("latest_completed_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_projects_latest_completed_run_id"),
        "projects",
        ["latest_completed_run_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_projects_latest_completed_run",
        "projects",
        "governance_runs",
        ["latest_completed_run_id", "id", "tenant_id"],
        ["id", "project_id", "tenant_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )

    op.execute(
        """
        CREATE FUNCTION reject_source_snapshot_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'source_snapshots are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER source_snapshots_immutable
        BEFORE UPDATE OR DELETE ON source_snapshots
        FOR EACH ROW EXECUTE FUNCTION reject_source_snapshot_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_governance_run_facts()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status = 'COMPLETED' THEN
                RAISE EXCEPTION 'completed governance_runs are immutable';
            END IF;
            IF ROW(
                NEW.tenant_id, NEW.project_id, NEW.trigger_id, NEW.session_id,
                NEW.requested_by, NEW.customer_upload_id,
                NEW.customer_upload_sha256, NEW.customer_upload_profile_id,
                NEW.customer_upload_profile_version, NEW.source_instance_id,
                NEW.cloudatlas_validated_fingerprint, NEW.cloudatlas_capset_id,
                NEW.cloudatlas_method, NEW.package_sha256,
                NEW.descriptor_sha256, NEW.runner_build_version, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.tenant_id, OLD.project_id, OLD.trigger_id, OLD.session_id,
                OLD.requested_by, OLD.customer_upload_id,
                OLD.customer_upload_sha256, OLD.customer_upload_profile_id,
                OLD.customer_upload_profile_version, OLD.source_instance_id,
                OLD.cloudatlas_validated_fingerprint, OLD.cloudatlas_capset_id,
                OLD.cloudatlas_method, OLD.package_sha256,
                OLD.descriptor_sha256, OLD.runner_build_version, OLD.created_at
            ) THEN
                RAISE EXCEPTION 'governance_run pinned facts are immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER governance_runs_protect_facts
        BEFORE UPDATE ON governance_runs
        FOR EACH ROW EXECUTE FUNCTION protect_governance_run_facts()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER governance_runs_protect_facts ON governance_runs")
    op.execute("DROP FUNCTION protect_governance_run_facts()")
    op.execute("DROP TRIGGER source_snapshots_immutable ON source_snapshots")
    op.execute("DROP FUNCTION reject_source_snapshot_mutation()")
    op.drop_constraint(
        "fk_projects_latest_completed_run", "projects", type_="foreignkey"
    )
    op.drop_index(
        op.f("ix_projects_latest_completed_run_id"), table_name="projects"
    )
    op.drop_column("projects", "latest_completed_run_id")
    op.drop_table("source_snapshots")
    op.drop_table("run_steps")
    op.drop_index(
        "uq_governance_runs_one_active_per_project",
        table_name="governance_runs",
        postgresql_where=sa.text("status = 'RUNNING'"),
    )
    op.drop_table("governance_runs")
    op.drop_constraint("uq_artifacts_id_tenant", "artifacts", type_="unique")
    op.drop_constraint("uq_source_instances_scope", "source_instances", type_="unique")
    op.drop_constraint("uq_customer_uploads_scope", "customer_uploads", type_="unique")
    op.drop_constraint("uq_projects_id_tenant", "projects", type_="unique")
