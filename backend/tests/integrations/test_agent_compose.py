from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
    AgentComposeRunStart,
    AgentComposeSessionObservation,
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
    monkeypatch.setattr(settings, "AGENT_COMPOSE_AGENT_NAME", "runner")
    monkeypatch.setattr(
        settings, "MODEL_QUALIFICATION_AGENT_NAME", "model-qualifier"
    )
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
    assert calls[1]["path"].endswith("StartAgentRun")
    assert calls[1]["headers"]["Authorization"] == "Bearer test-token"
    assert calls[1]["json"]["run"]["env"] == [
        {"name": "A_FIRST", "value": "first", "secret": False},
        {"name": "Z_LAST", "value": "last", "secret": False},
    ]


def test_model_qualification_uses_a_pi_prompt_without_secret_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(monkeypatch)
    client = AgentComposeClient()
    expected_id = client.expected_model_qualification_run_id("qualification-1")
    calls: list[dict[str, Any]] = []
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

    def factory(**_kwargs: Any) -> _Client:
        return _Client(next(responses), calls)

    monkeypatch.setattr("app.integrations.agent_compose.httpx.Client", factory)

    client.start_model_qualification(
        client_request_id="qualification-1",
        prompt="fixed synthetic fixture",
    )

    run_request = calls[1]["json"]["run"]
    assert calls[1]["path"].endswith("StartAgentRun")
    assert run_request["agentName"] == "model-qualifier"
    assert run_request["prompt"] == "fixed synthetic fixture"
    assert "command" not in run_request
    assert run_request["env"] == []
    assert "secret" not in json.dumps(calls)


def test_get_run_returns_terminal_model_output_without_logging_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(monkeypatch)
    client = AgentComposeClient()
    run_id = client.expected_model_qualification_run_id("qualification-1")
    _install_response(
        monkeypatch,
        _Response(
            200,
            {
                "run": {
                    "summary": {
                        "runId": run_id,
                        "status": "RUN_STATUS_SUCCEEDED",
                    },
                    "output": '{"recommendations": []}',
                }
            },
        ),
    )

    result = client.get_run(run_id)

    assert result is not None
    assert result.output == '{"recommendations": []}'
    assert result.is_terminal


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
            {
                "run": {
                    "summary": {
                        "runId": expected_id,
                        "status": "RUNNING",
                        "sandboxId": "a" * 64,
                    }
                }
            },
        ),
    )

    result = client.start_governance_run(
        client_request_id="project:trigger", environment={}
    )

    assert result.run_id == expected_id
    assert result.started is False
    assert result.status == "RUNNING"
    assert result.session_id == "a" * 64


def test_retry_start_rejects_an_existing_run_for_another_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(monkeypatch)
    client = AgentComposeClient()
    expected_id = client.expected_run_id("project:trigger:retry:2")
    _install_response(
        monkeypatch,
        _Response(
            200,
            {
                "run": {
                    "summary": {
                        "runId": expected_id,
                        "status": "RUNNING",
                        "sandboxId": "a" * 64,
                    }
                }
            },
        ),
    )

    with pytest.raises(
        AgentComposeBoundaryError, match="agent_compose_response_contract_failed"
    ):
        client.start_governance_run(
            client_request_id="project:trigger:retry:2",
            environment={},
            session_id="b" * 64,
        )


def test_agent_compose_run_observation_fails_closed_for_unknown_status() -> None:
    assert AgentComposeRunStart(
        run_id="a" * 64, started=False, status="RUN_STATUS_FAILED"
    ).is_terminal
    assert not AgentComposeRunStart(
        run_id="a" * 64, started=False, status="RUN_STATUS_RUNNING"
    ).is_terminal
    assert not AgentComposeRunStart(
        run_id="a" * 64, started=False, status="future-status"
    ).is_terminal


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


def test_session_query_and_resume_preserve_the_authoritative_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(monkeypatch)
    session_id = "a" * 64
    calls: list[dict[str, Any]] = []
    responses = iter(
        [
            _Response(
                200,
                {"sandbox": {"sandboxId": session_id, "status": "SANDBOX_STATUS_STOPPED"}},
            ),
            _Response(
                200,
                {"sandbox": {"sandboxId": session_id, "status": "SANDBOX_STATUS_RUNNING"}},
            ),
        ]
    )

    def factory(**_kwargs: Any) -> _Client:
        return _Client(next(responses), calls)

    monkeypatch.setattr("app.integrations.agent_compose.httpx.Client", factory)
    client = AgentComposeClient()

    observed = client.get_session(session_id)
    resumed = client.resume_session(session_id)

    assert observed is not None
    assert observed.observation is AgentComposeSessionObservation.TERMINAL
    assert resumed.session_id == session_id
    assert resumed.observation is AgentComposeSessionObservation.RUNNING
    assert calls[0]["path"].endswith("GetSandbox")
    assert calls[1]["path"].endswith("ResumeSandbox")
    assert calls[1]["json"] == {"sandboxId": session_id}


def test_session_query_fails_closed_for_missing_and_unrecognized_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(monkeypatch)
    session_id = "b" * 64
    client = AgentComposeClient()

    _install_response(monkeypatch, _Response(404))
    assert client.get_session(session_id) is None

    _install_response(
        monkeypatch,
        _Response(
            200,
            {"sandbox": {"sandboxId": session_id, "status": "failed"}},
        ),
    )
    observed = client.get_session(session_id)
    assert observed is not None
    assert observed.observation is AgentComposeSessionObservation.UNKNOWN


def test_resume_session_maps_non_successful_responses_to_not_recoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(monkeypatch)
    client = AgentComposeClient()
    _install_response(monkeypatch, _Response(500))

    with pytest.raises(
        AgentComposeBoundaryError,
        match="agent_compose_session_not_recoverable",
    ):
        client.resume_session("c" * 64)


def test_retry_start_reuses_the_original_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_settings(monkeypatch)
    client = AgentComposeClient()
    session_id = "c" * 64
    request_id = "project:trigger:retry:2"
    expected_id = client.expected_run_id(request_id)
    calls: list[dict[str, Any]] = []
    responses = iter(
        [
            _Response(404),
            _Response(
                200,
                {
                    "run": {
                        "runId": expected_id,
                        "status": "RUNNING",
                        "sandboxId": session_id,
                    },
                    "started": True,
                },
            ),
        ]
    )

    def factory(**_kwargs: Any) -> _Client:
        return _Client(next(responses), calls)

    monkeypatch.setattr("app.integrations.agent_compose.httpx.Client", factory)

    result = client.start_governance_run(
        client_request_id=request_id,
        environment={},
        session_id=session_id,
    )

    assert result.started is True
    assert calls[1]["json"]["run"]["sandboxId"] == session_id


@pytest.mark.parametrize("sandbox_id", [None, "d" * 64])
def test_retry_start_preserves_the_requested_session_when_response_omits_it(
    monkeypatch: pytest.MonkeyPatch,
    sandbox_id: str | None,
) -> None:
    _configure_settings(monkeypatch)
    client = AgentComposeClient()
    session_id = "c" * 64
    request_id = "project:trigger:retry:2"
    expected_id = client.expected_run_id(request_id)
    summary: dict[str, Any] = {
        "runId": expected_id,
        "status": "RUNNING",
    }
    if sandbox_id is not None:
        summary["sandboxId"] = sandbox_id
    responses = iter(
        [
            _Response(404),
            _Response(
                200,
                {"run": summary, "started": True},
            ),
        ]
    )

    def factory(**_kwargs: Any) -> _Client:
        return _Client(next(responses), [])

    monkeypatch.setattr("app.integrations.agent_compose.httpx.Client", factory)

    if sandbox_id is None:
        result = client.start_governance_run(
            client_request_id=request_id,
            environment={},
            session_id=session_id,
        )
        assert result.session_id == session_id
    else:
        with pytest.raises(
            AgentComposeBoundaryError,
            match="agent_compose_response_contract_failed",
        ):
            client.start_governance_run(
                client_request_id=request_id,
                environment={},
                session_id=session_id,
            )


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
