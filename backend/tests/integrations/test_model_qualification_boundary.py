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
