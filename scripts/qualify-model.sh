#!/bin/sh
set -eu

exec docker compose -f compose.yml exec -T backend python -m app.model_qualification
