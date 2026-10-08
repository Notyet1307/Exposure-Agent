"""Add immutable receipts for full customer-upload replacement.

Revision ID: f1a2b3c4d5e6
Revises: ca2810000001
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


revision = "f1a2b3c4d5e6"
down_revision = "ca2810000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_upload_replacements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_upload_id", sa.Uuid(), nullable=False),
        sa.Column("expected_upload_id", sa.Uuid(), nullable=True),
        sa.Column("expected_revision_id", sa.Uuid(), nullable=True),
        sa.Column("expected_profile_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "operation_key",
            sqlmodel.sql.sqltypes.AutoString(length=128),
            nullable=False,
        ),
        sa.Column(
            "request_sha256",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
        sa.Column("sealed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_customer_upload_replacement_request_hash",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_upload_id", "project_id", "tenant_id"],
            [
                "customer_uploads.id",
                "customer_uploads.project_id",
                "customer_uploads.tenant_id",
            ],
            name="fk_customer_upload_replacement_candidate_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["projects.id", "projects.tenant_id"],
            name="fk_customer_upload_replacement_project_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "created_by",
            "operation_key",
            name="uq_customer_upload_replacement_operation",
        ),
    )
    op.create_index(
        op.f("ix_customer_upload_replacements_project_id"),
        "customer_upload_replacements",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_customer_upload_replacements_tenant_id"),
        "customer_upload_replacements",
        ["tenant_id"],
        unique=False,
    )
    op.execute("""
        CREATE FUNCTION guard_customer_upload_replacement() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' AND NOT OLD.sealed AND NEW.sealed
             AND (to_jsonb(OLD) - 'sealed') = (to_jsonb(NEW) - 'sealed') THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'customer upload replacement is immutable';
        END $$;
        CREATE TRIGGER customer_upload_replacements_immutable
        BEFORE UPDATE OR DELETE ON customer_upload_replacements
        FOR EACH ROW EXECUTE FUNCTION guard_customer_upload_replacement();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM customer_upload_replacements)"))
        .scalar()
    ):
        raise RuntimeError(
            "Cannot remove immutable customer replacement receipts; use a forward migration"
        )
    op.execute(
        "DROP TRIGGER customer_upload_replacements_immutable ON customer_upload_replacements"
    )
    op.execute("DROP FUNCTION guard_customer_upload_replacement()")
    op.drop_index(
        op.f("ix_customer_upload_replacements_tenant_id"),
        table_name="customer_upload_replacements",
    )
    op.drop_index(
        op.f("ix_customer_upload_replacements_project_id"),
        table_name="customer_upload_replacements",
    )
    op.drop_table("customer_upload_replacements")
