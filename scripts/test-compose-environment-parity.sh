#!/usr/bin/env bash
set -euo pipefail

: "${AGENT_COMPOSE_RUNTIME_VERSION:=sha256:092f8c4fbf7254ddd200a36d99ae6583cd08f5ddeda9cafd559b3636890c9670}"
export AGENT_COMPOSE_RUNTIME_VERSION

compose_config="$(docker compose -f compose.yml -f compose.override.yml config --format json)"

printf '%s' "$compose_config" | python3 -c '
import json
import os
import sys

services = json.load(sys.stdin)["services"]


def service_environment(service: str) -> dict[str, str]:
    environment = services[service].get("environment", {})
    if isinstance(environment, dict):
        return environment
    return dict(item.split("=", 1) for item in environment)


def require_equal(service: str, name: str, expected: str) -> None:
    actual = service_environment(service).get(name)
    if actual != expected:
        raise SystemExit(f"{service}.{name} is not propagated from CI")

for name in (
    "SECRET_KEY",
    "POSTGRES_PASSWORD",
    "FIRST_SUPERUSER",
    "FIRST_SUPERUSER_PASSWORD",
):
    source_service = "db" if name == "POSTGRES_PASSWORD" else "backend"
    expected = os.environ.get(name) or service_environment(source_service).get(name)
    if expected is None:
        raise SystemExit(f"{name} is missing from the resolved Compose config")
    for service in ("prestart", "backend", "agent-compose-project-init"):
        require_equal(service, name, expected)

postgres_password = service_environment("db").get("POSTGRES_PASSWORD")
if postgres_password is None:
    raise SystemExit("db.POSTGRES_PASSWORD is missing")
require_equal("db", "POSTGRES_PASSWORD", postgres_password)
for name in ("FIRST_SUPERUSER", "FIRST_SUPERUSER_PASSWORD"):
    expected = os.environ.get(name) or service_environment("backend").get(name)
    if expected is None:
        raise SystemExit(f"backend.{name} is missing")
    require_equal("playwright", name, expected)
require_equal(
    "playwright",
    "CLOUDATLAS_CAPSET_TOKEN",
    service_environment("backend").get("CLOUDATLAS_CAPSET_TOKEN"),
)

for name in ("POSTGRES_DB", "POSTGRES_USER"):
    expected = service_environment("db").get(name)
    require_equal("agent-compose-project-init", name, expected)

for name in ("AGENT_COMPOSE_AUTH_TOKEN",):
    expected = service_environment("agent-compose").get(name)
    require_equal("agent-compose-project-init", name, expected)

for name in (
    "CLOUDATLAS_CAPSET_TOKEN",
    "AGENT_COMPOSE_RUNTIME_VERSION",
    "RUNNER_BUILD_VERSION",
    "MODEL_API_ENDPOINT",
    "MODEL_API_PROTOCOL",
    "MODEL_API_KEY",
    "MODEL_IDENTITY",
    "MODEL_CONFIG_REVISION",
    "MODEL_QUALIFICATION_TIMEOUT_SECONDS",
):
    expected = service_environment("backend").get(name)
    require_equal("agent-compose-project-init", name, expected)

project_environment = service_environment("agent-compose-project-init")
runner_image = services["governance-runner-image"]["image"]
runner_image_name = project_environment["DOCKER_IMAGE_RUNNER"]
runner_version = project_environment["RUNNER_BUILD_VERSION"]
expected_runner_image = f"{runner_image_name}:{runner_version}"
if runner_image != expected_runner_image:
    raise SystemExit("agent-compose runner image does not match the Compose build")

artifact_path = project_environment["ARTIFACT_HOST_PATH"]
for service in ("agent-compose", "backend"):
    sources = {
        mount["source"]
        for mount in services[service].get("volumes", [])
        if mount.get("type") == "bind"
    }
    if artifact_path not in sources:
        raise SystemExit(f"{service} does not use the configured Artifact bind path")

print("Compose CI credential parity passed")
'

optional_model_config="$(
  MODEL_API_ENDPOINT= MODEL_API_KEY= MODEL_IDENTITY= \
    docker compose -f compose.yml config --format json
)"
printf '%s' "$optional_model_config" | python3 -c '
import json
import sys

services = json.load(sys.stdin)["services"]
for service in ("backend", "agent-compose-project-init"):
    environment = services[service]["environment"]
    assert environment["MODEL_API_ENDPOINT"] == "http://127.0.0.1:9/v1"
    assert environment["MODEL_API_KEY"] == ""
    assert environment["MODEL_IDENTITY"] == "unconfigured"
    assert environment["MODEL_QUALIFICATION_TIMEOUT_SECONDS"] == "120"
print("Optional model configuration passed")
'
