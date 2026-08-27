import ast
import hashlib
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import CheckConstraint, Engine
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, create_engine, select

from app.core.config import settings
from app.domain.ai_governance_drafts import (
    AiDraftEditedOutput,
    AiDraftModelOutput,
    AiGovernanceDraftCreation,
    AiGovernanceDraftStateError,
    DraftFindingBinding,
    DraftRunnerInputs,
    bind_draft_session,
    create_ai_governance_draft,
    fail_draft,
    load_draft_runner_inputs,
    mark_draft_reviewable,
    reserve_draft_run_identity,
    review_draft,
)
from app.domain.models import (
    AiGovernanceDraft,
    AiGovernanceDraftFindingBinding,
    AiGovernanceDraftReviewDecision,
    GovernanceReport,
)
from tests.migrations.test_schema_history import (
    DEPLOYMENT_TENANT_ID,
    _insert_governance_report,
    _insert_scoped_report_artifacts,
    _seed_stage3_run_facts,
    connect,
    run_migration,
)
from tests.utils.audit import reject_audit_inserts

BACKEND_DIR = Path(__file__).resolve().parents[2]
BINDING_INSERT = "INSERT INTO ai_governance_draft_finding_bindings (id, tenant_id, project_id, governance_run_id, draft_id, finding_id, evidence_id, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, now())"
FUNCTION_REPLACEMENT_MARKERS = {
    "d3e4f5a6b7c8": "NEW.processing_contract_version",
    "e4f5a6b7c8d9": "NEW.report_contract_version",
    "a2b3c4d5e6f7": "OLD.status LIKE 'COMPLETED%'",
}


def _migration_string_assignment(tree: ast.Module, name: str) -> str:
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
        ):
            if isinstance(node.value.value, str):
                return node.value.value
    raise AssertionError(f"migration {name} assignment missing")


def _replaced_function_boundaries() -> tuple[tuple[str, str], ...]:
    boundaries: list[tuple[str, str]] = []
    migration_dir = BACKEND_DIR / "app" / "alembic" / "versions"
    for migration_path in migration_dir.glob("*.py"):
        source = migration_path.read_text(encoding="utf-8")
        if "CREATE OR REPLACE FUNCTION" not in source:
            continue
        tree = ast.parse(source)
        boundaries.append(
            (
                _migration_string_assignment(tree, "revision"),
                _migration_string_assignment(tree, "down_revision"),
            )
        )
    assert boundaries
    return tuple(sorted(boundaries))


# A new replacement boundary must declare the semantic marker its downgrade removes.
_FUNCTION_BOUNDARIES = _replaced_function_boundaries()
assert {revision for revision, _ in _FUNCTION_BOUNDARIES} == set(
    FUNCTION_REPLACEMENT_MARKERS
)
REPLACED_TRIGGER_BOUNDARIES = tuple(
    (revision, predecessor, FUNCTION_REPLACEMENT_MARKERS[revision])
    for revision, predecessor in _FUNCTION_BOUNDARIES
)


def run_downgrade(database: str, revision: str) -> None:
    environment = os.environ.copy()
    environment["POSTGRES_DB"] = database
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", revision],
        cwd=BACKEND_DIR,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def draft_database() -> Iterator[str]:
    database = f"test_ai_draft_{uuid.uuid4().hex}"
    with connect(settings.POSTGRES_DB) as admin_connection:
        admin_connection.autocommit = True
        admin_connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database))
        )

    try:
        run_migration(database, "head")
        yield database
    finally:
        with connect(settings.POSTGRES_DB) as admin_connection:
            admin_connection.autocommit = True
            admin_connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(database)
                )
            )


def _engine(database: str) -> Engine:
    return create_engine(
        URL.create(
            "postgresql+psycopg",
            username=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            host=settings.POSTGRES_SERVER,
            port=settings.POSTGRES_PORT,
            database=database,
        )
    )


@contextmanager
def _session_scope(database: str) -> Iterator[Session]:
    with Session(_engine(database)) as session:
        yield session


def _operate[ResultT](
    database: str, operation: Callable[..., ResultT], **kwargs: Any
) -> ResultT:
    with _session_scope(database) as session:
        return operation(session=session, **kwargs)


def _apply[ResultT](
    database: str,
    operation: Callable[..., ResultT],
    draft: AiGovernanceDraft,
    **kwargs: Any,
) -> ResultT:
    return _operate(database, operation, draft=draft, **kwargs)


def _assert_state_error(
    database: str,
    match: str,
    operation: Callable[..., object],
    draft: AiGovernanceDraft | None = None,
    **kwargs: Any,
) -> None:
    if draft is not None:
        kwargs["draft"] = draft
    with pytest.raises(AiGovernanceDraftStateError, match=match):
        _operate(database, operation, **kwargs)


@contextmanager
def _reject_draft_audits(database: str) -> Iterator[None]:
    with Session(_engine(database)) as session, reject_audit_inserts(session):
        yield


def _fetchone(
    database: str, statement: str, parameters: tuple[Any, ...] = ()
) -> tuple[Any, ...] | None:
    with connect(database) as connection:
        row = connection.execute(statement, parameters).fetchone()
        return None if row is None else tuple(row)


def _fetchall(
    database: str, statement: str, parameters: tuple[Any, ...] = ()
) -> list[tuple[Any, ...]]:
    with connect(database) as connection:
        return [
            tuple(row) for row in connection.execute(statement, parameters).fetchall()
        ]


def _draft_row(
    database: str, draft_id: uuid.UUID, columns: str
) -> tuple[Any, ...] | None:
    return _fetchone(
        database,
        f"SELECT {columns} FROM ai_governance_drafts WHERE id = %s",
        (draft_id,),
    )


def _seed_draft_fixture(
    database: str,
    *,
    identity_suffix: str = "",
    complete_run: bool = True,
) -> dict[str, Any]:
    ids = _seed_stage3_run_facts(
        database,
        complete=False,
        processing_contract_version="ip-v1",
        report_contract_version="deterministic-report-v1",
        identity_suffix=identity_suffix,
    )
    resource_id, finding_id, occurrence_id = (uuid.uuid4() for _ in range(3))
    evidence_id, unplanned_evidence_id = uuid.uuid4(), uuid.uuid4()
    canonical_ip = f"192.0.2.{10 + len(identity_suffix)}"
    project_scope = (DEPLOYMENT_TENANT_ID, ids["project_id"])
    run_scope = (*project_scope, ids["run_id"])
    with connect(database) as connection:
        connection.execute(
            "INSERT INTO resources (id, tenant_id, project_id, resource_type, canonical_key, created_at, updated_at) VALUES (%s, %s, %s, 'IP', %s, now(), now())",
            (resource_id, *project_scope, canonical_ip),
        )
        connection.execute(
            "INSERT INTO findings (id, tenant_id, project_id, resource_id, finding_type, dedupe_key, status, created_at, updated_at) VALUES (%s, %s, %s, %s, 'UNOBSERVED_ASSET', %s, 'OPEN', now(), now())",
            (
                finding_id,
                *project_scope,
                resource_id,
                f"UNOBSERVED_ASSET:{resource_id}",
            ),
        )
        connection.execute(
            "INSERT INTO finding_occurrences (id, tenant_id, project_id, finding_id, governance_run_id, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, now(), now())",
            (occurrence_id, *project_scope, finding_id, ids["run_id"]),
        )
        for snapshot_id in (
            ids["customer_snapshot_id"],
            ids["cloudatlas_snapshot_id"],
        ):
            connection.execute(
                "INSERT INTO finding_occurrence_snapshots (id, tenant_id, project_id, governance_run_id, finding_occurrence_id, source_snapshot_id, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, now(), now())",
                (uuid.uuid4(), *run_scope, occurrence_id, snapshot_id),
            )
    html_artifact_id, csv_artifact_id = _insert_scoped_report_artifacts(database, ids)
    canonical_content = (
        f'{{"schema_version":"deterministic-report-v1","report":{{"report_identity":{{'
        f'"governance_run_id":"{ids["run_id"]}","project_id":"{ids["project_id"]}",'
        '"report_contract_version":"deterministic-report-v1",'
        '"generation_mode":"DETERMINISTIC_TEMPLATE"}},"evidence_plan":{'
        f'"governance_run_id":"{ids["run_id"]}",'
        '"report_contract_version":"deterministic-report-v1","max_entries":50,'
        f'"entries":[{{"coverage":"OPEN_BACKLOG","finding_id":"{finding_id}",'
        f'"finding_type":"UNOBSERVED_ASSET","canonical_ip":"{canonical_ip}",'
        f'"transition_type":null,"evidence_reference":{{"governance_run_id":"{ids["run_id"]}",'
        f'"fact_type":"FINDING_OCCURRENCE","fact_id":"{occurrence_id}"}}}}]}}}}'
    )
    report_id = _insert_governance_report(
        database,
        ids=ids,
        html_artifact_id=html_artifact_id,
        csv_artifact_id=csv_artifact_id,
        canonical_content=canonical_content,
    )
    with connect(database) as connection:
        for values in (
            (evidence_id, *run_scope, report_id, None, occurrence_id),
            (
                unplanned_evidence_id,
                *run_scope,
                report_id,
                ids["customer_snapshot_id"],
                None,
            ),
        ):
            connection.execute(
                "INSERT INTO evidence (id, tenant_id, project_id, governance_run_id, governance_report_id, source_snapshot_id, finding_occurrence_id, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, now(), now())",
                values,
            )
        if complete_run:
            connection.execute(
                "UPDATE governance_runs SET status = 'COMPLETED', "
                "completed_at = now(), updated_at = now() WHERE id = %s",
                (ids["run_id"],),
            )
            connection.execute(
                "UPDATE projects SET latest_completed_run_id = %s WHERE id = %s",
                (ids["run_id"], ids["project_id"]),
            )
    return ids | {
        "report_id": report_id,
        "finding_id": finding_id,
        "occurrence_id": occurrence_id,
        "evidence_ids": (evidence_id,),
        "unplanned_evidence_id": unplanned_evidence_id,
    }


def _create_draft(
    database: str,
    ids: dict[str, Any],
    *,
    idempotency_key: str = "request-key-1",
    finding_override: uuid.UUID | None = None,
    evidence_override: uuid.UUID | None = None,
) -> AiGovernanceDraft:
    return _request_draft(
        database,
        ids,
        idempotency_key=idempotency_key,
        finding_override=finding_override,
        evidence_override=evidence_override,
    ).draft


def _request_draft(
    database: str,
    ids: dict[str, Any],
    *,
    idempotency_key: str = "request-key-1",
    finding_override: uuid.UUID | None = None,
    evidence_override: uuid.UUID | None = None,
    report_override: GovernanceReport | None = None,
    agent_compose_run_id: str | None = None,
) -> AiGovernanceDraftCreation:
    with _session_scope(database) as session:
        report = (
            report_override
            or session.exec(
                select(GovernanceReport).where(GovernanceReport.id == ids["report_id"])
            ).one()
        )
        return create_ai_governance_draft(
            session=session,
            report=report,
            initiated_by="operator-subject",
            idempotency_key=idempotency_key,
            model_identity="customer-model",
            config_fingerprint="a" * 64,
            agent_compose_run_id=agent_compose_run_id,
            bindings=[
                DraftFindingBinding(
                    finding_id=finding_override or ids["finding_id"],
                    evidence_id=evidence_override or ids["evidence_ids"][0],
                )
            ],
        )


def _reviewable_output(
    draft: AiGovernanceDraft, ids: dict[str, Any]
) -> AiDraftModelOutput:
    return AiDraftModelOutput.model_validate(
        {
            "report_sha256": draft.report_sha256,
            "summary": "deterministic report interpretation",
            "recommendations": [
                {
                    "finding_id": str(ids["finding_id"]),
                    "rescan_recommendation": "verify exposure",
                    "pending_verifications": ["owner unknown"],
                    "limitations": ["single observation"],
                    "claims": [
                        {
                            "claim_id": "claim-1",
                            "evidence_ids": [str(ids["evidence_ids"][0])],
                        }
                    ],
                }
            ],
        }
    )


def _bind_draft(database: str, draft: AiGovernanceDraft) -> AiGovernanceDraft:
    return _apply(
        database,
        bind_draft_session,
        draft,
        agent_compose_run_id="b" * 64,
        session_id="c" * 64,
    )


def _make_reviewable(
    database: str, draft: AiGovernanceDraft, ids: dict[str, Any]
) -> AiGovernanceDraft:
    return _apply(
        database,
        mark_draft_reviewable,
        draft,
        model_output=_reviewable_output(draft, ids),
    )


def _review(
    database: str,
    draft: AiGovernanceDraft,
    decision: AiGovernanceDraftReviewDecision,
    edited_output: AiDraftEditedOutput | None = None,
) -> AiGovernanceDraft:
    return _apply(
        database,
        review_draft,
        draft,
        reviewer="operator-subject",
        decision=decision,
        edited_output=edited_output,
    )


def _load_runner_inputs(
    database: str, draft_id: uuid.UUID, session_id: str
) -> DraftRunnerInputs:
    return _operate(
        database,
        load_draft_runner_inputs,
        draft_id=draft_id,
        session_id=session_id,
    )


def _sha256_canonical(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _insert_unsealed_draft(
    connection: psycopg.Connection,
    ids: dict[str, Any],
    *,
    idempotency_key: str,
    draft_id: uuid.UUID | None = None,
    report_id: uuid.UUID | None = None,
    status: str = "GENERATING",
    failure_code: str | None = None,
    model_output: str | None = None,
    generation_terminal: bool = False,
) -> uuid.UUID:
    inserted_id = draft_id or uuid.uuid4()
    connection.execute(
        "INSERT INTO ai_governance_drafts (id, tenant_id, project_id, governance_run_id, governance_report_id, report_sha256, initiated_by, idempotency_key, model_identity, config_fingerprint, status, failure_code, model_output, generation_terminal_at, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, CASE WHEN %s THEN now() END, now(), now())",
        (
            inserted_id,
            DEPLOYMENT_TENANT_ID,
            ids["project_id"],
            ids["run_id"],
            report_id or ids["report_id"],
            "e" * 64,
            "operator-subject",
            idempotency_key,
            "customer-model",
            "a" * 64,
            status,
            failure_code,
            model_output,
            generation_terminal,
        ),
    )
    return inserted_id


def _seal_draft(
    connection: psycopg.Connection,
    ids: dict[str, Any],
    draft_id: uuid.UUID,
    *,
    finding_id: uuid.UUID | None = None,
    evidence_id: uuid.UUID | None = None,
) -> None:
    connection.execute(
        BINDING_INSERT,
        _binding_values(ids, draft_id, finding_id, evidence_id),
    )
    connection.execute(
        "UPDATE ai_governance_drafts SET bindings_sealed_at = now() WHERE id = %s",
        (draft_id,),
    )


def _binding_values(
    ids: dict[str, Any],
    draft_id: uuid.UUID,
    finding_id: uuid.UUID | None = None,
    evidence_id: uuid.UUID | None = None,
) -> tuple[Any, ...]:
    return (
        uuid.uuid4(),
        DEPLOYMENT_TENANT_ID,
        ids["project_id"],
        ids["run_id"],
        draft_id,
        finding_id or ids["finding_id"],
        evidence_id or ids["evidence_ids"][0],
    )


def _insert_run(
    connection: psycopg.Connection, ids: dict[str, Any], session_id: str
) -> None:
    connection.execute(
        "INSERT INTO governance_runs (id, tenant_id, project_id, trigger_id, session_id, requested_by, status, customer_upload_id, customer_upload_sha256, customer_upload_profile_id, customer_upload_profile_version, source_instance_id, cloudatlas_validated_fingerprint, cloudatlas_capset_id, cloudatlas_method, package_sha256, descriptor_sha256, runner_build_version, processing_contract_version, report_contract_version, created_at, updated_at) SELECT %s, tenant_id, project_id, %s, %s, requested_by, 'RUNNING', customer_upload_id, customer_upload_sha256, customer_upload_profile_id, customer_upload_profile_version, source_instance_id, cloudatlas_validated_fingerprint, cloudatlas_capset_id, cloudatlas_method, package_sha256, descriptor_sha256, runner_build_version, processing_contract_version, report_contract_version, now(), now() FROM governance_runs WHERE id = %s",
        (
            uuid.uuid4(),
            f"draft-session-collision-{uuid.uuid4()}",
            session_id,
            ids["run_id"],
        ),
    )


def _insert_sealed_draft(
    connection: psycopg.Connection, ids: dict[str, Any], key: str
) -> None:
    _seal_draft(
        connection, ids, _insert_unsealed_draft(connection, ids, idempotency_key=key)
    )


def _bind_raw_session(
    connection: psycopg.Connection, draft_id: uuid.UUID, session_id: str
) -> None:
    connection.execute(
        "UPDATE ai_governance_drafts SET session_id = %s, agent_compose_run_id = %s WHERE id = %s",
        (session_id, "f" * 64, draft_id),
    )


def _assert_concurrent_lock(
    database: str,
    first: Callable[[psycopg.Connection], object],
    second: Callable[[psycopg.Connection], object],
) -> None:
    with connect(database) as first_connection:
        first(first_connection)
        with pytest.raises(psycopg.errors.LockNotAvailable, match="lock timeout"):
            with connect(database) as second_connection:
                second_connection.execute("SET LOCAL lock_timeout = '250ms'")
                second(second_connection)
    with pytest.raises(psycopg.errors.RaiseException):
        with connect(database) as second_connection:
            second(second_connection)


def _assert_trigger_rejects(
    database: str,
    match: str,
    statement: str,
    parameters: tuple[Any, ...] = (),
) -> None:
    with pytest.raises(psycopg.errors.RaiseException, match=match):
        with connect(database) as connection:
            connection.execute(statement, parameters)


def _relation_exists(database: str, relation: str) -> bool:
    return _fetchone(database, "SELECT to_regclass(%s)", (f"public.{relation}",)) != (
        None,
    )


def _draft_audit_events(database: str, draft_id: uuid.UUID) -> list[tuple[Any, ...]]:
    return _fetchall(
        database,
        "SELECT tenant_id, project_id, actor_subject, actor_type, action, "
        "target_type, target_id, before_data, after_data FROM audit_events "
        "WHERE target_type = 'ai_governance_draft' AND target_id = %s "
        "ORDER BY occurred_at, id",
        (draft_id,),
    )


def _assert_run_pins_immutable(database: str, run_id: uuid.UUID) -> None:
    _assert_trigger_rejects(
        database,
        "pinned facts are immutable",
        "UPDATE governance_runs SET requested_by = %s WHERE id = %s",
        ("tampered", run_id),
    )


def _assert_surviving_finding_evidence_seals(
    database: str, ids: dict[str, Any]
) -> None:
    if _relation_exists(database, "findings"):
        _assert_trigger_rejects(
            database,
            "immutable",
            "UPDATE findings SET dedupe_key = %s WHERE id = %s",
            ("tampered", ids["finding_id"]),
        )
        _assert_trigger_rejects(
            database,
            "immutable",
            "UPDATE finding_occurrences SET finding_id = %s WHERE id = %s",
            (ids["finding_id"], ids["occurrence_id"]),
        )
    if _relation_exists(database, "evidence"):
        evidence_id = ids["evidence_ids"][0]
        _assert_trigger_rejects(
            database,
            "completed",
            "INSERT INTO evidence "
            "(id, tenant_id, project_id, governance_run_id, "
            "governance_report_id, finding_occurrence_id, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, now(), now())",
            (
                uuid.uuid4(),
                DEPLOYMENT_TENANT_ID,
                ids["project_id"],
                ids["run_id"],
                ids["report_id"],
                ids["occurrence_id"],
            ),
        )
        for statement in (
            "UPDATE evidence SET updated_at = now() WHERE id = %s",
            "DELETE FROM evidence WHERE id = %s",
        ):
            _assert_trigger_rejects(database, "completed", statement, (evidence_id,))


def _assert_head_draft_seals(
    database: str, ids: dict[str, Any], draft_id: uuid.UUID
) -> None:
    _assert_trigger_rejects(
        database,
        "immutable",
        "UPDATE ai_governance_drafts SET report_sha256 = %s WHERE id = %s",
        ("e" * 64, draft_id),
    )
    _assert_trigger_rejects(
        database,
        "immutable",
        "UPDATE ai_governance_draft_finding_bindings SET evidence_id = %s "
        "WHERE draft_id = %s",
        (ids["unplanned_evidence_id"], draft_id),
    )
    session_id = draft_id.hex * 2
    with connect(database) as connection:
        _bind_raw_session(connection, draft_id, session_id)
    with pytest.raises(psycopg.errors.RaiseException, match="independent"):
        with connect(database) as connection:
            _insert_run(connection, ids, session_id)


def test_draft_schema_has_no_sensitive_persistence_fields_and_matches_model(
    draft_database: str,
) -> None:
    draft_table = AiGovernanceDraft.__table__  # type: ignore[attr-defined]
    binding_table = AiGovernanceDraftFindingBinding.__table__  # type: ignore[attr-defined]
    model_checks = {
        item.name
        for item in draft_table.constraints
        if isinstance(item, CheckConstraint)
    }
    assert not any(
        isinstance(item, CheckConstraint) for item in binding_table.constraints
    )
    assert {
        row[0]
        for row in _fetchall(
            draft_database,
            "SELECT conname FROM pg_constraint WHERE "
            "conrelid = 'ai_governance_drafts'::regclass AND contype = 'c'",
        )
    } == model_checks
    sensitive = (
        "secret",
        "api_key",
        "credential",
        "token",
        "prompt",
        "provider_event",
        "raw_event",
        "raw_output",
        "raw_payload",
        "model_endpoint",
        "evidence_payload",
    )
    for table_name, model_table in (
        ("ai_governance_drafts", draft_table),
        ("ai_governance_draft_finding_bindings", binding_table),
    ):
        columns = {
            row[0]
            for row in _fetchall(
                draft_database,
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s",
                (table_name,),
            )
        }
        assert columns == {column.name for column in model_table.columns}
        assert all(
            fragment not in column for column in columns for fragment in sensitive
        )
    index = _fetchone(
        draft_database,
        "SELECT indexdef FROM pg_indexes WHERE tablename = 'ai_governance_drafts' "
        "AND indexname = 'uq_ai_governance_drafts_one_active_per_report'",
    )
    assert index is not None and all(
        marker in index[0]
        for marker in (
            "UNIQUE INDEX",
            "(tenant_id, project_id, governance_report_id)",
            "WHERE",
            "status",
            "GENERATING",
        )
    )
    assert _fetchone(
        draft_database,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE "
        "conrelid = 'ai_governance_drafts'::regclass "
        "AND conname = 'uq_ai_governance_drafts_idempotency'",
    ) == ("UNIQUE (tenant_id, project_id, idempotency_key)",)
    scoped_fks = dict(
        _fetchall(
            draft_database,
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE "
            "conrelid IN ('ai_governance_drafts'::regclass, "
            "'ai_governance_draft_finding_bindings'::regclass) AND contype = 'f'",
        )
    )
    assert set(scoped_fks) == {
        "fk_ai_governance_drafts_report_scope",
        "fk_ai_governance_drafts_project_scope",
        "fk_ai_governance_draft_finding_bindings_draft_scope",
        "fk_ai_governance_draft_finding_bindings_finding_scope",
        "fk_ai_governance_draft_finding_bindings_evidence_scope",
    }
    assert all(
        "project_id" in definition and "tenant_id" in definition
        for definition in scoped_fks.values()
    )


def test_draft_pins_inputs_and_enforces_idempotency_and_one_active_generation(
    draft_database: str,
) -> None:
    ids = _seed_draft_fixture(draft_database)
    first_request = _request_draft(draft_database, ids)
    draft = first_request.draft
    assert first_request.created is True
    requested_event = (
        DEPLOYMENT_TENANT_ID,
        ids["project_id"],
        "operator-subject",
        "user",
        "ai_governance_draft.generation_requested",
        "ai_governance_draft",
        draft.id,
        None,
        {
            "governance_report_id": str(ids["report_id"]),
            "status": "GENERATING",
            "finding_count": 1,
        },
    )
    assert _draft_audit_events(draft_database, draft.id) == [requested_event]

    report_row = _fetchone(
        draft_database,
        "SELECT canonical_content FROM governance_reports WHERE id = %s",
        (ids["report_id"],),
    )
    assert report_row is not None
    expected_hash = _sha256_canonical(report_row[0])
    assert _fetchone(
        draft_database,
        "SELECT tenant_id, project_id, governance_run_id, governance_report_id, "
        "report_sha256, initiated_by, idempotency_key, model_identity, "
        "config_fingerprint, status, model_output, review_decision, reviewed_by, "
        "session_id, agent_compose_run_id FROM ai_governance_drafts WHERE id = %s",
        (draft.id,),
    ) == (
        DEPLOYMENT_TENANT_ID,
        ids["project_id"],
        ids["run_id"],
        ids["report_id"],
        expected_hash,
        "operator-subject",
        "request-key-1",
        "customer-model",
        "a" * 64,
        "GENERATING",
        *([None] * 5),
    )
    assert _fetchone(
        draft_database,
        "SELECT bindings_sealed_at IS NOT NULL FROM ai_governance_drafts WHERE id = %s",
        (draft.id,),
    ) == (True,)
    assert _fetchall(
        draft_database,
        "SELECT finding_id, evidence_id FROM ai_governance_draft_finding_bindings "
        "WHERE draft_id = %s ORDER BY evidence_id",
        (draft.id,),
    ) == [(ids["finding_id"], item) for item in sorted(ids["evidence_ids"])]

    replay = _request_draft(draft_database, ids, idempotency_key="request-key-1")
    assert replay.created is False
    assert replay.draft.id == draft.id
    replay_with_changed_binding = _request_draft(
        draft_database,
        ids,
        idempotency_key="request-key-1",
        evidence_override=ids["unplanned_evidence_id"],
    )
    assert replay_with_changed_binding.created is False
    assert replay_with_changed_binding.draft.id == draft.id
    assert _draft_audit_events(draft_database, draft.id) == [requested_event]
    assert _fetchone(
        draft_database,
        "SELECT count(*) FROM ai_governance_drafts WHERE governance_report_id = %s "
        "AND idempotency_key = %s",
        (ids["report_id"], "request-key-1"),
    ) == (1,)

    with pytest.raises(AiGovernanceDraftStateError, match="draft_generation_active"):
        _create_draft(draft_database, ids, idempotency_key="request-key-2")

    other_ids = _seed_draft_fixture(draft_database, identity_suffix="-other")
    with pytest.raises(AiGovernanceDraftStateError, match="evidence_not_bound"):
        _create_draft(
            draft_database,
            other_ids,
            evidence_override=other_ids["unplanned_evidence_id"],
        )
    with pytest.raises(AiGovernanceDraftStateError, match="finding_not_selected"):
        _create_draft(
            draft_database,
            other_ids,
            idempotency_key="request-key-2",
            finding_override=ids["finding_id"],
        )

    other_draft = _create_draft(
        draft_database, other_ids, idempotency_key="request-key-1"
    )
    assert other_draft.id != draft.id
    assert _fetchone(
        draft_database,
        "SELECT count(*) FROM ai_governance_drafts WHERE governance_report_id = %s "
        "AND status = 'GENERATING'",
        (other_ids["report_id"],),
    ) == (1,)

    third_ids = _seed_draft_fixture(draft_database, identity_suffix="-third")
    with pytest.raises(psycopg.errors.RaiseException, match="published report"):
        with connect(draft_database) as connection:
            _insert_unsealed_draft(
                connection,
                ids,
                idempotency_key="cross-project-key",
                report_id=third_ids["report_id"],
            )
    unpublished = _seed_draft_fixture(
        draft_database, identity_suffix="-unpublished", complete_run=False
    )
    with pytest.raises(AiGovernanceDraftStateError, match="report_not_published"):
        _create_draft(draft_database, unpublished)


def test_draft_reserves_launch_identity_before_idempotent_session_binding(
    draft_database: str,
) -> None:
    ids = _seed_draft_fixture(draft_database, identity_suffix="-launch-reservation")
    run_id = "b" * 64
    session_id = "c" * 64
    creation = _request_draft(
        draft_database,
        ids,
        idempotency_key="reserved-launch",
        agent_compose_run_id=run_id,
    )

    assert creation.created is True
    assert creation.draft.agent_compose_run_id == run_id
    assert creation.draft.session_id is None
    bound = _apply(
        draft_database,
        bind_draft_session,
        creation.draft,
        agent_compose_run_id=run_id,
        session_id=session_id,
    )
    rebound = _apply(
        draft_database,
        bind_draft_session,
        creation.draft,
        agent_compose_run_id=run_id,
        session_id=session_id,
    )
    assert rebound.id == bound.id
    assert rebound.agent_compose_run_id == run_id
    assert rebound.session_id == session_id


def test_latest_downgrade_rejects_a_reserved_unbound_launch(
    draft_database: str,
) -> None:
    ids = _seed_draft_fixture(draft_database, identity_suffix="-downgrade-reservation")
    run_id = "b" * 64
    creation = _request_draft(
        draft_database,
        ids,
        idempotency_key="downgrade-reservation",
        agent_compose_run_id=run_id,
    )

    with pytest.raises(subprocess.CalledProcessError) as error:
        run_downgrade(draft_database, "a1b2c3d4e5f6")
    assert "reserved unbound Run identity" in error.value.stderr

    with connect(draft_database) as connection:
        assert connection.execute(
            "SELECT agent_compose_run_id, session_id FROM ai_governance_drafts "
            "WHERE id = %s",
            (creation.draft.id,),
        ).fetchone() == (run_id, None)
        constraint = connection.execute(
            "SELECT pg_get_constraintdef(oid), convalidated FROM pg_constraint "
            "WHERE conrelid = 'ai_governance_drafts'::regclass "
            "AND conname = 'ck_ai_governance_drafts_session_binding'"
        ).fetchone()
    assert constraint is not None
    assert "session_id IS NULL OR agent_compose_run_id IS NOT NULL" in constraint[0]
    assert constraint[1] is True


def test_failed_draft_replays_by_key_and_requires_an_explicit_new_attempt(
    draft_database: str,
) -> None:
    ids = _seed_draft_fixture(draft_database)
    first = _request_draft(draft_database, ids)
    _bind_draft(draft_database, first.draft)
    failed = _apply(
        draft_database, fail_draft, first.draft, failure_code="provider_failed"
    )

    replay = _request_draft(draft_database, ids)
    assert replay.created is False
    assert replay.draft.id == failed.id
    assert replay.draft.status == "FAILED"
    events = _draft_audit_events(draft_database, failed.id)
    assert [event[4] for event in events] == [
        "ai_governance_draft.generation_requested",
        "ai_governance_draft.generation_failed",
    ]
    assert events[-1][2:4] == ("ai-draft-runner", "system")
    assert events[-1][7:] == (
        {"status": "GENERATING"},
        {"status": "FAILED", "failure_code": "provider_failed"},
    )

    explicit_attempt = _request_draft(
        draft_database,
        ids,
        idempotency_key="request-key-2",
    )
    assert explicit_attempt.created is True
    assert explicit_attempt.draft.id != failed.id
    assert explicit_attempt.draft.status == "GENERATING"
    _assert_state_error(
        draft_database,
        "session_identity_reused",
        bind_draft_session,
        explicit_attempt.draft,
        agent_compose_run_id="d" * 64,
        session_id="c" * 64,
    )


def test_mandatory_audit_failure_rolls_back_audited_business_mutations(
    draft_database: str,
) -> None:
    def assert_rollback(
        draft: AiGovernanceDraft,
        mutation: Callable[[], object],
        columns: str,
        expected: tuple[Any, ...],
    ) -> None:
        before = _draft_audit_events(draft_database, draft.id)
        with _reject_draft_audits(draft_database), pytest.raises(SQLAlchemyError):
            mutation()
        assert _draft_row(draft_database, draft.id, columns) == expected
        assert _draft_audit_events(draft_database, draft.id) == before

    ids = _seed_draft_fixture(draft_database)
    with _reject_draft_audits(draft_database), pytest.raises(SQLAlchemyError):
        _request_draft(draft_database, ids)
    assert _fetchone(draft_database, "SELECT count(*) FROM ai_governance_drafts") == (
        0,
    )
    assert _fetchone(
        draft_database,
        "SELECT count(*) FROM audit_events WHERE target_type = 'ai_governance_draft'",
    ) == (0,)

    draft = _create_draft(draft_database, ids)
    _bind_draft(draft_database, draft)
    assert_rollback(
        draft,
        lambda: _make_reviewable(draft_database, draft, ids),
        "status, model_output, generation_terminal_at",
        ("GENERATING", None, None),
    )

    _make_reviewable(draft_database, draft, ids)
    assert_rollback(
        draft,
        lambda: _review(
            draft_database, draft, AiGovernanceDraftReviewDecision.ACCEPTED
        ),
        "review_decision, reviewed_by, reviewed_at",
        (None, None, None),
    )

    failed_candidate = _create_draft(
        draft_database, ids, idempotency_key="audit-failure-at-fail"
    )
    assert_rollback(
        failed_candidate,
        lambda: _apply(
            draft_database, fail_draft, failed_candidate, failure_code="timeout"
        ),
        "status, failure_code, generation_terminal_at",
        ("GENERATING", None, None),
    )

    reserved_candidate = _create_draft(
        draft_database, ids, idempotency_key="audit-failure-at-terminal-binding"
    )
    reserved = _apply(
        draft_database,
        reserve_draft_run_identity,
        reserved_candidate,
        agent_compose_run_id="e" * 64,
    )
    assert_rollback(
        reserved,
        lambda: _apply(
            draft_database,
            fail_draft,
            reserved,
            failure_code="timeout",
            actor_subject="agent-compose-control-plane",
            agent_compose_run_id="e" * 64,
            session_id="f" * 64,
        ),
        "status, failure_code, generation_terminal_at, session_id",
        ("GENERATING", None, None, None),
    )


def test_archived_project_rejects_every_draft_entrypoint(draft_database: str) -> None:
    ids = _seed_draft_fixture(draft_database)
    draft = _create_draft(draft_database, ids)
    _assert_trigger_rejects(
        draft_database,
        "active ai governance draft",
        "UPDATE projects SET archived_at = now() WHERE id = %s",
        (ids["project_id"],),
    )
    _bind_draft(draft_database, draft)
    _make_reviewable(draft_database, draft, ids)
    with connect(draft_database) as connection:
        connection.execute(
            "UPDATE projects SET archived_at = now(), updated_at = now() WHERE id = %s",
            (ids["project_id"],),
        )

    with pytest.raises(AiGovernanceDraftStateError, match="draft_project_archived"):
        _request_draft(draft_database, ids)
    operations: tuple[Callable[[Session], object], ...] = (
        lambda session: bind_draft_session(
            session=session,
            draft=draft,
            agent_compose_run_id="d" * 64,
            session_id="e" * 64,
        ),
        lambda session: mark_draft_reviewable(
            session=session, draft=draft, model_output=_reviewable_output(draft, ids)
        ),
        lambda session: fail_draft(
            session=session, draft=draft, failure_code="timeout"
        ),
        lambda session: review_draft(
            session=session,
            draft=draft,
            reviewer="operator-subject",
            decision=AiGovernanceDraftReviewDecision.ACCEPTED,
        ),
        lambda session: load_draft_runner_inputs(
            session=session, draft_id=draft.id, session_id="c" * 64
        ),
    )
    for operation in operations:
        with (
            _session_scope(draft_database) as session,
            pytest.raises(AiGovernanceDraftStateError, match="draft_project_archived"),
        ):
            operation(session)
    _assert_trigger_rejects(
        draft_database,
        "archived projects are read-only",
        "UPDATE ai_governance_drafts SET updated_at = now() WHERE id = %s",
        (draft.id,),
    )


@pytest.mark.parametrize("first_writer", ("generation", "archive"))
def test_archive_and_generation_share_project_row_serialization(
    draft_database: str, first_writer: str
) -> None:
    ids = _seed_draft_fixture(draft_database)

    def archive(connection: psycopg.Connection) -> None:
        connection.execute(
            "UPDATE projects SET archived_at = now() WHERE id = %s",
            (ids["project_id"],),
        )

    def generate(connection: psycopg.Connection) -> None:
        _insert_unsealed_draft(connection, ids, idempotency_key="concurrent-generation")

    def generate_and_seal(connection: psycopg.Connection) -> None:
        _insert_sealed_draft(connection, ids, "concurrent-generation")

    first, second = (
        (generate_and_seal, archive)
        if first_writer == "generation"
        else (archive, generate)
    )
    _assert_concurrent_lock(draft_database, first, second)


def test_draft_hash_uses_the_persisted_report_not_the_caller_object(
    draft_database: str,
) -> None:
    ids = _seed_draft_fixture(draft_database)
    with _session_scope(draft_database) as session:
        persisted = session.exec(
            select(GovernanceReport).where(GovernanceReport.id == ids["report_id"])
        ).one()
        values = persisted.model_dump()
    values["canonical_content"] = {"forged": "caller-controlled"}
    forged = GovernanceReport.model_validate(values)

    draft = _request_draft(
        draft_database,
        ids,
        report_override=forged,
    ).draft

    with connect(draft_database) as connection:
        canonical_content = connection.execute(
            "SELECT canonical_content FROM governance_reports WHERE id = %s",
            (ids["report_id"],),
        ).fetchone()
    assert canonical_content is not None
    assert draft.report_sha256 == _sha256_canonical(canonical_content[0])
    assert draft.report_sha256 != _sha256_canonical(values["canonical_content"])


@pytest.mark.parametrize("initial_status", ["REVIEWABLE", "FAILED"])
def test_database_rejects_a_draft_created_in_a_terminal_generation_state(
    draft_database: str,
    initial_status: str,
) -> None:
    ids = _seed_draft_fixture(draft_database)
    model_output = "{}" if initial_status == "REVIEWABLE" else None
    failure_code = "provider_failed" if initial_status == "FAILED" else None

    with pytest.raises(psycopg.errors.RaiseException, match="start in GENERATING"):
        with connect(draft_database) as connection:
            _insert_unsealed_draft(
                connection,
                ids,
                idempotency_key=f"invalid-initial-{initial_status.lower()}",
                status=initial_status,
                failure_code=failure_code,
                model_output=model_output,
                generation_terminal=True,
            )


def test_database_rejects_generation_to_review_terminal_shortcut(
    draft_database: str,
) -> None:
    ids = _seed_draft_fixture(draft_database)
    draft = _create_draft(draft_database, ids)

    _assert_trigger_rejects(
        draft_database,
        "separate transition",
        "UPDATE ai_governance_drafts SET status = 'REVIEWABLE', session_id = %s, "
        "agent_compose_run_id = %s, model_output = %s::jsonb, "
        "generation_terminal_at = now(), review_decision = 'ACCEPTED', "
        "reviewed_by = 'operator-subject', reviewed_at = now() WHERE id = %s",
        (
            "c" * 64,
            "b" * 64,
            json.dumps(_reviewable_output(draft, ids).model_dump()),
            draft.id,
        ),
    )


def test_database_requires_complete_session_binding(draft_database: str) -> None:
    ids = _seed_draft_fixture(draft_database)
    draft = _create_draft(draft_database, ids)
    with connect(draft_database) as connection:
        governance_session_id = connection.execute(
            "SELECT session_id FROM governance_runs WHERE id = %s",
            (ids["run_id"],),
        ).fetchone()
    assert governance_session_id is not None

    _assert_trigger_rejects(
        draft_database,
        "independent",
        "UPDATE ai_governance_drafts SET session_id = %s, "
        "agent_compose_run_id = %s WHERE id = %s",
        (governance_session_id[0], "b" * 64, draft.id),
    )

    with pytest.raises(
        psycopg.errors.CheckViolation,
        match="ck_ai_governance_drafts_session_binding",
    ):
        with connect(draft_database) as connection:
            connection.execute(
                "UPDATE ai_governance_drafts SET session_id = %s WHERE id = %s",
                ("c" * 64, draft.id),
            )


def test_database_rejects_draft_first_session_reuse(draft_database: str) -> None:
    ids = _seed_draft_fixture(draft_database)
    draft = _create_draft(draft_database, ids)
    draft_session_id = "d" * 64
    with connect(draft_database) as connection:
        connection.execute(
            "UPDATE ai_governance_drafts SET session_id = %s, "
            "agent_compose_run_id = %s WHERE id = %s",
            (draft_session_id, "e" * 64, draft.id),
        )

    with pytest.raises(psycopg.errors.RaiseException, match="independent"):
        with connect(draft_database) as connection:
            _insert_run(connection, ids, draft_session_id)


@pytest.mark.parametrize("first_writer", ("run", "draft"))
def test_database_serializes_concurrent_session_reuse(
    draft_database: str, first_writer: str
) -> None:
    ids = _seed_draft_fixture(draft_database)
    draft = _create_draft(draft_database, ids)
    shared_session_id = "f" * 64

    def run(connection: psycopg.Connection) -> None:
        _insert_run(connection, ids, shared_session_id)

    def bind(connection: psycopg.Connection) -> None:
        _bind_raw_session(connection, draft.id, shared_session_id)

    first, second = (run, bind) if first_writer == "run" else (bind, run)
    _assert_concurrent_lock(draft_database, first, second)


def test_database_rejects_evidence_bound_to_the_wrong_finding(
    draft_database: str,
) -> None:
    ids = _seed_draft_fixture(draft_database)
    missing_binding_draft_id = uuid.uuid4()
    with pytest.raises(psycopg.errors.RaiseException, match="requires 1 to 8"):
        with connect(draft_database) as connection:
            _insert_unsealed_draft(
                connection,
                ids,
                draft_id=missing_binding_draft_id,
                idempotency_key="missing-bindings",
            )
            connection.execute(
                "UPDATE ai_governance_drafts SET bindings_sealed_at = now() WHERE id = %s",
                (missing_binding_draft_id,),
            )
    draft_id = uuid.uuid4()
    other_resource_id = uuid.uuid4()
    other_finding_id = uuid.uuid4()

    with connect(draft_database) as connection:
        connection.execute(
            "INSERT INTO resources "
            "(id, tenant_id, project_id, resource_type, canonical_key, created_at, "
            "updated_at) VALUES (%s, %s, %s, 'IP', '192.0.2.250', now(), now())",
            (other_resource_id, DEPLOYMENT_TENANT_ID, ids["project_id"]),
        )
        connection.execute(
            "INSERT INTO findings "
            "(id, tenant_id, project_id, resource_id, finding_type, dedupe_key, "
            "status, created_at, updated_at) VALUES (%s, %s, %s, %s, "
            "'UNOBSERVED_ASSET', %s, 'OPEN', now(), now())",
            (
                other_finding_id,
                DEPLOYMENT_TENANT_ID,
                ids["project_id"],
                other_resource_id,
                f"UNOBSERVED_ASSET:{other_resource_id}",
            ),
        )

    with pytest.raises(psycopg.errors.RaiseException, match="binding scope invalid"):
        with connect(draft_database) as connection:
            _insert_unsealed_draft(
                connection,
                ids,
                draft_id=draft_id,
                idempotency_key="wrong-finding-binding",
            )
            _seal_draft(connection, ids, draft_id, finding_id=other_finding_id)


def test_guarded_transitions_and_terminal_immutability(draft_database: str) -> None:
    ids = _seed_draft_fixture(draft_database)
    draft = _create_draft(draft_database, ids)
    _assert_trigger_rejects(
        draft_database,
        "sealed",
        BINDING_INSERT,
        _binding_values(ids, draft.id, evidence_id=ids["unplanned_evidence_id"]),
    )
    _assert_trigger_rejects(
        draft_database,
        "seal is immutable",
        "UPDATE ai_governance_drafts SET bindings_sealed_at = bindings_sealed_at + interval '1 second' WHERE id = %s",
        (draft.id,),
    )

    _assert_state_error(
        draft_database,
        "session_not_bound",
        mark_draft_reviewable,
        draft,
        model_output=_reviewable_output(draft, ids),
    )

    with connect(draft_database) as connection:
        _insert_run(connection, ids, "f" * 64)
    _assert_state_error(
        draft_database,
        "session_identity_reused",
        bind_draft_session,
        draft,
        agent_compose_run_id="b" * 64,
        session_id="f" * 64,
    )

    bound = _bind_draft(draft_database, draft)
    assert bound.session_id == "c" * 64
    assert bound.agent_compose_run_id == "b" * 64

    _assert_state_error(
        draft_database,
        "session_already_bound",
        bind_draft_session,
        draft,
        agent_compose_run_id="d" * 64,
        session_id="e" * 64,
    )

    mismatched_output = _reviewable_output(draft, ids)
    mismatched_output.report_sha256 = "f" * 64
    _assert_state_error(
        draft_database,
        "report_mismatch",
        mark_draft_reviewable,
        draft,
        model_output=mismatched_output,
    )

    reviewable = _make_reviewable(draft_database, draft, ids)
    assert reviewable.status == "REVIEWABLE"
    assert reviewable.model_output is not None
    _assert_trigger_rejects(
        draft_database,
        "reviewable draft facts are immutable",
        "UPDATE ai_governance_drafts SET model_output = %s::jsonb WHERE id = %s",
        ('{"tampered": true}', draft.id),
    )

    _assert_state_error(
        draft_database,
        "draft_not_generating",
        fail_draft,
        draft,
        failure_code="timeout",
    )

    _assert_state_error(
        draft_database,
        "review_requires_edited_output",
        review_draft,
        draft,
        reviewer="operator-subject",
        decision=AiGovernanceDraftReviewDecision.EDITED,
    )

    accepted = _review(draft_database, draft, AiGovernanceDraftReviewDecision.ACCEPTED)
    assert accepted.review_decision == "ACCEPTED"
    assert accepted.reviewed_by == "operator-subject"
    assert accepted.operator_edited_output is None
    events = _draft_audit_events(draft_database, draft.id)
    assert [event[4] for event in events] == [
        "ai_governance_draft.generation_requested",
        "ai_governance_draft.generation_succeeded",
        "ai_governance_draft.reviewed",
    ]
    assert events[-1] == (
        DEPLOYMENT_TENANT_ID,
        ids["project_id"],
        "operator-subject",
        "user",
        "ai_governance_draft.reviewed",
        "ai_governance_draft",
        draft.id,
        {"review_decision": None},
        {"review_decision": "ACCEPTED"},
    )
    audit_snapshots = json.dumps([event[7:] for event in events]).lower()
    assert not any(
        fragment in audit_snapshots
        for fragment in (
            "secret",
            "prompt",
            "provider",
            "evidence",
            "model_output",
            "operator_edited_output",
        )
    )

    _assert_state_error(
        draft_database,
        "draft_already_reviewed",
        review_draft,
        draft,
        reviewer="operator-subject",
        decision=AiGovernanceDraftReviewDecision.REJECTED,
    )

    terminal_mutations = (
        ("report_sha256 = %s", "e" * 64),
        ("status = %s", "FAILED"),
        ("model_output = %s::jsonb", '{"tampered": true}'),
        ("review_decision = %s", "REJECTED"),
        ("session_id = %s", "d" * 64),
        ("operator_edited_output = %s::jsonb", '{"smuggled": true}'),
    )
    for assignment, value in terminal_mutations:
        _assert_trigger_rejects(
            draft_database,
            "immutable",
            f"UPDATE ai_governance_drafts SET {assignment} WHERE id = %s",
            (value, draft.id),
        )


def test_failed_draft_is_terminal_and_keeps_bindings_sealed(
    draft_database: str,
) -> None:
    ids = _seed_draft_fixture(draft_database)
    draft = _create_draft(draft_database, ids)
    with pytest.raises(
        psycopg.errors.CheckViolation,
        match="ck_ai_governance_drafts_failure_code",
    ):
        with connect(draft_database) as connection:
            connection.execute(
                "UPDATE ai_governance_drafts SET status = 'FAILED', failure_code = 'Provider said: raw event payload', generation_terminal_at = now() WHERE id = %s",
                (draft.id,),
            )

    failed = _apply(draft_database, fail_draft, draft, failure_code="timeout")
    assert failed.status == "FAILED"
    assert failed.failure_code == "timeout"
    assert failed.model_output is None

    _assert_state_error(
        draft_database,
        "draft_not_generating",
        bind_draft_session,
        draft,
        agent_compose_run_id="b" * 64,
        session_id="c" * 64,
    )
    _assert_state_error(
        draft_database,
        "draft_not_reviewable",
        review_draft,
        draft,
        reviewer="operator-subject",
        decision=AiGovernanceDraftReviewDecision.REJECTED,
    )

    _assert_trigger_rejects(
        draft_database,
        "sealed",
        BINDING_INSERT,
        _binding_values(ids, draft.id),
    )
    for match, statement, parameters in (
        (
            "immutable",
            "DELETE FROM ai_governance_draft_finding_bindings WHERE draft_id = %s",
            (draft.id,),
        ),
        (
            "immutable",
            "UPDATE ai_governance_draft_finding_bindings SET evidence_id = %s "
            "WHERE draft_id = %s",
            (ids["unplanned_evidence_id"], draft.id),
        ),
        (
            "immutable history",
            "DELETE FROM ai_governance_drafts WHERE id = %s",
            (draft.id,),
        ),
    ):
        _assert_trigger_rejects(draft_database, match, statement, parameters)


def test_edited_review_is_separate_operator_text_and_immutable_model_output(
    draft_database: str,
) -> None:
    ids = _seed_draft_fixture(draft_database)
    draft = _create_draft(draft_database, ids)
    _bind_draft(draft_database, draft)
    model_output = _reviewable_output(draft, ids)
    _make_reviewable(draft_database, draft, ids)

    edited = AiDraftEditedOutput.model_validate(
        {
            "findings": [
                {
                    "finding_id": str(ids["finding_id"]),
                    "rescan_recommendation": "operator-rewritten recommendation",
                    "pending_verifications": ["operator pending item"],
                    "limitations": ["operator limitation"],
                }
            ]
        }
    )
    reviewed = _review(
        draft_database, draft, AiGovernanceDraftReviewDecision.EDITED, edited
    )
    assert reviewed.review_decision == "EDITED"
    assert reviewed.operator_edited_output == {
        "findings": [
            {
                "finding_id": str(ids["finding_id"]),
                "rescan_recommendation": "operator-rewritten recommendation",
                "pending_verifications": ["operator pending item"],
                "limitations": ["operator limitation"],
            }
        ]
    }

    with connect(draft_database) as connection:
        row = connection.execute(
            "SELECT model_output, operator_edited_output, review_decision "
            "FROM ai_governance_drafts WHERE id = %s",
            (draft.id,),
        ).fetchone()
        assert row is not None
        assert row[0] == model_output.model_dump()
        assert row[1] == reviewed.operator_edited_output
        assert row[2] == "EDITED"


def test_transitions_leave_run_report_and_finding_facts_unchanged(
    draft_database: str,
) -> None:
    ids = _seed_draft_fixture(draft_database)

    def snapshot() -> dict[str, list[tuple[Any, ...]]]:
        with connect(draft_database) as connection:
            return {
                table: connection.execute(
                    f"SELECT * FROM {table} ORDER BY id"
                ).fetchall()
                for table in (
                    "projects",
                    "governance_runs",
                    "governance_reports",
                    "findings",
                    "evidence",
                    "finding_occurrences",
                    "finding_transitions",
                )
            }

    before = snapshot()
    draft = _create_draft(draft_database, ids)
    _bind_draft(draft_database, draft)
    _make_reviewable(draft_database, draft, ids)
    _review(draft_database, draft, AiGovernanceDraftReviewDecision.REJECTED)
    assert snapshot() == before

    failed_draft = _create_draft(draft_database, ids, idempotency_key="request-key-2")
    _apply(draft_database, fail_draft, failed_draft, failure_code="timeout")
    assert snapshot() == before


def test_runner_handoff_reloads_bounded_input_and_rejects_mismatches(
    draft_database: str,
) -> None:
    ids = _seed_draft_fixture(draft_database)
    draft = _create_draft(draft_database, ids)

    with pytest.raises(AiGovernanceDraftStateError, match="session_mismatch"):
        _load_runner_inputs(draft_database, draft.id, "c" * 64)

    bound = _bind_draft(draft_database, draft)
    assert bound.session_id == "c" * 64

    inputs = _load_runner_inputs(draft_database, draft.id, "c" * 64)
    assert inputs.draft_id == draft.id
    assert inputs.project_id == ids["project_id"]
    assert inputs.governance_report_id == ids["report_id"]
    assert inputs.governance_run_id == ids["run_id"]
    assert inputs.model_identity == "customer-model"
    assert inputs.config_fingerprint == "a" * 64
    assert len(inputs.findings) == 1
    finding_input = inputs.findings[0]
    assert finding_input.finding_id == ids["finding_id"]
    assert finding_input.finding_type == "UNOBSERVED_ASSET"
    assert finding_input.canonical_ip.startswith("192.0.2.")
    assert finding_input.coverage == "OPEN_BACKLOG"
    assert finding_input.transition_type is None
    assert {reference.fact_id for reference in finding_input.evidence} == {
        ids["occurrence_id"]
    }
    assert {reference.fact_type for reference in finding_input.evidence} == {
        "FINDING_OCCURRENCE"
    }

    with pytest.raises(AiGovernanceDraftStateError, match="session_mismatch"):
        _load_runner_inputs(draft_database, draft.id, "d" * 64)
    with pytest.raises(AiGovernanceDraftStateError, match="draft_not_found"):
        _load_runner_inputs(draft_database, uuid.uuid4(), "c" * 64)

    _apply(draft_database, fail_draft, draft, failure_code="timeout")
    with pytest.raises(AiGovernanceDraftStateError, match="draft_not_generating"):
        _load_runner_inputs(draft_database, draft.id, "c" * 64)


def _run_draft_runner(
    database: str,
    *,
    draft_id: uuid.UUID,
    agent_compose_run_id: str,
    session_id: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "POSTGRES_DB": database,
            "POSTGRES_SERVER": settings.POSTGRES_SERVER,
            "POSTGRES_PORT": str(settings.POSTGRES_PORT),
            "POSTGRES_USER": settings.POSTGRES_USER,
            "POSTGRES_PASSWORD": settings.POSTGRES_PASSWORD,
            "AI_DRAFT_ID": str(draft_id),
            "AI_DRAFT_RUN_ID": agent_compose_run_id,
            "SANDBOX_ID": session_id,
            "LLM_API_KEY": "sensitive-model-secret",
            "PROMPT_TEXT": "complete-prompt-material",
            "EVIDENCE_PAYLOAD": "raw-evidence-payload",
            "PROVIDER_EVENT": "raw-provider-event",
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "app.ai_draft_runner"],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_draft_runner_starts_with_only_draft_identity_and_handles_mismatches(
    draft_database: str,
) -> None:
    ids = _seed_draft_fixture(draft_database)
    run_id = "b" * 64
    draft = _request_draft(
        draft_database,
        ids,
        idempotency_key="runner-reservation",
        agent_compose_run_id=run_id,
    ).draft

    completed = _run_draft_runner(
        draft_database,
        draft_id=draft.id,
        agent_compose_run_id=run_id,
        session_id="c" * 64,
    )
    assert completed.returncode == 0, completed.stderr
    for sensitive_material in (
        "sensitive-model-secret",
        "complete-prompt-material",
        "raw-evidence-payload",
        "raw-provider-event",
    ):
        assert sensitive_material not in completed.stdout
        assert sensitive_material not in completed.stderr
    payload = json.loads(completed.stdout.strip())
    assert payload["draft_id"] == str(draft.id)
    assert payload["governance_report_id"] == str(ids["report_id"])
    assert payload["findings"][0]["finding_id"] == str(ids["finding_id"])
    assert payload["findings"][0]["finding_type"] == "UNOBSERVED_ASSET"
    assert payload["findings"][0]["coverage"] == "OPEN_BACKLOG"
    assert payload["findings"][0]["transition_type"] is None
    assert payload["findings"][0]["evidence"][0]["fact_type"] == "FINDING_OCCURRENCE"

    for failed in (
        _run_draft_runner(
            draft_database,
            draft_id=draft.id,
            agent_compose_run_id=run_id,
            session_id="d" * 64,
        ),
        _run_draft_runner(
            draft_database,
            draft_id=uuid.uuid4(),
            agent_compose_run_id=run_id,
            session_id="c" * 64,
        ),
    ):
        assert failed.returncode == 1
        assert "sensitive-model-secret" not in failed.stdout
        assert "sensitive-model-secret" not in failed.stderr


@pytest.mark.parametrize(
    ("boundary_revision", "predecessor_revision", "boundary_marker"),
    REPLACED_TRIGGER_BOUNDARIES,
)
def test_migration_chain_restores_replaced_triggers_and_keeps_findings_sealed(
    draft_database: str,
    boundary_revision: str,
    predecessor_revision: str,
    boundary_marker: str,
) -> None:
    ids = _seed_draft_fixture(draft_database, complete_run=True)
    draft = _create_draft(draft_database, ids)
    running_ids = _seed_stage3_run_facts(
        draft_database,
        complete=False,
        processing_contract_version="ip-v1",
        report_contract_version="deterministic-report-v1",
        identity_suffix=f"-boundary-{boundary_revision}",
    )

    def assert_revision(revision: str) -> None:
        with connect(draft_database) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == (revision,)

    def governance_run_protection() -> str:
        with connect(draft_database) as connection:
            row = connection.execute(
                "SELECT pg_get_functiondef("
                "'protect_governance_run_facts()'::regprocedure)"
            ).fetchone()
        assert row is not None
        return str(row[0])

    def assert_legacy_schema_protections() -> None:
        _assert_run_pins_immutable(draft_database, running_ids["run_id"])
        _assert_surviving_finding_evidence_seals(draft_database, ids)
        with connect(draft_database) as connection:
            assert connection.execute(
                "SELECT to_regclass('public.ai_governance_drafts'), "
                "to_regclass('public.ai_governance_draft_finding_bindings')"
            ).fetchone() == (None, None)

    _assert_run_pins_immutable(draft_database, running_ids["run_id"])
    _assert_surviving_finding_evidence_seals(draft_database, ids)
    _assert_head_draft_seals(draft_database, ids, draft.id)

    run_downgrade(draft_database, boundary_revision)
    assert_revision(boundary_revision)
    assert boundary_marker in governance_run_protection()
    assert_legacy_schema_protections()

    run_downgrade(draft_database, predecessor_revision)
    assert_revision(predecessor_revision)
    assert boundary_marker not in governance_run_protection()
    assert_legacy_schema_protections()

    run_migration(draft_database, "head")
    assert_revision("b2c3d4e5f6a7")

    fresh_ids = _seed_draft_fixture(
        draft_database, identity_suffix="-fresh", complete_run=True
    )
    fresh_draft = _create_draft(draft_database, fresh_ids, idempotency_key="fresh-key")
    _assert_run_pins_immutable(draft_database, running_ids["run_id"])
    _assert_surviving_finding_evidence_seals(draft_database, fresh_ids)
    _assert_head_draft_seals(draft_database, fresh_ids, fresh_draft.id)
