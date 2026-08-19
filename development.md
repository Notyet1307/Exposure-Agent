# Exposure-Agent development

## Runtime environment

Create the ignored local environment once from the repository root:

```bash
cp .env.example .env
mkdir -p /tmp/exposure-agent-artifacts
```

`.env.example` contains only local placeholders. Keep runtime `.env` files untracked and replace every secret, token and customer-specific value for a deployed installation.

Before the first Compose startup, set nonempty random `AGENT_COMPOSE_AUTH_TOKEN` and read-only `CLOUDATLAS_CAPSET_TOKEN` values in `.env`. The empty example values intentionally make Compose fail closed.

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

Nginx serves the frontend and proxies `/api` to FastAPI. Browser code uses relative API URLs. When Vite runs directly, its development proxy forwards `/api` to `API_PROXY_TARGET`, which defaults to `http://localhost:8000` and may be overridden in ignored `frontend/.env.local`.

The first startup can take a minute while PostgreSQL becomes healthy, Alembic applies migrations, OctoBus imports the product package, agent-compose initializes its project, and the initial Admin account is created.

```bash
docker compose ps
docker compose logs -f backend frontend agent-compose octobus
```

Stop without deleting persistent data:

```bash
docker compose down --remove-orphans
```

Use `docker compose down -v --remove-orphans` only for an explicitly isolated project whose data may be discarded.

## Local processes

To run Vite while keeping PostgreSQL and FastAPI in Compose:

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

## Client generation

Regenerate the TypeScript client whenever the FastAPI contract changes:

```bash
bash scripts/generate-client.sh
```

The script exports OpenAPI, regenerates `frontend/src/client`, and runs frontend linting. Generated output must not be edited by hand.

## Validation

```bash
python3 scripts/check-context-hygiene.py

cd backend
uv run bash scripts/lint.sh
uv run bash scripts/tests-start.sh

cd ../frontend
bun run lint
bun run build
bun run test

cd ..
docker compose -f compose.yml config --quiet
./scripts/test-compose-environment-parity.sh
```

Backend and browser tests require PostgreSQL. The browser suite uses the same relative `/api` contract as the Nginx application shell.

## Pre-commit checks

The repository uses [prek](https://prek.j178.dev/) for formatting and static checks:

```bash
uv run prek install -f
uv run prek run --all-files
```
