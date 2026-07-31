"""Add immutable Artifact and CustomerUpload acceptance records.

Revision ID: e7c8d9a0b1f2
Revises: d6a7f4b8c921
Create Date: 2026-07-31 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e7c8d9a0b1f2"
down_revision = "d6a7f4b8c921"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
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
        sa.CheckConstraint("byte_size > 0", name="ck_artifacts_byte_size_positive"),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name="ck_artifacts_sha256_format"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        op.f("ix_artifacts_sha256"), "artifacts", ["sha256"], unique=False
    )
    op.create_index(
        op.f("ix_artifacts_tenant_id"), "artifacts", ["tenant_id"], unique=False
    )

    op.create_unique_constraint(
        "uq_customer_upload_profiles_id_project_version",
        "customer_upload_profiles",
        ["id", "project_id", "version"],
    )

    op.create_table(
        "customer_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_filename", sa.String(length=128), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
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
            "profile_version > 0",
            name="ck_customer_uploads_profile_version_positive",
        ),
        sa.CheckConstraint(
            "raw_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_customer_uploads_raw_sha256_format",
        ),
        sa.CheckConstraint(
            "record_count > 0", name="ck_customer_uploads_record_count_positive"
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["profile_id", "project_id", "profile_version"],
            [
                "customer_upload_profiles.id",
                "customer_upload_profiles.project_id",
                "customer_upload_profiles.version",
            ],
            name="fk_customer_uploads_profile_project_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id"),
        sa.UniqueConstraint(
            "project_id",
            "raw_sha256",
            "profile_id",
            "profile_version",
            name="uq_customer_uploads_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_customer_uploads_profile_id"),
        "customer_uploads",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_customer_uploads_project_id"),
        "customer_uploads",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_customer_uploads_raw_sha256"),
        "customer_uploads",
        ["raw_sha256"],
        unique=False,
    )
    op.create_index(
        op.f("ix_customer_uploads_tenant_id"),
        "customer_uploads",
        ["tenant_id"],
        unique=False,
    )

    op.execute(
        """
        CREATE FUNCTION reject_customer_upload_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION '% records are immutable', TG_TABLE_NAME;
        END;
        $$
        """
    )
    for table_name in ("artifacts", "customer_uploads"):
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_immutable
            BEFORE UPDATE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_customer_upload_update()
            """
        )


def downgrade() -> None:
    for table_name in ("customer_uploads", "artifacts"):
        op.execute(f"DROP TRIGGER {table_name}_immutable ON {table_name}")
    op.execute("DROP FUNCTION reject_customer_upload_update()")
    op.drop_index(
        op.f("ix_customer_uploads_tenant_id"), table_name="customer_uploads"
    )
    op.drop_index(
        op.f("ix_customer_uploads_raw_sha256"), table_name="customer_uploads"
    )
    op.drop_index(
        op.f("ix_customer_uploads_project_id"), table_name="customer_uploads"
    )
    op.drop_index(
        op.f("ix_customer_uploads_profile_id"), table_name="customer_uploads"
    )
    op.drop_table("customer_uploads")
    op.drop_constraint(
        "uq_customer_upload_profiles_id_project_version",
        "customer_upload_profiles",
        type_="unique",
    )
    op.drop_index(op.f("ix_artifacts_tenant_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_sha256"), table_name="artifacts")
    op.drop_table("artifacts")
