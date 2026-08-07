#!/usr/bin/env bash
set -euo pipefail

compose_files=(-f compose.yml -f compose.override.yml -f compose.governance-run-fixture.yml)
test_root="$(mktemp -d "${TMPDIR:-/tmp}/exposure-agent-governance.XXXXXX")"
artifact_host_path="$test_root/artifacts"
agent_compose_config_path="$test_root/agent-compose.yml"
mkdir -p "$artifact_host_path"
sed "s|source: /tmp/exposure-agent-artifacts|source: $artifact_host_path|" \
  agent-compose.yml >"$agent_compose_config_path"
export ARTIFACT_HOST_PATH="$artifact_host_path"
export AGENT_COMPOSE_CONFIG_PATH="$agent_compose_config_path"
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
RUN_GOVERNANCE_E2E=1 docker compose "${compose_files[@]}" run --rm --no-deps \
  -e RUN_GOVERNANCE_E2E=1 playwright \
  bunx playwright test tests/governance-run.spec.ts \
  --workers=1 --retries=0 --fail-on-flaky-tests --trace=retain-on-failure
