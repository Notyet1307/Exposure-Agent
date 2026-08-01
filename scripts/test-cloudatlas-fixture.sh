#!/usr/bin/env bash
set -euo pipefail

compose_file="compose.cloudatlas-fixture.yml"
cleanup() {
  docker compose -f "$compose_file" down -v --remove-orphans
}
trap cleanup EXIT

cleanup
docker compose -f "$compose_file" up --build -d
docker compose -f "$compose_file" wait cloudatlas-fixture-init

fixture_base_url="http://127.0.0.1:${CLOUDATLAS_FIXTURE_PORT:-19000}"
verify_fixture() {
  (
    cd backend
    OCTOBUS_URL="$fixture_base_url" uv run python \
      ../tests/cloudatlas_fixture/verify.py \
      --base-url "$fixture_base_url" "$@"
  )
}

baseline_fingerprint="$(verify_fixture --print-backend-fingerprint)"
printf '%s\n' 'fixture-secondary-capset-token' | docker compose \
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
