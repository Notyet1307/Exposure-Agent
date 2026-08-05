import json
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
PROJECT_MEMBERSHIP_REVISION = "b4f2a1c8d903"
CUSTOMER_UPLOAD_PROFILE_REVISION = "d6a7f4b8c921"
CURRENT_GOVERNANCE_RUN_REVISION = "c1d2e3f4a5b6"
DEPLOYMENT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_PROFILE_DEFINITION = {
    "required_headers": [
        "资产IP",
        "起始端口",
        "结束端口",
        "是否web界面",
        "web界面url",
    ],
    "warning_headers": [
        "服务类型",
        "资产负责人",
        "资产所属部门",
        "端口负责人",
        "部门",
    ],
    "optional_headers": ["序号"],
}


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
        ).fetchone() == (CURRENT_GOVERNANCE_RUN_REVISION,)
        assert connection.execute("SELECT id FROM tenants").fetchall() == [
            (DEPLOYMENT_TENANT_ID,)
        ]
        assert connection.execute(
            "SELECT to_regclass('public.projects')"
        ).fetchone() == ("projects",)
        assert connection.execute(
            "SELECT to_regclass('public.audit_events')"
        ).fetchone() == ("audit_events",)
        assert connection.execute(
            "SELECT to_regclass('public.project_memberships')"
        ).fetchone() == ("project_memberships",)


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
            "SELECT id, name, archived_at, current_customer_upload_id "
            "FROM projects WHERE id = %s",
            (project_id,),
        ).fetchone() == (project_id, "Existing Project", None, None)
        assert connection.execute(
            "SELECT id, action FROM audit_events WHERE id = %s",
            (audit_event_id,),
        ).fetchone() == (audit_event_id, "project.created")


def test_existing_projects_receive_independent_default_profiles_once(
    template_baseline_database: str,
) -> None:
    run_migration(template_baseline_database, PROJECT_MEMBERSHIP_REVISION)

    first_project_id = uuid.uuid4()
    second_project_id = uuid.uuid4()
    with connect(template_baseline_database) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO projects (id, tenant_id, name, created_at, updated_at) "
                "VALUES (%s, %s, %s, now(), now())",
                [
                    (
                        first_project_id,
                        DEPLOYMENT_TENANT_ID,
                        "First Existing Project",
                    ),
                    (
                        second_project_id,
                        DEPLOYMENT_TENANT_ID,
                        "Second Existing Project",
                    ),
                ],
            )

    run_migration(template_baseline_database, "head")
    run_migration(template_baseline_database, "head")

    with connect(template_baseline_database) as connection:
        profiles = connection.execute(
            "SELECT id, project_id, tenant_id, version, definition, "
            "created_at, updated_at "
            "FROM customer_upload_profiles ORDER BY project_id"
        ).fetchall()
        assert len(profiles) == 2
        assert {profile[1] for profile in profiles} == {
            first_project_id,
            second_project_id,
        }
        assert profiles[0][0] != profiles[1][0]
        assert all(profile[2] == DEPLOYMENT_TENANT_ID for profile in profiles)
        assert all(profile[3] == 1 for profile in profiles)
        assert all(profile[4] == DEFAULT_PROFILE_DEFINITION for profile in profiles)
        assert all(profile[5] is not None for profile in profiles)
        assert all(profile[6] is not None for profile in profiles)
        assert connection.execute(
            "SELECT count(*) FROM projects p "
            "JOIN customer_upload_profiles cup "
            "ON cup.id = p.current_customer_upload_profile_id "
            "AND cup.project_id = p.id"
        ).fetchone() == (2,)

    with pytest.raises(psycopg.errors.UniqueViolation):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "INSERT INTO customer_upload_profiles "
                "(id, tenant_id, project_id, version, definition, "
                "created_at, updated_at) "
                "VALUES (%s, %s, %s, 1, %s::jsonb, now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    first_project_id,
                    json.dumps(DEFAULT_PROFILE_DEFINITION, ensure_ascii=False),
                ),
            )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with connect(template_baseline_database) as connection:
            second_profile_row = connection.execute(
                "SELECT id FROM customer_upload_profiles WHERE project_id = %s",
                (second_project_id,),
            ).fetchone()
            assert second_profile_row is not None
            second_profile_id = second_profile_row[0]
            connection.execute(
                "UPDATE projects SET current_customer_upload_profile_id = %s "
                "WHERE id = %s",
                (second_profile_id, first_project_id),
            )

    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "UPDATE customer_upload_profiles SET definition = %s::jsonb "
                "WHERE project_id = %s",
                (json.dumps({"required_headers": []}), first_project_id),
            )


def test_customer_upload_schema_enforces_idempotency_immutability_and_deletion(
    template_baseline_database: str,
) -> None:
    run_migration(template_baseline_database, "head")

    project_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    upload_id = uuid.uuid4()
    raw_sha256 = "a" * 64
    with connect(template_baseline_database) as connection:
        connection.execute(
            "INSERT INTO projects "
            "(id, tenant_id, name, current_customer_upload_profile_id, "
            "created_at, updated_at) VALUES (%s, %s, %s, %s, now(), now())",
            (
                project_id,
                DEPLOYMENT_TENANT_ID,
                "Upload Constraints",
                profile_id,
            ),
        )
        connection.execute(
            "INSERT INTO customer_upload_profiles "
            "(id, tenant_id, project_id, version, definition, "
            "created_at, updated_at) "
            "VALUES (%s, %s, %s, 1, %s::jsonb, now(), now())",
            (
                profile_id,
                DEPLOYMENT_TENANT_ID,
                project_id,
                json.dumps(DEFAULT_PROFILE_DEFINITION, ensure_ascii=False),
            ),
        )
        connection.execute(
            "INSERT INTO artifacts "
            "(id, tenant_id, storage_key, media_type, byte_size, sha256, "
            "created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, 10, %s, now(), now())",
            (
                artifact_id,
                DEPLOYMENT_TENANT_ID,
                f"customer_uploads/{artifact_id}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                raw_sha256,
            ),
        )
        connection.execute(
            "INSERT INTO customer_uploads "
            "(id, tenant_id, project_id, artifact_id, display_filename, "
            "raw_sha256, profile_id, profile_version, record_count, warnings, "
            "created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 1, '[]'::jsonb, "
            "now(), now())",
            (
                upload_id,
                DEPLOYMENT_TENANT_ID,
                project_id,
                artifact_id,
                "customer.xlsx",
                raw_sha256,
                profile_id,
            ),
        )

    second_project_id = uuid.uuid4()
    second_profile_id = uuid.uuid4()
    with connect(template_baseline_database) as connection:
        connection.execute(
            "INSERT INTO projects "
            "(id, tenant_id, name, current_customer_upload_profile_id, "
            "created_at, updated_at) VALUES (%s, %s, %s, %s, now(), now())",
            (
                second_project_id,
                DEPLOYMENT_TENANT_ID,
                "Other Upload Constraints",
                second_profile_id,
            ),
        )
        connection.execute(
            "INSERT INTO customer_upload_profiles "
            "(id, tenant_id, project_id, version, definition, "
            "created_at, updated_at) "
            "VALUES (%s, %s, %s, 1, %s::jsonb, now(), now())",
            (
                second_profile_id,
                DEPLOYMENT_TENANT_ID,
                second_project_id,
                json.dumps(DEFAULT_PROFILE_DEFINITION, ensure_ascii=False),
            ),
        )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "UPDATE projects SET current_customer_upload_id = %s WHERE id = %s",
                (upload_id, second_project_id),
            )

    mismatched_artifact_id = uuid.uuid4()
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "INSERT INTO artifacts "
                "(id, tenant_id, storage_key, media_type, byte_size, sha256, "
                "created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, 10, %s, now(), now())",
                (
                    mismatched_artifact_id,
                    DEPLOYMENT_TENANT_ID,
                    f"customer_uploads/{mismatched_artifact_id}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "b" * 64,
                ),
            )
            connection.execute(
                "INSERT INTO customer_uploads "
                "(id, tenant_id, project_id, artifact_id, display_filename, "
                "raw_sha256, profile_id, profile_version, record_count, warnings, "
                "created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 2, 1, '[]'::jsonb, "
                "now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    project_id,
                    mismatched_artifact_id,
                    "mismatched.xlsx",
                    "b" * 64,
                    profile_id,
                ),
            )

    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "UPDATE artifacts SET byte_size = 11 WHERE id = %s", (artifact_id,)
            )

    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "UPDATE customer_uploads SET display_filename = %s WHERE id = %s",
                ("changed.xlsx", upload_id),
            )

    duplicate_artifact_id = uuid.uuid4()
    with pytest.raises(psycopg.errors.UniqueViolation):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "INSERT INTO artifacts "
                "(id, tenant_id, storage_key, media_type, byte_size, sha256, "
                "created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, 10, %s, now(), now())",
                (
                    duplicate_artifact_id,
                    DEPLOYMENT_TENANT_ID,
                    f"customer_uploads/{duplicate_artifact_id}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    raw_sha256,
                ),
            )
            connection.execute(
                "INSERT INTO customer_uploads "
                "(id, tenant_id, project_id, artifact_id, display_filename, "
                "raw_sha256, profile_id, profile_version, record_count, warnings, "
                "created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 1, '[]'::jsonb, "
                "now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    project_id,
                    duplicate_artifact_id,
                    "duplicate.xlsx",
                    raw_sha256,
                    profile_id,
                ),
            )

    with connect(template_baseline_database) as connection:
        connection.execute(
            "UPDATE projects SET current_customer_upload_id = %s WHERE id = %s",
            (upload_id, project_id),
        )

    with pytest.raises(psycopg.errors.RestrictViolation):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "DELETE FROM customer_uploads WHERE id = %s", (upload_id,)
            )

    with connect(template_baseline_database) as connection:
        connection.execute(
            "UPDATE projects SET current_customer_upload_id = NULL WHERE id = %s",
            (project_id,),
        )
        connection.execute("DELETE FROM customer_uploads WHERE id = %s", (upload_id,))
        connection.execute("DELETE FROM artifacts WHERE id = %s", (artifact_id,))
    with connect(template_baseline_database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM customer_uploads WHERE id = %s", (upload_id,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM artifacts WHERE id = %s", (artifact_id,)
        ).fetchone() == (0,)


def test_fresh_database_migrates_to_project_and_audit_schema(
    template_baseline_database: str,
) -> None:
    run_migration(template_baseline_database, "head")

    with connect(template_baseline_database) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (CURRENT_GOVERNANCE_RUN_REVISION,)
        assert connection.execute("SELECT id FROM tenants").fetchall() == [
            (DEPLOYMENT_TENANT_ID,)
        ]
        assert connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN (
                'projects',
                'project_memberships',
                'audit_events',
                'artifacts',
                'customer_upload_profiles',
                'customer_uploads',
                'governance_runs',
                'run_steps',
                'source_instances',
                'source_snapshots'
              )
            ORDER BY table_name
            """
        ).fetchall() == [
            ("artifacts",),
            ("audit_events",),
            ("customer_upload_profiles",),
            ("customer_uploads",),
            ("governance_runs",),
            ("project_memberships",),
            ("projects",),
            ("run_steps",),
            ("source_instances",),
            ("source_snapshots",),
        ]
        source_index = connection.execute(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND indexname = 'uq_source_instances_one_enabled_type_per_project'
            """
        ).fetchone()
        assert source_index is not None
        assert "UNIQUE INDEX" in source_index[0]
        assert "(project_id, source_type)" in source_index[0]
        assert "WHERE enabled" in source_index[0]
        active_run_index = connection.execute(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND indexname = 'uq_governance_runs_one_active_per_project'
            """
        ).fetchone()
        assert active_run_index is not None
        assert "UNIQUE INDEX" in active_run_index[0]
        assert "(project_id)" in active_run_index[0]
        assert "WHERE" in active_run_index[0]
        assert "status" in active_run_index[0]
        assert "RUNNING" in active_run_index[0]
        assert connection.execute(
            """
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'customer_upload_profiles'
              AND column_name IN ('tenant_id', 'created_at', 'updated_at')
            ORDER BY column_name
            """
        ).fetchall() == [
            ("created_at", "NO"),
            ("tenant_id", "NO"),
            ("updated_at", "NO"),
        ]
        assert connection.execute(
            """
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'projects'
              AND column_name IN (
                'archived_at',
                'current_customer_upload_id',
                'current_customer_upload_profile_id',
                'governance_launch_control_run_id',
                'governance_launch_input_hash',
                'governance_launch_trigger_id',
                'latest_completed_run_id'
              )
            ORDER BY column_name
            """
        ).fetchall() == [
            ("archived_at", "YES"),
            ("current_customer_upload_id", "YES"),
            ("current_customer_upload_profile_id", "NO"),
            ("governance_launch_control_run_id", "YES"),
            ("governance_launch_input_hash", "YES"),
            ("governance_launch_trigger_id", "YES"),
            ("latest_completed_run_id", "YES"),
        ]
        assert connection.execute(
            """
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'governance_runs'
              AND column_name IN ('session_terminal_at', 'session_recovery_code')
            ORDER BY column_name
            """
        ).fetchall() == [
            ("session_recovery_code", "YES"),
            ("session_terminal_at", "YES"),
        ]
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


def test_membership_migration_preserves_revoked_history_and_rejects_duplicates(
    template_baseline_database: str,
) -> None:
    run_migration(template_baseline_database, PROJECT_MEMBERSHIP_REVISION)

    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    with connect(template_baseline_database) as connection:
        connection.execute(
            'INSERT INTO "user" '
            "(email, is_active, is_superuser, id, hashed_password) "
            "VALUES (%s, true, false, %s, %s)",
            (f"member-{user_id}@example.com", user_id, "unused-test-hash"),
        )
        connection.execute(
            "INSERT INTO projects (id, tenant_id, name, created_at, updated_at) "
            "VALUES (%s, %s, %s, now(), now())",
            (project_id, DEPLOYMENT_TENANT_ID, "Membership History"),
        )
        connection.execute(
            "INSERT INTO project_memberships "
            "(id, tenant_id, project_id, user_id, roles, revoked_at, "
            "created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, now(), now(), now())",
            (
                membership_id,
                DEPLOYMENT_TENANT_ID,
                project_id,
                user_id,
                ["operator", "approver"],
            ),
        )

    run_migration(template_baseline_database, "head")

    with connect(template_baseline_database) as connection:
        assert connection.execute(
            "SELECT id, roles, revoked_at IS NOT NULL "
            "FROM project_memberships WHERE id = %s",
            (membership_id,),
        ).fetchone() == (membership_id, ["operator", "approver"], True)

    with pytest.raises(psycopg.errors.UniqueViolation):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "INSERT INTO project_memberships "
                "(id, tenant_id, project_id, user_id, roles, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    project_id,
                    user_id,
                    ["viewer"],
                ),
            )
