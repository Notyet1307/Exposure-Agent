---
name: verify-exposure2026
description: Verify Exposure2026 through a disposable synthetic PostgreSQL and real HTTP API; use for a project-create/read smoke, optional real browser project creation, and a real-browser customer-ledger first-selection journey; not full product acceptance.
---

# Exposure2026 verification pilot

## Launch
Use the project interpreter and the prepare/run commands below. Set `TASK_ID` for the task and choose a new `RUN_ROOT` for each frozen bundle. The prepare command freezes seven assets and records their identity. Bare `verify-exposure2026.py` does not freeze assets or record verification-asset identity.

Run this block with `MODE=prepare` before the journey. After the journey, keep the same `RUN_ROOT`, set `MODE=check`, and run the same block again. Check mode compares both copies with the original manifest and verifies unchanged product HEAD. Do not refresh the frozen copies after a failure.

```bash
export SOURCE_REPO=/Users/yet/Developer/exposure2026
export TASK_ID=customer-ledger-verification-pilot-20261107
export RUN_ROOT="${RUN_ROOT:-/Users/yet/ops/tasks/exposure2026/$TASK_ID/run-$(date -u +%Y%m%dT%H%M%SZ)}"
export MODE="${MODE:-prepare}"
"$SOURCE_REPO/.venv/bin/python" - <<'PY_PREPARE'
import contextlib, hashlib, json, os, shutil, subprocess, sys, traceback
from pathlib import Path

repo = Path(os.environ["SOURCE_REPO"]).resolve()
root = Path(os.environ["RUN_ROOT"]).resolve()
mode = os.environ["MODE"]
assert mode in ("prepare", "check"), "MODE must be prepare or check"
if mode == "prepare":
	root.mkdir(parents=True, exist_ok=False)
paths = [".claude/skills/verify-exposure2026/" + name for name in (
	"SKILL.md", "features/README.md", "features/customer-ledger.md",
	"features/external-assets.md", "features/projects.md",
)] + ["scripts/verify-exposure2026.py", "scripts/verify-exposure2026-ui.cjs"]
code = 0
with (root / f"{mode}.log").open("x") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
	try:
		head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
		manifest_path = root / "frozen-assets.json"
		if mode == "prepare":
			assets = []
			for path in paths:
				live, frozen = repo / path, root / "verification" / path
				frozen.parent.mkdir(parents=True, exist_ok=True)
				shutil.copyfile(live, frozen)
				assert live.read_bytes() == frozen.read_bytes(), path
				assets.append({"path": path, "live_sha256": hashlib.sha256(live.read_bytes()).hexdigest(),
					"frozen_sha256": hashlib.sha256(frozen.read_bytes()).hexdigest(), "frozen_path": str(frozen)})
			manifest_path.write_text(json.dumps({"product_head": head, "source_repo": str(repo), "assets": assets}, indent=2) + "\n")
		manifest = json.loads(manifest_path.read_text())
		assert manifest["product_head"] == head, "Product HEAD changed"
		assert manifest["source_repo"] == str(repo), "Source repository changed"
		assert [asset["path"] for asset in manifest["assets"]] == paths, "Asset list changed"
		for asset in manifest["assets"]:
			live, frozen = repo / asset["path"], root / "verification" / asset["path"]
			assert asset["frozen_path"] == str(frozen), "Frozen path changed"
			assert live.read_bytes() == frozen.read_bytes(), asset["path"]
			assert hashlib.sha256(live.read_bytes()).hexdigest() == asset["live_sha256"] == asset["frozen_sha256"] == hashlib.sha256(frozen.read_bytes()).hexdigest(), asset["path"]
		assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip() == head, "Product HEAD changed during check"
		print(json.dumps({"status": "PASS", "mode": mode, **manifest}, indent=2))
	except Exception:
		traceback.print_exc()
		code = 1
(root / f"{mode}.exit").write_text(str(code) + "\n")
print((root / f"{mode}.log").read_text(), end="")
sys.exit(code)
PY_PREPARE
```

Continue only when `prepare.exit` is `0`. The run block in Helpers uses this frozen bundle. Do not pre-create any evidence directory.

System `python3` is 3.9.6 on this host. It lacks `tarfile.extract(filter=...)`, and the product backend source uses Python 3.14 syntax. The helper checks the invoking interpreter path and tarfile filter support before extracting any source and returns BLOCKED with the expected `.venv/bin/python` path. Do not build a launcher; use the project interpreter.

The helper archives committed HEAD (not uncommitted changes), excludes .env files, initializes a private synthetic PostgreSQL cluster, migrates, seeds one synthetic administrator, then starts the real API on a free loopback port. Readiness requires authentication, not just a listening socket. Native PostgreSQL17 is a pilot stand-in; production PostgreSQL18, Docker topology, external services are NOT verified. For PostgreSQL18 pass `--pg-bin` pointing to its installed bin directory. Default API mode installs nothing. Explicit `--ui` installs only existing bun.lock dependencies in the disposable source using `bun install --frozen-lockfile`; it needs installed Bun, Node and Google Chrome. `--ledger` implies `--ui`. No new framework or global install.

## Doctor
Select `doctor` in the frozen-helper run block below. `--doctor` is read-only against the product and runtime prerequisites. It checks that the invoking interpreter is the project .venv, that `tarfile.extract` supports `filter`, and that required binaries/imports exist. It does NOT certify database readiness, version parity, UI dependencies or an existing app instance. This helper never drives an existing instance. API PID, loopback ports, committed HEAD and PostgreSQL version are recorded during launch. A wrong interpreter or missing runtime returns BLOCKED and exit 2.

## Drive
The project journey is [projects](features/projects.md): login, POST `/api/v1/projects/`, repeat with the same Idempotency-Key, GET detail, GET list, and GET the default upload profile. Readback and direct read-only SQL verify one persisted project. It uses actual HTTP user endpoints, never an internal setter. With `--ui` the helper additionally drives the actual login form, project creation form and page reload through locked Playwright/installed Chrome, capturing four project screenshots and asserting one additional database project; `--ledger` adds seven ledger screenshots.

The ledger journey is [customer-ledger](features/customer-ledger.md). With `--ledger` the helper also drives the real browser file input and the form's `Upload` button to reject a missing-required-column workbook and a port-70000 workbook with the actual 422 messages, verifies `current_upload_id` is unchanged, uploads a valid synthetic XLSX built from the API-created project's actual profile required headers (the UI project's profile is separately read and must match), clicks `Preview selection`, asserts `Selection preview` without an apply request and without a current-pointer change, clicks `Set as current input`, asserts the 201 receipt and that the current pointer equals the upload id, opens `Customer asset ledger` from the sidebar, reads rows/fields/count, reloads, and then independently re-reads through public API, read-only SQL and the persisted artifact file with its SHA-256. The UI applies through POST `/api/v1/projects/{id}/customer-ledger/replacements/preview` and POST `/api/v1/projects/{id}/customer-ledger/replacements`. It does not use the old `customer-uploads/{id}/select` route as a substitute for the real UI application path. Backend data is not mocked.

## Evidence
The prepare command above creates the frozen verification bundle and records product HEAD and asset SHA-256. The Helpers run block executes its Python helper with `--repo` pointing at the product; `--ui` and `--ledger` load the UI helper from the same frozen sibling directory. A run saves result.json, ui-result.json, screenshots, runtime.log, postgres.log, frontend.log, the synthetic fixtures, and artifact-uploaded.xlsx outside the disposable runtime directory. PASS requires all assertions plus successful cleanup. FAIL exits 1, BLOCKED exits 2, and unexercised surfaces remain NOT_RUN. Login credentials and bearer tokens are excluded. Preserve failed runs.

The project smoke keeps its empty-artifact assertion. The ledger run asserts the artifact directory is empty before upload, then exactly one artifact exists after the real upload and its SHA-256 equals the accepted upload `raw_sha256`. After apply the same artifact is read back and compared with the ledger rows. Do not keep the empty-directory assertion after a successful upload.

`--self-test` proves known bad assertions map to FAIL and absent runtime maps to BLOCKED; it is a classifier check, NOT a substitute for a real app journey. `--expect-name deliberately-wrong` on a new evidence directory exercises a known-bad project readback and must exit 1. `--expect-ledger-ip 192.0.2.99` on a new evidence directory exercises the new ledger readback assertion after the real UI path and must exit 1 with cleanup PASS. Never describe negative-test PASS as product acceptance.

External URLs point to loopback port 9, credentials are absent, no sources/model workers start, and only local project endpoints run. This is application-boundary avoidance, not an OS egress firewall. The helper does not alter git refs, repository dependency manifests or lockfiles, global installations or configuration, or Docker resources. Explicit `--ui` installs the already-locked dependencies only inside the disposable source copy. No real customer data is used.

## Cleanup
Automatic finally cleanup terminates only the child API process and stops only its private PG data directory. Only confirmed cleanup removes runtime/source/synthetic data; logs, results, fixtures, screenshots and artifact-uploaded.xlsx survive in the evidence root. Never kill by process name or stop another task's containers. A cleanup failure or EPERM makes the run FAIL and retains scratch data for inspection. UI Node/Vite and detached Chrome groups are separately registered in ui-supervisor-owner.json and ui-browser-owner.json; cleanup uses only those owned groups. `--ui-timeout-test` deliberately pauses after browser launch and forces timeout, checking cleanup behavior; it cannot be combined with `--ledger`. An unconfirmed group stop is never PASS; all later API/PG cleanup still runs and result.json is written. On an interrupted supervisor inspect the exact recorded PID and private cluster before acting; do not blindly rerun or clean shared paths.

## Helpers
After prepare, select one row, then execute the run block. Each invocation requires a new evidence directory and unused log/exit names. For a repeat of the same row, prepare a new `RUN_ROOT`. Negative journeys are optional future checks, not part of every ledger run.

| Check | Selection before the run block | Expected exit |
| --- | --- | --- |
| API | `RUN_NAME=api; set --` | 0 |
| UI | `RUN_NAME=ui; set -- --ui` | 0 |
| Ledger | `RUN_NAME=ledger; set -- --ledger` | 0 |
| Negative project | `RUN_NAME=negative-project; set -- --expect-name deliberately-wrong` | 1 |
| Negative ledger | `RUN_NAME=negative-ledger; set -- --ledger --expect-ledger-ip 192.0.2.99` | 1 |
| Doctor | `RUN_NAME=doctor; set -- --doctor` | 0 |
| Classifier | `RUN_NAME=self-test; set -- --self-test` | 0 |

For the ledger journey, copy this complete run block. For another check, replace its first two lines with the corresponding table selection.

```bash
RUN_NAME=ledger
set -- --ledger
"$SOURCE_REPO/.venv/bin/python" - "$RUN_ROOT" "$SOURCE_REPO" "$RUN_NAME" "$@" <<'PY_RUN'
import json, subprocess, sys
from pathlib import Path

root, repo = Path(sys.argv[1]), Path(sys.argv[2])
name, flags = sys.argv[3], sys.argv[4:]
assert (root / "prepare.exit").read_text().strip() == "0", "Prepare must pass"
command = [str(repo / ".venv/bin/python"), str(root / "verification/scripts/verify-exposure2026.py"), "--repo", str(repo), *flags]
if not any(flag in flags for flag in ("--doctor", "--self-test")):
	evidence = root / ("evidence" if name == "ledger" else f"evidence-{name}")
	assert not evidence.exists(), "Evidence directory must be new"
	command += ["--evidence", str(evidence)]
with (root / f"{name}.command.json").open("x") as record:
	json.dump(command, record, indent=2)
with (root / f"{name}.log").open("x") as log:
	result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
(root / f"{name}.exit").write_text(str(result.returncode) + "\n")
print(f"{name}: exit {result.returncode}; {root / (name + '.log')}")
sys.exit(result.returncode)
PY_RUN
```

The subprocess return code is written before this block exits, including negative-test failures. Do not use a background shell's completion code as the test result. After the run, execute the Launch block with `MODE=check`; require `check.exit` to be `0`.

- `RUN_ROOT/verification/` holds the seven assets at their original relative paths, including both sibling scripts.
- `RUN_ROOT/frozen-assets.json` binds the product HEAD and source repository to each live/frozen SHA-256 and frozen path.
- `RUN_ROOT/evidence/` holds the ledger result, UI result, screenshots, fixtures and retained artifact. Other journeys use `evidence-<name>/`; the helper creates these directories.
- `RUN_ROOT/<name>.log`, `<name>.exit` and `<name>.command.json` record each helper invocation. `prepare.log`/`prepare.exit` and `check.log`/`check.exit` record the beginning and ending identity checks.

The optional executable `scripts/verify-exposure2026-ui.cjs` is called by `--ui` and `--ledger`; do not invoke it against a shared server. Non-validation tracked or untracked changes block the committed-HEAD snapshot to prevent verifying stale product code. Begin/end source state and HEAD are recorded. The executable helper uses the project .venv interpreter and its already-installed backend dependencies; it installs nothing. Missing tools are not a pass. Recheck the feature map as routes change, using installed `/pstack:maintain-verification-skill` when appropriate.
