import os
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_qualification_agent_is_pi_only_internal_and_toolless() -> None:
    compose = (REPOSITORY_ROOT / "agent-compose.yml").read_text()
    qualifier = compose.split("  model-qualifier:\n", maxsplit=1)[1]

    assert "    provider: pi\n" in qualifier
    assert "    model: customer/${MODEL_IDENTITY}\n" in qualifier
    assert "      LLM_API_ENDPOINT: ${MODEL_API_ENDPOINT}\n" in qualifier
    assert "      LLM_API_PROTOCOL: ${MODEL_API_PROTOCOL}\n" in qualifier
    assert "        value: ${MODEL_API_KEY}\n" in qualifier
    assert "      MODEL_IDENTITY: ${MODEL_IDENTITY}\n" in qualifier
    assert "      MODEL_CONFIG_REVISION: ${MODEL_CONFIG_REVISION}\n" in qualifier
    assert "      AGENT_COMPOSE_RUNTIME_VERSION: ${AGENT_COMPOSE_RUNTIME_VERSION}\n" in qualifier
    assert (
        "      MODEL_QUALIFICATION_TIMEOUT_SECONDS: "
        "${MODEL_QUALIFICATION_TIMEOUT_SECONDS}\n" in qualifier
    )
    assert "        secret: true\n" in qualifier
    assert "codex" not in qualifier.lower()
    assert "fallback" not in qualifier.lower()
    assert "scheduler" not in qualifier.lower()

    runner_dockerfile = (REPOSITORY_ROOT / "backend/Dockerfile.runner").read_text()
    assert "pi-with-tools --no-tools" in runner_dockerfile
    assert '"retry":{"enabled":false' in runner_dockerfile

    integration = (
        REPOSITORY_ROOT / "backend/app/integrations/agent_compose.py"
    ).read_text()
    assert "/app/.venv/bin/python -m app.model_qualification_runner" in integration


def test_renderer_resolves_the_complete_qualification_configuration(
    tmp_path: Path,
) -> None:
    rendered = tmp_path / "agent-compose.yml"
    environment = os.environ | {
        "AGENT_COMPOSE_RUNTIME_VERSION": "compose-v1",
        "ARTIFACT_HOST_PATH": "/tmp/artifacts",
        "CLOUDATLAS_CAPSET_TOKEN": "cloudatlas-token",
        "DOCKER_IMAGE_RUNNER": "governance-runner",
        "ENVIRONMENT": "local",
        "FIRST_SUPERUSER": "fixture@example.com",
        "FIRST_SUPERUSER_PASSWORD": "admin-password",
        "MODEL_API_ENDPOINT": "http://model-fixture:8080/v1",
        "MODEL_API_KEY": "model-secret",
        "MODEL_API_PROTOCOL": "chat_completions",
        "MODEL_CONFIG_REVISION": "fixture-v1",
        "MODEL_IDENTITY": "fixture-model",
        "MODEL_QUALIFICATION_TIMEOUT_SECONDS": "17",
        "POSTGRES_DB": "app",
        "POSTGRES_PASSWORD": "postgres-password",
        "POSTGRES_USER": "postgres",
        "PROJECT_NAME": "Exposure-Agent",
        "RUNNER_BUILD_VERSION": "runner-v1",
        "SECRET_KEY": "application-secret",
    }

    subprocess.run(
        [
            "sh",
            str(REPOSITORY_ROOT / "scripts/render-agent-compose-config.sh"),
            str(REPOSITORY_ROOT / "agent-compose.yml"),
            str(rendered),
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    configuration = rendered.read_text()
    assert "${" not in configuration
    qualifier = configuration.split("  model-qualifier:\n", maxsplit=1)[1]
    assert "    model: customer/fixture-model\n" in qualifier
    assert "      LLM_API_ENDPOINT: http://model-fixture:8080/v1\n" in qualifier
    assert "        value: model-secret\n" in qualifier
    assert "      MODEL_QUALIFICATION_TIMEOUT_SECONDS: 17\n" in qualifier
