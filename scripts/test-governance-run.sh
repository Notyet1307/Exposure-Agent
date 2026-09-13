#!/usr/bin/env bash
set -euo pipefail

export COMPOSE_PROJECT_NAME="exposure_agent_governance_test_$$"
export SECRET_KEY="$(openssl rand -hex 32)"
export POSTGRES_PASSWORD="$(openssl rand -hex 32)"
export FIRST_SUPERUSER="admin-$$@governance-fixture.example"
export FIRST_SUPERUSER_PASSWORD="$(openssl rand -hex 32)"
export AGENT_COMPOSE_AUTH_TOKEN="$(openssl rand -hex 32)"
export AGENT_COMPOSE_RUNTIME_VERSION="${AGENT_COMPOSE_RUNTIME_VERSION:-sha256:092f8c4fbf7254ddd200a36d99ae6583cd08f5ddeda9cafd559b3636890c9670}"
export CLOUDATLAS_CAPSET_TOKEN="$(openssl rand -hex 32)"
export FIXTURE_CLOUDATLAS_TOKEN="$(openssl rand -hex 32)"
export RUNNER_BUILD_VERSION="governance-fixture-$$"
export TAG="governance-fixture-$$"
export MODEL_API_ENDPOINT="http://model-qualification-fixture:8080/v1"
export MODEL_API_PROTOCOL="chat_completions"
export MODEL_API_KEY="$(openssl rand -hex 32)"
export MODEL_IDENTITY="fixture-model"
export MODEL_CONFIG_REVISION="fixture-v1"
export MODEL_QUALIFICATION_TIMEOUT_SECONDS="30"

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
      backend agent-compose octobus cloudatlas-fixture \
      model-qualification-fixture || true
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
    runner_image_for_diagnostics="$(docker compose "${compose_files[@]}" config --format json |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["governance-runner-image"]["image"])')" || runner_image_for_diagnostics=""
    if [[ "$runner_image_for_diagnostics" == *":$RUNNER_BUILD_VERSION" ]]; then
      while read -r container_id; do
        docker logs --tail 200 "$container_id" || true
      done < <(docker ps --all --quiet --filter "ancestor=$runner_image_for_diagnostics")
    fi
  fi
  stack_cleanup
  cleanup_artifacts
  stack_cleanup
  if [[ -n "${EXPUX04_CHAIN_EVIDENCE_DIR:-}" ]]; then
    mkdir -p "$EXPUX04_CHAIN_EVIDENCE_DIR"
    for receipt in "$test_root"/workflow-result*.json; do
      [[ -e "$receipt" ]] || continue
      install -m 600 "$receipt" "$EXPUX04_CHAIN_EVIDENCE_DIR/$(basename "$receipt")"
    done
  fi
  rm -rf "$test_root"
  exit "$exit_code"
}
trap finish EXIT

without_model=0
with_model_connection_workflow=0
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --without-model) without_model=1 ;;
    --with-model-connection-workflow) with_model_connection_workflow=1 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
if ((without_model && with_model_connection_workflow)); then
  echo "--without-model cannot run the model connection workflow" >&2
  exit 2
fi
if ((with_model_connection_workflow)); then
  key_dir="$test_root/model-keys"
  mkdir -m 700 "$key_dir"
  openssl rand -out "$key_dir/v1.key" 32
  chmod 600 "$key_dir/v1.key"
  export MODEL_CONNECTION_KEY_HOST_DIRECTORY="$key_dir"
  export MODEL_CONNECTION_RUNNER_BUILD_VERSION="$RUNNER_BUILD_VERSION"
  export MODEL_WORKFLOW_PROVIDER_KEY="$(openssl rand -hex 32)"
  export MODEL_WORKFLOW_PROVIDER_IDENTITY="fixture-workflow-model"
  export COMPOSE_PROFILES="${COMPOSE_PROFILES:+$COMPOSE_PROFILES,}model-workflow"
  compose_files+=(-f compose.model-connections.yml)
fi
test_files=("$@")
if ((${#test_files[@]} == 0)); then
  test_files=(tests/governance-run.spec.ts tests/first-comparison.spec.ts)
fi
stack_cleanup
docker compose "${compose_files[@]}" build playwright
up_targets=(frontend)
if ((with_model_connection_workflow)); then
  up_targets+=(model-workflow-provider)
fi
docker compose "${compose_files[@]}" up --build -d --wait "${up_targets[@]}"
./scripts/test-model-qualification-fixture.sh
./scripts/qualify-model.sh
if ((without_model)); then
  # Keep the existing qualification checks, then test this stack's backend without a model.
  cat > "$test_root/without-model.yml" <<'YAML'
services:
  backend:
    environment:
      MODEL_API_KEY: ""
      MODEL_API_ENDPOINT: ""
YAML
  compose_files+=(-f "$test_root/without-model.yml")
  docker compose "${compose_files[@]}" up -d --no-deps --force-recreate --wait backend
  docker compose "${compose_files[@]}" exec -T backend python -c \
    'from app.core.config import settings; assert not settings.MODEL_API_KEY.get_secret_value(); assert not settings.MODEL_API_ENDPOINT; print("backend model unconfigured: PASS")'
fi
if ((with_model_connection_workflow)); then
  docker compose "${compose_files[@]}" run --rm --no-deps -T \
    -v "$PWD/tests/model_connection_backend:/fixture:ro" \
    -v "$test_root:/evidence:rw" \
    -e CHAIN_API_URL=http://backend:8000 \
    -e CHAIN_UI_URL=http://frontend \
    -e CHAIN_WORKBOOK_PATH=/app/frontend/tests/fixtures/first-comparison.xlsx \
    -e CHAIN_INPUT_PATH=/evidence/workflow-input.json \
    -e CHAIN_OUTPUT_PATH=/evidence/workflow-result.json \
    -e MODEL_WORKFLOW_PROVIDER_KEY \
    -e MODEL_WORKFLOW_PROVIDER_IDENTITY \
    --entrypoint python backend /fixture/activate_chain.py
  docker compose "${compose_files[@]}" run --rm --no-deps -T \
    -v "$PWD/tests/model_connection_backend:/app/tests/model_connection_backend:ro" \
    -v "$test_root:/evidence:rw" playwright \
    node /app/tests/model_connection_backend/workflow-browser.mjs \
    < "$test_root/workflow-input.json"
  python3 - "$test_root/workflow-result.json" <<'PY'
import json
import sys
result = json.load(open(sys.argv[1]))
assert result["status"] == "PASS"
assert result["project_id"] and result["run_id"] and result["resource_id"]
assert result["navigation_posts"] == result["shortcut_posts"] == 0
print("EXP-UX-04 real published Run to AI workflow: PASS")
PY
fi
docker compose "${compose_files[@]}" run --rm --no-deps \
  -e RUN_GOVERNANCE_E2E=1 -e EXPECT_BACKEND_MODEL_UNCONFIGURED="$without_model" playwright \
  bunx playwright test "${test_files[@]}" \
  --project=chromium --workers=1 --retries=0 --fail-on-flaky-tests \
  --trace=retain-on-failure
