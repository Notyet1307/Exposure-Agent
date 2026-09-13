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


def test_main_runs_all_fixed_checks_and_persists_pass(
    monkeypatch: pytest.MonkeyPatch,
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
    monkeypatch.setattr(validator, "run_pi_investigation", lambda **_: {"fixture": True})
    monkeypatch.setattr(validator.QualificationRunResult, "model_validate_json", lambda _: SimpleNamespace(config_fingerprint="f" * 64, evaluation=lambda: SimpleNamespace(status="PASS")))
    monkeypatch.setattr("app.domain.ai_investigations.validate_output", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.domain.ai_analysis_reports.validate_output", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(validator.service, "finish_validation", lambda _s, _id, evidence, failure=None: saved.append({"evidence": evidence, "failure": failure}))

    assert validator.main() == 0
    assert saved == [{"evidence": {**op.evidence, "qualification": "PASS", "investigation": "PASS", "analysis_report": "PASS"}, "failure": None}]


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
