import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import sql

from app.core.config import settings
from tests.migrations.test_schema_history import (
    DEPLOYMENT_TENANT_ID,
    STAGE4_GOVERNANCE_RUN_REVISION,
    _insert_governance_report,
    _insert_scoped_report_artifacts,
    _seed_stage3_run_facts,
    connect,
    run_migration,
)


@pytest.fixture
def evidence_database() -> Iterator[str]:
    database = f"test_evidence_{uuid.uuid4().hex}"
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


def _seed_evidence_targets(
    database: str,
    *,
    identity_suffix: str = "",
) -> tuple[dict[str, uuid.UUID], dict[str, uuid.UUID]]:
    ids = _seed_stage3_run_facts(
        database,
        complete=False,
        processing_contract_version="ip-v1",
        report_contract_version="deterministic-report-v1",
        identity_suffix=identity_suffix,
    )
    html_artifact_id, csv_artifact_id = _insert_scoped_report_artifacts(database, ids)
    _insert_governance_report(
        database,
        ids=ids,
        html_artifact_id=html_artifact_id,
        csv_artifact_id=csv_artifact_id,
    )

    observation_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    finding_id = uuid.uuid4()
    occurrence_id = uuid.uuid4()
    transition_id = uuid.uuid4()
    with connect(database) as connection:
        report_row = connection.execute(
            "SELECT id FROM governance_reports WHERE governance_run_id = %s",
            (ids["run_id"],),
        ).fetchone()
        assert report_row is not None
        report_id = report_row[0]
        connection.execute(
            "INSERT INTO resources "
            "(id, tenant_id, project_id, resource_type, canonical_key, "
            "created_at, updated_at) VALUES (%s, %s, %s, 'IP', %s, now(), now())",
            (
                resource_id,
                DEPLOYMENT_TENANT_ID,
                ids["project_id"],
                f"192.0.2.{10 + len(identity_suffix)}",
            ),
        )
        connection.execute(
            "INSERT INTO observations "
            "(id, tenant_id, project_id, governance_run_id, source_snapshot_id, "
            "source_type, source_record_key, raw_ip, canonical_ip, created_at, "
            "updated_at) VALUES (%s, %s, %s, %s, %s, 'CUSTOMER_UPLOAD', %s, "
            "%s, %s, now(), now())",
            (
                observation_id,
                DEPLOYMENT_TENANT_ID,
                ids["project_id"],
                ids["run_id"],
                ids["customer_snapshot_id"],
                f"row{identity_suffix}:2",
                f"192.0.2.{10 + len(identity_suffix)}",
                f"192.0.2.{10 + len(identity_suffix)}",
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
                f"UNREPORTED_ASSET:{resource_id}",
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
            "transition_type, created_at, updated_at) VALUES "
            "(%s, %s, %s, %s, %s, 'OPENED', now(), now())",
            (
                transition_id,
                DEPLOYMENT_TENANT_ID,
                ids["project_id"],
                finding_id,
                ids["run_id"],
            ),
        )
        for table_name, parent_column, parent_id in (
            ("finding_occurrence_snapshots", "finding_occurrence_id", occurrence_id),
            ("finding_transition_snapshots", "finding_transition_id", transition_id),
        ):
            for snapshot_id in (
                ids["customer_snapshot_id"],
                ids["cloudatlas_snapshot_id"],
            ):
                connection.execute(
                    f"INSERT INTO {table_name} "
                    f"(id, tenant_id, project_id, governance_run_id, {parent_column}, "
                    "source_snapshot_id, created_at, updated_at) "
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

    return ids, {
        "report_id": report_id,
        "source_snapshot_id": ids["customer_snapshot_id"],
        "observation_id": observation_id,
        "finding_occurrence_id": occurrence_id,
        "finding_transition_id": transition_id,
        "html_artifact_id": html_artifact_id,
        "csv_artifact_id": csv_artifact_id,
    }


def _insert_evidence(
    database: str,
    *,
    ids: dict[str, uuid.UUID],
    targets: dict[str, uuid.UUID],
    evidence_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID = DEPLOYMENT_TENANT_ID,
    project_id: uuid.UUID | None = None,
    governance_run_id: uuid.UUID | None = None,
    governance_report_id: uuid.UUID | None = None,
    **target_overrides: uuid.UUID | None,
) -> uuid.UUID:
    evidence_id = evidence_id or uuid.uuid4()
    target_values: dict[str, uuid.UUID | None] = {
        "source_snapshot_id": None,
        "observation_id": None,
        "finding_occurrence_id": None,
        "finding_transition_id": None,
    }
    target_values.update(target_overrides)
    with connect(database) as connection:
        connection.execute(
            "INSERT INTO evidence "
            "(id, tenant_id, project_id, governance_run_id, governance_report_id, "
            "source_snapshot_id, observation_id, finding_occurrence_id, "
            "finding_transition_id, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())",
            (
                evidence_id,
                tenant_id,
                project_id or ids["project_id"],
                governance_run_id or ids["run_id"],
                governance_report_id or targets["report_id"],
                target_values["source_snapshot_id"],
                target_values["observation_id"],
                target_values["finding_occurrence_id"],
                target_values["finding_transition_id"],
            ),
        )
    return evidence_id


def test_evidence_accepts_exactly_one_supported_existing_run_fact(
    evidence_database: str,
) -> None:
    run_migration(evidence_database, "head")
    ids, targets = _seed_evidence_targets(evidence_database)

    for target_column in (
        "source_snapshot_id",
        "observation_id",
        "finding_occurrence_id",
        "finding_transition_id",
    ):
        _insert_evidence(
            evidence_database,
            ids=ids,
            targets=targets,
            **{target_column: targets[target_column]},
        )

    with connect(evidence_database) as connection:
        assert connection.execute("SELECT count(*) FROM evidence").fetchone() == (4,)
        columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'evidence'"
            ).fetchall()
        }
        assert columns.isdisjoint(
            {
                "artifact_id",
                "artifact_content",
                "canonical_content",
                "raw_payload",
                "actor_subject",
                "action",
                "target_type",
            }
        )

    invalid_targets: tuple[dict[str, uuid.UUID], ...] = (
        {},
        {
            "source_snapshot_id": targets["source_snapshot_id"],
            "observation_id": targets["observation_id"],
        },
        {"source_snapshot_id": uuid.uuid4()},
    )
    for invalid_target in invalid_targets:
        with pytest.raises(
            (psycopg.errors.CheckViolation, psycopg.errors.ForeignKeyViolation)
        ):
            _insert_evidence(
                evidence_database,
                ids=ids,
                targets=targets,
                **invalid_target,
            )


def test_evidence_rejects_cross_tenant_project_run_report_and_target_scope(
    evidence_database: str,
) -> None:
    run_migration(evidence_database, "head")
    ids, targets = _seed_evidence_targets(evidence_database)
    other_ids, other_targets = _seed_evidence_targets(
        evidence_database, identity_suffix="-other"
    )

    scope_overrides: tuple[dict[str, Any], ...] = (
        {"tenant_id": uuid.uuid4()},
        {"project_id": other_ids["project_id"]},
        {"governance_run_id": other_ids["run_id"]},
        {"governance_report_id": other_targets["report_id"]},
        {"source_snapshot_id": other_targets["source_snapshot_id"]},
    )
    for overrides in scope_overrides:
        values: dict[str, Any] = {
            "source_snapshot_id": targets["source_snapshot_id"]
        }
        values.update(overrides)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            _insert_evidence(
                evidence_database,
                ids=ids,
                targets=targets,
                **values,
            )


@pytest.mark.parametrize("completed_status", ["COMPLETED", "COMPLETED_WITH_WARNINGS"])
def test_completed_run_rejects_late_evidence_and_report_mutations(
    evidence_database: str,
    completed_status: str,
) -> None:
    run_migration(evidence_database, "head")
    ids, targets = _seed_evidence_targets(evidence_database)
    evidence_id = _insert_evidence(
        evidence_database,
        ids=ids,
        targets=targets,
        source_snapshot_id=targets["source_snapshot_id"],
    )

    with connect(evidence_database) as connection:
        connection.execute(
            "UPDATE evidence SET source_snapshot_id = NULL, observation_id = %s, "
            "updated_at = now() WHERE id = %s",
            (targets["observation_id"], evidence_id),
        )
        connection.execute(
            "UPDATE governance_reports SET canonical_content = "
            "'{\"report_identity\": {\"pre_publish\": true}}'::jsonb, "
            "updated_at = now() WHERE id = %s",
            (targets["report_id"],),
        )
        connection.execute(
            "UPDATE governance_runs SET status = %s, completed_at = now(), "
            "updated_at = now() WHERE id = %s",
            (completed_status, ids["run_id"]),
        )

    evidence_mutations = (
        (
            "INSERT INTO evidence "
            "(id, tenant_id, project_id, governance_run_id, governance_report_id, "
            "source_snapshot_id, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, now(), now())",
            (
                uuid.uuid4(),
                DEPLOYMENT_TENANT_ID,
                ids["project_id"],
                ids["run_id"],
                targets["report_id"],
                targets["source_snapshot_id"],
            ),
        ),
        (
            "UPDATE evidence SET observation_id = NULL, source_snapshot_id = %s "
            "WHERE id = %s",
            (targets["source_snapshot_id"], evidence_id),
        ),
        ("DELETE FROM evidence WHERE id = %s", (evidence_id,)),
    )
    for statement, parameters in evidence_mutations:
        with pytest.raises(psycopg.errors.RaiseException, match="completed"):
            with connect(evidence_database) as connection:
                connection.execute(statement, parameters)

    report_mutations = (
        (
            "UPDATE governance_reports SET canonical_content = "
            "'{\"late\": true}'::jsonb WHERE id = %s",
            (targets["report_id"],),
        ),
        (
            "UPDATE governance_reports SET html_artifact_id = %s, html_sha256 = %s "
            "WHERE id = %s",
            (targets["csv_artifact_id"], "9" * 64, targets["report_id"]),
        ),
        ("DELETE FROM governance_reports WHERE id = %s", (targets["report_id"],)),
    )
    for report_statement, report_parameters in report_mutations:
        with pytest.raises(psycopg.errors.RaiseException, match="completed"):
            with connect(evidence_database) as connection:
                connection.execute(report_statement, report_parameters)


def test_stage4_history_upgrades_without_synthetic_report_or_evidence(
    evidence_database: str,
) -> None:
    run_migration(evidence_database, STAGE4_GOVERNANCE_RUN_REVISION)
    ids = _seed_stage3_run_facts(
        evidence_database,
        processing_contract_version="ip-v1",
        step_codes=(
            "LOAD_CUSTOMER",
            "PULL_CLOUDATLAS",
            "NORMALIZE",
            "RESOLVE",
            "CHECK_FINDINGS",
            "PUBLISH",
        ),
    )

    run_migration(evidence_database, "head")

    with connect(evidence_database) as connection:
        assert connection.execute(
            "SELECT report_contract_version FROM governance_runs WHERE id = %s",
            (ids["run_id"],),
        ).fetchone() == (None,)
        assert connection.execute(
            "SELECT count(*) FROM governance_reports WHERE governance_run_id = %s",
            (ids["run_id"],),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM evidence WHERE governance_run_id = %s",
            (ids["run_id"],),
        ).fetchone() == (0,)
