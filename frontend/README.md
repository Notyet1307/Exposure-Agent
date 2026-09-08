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

## Customer reading prototype (development only)

Use `/?prototype=customer&variant=A` after signing in to review three read-only
layouts. `A`, `B`, and `C` are selectable from the floating switcher; the route
is gated by `import.meta.env.DEV` and does not call or modify product APIs.

The layouts take structural inspiration only from [Landbook](https://land-book.com/)
and [Motionsites' feature-tabs prompt](https://motionsites.org/prompts/glassmorphic-feature-tabs):
compact analysis hierarchy and sectional navigation, respectively. No source code
or visual treatment is copied.

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


### Full-capability customer reading prototype

Preferred entry: `http://localhost:5174/?prototype=customer&reader=full`.
The earlier A/B/C sketches remain as comparison history; their simplified relationship diagram is not the implementation direction.

The full reader uses the existing published Run APIs, LineageScope, directed-path traversal, NodeDetails and ReportDetailDialog. It preserves all returned nodes/edges and the original eight edge semantics, partial coverage and immutable report boundaries. The synthetic Run is fixed to `becdfd4f-fdb4-47cb-90ad-2cf07fe0be8f`; this prototype must not be promoted as a general production reader without an implementation Issue.

Results and management share the sidebar. The graph has bounded scrolling and fit-width, while node details scroll independently on desktop. Resource scope is carried in the URL. A shared LocaleProvider now covers Chinese/English UI text across login, administration, settings, inputs, governance results, comparisons, lineage and report presentation. The default is Chinese and the choice persists. Customer values, protocol identifiers, hashes and original report content are preserved. This is still a prototype branch, not a production rollout.

Verification: production build; original lineage component suite 23 passed; live synthetic overview/single-resource, report identity/focus return, URL reload, fit-width and 390px overflow checks. No business data was mutated for this revision.


Localization verification: build, context hygiene, and 88 component tests passed. The locale behavior test checks default Chinese, changing to English without losing entered text, and persistence after reload. Existing component regressions explicitly run in English. Browser checks covered Chinese Admin pagination/validation and published-report labels. No account or password was changed by verification.
