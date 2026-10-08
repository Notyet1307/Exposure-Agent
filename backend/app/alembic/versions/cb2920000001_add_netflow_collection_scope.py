"""Add explicit confirmed collection scope to immutable NetFlow contexts.

Revision ID: cb2920000001
Revises: f1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "cb2920000001"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "netflow_context_revisions",
        sa.Column("collection_scope", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "netflow_context_revisions",
        sa.Column("collection_scope_evidence", sa.String(length=2048), nullable=True),
    )
    op.create_check_constraint(
        "ck_nf_context_collection_scope",
        "netflow_context_revisions",
        "(collection_scope IS NULL AND collection_scope_evidence IS NULL) OR "
        "(collection_scope IS NOT NULL AND collection_scope_evidence IS NOT NULL "
        "AND btrim(collection_scope) <> '' AND btrim(collection_scope_evidence) <> '')",
    )
    op.create_index(
        "ix_nf_context_collection_scope",
        "netflow_context_revisions",
        ["project_id", "tenant_id", "collection_scope"],
    )


def downgrade() -> None:
    present = op.get_bind().execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM netflow_context_revisions WHERE collection_scope IS NOT NULL)")
    ).scalar_one()
    if present:
        raise RuntimeError("cannot downgrade while collection scopes are recorded")
    op.drop_index("ix_nf_context_collection_scope", table_name="netflow_context_revisions")
    op.drop_constraint("ck_nf_context_collection_scope", "netflow_context_revisions", type_="check")
    op.drop_column("netflow_context_revisions", "collection_scope_evidence")
    op.drop_column("netflow_context_revisions", "collection_scope")
