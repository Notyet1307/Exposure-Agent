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

Nginx forwards the original host, client address, and protocol headers. The customer ingress terminates TLS, proxies to the loopback listener, sets trusted forwarding headers, and restricts access to the host.

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
curl --fail http://127.0.0.1:8080/api/v1/utils/health-check/
curl --fail https://exposure.example.com/login
curl --fail https://exposure.example.com/api/v1/utils/health-check/
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

The current application database is stored in the `app-db-data` volume. Back it up before upgrades and verify restore procedures in the target environment. Do not remove volumes during a normal upgrade.

The broader architecture also requires persistent artifact and integration state when those later services are implemented. They are not part of issue #5 and must not be added to this application shell early.
