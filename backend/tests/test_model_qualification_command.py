from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

import app.model_qualification as command
from app.core.config import settings


class _Session:
    def __init__(self, engine: object) -> None:
        self.engine = engine

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


@pytest.mark.parametrize(
    ("status", "failure_code", "expected_code", "expected_output"),
    [
        ("PASS", None, 0, "model qualification: PASS\n"),
        (
            "FAIL",
            "quality_gate_failed",
            1,
            "model qualification: FAIL (quality_gate_failed)\n",
        ),
    ],
)
def test_command_reports_only_the_redacted_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    failure_code: str | None,
    expected_code: int,
    expected_output: str,
) -> None:
    binding = object()
    client = object()
    invocation: dict[str, Any] = {}

    monkeypatch.setattr(settings, "MODEL_API_KEY", SecretStr("test-secret"))
    monkeypatch.setattr(command, "model_binding", lambda **_kwargs: binding)
    monkeypatch.setattr(command, "Session", _Session)
    monkeypatch.setattr(command, "AgentComposeClient", lambda: client)

    def execute(**kwargs: Any) -> SimpleNamespace:
        invocation.update(kwargs)
        return SimpleNamespace(status=status, failure_code=failure_code)

    monkeypatch.setattr(command, "execute_model_qualification", execute)

    assert command.main() == expected_code
    assert capsys.readouterr().out == expected_output
    assert invocation["binding"] is binding
    assert invocation["client"] is client
    assert isinstance(invocation["session"], _Session)
    assert invocation["request_id"].startswith("model-qualification:")
    assert "test-secret" not in expected_output


def test_command_fails_before_starting_a_run_when_secret_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(settings, "MODEL_API_KEY", SecretStr(""))
    monkeypatch.setattr(command, "model_binding", lambda **_kwargs: object())
    monkeypatch.setattr(
        command,
        "execute_model_qualification",
        lambda **_kwargs: pytest.fail("qualification must not start"),
    )

    assert command.main() == 1
    assert capsys.readouterr().out == (
        "model qualification: FAIL (configuration_invalid)\n"
    )
