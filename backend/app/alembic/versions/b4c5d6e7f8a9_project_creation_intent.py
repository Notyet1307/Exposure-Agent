"""Persist Project creation intents for scoped idempotent replay."""
from alembic import op
import sqlalchemy as sa

revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("creation_actor", "creation_key", "creation_name"):
        op.add_column("projects", sa.Column(name, sa.String(255), nullable=True))
    op.create_unique_constraint("uq_projects_creation_key", "projects", ["tenant_id", "creation_actor", "creation_key"])
    op.create_check_constraint("ck_projects_creation_intent", "projects", "(creation_actor IS NULL AND creation_key IS NULL AND creation_name IS NULL) OR (creation_actor IS NOT NULL AND creation_key IS NOT NULL AND creation_name IS NOT NULL)")


def downgrade():
    op.drop_constraint("ck_projects_creation_intent", "projects", type_="check")
    op.drop_constraint("uq_projects_creation_key", "projects", type_="unique")
    for name in ("creation_name", "creation_key", "creation_actor"):
        op.drop_column("projects", name)
