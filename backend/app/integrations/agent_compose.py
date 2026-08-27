from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

import httpx

from app.core.config import settings

_PROJECT_KIND: Final = "project"
_RUN_KIND: Final = "run"
_RUN_SOURCE: Final = "api"
_START_RUN_PATH: Final = "/agentcompose.v2.RunService/StartAgentRun"
_GET_RUN_PATH: Final = "/agentcompose.v2.RunService/GetRun"
_GET_SESSION_PATH: Final = "/agentcompose.v2.SandboxService/GetSandbox"
_RESUME_SESSION_PATH: Final = "/agentcompose.v2.SandboxService/ResumeSandbox"


class AgentComposeBoundaryError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AgentComposeRunStart:
    run_id: str
    started: bool
    status: str
    session_id: str | None = None
    output: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status.upper() in {
            "SUCCEEDED",
            "RUN_STATUS_SUCCEEDED",
        }

    @property
    def is_terminal(self) -> bool:
        return self.status.upper() in {
            "FAILED",
            "SUCCEEDED",
            "RUN_STATUS_FAILED",
            "RUN_STATUS_SUCCEEDED",
        }

    @property
    def is_active(self) -> bool:
        return self.status.upper() in {
            "PENDING",
            "RUNNING",
            "RUN_STATUS_PENDING",
            "RUN_STATUS_RUNNING",
        }


class AgentComposeSessionObservation(StrEnum):
    TERMINAL = "terminal"
    RUNNING = "running"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AgentComposeDraftNamespace:
    """The stable agent-compose names needed to recover a reserved draft Run."""

    project_id: str
    agent_name: str


@dataclass(frozen=True)
class AgentComposeSession:
    session_id: str
    observation: AgentComposeSessionObservation


def _session_observation(status: str) -> AgentComposeSessionObservation:
    normalized = status.lower()
    if normalized in {"stopped", "sandbox_status_stopped"}:
        return AgentComposeSessionObservation.TERMINAL
    if normalized in {"running", "sandbox_status_running"}:
        return AgentComposeSessionObservation.RUNNING
    return AgentComposeSessionObservation.UNKNOWN


def _stable_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256()
    for value in (kind, *parts):
        encoded = value.strip().encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _required_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentComposeBoundaryError("agent_compose_response_contract_failed")
    return value


def _required_string(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise AgentComposeBoundaryError("agent_compose_response_contract_failed")
    return value


class AgentComposeClient:
    def __init__(
        self, *, ai_governance_draft_namespace: AgentComposeDraftNamespace | None = None
    ) -> None:
        self.base_url = settings.AGENT_COMPOSE_URL.rstrip("/")
        namespace = ai_governance_draft_namespace
        self.project_id = (
            namespace.project_id
            if namespace is not None
            else _stable_id(_PROJECT_KIND, settings.AGENT_COMPOSE_PROJECT_NAME)
        )
        self.ai_governance_draft_agent_name = (
            namespace.agent_name
            if namespace is not None
            else settings.AI_GOVERNANCE_DRAFT_AGENT_NAME
        )

    def ai_governance_draft_namespace(self) -> AgentComposeDraftNamespace:
        return AgentComposeDraftNamespace(
            project_id=self.project_id,
            agent_name=self.ai_governance_draft_agent_name,
        )

    def _request(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        missing_ok: bool = False,
        non_ok_code: str = "agent_compose_start_failed",
    ) -> dict[str, Any] | None:
        token = settings.AGENT_COMPOSE_AUTH_TOKEN.get_secret_value()
        headers = {
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=settings.AGENT_COMPOSE_TIMEOUT_SECONDS,
            ) as client:
                response = client.post(path, headers=headers, json=payload)
        except httpx.HTTPError:
            raise AgentComposeBoundaryError("agent_compose_unavailable")
        if response.status_code == 404 and missing_ok:
            return None
        if response.status_code != 200:
            raise AgentComposeBoundaryError(non_ok_code)
        try:
            body = response.json()
        except ValueError:
            raise AgentComposeBoundaryError("agent_compose_response_contract_failed")
        return _required_object(body)

    def _expected_run_id(self, *, agent_name: str, client_request_id: str) -> str:
        return _stable_id(
            _RUN_KIND,
            self.project_id,
            agent_name,
            _RUN_SOURCE,
            client_request_id,
        )

    def expected_run_id(self, client_request_id: str) -> str:
        return self._expected_run_id(
            agent_name=settings.AGENT_COMPOSE_AGENT_NAME,
            client_request_id=client_request_id,
        )

    def expected_model_qualification_run_id(self, client_request_id: str) -> str:
        return self._expected_run_id(
            agent_name=settings.MODEL_QUALIFICATION_AGENT_NAME,
            client_request_id=client_request_id,
        )

    def expected_ai_governance_draft_run_id(self, client_request_id: str) -> str:
        return self._expected_run_id(
            agent_name=self.ai_governance_draft_agent_name,
            client_request_id=client_request_id,
        )

    def get_run(self, run_id: str) -> AgentComposeRunStart | None:
        body = self._request(
            _GET_RUN_PATH,
            {"projectId": self.project_id, "runId": run_id},
            missing_ok=True,
        )
        if body is None:
            return None
        detail = _required_object(body.get("run"))
        summary = _required_object(detail.get("summary"))
        returned_id = _required_string(summary.get("runId"))
        if returned_id != run_id:
            raise AgentComposeBoundaryError("agent_compose_response_contract_failed")
        status = _required_string(summary.get("status"))
        session_id = summary.get("sandboxId")
        if session_id is not None and (
            not isinstance(session_id, str) or not session_id
        ):
            raise AgentComposeBoundaryError("agent_compose_response_contract_failed")
        output = detail.get("output")
        if output is not None and not isinstance(output, str):
            raise AgentComposeBoundaryError("agent_compose_response_contract_failed")
        return AgentComposeRunStart(
            run_id=run_id,
            started=False,
            status=status,
            session_id=session_id,
            output=output,
        )

    def get_session(self, session_id: str) -> AgentComposeSession | None:
        body = self._request(
            _GET_SESSION_PATH,
            {"sandboxId": session_id},
            missing_ok=True,
        )
        if body is None:
            return None
        sandbox = _required_object(body.get("sandbox"))
        returned_id = _required_string(sandbox.get("sandboxId"))
        if returned_id != session_id:
            raise AgentComposeBoundaryError("agent_compose_response_contract_failed")
        status = _required_string(sandbox.get("status"))
        return AgentComposeSession(
            session_id=session_id,
            observation=_session_observation(status),
        )

    def resume_session(self, session_id: str) -> AgentComposeSession:
        body = self._request(
            _RESUME_SESSION_PATH,
            {"sandboxId": session_id},
            missing_ok=True,
            non_ok_code="agent_compose_session_not_recoverable",
        )
        if body is None:
            raise AgentComposeBoundaryError("agent_compose_session_not_recoverable")
        sandbox = _required_object(body.get("sandbox"))
        returned_id = _required_string(sandbox.get("sandboxId"))
        if returned_id != session_id:
            raise AgentComposeBoundaryError("agent_compose_response_contract_failed")
        status = _required_string(sandbox.get("status"))
        return AgentComposeSession(
            session_id=session_id,
            observation=_session_observation(status),
        )

    def start_governance_run(
        self,
        *,
        client_request_id: str,
        environment: dict[str, str],
        session_id: str | None = None,
    ) -> AgentComposeRunStart:
        return self._start_run(
            agent_name=settings.AGENT_COMPOSE_AGENT_NAME,
            client_request_id=client_request_id,
            environment=environment,
            command="/app/.venv/bin/python -m app.governance_runner",
            session_id=session_id,
        )

    def start_model_qualification(
        self, *, client_request_id: str
    ) -> AgentComposeRunStart:
        return self._start_run(
            agent_name=settings.MODEL_QUALIFICATION_AGENT_NAME,
            client_request_id=client_request_id,
            environment={},
            secret_environment={
                "LLM_API_KEY": settings.MODEL_API_KEY.get_secret_value()
            },
            command="/app/.venv/bin/python -m app.model_qualification_runner",
        )

    def start_ai_governance_draft(
        self, *, client_request_id: str, draft_id: str
    ) -> AgentComposeRunStart:
        if not draft_id:
            raise AgentComposeBoundaryError("agent_compose_response_contract_failed")
        return self._start_run(
            agent_name=self.ai_governance_draft_agent_name,
            client_request_id=client_request_id,
            environment={},
            # Issue #143 creates and binds the dedicated Session only. The
            # bounded model handoff is a downstream capability, so this Agent
            # receives neither application credentials nor draft input.
            command="/usr/bin/true",
        )

    def _start_run(
        self,
        *,
        agent_name: str,
        client_request_id: str,
        environment: dict[str, str],
        command: str,
        secret_environment: dict[str, str] | None = None,
        session_id: str | None = None,
    ) -> AgentComposeRunStart:
        run_id = self._expected_run_id(
            agent_name=agent_name,
            client_request_id=client_request_id,
        )
        existing = self.get_run(run_id)
        if existing is not None:
            if session_id is not None and existing.session_id != session_id:
                raise AgentComposeBoundaryError(
                    "agent_compose_response_contract_failed"
                )
            return existing
        run_environment = {name: (value, False) for name, value in environment.items()}
        run_environment.update(
            {name: (value, True) for name, value in (secret_environment or {}).items()}
        )
        run_request: dict[str, Any] = {
            "projectId": self.project_id,
            "agentName": agent_name,
            "source": "RUN_SOURCE_API",
            "clientRequestId": client_request_id,
            "cleanupPolicy": ("RUN_SANDBOX_CLEANUP_POLICY_STOP_ON_COMPLETION"),
            "command": command,
            "env": [
                {"name": name, "value": value, "secret": secret}
                for name, (value, secret) in sorted(run_environment.items())
            ],
        }
        if session_id is not None:
            run_request["sandboxId"] = session_id
        body = self._request(
            _START_RUN_PATH,
            {"run": run_request},
        )
        assert body is not None
        summary = _required_object(body.get("run"))
        returned_id = _required_string(summary.get("runId"))
        if returned_id != run_id:
            raise AgentComposeBoundaryError("agent_compose_response_contract_failed")
        status = _required_string(summary.get("status"))
        started = body.get("started")
        if not isinstance(started, bool):
            raise AgentComposeBoundaryError("agent_compose_response_contract_failed")
        returned_session_id = (
            _required_string(summary.get("sandboxId"))
            if summary.get("sandboxId") is not None
            else None
        )
        if session_id is not None:
            if returned_session_id is not None and returned_session_id != session_id:
                raise AgentComposeBoundaryError(
                    "agent_compose_response_contract_failed"
                )
            # StartRun omits sandboxId when an explicit sandboxId is reused;
            # reject conflicts, but retain the requested binding.
            returned_session_id = session_id
        return AgentComposeRunStart(
            run_id=run_id,
            started=started,
            status=status,
            session_id=returned_session_id,
        )
