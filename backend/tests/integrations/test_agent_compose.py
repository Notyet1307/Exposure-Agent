from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
)


class _Response:
    def __init__(
        self,
        status_code: int,
        body: Any = None,
        *,
        invalid_json: bool = False,
    ) -> None:
        self.status_code = status_code
        self._body = body
        self._invalid_json = invalid_json

    def json(self) -> Any:
        if self._invalid_json:
            raise ValueError("invalid json")
        return self._body


class _Client:
    def __init__(
        self,
        response: _Response | Exception,
        calls: list[dict[str, Any]],
    ) -> None:
        self.response = response
        self.calls = calls

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, path: str, **kwargs: Any) -> _Response:
        self.calls.append({"path": path, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _configure_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AGENT_COMPOSE_URL", "http://agent-compose/")
    monkeypatch.setattr(settings, "AGENT_COMPOSE_PROJECT_NAME", "project")
    monkeypatch.setattr(settings, "AGENT_COMPOSE_PROJECT_SOURCE_PATH", "/source")
    monkeypatch.setattr(settings, "AGENT_COMPOSE_AGENT_NAME", "runner")
    monkeypatch.setattr(settings, "AGENT_COMPOSE_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setattr(
        settings, "AGENT_COMPOSE_AUTH_TOKEN", SecretStr("test-token")
    )


def _install_response(
    monkeypatch: pytest.MonkeyPatch,
    response: _Response | Exception,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def factory(**_kwargs: Any) -> _Client:
        return _Client(response, calls)

    monkeypatch.setattr("app.integrations.agent_compose.httpx.Client", factory)
    return calls


def test_start_governance_run_builds_sorted_environment_and_returns_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(monkeypatch)
    calls: list[dict[str, Any]] = []
    responses = iter(
        [
            _Response(404),
            _Response(
                200,
                {
                    "run": {"runId": "placeholder", "status": "RUNNING"},
                    "started": True,
                },
            ),
        ]
    )

    def factory(**_kwargs: Any) -> _Client:
        return _Client(next(responses), calls)

    monkeypatch.setattr("app.integrations.agent_compose.httpx.Client", factory)
    client = AgentComposeClient()
    request_id = "project:trigger"
    expected_id = client.expected_run_id(request_id)
    # The second response is intentionally tied to the client's deterministic ID.
    responses = iter(
        [
            _Response(404),
            _Response(
                200,
                {
                    "run": {"runId": expected_id, "status": "RUNNING"},
                    "started": True,
                },
            ),
        ]
    )

    result = client.start_governance_run(
        client_request_id=request_id,
        environment={"Z_LAST": "last", "A_FIRST": "first"},
    )

    assert result.run_id == expected_id
    assert result.started is True
    assert result.status == "RUNNING"
    assert calls[0]["path"].endswith("GetRun")
    assert calls[1]["path"].endswith("StartRun")
    assert calls[1]["headers"]["Authorization"] == "Bearer test-token"
    assert calls[1]["json"]["run"]["env"] == [
        {"name": "A_FIRST", "value": "first", "secret": False},
        {"name": "Z_LAST", "value": "last", "secret": False},
    ]


def test_start_governance_run_reuses_existing_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(monkeypatch)
    client = AgentComposeClient()
    expected_id = client.expected_run_id("project:trigger")
    _install_response(
        monkeypatch,
        _Response(
            200,
            {"run": {"summary": {"runId": expected_id, "status": "RUNNING"}}},
        ),
    )

    result = client.start_governance_run(
        client_request_id="project:trigger", environment={}
    )

    assert result.run_id == expected_id
    assert result.started is False
    assert result.status == "RUNNING"


@pytest.mark.parametrize(
    ("response", "missing_ok", "code"),
    [
        (httpx.ConnectError("offline"), False, "agent_compose_unavailable"),
        (_Response(500), False, "agent_compose_start_failed"),
        (_Response(404), False, "agent_compose_start_failed"),
        (_Response(200, invalid_json=True), False, "agent_compose_response_contract_failed"),
        (_Response(200, []), False, "agent_compose_response_contract_failed"),
    ],
)
def test_request_maps_transport_and_response_contract_failures(
    monkeypatch: pytest.MonkeyPatch,
    response: _Response | Exception,
    missing_ok: bool,
    code: str,
) -> None:
    _configure_settings(monkeypatch)
    client = AgentComposeClient()
    _install_response(monkeypatch, response)

    with pytest.raises(AgentComposeBoundaryError, match=code):
        client._request("/test", {}, missing_ok=missing_ok)


def test_get_run_rejects_mismatched_and_incomplete_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(monkeypatch)
    client = AgentComposeClient()
    run_id = client.expected_run_id("project:trigger")

    bodies: tuple[dict[str, Any], ...] = (
        {"run": {"summary": {"runId": "different", "status": "RUNNING"}}},
        {"run": {"summary": {"runId": run_id}}},
        {"run": {"summary": {"status": "RUNNING"}}},
        {"run": []},
    )
    for body in bodies:
        _install_response(monkeypatch, _Response(200, body))
        with pytest.raises(AgentComposeBoundaryError, match="contract_failed"):
            client.get_run(run_id)


def test_start_governance_run_rejects_invalid_started_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(monkeypatch)
    client = AgentComposeClient()
    run_id = client.expected_run_id("project:trigger")
    responses = iter(
        [
            _Response(404),
            _Response(
                200,
                {
                    "run": {"runId": run_id, "status": "RUNNING"},
                    "started": "yes",
                },
            ),
        ]
    )
    calls: list[dict[str, Any]] = []

    def factory(**_kwargs: Any) -> _Client:
        return _Client(next(responses), calls)

    monkeypatch.setattr("app.integrations.agent_compose.httpx.Client", factory)

    with pytest.raises(AgentComposeBoundaryError, match="contract_failed"):
        client.start_governance_run(
            client_request_id="project:trigger", environment={}
        )
