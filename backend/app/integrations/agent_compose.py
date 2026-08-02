from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Final

import httpx

from app.core.config import settings

_PROJECT_KIND: Final = "project"
_RUN_KIND: Final = "run"
_RUN_SOURCE: Final = "api"
_START_RUN_PATH: Final = "/agentcompose.v2.RunService/StartRun"
_GET_RUN_PATH: Final = "/agentcompose.v2.RunService/GetRun"


class AgentComposeBoundaryError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AgentComposeRunStart:
    run_id: str
    started: bool
    status: str


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
    def __init__(self) -> None:
        self.base_url = settings.AGENT_COMPOSE_URL.rstrip("/")
        self.project_id = _stable_id(
            _PROJECT_KIND,
            settings.AGENT_COMPOSE_PROJECT_NAME,
            settings.AGENT_COMPOSE_PROJECT_SOURCE_PATH,
        )

    def _request(
        self, path: str, payload: dict[str, Any], *, missing_ok: bool = False
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
            raise AgentComposeBoundaryError("agent_compose_start_failed")
        try:
            body = response.json()
        except ValueError:
            raise AgentComposeBoundaryError(
                "agent_compose_response_contract_failed"
            )
        return _required_object(body)

    def expected_run_id(self, client_request_id: str) -> str:
        return _stable_id(
            _RUN_KIND,
            self.project_id,
            settings.AGENT_COMPOSE_AGENT_NAME,
            _RUN_SOURCE,
            client_request_id,
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
            raise AgentComposeBoundaryError(
                "agent_compose_response_contract_failed"
            )
        status = _required_string(summary.get("status"))
        return AgentComposeRunStart(run_id=run_id, started=False, status=status)

    def start_governance_run(
        self,
        *,
        client_request_id: str,
        environment: dict[str, str],
    ) -> AgentComposeRunStart:
        run_id = self.expected_run_id(client_request_id)
        existing = self.get_run(run_id)
        if existing is not None:
            return existing
        body = self._request(
            _START_RUN_PATH,
            {
                "run": {
                    "projectId": self.project_id,
                    "agentName": settings.AGENT_COMPOSE_AGENT_NAME,
                    "command": (
                        "/app/.venv/bin/python -m app.governance_runner"
                    ),
                    "source": "RUN_SOURCE_API",
                    "clientRequestId": client_request_id,
                    "cleanupPolicy": (
                        "RUN_SANDBOX_CLEANUP_POLICY_STOP_ON_COMPLETION"
                    ),
                    "env": [
                        {"name": name, "value": value, "secret": False}
                        for name, value in sorted(environment.items())
                    ],
                }
            },
        )
        assert body is not None
        summary = _required_object(body.get("run"))
        returned_id = _required_string(summary.get("runId"))
        if returned_id != run_id:
            raise AgentComposeBoundaryError(
                "agent_compose_response_contract_failed"
            )
        status = _required_string(summary.get("status"))
        started = body.get("started")
        if not isinstance(started, bool):
            raise AgentComposeBoundaryError(
                "agent_compose_response_contract_failed"
            )
        return AgentComposeRunStart(run_id=run_id, started=started, status=status)
