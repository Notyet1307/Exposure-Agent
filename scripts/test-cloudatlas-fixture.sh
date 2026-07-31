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
python3 tests/cloudatlas_fixture/verify.py
