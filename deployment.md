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
- when model qualification is enabled, the customer-internal OpenAI-compatible
  `MODEL_API_ENDPOINT`, `MODEL_API_PROTOCOL`, `MODEL_API_KEY`, `MODEL_IDENTITY`,
  non-secret `MODEL_CONFIG_REVISION`, and optional
  `MODEL_QUALIFICATION_TIMEOUT_SECONDS`.

Generate independent random secrets, for example:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

The first-superuser values idempotently bootstrap the initial global Admin. OctoBus and agent-compose credentials must not enter PostgreSQL, application audit records, Git, image layers or ordinary logs. Restrict runtime `.env` permissions and store deployment secrets in the customer-approved secret mechanism.

Leaving the model endpoint, identity, or Secret unset keeps admission
fail-closed without preventing the rest of the deployment from starting.
`MODEL_API_KEY` is injected into agent-compose as a Secret and must never be
placed in `MODEL_CONFIG_REVISION`. Production model configuration must resolve
only to loopback, RFC1918 private-network, or IPv6 ULA addresses. The
qualification runner rejects link-local and cloud metadata addresses, public
addresses, DNS rebinding, and Provider redirects; OpenAI, Codex and other
external model providers are not fallback paths.

`FRONTEND_HOST` and `BACKEND_CORS_ORIGINS` are only needed for trusted cross-origin development. The deployed browser uses same-origin `/api`.

### Local synthetic qualification with Baizhi

For the maintainer-approved local test exception only, see [ADR-0014](docs/adr/0014-allow-local-baizhi-synthetic-qualification.md).
Set `MODEL_QUALIFICATION_ALLOW_BAIZHI_TEST=true`, the exact endpoint
`https://ai-api-gateway.app.baizhi.cloud/api/openai`, protocol `responses`, and
the selected OMP model identity and credential in restricted runtime configuration.
The flag defaults to false. This enables only the fixed synthetic qualification
fixture; it does not enable public-provider product draft requests. Disable the
flag and remove the test credential before customer deployment.

### Local synthetic single-asset investigation

[ADR-0015](docs/adr/0015-allow-bounded-synthetic-ai-business-tasks.md) permits a
separate, default-closed local synthetic business path. Qualification PASS alone
does not permit business material to leave the deployment. Enable
`AI_INVESTIGATION_ALLOW_BAIZHI_TEST` only for the approved local synthetic
deployment, with the exact ADR-0014 endpoint and Responses protocol. Keep the
existing application security mode and private-model production default.

`AI_INVESTIGATION_SYNTHETIC_MANIFEST` is a single-line JSON array supplied by the
deployment operator, never by an API request or model. Each approved entry has
`project_id`, `run_id`, `resource_id`, nullable `finding_id`, `material_sha256`,
and `sources`. Each present source has `source_type`, `input_id`, `snapshot_id`,
and `content_sha256`; include all present sources sorted by `source_type`.
Absent NetFlow remains explicit in the material rather than a fabricated
snapshot. Asset-level and Finding-level scopes are separate permissions.

After independently confirming that every input and derived field is synthetic,
use `app.domain.ai_investigations.prepare_material` with an authorized Project,
an `InvestigationRequest`, and a fresh read-only REPEATABLE READ Session to
obtain the exact material and source identities. `material_hash` computes its
SHA-256 over sorted-key UTF-8 JSON, `ensure_ascii=False`, `allow_nan=False`,
and separators `(',', ':')`. This reader does not call a model or grant
permission. Install only the reviewed entries in restricted runtime
configuration and apply them to both backend and the `ai-investigation` agent.
New uploads, changed sources or different scopes require explicit review and
a new exact entry; a permitted project name or ID is insufficient.

The deployment fixes budgets before execution:

| Setting | Default |
| --- | --- |
| `AI_INVESTIGATION_TIMEOUT_SECONDS` | 120 seconds |
| `AI_INVESTIGATION_MAX_TOOL_CALLS` | 4 |
| `AI_INVESTIGATION_MAX_MATERIAL_BYTES` | 65536 cumulative bytes |
| `AI_INVESTIGATION_MAX_OUTPUT_BYTES` | 32768 bytes |

The supervisor receives database credentials; the Pi child receives only an
authenticated local bridge, with the single packaged `read_asset_facts` tool.
Do not add built-in tools, arbitrary extensions or Artifact mounts to this agent.
Build backend and Runner together, apply migrations, install the agent
definition, and qualify the current model binding before enabling creation.
Run controls, credential changes and a deployment switch retain their normal
authorization and drain/backup requirements.

Verify a Web-triggered investigation reaches a persisted terminal result, its
citations resolve within the fixed material, replay does not launch another
Session, Viewer creation is refused, and published facts remain unchanged.
An unknown or unreachable Session is not success; reading/replaying its saved
identity must not start a replacement. Only a confirmed failure permits an
explicit new attempt, preserving the failed record. Disable the business and
qualification exceptions and remove test credentials after local acceptance.

### agent-compose v2608.4.0 upgrade

This runtime derives Project and Run IDs from the project name without the
legacy source-path component. Before upgrading from the prior pinned runtime,
block new Governance Run triggers and finish every active or retryable Session;
do not carry an in-flight retry across the upgrade. Back up the coordinated
state, apply the new project, then rerun any unfinished business operation as a
new Governance Run. This bounded cutover preserves PostgreSQL business facts
while avoiding lookup or deduplication against the legacy ID space.

### `deterministic-report-v2` production cutover

[ADR-0013](docs/adr/0013-select-report-contract-by-pinned-netflow-presence.md)
changes new `governance-run-input-v1` dispatch in one step: no selected NetFlow
Dataset remains `deterministic-report-v1`; a selected Dataset becomes
`deterministic-report-v2`. There is no feature flag or dual-dispatch period.

Before deploying this change:

1. block new Governance Run Trigger, Retry and Rerun requests;
2. wait until every Project has no launch reservation (`governance_launch_*` is
   null) and PostgreSQL has no `RUNNING` GovernanceRun;
3. verify that every corresponding agent-compose Session is terminal and that
   no temporary Governance Runner remains active; an unreachable, unknown or
   unrecognized Session state blocks the cutover;
4. take the coordinated backup, then deploy the backend, Governance Runner
   image and frontend from the same release. Do not run an old API with the new
   Runner or the new API with an old Runner.

After health and readiness checks pass, re-enable Governance Run operations.
The next new absent-input Run must retain v1 and the next new present-input Run
must pin v2 in its fixed input Hash; a present Dataset with zero records or zero
positive activity still completes on v2. Existing Run pins and published v1
bytes are not migrated or backfilled, and Retry preserves the stored historical
contract. Rollback requires the same trigger block and drain; never rewrite or
delete a published v2 fact, report or Artifact.

## Start and verify

Use the base Compose file so development overrides are excluded:

```bash
docker compose -f compose.yml pull
docker compose -f compose.yml up -d --wait
```

`prestart` applies Alembic migrations and creates the initial Admin. `octobus-package-init` imports the product-owned package, and `agent-compose-project-init` installs the Governance Runner and Pi model-qualification agents before the backend starts.

The default runtime digest identifies upstream agent-compose v2608.4.0 at
revision `5df1acb0cda4159f7106f263e358c8a84026a142`; both service and guest images
carry that OCI source revision and remain pinned by multi-architecture manifest
digest.

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
