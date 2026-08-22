import json
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from app.domain.model_qualification import (
    ModelBinding,
    ModelQualificationOutput,
    QualificationRunResult,
    evaluate_qualification,
    execute_model_qualification,
    model_binding,
    qualification_run_result_json,
)
from app.domain.models import ModelQualificationResult
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeRunStart,
)


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
        endpoint="http://127.0.0.1:8081/v1",
        model_identity="fake-model",
        protocol="chat_completions",
        config_revision="test-v1",
        runner_build_version="runner-v1",
        agent_compose_runtime_version="compose-v1",
        request_id="qualification-test",
    )

    assert result.status == "PASS"
    assert client.calls == [{"client_request_id": "qualification-test"}]
    stored = session.exec(select(ModelQualificationResult)).one()
    serialized = repr(stored.model_dump())
    assert "fixture-finding" not in serialized
    assert "127.0.0.1" not in serialized
    assert "prompt" not in serialized
    assert "provider" not in serialized
    assert "secret" not in serialized


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
        endpoint="http://127.0.0.1:8081/v1",
        model_identity="fake-model",
        protocol="chat_completions",
        config_revision="test-v1",
        runner_build_version="runner-v1",
        agent_compose_runtime_version="compose-v1",
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
            endpoint="http://127.0.0.1:8081/v1",
            model_identity="fake-model",
            protocol="chat_completions",
            config_revision="test-v1",
            runner_build_version="runner-v1",
            agent_compose_runtime_version="compose-v1",
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
        endpoint="http://127.0.0.1:8081/v1",
        model_identity="fake-model",
        protocol="chat_completions",
        config_revision="test-v1",
        runner_build_version="runner-v1",
        agent_compose_runtime_version="compose-v1",
        request_id="qualification-test",
    )

    assert result.status == "FAIL"
    assert result.failure_code == "model_binding_attestation_failed"
