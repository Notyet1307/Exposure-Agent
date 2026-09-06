import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import Connection, text
from sqlmodel import Session, func, select

from app.api.deps import get_db
from app.api.routes import governance_reports as report_routes
from app.core.db import engine
from app.domain import ai_governance_drafts as draft_service
from app.domain.models import (
    AiGovernanceDraft,
    AuditEvent,
    GovernanceReport,
    GovernanceRun,
)
from app.main import app
from tests.api.routes.test_ai_governance_draft_requests import (
    _operator_draft_request_context,
)


@pytest.fixture
def isolated_connection() -> Generator[Connection]:
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


def test_v2_refuses_ai_before_evidence_or_model_work_including_replay(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    isolated_connection: Connection,
) -> None:
    project, report, headers, finding_id, request_url = _operator_draft_request_context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        qualify_model=False,
    )
    existing_key = f"candidate-existing-{uuid.uuid4()}"
    with Session(
        isolated_connection, join_transaction_mode="create_savepoint"
    ) as setup:
        stored_report = setup.get(GovernanceReport, report.id)
        assert stored_report is not None
        binding = draft_service.draft_finding_bindings_for_request(
            session=setup, report=stored_report, finding_ids=[uuid.UUID(finding_id)]
        )
        draft_service.create_ai_governance_draft(
            session=setup,
            report=stored_report,
            initiated_by="fixture",
            idempotency_key=existing_key,
            model_identity="fixture-model",
            config_fingerprint="a" * 64,
            bindings=binding,
        )

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "Unsupported v2 must not resolve Evidence or contact a model/Session"
        )

    monkeypatch.setattr(draft_service, "draft_finding_bindings_for_request", forbidden)
    monkeypatch.setattr(draft_service, "create_ai_governance_draft", forbidden)
    monkeypatch.setattr(report_routes, "_require_current_model_binding", forbidden)
    monkeypatch.setattr(report_routes, "_launch_or_reconcile_draft_session", forbidden)
    # Future-version fixture is transaction-local, never a production v2 publish.
    # Existing migration tests use the same trigger bypass for corrupt-fact cases.
    with Session(
        isolated_connection, join_transaction_mode="create_savepoint"
    ) as isolated:
        isolated.execute(text("SET LOCAL session_replication_role = replica"))
        stored_report = isolated.get(GovernanceReport, report.id)
        assert stored_report is not None
        stored_run = isolated.get(GovernanceRun, report.governance_run_id)
        assert stored_run is not None
        stored_report.report_contract_version = "deterministic-report-v2"
        stored_run.report_contract_version = "deterministic-report-v2"
        stored_report.canonical_content = {"invalid": "must not parse Evidence"}
        isolated.add(stored_report)
        isolated.add(stored_run)
        isolated.flush()
        isolated.execute(text("SET LOCAL session_replication_role = origin"))
        baseline_drafts = isolated.exec(
            select(func.count()).select_from(AiGovernanceDraft)
        ).one()
        baseline_audits = isolated.exec(
            select(func.count()).select_from(AuditEvent)
        ).one()
        existing_draft = isolated.exec(
            select(AiGovernanceDraft).where(
                AiGovernanceDraft.idempotency_key == existing_key
            )
        ).one()
        frozen_draft = existing_draft.model_dump()

        def override_db() -> Generator[Session]:
            yield isolated

        previous = app.dependency_overrides.get(get_db)
        app.dependency_overrides[get_db] = override_db
        try:
            detail = client.get(
                request_url.removesuffix("/ai-governance-drafts"), headers=headers
            )
            assert detail.status_code == 200
            assert detail.json()["can_request_ai_governance_draft"] is False
            assert detail.json()["report_contract_version"] == "deterministic-report-v2"
            for key in (f"candidate-new-{uuid.uuid4()}", existing_key):
                response = client.post(
                    request_url,
                    headers={**headers, "Idempotency-Key": key},
                    json={"finding_ids": [finding_id]},
                )
                assert response.status_code == 409
                assert (
                    response.json()["detail"]["code"]
                    == "draft_report_contract_unsupported"
                )
            with_session_report = draft_service.require_published_report_for_draft
            try:
                with_session_report(session=isolated, report=stored_report)
            except draft_service.AiGovernanceDraftStateError as error:
                assert error.code == "draft_report_contract_unsupported"
            else:
                raise AssertionError("Direct domain callers must also refuse v2")
            assert (
                isolated.exec(select(func.count()).select_from(AiGovernanceDraft)).one()
                == baseline_drafts
            )
            assert (
                isolated.exec(select(func.count()).select_from(AuditEvent)).one()
                == baseline_audits
            )
            isolated.refresh(existing_draft)
            assert existing_draft.model_dump() == frozen_draft
            assert str(project["id"]) in request_url
            wrong_report_url = request_url.replace(str(report.id), str(uuid.uuid4()))
            missing_report = client.post(
                wrong_report_url,
                headers={
                    **headers,
                    "Idempotency-Key": f"candidate-wrong-scope-{uuid.uuid4()}",
                },
                json={"finding_ids": [finding_id]},
            )
            assert missing_report.status_code == 404
        finally:
            if previous is None:
                app.dependency_overrides.pop(get_db, None)
            else:
                app.dependency_overrides[get_db] = previous
            isolated.rollback()
