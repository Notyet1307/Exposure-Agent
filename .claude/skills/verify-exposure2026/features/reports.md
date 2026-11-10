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
