"""Task-only provider proxy: original model keys never enter agent-compose or Pi."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from dataclasses import replace
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.core.time import get_datetime_utc
from app.domain import model_connections as service
from app.domain.model_qualification import ModelBinding, model_binding
from app.domain.models import (
    AiInvestigation,
    AnalysisReport,
    ModelConnectionLease,
    ModelConnectionOperation,
    ModelConnectionVersion,
)
from app.integrations.agent_compose import AgentComposeBoundaryError
from app.integrations.model_connection_runtime import client_for_version

MAX_PROXY_BODY = 8 * 1024 * 1024


def _task_binding(
    session: Session, lease: ModelConnectionLease
) -> tuple[service.ConnectionBinding, str, int]:
    """Reload authorization and fixed materials, not merely a cached token."""
    if (
        lease.expires_at <= get_datetime_utc()
        or lease.request_count >= lease.max_requests
    ):
        raise service.ModelConnectionError("model_connection_lease_expired")
    if lease.family == "validation":
        op = session.get(ModelConnectionOperation, lease.task_id)
        if (
            op is None
            or op.connection_id != lease.connection_id
            or op.agent_run_id != lease.agent_run_id
            or not op.session_id
        ):
            raise service.ModelConnectionError("model_connection_proxy_denied")
        binding = service.validation_binding(session, op.id)
        version = service.get_version(session, lease.connection_id)
        service.binding_for_version(session, version, lease.purpose)
        return binding, op.session_id, 32768
    if lease.family == "investigation":
        if lease.purpose != "investigation":
            raise service.ModelConnectionError("model_connection_proxy_denied")
        from app.domain import ai_investigations as investigations

        record = session.get(AiInvestigation, lease.task_id)
        if (
            record is None
            or record.status != "GENERATING"
            or record.connection_version_id != lease.connection_id
            or record.agent_compose_run_id != lease.agent_run_id
            or not record.session_id
        ):
            raise service.ModelConnectionError("model_connection_proxy_denied")
        _, _, candidate = investigations.load_material(
            project_id=record.project_id,
            user_id=record.initiated_by,
            scope=investigations.InvestigationRequest(
                resource_id=record.resource_id,
                run_id=record.run_id,
                finding_id=record.finding_id,
            ),
            record=record,
        )
        if not isinstance(candidate, service.ConnectionBinding):
            raise service.ModelConnectionError("model_connection_proxy_denied")
        return candidate, record.session_id, record.max_output_bytes
    if lease.family == "report":
        if lease.purpose != "analysis_report":
            raise service.ModelConnectionError("model_connection_proxy_denied")
        from app.domain import ai_analysis_reports as reports

        report = session.get(AnalysisReport, lease.task_id)
        if (
            report is None
            or report.status != "GENERATING"
            or report.connection_version_id != lease.connection_id
            or report.agent_compose_run_id != lease.agent_run_id
            or not report.session_id
        ):
            raise service.ModelConnectionError("model_connection_proxy_denied")
        _, _, candidate = reports.load_material(
            project_id=report.project_id,
            user_id=report.created_by_id,
            run_id=report.run_id,
            record=report,
        )
        if not isinstance(candidate, service.ConnectionBinding):
            raise service.ModelConnectionError("model_connection_proxy_denied")
        return candidate, report.session_id, report.max_output_bytes
    raise service.ModelConnectionError("model_connection_proxy_denied")


def forward(
    lease_id: uuid.UUID, token: str, suffix: str, body: bytes
) -> tuple[bytes, str]:
    if not token or len(token) > 255 or len(body) > MAX_PROXY_BODY:
        raise service.ModelConnectionError("model_connection_proxy_denied")
    digest = hashlib.sha256(token.encode()).hexdigest()
    # No database transaction spans the control-plane observation.
    with Session(engine) as session:
        lease = session.get(ModelConnectionLease, lease_id)
        if lease is None:
            raise service.ModelConnectionError("model_connection_proxy_denied")
        if not hmac.compare_digest(lease.token_hash, digest):
            lease.failure_code = "model_connection_proxy_token_rejected"
            session.add(lease)
            session.commit()
            raise service.ModelConnectionError("model_connection_proxy_denied")
        try:
            binding, sandbox, _ = _task_binding(session, lease)
        except ValueError as error:
            lease.failure_code = getattr(error, "code", "model_connection_proxy_denied")
            session.add(lease)
            session.commit()
            raise service.ModelConnectionError(
                "model_connection_proxy_denied"
            ) from None
        version = service.get_version(session, lease.connection_id)
        client = client_for_version(version)
        run_id = lease.agent_run_id
        expected_revision = version.runtime_project_revision
        expected_agent = (version.runtime_agents or {}).get(
            {
                "validation": "model-connection-validator",
                "investigation": "ai-investigation",
                "report": "ai-analysis-report",
            }[lease.family]
        )
        role = {
            "validation": "model-connection-validator",
            "investigation": "ai-investigation",
            "report": "ai-analysis-report",
        }[lease.family]
    try:
        run = client.get_run(run_id)
    except AgentComposeBoundaryError:
        raise service.ModelConnectionError("model_connection_proxy_denied") from None
    if (
        run is None
        or not run.is_active
        or run.session_id != sandbox
        or run.project_id != client.project_id
        or run.agent_name != role
        or run.project_revision != expected_revision
        or not expected_agent
        or run.agent_id != expected_agent
    ):
        # Keep the public capability response opaque, but leave a stable,
        # non-secret reason for the owning validation operation.
        with Session(engine) as session:
            lease = session.get(ModelConnectionLease, lease_id)
            if lease is not None:
                lease.failure_code = "model_connection_runtime_attestation_failed"
                session.add(lease)
                session.commit()
        raise service.ModelConnectionError("model_connection_proxy_denied")
    with Session(engine) as session:
        # ponytail: one bounded provider call holds a version read lock; optimize
        # admission/send separation only if measured revoke latency requires it.
        version = session.exec(
            select(ModelConnectionVersion)
            .where(ModelConnectionVersion.id == binding.connection_version_id)
            .with_for_update(read=True)
        ).one()
        lease = session.exec(
            select(ModelConnectionLease)
            .where(ModelConnectionLease.id == lease_id)
            .with_for_update()
        ).one()
        if not hmac.compare_digest(lease.token_hash, digest):
            raise service.ModelConnectionError("model_connection_proxy_denied")
        try:
            binding, current_sandbox, max_output = _task_binding(session, lease)
        except service.ModelConnectionError as error:
            lease.failure_code = error.code
            session.add(lease)
            session.commit()
            raise
        if current_sandbox != sandbox:
            raise service.ModelConnectionError("model_connection_proxy_denied")
        expected = (
            "responses" if binding.protocol == "responses" else "chat/completions"
        )
        try:
            payload = json.loads(body)
        except ValueError, UnicodeError:
            raise service.ModelConnectionError(
                "model_connection_proxy_denied"
            ) from None
        if (
            suffix != expected
            or not isinstance(payload, dict)
            or payload.get("model") != binding.model_identity
        ):
            raise service.ModelConnectionError("model_connection_proxy_denied")
        try:
            key = service.provider_key(session, version)
        except service.ModelConnectionError as error:
            lease.failure_code = error.code
            session.add(lease)
            session.commit()
            raise
        endpoint = urlsplit(binding.endpoint)
        address = binding.resolved_address
        if ":" in address:
            address = "[" + address + "]"
        target = urlunsplit(
            (
                endpoint.scheme,
                address + (":" + str(endpoint.port) if endpoint.port else ""),
                endpoint.path.rstrip("/") + "/" + expected,
                "",
                "",
            )
        )
        timeout = max(
            0.01, min(120.0, (lease.expires_at - get_datetime_utc()).total_seconds())
        )
        lease.request_count += 1
        session.add(lease)
        session.flush()
        failure = False
        response_body = bytearray()
        content_type = "application/json"
        try:
            with httpx.Client(
                trust_env=False, follow_redirects=False, timeout=timeout
            ) as http:
                with http.stream(
                    "POST",
                    target,
                    content=body,
                    headers={
                        "Authorization": "Bearer " + key,
                        "Content-Type": "application/json",
                        "Host": endpoint.netloc,
                    },
                    extensions={"sni_hostname": endpoint.hostname},
                ) as response:
                    if response.status_code != 200:
                        failure = True
                        lease.failure_code = (
                            "model_connection_authentication_failed"
                            if response.status_code in {401, 403}
                            else "model_connection_provider_failed"
                        )
                    else:
                        for chunk in response.iter_bytes():
                            response_body.extend(chunk)
                            if (
                                len(response_body) > max_output * 128 + 65536
                                or get_datetime_utc() >= lease.expires_at
                            ):
                                failure = True
                                break
                        if response.headers.get("Content-Type", "").startswith(
                            "text/event-stream"
                        ):
                            content_type = "text/event-stream"
        except httpx.HTTPError:
            failure = True
            lease.failure_code = "model_connection_provider_unavailable"
        if key.encode() in response_body:
            failure = True
            lease.failure_code = "model_connection_provider_secret_echo"
        if failure and lease.failure_code is None:
            lease.failure_code = "model_connection_provider_failed"
        # Failed and denied transport attempts consume their admitted lease use.
        session.commit()
    if failure:
        raise service.ModelConnectionError("model_connection_provider_failed")
    return bytes(response_body), content_type


def transport_binding(binding: ModelBinding, purpose: str) -> tuple[ModelBinding, str]:
    """Only the trusted runner reads this limited capability; child gets loopback."""
    if not isinstance(binding, service.ConnectionBinding):
        raise service.ModelConnectionError("model_connection_proxy_denied")
    try:
        identity, token = os.environ["MODEL_LEASE_" + purpose.upper()].split(":", 1)
        lease_id = uuid.UUID(identity)
    except KeyError, ValueError:
        raise service.ModelConnectionError("model_connection_proxy_denied") from None
    with Session(engine) as session:
        lease = session.get(ModelConnectionLease, lease_id)
        if (
            lease is None
            or lease.purpose != purpose
            or not hmac.compare_digest(
                lease.token_hash, hashlib.sha256(token.encode()).hexdigest()
            )
        ):
            raise service.ModelConnectionError("model_connection_proxy_denied")
        if (
            lease.expires_at <= get_datetime_utc()
            or lease.connection_id != binding.connection_version_id
        ):
            raise service.ModelConnectionError("model_connection_lease_expired")
    target = (
        settings.MODEL_CONNECTION_INTERNAL_URL.rstrip("/")
        + settings.API_V1_STR
        + "/model-connections/internal/"
        + str(lease_id)
    )
    try:
        pin = model_binding(
            endpoint=target,
            model_identity=binding.model_identity,
            protocol=binding.protocol,
            config_revision=binding.config_revision,
            runner_build_version=binding.runner_build_version,
            agent_compose_runtime_version=binding.agent_compose_runtime_version,
        )
    except ValueError:
        raise service.ModelConnectionError("model_connection_proxy_denied") from None
    return replace(
        binding, endpoint=pin.endpoint, resolved_address=pin.resolved_address
    ), token
