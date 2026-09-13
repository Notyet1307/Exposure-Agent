"""Immutable, non-secret model projects and scoped lease delivery over native Connect."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.domain import model_connections as service
from app.domain.models import (
    ModelConnectionLease,
    ModelConnectionOperation,
    ModelConnectionVersion,
)
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
    AgentComposeDraftNamespace,
    AgentComposeRunStart,
    _stable_id,
)

ROLES = (
    "model-connection-validator",
    "ai-investigation",
    "ai-analysis-report",
    "ai-governance-draft",
)


def client_for_version(version: ModelConnectionVersion) -> AgentComposeClient:
    return AgentComposeClient(
        ai_governance_draft_namespace=AgentComposeDraftNamespace(
            project_id=_stable_id("project", version.runtime_project_name),
            agent_name="ai-governance-draft",
        )
    )


def project_spec(version: ModelConnectionVersion) -> dict[str, Any]:
    env = [
        {"name": k, "value": v}
        for k, v in sorted(
            {
                "MODEL_CONNECTION_VERSION_ID": str(version.id),
                "MODEL_IDENTITY": version.model_identity,
                "RUNNER_BUILD_VERSION": version.runner_build_version,
                "AGENT_COMPOSE_RUNTIME_VERSION": version.runtime_version,
            }.items()
        )
    ]
    return {
        "name": version.runtime_project_name,
        "variables": [],
        "volumes": [],
        "workspaces": [],
        "mcpServers": [],
        "octobusServers": [],
        "agents": [
            {
                "name": role,
                "provider": "pi",
                "model": "customer/" + version.model_identity,
                "image": settings.DOCKER_IMAGE_RUNNER
                + ":"
                + version.runner_build_version,
                "driver": {"name": "docker", "docker": {}},
                "enabled": True,
                "env": env,
                "volumes": [],
            }
            for role in ROLES
        ],
    }


def _project(client: AgentComposeClient) -> dict[str, Any] | None:
    response = client._request(
        "/agentcompose.v2.ProjectService/GetProject",
        {"project": {"projectId": client.project_id}, "includeSpec": True},
        missing_ok=True,
    )
    return response.get("project") if response else None


def normalized_projection(spec: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(spec)
    # This pinned runtime omits empty Docker options when decoding a stored spec,
    # while dry-run emits the empty oneof. Keep every nonempty option significant.
    for agent in result.get("agents", []):
        driver = agent.get("driver", {})
        if driver.get("name") == "docker" and driver.get("docker") == {}:
            driver.pop("docker")
    return result


def ensure_project(version: ModelConnectionVersion, *, create: bool) -> dict[str, Any]:
    client = client_for_version(version)
    spec = project_spec(version)
    checked = client._request(
        "/agentcompose.v2.ProjectService/ValidateProject", {"spec": spec}
    )
    if not checked or checked.get("valid") is not True:
        raise service.ModelConnectionError("model_connection_runtime_invalid")
    dry = client._request(
        "/agentcompose.v2.ProjectService/ApplyProject", {"spec": spec, "dryRun": True}
    )
    if not dry or not isinstance(dry.get("revision"), dict):
        raise service.ModelConnectionError("model_connection_runtime_invalid")
    revision = dry["revision"]
    expected = revision.get("spec")
    digest = revision.get("specHash")
    if not isinstance(expected, dict) or not isinstance(digest, str) or not digest:
        raise service.ModelConnectionError("model_connection_runtime_invalid")
    observed = _project(client)
    if observed is None and create:
        try:
            client._request(
                "/agentcompose.v2.ProjectService/ApplyProject",
                {"spec": spec, "submittedSpecHash": digest},
            )
        except AgentComposeBoundaryError:
            # A lost Apply response is resolved by observation, never a second Apply.
            pass
        observed = _project(client)
    if observed is None:
        raise service.ModelConnectionError("model_connection_runtime_unknown")
    summary = observed.get("summary", {})
    if (
        summary.get("projectId") != client.project_id
        or summary.get("name") != version.runtime_project_name
        or summary.get("sourcePath", "") != ""
        or summary.get("specHash") != digest
        or normalized_projection(observed.get("spec", {}))
        != normalized_projection(expected)
        or (
            version.runtime_spec_hash is not None
            and version.runtime_spec_hash != digest
        )
    ):
        raise service.ModelConnectionError("model_connection_runtime_conflict")
    rows = observed.get("agents", [])
    agents = {row.get("agentName"): row.get("managedAgentId") for row in rows}
    number = str(summary.get("currentRevision", ""))
    if (
        len(rows) != len(ROLES)
        or set(agents) != set(ROLES)
        or any(not isinstance(value, str) or not value for value in agents.values())
        or not number.isdigit()
        or int(number) < 1
        or (
            version.runtime_project_id is not None
            and version.runtime_project_id != client.project_id
        )
        or (
            version.runtime_project_revision is not None
            and version.runtime_project_revision != number
        )
        or (version.runtime_agents is not None and version.runtime_agents != agents)
    ):
        raise service.ModelConnectionError("model_connection_runtime_conflict")
    return {
        "spec_hash": digest,
        "project_id": client.project_id,
        "project_revision": number,
        "agents": agents,
    }


def runner_environment() -> tuple[dict[str, str], dict[str, str]]:
    # No model API Key, master key, key directory, or JWT signing secret goes to the runtime.
    names = (
        "ENVIRONMENT",
        "POSTGRES_SERVER",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_DB",
        "NETFLOW_MAX_BYTES",
        "OCTOBUS_URL",
        "AGENT_COMPOSE_URL",
        "AGENT_COMPOSE_PROJECT_NAME",
        "MODEL_CONNECTION_INTERNAL_URL",
        "MODEL_QUALIFICATION_ALLOW_BAIZHI_TEST",
        "AI_INVESTIGATION_ALLOW_BAIZHI_TEST",
        "AI_ANALYSIS_REPORT_ALLOW_BAIZHI_TEST",
        "AI_INVESTIGATION_SYNTHETIC_MANIFEST",
        "AI_ANALYSIS_REPORT_SYNTHETIC_MANIFEST",
    )
    env = {name: str(getattr(settings, name)) for name in names}
    env.update(
        PROJECT_NAME="model-connection-task",
        FIRST_SUPERUSER="runner@example.com",
        FIRST_SUPERUSER_PASSWORD="unused-model-runner",
    )
    private = {
        "POSTGRES_PASSWORD": settings.POSTGRES_PASSWORD,
        "AGENT_COMPOSE_AUTH_TOKEN": settings.AGENT_COMPOSE_AUTH_TOKEN.get_secret_value(),
        "CLOUDATLAS_CAPSET_TOKEN": settings.CLOUDATLAS_CAPSET_TOKEN.get_secret_value(),
    }
    return env, private


def _leases_environment(
    session: Session, family: str, task_id: uuid.UUID
) -> dict[str, str]:
    values = {}
    for lease in session.exec(
        select(ModelConnectionLease).where(
            ModelConnectionLease.family == family,
            ModelConnectionLease.task_id == task_id,
        )
    ).all():
        values["MODEL_LEASE_" + lease.purpose.upper()] = (
            str(lease.id) + ":" + service.lease_token(lease)
        )
    return values


def start_validation(operation_id: uuid.UUID) -> None:
    with Session(engine) as session:
        op = session.get(ModelConnectionOperation, operation_id)
        if op is None or op.status in {"SUCCEEDED", "FAILED"}:
            return
        binding = service.validation_binding(session, op.id)
        version = service.get_version(session, op.connection_id)
        private = _leases_environment(session, "validation", op.id)
        session.expunge(version)
    try:
        attested = ensure_project(version, create=True)
        env, secrets = runner_environment()
        env["RUNNER_BUILD_VERSION"] = version.runner_build_version
        secrets.update(private)
        env["MODEL_VALIDATION_OPERATION_ID"] = str(operation_id)
        env["MODEL_VALIDATION_RUN_ID"] = _stable_id(
            "run",
            binding.agent_project_id,
            "model-connection-validator",
            "api",
            "model-validation:" + str(operation_id),
        )
        # Persist the accepted project hash before a worker can attest it.
        with Session(engine) as session:
            service.state_for_write(session)
            current = session.get(ModelConnectionOperation, operation_id)
            if current is None or current.status in {"SUCCEEDED", "FAILED"}:
                return
            service.validation_binding(session, operation_id)
            v = service.get_version(session, current.connection_id)
            v.runtime_spec_hash = attested["spec_hash"]
            v.runtime_project_id = attested["project_id"]
            v.runtime_project_revision = attested["project_revision"]
            v.runtime_agents = attested["agents"]
            current.status = "RUNNING"
            current.error_code = None
            session.add(v)
            session.add(current)
            session.commit()
        observed = client_for_version(version)._start_run(
            agent_name="model-connection-validator",
            client_request_id="model-validation:" + str(operation_id),
            environment=env,
            secret_environment=secrets,
            command="/app/.venv/bin/python -m app.model_connection_validator",
        )
        with Session(engine) as session:
            current = session.get(ModelConnectionOperation, operation_id)
            if current is not None and current.status not in {"SUCCEEDED", "FAILED"}:
                if observed.session_id is not None:
                    current.session_id = observed.session_id
                session.add(current)
                session.commit()
    except (AgentComposeBoundaryError, service.ModelConnectionError) as error:
        code = error.code
        with Session(engine) as session:
            op = session.get(ModelConnectionOperation, operation_id)
            if op is not None and op.status not in {"SUCCEEDED", "FAILED"}:
                op.status = "UNKNOWN"
                op.error_code = code
                session.add(op)
                session.commit()


def reconcile_validation(operation_id: uuid.UUID) -> None:
    with Session(engine) as session:
        op = session.get(ModelConnectionOperation, operation_id)
        if (
            op is None
            or op.action != "VALIDATE"
            or op.status in {"SUCCEEDED", "FAILED"}
            or not op.agent_run_id
        ):
            return
        version = service.get_version(session, op.connection_id)
        run_id = op.agent_run_id
        session.expunge(version)
    try:
        observed = client_for_version(version).get_run(run_id)
    except AgentComposeBoundaryError:
        return
    if observed is not None and observed.is_terminal:
        with Session(engine) as session:
            service.finish_validation(
                session,
                operation_id,
                None,
                "model_connection_validation_result_missing",
            )


def start_business_task(record: Any, family: str) -> AgentComposeRunStart:
    from app.core.time import get_datetime_utc

    with Session(engine) as session:
        version = service.get_version(session, record.connection_version_id)
        purpose = "investigation" if family == "investigation" else "analysis_report"
        service.binding_for_task(session, purpose, record)
        lease = service.create_lease(
            session,
            version,
            family,
            purpose,
            record.id,
            record.agent_compose_run_id,
            record.timeout_seconds + 60,
            record.max_tool_calls + 1,
        )
        if lease.expires_at <= get_datetime_utc():
            raise service.ModelConnectionError("model_connection_lease_expired")
        token = service.lease_token(lease)
        lease_id = lease.id
        session.commit()
        # commit expires ORM state; the native project attestation is outside
        # this database transaction and therefore needs a loaded snapshot.
        session.refresh(version)
        session.expunge(version)
    ensure_project(version, create=False)
    env, secrets = runner_environment()
    env["RUNNER_BUILD_VERSION"] = version.runner_build_version
    secrets["MODEL_LEASE_" + purpose.upper()] = str(lease_id) + ":" + token
    if family == "investigation":
        env.update(
            AI_INVESTIGATION_ID=str(record.id),
            AI_INVESTIGATION_RUN_ID=record.agent_compose_run_id,
        )
        agent = "ai-investigation"
        nonce = "ai-investigation:" + str(record.id)
        module = "app.ai_investigation_runner"
    else:
        env.update(
            AI_ANALYSIS_REPORT_ID=str(record.id),
            AI_ANALYSIS_REPORT_RUN_ID=record.agent_compose_run_id,
        )
        agent = "ai-analysis-report"
        nonce = "analysis-report:" + str(record.id)
        module = "app.ai_analysis_report_runner"
    return client_for_version(version)._start_run(
        agent_name=agent,
        client_request_id=nonce,
        environment=env,
        secret_environment=secrets,
        command="/app/.venv/bin/python -m " + module,
    )
