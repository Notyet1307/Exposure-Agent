"""Add GovernanceRun Session recovery facts.

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
Create Date: 2026-08-11 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("governance_launch_trigger_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column(
            "governance_launch_control_run_id", sa.String(length=64), nullable=True
        ),
    )
    op.add_column(
        "projects",
        sa.Column("governance_launch_input_hash", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_projects_governance_launch_complete",
        "projects",
        "(governance_launch_trigger_id IS NULL AND "
        "governance_launch_control_run_id IS NULL AND "
        "governance_launch_input_hash IS NULL) OR "
        "(governance_launch_trigger_id IS NOT NULL AND "
        "governance_launch_control_run_id IS NOT NULL AND "
        "governance_launch_input_hash IS NOT NULL)",
    )
    op.add_column(
        "governance_runs",
        sa.Column("session_terminal_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "governance_runs",
        sa.Column("session_recovery_code", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("governance_runs", "session_recovery_code")
    op.drop_column("governance_runs", "session_terminal_at")
    op.drop_constraint(
        "ck_projects_governance_launch_complete", "projects", type_="check"
    )
    op.drop_column("projects", "governance_launch_input_hash")
    op.drop_column("projects", "governance_launch_control_run_id")
    op.drop_column("projects", "governance_launch_trigger_id")
