# NetFlow bulk processing progress

One read surface reports the fixed, selected bulk analysis. It is not a second
detail reader, scheduler, or task selector.

## Entry points

- `frontend/src/components/NetflowProgress.tsx` owns `useNetflowProgress` and the rendered `Processing progress` region.
- `frontend/src/components/NetflowResults.tsx` mounts it for the analysis fixed in the URL; `NetflowAnalysisActions.tsx` mounts the same state in Results, Inputs and Correlation so actions and display share one query key.
- `frontend/src/lib/netflow-progress.ts` is the pure identity/observation parser and terminal/cancellation derivation.

Only `analysis.provenance.backend === "netflow-bulk-v1"` enables the query. Legacy analyses keep their existing status/time and make no progress request. Progress never selects another analysis, rewrites the URL, or publishes a fetched row as a new current result.

## Display

- Actual `status` and `phase` labels; unknown raw values are shown, never inferred terminal.
- `files_completed / files_total`; a reported zero total stays zero. No percentage, progress bar or ETA.
- Absolute heartbeat time or `No heartbeat reported`; a missing, stale or zero heartbeat never became a failure.
- Observation time separately from heartbeat; cancellation shows `Cancellation requested` or `Processing cancelled`.

Terminal requires agreement: a success status needs the terminal phase and
`files_completed === files_total`; FAILED is terminal only for a failed or
cancelled phase. Polling is 5 seconds until that validated terminal state; a
terminal mount performs one read. An unresolved temporary read keeps retrying
for the same identity even when the parent detail is terminal.

The query key and cleanup lifetime are bound to the immutable identity/scope
fields (project, analysis, dataset, context, namespace, fixture, backend and
caller scope). A same-task status, quality or count refresh keeps the key and
the last observation; a real identity/scope change cancels and removes the old
query and rejects its late response.

`parseNetflowProgress` rejects a payload whose `files_completed` exceeds
`files_total`, so the boundary never accepts an impossible count. A reported
`0 / 0` stays valid.

## Error and cancellation matrix

| State | Trigger | Behavior |
| --- | --- | --- |
| temporary | network/5xx/408/429/other | Keep only the same-identity last observation, show a stale/read-error notice and retry; never mark the task FAILED or clear results. |
| refusal | 401/403/404/410, or a known bulk 409 (`netflow_context_revoked`, `netflow_artifact_integrity_failed`) | Clear progress content and stop polling. The Results deny gate and Correlation's existing denial path also clear the cached result/correlation rows for that fixed identity; the denial never crosses a true identity/scope change. This is not a legacy fallback and not permission to read the task. |
| identity/shape | wrong project/analysis/dataset/context/namespace/fixture/backend, completed greater than total, or malformed payload | Clear progress content and keep same-task retries; the payload is not data. Only the progress card clears; the result reader's own identity checks stay authoritative. |
| requested | server `cancel_requested` or a scoped POST acknowledgement | Show requested only while the mounted task is unfinished and no terminal non-cancel observation exists. |
| confirmed | one validated observation with `status=FAILED` and `phase=CANCELLED` | Show confirmed. No cross-endpoint stitching, error-code whitelist or local inference. |

All cancel success/catch/finally continuations are scoped to the exact mounted
analysis; a response for another analysis is never acknowledged.

## Mock API evidence

These tests use Playwright `page.route`; they remain separate from the real
runtime evidence and are not a backend PASS:

```sh
cd frontend
bunx playwright test tests/netflow-progress.component.spec.ts tests/netflow-results.component.spec.ts tests/netflow-correlation.component.spec.ts --project=component --workers=1 --reporter=line
```

The focused Results correction proves that a transient access/batch/progress
read failure keeps validated data with a stale notice (or offers a retryable
unavailable branch without initial data), while explicit access/batch/progress
refusals and an access identity mismatch still clear and block. The parsed
`completed > total` case and the same-task metadata-refresh retention during
transient progress errors each have a focused regression.

## Real runtime and UI evidence

`scripts/test-netflow-bulk-runtime.py` drives a new isolated PostgreSQL 18, the
API, agent-compose controller/guest and the real Vite UI. It deliberately
refuses a dirty checkout through `Run.check_identity`.

Entry points:

```sh
.venv/bin/python scripts/test-netflow-bulk-runtime.py NEW_EVIDENCE_DIR --scenario progress
.venv/bin/python scripts/test-netflow-bulk-runtime.py NEW_EVIDENCE_DIR --scenario capacity
.venv/bin/python scripts/test-netflow-bulk-runtime.py NEW_EVIDENCE_DIR --scenario all
```

- `capacity` (default) preserves the 128 MB / 4-file capacity run and the
  `raw_count > 100000` observation assertion. It also runs pre-claim
  cancellation, a real-UI live-lease cancel and a terminal UI view.
- `progress` (alias `small`) does not create the 128 MB input. It runs a 4 MB /
  4-file success, writes every progress sample before assertions, and reads the
  private PostgreSQL `netflow_bulk_jobs` and `netflow_bulk_members` rows for
  phase, lease, heartbeat, complete-file count and sum of `raw_count`. It then
  runs pre-claim cancellation and a bounded real-UI cancellation at 16 MB,
  retried once at 64 MB when the window is missed. A missed attempt that may
  still be running is first polled through the real progress API to a terminal
  state with a bounded wait; a still-running timeout fails honestly instead of
  starting an overlapping attempt.
- `all` runs both scenarios in one isolated environment.

`frontend/tests/netflow-bulk-runtime.spec.ts` starts the UI from the real
`Start selected context analysis` button, records every actual progress
response with `page.on("response")` (identity, HTTP status, phase, files,
heartbeat) into JSONL, observes an unfinished Results-page response, a later
response and terminal success, then asserts the visible terminal fields.
Cancellation is a real click on `Cancel bulk processing` after a live-lease
response. The test records the actual POST `/cancel` acknowledgement, visible
`Cancellation requested`, server `FAILED`/`CANCELLED`, visible
`Processing cancelled`, current-result retention and unreadable cancelled
result. Missed 16 MB windows are written under `ui-cancel-attempts/` and are a
MISSED result, never a PASS. The success test reads
`/netflow-results/current` at its own terminal success, before any later cancel
task starts, and saves that response identity and timestamp in
`ui-progress.json`; the Python verifier checks this snapshot plus the
independent progress and SQL readback. It does not require the later global
current to still name the success analysis. Each cancel attempt that reaches
a live lease instead records and asserts its own pre-click current result, so a
successful missed 16 MB attempt may legitimately become the retained current
without weakening the assertion. Progress events record
the response-time page URL; the success evidence requires the first unfinished
response to come from `/netflow-results` and both first and terminal responses
to be HTTP 200. No API route interception or manually emitted callback is used.

Failure persistence merges the error and traceback into the existing
`runtime-result.json`, preserving build, project and completed scenarios.
`samples` and progress events are written before assertions. The harness
captures its own controller, database and guest logs before removal, writes
`cleanup.json` with `docker ps`, `network ls` and guest readback, and removes
only its network, named containers and guests whose mount belongs to this
evidence directory. Cleanup status is derived from readback, not from `docker
rm` exit codes alone.

A real runtime/UI PASS requires a clean committed candidate and a new evidence
directory. This map does not claim that frozen run has executed.
