"""Add Project current NetFlowDataset selection.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "current_netflow_dataset_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_projects_current_netflow_dataset",
        "projects",
        "netflow_datasets",
        ["current_netflow_dataset_id", "id", "tenant_id"],
        ["id", "project_id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_projects_current_netflow_dataset_id"),
        "projects",
        ["current_netflow_dataset_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_projects_current_netflow_dataset_id"), table_name="projects"
    )
    op.drop_constraint(
        "fk_projects_current_netflow_dataset", "projects", type_="foreignkey"
    )
    op.drop_column("projects", "current_netflow_dataset_id")
