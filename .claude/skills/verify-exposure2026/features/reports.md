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

Refresh and cross-route return still reset the page report selection, version page and unsaved edits, and report permalinks remain out of scope. The report evidence link inside the report body still replaces URL search with its fixed evidence parameters; that pre-existing caveat is unchanged. Report version pagination while editing remains the existing selection behavior, not a reading-entry guarantee.

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

Recent reading-entry coverage lives in `core-reading.component.spec.ts` (focus cycle, URL invariance, sticky-header clearance at three widths, keyboard traversal, open materials/drawer cycle, deep-link and material round trip) and `v2-reports.component.spec.ts` (same report DOM node across the cycle, version 26/version page/full body/draft retention with filters, GET-only requests, empty and model-unavailable states, new-result notice, delayed response, temporary failure and explicit expiry).

Also run the normal `bun run build` and a read-only `bunx biome check` on touched files. If no managed service is running, mark browser tests BLOCKED instead of starting an unapproved server or using Playwright `webServer`.

## Mock boundary and evidence limits

The component specs use Playwright `page.route` synthetic HTTP responses (401/403/404/410/400/409/418/503, `readable:false`, wrong IDs, gated/delayed responses) against the real frontend in Chromium. They prove frontend state/rendering/request behavior only. They do not prove the real backend contract, database, tenant permission revocation, material TTL, provider/model execution, or production deployment. `window.print` is stubbed; the real print dialog is not exercised. The direct probes under `implementation/fix-round-4/probes/round4-probe.ts` (classifiers and print epoch) and `implementation/fix-round-5/probes/round5-probe.ts` (a history refusal stays observed after collapsing to summary) are source-extraction/VM checks, not browser acceptance, and must be labeled as such. The reading-entry browser evidence under `implementation/` uses the same Chromium plus route-mock boundary; real browser UI zoom at 200% was not run, only a 720x450 CSS-viewport proxy.

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
- Mock boundary: both configs use real Chromium against the real frontend, with Playwright `page.route` catching every `/api/v1/**` request. All responses are synthetic (identity, paging, version/domain, 401/403/404/410, 503, delayed responses, expiry timestamps, hostile text). This proves frontend request/state/rendering behavior only, not the real backend contract, DTO/schema, permissions, retention, provider/model execution or deployment. No real customer/cloud/NetFlow data, credentials, PG, FastAPI, cloud source or model was read or started. A real backend/browser acceptance run remains NOT_RUN.
- New regression coverage in `frontend/tests/core-reading.component.spec.ts`: independent multi-page sources including PORT-only later pages; legacy/explicit-zero/overflow; Back/Forward and close; classification/core page/filter/sort/result resets; fixed material return and legacy parser compatibility; simultaneous 503+410 in both orders plus 401/403 refusal; `comparison_address_not_found` exemption; paging/domain/version contradictions; delayed old page; expiry with the drawer open; provenance/version/time/filter/zero/missing/hostile/long-IPv6 rendering; 1440/1280/390/375 geometry and screenshots. Item-7 report DOM/version page/full body/draft cycles stay covered by the existing `v2-reports.component.spec.ts` suite.
