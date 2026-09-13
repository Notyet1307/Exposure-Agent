"""Persisted legacy records keep their identity through the adoption gate.

Native observations are controlled here; faults.py separately exercises real
UNKNOWN/terminal control-plane observations in an owned daemon.
"""

import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.api.routes import governance_reports as governance_report_routes
from app.api.routes import model_connections as routes
from app.domain import ai_analysis_reports, ai_governance_drafts, ai_investigations
from app.domain import model_connections as service
from app.domain.models import (
    AiGovernanceDraft,
    AiInvestigation,
    AnalysisReport,
    Finding,
    ModelConnectionVersion,
)
from app.integrations import model_connection_runtime as runtime
from app.integrations.agent_compose import (
    AgentComposeClient,
    AgentComposeRunStart,
    AgentComposeSession,
    AgentComposeSessionObservation,
)
from tests.api.routes.test_ai_governance_draft_requests import (
    _operator_draft_request_context,
)
from tests.api.routes.test_model_connections import act, validated
from tests.api.routes.test_model_connections import (
    model_environment as model_environment,
)

legacy_drained = routes._legacy_drained


def test_managed_draft_pins_its_version_and_replays_after_replacement_or_revoke(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, report, headers, finding_id, draft_url = _operator_draft_request_context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    session_id = "a" * 64
    captured: list[AgentComposeClient] = []

    def start(
        native: AgentComposeClient, *, client_request_id: str, **_kwargs: Any
    ) -> AgentComposeRunStart:
        captured.append(native)
        return AgentComposeRunStart(
            run_id=native.expected_ai_governance_draft_run_id(client_request_id),
            started=True,
            status="RUNNING",
            session_id=session_id,
        )

    monkeypatch.setattr(AgentComposeClient, "start_ai_governance_draft", start)
    version_a = validated(client, superuser_token_headers, "A")
    assert act(client, superuser_token_headers, version_a, "activate").status_code == 200
    created = client.post(
        draft_url,
        headers={**headers, "Idempotency-Key": "managed-draft"},
        json={"finding_ids": [finding_id]},
    )
    assert created.status_code == 202, created.text
    draft_id = uuid.UUID(created.json()["id"])
    db.expire_all()
    draft = db.get(AiGovernanceDraft, draft_id)
    version = db.get(ModelConnectionVersion, uuid.UUID(version_a))
    assert draft and version
    assert draft.connection_version_id == version.id
    assert captured[0].project_id == runtime.client_for_version(version).project_id
    assert "ai-governance-draft" in runtime.ROLES
    assert all(
        "KEY" not in item["name"]
        for agent in runtime.project_spec(version)["agents"]
        for item in agent["env"]
    )

    version_b = validated(client, superuser_token_headers, "B")
    assert act(client, superuser_token_headers, version_b, "activate").status_code == 200
    replay = client.post(
        draft_url,
        headers={**headers, "Idempotency-Key": "managed-draft"},
        json={"finding_ids": [finding_id]},
    )
    assert replay.status_code == 200 and replay.json()["id"] == str(draft_id)
    assert act(client, superuser_token_headers, version_a, "revoke").status_code == 200
    replay_after_revoke = client.post(
        draft_url,
        headers={**headers, "Idempotency-Key": "managed-draft"},
        json={"finding_ids": [finding_id]},
    )
    assert replay_after_revoke.status_code == 200
    db.expire_all()
    draft = db.get(AiGovernanceDraft, draft_id)
    assert draft
    with pytest.raises(HTTPException) as error:
        governance_report_routes._require_draft_model_binding(session=db, draft=draft)
    assert error.value.status_code == 409


@pytest.mark.parametrize("family", ["investigation", "report", "draft"])
def test_legacy_pending_unknown_and_terminal_preserve_record(
    family: str,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The repository keeps one test DB for the suite. These deployment-wide
    # gate tests need a clean legacy job set, rather than earlier modules' jobs.
    db.rollback()
    db.execute(
        text(
            "TRUNCATE ai_investigations, analysis_reports, ai_governance_drafts CASCADE"
        )
    )
    db.commit()
    project, report, headers, finding_id, draft_url = _operator_draft_request_context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    finding = db.get(Finding, uuid.UUID(finding_id))
    assert finding
    native_session = uuid.uuid4().hex * 2
    method = {
        "investigation": "expected_ai_investigation_run_id",
        "report": "expected_analysis_report_run_id",
        "draft": "expected_ai_governance_draft_run_id",
    }[family]

    def start(
        native: AgentComposeClient, *, client_request_id: str, **_kwargs: Any
    ) -> AgentComposeRunStart:
        run_id = getattr(native, method)(client_request_id)
        return AgentComposeRunStart(
            run_id=run_id, started=True, status="RUNNING", session_id=native_session
        )

    monkeypatch.setattr(
        AgentComposeClient,
        {
            "investigation": "start_ai_investigation",
            "report": "start_analysis_report",
            "draft": "start_ai_governance_draft",
        }[family],
        start,
    )
    monkeypatch.setattr(AgentComposeClient, "get_run", lambda *_: None)
    url = (
        draft_url
        if family == "draft"
        else f"/api/v1/projects/{project['id']}/"
        + ("ai-investigations" if family == "investigation" else "analysis-reports")
    )
    body: dict[str, Any] = (
        {"finding_ids": [finding_id]}
        if family == "draft"
        else {"run_id": str(report.governance_run_id)}
    )
    if family == "investigation":
        body["resource_id"] = str(finding.resource_id)
    response = client.post(
        url, headers={**headers, "Idempotency-Key": "legacy-record"}, json=body
    )
    assert response.status_code == (202 if family == "draft" else 201), response.text
    record_id = uuid.UUID(response.json()["id"])
    model = {
        "investigation": AiInvestigation,
        "report": AnalysisReport,
        "draft": AiGovernanceDraft,
    }[family]
    db.expire_all()
    initial = db.get(model, record_id)
    assert initial
    initial_snapshot = initial.model_dump(mode="json")
    version = validated(client, superuser_token_headers)
    monkeypatch.setattr(routes, "_legacy_drained", legacy_drained)
    monkeypatch.setattr(
        AgentComposeClient,
        "get_run",
        lambda _self, run: AgentComposeRunStart(
            run_id=run,
            started=False,
            status="RUN_STATUS_SUCCEEDED",
            session_id=native_session,
        ),
    )
    blocked = act(client, superuser_token_headers, version, "activate").json()
    assert blocked["operation"]["error_code"] == "legacy_binding_unknown"
    assert blocked["state"]["active_id"] is None and not blocked["state"]["adopted"]
    db.expire_all()
    preserved = db.get(model, record_id)
    assert preserved and preserved.model_dump(mode="json") == initial_snapshot
    if family == "investigation":
        ai_investigations.finish(
            investigation_id=record_id, failure_code="agent_compose_run_failed"
        )
    elif family == "report":
        ai_analysis_reports.finish(
            analysis_report_id=record_id, failure_code="agent_compose_run_failed"
        )
    else:
        db.expire_all()
        draft = db.get(AiGovernanceDraft, record_id)
        assert draft
        ai_governance_drafts.fail_draft(
            session=db, draft=draft, failure_code="agent_compose_run_failed"
        )
    db.expire_all()
    record = db.get(model, record_id)
    assert record
    original = record.model_dump(mode="json")
    for observed in [
        None,
        AgentComposeSessionObservation.UNKNOWN,
        AgentComposeSessionObservation.RUNNING,
    ]:
        monkeypatch.setattr(
            AgentComposeClient,
            "get_session",
            lambda _self, _id, value=observed: (
                AgentComposeSession(session_id=native_session, observation=value)
                if value
                else None
            ),
        )
        blocked = act(client, superuser_token_headers, version, "activate").json()
        assert blocked["operation"]["error_code"] == "legacy_binding_unknown"
        assert blocked["state"]["active_id"] is None
    monkeypatch.setattr(
        AgentComposeClient,
        "get_session",
        lambda *_: AgentComposeSession(
            session_id=native_session,
            observation=AgentComposeSessionObservation.TERMINAL,
        ),
    )
    accepted = act(client, superuser_token_headers, version, "activate").json()
    assert accepted["operation"]["status"] == "SUCCEEDED"
    db.expire_all()
    record = db.get(model, record_id)
    assert record
    assert record.model_dump(mode="json") == original
    if family != "draft":
        assert isinstance(record, (AiInvestigation, AnalysisReport))
        assert record.connection_version_id is None
        assert (
            service.binding_for_task(
                db,
                "investigation" if family == "investigation" else "analysis_report",
                record,
            )
            is None
        )
