import json
from typing import Any

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from app.domain.model_qualification import execute_model_qualification
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
        self, *, client_request_id: str, prompt: str
    ) -> AgentComposeRunStart:
        self.calls.append({"client_request_id": client_request_id, "prompt": prompt})
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


def _passing_output() -> str:
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


def test_execution_sends_only_the_fixed_fixture_and_persists_redacted_pass() -> None:
    session = _session()
    client = _Client(_passing_output())

    result = execute_model_qualification(
        session=session,
        client=client,
        endpoint="http://127.0.0.1:8081/v1",
        model_identity="fake-model",
        protocol="chat_completions",
        config_revision="test-v1",
        request_id="qualification-test",
    )

    assert result.status == "PASS"
    assert "fixture-finding-1" in client.calls[0]["prompt"]
    assert "customer" in client.calls[0]["prompt"].lower()
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
            self, *, client_request_id: str, prompt: str
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
            request_id="qualification-test",
        )

        assert result.status == "FAIL"
        assert result.failure_code == "model_output_invalid"
