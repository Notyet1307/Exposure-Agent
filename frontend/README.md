# Exposure-Agent frontend

The frontend uses Bun, Vite, React and TypeScript. Nginx serves the production build and proxies same-origin `/api` requests to FastAPI.

## Local development

Create the repository root runtime environment first, then run from `frontend/`:

```bash
bun ci
bun run dev
```

Vite forwards `/api` to `http://localhost:8000` by default. To point the local proxy at another trusted development backend, create the ignored `frontend/.env.local`:

```env
API_PROXY_TARGET=http://localhost:8000
```

The deployed browser should leave `VITE_API_URL` empty so API calls remain same-origin.

## Interface language

The application defaults to Simplified Chinese (`zh-CN`). The global language selector and the selector inside dialogs share one persisted preference (`exposure:language`); switching to English does not reload routes or reset forms, filters or report selections.

Use `useI18n` from `src/lib/i18n.tsx` for interface text and dates. Keep error keys untranslated in state and translate at render time so existing errors update when the language changes. Dates retain local-time behavior unless a field explicitly requests UTC. Protocol values, customer data and immutable report content are not rewritten.

Existing Playwright regressions import `tests/fixtures.ts` to select English at the actual test origin. The language-specific suite uses the product default directly; tests must not change that default or introduce a fixed origin.

## Theme keyboard interaction

The login and sidebar theme menus use Radix's default modal focus management, matching the other application menus. Selecting a theme or pressing Escape returns focus to the opening button, including when the menu is reopened during its closing animation. The language component suite covers both theme entry points.

## Published reading workspace

The shared sidebar separates published Overview, Assets & differences, Lineage and Reports from current project management. Project choices come from the authorized project API; published Run choices come from the cursor-paginated report list. Initial selection probes the newest compatible published result and writes its explicit Run into the URL. An unavailable explicit Project or Run is never silently replaced.

The URL preserves project/run scope, matrix classification and NetFlow filters, pagination, resource scope, and management list/detail state across refresh and navigation. Current assets, inputs and Findings remain current-project management views, not historical Run facts.

Overview reads `ip_source_comparison_summary` from the selected canonical report-v2; totals are independent of the matrix's 25-row pages. Report-v1 has no three-source summary and displays N/A rather than zero. The full matrix can trace resources beyond the bounded lineage overview. Snapshot metadata, identifiers and technical explanations are expandable; integrity failures, UNKNOWN/absence semantics and truncation limits remain visible.

## CloudAtlas asset entry

The single **CloudAtlas ledger / 云图原生资产账** navigation item opens `/projects/{projectId}/cloudatlas-ledger`. Its default **Synced assets** view reads independent IP, port-service, root-domain and DNS versions; no CustomerUpload, NetFlow, Run or Resource is required. Without a project, the entry asks for an accessible project using the existing selector. Source options name their supported domains; source setup and explicit synchronization remain on this page.

`asset_view=history` opens **Historical Run snapshots**, retaining the original snapshot, revision, profile and management APIs. Old explicit `cloud_*`/profile/customer query links select history before defaults are applied. New `external_*` links select synced assets. Mixed families or an invalid `asset_view` display a context error without mounting either reader; switching views explicitly starts a fresh query.

`/projects/{projectId}/external-assets` is a replace-only compatibility redirect, preserving supported fixed query identities and fragments. New internal links use the canonical route. Project/account changes discard the previous page's cached data and editors; saved synchronization intent stays actor/project/source scoped and is never replayed by navigation. The old root **CloudAtlas** source-management form remains `legacy-ip-v1` configuration for historical Runs and links to the independent source setup.

## NetFlow source correlation

The **NetFlow source correlation / NetFlow 来源关联** page at `/projects/{projectId}/netflow-correlation` fixes Dataset, processing context, Analysis, namespace, source versions, correlation revision, and feedback revision in the URL. It reads the generated `netflow-correlation-v1` client for summary, complete address pages, NetFlow-only clues, peers, source-side service comparisons, bounded evidence, review tasks, and append-only feedback. Explicit IDs never fall back to `latest`; changing the account, project, or fixed scope removes the page's scoped cache. The legacy NetFlow ledger remains available separately.


## Generated client

When the FastAPI contract changes, run from the repository root:

```bash
bash scripts/generate-client.sh
```

Commit the resulting `frontend/src/client/**` changes. Generated client files and `frontend/src/routeTree.gen.ts` must not be edited by hand.

## Validation

From `frontend/`:

```bash
bun run lint
bun run build
bun run test
```

Playwright requires the Compose application and test credentials from the ignored root `.env`. Use `bun run test:ui` only for interactive debugging.
