from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import time
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlmodel import Session, select

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


def _allow_session_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(AgentComposeClient, "get_run", lambda *_args, **_kwargs: None)

    def start(
        client: AgentComposeClient,
        *,
        client_request_id: str,
        draft_id: str,
    ) -> AgentComposeRunStart:
        parsed_draft_id = uuid.UUID(draft_id)
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
    stdout: str,
    return_code: int = 0,
    sleep_seconds: float = 0,
) -> Path:
    capture_path = tmp_path / f"pi-capture-{uuid.uuid4()}.json"
    executable = tmp_path / "pi"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys, time\n"
        f"capture = pathlib.Path({str(capture_path)!r})\n"
        "capture.write_text(json.dumps({\n"
        "  'argv': sys.argv[1:],\n"
        "  'environment': sorted(os.environ),\n"
        "  'stdin': sys.stdin.read(),\n"
        "}))\n"
        f"time.sleep({sleep_seconds!r})\n"
        f"sys.stdout.write({stdout!r})\n"
        f"raise SystemExit({return_code})\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    return capture_path


def _request_context(
    *,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    project, report, operator_headers, finding_id, url = (
        _operator_draft_request_context(
            client=client,
            superuser_token_headers=superuser_token_headers,
            db=db,
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
        )
    )
    _allow_session_start(monkeypatch)
    response = client.post(
        url,
        headers={
            **operator_headers,
            "Idempotency-Key": f"ai-runner-{uuid.uuid4()}",
        },
        json={"finding_ids": [finding_id]},
    )
    assert response.status_code == 202, response.text
    return {
        "project_id": uuid.UUID(str(project["id"])),
        "report_id": report.id,
        "operator_headers": operator_headers,
        "finding_id": uuid.UUID(finding_id),
        "draft_id": uuid.UUID(cast(dict[str, Any], response.json())["id"]),
    }


def _draft_and_output(draft_id: uuid.UUID) -> tuple[AiGovernanceDraft, dict[str, Any]]:
    with Session(engine) as session:
        draft = session.get(AiGovernanceDraft, draft_id)
        assert draft is not None
        binding = session.exec(
            select(AiGovernanceDraftFindingBinding).where(
                AiGovernanceDraftFindingBinding.draft_id == draft.id
            )
        ).one()
        output = {
            "report_sha256": draft.report_sha256,
            "summary": "Bounded customer-internal interpretation.",
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
        session.expunge(draft)
    return draft, output


def _runner_environment(
    monkeypatch: pytest.MonkeyPatch, draft: AiGovernanceDraft
) -> None:
    assert draft.agent_compose_run_id is not None
    assert draft.session_id is not None
    monkeypatch.setenv("AI_DRAFT_ID", str(draft.id))
    monkeypatch.setenv("AI_DRAFT_RUN_ID", draft.agent_compose_run_id)
    monkeypatch.setenv("SANDBOX_ID", draft.session_id)
    monkeypatch.setattr(sys, "argv", ["ai-draft-runner"])


def test_runner_executes_one_sanitized_bounded_model_attempt_and_persists_output(
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
    draft, output = _draft_and_output(cast(uuid.UUID, context["draft_id"]))
    capture_path = _fake_pi(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        stdout=json.dumps(output),
    )
    _runner_environment(monkeypatch, draft)

    assert run_ai_draft() == 0

    invocation = json.loads(capture_path.read_text(encoding="utf-8"))
    assert invocation["argv"].count("--no-tools") == 1
    assert "--no-session" in invocation["argv"]
    assert "DATABASE_URL" not in invocation["environment"]
    assert "POSTGRES_PASSWORD" not in invocation["environment"]
    assert "SECRET_KEY" not in invocation["environment"]
    assert draft.report_sha256 in invocation["stdin"]
    assert str(context["finding_id"]) in invocation["stdin"]

    with Session(engine) as session:
        completed = session.get(AiGovernanceDraft, draft.id)
        assert completed is not None
        assert completed.status == AiGovernanceDraftStatus.REVIEWABLE
        assert completed.model_output == output
        assert completed.failure_code is None


def test_runner_fails_closed_before_model_egress_when_binding_drifts(
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
    draft, _output = _draft_and_output(cast(uuid.UUID, context["draft_id"]))
    capture_path = _fake_pi(monkeypatch=monkeypatch, tmp_path=tmp_path, stdout="{}")
    _runner_environment(monkeypatch, draft)
    monkeypatch.setattr(
        settings,
        "MODEL_CONFIG_REVISION",
        f"{settings.MODEL_CONFIG_REVISION}-drifted",
    )

    assert run_ai_draft() == 0
    assert not capture_path.exists()

    with Session(engine) as session:
        failed = session.get(AiGovernanceDraft, draft.id)
        assert failed is not None
        assert failed.status == AiGovernanceDraftStatus.FAILED
        assert failed.failure_code == "model_binding_changed"
        assert failed.model_output is None


@pytest.mark.parametrize(
    ("stdout", "return_code", "expected_failure"),
    [
        ("", 0, "model_output_empty"),
        ("{}", 0, "model_output_invalid"),
        ("provider diagnostic containing secret text", 7, "model_run_failed"),
    ],
)
def test_runner_persists_redacted_terminal_failure_for_model_failures(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stdout: str,
    return_code: int,
    expected_failure: str,
) -> None:
    context = _request_context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    draft, _output = _draft_and_output(cast(uuid.UUID, context["draft_id"]))
    _fake_pi(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        stdout=stdout,
        return_code=return_code,
    )
    _runner_environment(monkeypatch, draft)

    assert run_ai_draft() == 0

    with Session(engine) as session:
        failed = session.get(AiGovernanceDraft, draft.id)
        assert failed is not None
        assert failed.status == AiGovernanceDraftStatus.FAILED
        assert failed.failure_code == expected_failure
        assert failed.model_output is None


def test_runner_timeout_is_one_terminal_attempt(
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
    draft, _output = _draft_and_output(cast(uuid.UUID, context["draft_id"]))
    capture_path = _fake_pi(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        stdout="{}",
        sleep_seconds=1,
    )
    _runner_environment(monkeypatch, draft)
    monkeypatch.setattr(settings, "AI_GOVERNANCE_DRAFT_TIMEOUT_SECONDS", 0.2)

    started_at = time.monotonic()
    assert run_ai_draft() == 0
    assert time.monotonic() - started_at < 2
    assert capture_path.exists()

    with Session(engine) as session:
        failed = session.get(AiGovernanceDraft, draft.id)
        assert failed is not None
        assert failed.status == AiGovernanceDraftStatus.FAILED
        assert failed.failure_code == "model_timeout"


def test_configured_agent_compose_run_passes_only_draft_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MODEL_API_ENDPOINT", "http://127.0.0.1/v1")
    monkeypatch.setattr(settings, "MODEL_IDENTITY", "customer-model")
    monkeypatch.setattr(settings, "AGENT_COMPOSE_RUNTIME_VERSION", "compose-v1")
    monkeypatch.setattr(settings, "MODEL_API_KEY", SecretStr("model-secret"))
    captured: dict[str, object] = {}

    def start(
        client: AgentComposeClient,
        *,
        agent_name: str,
        client_request_id: str,
        environment: dict[str, str],
        command: str,
        secret_environment: dict[str, str] | None = None,
        session_id: str | None = None,
    ) -> AgentComposeRunStart:
        captured.update(
            {
                "agent_name": agent_name,
                "client_request_id": client_request_id,
                "environment": environment,
                "command": command,
                "secret_environment": secret_environment,
                "session_id": session_id,
            }
        )
        return AgentComposeRunStart(
            run_id=client.expected_ai_governance_draft_run_id(client_request_id),
            started=True,
            status="RUN_STATUS_PENDING",
        )

    monkeypatch.setattr(AgentComposeClient, "_start_run", start)
    client = AgentComposeClient()
    request_id = "ai-governance-draft:00000000-0000-0000-0000-000000000001"
    draft_id = "00000000-0000-0000-0000-000000000001"

    client.start_ai_governance_draft(
        client_request_id=request_id,
        draft_id=draft_id,
    )

    assert captured["command"] == "/app/.venv/bin/python -m app.ai_draft_runner"
    assert captured["environment"] == {
        "AI_DRAFT_ID": draft_id,
        "AI_DRAFT_RUN_ID": client.expected_ai_governance_draft_run_id(request_id),
    }
    assert captured["secret_environment"] is None
