#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
: "${AGENT_COMPOSE_RUNTIME_VERSION:=sha256:092f8c4fbf7254ddd200a36d99ae6583cd08f5ddeda9cafd559b3636890c9670}"
: "${RUNNER_BUILD_VERSION:=model-qualification-fixture}"
export AGENT_COMPOSE_RUNTIME_VERSION RUNNER_BUILD_VERSION

image="exposure-agent-model-qualification-fixture:$RUNNER_BUILD_VERSION"
docker build --file backend/Dockerfile.runner \
  --build-arg "RUNNER_BUILD_VERSION=$RUNNER_BUILD_VERSION" --tag "$image" .
exec docker run --rm \
  --volume "$PWD/tests/model_qualification_fixture:/app/tests/model_qualification_fixture:ro" \
  --entrypoint /app/.venv/bin/python "$image" \
  /app/tests/model_qualification_fixture/verify.py
