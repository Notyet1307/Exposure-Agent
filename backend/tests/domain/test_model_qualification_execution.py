import json
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select, text

from app.domain.model_qualification import (
    ModelBinding,
    ModelQualificationOutput,
    QualificationRunResult,
    evaluate_qualification,
    execute_model_qualification,
    model_binding,
    qualification_run_result_json,
)
from app.domain.models import AuditEvent, ModelQualificationResult
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeRunStart,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(*_args: object, **_kwargs: object) -> str:
    return "JSON"


class _Client:
    def __init__(
        self, output: str | None, status: str = "RUN_STATUS_SUCCEEDED"
    ) -> None:
        self.output = output
        self.status = status
        self.calls: list[dict[str, Any]] = []

    def start_model_qualification(
        self, *, client_request_id: str
    ) -> AgentComposeRunStart:
        self.calls.append({"client_request_id": client_request_id})
        return AgentComposeRunStart(
            run_id="a" * 64,
            started=True,
            status=self.status,
            output=self.output,
        )

    def get_run(self, run_id: str) -> AgentComposeRunStart | None:
        return AgentComposeRunStart(
            run_id=run_id,
            started=False,
            status=self.status,
            output=self.output,
        )


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ModelQualificationResult.__table__.create(engine)  # type: ignore[attr-defined]
    AuditEvent.__table__.create(engine)  # type: ignore[attr-defined]
    return Session(engine)


def _passing_model_output() -> str:
    actions = (
        "CONFIRM_ASSET_OWNER",
        "ADD_AUTHENTICATED_SCAN",
        "VERIFY_NETWORK_ROUTE",
        "CONFIRM_SERVICE_EXPOSURE",
    )
    return json.dumps(
        {
            "recommendations": [
                {
                    "finding_id": f"fixture-finding-{number}",
                    "action_code": action,
                    "claims": [
                        {
                            "claim_id": f"fixture-claim-{number}",
                            "evidence_ids": [f"fixture-evidence-{number}"],
                        }
                    ],
                    "finding_modified": False,
                }
                for number, action in enumerate(actions, start=1)
            ],
            "unsupported_claims": [],
            "unauthorized_side_effects": [],
        }
    )


def _binding(*, runner_build_version: str = "runner-v1") -> ModelBinding:
    return model_binding(
        endpoint="http://127.0.0.1:8081/v1",
        model_identity="fake-model",
        protocol="chat_completions",
        config_revision="test-v1",
        runner_build_version=runner_build_version,
        agent_compose_runtime_version="compose-v1",
    )


def _passing_run_output(*, runner_build_version: str = "runner-v1") -> str:
    evaluation = evaluate_qualification(
        ModelQualificationOutput.model_validate_json(_passing_model_output())
    )
    return qualification_run_result_json(
        binding=_binding(runner_build_version=runner_build_version),
        evaluation=evaluation,
    )


def test_execution_runs_a_fixed_command_and_persists_redacted_attested_pass() -> None:
    session = _session()
    client = _Client(_passing_run_output())

    result = execute_model_qualification(
        session=session,
        client=client,
        binding=_binding(),
        request_id="qualification-test",
    )

    assert result.status == "PASS"
    assert client.calls == [{"client_request_id": "qualification-test"}]
    stored = session.exec(select(ModelQualificationResult)).one()
    audits = session.exec(
        select(AuditEvent).where(AuditEvent.target_id == stored.id)
    ).all()
    assert [event.action for event in audits] == [
        "model_qualification.triggered",
        "model_qualification.completed",
    ]
    assert {(event.actor_type, event.actor_subject) for event in audits} == {
        ("system", "model-qualification-command")
    }
    assert audits[0].after_data == {
        "config_fingerprint": stored.config_fingerprint,
        "fixture_version": "model-qualification-v1",
    }
    assert audits[1].after_data == {
        "config_fingerprint": stored.config_fingerprint,
        "failure_code": None,
        "fixture_version": "model-qualification-v1",
        "status": "PASS",
    }
    serialized = repr(
        {
            "result": stored.model_dump(),
            "audits": [event.model_dump() for event in audits],
        }
    )
    assert "fixture-finding" not in serialized
    assert "127.0.0.1" not in serialized
    assert "prompt" not in serialized
    assert "provider" not in serialized
    assert "secret" not in serialized


def test_execution_stops_when_trigger_audit_cannot_be_written() -> None:
    session = _session()
    session.execute(
        text(
            "CREATE TRIGGER reject_qualification_trigger "
            "BEFORE INSERT ON audit_events "
            "WHEN NEW.action = 'model_qualification.triggered' "
            "BEGIN SELECT RAISE(ABORT, 'audit rejected'); END"
        )
    )
    session.commit()
    client = _Client(_passing_run_output())

    with pytest.raises(SQLAlchemyError, match="audit rejected"):
        execute_model_qualification(
            session=session,
            client=client,
            binding=_binding(),
            request_id="qualification-test",
        )

    assert client.calls == []
    assert session.exec(select(AuditEvent)).all() == []


def test_result_rolls_back_when_completion_audit_cannot_be_written() -> None:
    session = _session()
    session.execute(
        text(
            "CREATE TRIGGER reject_qualification_completion "
            "BEFORE INSERT ON audit_events "
            "WHEN NEW.action = 'model_qualification.completed' "
            "BEGIN SELECT RAISE(ABORT, 'audit rejected'); END"
        )
    )
    session.commit()

    with pytest.raises(SQLAlchemyError, match="audit rejected"):
        execute_model_qualification(
            session=session,
            client=_Client(_passing_run_output()),
            binding=_binding(),
            request_id="qualification-test",
        )

    assert session.exec(select(ModelQualificationResult)).all() == []
    assert [event.action for event in session.exec(select(AuditEvent)).all()] == [
        "model_qualification.triggered"
    ]


def test_agent_compose_start_failure_has_no_fabricated_run_id() -> None:
    class UnavailableClient(_Client):
        def start_model_qualification(
            self, *, client_request_id: str
        ) -> AgentComposeRunStart:
            raise AgentComposeBoundaryError("agent_compose_unavailable")

    result = execute_model_qualification(
        session=_session(),
        client=UnavailableClient(None),
        binding=_binding(),
        request_id="qualification-test",
    )

    assert result.status == "FAIL"
    assert result.failure_code == "agent_compose_failed"
    assert result.agent_compose_run_id is None
    assert ModelQualificationResult.__table__.c.agent_compose_run_id.nullable  # type: ignore[attr-defined]


def test_timeout_uses_the_fail_closed_contract_code() -> None:
    result = execute_model_qualification(
        session=_session(),
        client=_Client(None, status="RUN_STATUS_RUNNING"),
        binding=_binding(),
        request_id="qualification-test",
        timeout_seconds=0,
    )

    assert result.status == "FAIL"
    assert result.failure_code == "timeout"


def test_missing_observed_run_uses_the_fail_closed_contract_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingRunClient(_Client):
        def get_run(self, run_id: str) -> AgentComposeRunStart | None:
            return None

    monkeypatch.setattr("app.domain.model_qualification.time.sleep", lambda _: None)
    result = execute_model_qualification(
        session=_session(),
        client=MissingRunClient(None, status="RUN_STATUS_RUNNING"),
        binding=_binding(),
        request_id="qualification-test",
    )

    assert result.status == "FAIL"
    assert result.failure_code == "result_missing"


def test_agent_compose_observation_failure_persists_fail_closed() -> None:
    class UnavailableClient(_Client):
        def start_model_qualification(
            self, *, client_request_id: str
        ) -> AgentComposeRunStart:
            return AgentComposeRunStart(
                run_id="e" * 64,
                started=True,
                status="RUN_STATUS_RUNNING",
            )

        def get_run(self, run_id: str) -> AgentComposeRunStart | None:
            raise AgentComposeBoundaryError("agent_compose_unavailable")

    result = execute_model_qualification(
        session=_session(),
        client=UnavailableClient(None),
        binding=_binding(),
        request_id="qualification-test",
    )

    assert result.status == "FAIL"
    assert result.failure_code == "agent_compose_failed"


def test_invalid_or_missing_provider_output_persists_fail_closed() -> None:
    for output in (None, "not-json"):
        session = _session()
        result = execute_model_qualification(
            session=session,
            client=_Client(output),
            binding=_binding(),
            request_id="qualification-test",
        )

        assert result.status == "FAIL"
        assert result.failure_code == "model_output_invalid"


def test_pass_aggregate_must_cover_the_complete_fixed_fixture() -> None:
    aggregate = json.loads(_passing_run_output())
    aggregate.update(
        {
            "availability_numerator": 1,
            "availability_denominator": 1,
            "traceable_citations": 1,
            "total_citations": 1,
        }
    )

    with pytest.raises(ValidationError, match="fixed fixture coverage"):
        QualificationRunResult.model_validate(aggregate)


def test_runtime_attestation_mismatch_fails_closed() -> None:
    result = execute_model_qualification(
        session=_session(),
        client=_Client(_passing_run_output(runner_build_version="stale-runner")),
        binding=_binding(),
        request_id="qualification-test",
    )

    assert result.status == "FAIL"
    assert result.failure_code == "model_binding_attestation_failed"
