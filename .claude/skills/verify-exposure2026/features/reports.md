# Analysis reports

Two read surfaces share a read-only contract but do not share capabilities.

## Entry points

- V2: `frontend/src/components/V2AnalysisReportsPanel.tsx`, mounted from `CoreComparisonResults` on the comparison result view (`/projects/:projectId/netflow-correlation?result=<id>&binding=<id|none>`). Labels: "AI interpretation for this comparison" or "Explain this difference". V2 may expose summary/full material, revisions, revision editing/confirmation and printing.
- Legacy: `frontend/src/components/AnalysisReportsPanel.tsx`, mounted from the governance report detail (`GovernanceReports` / `ReportDetailDialog`). Label: "AI analysis reports". Legacy has no V2 TTL, independent revision history or material-readable capability; do not claim them here.

## Comparison reading entries

`CoreComparisonResults` renders a compact `阅读区域` / `Reading areas` navigation row before the existing materials disclosure. Its ordinary buttons appear in this fixed order.

- `记录与依据` / `Records and evidence` focuses the named `comparison-views` fieldset above the address table. It does not select a result, classification, row or evidence drawer.
- `AI 解读与报告` / `AI interpretation and reports` focuses a visible heading above `AiModelStatus` and the page V2 report panel. The report wrapper section is named by that heading through `aria-labelledby`, covering the interpretation heading, model status and reports rather than claiming to be only model status. `返回阅读入口` / `Back to reading areas` beside that heading returns focus to the entry row.
- `本次资料` / `Materials used here` opens the existing native `<details>` idempotently and focuses its summary. It never toggles the details closed. Native summary activation still closes it.

The entry row uses file-local DOM refs only. It does not write URL search/hash, call `change`/`fixed`/`navigate`/history APIs, mount or unmount sections, re-own report or query state, generate reports, sync sources or call a model. Focus uses `focus({preventScroll: true})` followed by instant center placement; the nav, records fieldset, report heading and materials summary all carry the same visible `2px` outline, and the short targets clear the sticky workspace header at 1440, 390 and 375 widths. With the non-modal evidence drawer open, the page report and edits stay mounted and the left-side reading row remains usable at desktop width. The report toggles are placed together on the left of its heading so the 560px drawer cannot cover `返回阅读入口`. Narrow screens still require the existing `关闭依据` / `Close evidence` control before page content is usable. The address table keeps its own horizontal scroll container.

Refresh and cross-route return still reset the page report selection, version page and unsaved edits, and report permalinks remain out of scope. The report evidence link inside the report body still replaces URL search with its fixed evidence parameters; that pre-existing caveat is unchanged. While a report draft exists or a save/re-read is in flight, the report-version select and pagination are disabled and the page-change handler refuses with an explicit message; printing is read-only and does not disable version controls.

## Error matrix

| State | Trigger (frontend) | Behavior |
| --- | --- | --- |
| temporary | 0/5xx or non-ApiError, including detail/list/history | Labeled temporary; re-read the same selected version; do not auto-select latest or generate. Edits are retained. |
| permission | 401/403 | Explicit refusal; clear content/edits/printing and block actions. Global `main.tsx` redirects only for `401 Not authenticated` and `403 Could not validate credentials`; a component-level 403 denial does not redirect. |
| inactive | HTTP 400 with object body `{"detail":"Inactive user"}` via `isInactiveAccountError` | Explicit account-level refusal; clear content/edits/cache and block actions. Other 400 responses stay unknown, not refusals. |
| not_found | 404 | "Not found, or this account is not authorized under the fixed scope"; do not assert backend existence; no replacement selection. |
| expired | V2 only: 410, `v2_report_material_expired`, or V2 `valid_until` elapsed | Material-period refusal; clear content/edits/printing/cache. Legacy maps 410 to unknown. |
| unavailable | `v2_report_material_unavailable` (200 `readable:false`, 409, 410) | Material refusal; clear content/edits/printing/cache. |
| invalid | `v2_report_material_invalid` (200 `readable:false`, 409, 410) | Material-integrity refusal; clear content/edits/printing/cache. |
| unreadable | 200 `readable:false` with an unknown/null reason | Explicit unreadable; do not assume a cause; clear content/edits/printing/cache. |
| unknown | Other ApiError statuses and identity mismatches | Generic, no permission/expiry claim; edits are retained and no report is generated. |
| 409 revision conflict | V2 save/confirm 409 without a material code | V2-only "This version changed since it was read." message; keep unsaved edits, do not block. This is not a read-path classification and not the legacy message. 409 with a material code follows the material-refusal row. |

Refusals outrank temporary/unknown across detail, list, and V2 history. The V2 full/summary toggle controls whether the revisions request is issued and keeps non-refusal history errors tied to the full view, but an explicit history refusal for the current selected report/revision is observed even after collapsing to summary. V2 history keeps the last known selected-report/revision boundary while detail is unavailable, so an in-flight history refusal is not lost when a detail 503 arrives. Explicit re-read clears the stored problem and reissues the same selected report/revision read. V2 printing captures a read epoch; explicit refusal cleanup invalidates a pending same-identity print GET before it can restore cache/print payload, and the epoch is checked again after the render-before-print frames.

## Item10 report sections and draft history (2026-11-12)

The V2 panel keeps the full report readable and adds a chapter locator before the full report body plus an in-place editor. This section describes the new behavior and its evidence; earlier reading-entry guarantees and caveats above remain in force.

### Chapter location and editing

- `V2AnalysisReportsPanel` renders a `Report chapters` navigation in full mode before `V2ReportContent`, so it precedes the first visible report heading in read and edit modes. Read mode reaches fixed facts, every `text.sections` heading, priority cases, data limits and fixed sources. A fact-only section focuses its read-only heading; sections with editable claims focus that claim's single editor in edit mode. The summary and unplaced groups are locatable only while editing because they have no separate read-mode chapter.
- The editor groups editable claims by chapter membership derived from `report.text` (`reportChapters.ts`): summary-only claims, each section, then unplaced claims. A claim listed in several sections has exactly one canonical textarea; every other occurrence shows an `Also appears in` membership list and a `Focus shared claim <id>` link to that same editor. Summary-only and unplaced claims are never silently dropped.
- Priority cases keep separate `Why verify this object · <address>` and `What to verify next · <address>` fields. Fact claims, fixed facts, sources, limits and citations remain read-only. The original AI draft stays a separate read-only disclosure.
- Saving sends only the captured draft's project/report id, `expected_revision = baselineRevision`, the edited narrative claims and the case fields. The report-bound draft records `scopeKey`, project, report, baseline revision, baseline/current values, conflict state and the last explicit reread result. It is not URL- or localStorage-backed and is never written automatically.
- While a draft exists or a write/re-read is busy, the version select and pagination are disabled inside a fieldset and the page-change handler refuses with `Save or discard your draft before changing report versions or pages.` The handler guard is defense in depth, not only the HTML attribute. Read-only printing is intentionally outside the write-busy gate so existing late-print defenses remain meaningful.
- A 409 revision conflict keeps the old draft text and old baseline, disables Save, and offers explicit `Re-read this report`, `Discard and restart from latest revision` and `Discard draft`. Re-read does not rebase the draft; it only records the latest revision/status. Restart is explicit and rebuilds the baseline from the cached latest DRAFT report. If the report was confirmed meanwhile, the draft becomes copy-only (`Unsaved draft text`, no Save/Confirm) until an explicit discard. Material refusals clear the draft and block the panel. Explicit reread, save and confirm capture `readEpoch.current` at request start and ignore any obsolete success or failure after a refusal increments the epoch; a late readable response cannot restore the cleared private cache, draft or errors. A fresh explicit reread after the refusal works normally.
- Confirmation is always a separate request/action from save. Saving leaves the report DRAFT; confirmation uses the captured current revision and removes edit/confirm controls once confirmed.

### Revision history boundary

- History is fetched only in full mode for the selected report and its observed revision. The UI compares only N with the exact N-1 snapshot. It never walks a chain or compares non-adjacent revisions.
- `reportHistory.ts` parses the raw revisions response before rendering: array, same report id, unique row id/revision, positive revision, exact report or address section tuple, claim id pattern/types, non-empty bounded prose and refs, pointer membership, unique case identity and limitations. Repeated summary/section pointers to known claims are accepted because the authoritative server contract accepts them; presentation dedupes repeated occurrences with stable keys while the ordered protected snapshot data is preserved. Invalid history is an explicit `role=alert`; it is never rendered as empty and never produces a plausible diff.
- A missing N-1 shows `Revision N-1 is not available, so no comparison is shown across the gap.` The selected current snapshot body still renders below the gap alert, with no before/after pair and no invented comparison. Revision 1 shows only the initial snapshot. Empty history is a distinct message. Metadata with missing/invalid status, time or actor is normalized to `Status unavailable`, `Time unavailable` and `Author unavailable`; an actor UUID, when present, is labeled as a recorded identifier, not a display name.
- The panel receives the current verified readable `report.text` and validates the selected snapshot, and any predecessor, against that protected structure (summary/section membership, claim types and refs, case identity/refs, limitations) in initial, gap and adjacent states. A selected mismatch shows an explicit fixed-structure mismatch notice, keeps the metadata list, and suppresses the selected body and every changed/unchanged/confirmation claim. A matching selected snapshot with a mismatching predecessor shows the notice plus the selected body alone, with no pair or comparison claim. If the current report has no verified text, history shows an explicit unavailable state and no snapshot body. When both match, the panel states whether full text changed, no narrative text changed, or only a DRAFT-to-CONFIRMED step occurred, and lists affected chapters from claim membership; an unplaced changed claim derives `Not placed in a chapter`. Snapshot bodies include all summary/section memberships plus the honest `Not placed in a chapter` group. Full before/after snapshot bodies are rendered side by side (stacked when narrow).
- A temporary history read failure shows a retry and no empty claim. A history refusal is observed even after collapsing to summary; the prior selected report/revision boundary is retained while detail is temporarily unavailable.

### Legacy reports

`AnalysisReportsPanel` keeps exactly its four narrative textareas (business summary, key differences, investigation/verification progress, next steps). A `Report chapters` locator focuses each current chapter heading in read mode and the corresponding textarea while editing. The panel always states that per-revision saved history is unavailable for legacy reports and that the revision number is not a readable history; no diff UI is added.

### Tests, real journey and residual limits

- New focused coverage: `frontend/tests/report-sections.component.spec.ts` (24 tests) covers the wrong-report PATCH regression with a forced page/version change; disabled and handler-guarded pagination during a gated in-flight save; locator-before-body DOM order and keyboard activation in read/edit; chapter locators, the single shared editor and summary-locator gating when every summary claim is also in a section; unplaced-claim history prose and affected group; server-valid repeated summary/section pointers with one canonical editor and no duplicate React keys; selected/predecessor validation against the current verified structure for initial, gap, identically corrupted pair, one bad predecessor, valid control and missing current text; gap selected-body rendering; address reports; save/confirm separation and read-only toggles; adjacent, initial, gap, empty, missing-metadata, invalid and failed history; ordinary conflict, confirmed-after-conflict, temporary reread failure, collapsed delayed refusal, 403/material-410 reread races with late readable responses and a fresh-reread control; and 375/390 overflow, wrapping and keyboard reachability. The legacy locator/notice test lives in `frontend/tests/reports.component.spec.ts`.
- Existing suites remain green: `report-sections` 24, `v2-reports` 60, `reports` 53, `core-reading` 33, run against the managed Vite at `http://127.0.0.1:5192` with the evidence-local config `/Users/yet/ops/tasks/exposure2026/report-sections-20261112/rework-01/author/tests/playwright.evidence.config.cjs` (workers 1, retries 0, no `webServer`). The earlier implementation config remains valid evidence for its own run.
- Real API/PG Chromium journey, no route mocks: `/Users/yet/ops/tasks/exposure2026/report-sections-20261112/implementation/author/browser/real-journey.spec.ts`, config `.../tests/playwright.browser.config.cjs`, logs/screenshots under `.../implementation/author/browser/`. The read leg verified the saved draft revision 2 and its 2/1 adjacent history. The write leg saved revision 3, a second API writer advanced revision 4 and caused a real 409, explicit reread did not rebase, restart saved revision 5, confirmation produced revision 6, and direct PATCH/confirm on the confirmed report both returned 409 `analysis_report_not_editable`. Browser writes were only the two same-report PATCHes and the confirm POST; no generation/create POST occurred. The fixture draft is now CONFIRMED revision 6, so the write leg is not idempotent; do not rerun it without reseeding.
- Rework-01 actual-backend read replay, no route mocks: `/Users/yet/ops/tasks/exposure2026/report-sections-20261112/rework-01/author/browser/real-read.spec.ts` with config `.../browser/playwright.config.cjs`. At 1280 and 375 it read CONFIRMED revision 6 and snapshots 1–6, asserted the chapter navigation is before the first report content by DOM order and bounding box, activated the first locator by keyboard, rendered before-2/after-3 prose and the confirmation-only step, and recorded 15 GET requests with zero writes. Screenshots, `run.log` and `readback-{1280,375}.json` live under `.../rework-01/author/browser/`. The earlier real write journey remains the unchanged write-path evidence; the new reread race is mock/probe-only and does not prove real permission revocation.
- Still out of scope/unchanged: no report permalink, no pre-edit version selection memory guarantee, the report body's evidence link still replaces URL search, the 560px address drawer still needs `Close evidence` before narrow page content is usable, and the real browser print dialog was not opened (print reauthorization remains covered by component tests with `window.print` stubbed).

## Managed Vite + component tests

Start Vite only through the managed dev-server tool (`mcp__chat__start_dev_server`) in `frontend` with `bun run dev -- --host 127.0.0.1`; do not use shell background/nohup. Point `PLAYWRIGHT_BASE_URL` at that managed URL. Every component-test command below must pass an evidence-local config through `--config`; the repository `playwright.config.ts` declares `webServer` and is not acceptable for component verification. Its `reuseExistingServer: !CI` only reuses an already reachable URL; when the managed endpoint is unavailable, the repository config launches `bun run dev` before anyone can intervene.

If the managed endpoint is unavailable, browser tests are BLOCKED. Do not start, or test starting, any unapproved listener, and do not fall back to the repository config or to any config that declares `webServer`.

Create the evidence-local config outside the repository under the task evidence directory. Omit `webServer` (or set it to `undefined`). Example for evidence root `<evidence-root>`.

```js
// <evidence-root>/playwright.evidence.config.cjs
module.exports = {
  testDir: "/Users/yet/Developer/exposure2026-result-reading-20261110/frontend/tests",
  testMatch: /.*\.component\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  preserveOutput: "always",
  reporter: "line",
  outputDir: "<evidence-root>/test-results",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:5184",
  },
}
```

For this task `<evidence-root>` is `/Users/yet/ops/tasks/exposure2026/result-reading-20261110/rework-01`, the config is `/Users/yet/ops/tasks/exposure2026/result-reading-20261110/rework-01/playwright.evidence.config.cjs`, and `outputDir` is `/Users/yet/ops/tasks/exposure2026/result-reading-20261110/rework-01/test-results`.

```sh
cd frontend
PLAYWRIGHT_BASE_URL=http://127.0.0.1:5184 bunx playwright test tests/core-reading.component.spec.ts --config /Users/yet/ops/tasks/exposure2026/result-reading-20261110/rework-01/playwright.evidence.config.cjs --reporter=line
PLAYWRIGHT_BASE_URL=http://127.0.0.1:5184 bunx playwright test tests/v2-reports.component.spec.ts --config /Users/yet/ops/tasks/exposure2026/result-reading-20261110/rework-01/playwright.evidence.config.cjs --reporter=line
PLAYWRIGHT_BASE_URL=http://127.0.0.1:5184 bunx playwright test tests/reports.component.spec.ts --config /Users/yet/ops/tasks/exposure2026/result-reading-20261110/rework-01/playwright.evidence.config.cjs --reporter=line
```

The CLI spec path selects the intended file; the config already fixes one worker, zero retries, and line output.

Recent report coverage lives in `report-sections.component.spec.ts` (item10 chapter/draft/history/conflict matrices). Recent reading-entry coverage lives in `core-reading.component.spec.ts` (focus cycle, URL invariance, sticky-header clearance at three widths, keyboard traversal, open materials/drawer cycle, deep-link and material round trip) and `v2-reports.component.spec.ts` (same report DOM node across the cycle, version 26/version page/full body/draft retention with filters, GET-only requests, empty and model-unavailable states, new-result notice, delayed response, temporary failure and explicit expiry).

Also run the normal `bun run build` and a read-only `bunx biome check` on touched files. If no managed service is running, mark browser tests BLOCKED instead of starting an unapproved server or using Playwright `webServer`.

## Mock boundary and evidence limits

The component specs use Playwright `page.route` synthetic HTTP responses (401/403/404/410/400/409/418/503, `readable:false`, wrong IDs, gated/delayed responses) against the real frontend in Chromium. They prove frontend state/rendering/request behavior only. They do not prove the real backend contract, database, tenant permission revocation, material TTL, provider/model execution, or production deployment. `window.print` is stubbed; the real print dialog is not exercised. The direct probes under `implementation/fix-round-4/probes/round4-probe.ts` (classifiers and print epoch) and `implementation/fix-round-5/probes/round5-probe.ts` (a history refusal stays observed after collapsing to summary), and the rework-01 probe `rework-01/author/probes/r5-epoch-probe.cjs` (late reread/save/confirm responses after a refusal set no cache; valid reread control still succeeds), are source-extraction/VM checks, not browser acceptance, and must be labeled as such. The reading-entry browser evidence under `implementation/` uses the same Chromium plus route-mock boundary; real browser UI zoom at 200% was not run, only a 720x450 CSS-viewport proxy.

## Fixed evidence comparison (2026-11-10)

`CoreComparisonResults` keeps one non-modal `Sheet` and one drawer scroller. With a fixed `core_address`, the drawer renders two independently headed, independently paginated full collections in DOM order: customer declarations then CloudAtlas observations. A wide viewport (`min-width: 1280px`) places them in two comparison-scoped columns; narrower views stack them in one column. The existing source jump buttons only focus/scroll their heading; they do not change URL state, select a source, pair rows, diff fields or navigate reports. The 560px sheet width is retained; measured column widths are at least 220px at 1280/1440 with wrapping and no drawer or document horizontal overflow. Narrow 390/375 views keep source jumps, both paginations and Close evidence reachable.

Search-state contract:

- `core_customer_page` and `core_cloud_page` are optional nonnegative safe integers bounded so `page * 25` is safe. Absent stays absent; explicit `0` is distinct. `resolveEvidencePages` lets the legacy selected source (`core_evidence=customer|cloud` plus `core_evidence_page`) supply that source's initial page and the other source starts at 0. The first page/state write materializes both resolved numbers and `core_evidence_page=0`, so legacy cannot later move to another source.
- Every source/page change uses the latest-search functional updater; this is not a second local page cache. An invalid/overflow page becomes 0 while `core_filter_invalid` stays visible and evidence reads stay disabled until an explicit reset.
- `back_customer_page` and `back_cloud_page` join the existing validated return chain; `ComparisonReturnLink` maps them. `back_evidence_page` remains for legacy links. Closing the drawer and every address-clearing reset (classification, core page, IP filter, sort, clear, result change, view evidence) resets both source pages and the legacy field.
- Each source issues its own fixed GET `/comparison-results/:id/addresses/:addressKey/evidence` keyed by result/address/source/page with skip `page*25`, limit 25. There is no later-page prefetch and no latest-source fallback. Envelope `result_id`, `address_key`, `source`, `skip`, `limit`, nonnegative count and every record's source/domain/version against the fixed summary pins are checked; contradictions are read errors, not empty. `count=0` with no rows is the only empty source state; a later empty page offers that source's first-page recovery.
- A required-source 401/403/404/410 (except `comparison_address_not_found`) from summary, rows, detail, customer proof or cloud proof denies the whole fixed result and clears prefix caches before peer content renders. `comparison_address_not_found` stays local to that source. Temporary failures, identity mismatches, expiry while open, and late old responses never substitute the other source, another page or a newer result.
- The drawer shows fixed result generation time, namespace, result/scope IDs and rule version; customer provenance and application time; separate CloudAtlas IP and PORT version blocks with IDs, source space, status, counts, completeness, collected/published/retain times, exact filter JSON and the empty-object caveat; per-record domain/fixed-version captions; raw original and availability in `<details>`. Customer start/end ports, CloudAtlas `live_port`, CloudAtlas PORT observations and NetFlow source-side ports each carry distinct role text. Missing metadata reads 未提供 / Not provided; raw text is literal React text with no HTML activation.

Task evidence root: `/Users/yet/ops/tasks/exposure2026/evidence-comparison-20261110/implementation`.

- Component suite config (repository spec files, evidence-local, no `webServer`): `/Users/yet/ops/tasks/exposure2026/evidence-comparison-20261110/implementation/playwright.repo.config.cjs`.
- Implementation-local browser probe config (`testDir` points into `implementation/probes`, no `webServer`, real Chromium): `/Users/yet/ops/tasks/exposure2026/evidence-comparison-20261110/implementation/playwright.probe.config.cjs`.
- Managed Vite used for this task: id `01a1c5f9-6598-73b7-8b8d-6bf5d85fa00d`, URL `http://127.0.0.1:5185`, PID `74590`. Do not start a fallback listener; if it is unavailable, browser evidence is BLOCKED.
- Screenshots: `implementation/screenshots/evidence-sources-{1440,1280,390,375}.png` and `probe-{1440,1280,390,375}.png`. Logs: `implementation/logs/`.
- Mock boundary: both configs use real Chromium against the real frontend, with Playwright `page.route` catching every `/api/v1/**` request. All responses are synthetic (identity, paging, version/domain, 401/403/404/410, 503, delayed responses, expiry timestamps, hostile text). This proves frontend request/state/rendering behavior only, not the real backend contract, DTO/schema, permissions, retention, provider/model execution or deployment. No real customer/cloud/NetFlow data, credentials, PG, FastAPI, cloud source or model was read or started. For that 2026-11-10 task, a real backend/browser acceptance run remains NOT_RUN; the item10 real API/PG journey above is the separate recorded run.
- New regression coverage in `frontend/tests/core-reading.component.spec.ts`: independent multi-page sources including PORT-only later pages; legacy/explicit-zero/overflow; Back/Forward and close; classification/core page/filter/sort/result resets; fixed material return and legacy parser compatibility; simultaneous 503+410 in both orders plus 401/403 refusal; `comparison_address_not_found` exemption; paging/domain/version contradictions; delayed old page; expiry with the drawer open; provenance/version/time/filter/zero/missing/hostile/long-IPv6 rendering; 1440/1280/390/375 geometry and screenshots. Item-7 report DOM/version page/full body/draft cycles stay covered by the existing `v2-reports.component.spec.ts` suite.
