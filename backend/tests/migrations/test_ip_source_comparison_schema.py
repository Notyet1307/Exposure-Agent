import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import psycopg
import pytest
from psycopg import sql

from app.domain.models import IPSourceComparisonFact
from tests.migrations.test_ai_governance_draft_schema import (
    _insert_unsealed_draft,
    _seal_draft,
    _seed_draft_fixture,
    run_downgrade,
)
from tests.migrations.test_evidence_schema import (
    _insert_evidence,
    _seed_evidence_targets,
)
from tests.migrations.test_evidence_schema import (
    evidence_database as evidence_database,
)
from tests.migrations.test_schema_history import (
    DEPLOYMENT_TENANT_ID,
    _seed_stage3_run_facts,
    connect,
    run_migration,
)

PRE_COMPARISON_REVISION = "b8c9d0e1f2a3"
COMPARISON_REVISION = "c9d0e1f2a3b4"


def _fact_values(
    ids: dict[str, Any], resource_id: uuid.UUID, canonical_ip: str = "192.0.2.10"
) -> dict[str, Any]:
    return {
        "id": uuid.uuid5(ids["run_id"], f"ip-source-comparison/v1/{canonical_ip}"),
        "tenant_id": DEPLOYMENT_TENANT_ID,
        "project_id": ids["project_id"],
        "governance_run_id": ids["run_id"],
        "resource_id": resource_id,
        "contract_version": "ip-source-comparison/v1",
        "canonical_ip": canonical_ip,
        "customer_upload_present": True,
        "cloudatlas_present": True,
        "netflow_status": "UNKNOWN",
        "classification": "matched",
        "classification_reason": "observed_in_both_sources",
        "netflow_reason": "netflow_input_absent",
        "content_hash": "a" * 64,
    }


def _insert_fact(connection: psycopg.Connection, values: dict[str, Any]) -> None:
    connection.execute(
        sql.SQL("INSERT INTO ip_source_comparison_facts ({}) VALUES ({})").format(
            sql.SQL(", ").join(map(sql.Identifier, values)),
            sql.SQL(", ").join(sql.Placeholder() for _ in values),
        ),
        tuple(values.values()),
    )


def _insert_comparison_evidence(
    connection: psycopg.Connection,
    ids: dict[str, Any],
    targets: dict[str, Any],
    fact_id: uuid.UUID,
    **overrides: Any,
) -> uuid.UUID:
    values = {
        "id": uuid.uuid4(),
        "tenant_id": DEPLOYMENT_TENANT_ID,
        "project_id": ids["project_id"],
        "governance_run_id": ids["run_id"],
        "governance_report_id": targets["report_id"],
        "ip_source_comparison_fact_id": fact_id,
    } | overrides
    connection.execute(
        sql.SQL(
            "INSERT INTO evidence ({}, created_at, updated_at) VALUES ({}, now(), now())"
        ).format(
            sql.SQL(", ").join(map(sql.Identifier, values)),
            sql.SQL(", ").join(sql.Placeholder() for _ in values),
        ),
        tuple(values.values()),
    )
    evidence_id = values["id"]
    assert isinstance(evidence_id, uuid.UUID)
    return evidence_id


def _seed_comparison_scope(
    database: str, *, identity_suffix: str = ""
) -> tuple[dict[str, uuid.UUID], dict[str, uuid.UUID]]:
    return _seed_evidence_targets(
        database,
        identity_suffix=identity_suffix,
        report_contract_version="deterministic-report-v2",
    )


def _add_resource(connection: psycopg.Connection, ids: dict[str, Any]) -> uuid.UUID:
    resource_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO resources "
        "(id, tenant_id, project_id, resource_type, canonical_key, created_at, updated_at) "
        "VALUES (%s, %s, %s, 'IP', '192.0.2.200', now(), now())",
        (resource_id, DEPLOYMENT_TENANT_ID, ids["project_id"]),
    )
    return resource_id


def test_comparison_schema_fields_and_required_enum_hash_constraints(
    evidence_database: str,
) -> None:
    run_migration(evidence_database, "head")
    ids, targets = _seed_comparison_scope(evidence_database)
    values = _fact_values(ids, targets["resource_id"])
    with connect(evidence_database) as connection:
        columns = connection.execute(
            "SELECT column_name, is_nullable, data_type, character_maximum_length "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'ip_source_comparison_facts'"
        ).fetchall()
        assert {row[0] for row in columns} == set(values) | {"created_at"}
        assert {row[0] for row in columns} == set(
            IPSourceComparisonFact.__table__.columns.keys()  # type: ignore[attr-defined]
        )
        assert all(row[1] == "NO" for row in columns)
        types = {row[0]: (row[2], row[3]) for row in columns}
        assert types["canonical_ip"] == ("character varying", 39)
        assert types["customer_upload_present"] == ("boolean", None)
        assert types["cloudatlas_present"] == ("boolean", None)
        scoped_foreign_keys = {
            "fk_ip_source_comparison_facts_run_scope",
            "fk_ip_source_comparison_facts_resource_scope",
            "fk_evidence_ip_source_comparison_scope",
            "fk_evidence_governance_report_scope",
            "fk_governance_reports_run_contract_scope",
        }
        assert set(
            connection.execute(
                "SELECT conname, confdeltype FROM pg_constraint WHERE conname = ANY(%s)",
                (list(scoped_foreign_keys),),
            ).fetchall()
        ) == {(name, "r") for name in scoped_foreign_keys}
        for column in values:
            with pytest.raises(psycopg.errors.NotNullViolation):
                with connection.transaction():
                    _insert_fact(connection, values | {column: None})
        invalid_values = (
            {"contract_version": "ip-source-comparison/v2"},
            {"canonical_ip": " "},
            {"classification": "unknown"},
            {"classification_reason": "unknown"},
            {"customer_upload_present": False},
            {"netflow_status": "INACTIVE"},
            {"netflow_status": "ACTIVE"},
            {"netflow_reason": "positive_activity_observed"},
            {"netflow_reason": "unknown"},
            {"content_hash": "A" * 64},
            {"content_hash": "g" * 64},
            {"content_hash": "a" * 63},
        )
        for invalid in invalid_values:
            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    _insert_fact(connection, values | invalid)
        with pytest.raises(psycopg.errors.StringDataRightTruncation):
            with connection.transaction():
                _insert_fact(connection, values | {"canonical_ip": "a" * 40})


def test_comparison_seven_membership_combinations_and_unknown_reasons(
    evidence_database: str,
) -> None:
    run_migration(evidence_database, "head")
    ids, targets = _seed_comparison_scope(evidence_database)
    values = _fact_values(ids, targets["resource_id"])
    combinations = (
        (True, True, "matched", "observed_in_both_sources"),
        (True, False, "customer_upload_only", "observed_in_customer_upload_only"),
        (False, True, "cloudatlas_only", "observed_in_cloudatlas_only"),
        (False, False, "neither_source_observed", "not_observed_in_either_source"),
    )
    with connect(evidence_database) as connection:
        count = 0
        for customer, cloudatlas, classification, reason in combinations:
            for status, netflow_reason in (
                ("ACTIVE", "positive_activity_observed"),
                ("UNKNOWN", "netflow_input_absent"),
                ("UNKNOWN", "no_positive_activity_evidence"),
            ):
                row = values | {
                    "customer_upload_present": customer,
                    "cloudatlas_present": cloudatlas,
                    "classification": classification,
                    "classification_reason": reason,
                    "netflow_status": status,
                    "netflow_reason": netflow_reason,
                }
                if not customer and not cloudatlas and status == "UNKNOWN":
                    with pytest.raises(psycopg.errors.CheckViolation):
                        with connection.transaction():
                            _insert_fact(connection, row)
                else:
                    with connection.transaction(force_rollback=True):
                        _insert_fact(connection, row)
                        count += 1
        assert count == 10  # Seven combinations, plus the second UNKNOWN reason.


def test_comparison_exact_one_uniqueness_scope_and_legacy_duplicates(
    evidence_database: str,
) -> None:
    run_migration(evidence_database, "head")
    ids, targets = _seed_comparison_scope(evidence_database)
    other_ids, other_targets = _seed_comparison_scope(
        evidence_database, identity_suffix="-other"
    )
    values = _fact_values(ids, targets["resource_id"])
    other_values = _fact_values(other_ids, other_targets["resource_id"], "192.0.2.16")
    with connect(evidence_database) as connection:
        _insert_fact(connection, values)
        _insert_fact(connection, other_values)
        _insert_comparison_evidence(connection, ids, targets, values["id"])
        extra_resource = _add_resource(connection, ids)
        for duplicate, constraint in (
            (
                {"id": uuid.uuid4(), "canonical_ip": "192.0.2.200"},
                "uq_ip_source_comparison_facts_run_resource",
            ),
            (
                {"id": uuid.uuid4(), "resource_id": extra_resource},
                "uq_ip_source_comparison_facts_run_ip",
            ),
        ):
            with pytest.raises(psycopg.errors.UniqueViolation) as error:
                with connection.transaction():
                    _insert_fact(connection, values | duplicate)
            assert error.value.diag.constraint_name == constraint
        with pytest.raises(psycopg.errors.UniqueViolation) as error:
            with connection.transaction():
                _insert_comparison_evidence(connection, ids, targets, values["id"])
        assert (
            error.value.diag.constraint_name
            == "uq_evidence_report_ip_source_comparison"
        )
        for old_column in (
            "source_snapshot_id",
            "observation_id",
            "finding_occurrence_id",
            "finding_transition_id",
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    _insert_comparison_evidence(
                        connection,
                        ids,
                        targets,
                        values["id"],
                        **{old_column: targets[old_column]},
                    )
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                _insert_comparison_evidence(
                    connection,
                    ids,
                    targets,
                    values["id"],
                    ip_source_comparison_fact_id=None,
                )
        for scope in (
            {"tenant_id": uuid.uuid4()},
            {"project_id": other_ids["project_id"]},
            {"governance_run_id": other_ids["run_id"]},
            {"governance_run_id": uuid.uuid4()},
            {"resource_id": other_targets["resource_id"]},
            {"resource_id": uuid.uuid4()},
        ):
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                with connection.transaction():
                    _insert_fact(
                        connection,
                        values
                        | {
                            "id": uuid.uuid4(),
                            "canonical_ip": "192.0.2.201",
                            "resource_id": extra_resource,
                        }
                        | scope,
                    )
        # Multiple distinct comparison targets per Report remain legal.
        second = _fact_values(ids, extra_resource, "192.0.2.200")
        _insert_fact(connection, second)
        for scope in (
            {"tenant_id": uuid.uuid4()},
            {"project_id": other_ids["project_id"]},
            {"governance_run_id": other_ids["run_id"]},
            {"governance_report_id": other_targets["report_id"]},
            {"ip_source_comparison_fact_id": other_values["id"]},
            {"ip_source_comparison_fact_id": uuid.uuid4()},
        ):
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                with connection.transaction():
                    _insert_comparison_evidence(
                        connection, ids, targets, second["id"], **scope
                    )
        _insert_comparison_evidence(connection, ids, targets, second["id"])
    for _ in range(2):
        _insert_evidence(
            evidence_database,
            ids=ids,
            targets=targets,
            source_snapshot_id=targets["source_snapshot_id"],
        )
    with connect(evidence_database) as connection:
        assert connection.execute("SELECT count(*) FROM evidence").fetchone() == (4,)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with connection.transaction():
                connection.execute(
                    "UPDATE governance_reports SET report_contract_version = 'deterministic-report-v1' WHERE id = %s",
                    (targets["report_id"],),
                )


@pytest.mark.parametrize(
    "status",
    [
        "RUNNING",
        "FAILED_DATA",
        "FAILED_PROCESSING",
        "COMPLETED",
        "COMPLETED_WITH_WARNINGS",
    ],
)
def test_comparison_facts_are_immutable_in_every_run_state(
    evidence_database: str,
    status: str,
) -> None:
    run_migration(evidence_database, "head")
    ids, targets = _seed_comparison_scope(evidence_database)
    values = _fact_values(ids, targets["resource_id"])
    with connect(evidence_database) as connection:
        _insert_fact(connection, values)
        evidence_id = _insert_comparison_evidence(
            connection, ids, targets, values["id"]
        )
        extra_resource = _add_resource(connection, ids)
        connection.execute(
            "UPDATE governance_runs SET status = %s, completed_at = CASE WHEN %s LIKE 'COMPLETED%%' THEN now() ELSE NULL END WHERE id = %s",
            (status, status, ids["run_id"]),
        )
    for statement in (
        "UPDATE ip_source_comparison_facts SET content_hash = content_hash WHERE id = %s",
        "DELETE FROM ip_source_comparison_facts WHERE id = %s",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            with connect(evidence_database) as connection:
                connection.execute(statement, (values["id"],))
    if status.startswith("COMPLETED"):
        with pytest.raises(psycopg.errors.RaiseException, match="completed"):
            with connect(evidence_database) as connection:
                _insert_fact(
                    connection, _fact_values(ids, extra_resource, "192.0.2.200")
                )
        with pytest.raises(psycopg.errors.RaiseException, match="completed"):
            with connect(evidence_database) as connection:
                _insert_comparison_evidence(connection, ids, targets, values["id"])
        for statement in (
            "UPDATE evidence SET updated_at = now() WHERE id = %s",
            "DELETE FROM evidence WHERE id = %s",
        ):
            with pytest.raises(psycopg.errors.RaiseException, match="completed"):
                with connect(evidence_database) as connection:
                    connection.execute(statement, (evidence_id,))


def _wait_for_run_lock(
    connection: psycopg.Connection,
    blocked_pid: int,
    blocker_pid: int,
) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        row = connection.execute(
            "SELECT pg_blocking_pids(%s)", (blocked_pid,)
        ).fetchone()
        if row is not None and blocker_pid in row[0]:
            return
        time.sleep(0.01)
    raise AssertionError("Competing transaction did not wait on the Run lock")


@pytest.mark.parametrize("completed_status", ["COMPLETED", "COMPLETED_WITH_WARNINGS"])
@pytest.mark.parametrize("first_writer", ["publication", "fact"])
def test_comparison_insert_and_publication_serialize_on_the_run_row(
    evidence_database: str,
    completed_status: str,
    first_writer: str,
) -> None:
    run_migration(evidence_database, "head")
    ids, targets = _seed_comparison_scope(evidence_database)
    values = _fact_values(ids, targets["resource_id"])
    with connect(evidence_database) as first, connect(evidence_database) as second:
        second.execute("SET statement_timeout = '10s'")
        first_pid, second_pid = first.info.backend_pid, second.info.backend_pid

        def publish(connection: psycopg.Connection) -> int:
            connection.execute(
                "UPDATE governance_runs SET status = %s, completed_at = now() WHERE id = %s",
                (completed_status, ids["run_id"]),
            )
            row = connection.execute(
                "SELECT count(*) FROM ip_source_comparison_facts WHERE governance_run_id = %s",
                (ids["run_id"],),
            ).fetchone()
            assert row is not None
            return int(row[0])

        if first_writer == "publication":
            assert publish(first) == 0
        else:
            _insert_fact(first, values)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = (
                executor.submit(_insert_fact, second, values)
                if first_writer == "publication"
                else executor.submit(publish, second)
            )
            try:
                _wait_for_run_lock(first, second_pid, first_pid)
            finally:
                first.commit()
            if first_writer == "publication":
                with pytest.raises(psycopg.errors.RaiseException, match="completed"):
                    future.result(timeout=10)
                second.rollback()
            else:
                # The publication check, under the winning Run lock, sees the full write.
                assert future.result(timeout=10) == 1
                second.commit()
    with connect(evidence_database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM ip_source_comparison_facts"
        ).fetchone() == ((0,) if first_writer == "publication" else (1,))


@pytest.mark.parametrize("after_evidence", [False, True])
def test_comparison_fact_and_evidence_follow_outer_transaction_rollback(
    evidence_database: str,
    after_evidence: bool,
) -> None:
    run_migration(evidence_database, "head")
    ids, targets = _seed_comparison_scope(evidence_database)
    values = _fact_values(ids, targets["resource_id"])
    with pytest.raises(RuntimeError, match="rollback probe"):
        with connect(evidence_database) as connection:
            _insert_fact(connection, values)
            if after_evidence:
                _insert_comparison_evidence(connection, ids, targets, values["id"])
            raise RuntimeError("rollback probe")
    with connect(evidence_database) as connection:
        for table in ("ip_source_comparison_facts", "evidence"):
            assert connection.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
            ).fetchone() == (0,)


def test_comparison_migration_preserves_null_v1_history_without_backfill(
    evidence_database: str,
) -> None:
    run_migration(evidence_database, PRE_COMPARISON_REVISION)
    _seed_stage3_run_facts(evidence_database, identity_suffix="-legacy")
    ids, targets = _seed_evidence_targets(evidence_database, identity_suffix="-v1")
    _insert_evidence(
        evidence_database,
        ids=ids,
        targets=targets,
        source_snapshot_id=targets["source_snapshot_id"],
    )

    def snapshot() -> dict[str, list[Any]]:
        with connect(evidence_database) as connection:
            return {
                table: connection.execute(
                    sql.SQL(
                        "SELECT to_jsonb(row) - 'ip_source_comparison_fact_id' FROM {} AS row ORDER BY id"
                    ).format(sql.Identifier(table))
                ).fetchall()
                for table in ("governance_runs", "governance_reports", "evidence")
            }

    before = snapshot()
    run_migration(evidence_database, "head")
    assert snapshot() == before
    with connect(evidence_database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM ip_source_comparison_facts"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT ip_source_comparison_fact_id FROM evidence"
        ).fetchall() == [(None,)]
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (COMPARISON_REVISION,)
    run_downgrade(evidence_database, PRE_COMPARISON_REVISION)
    assert snapshot() == before
    run_migration(evidence_database, "head")
    assert snapshot() == before


@pytest.mark.parametrize("mixed_target", [False, True])
def test_ai_sql_binding_guard_rejects_new_target_even_with_a_legacy_target(
    evidence_database: str,
    mixed_target: bool,
) -> None:
    run_migration(evidence_database, "head")
    ids = _seed_draft_fixture(evidence_database, complete_run=False)
    with connect(evidence_database) as connection:
        resource = connection.execute(
            "SELECT resource_id FROM findings WHERE id = %s", (ids["finding_id"],)
        ).fetchone()
        assert resource is not None
        values = _fact_values(ids, resource[0])
        _insert_fact(connection, values)
        if mixed_target:
            # Corruption injection: isolate the AI allowlist from the exact-one guard.
            connection.execute(
                "ALTER TABLE evidence DROP CONSTRAINT ck_evidence_exactly_one_target"
            )
        connection.execute(
            "UPDATE evidence SET ip_source_comparison_fact_id = %s, finding_occurrence_id = %s WHERE id = %s",
            (
                values["id"],
                ids["occurrence_id"] if mixed_target else None,
                ids["evidence_ids"][0],
            ),
        )
        connection.execute(
            "UPDATE governance_runs SET status = 'COMPLETED', completed_at = now() WHERE id = %s",
            (ids["run_id"],),
        )
    with pytest.raises(
        psycopg.errors.RaiseException, match="finding binding scope invalid"
    ):
        with connect(evidence_database) as connection:
            draft_id = _insert_unsealed_draft(
                connection, ids, idempotency_key="comparison-not-allowed"
            )
            _seal_draft(connection, ids, draft_id)
