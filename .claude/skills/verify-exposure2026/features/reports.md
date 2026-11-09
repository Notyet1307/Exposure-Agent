# Analysis reports

Two read surfaces share a read-only contract but do not share capabilities.

## Entry points

- V2: `frontend/src/components/V2AnalysisReportsPanel.tsx`, mounted from `CoreComparisonResults` on the comparison result view (`/projects/:projectId/netflow-correlation?result=<id>&binding=<id|none>`). Labels: "AI interpretation for this comparison" or "Explain this difference". V2 may expose summary/full material, revisions, revision editing/confirmation and printing.
- Legacy: `frontend/src/components/AnalysisReportsPanel.tsx`, mounted from the governance report detail (`GovernanceReports` / `ReportDetailDialog`). Label: "AI analysis reports". Legacy has no V2 TTL, independent revision history or material-readable capability; do not claim them here.

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

Start Vite only through the managed dev-server tool (`mcp__chat__start_dev_server`) in `frontend` with `bun run dev -- --host 127.0.0.1`; do not use shell background/nohup. Use a dedicated Playwright config with `webServer: undefined`, `testDir: frontend/tests` and `testMatch` for the two component specs; set `PLAYWRIGHT_BASE_URL` to the managed URL.

```sh
cd frontend
PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 bunx playwright test --config <dedicated-config> tests/v2-reports.component.spec.ts
PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 bunx playwright test --config <dedicated-config> tests/reports.component.spec.ts
```

Also run the normal `bun run build` and a read-only `bunx biome check` on touched files. If no managed service is running, mark browser tests BLOCKED instead of starting an unapproved server or using Playwright `webServer`.

## Mock boundary and evidence limits

The component specs use Playwright `page.route` synthetic HTTP responses (401/403/404/410/400/409/418/503, `readable:false`, wrong IDs, gated/delayed responses) against the real frontend in Chromium. They prove frontend state/rendering/request behavior only. They do not prove the real backend contract, database, tenant permission revocation, material TTL, provider/model execution, or production deployment. `window.print` is stubbed; the real print dialog is not exercised. The direct probes under `implementation/fix-round-4/probes/round4-probe.ts` (classifiers and print epoch) and `implementation/fix-round-5/probes/round5-probe.ts` (a history refusal stays observed after collapsing to summary) are source-extraction/VM checks, not browser acceptance, and must be labeled as such.
