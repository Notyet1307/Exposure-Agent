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
        ).fetchone() == (CLEANUP_REVISION,)
