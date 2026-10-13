import sys
import uuid
from types import SimpleNamespace

import pytest

from app import netflow_processing_runner as runner


class FakeSession:
    def __init__(self, rows: list[object | None]):
        self.rows = iter(rows)

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, *_: object) -> object | None:
        return next(self.rows)


def configure(
    monkeypatch: pytest.MonkeyPatch, rows: list[object | None]
) -> tuple[str, str, uuid.UUID]:
    analysis_id = uuid.uuid4()
    run_id, session_id = "a" * 64, "b" * 64
    monkeypatch.setattr(runner, "Session", lambda _: FakeSession(rows))
    monkeypatch.setattr(
        runner, "Path", lambda _: SimpleNamespace(read_text=lambda: "test-build\n")
    )
    monkeypatch.setattr(
        runner,
        "settings",
        SimpleNamespace(
            governance_runner_build_version="test-build",
            NETFLOW_BULK_RSS_BYTES=1,
            NETFLOW_BULK_TIMEOUT_SECONDS=1,
        ),
    )
    monkeypatch.setenv("NETFLOW_ANALYSIS_ID", str(analysis_id))
    monkeypatch.setenv("NETFLOW_ANALYSIS_RUN_ID", run_id)
    monkeypatch.setenv("SANDBOX_ID", session_id)
    monkeypatch.setattr(sys, "argv", ["runner"])
    return run_id, session_id, analysis_id


def test_runner_rejects_argv_identity_and_build_before_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["runner", "extra"])
    assert runner.main() == 1
    monkeypatch.setattr(sys, "argv", ["runner"])
    monkeypatch.setenv("NETFLOW_ANALYSIS_ID", "not-a-uuid")
    assert runner.main() == 1
    configure(monkeypatch, [])

    def unexpected_session(*_args: object) -> object:
        pytest.fail("invalid identity reached the database")

    monkeypatch.setattr(runner, "Session", unexpected_session)
    monkeypatch.setenv("NETFLOW_ANALYSIS_RUN_ID", "invalid-run")
    assert runner.main() == 1
    monkeypatch.setenv("NETFLOW_ANALYSIS_RUN_ID", "a" * 64)
    monkeypatch.setenv("SANDBOX_ID", "invalid-session")
    assert runner.main() == 1
    monkeypatch.setenv("SANDBOX_ID", "b" * 64)
    monkeypatch.setattr(
        runner, "Path", lambda _: SimpleNamespace(read_text=lambda: "other-build")
    )
    assert runner.main() == 1


def test_runner_dispatches_legacy_only_when_result_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reserved, completed = (
        SimpleNamespace(identity={}),
        SimpleNamespace(status="SUCCEEDED"),
    )
    run_id, session_id, analysis_id = configure(monkeypatch, [reserved, completed])
    calls: list[tuple[object, uuid.UUID, str, str]] = []
    monkeypatch.setattr(
        runner,
        "execute_analysis",
        lambda session, analysis, run, sandbox: calls.append(
            (session, analysis, run, sandbox)
        ),
    )
    assert runner.main() == 0
    assert calls and calls[0][1:] == (analysis_id, run_id, session_id)


def test_runner_dispatches_bulk_with_mocked_linux_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reserved = SimpleNamespace(identity={"backend": "netflow-bulk-v1"})
    completed = SimpleNamespace(status="SUCCEEDED_WITH_WARNINGS")
    run_id, session_id, analysis_id = configure(monkeypatch, [reserved, completed])
    import resource

    import app.domain.netflow_bulk as bulk

    calls: list[tuple[object, uuid.UUID, str, str]] = []
    limits: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr(
        bulk,
        "execute",
        lambda session, analysis, run, sandbox: calls.append(
            (session, analysis, run, sandbox)
        ),
    )
    monkeypatch.setattr(
        resource, "setrlimit", lambda kind, value: limits.append((kind, value))
    )
    monkeypatch.setattr(sys, "platform", "linux")
    settings = runner.__dict__["settings"]
    monkeypatch.setattr(settings, "NETFLOW_BULK_RSS_BYTES", 123)
    monkeypatch.setattr(settings, "NETFLOW_BULK_TIMEOUT_SECONDS", 7)
    assert runner.main() == 0
    assert calls and calls[0][1:] == (analysis_id, run_id, session_id)
    assert limits == [(resource.RLIMIT_AS, (492, 492)), (resource.RLIMIT_CPU, (37, 37))]


def test_runner_failure_is_quiet_and_never_reports_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(monkeypatch, [SimpleNamespace(identity={})])
    monkeypatch.setattr(
        runner,
        "execute_analysis",
        lambda *args: (_ for _ in ()).throw(RuntimeError("source row")),
    )
    assert runner.main() == 1
    assert capsys.readouterr().out == ""
