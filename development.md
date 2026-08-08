# Exposure-Agent development

## Docker Compose

Start the local stack from the repository root:

```bash
docker compose up -d --wait
```

The development override binds these entry points to host loopback only:

- application shell (Nginx): <http://localhost:5173>
- same-origin readiness check: <http://localhost:5173/health/ready>
- backend API for direct development and OpenAPI generation: <http://localhost:8000>
- backend API documentation: <http://localhost:8000/docs>
- PostgreSQL: `localhost:5432`

Nginx serves the frontend and proxies `/api` to FastAPI. Browser code uses relative API URLs in every environment. When Vite runs directly, its development proxy forwards `/api` to `API_PROXY_TARGET`, which defaults to `http://localhost:8000`.

The first startup can take a minute while PostgreSQL becomes healthy, Alembic applies migrations, and the initial Admin account is created. Inspect service state and logs with:

```bash
docker compose ps
docker compose logs -f backend frontend
```

Stop the stack without deleting PostgreSQL data:

```bash
docker compose down --remove-orphans
```

Use `docker compose down -v --remove-orphans` only when a clean database is intentional.

## Local processes

To run the frontend with Vite while keeping PostgreSQL and FastAPI in Compose:

```bash
docker compose stop frontend
cd frontend
bun ci
bun run dev
```

To run FastAPI directly while keeping PostgreSQL in Compose:

```bash
docker compose stop backend
cd backend
uv sync
uv run fastapi dev app/main.py
```

The checked-in `.env` contains local, non-production placeholders. Replace every secret for a deployed installation and do not commit customer credentials.

## Client generation

Regenerate the TypeScript client whenever the FastAPI contract changes:

```bash
bash scripts/generate-client.sh
```

The script exports the OpenAPI document, regenerates `frontend/src/client`, and runs frontend linting. Generated client output must not be edited by hand.

## Validation

Run focused checks while implementing and the relevant full checks before committing:

```bash
cd backend
uv run bash scripts/lint.sh
uv run bash scripts/tests-start.sh

cd ../frontend
bun run lint
bun run build
bun run test

cd ..
docker compose -f compose.yml config --quiet
docker compose -f compose.yml build
docker compose -f compose.yml up -d --wait
curl --fail http://127.0.0.1:8080/health/live
curl --fail http://127.0.0.1:8080/health/ready
curl --fail http://127.0.0.1:8080/login
docker compose -f compose.yml down -v --remove-orphans
```

Backend and browser tests require PostgreSQL. The browser suite uses the same relative `/api` contract as the Nginx application shell.

## Pre-commit checks

The repository uses [prek](https://prek.j178.dev/) for formatting and static checks. Install the Git hook and run all hooks manually with:

```bash
uv run prek install -f
uv run prek run --all-files
```
