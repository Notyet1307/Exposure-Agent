"""Freeze agent-compose namespace with each reserved AI draft Run.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-28 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None

_NAMESPACE_CONSTRAINT = "ck_ai_governance_drafts_agent_compose_namespace"
_PROJECT_ID_CONSTRAINT = "ck_ai_governance_drafts_agent_compose_project_id"


def upgrade() -> None:
    legacy_reserved_run = op.get_bind().execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM ai_governance_drafts "
            "WHERE agent_compose_run_id IS NOT NULL AND session_id IS NULL)"
        )
    ).scalar_one()
    if legacy_reserved_run:
        raise RuntimeError(
            "cannot upgrade while an AI draft has a reserved Run without a frozen namespace"
        )
    op.add_column(
        "ai_governance_drafts",
        sa.Column("agent_compose_project_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ai_governance_drafts",
        sa.Column("agent_compose_agent_name", sa.String(length=255), nullable=True),
    )
    op.create_check_constraint(
        _NAMESPACE_CONSTRAINT,
        "ai_governance_drafts",
        "(agent_compose_run_id IS NULL AND agent_compose_project_id IS NULL "
        "AND agent_compose_agent_name IS NULL) OR "
        "(agent_compose_run_id IS NOT NULL AND agent_compose_project_id IS NOT NULL "
        "AND btrim(agent_compose_agent_name) <> '') OR "
        "(agent_compose_run_id IS NOT NULL AND session_id IS NOT NULL "
        "AND agent_compose_project_id IS NULL AND agent_compose_agent_name IS NULL)",
    )
    op.create_check_constraint(
        _PROJECT_ID_CONSTRAINT,
        "ai_governance_drafts",
        "agent_compose_project_id IS NULL OR "
        "agent_compose_project_id ~ '^[0-9a-f]{64}$'",
    )
    op.execute(
        """
        CREATE FUNCTION protect_ai_governance_draft_agent_compose_namespace()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND (OLD.agent_compose_project_id IS NOT NULL
                    OR OLD.agent_compose_agent_name IS NOT NULL)
               AND (NEW.agent_compose_project_id IS DISTINCT FROM OLD.agent_compose_project_id
                    OR NEW.agent_compose_agent_name IS DISTINCT FROM OLD.agent_compose_agent_name)
            THEN
                RAISE EXCEPTION 'ai_governance_draft agent-compose namespace cannot be replaced';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER ai_governance_drafts_protect_agent_compose_namespace
        BEFORE UPDATE OF agent_compose_project_id, agent_compose_agent_name
        ON ai_governance_drafts
        FOR EACH ROW EXECUTE FUNCTION protect_ai_governance_draft_agent_compose_namespace()
        """
    )


def downgrade() -> None:
    namespace_present = op.get_bind().execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM ai_governance_drafts "
            "WHERE agent_compose_project_id IS NOT NULL "
            "OR agent_compose_agent_name IS NOT NULL)"
        )
    ).scalar_one()
    if namespace_present:
        raise RuntimeError(
            "cannot downgrade while an AI draft has a frozen agent-compose namespace"
        )
    op.execute(
        "DROP TRIGGER ai_governance_drafts_protect_agent_compose_namespace "
        "ON ai_governance_drafts"
    )
    op.execute("DROP FUNCTION protect_ai_governance_draft_agent_compose_namespace")
    op.drop_constraint(_PROJECT_ID_CONSTRAINT, "ai_governance_drafts", type_="check")
    op.drop_constraint(_NAMESPACE_CONSTRAINT, "ai_governance_drafts", type_="check")
    op.drop_column("ai_governance_drafts", "agent_compose_agent_name")
    op.drop_column("ai_governance_drafts", "agent_compose_project_id")
