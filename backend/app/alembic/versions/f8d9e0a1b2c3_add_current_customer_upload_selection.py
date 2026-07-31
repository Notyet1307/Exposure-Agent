"""Add each Project's explicit current CustomerUpload selection.

Revision ID: f8d9e0a1b2c3
Revises: e7c8d9a0b1f2
Create Date: 2026-08-08 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f8d9e0a1b2c3"
down_revision = "e7c8d9a0b1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_customer_uploads_id_project",
        "customer_uploads",
        ["id", "project_id"],
    )
    op.add_column(
        "projects",
        sa.Column(
            "current_customer_upload_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_projects_current_customer_upload",
        "projects",
        "customer_uploads",
        ["current_customer_upload_id", "id"],
        ["id", "project_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_projects_current_customer_upload_id"),
        "projects",
        ["current_customer_upload_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_projects_current_customer_upload_id"), table_name="projects"
    )
    op.drop_constraint(
        "fk_projects_current_customer_upload", "projects", type_="foreignkey"
    )
    op.drop_column("projects", "current_customer_upload_id")
    op.drop_constraint(
        "uq_customer_uploads_id_project", "customer_uploads", type_="unique"
    )
