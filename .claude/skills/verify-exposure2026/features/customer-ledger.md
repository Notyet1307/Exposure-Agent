# Customer ledger

## Sub-features
Upload a customer XLSX, reject invalid structure or values, surface the accepted upload's returned identity with an explicit preview action, preview a first selection without changing the current pointer, explicitly set the current input, read the accepted ledger rows and fields, and refresh persisted values.

The first-selection path starts with no current input, then one accepted upload becomes current. Current runtime evidence also includes one real desktop Chromium journey that covers first-selection preview and apply, bounded replacement detail, a concurrent current-version conflict with explicit re-preview, and receipt recovery after a deliberately dropped apply response. That journey ran against real PostgreSQL 18.6, the API and Vite with synthetic data. It is feature-level evidence, not whole-project acceptance. Manual revisions, archiving, reports, large-ledger production capacity, non-Chromium browsers and real multi-browser concurrency remain NOT_RUN. See Verification status below for the current evidence and limits.

## How to get to it (user POV)
Sign in as an administrator. Create a project through the project form and land on `/?project=<ID>&view=inputs`. In the `Upload XLSX` card choose a file with the `XLSX file` input, then press the form's `Upload` button. The server validates the workbook. An accepted file appears in `Accepted uploads` with status `Available`, and the upload response is also shown as an accepted candidate card with its filename, ID, record count, profile version and warnings. The upload card offers `Preview this file`; selecting the row's `Preview selection` is the equivalent explicit action. Nothing is previewed or applied automatically, the project input is still `Not ready`, and the upload is not current until the user explicitly applies it. Choosing a local file only becomes submittable through `Upload`; previewing an accepted upload abandons that local choice, and cancelling the preview leaves `No file chosen` and asks for a file instead of submitting the abandoned selection.

Press `Preview this file` or the new file's row action `Preview selection`. A `Selection preview` card shows the candidate filename and/or ID, current and new record/IP counts plus added, removed and changed IP counts, and the candidate warnings. Press `Set as current input`. The confirmation says only `Operation confirmed.`; it does not claim the candidate is still current. Current ownership is read from the latest successful accepted-upload read. The confirmation also links to the existing `netflow-correlation` route with the current project and empty search; opening it only navigates and does not generate or run comparison results. Press `Customer asset ledger` in the sidebar, not a remembered URL. The ledger shows the fixed current version, total active records, distinct IPs, matching source records, and a row per source record. Press `Details` on a row to read its fields. A page reload keeps the same ledger version and rows.

## Driving it with the helper
Use the skill's [Launch prepare/check block and Helpers run block](../SKILL.md) with `--ledger` to execute the frozen helper. `--ledger` implies `--ui`. The helper reads the API-created project's actual upload profile through GET `/api/v1/projects/{id}/customer-upload-profile` and builds the fixtures from its `required_headers`. If those headers differ from the expected five headers, fixture generation returns BLOCKED, not a silently adapted workbook. The UI script separately reads the UI-created project's profile and requires it to match before uploading; a mismatch there is a product-consistency FAIL, not a skipped journey.

The real browser path executes in this order:

1. Login form, create project, reload, confirm the project id and heading.
2. Upload `customer-ledger-missing-header.xlsx`, a small workbook missing `web界面url`. Assert 422, code `missing_required_structure`, field `web_url`, and the visible message `The workbook is missing required structure.` with a `Web URL` diagnostic.
3. Upload `customer-ledger-port-70000.xlsx`, a small workbook with start and end port 70000. Assert 422, code `invalid_required_value`, field `start_port`, reason `port_out_of_range`, limit 65535, and the visible message plus `Port must be between 1 and 65535`.
4. After each rejected upload, assert the upload list still has count 0 and `current_customer_upload_id` is null, and the ledger read still has no `upload_id` or `current_upload_id`.
5. Upload `customer-ledger-valid.xlsx` with two rows built from the actual required headers: `192.0.2.10` and `192.0.2.11`, ports 443, `否`, empty URL. Assert 201, record_count 2, profile_version 1, the accepted message, an `Available` row, and that the project input is still `Not ready`.
6. Assert the current pointer is still null after upload and no POST to `/customer-ledger/replacements` has happened. The source also shows a candidate card with the returned filename and an explicit `Preview this file` action; the frozen helper does not assert that card.
7. Press `Preview selection` (the equivalent row action to `Preview this file`). Assert POST `/api/v1/projects/{id}/customer-ledger/replacements/preview` returns 200, `current_upload_id` is null, candidate record/IP counts are 2/2, added/removed/changed are 2/0/0, and `Selection preview` is visible.
8. Assert the current pointer is still null after preview and no apply request has happened.
9. Press `Set as current input`. Assert POST `/api/v1/projects/{id}/customer-ledger/replacements` returns 201 with the candidate id, `expected_upload_id` null, and the same project id. Assert the confirmation says `Operation confirmed.` and that the current pointer now equals the upload id.
10. Read the ledger through the public API. Assert upload id equals current upload id, revision id is null, count/total records/unique IPs are 2/2/2, both IPs are present, and each row has start port 443, end port 443, `is_web` `否`, and null `web_url`.
11. Press `Customer asset ledger` inside the sidebar. Assert the URL path `/projects/{id}/customer-ledger`, the heading, `2 matching source records`, `2 active records`, `2 distinct IPs`, and both rows with `443` and the web marker. Press `Details` on `192.0.2.10` and assert the field labels and values, including `Web URL` as `Not provided`.
12. Reload directly (pressing `Details` did not add a row filter) and assert the same two rows and `2 matching source records` persist.
13. Independently re-read GET `/api/v1/projects/{id}/customer-uploads`, GET `/api/v1/projects/{id}/customer-ledger`, read-only SQL for the project pointer/upload/artifact/replacement counts, and the persisted artifact file. Assert exactly one artifact exists, its SHA-256 equals the accepted upload `raw_sha256`, the SQL pointer equals the upload id, there is one replacement receipt, and there are zero manual revisions.

The UI uses the real replacements preview and apply endpoints. The old `POST /api/v1/projects/{id}/customer-uploads/{upload_id}/select` route is not the UI application path and must not be used to fake this journey. No response is mocked.

## Replacement detail revision (item 9)

This revision adds a read-only, fixed-basis source detail endpoint and an expandable detail panel inside the existing replacement preview. The category summary and apply flow are unchanged.

- Endpoint: `POST /api/v1/projects/{project_id}/customer-ledger/replacements/details`.
- Body: `{basis: {candidate_upload_id, expected_upload_id, expected_revision_id, expected_profile_id}, selector: {kind: "groups", category, skip, limit} | {kind: "records", category, canonical_ip, side, skip, limit}}`.
- `basis.expected_upload_id` and `basis.expected_revision_id` are required keys and nullable. Group limits default to 25 (max 25); record limits default to 10 (max 10). Extra keys, invalid limits, or invalid selectors return 422; an IP outside the selected category returns 404 `ledger_diff_group_not_found`. Offsets are bounded at `9007199254740991`; negative or larger values return 422.
- Group pages return `total_groups` and `groups[{canonical_ip, current_records, candidate_records}]`; record pages return `total_records` and up to 10 complete `records[{entry_id, position, canonical_ip, fields}]` for one side. Valid offsets at or below the bound past the total return an empty page with the truthful total.
- The envelope echoes the authenticated actor, the authorized project, the original basis, and the validated selector. Reads reauthorize `PROJECT_READ_ROLES`, revalidate the original basis through the same comparison rows as preview, and never pair records across files.
- Every response from this endpoint, including success, request-body validation errors, raised HTTP errors, and unexpected failures, returns `Cache-Control: private, no-store`. Validation errors use the app-registered sanitized handler and omit `input`. Unexpected, dependency, and response-validation failures return a generic 500 `{"detail": "Internal Server Error"}` without exception text and are logged with a traceback.
- New detail record fields use a distinct tagged number shape: `{kind: "number", numeric_type: "integer" | "float", value: string}`. The existing ledger API keeps its original `Cell` numbers. Integers carry exact decimal text, including `9007199254740993` and its negative; finite floats use Python's existing `repr`; booleans stay boolean and temporal cells pass through. Backend and frontend validate the tag and value syntax, and malformed tags are rejected. The exact renderer displays the tagged text with a visible `integer` or `float` label; a raw JavaScript number fails closed instead of rendering a rounded value. This does not recover numeric precision already lost in the source XLSX.
- The detail panel only reads. It never owns an apply key or digest, never writes sessionStorage, and never applies. Its query keys include actor, project, fresh preview generation, full basis, and selector. Caches clear on preview cancel, stale basis, denial, scope change, and unmount. Collapsing a category or IP subpanel only changes UI state; it does not clear that subpanel's cached query, and subpanel cache clearing is not implemented. A 409 version/profile response or a successful current-tuple refetch showing a different tuple invalidates only the matching unsubmitted preview and offers `Read latest version and preview again`; it cannot overwrite preparing, submitted, unknown, or confirmed state.
- The current-basis read and the detail page reads share one error classifier. 401, 403, 404, and the existing 400 `{"detail": "Inactive user"}` deny and clear private detail immediately; a 404 with `ledger_diff_group_not_found` remains the scoped group-missing state. Denial does not wait for another detail read or an accepted-upload owner query.
- Detail renders only in the unsubmitted `preview` flow. Starting apply preparation unmounts it and cancels its generation-scoped queries, so a late detail success or 409 cannot change preparing, submitted, unknown, or confirmed state. Historical receipt recovery and the original structured-404 resend rule are unchanged.

### Verification status for this revision

#### Current status (2026-11-11, rework-06 documentation correction)

This section records feature-level evidence. Non-author Standards/Spec reviews and the owner’s independent component-browser verification are complete for item 9; the owner’s final acceptance record is `final-acceptance.json` in the evidence root. This is not whole-project or complete G2 acceptance.

The cloud runtime run passed 104 backend tests with exit 0. That total is exactly 102 real PostgreSQL 18.6 API tests plus 2 isolated route tests. The 102 break down as 39 customer-ledger route tests on the real PostgreSQL 18.6 API, 43 customer uploads, 7 core comparisons, 4 analysis reports and 9 v2 reports. The 2 detail-route sanitization tests are isolated route tests, not real PostgreSQL. Evidence is in `cloud/runtime-rework04-20261111T1206Z/remote-evidence/logs/` (`pytest-customer-ledger.log`, `pytest-domain-sanitization.log` and the adjacent per-file logs), summarized by `rework-05/acceptance-evidence.json`.

One real journey passed, 1/1, in `replacement-detail.real.spec.ts`, test `real replacement detail, conflict, re-preview and receipt recovery`, duration 11.252 s. It ran against real PostgreSQL 18.6, the real API and Vite with synthetic data in one desktop Chromium. It covered:

- first-selection preview, bounded detail and cancel without apply;
- first explicit apply;
- replacement preview and category pages;
- a concurrent current-version conflict and explicit re-preview;
- a final real apply whose successful response was deliberately dropped as a transport fault (`route.fetch()` then `route.abort("failed")`), the UI `Replacement outcome unknown`, `Recover result` GET of the original receipt, and no second apply.

Evidence is `cloud/browser-retry-20261111T1306Z/evidence/real/real-report.json`, with the spec at `cloud/browser-retry-20261111T1306Z/verification/replacement-detail.real.spec.ts`. This is a custom spec, not the `verify-exposure2026.py --ledger` helper, and not a broad real-browser matrix.

The task owner independently reran the two repaired component test files locally and got 130/130 passed, 0 skipped, 0 unexpected, in 3.3 minutes. The 130 is 97 in `dashboard.component.spec.ts` plus 33 in `core-reading.component.spec.ts`. A focused rerun of the four repaired tests passed 4/4; it is a subset of the 130, not an additional count. Evidence is `rework-05/rerun/two-file-report.json`, `rework-05/rerun/focused-report.json` and the matching `.stdout` files. Adjacent evidence is 75/75 passed in the original cloud mock report, dashboard-results 23 plus reports 52. Those test files and their product code were unchanged, so they are reused from `cloud/browser-retry-20261111T1306Z/evidence/mock/mock-report.json` via `rework-05/unchanged-adjacent-browser.json`. The fresh two-file 130 and the reused adjacent 75 come from different runs and are not one fresh 205-test run.

Failure history is preserved. The earlier 205-test mock run was 201 passed and 4 failed, at `core-reading.component.spec.ts` line 1557 and line 2257, and `dashboard.component.spec.ts` line 6331 and line 6934. The 130/130 rerun repairs those four; it does not erase that history.

The frontend production build passed, exit 0, with `cd frontend && bun run build` on Vite 8.0.16. Evidence is `rework-05/author/checks/build.stdout` and `build.stderr`. The full frontend typecheck is NOT_PASS. `../node_modules/.bin/tsc --noEmit -p tsconfig.json` exits 2 with 55 baseline diagnostics, normalized-identical to the recorded 55 baseline, and this rework adds none. This documentation round ran no typecheck. The old 56 count is stale and historical; see the pre-cloud history note below.

At the cloud run there were 816 files. At the rework-05 comparison, after the cloud run and before this documentation update, only the two repaired test files differed; product code, dependencies and lockfiles were unchanged, per `rework-05/cloud-evidence-applicability.json`. This documentation update is an additional documentation-only change and does not affect the runtime evidence. The cloud VM is terminated and its disk retained; no new cloud run was made.

The following remain NOT_RUN or not established:

- the `verify-exposure2026.py --ledger` helper;
- non-Chromium browsers;
- production and large-ledger capacity;
- real multi-browser concurrency;
- external source or model calls;
- narrow-screen keyboard and multi-page checks, which have component-mock evidence only and no real-browser run;
- manual revisions and archiving, reports, and CloudAtlas or other external sources;
- the `ledger_key_conflict` branch and the structured-404 resend branch, which remain mock-only. The real journey covered version conflict and re-preview, plus transport-fault receipt recovery, not those two.

The fifth and sixth special acceptance items are unchanged. Item 9 scoped reviews are complete; there is no whole-project or complete G2 acceptance.

#### Superseded history: pre-cloud blocked state (2026-11-11)

This was the pre-cloud status retained from the earlier repair documentation. The current runtime evidence above supersedes it. The managed PostgreSQL restart approval timed out with `the user didn't answer the approval card in time; nothing changed`. That rework did not retry it and did not use a service, database connection, Playwright run, dev server or alternate port. Backend, API and browser runtime were then `BLOCKED`/`NOT_RUN`. Test collection, pure in-process ASGI and Pydantic probes, static React render, typecheck, lint, production build and a pure comparison benchmark were not runtime API or browser acceptance.

Checks recorded during the earlier repairs (historical, not runtime acceptance):

- `cd backend && uv run bash scripts/lint.sh` passed.
- `../.venv/bin/python -m pytest tests/api/routes/test_customer_ledger.py --collect-only -q` collected 38 tests. Tests were not executed because `tests/conftest.py` has a session-autouse PostgreSQL fixture.
- A pure in-process ASGI and Pydantic probe using the real sanitizer, real scoped route class and real models checked validation sanitization, unexpected, dependency and response-validation 500 responses with `private, no-store`, tagged large integers and floats, malformed tag rejection, and skip bounds.
- `cd frontend && bunx tsc -p tsconfig.json --noEmit` was previously described as 56 diagnostic output lines. Owner normalization identified 55 distinct baseline diagnostics; the old 56 wording was a counting error, not an additional resolved diagnostic. The current 55 baseline diagnostics remain, so this is not a green typecheck.
- `cd frontend && bun run build` passed. `cd frontend && bun run lint` passed.
- Static render of the actual exact field component with tagged `9007199254740993`, its negative, a finite float, booleans, temporal values, literal whitespace and a 32767-character value passed. A raw JavaScript number rendered as `unsupported value`, not a rounded number.
- A pure repeated-read comparison benchmark measured only the in-process `_compare_rows` path. Database, API serialization, XLSX parsing, network and browser costs are excluded, so it is not performance acceptance.

Historical, not current acceptance: the pre-rework candidate by author `ab058e90a00d48134`, recorded before the subsequent repair and cloud runs, retains author evidence of 32 backend tests, 75 component tests and one real-browser test passing in that author's task-private environment. That real test was the custom author journey in `runtime/verification/real-run.log`, not the `verify-exposure2026.py --ledger` helper. It is attached to that prior candidate and evidence identity and is historical; it is not independent acceptance of this rework. Its historical 75 component tests are a different run from the current adjacent 75 reused from the cloud mock report (dashboard-results 23 plus reports 52).

That historical revision did not run all DB and API tests (prepared in source but blocked), any Playwright component or browser execution, the `verify-exposure2026.py --ledger` helper, the real backend or browser journey, multi-user concurrent browsers, maximum-size fields through the API or PostgreSQL, non-Chromium browsers, PostgreSQL18 or Docker equivalence, or model and external-source calls.

## Gotchas
Read the actual profile before generating a workbook. The default required headers are `资产IP`, `起始端口`, `结束端口`, `是否web界面`, `web界面url`; a different profile blocks the synthetic fixture rather than weakening validation.

Upload success is not application. After a successful upload the row is `Available`, the project input remains `Not ready`, and the current pointer is still null. The helper asserts both the API pointer and the absence of an apply request before the explicit click.

The artifact appears at upload acceptance, before the explicit selection. The project smoke's empty-artifact assertion applies only before upload. After a successful upload assert exactly one artifact and its SHA-256, not an empty directory. In this path the artifact row is linked through `customer_uploads.artifact_id`; `artifacts.project_id` is null. Read-only SQL must join through `customer_uploads`, not filter `artifacts.project_id`.

The first selection has no ledger revision. After apply, `current_revision_id` and `revision` are null and the ledger shows `Accepted input`. That is expected for this path, not a persistence failure.

Clicking a ledger row's IP adds a `ledger_ip` filter to the URL. `Details` only opens the record panel and does not filter. Clear the filter with `All IPs` before reloading if the proof needs all rows; otherwise the reload correctly shows only the filtered row.

For an apply response with a definitive rejection status of 400, 401, 403, 404, or 422, the page clears the saved request identity and offers an explicit preview action again; it does not treat the result as unknown. For a 409, classify by the structured detail code. `ledger_version_conflict` or `ledger_profile_changed` retains the candidate and offers `Read latest version and preview again`; the user must then apply explicitly. `ledger_key_conflict` is a distinct message, clears the rejected intent, and never auto-retries. Other 409 codes are definitive rejections, not unknown outcomes.

For an unknown apply outcome, such as a network error or 5xx response outside those definitive statuses, the page retains the saved request identity and shows `Recover result`, which sends GET `/api/v1/projects/{id}/customer-ledger/replacements/{operation_key}`. A successful read confirms the receipt. Only a structured GET 404 with code `ledger_replacement_not_found` while the project is writable enables `Resend original request`, using the original identity and request. A generic 404 and other read errors retain the identity and do not enable resend. If a successful accepted-upload read later reports `can_select=false` and `can_upload=false` (readable but not writable), the page keeps the saved operation identity, its sessionStorage entry and receipt GET, keeps the submitted state across reload, and disables resend and apply until write access returns. A 401, 403 or 404 accepted-upload read failure is a real read denial and clears the saved identity.

The real-browser `--ledger` helper journey remains NOT_RUN for this revision. The current real evidence is the separate custom `replacement-detail.real.spec.ts` journey described under Verification status. It is one desktop Chromium run against real PostgreSQL 18.6, the API and Vite, and it covers candidate detail, version conflict and re-preview, and unknown-outcome receipt recovery after a deliberately dropped apply response. It is not the helper. A prior candidate retains one historical custom author real-browser run in `runtime/verification/real-run.log`; that run is historical evidence tied to that candidate, not independent current acceptance. The `ledger_key_conflict` branch and the structured-404 resend branch remain covered only by component mocks, not a real backend journey. Manual revisions and archiving, reports, CloudAtlas or external sources, model calls, Docker or other container equivalence, non-Chromium browsers, real multi-browser concurrency and large-ledger production capacity also remain NOT_RUN. Item 9 scoped reviews are complete; there is no whole-project or complete G2 acceptance.
