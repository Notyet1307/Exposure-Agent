# Exposure-Agent private deployment boundary

Exposure-Agent is delivered as a single-customer, single-instance Docker Compose application. Customer infrastructure owns DNS, TLS termination, ingress policy, host hardening, image distribution, backups and rollout.

The repository contains no customer-environment deployment workflow or automatic certificate configuration.

## Runtime path

```text
customer network
  -> customer-managed HTTPS ingress (port 443)
       -> host loopback 127.0.0.1:8080
            -> frontend (Nginx)
                 -> static React application
                 -> /api -> backend (FastAPI)
                      -> db (PostgreSQL)
                      -> octobus -> CloudAtlas
                      -> agent-compose -> temporary Governance Runner
```

Only customer-managed HTTPS ingress is customer-facing. The supplied Compose file binds Nginx to `127.0.0.1:${WEB_HTTP_PORT:-8080}`; PostgreSQL, FastAPI, OctoBus and agent-compose remain internal. The ingress must replace `X-Real-IP` with the validated client address and set trusted forwarding headers.

## Configuration

Create runtime configuration outside Git:

```bash
cp .env.example .env
```

Replace every placeholder before deployment. Required installation-specific values include:

- `SECRET_KEY`, `FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD`;
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`;
- `DOCKER_IMAGE_BACKEND`, `DOCKER_IMAGE_FRONTEND`, `DOCKER_IMAGE_OCTOBUS`, `DOCKER_IMAGE_RUNNER`, `TAG`;
- `RUNNER_BUILD_VERSION`, `ARTIFACT_HOST_PATH`;
- `AGENT_COMPOSE_AUTH_TOKEN`, pinned `AGENT_COMPOSE_RUNTIME_VERSION`,
  `CLOUDATLAS_CAPSET_TOKEN`;
- the customer-internal OpenAI-compatible `MODEL_API_ENDPOINT`,
  `MODEL_API_PROTOCOL`, `MODEL_API_KEY`, `MODEL_IDENTITY`, and the non-secret
  `MODEL_CONFIG_REVISION`.

Generate independent random secrets, for example:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

The first-superuser values idempotently bootstrap the initial global Admin. OctoBus and agent-compose credentials must not enter PostgreSQL, application audit records, Git, image layers or ordinary logs. Restrict runtime `.env` permissions and store deployment secrets in the customer-approved secret mechanism.

`MODEL_API_KEY` is injected into agent-compose as a Secret and must never be
placed in `MODEL_CONFIG_REVISION`. Production model configuration must resolve
only to loopback, link-local, or private-network addresses. The qualification
runner rejects public addresses and Provider redirects; OpenAI, Codex and other
external model providers are not fallback paths.

`FRONTEND_HOST` and `BACKEND_CORS_ORIGINS` are only needed for trusted cross-origin development. The deployed browser uses same-origin `/api`.

## Start and verify

Use the base Compose file so development overrides are excluded:

```bash
docker compose -f compose.yml pull
docker compose -f compose.yml up -d --wait
```

`prestart` applies Alembic migrations and creates the initial Admin. `octobus-package-init` imports the product-owned package, and `agent-compose-project-init` installs the Governance Runner and Pi model-qualification agents before the backend starts.

Run the fixed non-customer qualification fixture after startup and whenever the
endpoint, model identity, protocol, non-secret model configuration, Runner
build, qualification contract, or pinned agent-compose runtime changes:

```bash
./scripts/qualify-model.sh
```

Only a `PASS` for the current binding is admitted. The command prints a
redacted verdict; inspect neither the model Secret nor raw Provider events in
ordinary logs.

Verify from the deployment host and then through customer HTTPS ingress:

```bash
curl --fail http://127.0.0.1:8080/login
curl --fail http://127.0.0.1:8080/health/live
curl --fail http://127.0.0.1:8080/health/ready
curl --fail https://exposure.example.com/login
curl --fail https://exposure.example.com/health/live
curl --fail https://exposure.example.com/health/ready
```

```bash
docker compose -f compose.yml ps
docker compose -f compose.yml logs backend frontend prestart octobus \
  octobus-package-init agent-compose agent-compose-project-init
```

## Persistent state

Four state stores form one coordinated recovery boundary:

| Store | Contents |
|---|---|
| `app-db-data` | PostgreSQL business facts, authorization, audit and Artifact metadata |
| `${ARTIFACT_HOST_PATH}` host bind | immutable CustomerUpload and generated report files |
| `octobus-data` | OctoBus package, Instance, Capset and credential state |
| `agent-compose-data` | agent-compose project, Session and runtime recovery state |

Compose prefixes named volume names with the deployment project name. `${ARTIFACT_HOST_PATH}` is not a named volume; backup tooling must capture that exact host path. `octobus-data` and `agent-compose-data` are secret-bearing and require encryption, restricted access and the same retention controls as deployment credentials.

## Coordinated backup

Before a volume-level backup:

1. block new ingress writes;
2. confirm no Governance Runner Session is active;
3. stop writers with `docker compose -f compose.yml stop backend agent-compose octobus`;
4. stop `db` as well when taking a filesystem-level PostgreSQL volume snapshot, or use a transaction-consistent PostgreSQL backup method;
5. capture all four stores under one recovery-set identifier before restarting services.

```bash
docker compose -f compose.yml stop backend agent-compose octobus db
# Customer-managed tooling captures app-db-data, octobus-data,
# agent-compose-data and the ARTIFACT_HOST_PATH directory together.
docker compose -f compose.yml start db octobus agent-compose backend
```

Do not remove persistent volumes during a normal upgrade. Record source revision, image digests, migration revision, environment configuration version without secret values, backup identifier, rollout and rollback procedure.

## Restore and verification

Restore all four stores from the same recovery set while the application is stopped, including the original ownership and permissions of `${ARTIFACT_HOST_PATH}`. Then use the normal startup path so all init services revalidate their contracts.

After restore, verify:

- Compose services and `/health/live`, `/health/ready`, `/login`;
- current Alembic revision and expected Project / CustomerUpload inventory;
- a sample of stored Artifact SHA-256 values against files under `${ARTIFACT_HOST_PATH}`;
- OctoBus package, Instance, Capset, method and credential inventory;
- agent-compose project and expected Session inventory;
- CloudAtlas SourceInstance fingerprints and one authorized read-only validation where required.

Any SourceInstance whose restored material differs from its stored fingerprint remains invalid until corrected and revalidated. Backup and restore are not accepted until all four stores and these checks agree.
