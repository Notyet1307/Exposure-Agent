import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from app.core.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[2]
PRE_CLEANUP_REVISION = "fe56fa70289e"
CLEANUP_REVISION = "a7d4c9e0b1f2"
PROJECT_AUDIT_REVISION = "c9d4e2f7a105"
PROJECT_LIFECYCLE_REVISION = "7e4a1b2c3d40"
DEPLOYMENT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def connect(database: str) -> psycopg.Connection:
    return psycopg.connect(
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        dbname=database,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )


@pytest.fixture
def template_baseline_database() -> Iterator[str]:
    database = f"test_template_upgrade_{uuid.uuid4().hex}"
    with connect(settings.POSTGRES_DB) as admin_connection:
        admin_connection.autocommit = True
        admin_connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database))
        )

    try:
        yield database
    finally:
        with connect(settings.POSTGRES_DB) as admin_connection:
            admin_connection.autocommit = True
            admin_connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(database)
                )
            )


def run_migration(database: str, revision: str) -> None:
    environment = os.environ.copy()
    environment["POSTGRES_DB"] = database
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=BACKEND_DIR,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_template_database_upgrades_without_losing_users(
    template_baseline_database: str,
) -> None:
    run_migration(template_baseline_database, PRE_CLEANUP_REVISION)

    user_id = uuid.uuid4()
    with connect(template_baseline_database) as connection:
        connection.execute(
            'INSERT INTO "user" '
            "(email, is_active, is_superuser, full_name, id, hashed_password) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                "legacy-admin@example.com",
                True,
                True,
                "Legacy Admin",
                user_id,
                "unused-test-hash",
            ),
        )
        connection.execute(
            "INSERT INTO item (description, id, title, owner_id) "
            "VALUES (%s, %s, %s, %s)",
            ("template example", uuid.uuid4(), "Legacy Item", user_id),
        )

    run_migration(template_baseline_database, "head")

    with connect(template_baseline_database) as connection:
        assert connection.execute("SELECT to_regclass('public.item')").fetchone() == (
            None,
        )
        assert connection.execute(
            'SELECT email FROM "user" WHERE id = %s', (user_id,)
        ).fetchone() == ("legacy-admin@example.com",)
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (PROJECT_LIFECYCLE_REVISION,)
        assert connection.execute("SELECT id FROM tenants").fetchall() == [
            (DEPLOYMENT_TENANT_ID,)
        ]
        assert connection.execute(
            "SELECT to_regclass('public.projects')"
        ).fetchone() == ("projects",)
        assert connection.execute(
            "SELECT to_regclass('public.audit_events')"
        ).fetchone() == ("audit_events",)


def test_existing_projects_and_audit_events_survive_lifecycle_upgrade(
    template_baseline_database: str,
) -> None:
    run_migration(template_baseline_database, PROJECT_AUDIT_REVISION)

    project_id = uuid.uuid4()
    audit_event_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    with connect(template_baseline_database) as connection:
        connection.execute(
            "INSERT INTO projects (id, tenant_id, name, created_at, updated_at) "
            "VALUES (%s, %s, %s, now(), now())",
            (project_id, DEPLOYMENT_TENANT_ID, "Existing Project"),
        )
        connection.execute(
            "INSERT INTO audit_events "
            "(id, tenant_id, project_id, actor_subject, actor_type, action, "
            "target_type, target_id, occurred_at, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now(), now())",
            (
                audit_event_id,
                DEPLOYMENT_TENANT_ID,
                project_id,
                str(actor_id),
                "user",
                "project.created",
                "project",
                project_id,
            ),
        )

    run_migration(template_baseline_database, "head")

    with connect(template_baseline_database) as connection:
        assert connection.execute(
            "SELECT id, name, archived_at FROM projects WHERE id = %s",
            (project_id,),
        ).fetchone() == (project_id, "Existing Project", None)
        assert connection.execute(
            "SELECT id, action FROM audit_events WHERE id = %s",
            (audit_event_id,),
        ).fetchone() == (audit_event_id, "project.created")


def test_fresh_database_migrates_to_project_and_audit_schema(
    template_baseline_database: str,
) -> None:
    run_migration(template_baseline_database, "head")

    with connect(template_baseline_database) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (PROJECT_LIFECYCLE_REVISION,)
        assert connection.execute("SELECT id FROM tenants").fetchall() == [
            (DEPLOYMENT_TENANT_ID,)
        ]
        assert connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('projects', 'audit_events')
            ORDER BY table_name
            """
        ).fetchall() == [("audit_events",), ("projects",)]
        assert connection.execute(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'projects'
              AND column_name = 'archived_at'
            """
        ).fetchone() == ("YES",)
        assert connection.execute(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'audit_events'
              AND column_name = 'project_id'
            """
        ).fetchone() == ("YES",)
        assert connection.execute(
            """
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'audit_events'
              AND column_name IN ('created_at', 'updated_at')
            ORDER BY column_name
            """
        ).fetchall() == [("created_at", "NO"), ("updated_at", "NO")]
