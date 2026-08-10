"""Add the scoped GovernanceReport and report Artifact contract.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-08-14 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing source Artifacts remain unscoped. Report Artifacts are created with
    # both columns populated so their owning Run can be enforced by composite FKs.
    op.add_column(
        "artifacts",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "artifacts",
        sa.Column(
            "governance_run_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_check_constraint(
        "ck_artifacts_governance_run_project",
        "artifacts",
        "governance_run_id IS NULL OR project_id IS NOT NULL",
    )
    op.create_foreign_key(
        "fk_artifacts_project_scope",
        "artifacts",
        "projects",
        ["project_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_artifacts_governance_run_scope",
        "artifacts",
        "governance_runs",
        ["governance_run_id", "project_id", "tenant_id"],
        ["id", "project_id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_artifacts_report_scope_hash",
        "artifacts",
        ["id", "governance_run_id", "project_id", "tenant_id", "sha256"],
    )
    op.create_index("ix_artifacts_project_id", "artifacts", ["project_id"])
    op.create_index(
        "ix_artifacts_governance_run_id", "artifacts", ["governance_run_id"]
    )

    op.create_unique_constraint(
        "uq_governance_runs_report_contract_scope",
        "governance_runs",
        ["id", "project_id", "tenant_id", "report_contract_version"],
    )

    op.create_table(
        "governance_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "governance_run_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("report_contract_version", sa.String(length=100), nullable=False),
        sa.Column("generation_mode", sa.String(length=30), nullable=False),
        sa.Column(
            "canonical_content",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("html_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("html_sha256", sa.String(length=64), nullable=False),
        sa.Column("csv_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("csv_sha256", sa.String(length=64), nullable=False),
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
        sa.CheckConstraint(
            "btrim(report_contract_version) <> ''",
            name="ck_governance_reports_contract_version",
        ),
        sa.CheckConstraint(
            "generation_mode = 'DETERMINISTIC_TEMPLATE'",
            name="ck_governance_reports_generation_mode",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(canonical_content) = 'object' "
            "AND canonical_content <> '{}'::jsonb",
            name="ck_governance_reports_canonical_content",
        ),
        sa.CheckConstraint(
            "html_sha256 ~ '^[0-9a-f]{64}$' "
            "AND csv_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_governance_reports_artifact_hashes",
        ),
        sa.CheckConstraint(
            "html_artifact_id <> csv_artifact_id",
            name="ck_governance_reports_distinct_artifacts",
        ),
        sa.ForeignKeyConstraint(
            [
                "governance_run_id",
                "project_id",
                "tenant_id",
                "report_contract_version",
            ],
            [
                "governance_runs.id",
                "governance_runs.project_id",
                "governance_runs.tenant_id",
                "governance_runs.report_contract_version",
            ],
            name="fk_governance_reports_run_contract_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "html_artifact_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
                "html_sha256",
            ],
            [
                "artifacts.id",
                "artifacts.governance_run_id",
                "artifacts.project_id",
                "artifacts.tenant_id",
                "artifacts.sha256",
            ],
            name="fk_governance_reports_html_artifact_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "csv_artifact_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
                "csv_sha256",
            ],
            [
                "artifacts.id",
                "artifacts.governance_run_id",
                "artifacts.project_id",
                "artifacts.tenant_id",
                "artifacts.sha256",
            ],
            name="fk_governance_reports_csv_artifact_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            name="uq_governance_reports_scope",
        ),
        sa.UniqueConstraint(
            "governance_run_id", name="uq_governance_reports_governance_run"
        ),
        sa.UniqueConstraint(
            "html_artifact_id", name="uq_governance_reports_html_artifact_id"
        ),
        sa.UniqueConstraint(
            "csv_artifact_id", name="uq_governance_reports_csv_artifact_id"
        ),
    )
    op.create_index(
        "ix_governance_reports_tenant_id", "governance_reports", ["tenant_id"]
    )
    op.create_index(
        "ix_governance_reports_project_id", "governance_reports", ["project_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_governance_reports_project_id", table_name="governance_reports")
    op.drop_index("ix_governance_reports_tenant_id", table_name="governance_reports")
    op.drop_table("governance_reports")
    op.drop_constraint(
        "uq_governance_runs_report_contract_scope",
        "governance_runs",
        type_="unique",
    )
    op.drop_index("ix_artifacts_governance_run_id", table_name="artifacts")
    op.drop_index("ix_artifacts_project_id", table_name="artifacts")
    op.drop_constraint(
        "uq_artifacts_report_scope_hash", "artifacts", type_="unique"
    )
    op.drop_constraint(
        "fk_artifacts_governance_run_scope", "artifacts", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_artifacts_project_scope", "artifacts", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_artifacts_governance_run_project", "artifacts", type_="check"
    )
    op.drop_column("artifacts", "governance_run_id")
    op.drop_column("artifacts", "project_id")
