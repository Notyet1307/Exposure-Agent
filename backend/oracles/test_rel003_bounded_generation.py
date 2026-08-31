import hashlib
import json
import os
import stat
import sys
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import app.domain.ai_governance_drafts as draft_service
from app.ai_draft_runner import main as run_ai_draft
from app.core.config import settings
from app.core.db import engine
from app.domain.models import (
    AiGovernanceDraft,
    AiGovernanceDraftFindingBinding,
    AiGovernanceDraftStatus,
)
from app.integrations.agent_compose import AgentComposeClient, AgentComposeRunStart
from tests.api.routes.test_ai_governance_draft_requests import (
    _operator_draft_request_context,
)


def _session_id(draft_id: uuid.UUID) -> str:
    return hashlib.sha256(f"session:{draft_id}".encode()).hexdigest()


def _allow_session_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(AgentComposeClient, "get_run", lambda *_args, **_kwargs: None)

    def start(
        client: AgentComposeClient,
        *,
        client_request_id: str,
        draft_id: str,
    ) -> AgentComposeRunStart:
        parsed_draft_id = uuid.UUID(draft_id)
        assert client_request_id == f"ai-governance-draft:{draft_id}"
        return AgentComposeRunStart(
            run_id=client.expected_ai_governance_draft_run_id(client_request_id),
            started=True,
            status="RUN_STATUS_SUCCEEDED",
            session_id=_session_id(parsed_draft_id),
        )

    monkeypatch.setattr(AgentComposeClient, "start_ai_governance_draft", start)


def _fake_pi(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    output: dict[str, Any],
) -> Path:
    capture_path = tmp_path / "pi-capture.json"
    executable = tmp_path / "pi"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        f"capture = pathlib.Path({str(capture_path)!r})\n"
        "capture.write_text(json.dumps({\n"
        "  'argv': sys.argv[1:],\n"
        "  'environment': sorted(os.environ),\n"
        "  'stdin': sys.stdin.read(),\n"
        "}))\n"
        f"print(json.dumps({output!r}))\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    return capture_path


def _request_draft(
    *,
    client: TestClient,
    headers: dict[str, str],
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    finding_id: uuid.UUID,
    idempotency_key: str,
) -> dict[str, Any]:
    response = client.post(
        f"{settings.API_V1_STR}/projects/{project_id}/governance-reports/"
        f"{report_id}/ai-governance-drafts",
        headers={**headers, "Idempotency-Key": idempotency_key},
        json={"finding_ids": [str(finding_id)]},
    )
    assert response.status_code == 202, response.text
    return cast(dict[str, Any], response.json())


def _request_context(
    *,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    project, report, operator_headers, finding_id, _url = (
        _operator_draft_request_context(
            client=client,
            superuser_token_headers=superuser_token_headers,
            db=db,
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
        )
    )
    return {
        "project_id": uuid.UUID(str(project["id"])),
        "report_id": report.id,
        "operator_headers": operator_headers,
        "finding_id": uuid.UUID(finding_id),
    }


def _runner_environment(
    monkeypatch: pytest.MonkeyPatch, draft: AiGovernanceDraft
) -> None:
    assert draft.agent_compose_run_id is not None
    assert draft.session_id is not None
    monkeypatch.setenv("AI_DRAFT_ID", str(draft.id))
    monkeypatch.setenv("AI_DRAFT_RUN_ID", draft.agent_compose_run_id)
    monkeypatch.setenv("SANDBOX_ID", draft.session_id)
    monkeypatch.setattr(sys, "argv", ["ai-draft-runner"])


def test_request_runs_one_bounded_model_attempt_and_replay_returns_it(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _request_context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    _allow_session_start(monkeypatch)
    requested = _request_draft(
        client=client,
        headers=context["operator_headers"],
        project_id=context["project_id"],
        report_id=context["report_id"],
        finding_id=context["finding_id"],
        idempotency_key="rel003-oracle-generation",
    )

    with Session(engine) as session:
        draft = session.get(AiGovernanceDraft, uuid.UUID(requested["id"]))
        assert draft is not None
        binding = session.exec(
            select(AiGovernanceDraftFindingBinding).where(
                AiGovernanceDraftFindingBinding.draft_id == draft.id
            )
        ).one()
        output = {
            "report_sha256": draft.report_sha256,
            "summary": "One bounded customer-internal interpretation.",
            "recommendations": [
                {
                    "finding_id": str(binding.finding_id),
                    "rescan_recommendation": "Verify the selected unobserved asset.",
                    "pending_verifications": ["Confirm the asset owner."],
                    "limitations": ["One bounded observation."],
                    "claims": [
                        {
                            "claim_id": "claim-selected-finding",
                            "evidence_ids": [str(binding.evidence_id)],
                        }
                    ],
                }
            ],
        }
        selected_evidence_id = binding.evidence_id
        capture_path = _fake_pi(
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            output=output,
        )
        _runner_environment(monkeypatch, draft)

    assert run_ai_draft() == 0

    invocation = json.loads(capture_path.read_text(encoding="utf-8"))
    assert "--no-tools" in invocation["argv"]
    assert "DATABASE_URL" not in invocation["environment"]
    assert "POSTGRES_PASSWORD" not in invocation["environment"]
    assert output["report_sha256"] in invocation["stdin"]
    assert str(context["finding_id"]) in invocation["stdin"]
    assert str(selected_evidence_id) in invocation["stdin"]

    replay = client.post(
        f"{settings.API_V1_STR}/projects/{context['project_id']}/"
        f"governance-reports/{context['report_id']}/ai-governance-drafts",
        headers={
            **context["operator_headers"],
            "Idempotency-Key": "rel003-oracle-generation",
        },
        json={"finding_ids": [str(context["finding_id"])]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == requested["id"]
    assert replay.json()["status"] == AiGovernanceDraftStatus.REVIEWABLE
    assert replay.json()["model_output"] == output


def test_binding_drift_fails_closed_before_model_data_egress(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context = _request_context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    _allow_session_start(monkeypatch)
    requested = _request_draft(
        client=client,
        headers=context["operator_headers"],
        project_id=context["project_id"],
        report_id=context["report_id"],
        finding_id=context["finding_id"],
        idempotency_key="rel003-oracle-drift",
    )
    capture_path = _fake_pi(monkeypatch=monkeypatch, tmp_path=tmp_path, output={})

    with Session(engine) as session:
        draft = session.get(AiGovernanceDraft, uuid.UUID(requested["id"]))
        assert draft is not None
        _runner_environment(monkeypatch, draft)
    monkeypatch.setattr(
        settings,
        "MODEL_CONFIG_REVISION",
        f"{settings.MODEL_CONFIG_REVISION}-drifted",
    )

    run_ai_draft()

    assert not capture_path.exists()
    with Session(engine) as session:
        failed = session.get(AiGovernanceDraft, uuid.UUID(requested["id"]))
        assert failed is not None
        assert failed.status == AiGovernanceDraftStatus.FAILED
        assert failed.failure_code == "model_binding_changed"
        assert failed.model_output is None


def test_failed_attempt_requires_a_fresh_key_record_run_and_session(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _request_context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    _allow_session_start(monkeypatch)
    first = _request_draft(
        client=client,
        headers=context["operator_headers"],
        project_id=context["project_id"],
        report_id=context["report_id"],
        finding_id=context["finding_id"],
        idempotency_key="rel003-oracle-failed-attempt",
    )
    with Session(engine) as session:
        old_draft = session.get(AiGovernanceDraft, uuid.UUID(first["id"]))
        assert old_draft is not None
        old_run_id = old_draft.agent_compose_run_id
        old_session_id = old_draft.session_id
        draft_service.fail_draft(
            session=session,
            draft=old_draft,
            failure_code="model_run_failed",
        )

    second = _request_draft(
        client=client,
        headers=context["operator_headers"],
        project_id=context["project_id"],
        report_id=context["report_id"],
        finding_id=context["finding_id"],
        idempotency_key="rel003-oracle-new-attempt",
    )
    assert second["id"] != first["id"]
    assert second["agent_compose_run_id"] != old_run_id
    assert second["session_id"] != old_session_id

    replay = client.post(
        f"{settings.API_V1_STR}/projects/{context['project_id']}/"
        f"governance-reports/{context['report_id']}/ai-governance-drafts",
        headers={
            **context["operator_headers"],
            "Idempotency-Key": "rel003-oracle-failed-attempt",
        },
        json={"finding_ids": [str(context["finding_id"])]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first["id"]
    assert replay.json()["status"] == AiGovernanceDraftStatus.FAILED
