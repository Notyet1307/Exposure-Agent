#!/usr/bin/env bash
set -euo pipefail

# Ensure non-interactive shells (Cindy/Pi/cron) find Homebrew, PG, uv, and bun.
for dir in \
  /opt/homebrew/opt/postgresql@18/bin \
  /opt/homebrew/opt/postgresql@17/bin \
  /usr/local/opt/postgresql@18/bin \
  /usr/local/opt/postgresql@17/bin \
  /opt/homebrew/bin \
  /usr/local/bin \
  "$HOME/.local/bin" \
  "$HOME/.bun/bin"
do
  if [ -d "$dir" ]; then
    case ":$PATH:" in
      *":$dir:"*) ;;
      *) PATH="$dir:$PATH" ;;
    esac
  fi
done
export PATH

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

missing=0
for tool in uv bun node initdb pg_ctl psql; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "BLOCKED: required tool '$tool' not found in PATH=$PATH" >&2
    missing=1
  fi
done
if [ "$missing" -ne 0 ]; then
  exit 2
fi

uv sync --frozen
(cd frontend && bun install --frozen-lockfile)

PY="$REPO_ROOT/.venv/bin/python"
VERIFY="$REPO_ROOT/scripts/verify-exposure2026.py"

"$PY" "$VERIFY" --self-test
"$PY" "$VERIFY" --repo "$REPO_ROOT" --doctor
echo "BOOTSTRAP_READY repo=$REPO_ROOT"
