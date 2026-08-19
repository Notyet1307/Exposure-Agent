#!/usr/bin/env bash
set -euo pipefail

export COMPOSE_PROJECT_NAME="exposure_agent_cloudatlas_fixture_test_$$"
export CLOUDATLAS_FIXTURE_PORT="${CLOUDATLAS_FIXTURE_PORT:-0}"
export FIXTURE_CLOUDATLAS_TOKEN="$(openssl rand -hex 32)"
export FIXTURE_CAPSET_TOKEN="$(openssl rand -hex 32)"
compose_file="compose.cloudatlas-fixture.yml"
cleanup() {
  docker compose -f "$compose_file" down -v --remove-orphans
}
trap cleanup EXIT

cleanup
docker compose -f "$compose_file" up --build -d
docker compose -f "$compose_file" wait cloudatlas-fixture-init

fixture_address="$(docker compose -f "$compose_file" port octobus 9000)"
fixture_base_url="http://$fixture_address"
verify_fixture() {
  (
    cd backend
    ALL_PROXY= HTTPS_PROXY= HTTP_PROXY= \
      all_proxy= https_proxy= http_proxy= \
      NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
      OCTOBUS_URL="$fixture_base_url" uv run python \
      ../tests/cloudatlas_fixture/verify.py \
      --base-url "$fixture_base_url" "$@"
  )
}

baseline_fingerprint="$(verify_fixture --print-backend-fingerprint)"
secondary_capset_token="$(openssl rand -hex 32)"
printf '%s\n' "$secondary_capset_token" | docker compose \
  -f "$compose_file" exec -T octobus octobus capset add-token \
  cloudatlas-readonly fixture-secondary --name FingerprintDriftFixture --token-stdin
verify_fixture \
  --stored-fingerprint "$baseline_fingerprint" \
  --expected-validation-status invalid
docker compose -f "$compose_file" exec -T octobus octobus capset remove-token \
  cloudatlas-readonly fixture-secondary
verify_fixture \
  --stored-fingerprint "$baseline_fingerprint" \
  --expected-validation-status validated
