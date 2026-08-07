#!/usr/bin/env bash
set -euo pipefail

: "${SECRET_KEY:?SECRET_KEY is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${FIRST_SUPERUSER:?FIRST_SUPERUSER is required}"
: "${FIRST_SUPERUSER_PASSWORD:?FIRST_SUPERUSER_PASSWORD is required}"

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
    expected = os.environ[name]
    for service in ("prestart", "backend", "agent-compose-project-init"):
        require_equal(service, name, expected)

require_equal("db", "POSTGRES_PASSWORD", os.environ["POSTGRES_PASSWORD"])
for name in ("FIRST_SUPERUSER", "FIRST_SUPERUSER_PASSWORD"):
    require_equal("playwright", name, os.environ[name])

for name in ("POSTGRES_DB", "POSTGRES_USER"):
    expected = service_environment("db").get(name)
    require_equal("agent-compose-project-init", name, expected)

print("Compose CI credential parity passed")
'
