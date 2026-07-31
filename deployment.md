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
                      -> OctoBus (internal only) -> CloudAtlas
```

Only the customer-managed HTTPS ingress exposes port 443 to the customer network. The supplied Compose file binds Nginx's unencrypted listener to host loopback only (`127.0.0.1:${WEB_HTTP_PORT:-8080}`); it must never be forwarded or rebound directly to a customer-network interface. PostgreSQL, FastAPI, and OctoBus remain on the Compose network. Set `WEB_HTTP_PORT` only when the ingress needs a different loopback port.

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
- `DOCKER_IMAGE_OCTOBUS`
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

The `prestart` service waits for PostgreSQL, applies Alembic migrations, and creates the initial Admin before FastAPI starts. In parallel, `octobus-package-init` waits for OctoBus and idempotently imports the product-owned `cloudatlas-read` package baked into the OctoBus image; the backend starts only after both initialization paths succeed. This same path supports fresh and existing PostgreSQL and OctoBus volumes.

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
docker compose -f compose.yml logs backend frontend prestart octobus octobus-package-init
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

The current application persists authoritative business records in `app-db-data`, immutable CustomerUpload files in `app-artifact-data`, and OctoBus Instance configuration, credentials, Capsets, and imported package state in `octobus-data`. Treat all three volumes as one coordinated recovery set: a database backup without its matching Artifact backup can point to missing customer files, while a mismatched OctoBus backup can invalidate stored SourceInstance fingerprints or lose the credentials needed to revalidate them. Because `octobus-data` contains credentials, its backup must receive the same encryption and access controls as other secret-bearing deployment material. Compose prefixes the actual volume names with the deployment project name, so confirm the resolved names with `docker compose -f compose.yml config` or the customer backup tooling.

Before an upgrade or backup, stop API writes and OctoBus control-plane changes, then capture all three volumes at the same recovery point. One deployment-shaped sequence is:

```bash
docker compose -f compose.yml stop backend octobus
# Use customer-managed backup tooling to capture app-db-data,
# app-artifact-data, and octobus-data as one named, versioned recovery set.
docker compose -f compose.yml start octobus backend
```

Restore all three volumes from the same recovery set before starting the application. Use the normal Compose startup so `octobus-package-init` confirms the product package import, then verify the database migration revision, CustomerUpload list access, a sample of stored Artifact SHA-256 values, and the expected OctoBus Service/Instance/Capset inventory. Any SourceInstance whose restored material differs from its stored fingerprint remains invalid until the material is corrected and the single read-only validation succeeds. Do not remove any persistent volume during a normal upgrade, and record backup completion and restore verification in the release handoff.

agent-compose persistence must join this coordinated backup procedure when that service enters the delivered Compose stack.
