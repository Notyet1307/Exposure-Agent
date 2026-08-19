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
