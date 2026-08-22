#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
docker compose -f compose.yml build governance-runner-image
exec docker compose -f compose.yml run --rm --no-deps \
  --volume "$PWD/tests/model_qualification_fixture:/app/tests/model_qualification_fixture:ro" \
  --entrypoint /app/.venv/bin/python governance-runner-image \
  /app/tests/model_qualification_fixture/verify.py
