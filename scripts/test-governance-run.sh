#!/usr/bin/env bash
set -euo pipefail

export COMPOSE_PROJECT_NAME="exposure_agent_governance_test_$$"
export SECRET_KEY="$(openssl rand -hex 32)"
export POSTGRES_PASSWORD="$(openssl rand -hex 32)"
export FIRST_SUPERUSER="admin-$$@governance-fixture.example"
export FIRST_SUPERUSER_PASSWORD="$(openssl rand -hex 32)"
export AGENT_COMPOSE_AUTH_TOKEN="$(openssl rand -hex 32)"
export CLOUDATLAS_CAPSET_TOKEN="$(openssl rand -hex 32)"
export FIXTURE_CLOUDATLAS_TOKEN="$(openssl rand -hex 32)"
export RUNNER_BUILD_VERSION="governance-fixture-$$"
export TAG="governance-fixture-$$"
export MODEL_API_ENDPOINT="http://model-qualification-unused:8080/v1"
export MODEL_API_PROTOCOL="chat_completions"
export MODEL_API_KEY="$(openssl rand -hex 32)"
export MODEL_IDENTITY="fixture-unused"
export MODEL_CONFIG_REVISION="fixture-v1"

compose_files=(-f compose.yml -f compose.override.yml -f compose.governance-run-fixture.yml)
test_root="$(mktemp -d "${TMPDIR:-/tmp}/exposure-agent-governance.XXXXXX")"
artifact_host_path="$test_root/artifacts"
mkdir -p "$artifact_host_path"
export ARTIFACT_HOST_PATH="$artifact_host_path"
export AGENT_COMPOSE_CONFIG_PATH="$PWD/agent-compose.yml"
stack_cleanup() {
  docker compose "${compose_files[@]}" down -v --remove-orphans
}
cleanup_artifacts() {
  docker compose "${compose_files[@]}" run --rm --no-deps \
    --entrypoint /bin/sh agent-compose-project-init -ec \
    'find /cleanup -mindepth 1 -delete'
}
finish() {
  exit_code=$?
  trap - EXIT
  if ((exit_code != 0)); then
    docker compose "${compose_files[@]}" logs --no-color --tail 200 \
      backend agent-compose octobus cloudatlas-fixture || true
    docker compose "${compose_files[@]}" run --rm --no-deps \
      --entrypoint /bin/sh agent-compose-project-init -ec '
        sh /usr/local/bin/render-exposure-agent-config \
          /config/agent-compose.template.yml /config/agent-compose.yml
        agent-compose --host http://agent-compose:7410 auth login \
          --token "$AGENT_COMPOSE_AUTH_TOKEN" >/dev/null
        runs="$(agent-compose --host http://agent-compose:7410 \
          --file /config/agent-compose.yml ps --all --json)"
        printf "%s\n" "$runs"
        printf "%s\n" "$runs" | awk -F\" '\''/"run_id"/{print $4}'\'' |
          while read -r run_id; do
            agent-compose --host http://agent-compose:7410 \
              --file /config/agent-compose.yml inspect run "$run_id" --json || true
          done
      ' || true
    while read -r container_id; do
      docker logs --tail 200 "$container_id" || true
    done < <(
      docker ps --all --quiet --filter ancestor=governance-runner:latest
    )
  fi
  stack_cleanup
  cleanup_artifacts
  stack_cleanup
  rm -rf "$test_root"
  exit "$exit_code"
}
trap finish EXIT

stack_cleanup
docker compose "${compose_files[@]}" build playwright
docker compose "${compose_files[@]}" up --build -d --wait frontend
./scripts/test-model-qualification-fixture.sh
docker compose "${compose_files[@]}" run --rm --no-deps \
  -e RUN_GOVERNANCE_E2E=1 playwright \
  bunx playwright test tests/governance-run.spec.ts \
  --project=chromium --workers=1 --retries=0 --fail-on-flaky-tests \
  --trace=retain-on-failure
