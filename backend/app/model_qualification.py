from __future__ import annotations

import sys
import uuid

from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.domain.model_qualification import (
    execute_model_qualification,
    model_binding,
)
from app.integrations.agent_compose import AgentComposeClient


def main() -> int:
    try:
        binding = model_binding(
            endpoint=settings.MODEL_API_ENDPOINT,
            model_identity=settings.MODEL_IDENTITY,
            protocol=settings.MODEL_API_PROTOCOL,
            config_revision=settings.MODEL_CONFIG_REVISION,
            runner_build_version=settings.RUNNER_BUILD_VERSION,
            agent_compose_runtime_version=settings.AGENT_COMPOSE_RUNTIME_VERSION,
        )
        if not settings.MODEL_API_KEY.get_secret_value():
            raise ValueError("model_configuration_invalid")
    except ValueError:
        sys.stdout.write("model qualification: FAIL (configuration_invalid)\n")
        return 1

    with Session(engine) as session:
        result = execute_model_qualification(
            session=session,
            client=AgentComposeClient(),
            endpoint=binding.endpoint,
            model_identity=binding.model_identity,
            protocol=binding.protocol,
            config_revision=binding.config_revision,
            runner_build_version=binding.runner_build_version,
            agent_compose_runtime_version=binding.agent_compose_runtime_version,
            request_id=f"model-qualification:{uuid.uuid4().hex}",
            timeout_seconds=settings.MODEL_QUALIFICATION_TIMEOUT_SECONDS,
        )
    if result.status == "PASS":
        sys.stdout.write("model qualification: PASS\n")
        return 0
    sys.stdout.write(f"model qualification: FAIL ({result.failure_code})\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
