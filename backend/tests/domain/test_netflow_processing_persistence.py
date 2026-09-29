"""Real PostgreSQL guards, exercised without the NetFlow application services."""

import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from app.core.db import engine
from app.core.time import get_datetime_utc
from app.domain.customer_upload_profiles import (
    default_customer_upload_profile_definition,
)
from app.domain.models import (
    DEPLOYMENT_TENANT_ID,
    Artifact,
    CustomerUploadProfile,
    NetFlowDataset,
    Project,
    Tenant,
)
from app.domain.netflow_models import (
    NetFlowAnalysis,
    NetFlowContextRevision,
    NetFlowFeedbackRevision,
    SourceCorrelationRevision,
)
from app.models import User


@pytest.fixture
def reservation() -> Iterator[tuple[Session, NetFlowAnalysis]]:
    # The domain conftest intentionally has no shared DB session. Roll back this
    # entire private transaction, including immutable rows, without disabling guards.
    with engine.connect() as connection, connection.begin():
        with Session(bind=connection) as session:
            tenant = session.get(Tenant, DEPLOYMENT_TENANT_ID)
            if tenant is None:
                tenant = Tenant()
                session.add(tenant)
            actor = User(
                email=f"nf-guards-{uuid.uuid4()}@example.com", hashed_password="unused"
            )
            session.add(actor)
            session.flush()
            profile_id = uuid.uuid4()
            project = Project(
                tenant_id=tenant.id,
                name="Synthetic NetFlow guards",
                current_customer_upload_profile_id=profile_id,
            )
            session.add(project)
            session.flush()
            session.add(
                CustomerUploadProfile(
                    id=profile_id,
                    tenant_id=tenant.id,
                    project_id=project.id,
                    version=1,
                    definition=default_customer_upload_profile_definition().model_dump(),
                )
            )
            artifacts = [
                Artifact(
                    tenant_id=tenant.id,
                    project_id=project.id,
                    storage_key=f"synthetic/{uuid.uuid4()}",
                    media_type="text/csv",
                    byte_size=1,
                    sha256=digest * 64,
                )
                for digest in ("a", "b")
            ]
            session.add_all(artifacts)
            session.flush()
            dataset = NetFlowDataset(
                tenant_id=tenant.id,
                project_id=project.id,
                raw_artifact_id=artifacts[0].id,
                normalized_artifact_id=artifacts[1].id,
                display_filename="synthetic.csv",
                raw_sha256="a" * 64,
                normalized_sha256="b" * 64,
                dataset_contract_version="netflow-dataset-v1",
                schema_fingerprint="c" * 64,
                encoding="utf-8-sig",
                byte_size=1,
                raw_record_count=1,
                activity_valid_record_count=1,
                isolated_record_count=0,
                duplicate_group_count=0,
                duplicate_record_count=0,
            )
            session.add(dataset)
            session.flush()
            context = NetFlowContextRevision(
                tenant_id=tenant.id,
                project_id=project.id,
                dataset_id=dataset.id,
                revision=1,
                network_namespace="synthetic-guards",
                state="CONFIRMED",
                raw_sha256=dataset.raw_sha256,
                normalized_sha256=dataset.normalized_sha256,
                payload={"test_fixture": True},
                created_by=actor.id,
                operation_key="context-one",
                request_sha256="d" * 64,
            )
            session.add(context)
            session.flush()
            analysis = NetFlowAnalysis(
                tenant_id=tenant.id,
                project_id=project.id,
                dataset_id=dataset.id,
                context_revision_id=context.id,
                network_namespace=context.network_namespace,
                processing_identity_sha256="e" * 64,
                identity={"config": "rules", "fixture": True},
                request={"operation": "process"},
                quality={"raw_record_count": 1},
                test_fixture=True,
                created_by=actor.id,
                agent_run_id="f" * 64,
                agent_project_id="0" * 64,
                runner_build_version="synthetic",
            )
            session.add(analysis)
            session.flush()
            yield session, analysis
            session.rollback()


def _initial(analysis: NetFlowAnalysis) -> NetFlowFeedbackRevision:
    return NetFlowFeedbackRevision(
        tenant_id=analysis.tenant_id,
        project_id=analysis.project_id,
        analysis_id=analysis.id,
        revision=1,
        system_generated=True,
        artifact_manifest={"root": "synthetic/initial", "files": {}},
    )


def _running(session: Session, analysis: NetFlowAnalysis) -> None:
    analysis.status = "RUNNING"
    analysis.session_id = "synthetic-session"
    analysis.started_at = get_datetime_utc()
    session.add(analysis)
    session.flush()


def _retry(parent: NetFlowAnalysis) -> NetFlowAnalysis:
    return NetFlowAnalysis(
        tenant_id=parent.tenant_id,
        project_id=parent.project_id,
        dataset_id=parent.dataset_id,
        context_revision_id=parent.context_revision_id,
        network_namespace=parent.network_namespace,
        processing_identity_sha256=parent.processing_identity_sha256,
        identity=parent.identity,
        request={"operation": "process", "retry_of_analysis_id": str(parent.id)},
        quality=parent.quality,
        test_fixture=parent.test_fixture,
        created_by=parent.created_by,
        retry_of_analysis_id=parent.id,
        agent_run_id=uuid.uuid4().hex * 2,
        agent_project_id=parent.agent_project_id,
        runner_build_version=parent.runner_build_version,
    )


def test_initial_and_imported_feedback_publish_atomically(
    reservation: tuple[Session, NetFlowAnalysis],
) -> None:
    session, analysis = reservation
    _running(session, analysis)
    initial = _initial(analysis)
    session.add(initial)
    session.flush()  # Analysis is still RUNNING: publication guard must be deferred.
    imported = NetFlowFeedbackRevision(
        tenant_id=analysis.tenant_id,
        project_id=analysis.project_id,
        analysis_id=analysis.id,
        parent_id=initial.id,
        revision=2,
        created_by=analysis.created_by,
        artifact_manifest={"root": "synthetic/imported", "files": {}},
        provider_claim={"origin": "imported", "responses": []},
    )
    session.add(imported)
    session.flush()
    analysis.status = "SUCCEEDED"
    analysis.completed_at = get_datetime_utc()
    analysis.result = {"manifest": {"status": "success", "test_fixture": True}}
    analysis.initial_feedback_revision_id = initial.id
    session.add(analysis)
    session.flush()
    connection = session.connection()
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    rows = (
        connection.execute(
            text("""
        SELECT a.status, a.initial_feedback_revision_id, f.revision, f.created_by,
               f.provider_claim IS NULL AS claim_is_sql_null
        FROM netflow_analyses a JOIN netflow_feedback_revisions f ON f.analysis_id = a.id
        WHERE a.id = :id ORDER BY f.revision
    """),
            {"id": analysis.id},
        )
        .tuples()
        .all()
    )
    assert rows == [
        ("SUCCEEDED", initial.id, 1, None, True),
        ("SUCCEEDED", initial.id, 2, analysis.created_by, False),
    ]
    with (
        pytest.raises(DBAPIError, match="terminal analysis is immutable"),
        session.begin_nested(),
    ):
        session.connection().execute(
            text("UPDATE netflow_analyses SET result = '{}'::jsonb WHERE id = :id"),
            {"id": analysis.id},
        )
    with (
        pytest.raises(DBAPIError, match="feedback revision chain"),
        session.begin_nested(),
    ):
        session.add(
            NetFlowFeedbackRevision(
                tenant_id=analysis.tenant_id,
                project_id=analysis.project_id,
                analysis_id=analysis.id,
                parent_id=imported.id,
                revision=3,
                artifact_manifest={},
            )
        )
        session.flush()
    for statement in (
        "UPDATE netflow_feedback_revisions SET human_note = 'rewritten' WHERE id = :id",
        "DELETE FROM netflow_feedback_revisions WHERE id = :id",
    ):
        with (
            pytest.raises(DBAPIError, match="revisions are immutable"),
            session.begin_nested(),
        ):
            session.connection().execute(text(statement), {"id": imported.id})


def test_unpublished_feedback_cannot_survive_commit_boundary(
    reservation: tuple[Session, NetFlowAnalysis],
) -> None:
    session, analysis = reservation
    with (
        pytest.raises(DBAPIError, match="feedback requires a published analysis"),
        session.begin_nested(),
    ):
        session.add(_initial(analysis))
        session.flush()
        session.connection().execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert (
        session.connection().scalar(
            text(
                "SELECT count(*) FROM netflow_feedback_revisions WHERE analysis_id = :id"
            ),
            {"id": analysis.id},
        )
        == 0
    )
    with (
        pytest.raises(DBAPIError, match="initial feedback must be system blank"),
        session.begin_nested(),
    ):
        initial = _initial(analysis)
        initial.system_generated = False
        initial.created_by = analysis.created_by
        session.add(initial)
        session.flush()


@pytest.mark.parametrize(
    "assignment",
    [
        "identity = '{}'::jsonb",
        "request = '{}'::jsonb",
        "quality = '{}'::jsonb",
        "runner_build_version = 'other'",
        "agent_run_id = repeat('1', 64)",
        "created_by = NULL",
        "processing_identity_sha256 = repeat('2', 64)",
    ],
)
def test_fixed_analysis_fields_cannot_be_rewritten(
    reservation: tuple[Session, NetFlowAnalysis], assignment: str
) -> None:
    session, analysis = reservation
    with (
        pytest.raises(DBAPIError, match="analysis identity is immutable"),
        session.begin_nested(),
    ):
        session.connection().execute(
            text(f"UPDATE netflow_analyses SET {assignment} WHERE id = :id"),
            {"id": analysis.id},
        )


def test_execution_binding_and_failed_retry_are_irreversible(
    reservation: tuple[Session, NetFlowAnalysis],
) -> None:
    session, analysis = reservation
    _running(session, analysis)
    connection = session.connection()
    for assignment in (
        "session_id = 'another-session'",
        "started_at = started_at + interval '1 second'",
    ):
        with (
            pytest.raises(DBAPIError, match="execution binding is immutable"),
            session.begin_nested(),
        ):
            session.connection().execute(
                text(f"UPDATE netflow_analyses SET {assignment} WHERE id = :id"),
                {"id": analysis.id},
            )
    with (
        pytest.raises(DBAPIError, match="terminal failed identity"),
        session.begin_nested(),
    ):
        session.add(_retry(analysis))
        session.flush()
    analysis.status = "FAILED"
    analysis.error_code = "netflow_execution_unavailable"
    analysis.completed_at = get_datetime_utc()
    session.add(analysis)
    session.flush()
    with (
        pytest.raises(DBAPIError, match="terminal failed identity"),
        session.begin_nested(),
    ):
        session.add(_retry(analysis))
        session.flush()
    analysis.terminal_confirmed = True
    session.add(analysis)
    session.flush()
    with (
        pytest.raises(DBAPIError, match="execution binding is immutable"),
        session.begin_nested(),
    ):
        session.connection().execute(
            text(
                "UPDATE netflow_analyses SET terminal_confirmed = false WHERE id = :id"
            ),
            {"id": analysis.id},
        )
    with (
        pytest.raises(DBAPIError, match="terminal analysis is immutable"),
        session.begin_nested(),
    ):
        session.connection().execute(
            text(
                "UPDATE netflow_analyses SET status = 'RUNNING', completed_at = NULL WHERE id = :id"
            ),
            {"id": analysis.id},
        )
    with (
        pytest.raises(DBAPIError, match="terminal failed identity"),
        session.begin_nested(),
    ):
        changed = _retry(analysis)
        changed.identity = {"config": "different"}
        session.add(changed)
        session.flush()
    successor = _retry(analysis)
    session.add(successor)
    session.flush()
    with (
        pytest.raises(DBAPIError, match="uq_nf_analysis_retry"),
        session.begin_nested(),
    ):
        session.add(_retry(analysis))
        session.flush()
    assert connection.execute(
        text(
            "SELECT status, terminal_confirmed, result IS NULL FROM netflow_analyses WHERE id = :id"
        ),
        {"id": analysis.id},
    ).one() == ("FAILED", True, True)
    assert (
        connection.scalar(
            text("SELECT id FROM netflow_analyses WHERE retry_of_analysis_id = :id"),
            {"id": analysis.id},
        )
        == successor.id
    )
    with (
        pytest.raises(DBAPIError, match="analyses cannot be deleted"),
        session.begin_nested(),
    ):
        session.connection().execute(
            text("DELETE FROM netflow_analyses WHERE id = :id"), {"id": successor.id}
        )


def test_context_chain_requires_exact_next_revision(
    reservation: tuple[Session, NetFlowAnalysis],
) -> None:
    session, analysis = reservation
    context = session.get(NetFlowContextRevision, analysis.context_revision_id)
    assert context is not None
    with (
        pytest.raises(DBAPIError, match="context revision chain"),
        session.begin_nested(),
    ):
        session.add(
            NetFlowContextRevision(
                **(
                    context.model_dump()
                    | {
                        "id": uuid.uuid4(),
                        "parent_id": context.id,
                        "revision": 3,
                        "operation_key": "skip-revision",
                        "created_at": context.created_at + timedelta(seconds=1),
                    }
                )
            )
        )
        session.flush()
    child = NetFlowContextRevision(
        **(
            context.model_dump()
            | {
                "id": uuid.uuid4(),
                "parent_id": context.id,
                "revision": 2,
                "operation_key": "revoke-context",
                "state": "REVOKED",
            }
        )
    )
    session.add(child)
    session.flush()
    assert session.connection().execute(
        text(
            "SELECT revision, state FROM netflow_context_revisions WHERE dataset_id = :id ORDER BY revision"
        ),
        {"id": analysis.dataset_id},
    ).tuples().all() == [(1, "CONFIRMED"), (2, "REVOKED")]
    with (
        pytest.raises(DBAPIError, match="revisions are immutable"),
        session.begin_nested(),
    ):
        session.connection().execute(
            text(
                "UPDATE netflow_context_revisions SET state = 'REVOKED' WHERE id = :id"
            ),
            {"id": context.id},
        )


@pytest.mark.parametrize(
    "change",
    [
        {"network_namespace": "different"},
        {"selection": {"cloud": None}},
        {"pins": {"netflow": {"identity": "different"}}},
        {"revision": 3},
    ],
)
def test_scope_revision_cannot_replace_frozen_inputs(
    reservation: tuple[Session, NetFlowAnalysis], change: dict[str, object]
) -> None:
    session, analysis = reservation
    root_id = uuid.uuid4()
    root = SourceCorrelationRevision(
        id=root_id,
        root_id=root_id,
        tenant_id=analysis.tenant_id,
        project_id=analysis.project_id,
        revision=1,
        network_namespace=analysis.network_namespace,
        created_by=analysis.created_by,
        selection={"netflow": {"analysis_id": str(analysis.id)}},
        pins={"netflow": {"identity": analysis.processing_identity_sha256}},
    )
    session.add(root)
    session.flush()
    with (
        pytest.raises(DBAPIError, match="changed netflow correlation inputs"),
        session.begin_nested(),
    ):
        session.add(
            SourceCorrelationRevision(
                **(
                    root.model_dump()
                    | {
                        "id": uuid.uuid4(),
                        "parent_id": root.id,
                        "revision": 2,
                        "scope_state": "CONFIRMED",
                        "evidence": "Synthetic same-scope declaration",
                    }
                    | change
                )
            )
        )
        session.flush()
    confirmed = SourceCorrelationRevision(
        **(
            root.model_dump()
            | {
                "id": uuid.uuid4(),
                "parent_id": root.id,
                "revision": 2,
                "scope_state": "CONFIRMED",
                "evidence": "Synthetic same-scope declaration",
            }
        )
    )
    session.add(confirmed)
    session.flush()
    assert session.connection().execute(
        text(
            "SELECT revision, scope_state FROM source_correlation_revisions WHERE root_id = :id ORDER BY revision"
        ),
        {"id": root.id},
    ).tuples().all() == [(1, "UNKNOWN"), (2, "CONFIRMED")]
    with (
        pytest.raises(DBAPIError, match="revisions are immutable"),
        session.begin_nested(),
    ):
        session.connection().execute(
            text("DELETE FROM source_correlation_revisions WHERE id = :id"),
            {"id": confirmed.id},
        )


def test_operation_recovery_has_one_actor_project_operation_key(
    reservation: tuple[Session, NetFlowAnalysis],
) -> None:
    session, analysis = reservation
    statement = text("""
        INSERT INTO audit_events
          (id, tenant_id, project_id, actor_subject, actor_type, action,
           target_type, target_id, after_data, occurred_at, created_at, updated_at)
        VALUES (:id, :tenant, :project, :actor, 'user', 'netflow.operation',
          'netflow_operation', :result,
          jsonb_build_object('operation', 'analysis:synthetic', 'operation_key', 'one-key',
                             'request_sha256', repeat('a', 64)), now(), now(), now())
    """)
    params = {
        "id": uuid.uuid4(),
        "tenant": analysis.tenant_id,
        "project": analysis.project_id,
        "actor": str(analysis.created_by),
        "result": analysis.id,
    }
    session.connection().execute(statement, params)
    with (
        pytest.raises(DBAPIError, match="uq_netflow_operation_key"),
        session.begin_nested(),
    ):
        session.connection().execute(statement, params | {"id": uuid.uuid4()})
    session.connection().execute(
        statement, params | {"id": uuid.uuid4(), "actor": str(uuid.uuid4())}
    )
    assert (
        session.connection().scalar(
            text(
                "SELECT count(*) FROM audit_events WHERE action = 'netflow.operation' AND project_id = :project"
            ),
            {"project": analysis.project_id},
        )
        == 2
    )
