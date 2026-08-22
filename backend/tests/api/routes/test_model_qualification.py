import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlmodel import Session

from app.core.config import settings
from app.domain.model_qualification import (
    QualificationEvaluation,
    model_config_fingerprint,
    persist_qualification_result,
)


def test_status_fails_closed_and_invalidates_on_configuration_drift(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MODEL_API_ENDPOINT", "http://127.0.0.1/v1")
    monkeypatch.setattr(settings, "MODEL_IDENTITY", "customer-model")
    monkeypatch.setattr(settings, "MODEL_API_PROTOCOL", "chat_completions")
    monkeypatch.setattr(settings, "MODEL_CONFIG_REVISION", "v1")
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "runner-v1")
    monkeypatch.setattr(settings, "AGENT_COMPOSE_RUNTIME_VERSION", "compose-v1")
    monkeypatch.setattr(settings, "MODEL_API_KEY", SecretStr("fixture-secret"))

    response = client.get(
        f"{settings.API_V1_STR}/model-qualification/status",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert response.json() == {"qualified": False}

    persist_qualification_result(
        session=db,
        endpoint=settings.MODEL_API_ENDPOINT,
        model_identity=settings.MODEL_IDENTITY,
        config_fingerprint=model_config_fingerprint(
            endpoint=settings.MODEL_API_ENDPOINT,
            model_identity=settings.MODEL_IDENTITY,
            protocol=settings.MODEL_API_PROTOCOL,
            config_revision=settings.MODEL_CONFIG_REVISION,
            runner_build_version=settings.RUNNER_BUILD_VERSION,
            agent_compose_runtime_version=settings.AGENT_COMPOSE_RUNTIME_VERSION,
        ),
        agent_compose_run_id="d" * 64,
        evaluation=QualificationEvaluation(
            fixture_version="model-qualification-v1",
            status="PASS",
            availability_numerator=3,
            availability_denominator=4,
            traceable_citations=4,
            total_citations=4,
            hallucination_count=0,
            finding_modification_count=0,
            unauthorized_side_effect_count=0,
            failure_code=None,
        ),
    )
    assert client.get(
        f"{settings.API_V1_STR}/model-qualification/status",
        headers=superuser_token_headers,
    ).json() == {"qualified": True}

    monkeypatch.setattr(settings, "MODEL_CONFIG_REVISION", "v2")
    assert client.get(
        f"{settings.API_V1_STR}/model-qualification/status",
        headers=superuser_token_headers,
    ).json() == {"qualified": False}
