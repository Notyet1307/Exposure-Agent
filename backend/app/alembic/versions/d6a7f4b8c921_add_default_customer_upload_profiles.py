"""Add each Project's immutable default CustomerUploadProfile v1.

Revision ID: d6a7f4b8c921
Revises: b4f2a1c8d903
Create Date: 2026-07-31 00:00:00.000000

"""
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d6a7f4b8c921"
down_revision = "b4f2a1c8d903"
branch_labels = None
depends_on = None

DEFAULT_PROFILE_DEFINITION = {
    "required_headers": [
        "资产IP",
        "起始端口",
        "结束端口",
        "是否web界面",
        "web界面url",
    ],
    "warning_headers": [
        "服务类型",
        "资产负责人",
        "资产所属部门",
        "端口负责人",
        "部门",
    ],
    "optional_headers": ["序号"],
}


def upgrade() -> None:
    op.create_table(
        "customer_upload_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            "version > 0", name="ck_customer_upload_profiles_version_positive"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_customer_upload_profiles_id_project"
        ),
        sa.UniqueConstraint(
            "project_id", "version", name="uq_customer_upload_profiles_project_version"
        ),
    )
    op.create_index(
        op.f("ix_customer_upload_profiles_project_id"),
        "customer_upload_profiles",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_customer_upload_profiles_tenant_id"),
        "customer_upload_profiles",
        ["tenant_id"],
        unique=False,
    )
    op.add_column(
        "projects",
        sa.Column(
            "current_customer_upload_profile_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    definition_json = json.dumps(DEFAULT_PROFILE_DEFINITION, ensure_ascii=False)
    op.execute(
        sa.text(
            """
            INSERT INTO customer_upload_profiles
                (id, tenant_id, project_id, version, definition, created_at, updated_at)
            SELECT
                gen_random_uuid(),
                p.tenant_id,
                p.id,
                1,
                CAST(:definition AS jsonb),
                now(),
                now()
            FROM projects AS p
            WHERE NOT EXISTS (
                SELECT 1
                FROM customer_upload_profiles AS cup
                WHERE cup.project_id = p.id AND cup.version = 1
            )
            ON CONFLICT (project_id, version) DO NOTHING
            """
        ).bindparams(definition=definition_json)
    )
    op.execute(
        """
        UPDATE projects AS p
        SET current_customer_upload_profile_id = cup.id
        FROM customer_upload_profiles AS cup
        WHERE cup.project_id = p.id
          AND cup.version = 1
          AND p.current_customer_upload_profile_id IS NULL
        """
    )
    op.alter_column(
        "projects", "current_customer_upload_profile_id", nullable=False
    )
    op.create_foreign_key(
        "fk_projects_current_customer_upload_profile",
        "projects",
        "customer_upload_profiles",
        ["current_customer_upload_profile_id", "id"],
        ["id", "project_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index(
        op.f("ix_projects_current_customer_upload_profile_id"),
        "projects",
        ["current_customer_upload_profile_id"],
        unique=False,
    )

    op.execute(
        """
        CREATE FUNCTION reject_customer_upload_profile_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'customer_upload_profiles are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER customer_upload_profiles_immutable
        BEFORE UPDATE OR DELETE ON customer_upload_profiles
        FOR EACH ROW EXECUTE FUNCTION reject_customer_upload_profile_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER customer_upload_profiles_immutable ON customer_upload_profiles"
    )
    op.execute("DROP FUNCTION reject_customer_upload_profile_mutation()")
    op.drop_index(
        op.f("ix_projects_current_customer_upload_profile_id"),
        table_name="projects",
    )
    op.drop_constraint(
        "fk_projects_current_customer_upload_profile",
        "projects",
        type_="foreignkey",
    )
    op.drop_column("projects", "current_customer_upload_profile_id")
    op.drop_index(
        op.f("ix_customer_upload_profiles_tenant_id"),
        table_name="customer_upload_profiles",
    )
    op.drop_index(
        op.f("ix_customer_upload_profiles_project_id"),
        table_name="customer_upload_profiles",
    )
    op.drop_table("customer_upload_profiles")
