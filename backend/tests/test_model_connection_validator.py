# mypy: disable-error-code="attr-defined"

import json
import sys
import uuid
from types import SimpleNamespace

import pytest

import app.model_connection_validator as validator


class _Session:
    def __init__(self, op: object) -> None:
        self.op = op

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get(self, _model: object, _id: object) -> object:
        return self.op

    def add(self, _: object) -> None:
        return None

    def commit(self) -> None:
        return None

    def refresh(self, _: object) -> None:
        return None

    def expunge(self, _: object) -> None:
        return None

    def exec(self, _: object) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: [])


@pytest.mark.parametrize("v2_failed", [False, True])
def test_main_runs_all_fixed_checks_and_persists_pass(
    monkeypatch: pytest.MonkeyPatch,
    v2_failed: bool,
) -> None:
    operation_id = uuid.uuid4()
    run_id, sandbox = "run", "a" * 64
    op = SimpleNamespace(
        id=operation_id,
        agent_run_id=run_id,
        connection_id=uuid.uuid4(),
        session_id=None,
        status="PENDING",
        evidence=None,
    )
    version = SimpleNamespace(runner_build_version="runner", runtime_spec_hash="sha256:x")
    binding = SimpleNamespace(config_fingerprint="f" * 64)
    saved: list[dict[str, object]] = []
    budgets: list[tuple[str, int, int]] = []
    monkeypatch.setattr(validator.settings, "AI_INVESTIGATION_MAX_OUTPUT_BYTES", 4096)
    monkeypatch.setattr(validator.settings, "AI_ANALYSIS_REPORT_MAX_OUTPUT_BYTES", 16384)
    monkeypatch.setenv("MODEL_VALIDATION_OPERATION_ID", str(operation_id))
    monkeypatch.setenv("MODEL_VALIDATION_RUN_ID", run_id)
    monkeypatch.setenv("SANDBOX_ID", sandbox)
    monkeypatch.setattr(validator, "Session", lambda _: _Session(op))
    monkeypatch.setattr(validator.service, "state_for_write", lambda _: None)
    monkeypatch.setattr(validator.service, "validation_binding", lambda *_: binding)
    monkeypatch.setattr(validator.service, "get_version", lambda *_: version)
    monkeypatch.setattr(validator, "_runner_build_version", lambda: "runner")
    monkeypatch.setattr(
        validator, "client_for_version", lambda _: SimpleNamespace(get_run=lambda _: SimpleNamespace(is_active=True, session_id=sandbox))
    )
    monkeypatch.setattr(validator, "transport_binding", lambda binding, _: (binding, "lease"))
    monkeypatch.setattr(validator, "_start_provider_proxy", lambda *_args, **_kwargs: (SimpleNamespace(shutdown=lambda: None, server_close=lambda: None, server_port=1), SimpleNamespace(join=lambda: None)))
    monkeypatch.setattr(validator, "_run_qualification", lambda *_: sys.stdout.write(json.dumps({"config_fingerprint": "f" * 64, "fixture_version": "x", "status": "PASS", "availability_numerator": 4, "availability_denominator": 4, "traceable_citations": 1, "total_citations": 1, "hallucination_count": 0, "finding_modification_count": 0, "unauthorized_side_effect_count": 0, "failure_code": None})))
    def run(
        *, task: str, max_output_bytes: int, max_tool_calls: int, **_: object
    ) -> dict[str, bool]:
        budgets.append((task, max_output_bytes, max_tool_calls))
        return {"fixture": True}

    monkeypatch.setattr(validator, "run_pi_investigation", run)
    monkeypatch.setattr(validator.QualificationRunResult, "model_validate_json", lambda _: SimpleNamespace(config_fingerprint="f" * 64, evaluation=lambda: SimpleNamespace(status="PASS")))
    monkeypatch.setattr("app.domain.ai_investigations.validate_output", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.domain.ai_analysis_reports.validate_output", lambda *_args, **_kwargs: None)
    def validate_v2(*_args: object, **_kwargs: object) -> None:
        if v2_failed:
            raise ValueError("model_output_invalid")

    monkeypatch.setattr(validator.v2, "validate_output", validate_v2)
    monkeypatch.setattr(validator.service, "finish_validation", lambda _s, _id, evidence, failure=None: saved.append({"evidence": evidence, "failure": failure}))

    assert validator.main() == (1 if v2_failed else 0)
    assert budgets == [("investigation", 4096, 2), ("analysis_report", 16384, 2), ("analysis_report", 16384, 2)]
    if v2_failed:
        assert saved[0]["failure"] == "model_connection_validation_failed"
        evidence = saved[0]["evidence"]
        assert isinstance(evidence, dict)
        assert evidence["analysis_report"] == "NOT_RUN"
        assert evidence["analysis_report_v2"] == "NOT_RUN"
        return
    assert saved == [{"evidence": {**op.evidence, "qualification": "PASS", "investigation": "PASS", "analysis_report": "PASS", "analysis_report_v2": "PASS"}, "failure": None}]


def test_main_marks_failed_when_runtime_cannot_be_attested(monkeypatch: pytest.MonkeyPatch) -> None:
    operation_id = uuid.uuid4()
    op = SimpleNamespace(id=operation_id, agent_run_id="run", connection_id=uuid.uuid4(), session_id=None, status="PENDING", evidence=None)
    failures: list[str | None] = []
    monkeypatch.setenv("MODEL_VALIDATION_OPERATION_ID", str(operation_id))
    monkeypatch.setenv("MODEL_VALIDATION_RUN_ID", "run")
    monkeypatch.setenv("SANDBOX_ID", "a" * 64)
    monkeypatch.setattr(validator, "Session", lambda _: _Session(op))
    monkeypatch.setattr(validator.service, "state_for_write", lambda _: None)
    monkeypatch.setattr(validator.service, "validation_binding", lambda *_: SimpleNamespace(config_fingerprint="f" * 64))
    monkeypatch.setattr(validator.service, "get_version", lambda *_: SimpleNamespace(runner_build_version="runner", runtime_spec_hash="sha256:x"))
    monkeypatch.setattr(validator, "_runner_build_version", lambda: "runner")
    monkeypatch.setattr(validator, "client_for_version", lambda _: SimpleNamespace(get_run=lambda _: None))
    monkeypatch.setattr(validator.service, "finish_validation", lambda _s, _id, _evidence, failure=None: failures.append(failure))

    assert validator.main() == 1
    assert failures == ["model_connection_validation_failed"]
