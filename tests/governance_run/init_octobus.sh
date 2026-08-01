#!/bin/sh
set -eu

OCTOBUS_ADDR="octobus:9000"
INSTANCE_ID="cloudatlas-fixture"
CAPSET_ID="cloudatlas-readonly"
METHOD="cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets"

instance_config='{"baseUrl":"http://cloudatlas-fixture:18080/openapi/","spaceId":"fixture-space"}'
instance_secret="$(printf '{"token":"%s"}' "$FIXTURE_CLOUDATLAS_TOKEN")"

octobus --addr "$OCTOBUS_ADDR" instance create "$INSTANCE_ID" \
  --service cloudatlas-read \
  --config-json "$instance_config" \
  --secret - <<EOF
$instance_secret
EOF
octobus --addr "$OCTOBUS_ADDR" capset create "$CAPSET_ID" \
  --name CloudAtlasReadOnly
octobus --addr "$OCTOBUS_ADDR" capset add-instance "$CAPSET_ID" "$INSTANCE_ID" \
  --no-all-methods
octobus --addr "$OCTOBUS_ADDR" capset select-method "$CAPSET_ID" "$INSTANCE_ID" \
  "/$METHOD"
printf '%s\n' "$FIXTURE_CAPSET_TOKEN" | octobus --addr "$OCTOBUS_ADDR" \
  capset add-token "$CAPSET_ID" fixture --name ExposureAgentFixture --token-stdin
