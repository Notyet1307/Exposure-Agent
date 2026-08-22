#!/bin/sh
set -eu

: "${DOCKER_IMAGE_RUNNER:?DOCKER_IMAGE_RUNNER is required}"
: "${RUNNER_BUILD_VERSION:?RUNNER_BUILD_VERSION is required}"
: "${ARTIFACT_HOST_PATH:?ARTIFACT_HOST_PATH is required}"

input=${1:?input template is required}
output=${2:?output path is required}

awk '
function render(text, token, name, at) {
  while (match(text, /\$\{[A-Z][A-Z0-9_]*\}/)) {
    at = RSTART
    token = substr(text, at, RLENGTH)
    name = substr(token, 3, length(token) - 3)
    if (!(name in ENVIRON)) {
      print name " is required" > "/dev/stderr"
      exit 1
    }
    text = substr(text, 1, at - 1) ENVIRON[name] substr(text, at + length(token))
  }
  return text
}
{ print render($0) }
' "$input" > "$output"
