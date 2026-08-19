# Exposure-Agent backend

The backend is the FastAPI control plane and deterministic governance runtime. PostgreSQL is the authoritative structured business store.

## Requirements

- Docker with Compose
- [uv](https://docs.astral.sh/uv/)

Install the pinned backend environment from `backend/`:

```bash
uv sync
```

## Current structure

- `app/models.py`: authentication and user models retained by the application shell;
- `app/domain/models.py`: Project, CustomerUpload, SourceInstance, GovernanceRun, IP Resource, Finding, report and audit models;
- `app/domain/`: deterministic validation, governance, report and external-boundary logic;
- `app/api/routes/`: authenticated HTTP routes;
- `app/integrations/`: agent-compose and other runtime clients;
- `app/alembic/versions/`: append-only database migration history;
- `tests/`: unit, integration, migration and API checks.

OctoBus is the external CloudAtlas boundary. agent-compose owns Runner Session scheduling and isolation, but never replaces PostgreSQL GovernanceRun facts. CustomerUpload and generated report files live under the configured Artifact root; the database stores their metadata and hashes.

## Validation

From `backend/`:

```bash
uv run bash scripts/lint.sh
uv run bash scripts/tests-start.sh
uv run coverage report --fail-under=90
```

The full test suite requires a reachable PostgreSQL configured by the repository root `.env`. See [development.md](../development.md) for the Compose path.

## Migrations

Schema changes require a new Alembic revision:

```bash
uv run alembic revision --autogenerate -m "describe the schema change"
uv run alembic upgrade head
```

Review generated SQL and migration tests before committing. Committed Alembic migrations must never be deleted or rewritten; fix later schema changes with a new revision.
