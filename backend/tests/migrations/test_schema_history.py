import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

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
CURRENT_GOVERNANCE_RUN_REVISION = "c2d3e4f5a6b7"
STAGE4_GOVERNANCE_RUN_REVISION = "d3e4f5a6b7c8"
STAGE3_GOVERNANCE_RUN_REVISION = "c1d2e3f4a5b6"
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
        assert connection.execute(
            "SELECT to_regclass('public.model_qualification_results')"
        ).fetchone() == ("model_qualification_results",)
        qualification_columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND table_name = 'model_qualification_results'"
            ).fetchall()
        }
        assert qualification_columns.isdisjoint(
            {
                "secret",
                "prompt",
                "provider_events",
                "raw_output",
                "model_endpoint",
            }
        )


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
            "SELECT count(*) FROM governance_reports"
        ).fetchone() == (0,)
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
                'governance_reports',
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
            ("governance_reports",),
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
              AND column_name IN (
                'report_contract_version',
                'session_terminal_at',
                'session_recovery_code'
              )
            ORDER BY column_name
            """
        ).fetchall() == [
            ("report_contract_version", "YES"),
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


def test_stage4_schema_is_installed_on_a_fresh_database(
    template_baseline_database: str,
) -> None:
    run_migration(template_baseline_database, "head")

    with connect(template_baseline_database) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (CURRENT_GOVERNANCE_RUN_REVISION,)
        assert connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN (
                'observations',
                'resources',
                'observation_resource_links',
                'findings',
                'finding_occurrences',
                'finding_occurrence_observations',
                'finding_occurrence_snapshots',
                'finding_transitions',
                'finding_transition_observations',
                'finding_transition_snapshots'
              )
            ORDER BY table_name
            """
        ).fetchall() == [
            ("finding_occurrence_observations",),
            ("finding_occurrence_snapshots",),
            ("finding_occurrences",),
            ("finding_transition_observations",),
            ("finding_transition_snapshots",),
            ("finding_transitions",),
            ("findings",),
            ("observation_resource_links",),
            ("observations",),
            ("resources",),
        ]
        assert connection.execute(
            """
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'governance_runs'
              AND column_name = 'processing_contract_version'
            """
        ).fetchone() == ("processing_contract_version", "YES")
        step_constraint = connection.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conname = 'ck_run_steps_code'
            """
        ).fetchone()
        assert step_constraint is not None
        assert "NORMALIZE" in step_constraint[0]
        assert "BUILD_REPORT" in step_constraint[0]
        assert "VALIDATE_REPORT" in step_constraint[0]


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


def _seed_stage3_run_facts(
    database: str,
    *,
    complete: bool = True,
    status: str = "RUNNING",
    processing_contract_version: str | None = None,
    report_contract_version: str | None = None,
    step_codes: tuple[str, ...] = (
        "LOAD_CUSTOMER",
        "PULL_CLOUDATLAS",
        "PUBLISH",
    ),
    identity_suffix: str = "",
) -> dict[str, uuid.UUID]:
    project_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    upload_id = uuid.uuid4()
    source_id = uuid.uuid4()
    run_id = uuid.uuid4()
    customer_snapshot_id = uuid.uuid4()
    cloudatlas_snapshot_id = uuid.uuid4()
    with connect(database) as connection:
        connection.execute(
            "INSERT INTO projects "
            "(id, tenant_id, name, current_customer_upload_profile_id, "
            "created_at, updated_at) VALUES (%s, %s, %s, %s, now(), now())",
            (
                project_id,
                DEPLOYMENT_TENANT_ID,
                "Stage 3 history",
                profile_id,
            ),
        )
        connection.execute(
            "INSERT INTO customer_upload_profiles "
            "(id, tenant_id, project_id, version, definition, "
            "created_at, updated_at) VALUES (%s, %s, %s, 1, %s::jsonb, now(), now())",
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
            "created_at, updated_at) VALUES (%s, %s, %s, %s, 1, %s, now(), now())",
            (
                artifact_id,
                DEPLOYMENT_TENANT_ID,
                f"stage3/{artifact_id}",
                "application/octet-stream",
                "a" * 64,
            ),
        )
        connection.execute(
            "INSERT INTO customer_uploads "
            "(id, tenant_id, project_id, artifact_id, display_filename, "
            "raw_sha256, profile_id, profile_version, record_count, warnings, "
            "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 1, "
            "'[]'::jsonb, now(), now())",
            (
                upload_id,
                DEPLOYMENT_TENANT_ID,
                project_id,
                artifact_id,
                "stage3.xlsx",
                "b" * 64,
                profile_id,
            ),
        )
        connection.execute(
            "INSERT INTO source_instances "
            "(id, tenant_id, project_id, source_type, instance_id, capset_id, "
            "enabled, validated_fingerprint, validated_at, created_at, updated_at) "
            "VALUES (%s, %s, %s, 'cloudatlas', %s, %s, true, %s, now(), now(), now())",
            (
                source_id,
                DEPLOYMENT_TENANT_ID,
                project_id,
                f"stage3-instance{identity_suffix}",
                "stage3-capset",
                "c" * 64,
            ),
        )
        run_columns = (
            "id, tenant_id, project_id, trigger_id, session_id, requested_by, "
            "status, customer_upload_id, customer_upload_sha256, "
            "customer_upload_profile_id, customer_upload_profile_version, "
            "source_instance_id, cloudatlas_validated_fingerprint, "
            "cloudatlas_capset_id, cloudatlas_method, package_sha256, "
            "descriptor_sha256, runner_build_version"
        )
        run_values: tuple[object, ...] = (
            run_id,
            DEPLOYMENT_TENANT_ID,
            project_id,
            f"stage3-trigger{identity_suffix}",
            f"stage3-session{identity_suffix}",
            "legacy-runner",
            upload_id,
            "b" * 64,
            profile_id,
            source_id,
            "c" * 64,
            "stage3-capset",
            "stage3-method",
            "d" * 64,
            "e" * 64,
            "stage3-build",
        )
        run_value_placeholders = "%s, %s, %s, %s, %s, %s, %s"
        if processing_contract_version is not None:
            run_columns += ", processing_contract_version"
            run_values += (processing_contract_version,)
            run_value_placeholders += ", %s"
        if report_contract_version is not None:
            run_columns += ", report_contract_version"
            run_values += (report_contract_version,)
            run_value_placeholders += ", %s"
        connection.execute(
            f"INSERT INTO governance_runs ({run_columns}, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'RUNNING', %s, %s, %s, 1, "
            f"{run_value_placeholders}, now(), now())",
            run_values,
        )
        for step_code in step_codes:
            connection.execute(
                "INSERT INTO run_steps "
                "(id, tenant_id, project_id, governance_run_id, step_code, status, "
                "attempt, input_hash, output_hash, started_at, completed_at, "
                "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, 'SUCCEEDED', "
                "1, %s, %s, now(), now(), now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    project_id,
                    run_id,
                    step_code,
                    "f" * 64,
                    "f" * 64,
                ),
            )
        connection.execute(
            "INSERT INTO source_snapshots "
            "(id, tenant_id, project_id, governance_run_id, source_type, "
            "customer_upload_id, artifact_id, content_sha256, schema_fingerprint, "
            "record_count, created_at, updated_at) VALUES (%s, %s, %s, %s, "
            "'CUSTOMER_UPLOAD', %s, %s, %s, %s, 1, now(), now())",
            (
                customer_snapshot_id,
                DEPLOYMENT_TENANT_ID,
                project_id,
                run_id,
                upload_id,
                artifact_id,
                "b" * 64,
                "1" * 64,
            ),
        )
        cloud_artifact_id = uuid.uuid4()
        connection.execute(
            "INSERT INTO artifacts "
            "(id, tenant_id, storage_key, media_type, byte_size, sha256, "
            "created_at, updated_at) VALUES (%s, %s, %s, %s, 1, %s, now(), now())",
            (
                cloud_artifact_id,
                DEPLOYMENT_TENANT_ID,
                f"stage3/cloud/{cloud_artifact_id}",
                "application/json",
                "2" * 64,
            ),
        )
        connection.execute(
            "INSERT INTO source_snapshots "
            "(id, tenant_id, project_id, governance_run_id, source_type, "
            "source_instance_id, artifact_id, content_sha256, schema_fingerprint, "
            "method_fingerprint, record_count, created_at, updated_at) VALUES "
            "(%s, %s, %s, %s, 'CLOUDATLAS', %s, %s, %s, %s, %s, 1, now(), now())",
            (
                cloudatlas_snapshot_id,
                DEPLOYMENT_TENANT_ID,
                project_id,
                run_id,
                source_id,
                cloud_artifact_id,
                "2" * 64,
                "3" * 64,
                "4" * 64,
            ),
        )
        if complete:
            connection.execute(
                "UPDATE governance_runs SET status = 'COMPLETED', "
                "completed_at = now(), updated_at = now() WHERE id = %s",
                (run_id,),
            )
            connection.execute(
                "UPDATE projects SET latest_completed_run_id = %s WHERE id = %s",
                (run_id, project_id),
            )
        elif status != "RUNNING":
            connection.execute(
                "UPDATE governance_runs SET status = %s, updated_at = now() "
                "WHERE id = %s",
                (status, run_id),
            )
    return {
        "project_id": project_id,
        "run_id": run_id,
        "customer_snapshot_id": customer_snapshot_id,
        "cloudatlas_snapshot_id": cloudatlas_snapshot_id,
    }


def test_report_contract_version_and_steps_are_persistable(
    template_baseline_database: str,
) -> None:
    run_migration(template_baseline_database, "head")
    report_steps = (
        "LOAD_CUSTOMER",
        "PULL_CLOUDATLAS",
        "NORMALIZE",
        "RESOLVE",
        "CHECK_FINDINGS",
        "BUILD_REPORT",
        "VALIDATE_REPORT",
        "PUBLISH",
    )
    ids = _seed_stage3_run_facts(
        template_baseline_database,
        complete=False,
        processing_contract_version="ip-v1",
        report_contract_version="deterministic-report-v1",
        step_codes=report_steps,
    )

    with connect(template_baseline_database) as connection:
        assert connection.execute(
            "SELECT report_contract_version FROM governance_runs WHERE id = %s",
            (ids["run_id"],),
        ).fetchone() == ("deterministic-report-v1",)
        persisted_steps = connection.execute(
            "SELECT step_code FROM run_steps WHERE governance_run_id = %s",
            (ids["run_id"],),
        ).fetchall()
        assert {row[0] for row in persisted_steps} == set(report_steps)
        assert len(persisted_steps) == len(report_steps)

    with pytest.raises(psycopg.errors.RaiseException, match="pinned facts"):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "UPDATE governance_runs SET report_contract_version = %s WHERE id = %s",
                ("deterministic-report-v2", ids["run_id"]),
            )


def test_stage3_facts_upgrade_without_reinterpretation(
    template_baseline_database: str,
) -> None:
    run_migration(template_baseline_database, STAGE3_GOVERNANCE_RUN_REVISION)
    ids = _seed_stage3_run_facts(template_baseline_database)

    run_migration(template_baseline_database, "head")

    with connect(template_baseline_database) as connection:
        assert connection.execute(
            "SELECT status, processing_contract_version FROM governance_runs "
            "WHERE id = %s",
            (ids["run_id"],),
        ).fetchone() == ("COMPLETED", None)
        assert connection.execute(
            "SELECT latest_completed_run_id FROM projects WHERE id = %s",
            (ids["project_id"],),
        ).fetchone() == (ids["run_id"],)
        assert connection.execute(
            "SELECT step_code FROM run_steps WHERE governance_run_id = %s "
            "ORDER BY step_code",
            (ids["run_id"],),
        ).fetchall() == [
            ("LOAD_CUSTOMER",),
            ("PUBLISH",),
            ("PULL_CLOUDATLAS",),
        ]
        assert connection.execute(
            "SELECT id FROM source_snapshots WHERE governance_run_id = %s "
            "ORDER BY source_type",
            (ids["run_id"],),
        ).fetchall() == [
            (ids["cloudatlas_snapshot_id"],),
            (ids["customer_snapshot_id"],),
        ]
        for table_name in (
            "observations",
            "observation_resource_links",
            "finding_occurrences",
            "finding_transitions",
            "finding_occurrence_observations",
            "finding_occurrence_snapshots",
            "finding_transition_observations",
            "finding_transition_snapshots",
        ):
            assert connection.execute(
                f"SELECT count(*) FROM {table_name} WHERE governance_run_id = %s",
                (ids["run_id"],),
            ).fetchone() == (0,)


def test_failed_stage3_facts_upgrade_without_reinterpretation(
    template_baseline_database: str,
) -> None:
    run_migration(template_baseline_database, STAGE3_GOVERNANCE_RUN_REVISION)
    ids = _seed_stage3_run_facts(
        template_baseline_database,
        complete=False,
        status="FAILED_DATA",
    )

    run_migration(template_baseline_database, "head")

    with connect(template_baseline_database) as connection:
        assert connection.execute(
            "SELECT status, processing_contract_version, completed_at "
            "FROM governance_runs WHERE id = %s",
            (ids["run_id"],),
        ).fetchone() == ("FAILED_DATA", None, None)
        assert connection.execute(
            "SELECT count(*) FROM observations WHERE governance_run_id = %s",
            (ids["run_id"],),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM finding_occurrences WHERE governance_run_id = %s",
            (ids["run_id"],),
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    ("complete", "status", "expected_status"),
    [
        (True, "RUNNING", "COMPLETED"),
        (False, "FAILED_PROCESSING", "FAILED_PROCESSING"),
    ],
)
def test_stage4_run_history_upgrades_without_report_backfill_or_new_steps(
    template_baseline_database: str,
    complete: bool,
    status: str,
    expected_status: str,
) -> None:
    run_migration(template_baseline_database, STAGE4_GOVERNANCE_RUN_REVISION)
    stage4_steps = (
        "LOAD_CUSTOMER",
        "PULL_CLOUDATLAS",
        "NORMALIZE",
        "RESOLVE",
        "CHECK_FINDINGS",
        "PUBLISH",
    )
    ids = _seed_stage3_run_facts(
        template_baseline_database,
        complete=complete,
        status=status,
        processing_contract_version="ip-v1",
        step_codes=stage4_steps,
    )
    with connect(template_baseline_database) as connection:
        steps_before_upgrade = connection.execute(
            "SELECT id, step_code, status, attempt FROM run_steps "
            "WHERE governance_run_id = %s ORDER BY step_code",
            (ids["run_id"],),
        ).fetchall()

    run_migration(template_baseline_database, "head")

    with connect(template_baseline_database) as connection:
        assert connection.execute(
            "SELECT status, processing_contract_version, report_contract_version "
            "FROM governance_runs WHERE id = %s",
            (ids["run_id"],),
        ).fetchone() == (expected_status, "ip-v1", None)
        assert (
            connection.execute(
                "SELECT id, step_code, status, attempt FROM run_steps "
                "WHERE governance_run_id = %s ORDER BY step_code",
                (ids["run_id"],),
            ).fetchall()
            == steps_before_upgrade
        )
        assert connection.execute(
            "SELECT count(*) FROM governance_reports"
        ).fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM evidence").fetchone() == (0,)


def test_governance_report_persists_canonical_content_and_artifact_hashes(
    template_baseline_database: str,
) -> None:
    run_migration(template_baseline_database, "head")
    ids = _seed_stage3_run_facts(
        template_baseline_database,
        complete=False,
        processing_contract_version="ip-v1",
        report_contract_version="deterministic-report-v1",
    )
    report_id = uuid.uuid4()
    html_artifact_id = uuid.uuid4()
    csv_artifact_id = uuid.uuid4()
    canonical_content = {
        "report_identity": {
            "governance_run_id": str(ids["run_id"]),
            "generation_mode": "DETERMINISTIC_TEMPLATE",
        }
    }

    with connect(template_baseline_database) as connection:
        for artifact_id, media_type, sha256 in (
            (html_artifact_id, "text/html", "8" * 64),
            (csv_artifact_id, "text/csv", "9" * 64),
        ):
            connection.execute(
                "INSERT INTO artifacts "
                "(id, tenant_id, project_id, governance_run_id, storage_key, "
                "media_type, byte_size, sha256, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, 1, %s, now(), now())",
                (
                    artifact_id,
                    DEPLOYMENT_TENANT_ID,
                    ids["project_id"],
                    ids["run_id"],
                    f"reports/{artifact_id}",
                    media_type,
                    sha256,
                ),
            )
        connection.execute(
            "INSERT INTO governance_reports "
            "(id, tenant_id, project_id, governance_run_id, "
            "report_contract_version, generation_mode, canonical_content, "
            "html_artifact_id, html_sha256, csv_artifact_id, csv_sha256, "
            "created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, 'DETERMINISTIC_TEMPLATE', %s::jsonb, "
            "%s, %s, %s, %s, now(), now())",
            (
                report_id,
                DEPLOYMENT_TENANT_ID,
                ids["project_id"],
                ids["run_id"],
                "deterministic-report-v1",
                json.dumps(canonical_content),
                html_artifact_id,
                "8" * 64,
                csv_artifact_id,
                "9" * 64,
            ),
        )

    with connect(template_baseline_database) as connection:
        assert connection.execute(
            "SELECT governance_run_id, report_contract_version, generation_mode, "
            "canonical_content, html_artifact_id, html_sha256, csv_artifact_id, "
            "csv_sha256 FROM governance_reports WHERE id = %s",
            (report_id,),
        ).fetchone() == (
            ids["run_id"],
            "deterministic-report-v1",
            "DETERMINISTIC_TEMPLATE",
            canonical_content,
            html_artifact_id,
            "8" * 64,
            csv_artifact_id,
            "9" * 64,
        )
        report_columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND table_name = 'governance_reports'"
            ).fetchall()
        }
        assert report_columns.isdisjoint(
            {"filesystem_path", "storage_key", "source_payload", "raw_payload"}
        )

    with pytest.raises(psycopg.errors.UniqueViolation):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "INSERT INTO governance_reports "
                "(id, tenant_id, project_id, governance_run_id, "
                "report_contract_version, generation_mode, canonical_content, "
                "html_artifact_id, html_sha256, csv_artifact_id, csv_sha256, "
                "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, "
                "'DETERMINISTIC_TEMPLATE', %s::jsonb, %s, %s, %s, %s, "
                "now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    ids["project_id"],
                    ids["run_id"],
                    "deterministic-report-v1",
                    json.dumps(canonical_content),
                    html_artifact_id,
                    "8" * 64,
                    csv_artifact_id,
                    "9" * 64,
                ),
            )


def _insert_scoped_report_artifacts(
    database: str,
    ids: dict[str, uuid.UUID],
) -> tuple[uuid.UUID, uuid.UUID]:
    html_artifact_id = uuid.uuid4()
    csv_artifact_id = uuid.uuid4()
    with connect(database) as connection:
        for artifact_id, media_type, sha256 in (
            (html_artifact_id, "text/html", "8" * 64),
            (csv_artifact_id, "text/csv", "9" * 64),
        ):
            connection.execute(
                "INSERT INTO artifacts "
                "(id, tenant_id, project_id, governance_run_id, storage_key, "
                "media_type, byte_size, sha256, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, 1, %s, now(), now())",
                (
                    artifact_id,
                    DEPLOYMENT_TENANT_ID,
                    ids["project_id"],
                    ids["run_id"],
                    f"reports/{artifact_id}",
                    media_type,
                    sha256,
                ),
            )
    return html_artifact_id, csv_artifact_id


def _insert_governance_report(
    database: str,
    *,
    ids: dict[str, uuid.UUID],
    html_artifact_id: uuid.UUID,
    csv_artifact_id: uuid.UUID,
    tenant_id: uuid.UUID = DEPLOYMENT_TENANT_ID,
    project_id: uuid.UUID | None = None,
    report_contract_version: str = "deterministic-report-v1",
    generation_mode: str = "DETERMINISTIC_TEMPLATE",
    canonical_content: str = '{"report_identity": {"complete": true}}',
    html_sha256: str = "8" * 64,
    csv_sha256: str = "9" * 64,
) -> None:
    with connect(database) as connection:
        connection.execute(
            "INSERT INTO governance_reports "
            "(id, tenant_id, project_id, governance_run_id, "
            "report_contract_version, generation_mode, canonical_content, "
            "html_artifact_id, html_sha256, csv_artifact_id, csv_sha256, "
            "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, "
            "%s::jsonb, %s, %s, %s, %s, now(), now())",
            (
                uuid.uuid4(),
                tenant_id,
                project_id or ids["project_id"],
                ids["run_id"],
                report_contract_version,
                generation_mode,
                canonical_content,
                html_artifact_id,
                html_sha256,
                csv_artifact_id,
                csv_sha256,
            ),
        )


def test_governance_report_checks_reject_partial_or_noncanonical_records(
    template_baseline_database: str,
) -> None:
    run_migration(template_baseline_database, "head")
    ids = _seed_stage3_run_facts(
        template_baseline_database,
        complete=False,
        processing_contract_version="ip-v1",
        report_contract_version="deterministic-report-v1",
    )
    html_artifact_id, csv_artifact_id = _insert_scoped_report_artifacts(
        template_baseline_database, ids
    )

    invalid_values: tuple[dict[str, Any], ...] = (
        {"generation_mode": "PI_VALIDATED"},
        {"report_contract_version": " "},
        {"canonical_content": "[]"},
        {"html_sha256": "not-a-sha256"},
        {"csv_artifact_id": html_artifact_id, "csv_sha256": "8" * 64},
    )
    for overrides in invalid_values:
        report_values: dict[str, Any] = {
            "ids": ids,
            "html_artifact_id": html_artifact_id,
            "csv_artifact_id": csv_artifact_id,
        }
        report_values.update(overrides)
        with pytest.raises(
            (psycopg.errors.CheckViolation, psycopg.errors.ForeignKeyViolation)
        ):
            _insert_governance_report(
                template_baseline_database,
                **report_values,
            )


def test_governance_report_rejects_cross_scope_run_and_artifact_relations(
    template_baseline_database: str,
) -> None:
    run_migration(template_baseline_database, "head")
    report_ids = _seed_stage3_run_facts(
        template_baseline_database,
        complete=False,
        processing_contract_version="ip-v1",
        report_contract_version="deterministic-report-v1",
    )
    other_ids = _seed_stage3_run_facts(
        template_baseline_database,
        complete=False,
        processing_contract_version="ip-v1",
        report_contract_version="deterministic-report-v1",
        identity_suffix="-other",
    )
    other_html_id, other_csv_id = _insert_scoped_report_artifacts(
        template_baseline_database, other_ids
    )

    scope_overrides_list: tuple[dict[str, Any], ...] = (
        {},
        {"project_id": other_ids["project_id"]},
        {"tenant_id": uuid.uuid4()},
        {"report_contract_version": "deterministic-report-v2"},
    )
    for scope_overrides in scope_overrides_list:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            _insert_governance_report(
                template_baseline_database,
                ids=report_ids,
                html_artifact_id=other_html_id,
                csv_artifact_id=other_csv_id,
                **scope_overrides,
            )


def test_stage4_scope_uniqueness_immutability_and_completed_run_guards(
    template_baseline_database: str,
) -> None:
    run_migration(template_baseline_database, "head")
    ids = _seed_stage3_run_facts(
        template_baseline_database,
        complete=False,
        processing_contract_version="ip-v1",
    )
    resource_id = uuid.uuid4()
    customer_observation_id = uuid.uuid4()
    cloudatlas_observation_id = uuid.uuid4()
    finding_id = uuid.uuid4()
    occurrence_id = uuid.uuid4()
    transition_id = uuid.uuid4()
    with connect(template_baseline_database) as connection:
        connection.execute(
            "INSERT INTO resources "
            "(id, tenant_id, project_id, resource_type, canonical_key, "
            "created_at, updated_at) VALUES (%s, %s, %s, 'IP', %s, now(), now())",
            (
                resource_id,
                DEPLOYMENT_TENANT_ID,
                ids["project_id"],
                "192.0.2.10",
            ),
        )
        connection.execute(
            "INSERT INTO observations "
            "(id, tenant_id, project_id, governance_run_id, source_snapshot_id, "
            "source_type, source_record_key, raw_ip, canonical_ip, created_at, "
            "updated_at) VALUES (%s, %s, %s, %s, %s, 'CUSTOMER_UPLOAD', %s, %s, "
            "%s, now(), now())",
            (
                customer_observation_id,
                DEPLOYMENT_TENANT_ID,
                ids["project_id"],
                ids["run_id"],
                ids["customer_snapshot_id"],
                "row:2",
                "192.0.2.10",
                "192.0.2.10",
            ),
        )
        connection.execute(
            "INSERT INTO observations "
            "(id, tenant_id, project_id, governance_run_id, source_snapshot_id, "
            "source_type, source_record_key, raw_ip, canonical_ip, "
            "cloudatlas_asset_id, cloudatlas_status, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, 'CLOUDATLAS', %s, %s, %s, %s, %s, "
            "now(), now())",
            (
                cloudatlas_observation_id,
                DEPLOYMENT_TENANT_ID,
                ids["project_id"],
                ids["run_id"],
                ids["cloudatlas_snapshot_id"],
                "page:1:item:0",
                "192.0.2.10",
                "192.0.2.10",
                "cloud-1",
                "valid",
            ),
        )
        for observation_id in (customer_observation_id, cloudatlas_observation_id):
            connection.execute(
                "INSERT INTO observation_resource_links "
                "(id, tenant_id, project_id, governance_run_id, observation_id, "
                "resource_id, processing_contract_version, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'ip-v1', now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    ids["project_id"],
                    ids["run_id"],
                    observation_id,
                    resource_id,
                ),
            )
        connection.execute(
            "INSERT INTO findings "
            "(id, tenant_id, project_id, resource_id, finding_type, dedupe_key, "
            "status, created_at, updated_at) VALUES (%s, %s, %s, %s, "
            "'UNREPORTED_ASSET', %s, 'OPEN', now(), now())",
            (
                finding_id,
                DEPLOYMENT_TENANT_ID,
                ids["project_id"],
                resource_id,
                "UNREPORTED_ASSET:192.0.2.10",
            ),
        )
        connection.execute(
            "INSERT INTO finding_occurrences "
            "(id, tenant_id, project_id, finding_id, governance_run_id, "
            "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, now(), now())",
            (
                occurrence_id,
                DEPLOYMENT_TENANT_ID,
                ids["project_id"],
                finding_id,
                ids["run_id"],
            ),
        )
        connection.execute(
            "INSERT INTO finding_transitions "
            "(id, tenant_id, project_id, finding_id, governance_run_id, "
            "transition_type, created_at, updated_at) VALUES (%s, %s, %s, %s, "
            "%s, 'OPENED', now(), now())",
            (
                transition_id,
                DEPLOYMENT_TENANT_ID,
                ids["project_id"],
                finding_id,
                ids["run_id"],
            ),
        )
        connection.execute(
            "INSERT INTO finding_occurrence_observations "
            "(id, tenant_id, project_id, governance_run_id, finding_occurrence_id, "
            "observation_id, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, "
            "%s, now(), now())",
            (
                uuid.uuid4(),
                DEPLOYMENT_TENANT_ID,
                ids["project_id"],
                ids["run_id"],
                occurrence_id,
                customer_observation_id,
            ),
        )
        for reference_table, parent_id, snapshot_id in (
            (
                "finding_occurrence_snapshots",
                occurrence_id,
                ids["customer_snapshot_id"],
            ),
            (
                "finding_occurrence_snapshots",
                occurrence_id,
                ids["cloudatlas_snapshot_id"],
            ),
        ):
            connection.execute(
                f"INSERT INTO {reference_table} "
                "(id, tenant_id, project_id, governance_run_id, "
                "finding_occurrence_id, source_snapshot_id, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    ids["project_id"],
                    ids["run_id"],
                    parent_id,
                    snapshot_id,
                ),
            )
        for observation_id in (customer_observation_id, cloudatlas_observation_id):
            connection.execute(
                "INSERT INTO finding_transition_observations "
                "(id, tenant_id, project_id, governance_run_id, "
                "finding_transition_id, observation_id, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    ids["project_id"],
                    ids["run_id"],
                    transition_id,
                    observation_id,
                ),
            )
        for snapshot_id in (
            ids["customer_snapshot_id"],
            ids["cloudatlas_snapshot_id"],
        ):
            connection.execute(
                "INSERT INTO finding_transition_snapshots "
                "(id, tenant_id, project_id, governance_run_id, "
                "finding_transition_id, source_snapshot_id, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    ids["project_id"],
                    ids["run_id"],
                    transition_id,
                    snapshot_id,
                ),
            )

    with pytest.raises(psycopg.errors.UniqueViolation):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "INSERT INTO findings "
                "(id, tenant_id, project_id, resource_id, finding_type, "
                "dedupe_key, status, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, 'UNREPORTED_ASSET', %s, 'OPEN', "
                "now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    ids["project_id"],
                    resource_id,
                    "different-dedupe-key",
                ),
            )

    with pytest.raises(psycopg.errors.RaiseException, match="does not match"):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "INSERT INTO observation_resource_links "
                "(id, tenant_id, project_id, governance_run_id, observation_id, "
                "resource_id, processing_contract_version, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'ip-v2', now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    ids["project_id"],
                    ids["run_id"],
                    customer_observation_id,
                    resource_id,
                ),
            )

    with pytest.raises(psycopg.errors.UniqueViolation):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "INSERT INTO finding_occurrences "
                "(id, tenant_id, project_id, finding_id, governance_run_id, "
                "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    ids["project_id"],
                    finding_id,
                    ids["run_id"],
                ),
            )

    with pytest.raises(psycopg.errors.UniqueViolation):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "INSERT INTO finding_transitions "
                "(id, tenant_id, project_id, finding_id, governance_run_id, "
                "transition_type, created_at, updated_at) VALUES (%s, %s, %s, %s, "
                "%s, 'CLOSED', now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    ids["project_id"],
                    finding_id,
                    ids["run_id"],
                ),
            )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "INSERT INTO observation_resource_links "
                "(id, tenant_id, project_id, governance_run_id, observation_id, "
                "resource_id, processing_contract_version, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'ip-v1', now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    uuid.uuid4(),
                    ids["run_id"],
                    uuid.uuid4(),
                    resource_id,
                ),
            )

    with connect(template_baseline_database) as connection:
        connection.execute(
            "UPDATE governance_runs SET status = 'COMPLETED', completed_at = now(), "
            "updated_at = now() WHERE id = %s",
            (ids["run_id"],),
        )

    for statement, parameters in (
        (
            "UPDATE observations SET raw_ip = '192.0.2.11' WHERE id = %s",
            (customer_observation_id,),
        ),
        (
            "UPDATE observation_resource_links SET processing_contract_version = "
            "'ip-v2' WHERE observation_id = %s",
            (customer_observation_id,),
        ),
        (
            "UPDATE source_snapshots SET record_count = 2 WHERE id = %s",
            (ids["customer_snapshot_id"],),
        ),
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            with connect(template_baseline_database) as connection:
                connection.execute(statement, parameters)

    late_observation = (
        uuid.uuid4(),
        DEPLOYMENT_TENANT_ID,
        ids["project_id"],
        ids["run_id"],
        ids["customer_snapshot_id"],
        "late-row",
        "192.0.2.12",
        "192.0.2.12",
    )
    with pytest.raises(psycopg.errors.RaiseException, match="completed"):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "INSERT INTO observations "
                "(id, tenant_id, project_id, governance_run_id, source_snapshot_id, "
                "source_type, source_record_key, raw_ip, canonical_ip, created_at, "
                "updated_at) VALUES (%s, %s, %s, %s, %s, 'CUSTOMER_UPLOAD', %s, %s, "
                "%s, now(), now())",
                late_observation,
            )

    with pytest.raises(psycopg.errors.RaiseException, match="completed"):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "INSERT INTO finding_occurrences "
                "(id, tenant_id, project_id, finding_id, governance_run_id, "
                "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    ids["project_id"],
                    finding_id,
                    ids["run_id"],
                ),
            )

    with pytest.raises(psycopg.errors.RaiseException, match="completed"):
        with connect(template_baseline_database) as connection:
            connection.execute(
                "INSERT INTO finding_transition_snapshots "
                "(id, tenant_id, project_id, governance_run_id, "
                "finding_transition_id, source_snapshot_id, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, now(), now())",
                (
                    uuid.uuid4(),
                    DEPLOYMENT_TENANT_ID,
                    ids["project_id"],
                    ids["run_id"],
                    transition_id,
                    ids["customer_snapshot_id"],
                ),
            )
