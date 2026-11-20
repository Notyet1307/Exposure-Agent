#!/usr/bin/env bash
# Run a command with standard macOS/Linux user tool paths prepended for non-interactive shells
# (Cindy, Pi, git hooks, cron). Project-agnostic and safe to reuse across repositories.
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "Usage: with-tool-path.sh <command> [args...]" >&2
  exit 2
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

for dir in \
  "$REPO_ROOT/.venv/bin" \
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

exec "$@"
