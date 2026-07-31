# Exposure-Agent private deployment boundary

Exposure-Agent v0.1 is delivered as a single-customer, single-instance Docker Compose application. This repository builds the application services and their internal network; customer infrastructure owns DNS, TLS termination, ingress policy, host hardening, image distribution, backups, and release rollout.

The repository intentionally contains no customer-environment deployment workflow or automatic certificate configuration.

## Runtime path

The persistent application stack is:

```text
customer network
  -> customer-managed HTTPS ingress (port 443)
       -> host loopback 127.0.0.1:8080
            -> governance-web (Nginx, container port 80)
                 -> static React application
                 -> /api -> governance-api (FastAPI, internal port 8000)
            -> PostgreSQL (internal only)
```

Only the customer-managed HTTPS ingress exposes port 443 to the customer network. The supplied Compose file binds Nginx's unencrypted listener to host loopback only (`127.0.0.1:${WEB_HTTP_PORT:-8080}`); it must never be forwarded or rebound directly to a customer-network interface. PostgreSQL and FastAPI remain on the Compose network. Set `WEB_HTTP_PORT` only when the ingress needs a different loopback port.

Nginx forwards the original host, client address, and protocol headers. The customer ingress terminates TLS, proxies to the loopback listener, replaces `X-Real-IP` with the validated client address, sets the other trusted forwarding headers, and restricts access to the host.

## Required configuration

Before starting a deployed installation, provide installation-specific values for:

- `SECRET_KEY`
- `FIRST_SUPERUSER`
- `FIRST_SUPERUSER_PASSWORD`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `DOCKER_IMAGE_BACKEND`
- `DOCKER_IMAGE_FRONTEND`
- `TAG`

Generate independent random values for secrets, for example:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Do not use the checked-in local placeholders. The first-superuser values bootstrap the initial global Admin idempotently; subsequent accounts are managed by that Admin.

`FRONTEND_HOST` and `BACKEND_CORS_ORIGINS` are only needed when a trusted development client calls FastAPI from a different origin. The deployed browser uses the same-origin `/api` path and does not require a public backend origin.

## Start and verify

Use the base Compose file for a deployment-shaped startup so local development overrides are not applied:

```bash
docker compose -f compose.yml pull
docker compose -f compose.yml up -d --wait
```

The `prestart` service waits for PostgreSQL, applies Alembic migrations, and creates the initial Admin before FastAPI starts. This same path supports both a fresh database and an existing database from the imported template baseline.

Verify the private ingress upstream from the deployment host (the customer-facing check must use its HTTPS URL):

```bash
curl --fail http://127.0.0.1:8080/login
curl --fail http://127.0.0.1:8080/health/live
curl --fail http://127.0.0.1:8080/health/ready
curl --fail https://exposure.example.com/login
curl --fail https://exposure.example.com/health/live
curl --fail https://exposure.example.com/health/ready
```

Inspect startup state without exposing internal services:

```bash
docker compose -f compose.yml ps
docker compose -f compose.yml logs backend frontend prestart
```

## Build and release handoff

Build-and-test GitHub Actions validate the source, images, migrations, Compose stack, and retained browser flows. They do not connect to an installation or release into a customer environment.

A customer-specific release process should consume reviewed images and record at least:

- source revision and image digests;
- environment configuration version, excluding secret values;
- database migration revision;
- rollout and rollback procedure;
- backup completion and restore verification.

Release orchestration belongs to the customer's delivery environment and must not be added to this repository without a new accepted decision.

## Persistence and backup

The current application persists authoritative business records in the `app-db-data` volume and immutable CustomerUpload files in the `app-artifact-data` volume. Treat both volumes as one recovery set: a database backup without its matching Artifact backup can restore metadata that points to missing customer files. Compose prefixes the actual volume names with the deployment project name, so confirm the resolved names with `docker compose -f compose.yml config` or the customer backup tooling.

Before an upgrade or backup, stop API writes and capture both volumes at the same recovery point. One deployment-shaped sequence is:

```bash
docker compose -f compose.yml stop backend
# Use customer-managed backup tooling to capture app-db-data and
# app-artifact-data as one named, versioned recovery set.
docker compose -f compose.yml start backend
```

Restore both volumes from the same recovery set before starting the application. Verify the database migration revision, CustomerUpload list access, and a sample of stored Artifact SHA-256 values after restoration. Do not remove either volume during a normal upgrade, and record backup completion and restore verification in the release handoff.

OctoBus and agent-compose persistence must be added to the same coordinated backup procedure when those services enter the delivered Compose stack.
