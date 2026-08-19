#!/bin/sh
set -eu

: "${DOCKER_IMAGE_RUNNER:?DOCKER_IMAGE_RUNNER is required}"
: "${RUNNER_BUILD_VERSION:?RUNNER_BUILD_VERSION is required}"
: "${ARTIFACT_HOST_PATH:?ARTIFACT_HOST_PATH is required}"

input=${1:?input template is required}
output=${2:?output path is required}

awk '
function replace_literal(text, needle, value, at) {
  while ((at = index(text, needle)) > 0) {
    text = substr(text, 1, at - 1) value substr(text, at + length(needle))
  }
  return text
}
{
  line = replace_literal($0, "${DOCKER_IMAGE_RUNNER}", ENVIRON["DOCKER_IMAGE_RUNNER"])
  line = replace_literal(line, "${RUNNER_BUILD_VERSION}", ENVIRON["RUNNER_BUILD_VERSION"])
  line = replace_literal(line, "${ARTIFACT_HOST_PATH}", ENVIRON["ARTIFACT_HOST_PATH"])
  print line
}
' "$input" > "$output"
