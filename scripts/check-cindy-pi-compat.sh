#!/usr/bin/env bash
# Read-only upgrade canary for Cindy-managed Pi + pstack adapter compatibility.
# Exit codes: 0 = PASS, 1 = FAIL, 2 = BLOCKED (host lacks Cindy/Pi/tools).
set -euo pipefail

for dir in \
  /opt/homebrew/bin \
  /usr/local/bin \
  "$HOME/.bun/bin" \
  "$HOME/.local/bin"
do
  if [ -d "$dir" ]; then
    case ":$PATH:" in
      *":$dir:"*) ;;
      *) PATH="$dir:$PATH" ;;
    esac
  fi
done
export PATH

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo)
      shift
      if [ "$#" -eq 0 ]; then
        echo "BLOCKED: --repo requires a path argument" >&2
        exit 2
      fi
      REPO_ROOT="$1"
      ;;
    *)
      echo "BLOCKED: unknown argument: $1" >&2
      exit 2
      ;;
  esac
  shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || (cd "$SCRIPT_DIR/.." && pwd))"
REPO_ROOT="${REPO_ROOT:-$DEFAULT_REPO_ROOT}"
CINDY_DATA_DIR="${CINDY_DATA_DIR:-$HOME/Library/Application Support/CindyGlobal}"
SELECTED_JSON="$CINDY_DATA_DIR/pi/selected.json"
PKG_STATE_JSON="$CINDY_DATA_DIR/pi-package-home/cindy-package-state.json"
MODEL_SHEET="$REPO_ROOT/.pstack/pi-home/pstack-models.md"

for tool in node bun; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "BLOCKED: required tool '$tool' not found in PATH=$PATH" >&2
    exit 2
  fi
done

if [ ! -f "$SELECTED_JSON" ] || [ ! -f "$PKG_STATE_JSON" ]; then
  echo "BLOCKED: Cindy managed Pi metadata missing under $CINDY_DATA_DIR" >&2
  exit 2
fi

if [ ! -f "$MODEL_SHEET" ]; then
  echo "FAIL: repo model sheet missing: $MODEL_SHEET" >&2
  exit 1
fi

PROBE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cindy-pi-compat-probe.XXXXXX")"
trap 'rm -rf "$PROBE_DIR"' EXIT

# [1/4] Verify selected.json and active managed Pi executable.
PI_INFO="$(node -e '
const fs = require("node:fs");
const path = require("node:path");
const dataDir = process.argv[1];
const selPath = process.argv[2];
const sel = JSON.parse(fs.readFileSync(selPath, "utf8"));
if (!sel.version || !sel.directory) {
  throw new Error("selected.json missing version or directory");
}
const piBin = path.join(dataDir, "pi", sel.directory, "pi");
fs.accessSync(piBin, fs.constants.X_OK);
process.stdout.write(JSON.stringify({ version: sel.version, directory: sel.directory, piBin }));
' "$CINDY_DATA_DIR" "$SELECTED_JSON")"

PI_BIN="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).piBin)' "$PI_INFO")"
PI_VERSION="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).version)' "$PI_INFO")"
echo "PASS [1/4] selected.json: version=$PI_VERSION bin=$PI_BIN"

# [2/4] Verify cindy-package-state.json approval & resolve adapter + vendor root.
PKG_INFO="$(node -e '
const fs = require("node:fs");
const path = require("node:path");
const pkgHome = process.argv[1];
const statePath = process.argv[2];
const overrideCompat = process.argv[3] || "";
const state = JSON.parse(fs.readFileSync(statePath, "utf8"));
const approved = state.approvedExtensionSources || [];
const disabled = new Set(state.disabledSources || []);
const unavailable = new Set(state.snapshotUnavailablePackages || []);
const fps = state.approvedExtensionFingerprints || {};

if (approved.length === 0) {
  throw new Error("No approvedExtensionSources in cindy-package-state.json");
}
for (const src of approved) {
  if (disabled.has(src)) throw new Error(`Approved extension source is disabled: ${src}`);
  if (unavailable.has(src)) throw new Error(`Approved extension source snapshot unavailable: ${src}`);
  const fp = fps[src];
  if (!fp || !/^[0-9a-f]{64}$/.test(fp)) {
    throw new Error(`Invalid or missing SHA-256 fingerprint for ${src}: ${fp}`);
  }
}

const primarySrc = approved[0];
const extPkgDir = path.resolve(pkgHome, primarySrc);
const extPkgJson = JSON.parse(fs.readFileSync(path.join(extPkgDir, "package.json"), "utf8"));
const extRel = (extPkgJson.pi && extPkgJson.pi.extensions && extPkgJson.pi.extensions[0]) || "./pi/index.ts";
const extEntry = path.resolve(extPkgDir, extRel);
if (!fs.existsSync(extEntry)) {
  throw new Error(`Extension entrypoint not found: ${extEntry}`);
}
const compatDir = overrideCompat ? path.resolve(overrideCompat) : path.dirname(extPkgDir);
const vendorDir = path.join(compatDir, "vendor");
if (!fs.existsSync(path.join(vendorDir, "tests", "pi"))) {
  throw new Error(`Vendor Pi tests not found under ${vendorDir}/tests/pi`);
}
process.stdout.write(JSON.stringify({
  approvedCount: approved.length,
  fingerprintPrefix: fps[primarySrc].slice(0, 12),
  extEntry,
  compatDir,
  vendorDir,
}));
' "$CINDY_DATA_DIR/pi-package-home" "$PKG_STATE_JSON" "${PSTACK_COMPAT_DIR:-}")"

EXT_ENTRY="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).extEntry)' "$PKG_INFO")"
VENDOR_DIR="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).vendorDir)' "$PKG_INFO")"
FP_PREFIX="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).fingerprintPrefix)' "$PKG_INFO")"
echo "PASS [2/4] cindy-package-state.json: approved fingerprint=${FP_PREFIX}... entry=$EXT_ENTRY"

# Resolve installed Pi package directory (holding peer deps like typebox) without mutating vendor/.
PI_PKG_DIR="$(bun -e '
import { pathToFileURL } from "node:url";
const mod = await import(pathToFileURL(`${process.argv[1]}/tools/pi-package.mjs`).href);
const piDir = mod.findPiPackage();
if (piDir) process.stdout.write(piDir);
' "$VENDOR_DIR")"

# Build an isolated read-only test copy in PROBE_DIR linked to Pi peer node_modules (never mutates vendor/).
VENDOR_SANDBOX="$PROBE_DIR/vendor-sandbox"
mkdir -p "$VENDOR_SANDBOX"
for item in package.json plugins tests tools docs; do
  if [ -e "$VENDOR_DIR/$item" ]; then
    cp -R "$VENDOR_DIR/$item" "$VENDOR_SANDBOX/$item"
  fi
done
if [ -n "$PI_PKG_DIR" ] && [ -d "$PI_PKG_DIR/node_modules" ] && [ ! -e "$VENDOR_SANDBOX/node_modules" ]; then
  mkdir -p "$VENDOR_SANDBOX/node_modules/@earendil-works"
  for entry in "$PI_PKG_DIR/node_modules"/*; do
    [ -e "$entry" ] || continue
    name="$(basename "$entry")"
    if [ "$name" != "@earendil-works" ]; then
      ln -s "$entry" "$VENDOR_SANDBOX/node_modules/$name"
    fi
  done
  if [ -d "$PI_PKG_DIR/node_modules/@earendil-works" ]; then
    for sub in "$PI_PKG_DIR/node_modules/@earendil-works"/*; do
      [ -e "$sub" ] || continue
      ln -s "$sub" "$VENDOR_SANDBOX/node_modules/@earendil-works/$(basename "$sub")"
    done
  fi
  ln -s "$PI_PKG_DIR" "$VENDOR_SANDBOX/node_modules/@earendil-works/pi-coding-agent"
fi

# [3/4] Verify repo model sheet parsing and run vendor non-live Pi unit suite.
bun -e '
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
const [vendorDir, sheetPath] = process.argv.slice(1);
const cfg = await import(pathToFileURL(`${vendorDir}/plugins/pstack/pi/config.ts`).href);
const text = readFileSync(sheetPath, "utf8");
const parsed = cfg.parseSheet(text);
if (!parsed.askToolOff) {
  throw new Error("Expected `pi ask tool: off` in repo pstack-models.md");
}
if (parsed.agentToolsOff) {
  throw new Error("Unexpected `pi agent tools: off` in repo pstack-models.md");
}
if (parsed.piModels.size < 3) {
  throw new Error(`Expected >= 3 pi models aliases, got ${parsed.piModels.size}`);
}
console.log(`PASS [3a/4] pstack-models.md parsed: aliases=${parsed.piModels.size} askToolOff=${parsed.askToolOff} hookOff=${parsed.hookOff}`);
' "$VENDOR_SANDBOX" "$MODEL_SHEET"

(
  cd "$VENDOR_SANDBOX"
  PSTACK_PI_LIVE=0 bun test tests/pi/
)
echo "PASS [3b/4] vendor tests/pi suite passed (PSTACK_PI_LIVE=0)"

# [4/4] Run minimal zero-token RPC probe against Cindy-managed Pi + pstack adapter.
RPC_DIR="$PROBE_DIR/rpc-agent-home"
mkdir -p "$RPC_DIR"

node -e '
const { spawn } = require("node:child_process");
const readline = require("node:readline");

const [piBin, extEntry, repoRoot, probeDir] = process.argv.slice(1);
const child = spawn(
  piBin,
  [
    "--mode", "rpc",
    "--no-session",
    "--no-skills",
    "--no-prompt-templates",
    "--extension", extEntry,
  ],
  {
    cwd: repoRoot,
    env: {
      ...process.env,
      PI_CODING_AGENT_DIR: probeDir,
      CINDY_PSTACK_SCOPE_HOME: probeDir,
    },
    stdio: ["pipe", "pipe", "pipe"],
  }
);

let stderr = "";
child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });

const responses = new Map();
const rl = readline.createInterface({ input: child.stdout });
const timer = setTimeout(() => {
  child.kill("SIGKILL");
  console.error("FAIL [4/4] RPC probe timed out after 15s.\nSTDERR:\n" + stderr);
  process.exit(1);
}, 15000);

function finish(ok, detail) {
  clearTimeout(timer);
  rl.close();
  try { child.stdin.end(); } catch {}
  child.kill("SIGTERM");
  if (!ok) {
    console.error("FAIL [4/4] RPC probe failed: " + detail + (stderr ? "\nSTDERR:\n" + stderr : ""));
    process.exit(1);
  }
  console.log("PASS [4/4] RPC probe: " + detail);
  process.exit(0);
}

rl.on("line", (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  let msg;
  try { msg = JSON.parse(trimmed); } catch { return; }
  if (msg.type === "response" && msg.id) {
    responses.set(msg.id, msg);
  }
  if (responses.has("state-1") && responses.has("cmds-1")) {
    const s = responses.get("state-1");
    const c = responses.get("cmds-1");
    if (!s.success) return finish(false, "get_state returned error: " + JSON.stringify(s));
    if (!c.success) return finish(false, "get_commands returned error: " + JSON.stringify(c));
    if (/duplicate tool|Error loading extension|InvalidValueError/i.test(stderr)) {
      return finish(false, "extension load warning/error detected in stderr");
    }
    const cmds = Array.isArray(c.data?.commands) ? c.data.commands : [];
    const pstackCmds = cmds.filter((x) => String(x.name || "").includes("pstack")).length;
    finish(true, `get_state=ok get_commands=ok total_commands=${cmds.length} pstack_commands=${pstackCmds}`);
  }
});

child.on("exit", (code, sig) => {
  if (!responses.has("state-1") || !responses.has("cmds-1")) {
    finish(false, `pi exited prematurely (code=${code}, signal=${sig})`);
  }
});

child.stdin.write(JSON.stringify({ id: "state-1", type: "get_state" }) + "\n");
child.stdin.write(JSON.stringify({ id: "cmds-1", type: "get_commands" }) + "\n");
' "$PI_BIN" "$EXT_ENTRY" "$REPO_ROOT" "$RPC_DIR"

echo "CINDY_PI_COMPAT_PASS version=$PI_VERSION"
