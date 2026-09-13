"""Deployment-scoped model versions; saving or qualification never implies activation."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain.model_connection_secrets import (
    EncryptedModelConnectionSecret,
    ModelConnectionSecretError,
    decrypt_model_connection_secret,
    encrypt_model_connection_secret,
    model_connection_operation_fingerprint,
)
from app.domain.model_qualification import ModelBinding, model_binding
from app.domain.models import (
    DEPLOYMENT_TENANT_ID,
    AuditEvent,
    ModelConnectionLease,
    ModelConnectionOperation,
    ModelConnectionSecret,
    ModelConnectionState,
    ModelConnectionVersion,
)
from app.integrations.agent_compose import (
    AgentComposeClient,
    AgentComposeDraftNamespace,
    _stable_id,
)
from app.models import User


class ModelConnectionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ExpectedGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_generation: int = Field(ge=0, strict=True)


class SaveConnection(ExpectedGeneration):
    name: str = Field(min_length=1, max_length=255)
    endpoint: str = Field(min_length=1, max_length=2048)
    protocol: Literal["responses", "chat_completions"]
    model_identity: str = Field(min_length=1, max_length=255)
    api_key: SecretStr = Field(min_length=1, max_length=8192)

    @field_validator("name", "endpoint", "model_identity", mode="before")
    @classmethod
    def trim(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("invalid_connection_field")
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("invalid_connection_field")
        return value

    @field_validator("api_key")
    @classmethod
    def header_safe(cls, value: SecretStr) -> SecretStr:
        if any(ord(c) < 33 or ord(c) > 126 for c in value.get_secret_value()):
            raise ValueError("invalid_api_key")
        return value


class ConnectionPublic(BaseModel):
    id: uuid.UUID
    name: str
    endpoint: str
    protocol: str
    model_identity: str
    validation_status: str
    validation_operation_id: uuid.UUID | None
    created_at: datetime
    activated_at: datetime | None
    revoked_at: datetime | None
    discarded_at: datetime | None
    key_configured: bool = True
    validation_evidence: dict[str, Any] | None = None
    validation_completed_at: datetime | None = None


class OperationPublic(BaseModel):
    expected_generation: int
    id: uuid.UUID
    connection_id: uuid.UUID
    action: str
    status: str
    error_code: str | None
    evidence: dict[str, Any] | None
    created_at: datetime
    completed_at: datetime | None


class ConnectionStatePublic(BaseModel):
    generation: int
    adopted: bool
    active_id: uuid.UUID | None
    pending_id: uuid.UUID | None
    connections: list[ConnectionPublic]


class ConnectionActionPublic(BaseModel):
    operation: OperationPublic
    state: ConnectionStatePublic


class ConnectionStatus(BaseModel):
    state: Literal["legacy", "unconfigured", "active", "disabled", "unavailable"]
    configured: bool
    ready: bool = Field(
        description="Connection readiness only; project material access is checked separately."
    )
    active_version_id: uuid.UUID | None = None
    model_identity: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ConnectionBinding(ModelBinding):
    connection_version_id: uuid.UUID
    secret_version_id: uuid.UUID
    agent_project_id: str


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _key_directory() -> Path:
    if settings.MODEL_CONNECTION_KEY_DIRECTORY is None:
        raise ModelConnectionError("model_connection_secret_unavailable")
    directory = settings.MODEL_CONNECTION_KEY_DIRECTORY
    if directory.resolve().is_relative_to(Path(__file__).resolve().parents[3]):
        raise ModelConnectionError("model_connection_secret_unavailable")
    return directory


def _seal(
    value: bytes, version_id: uuid.UUID, secret_id: uuid.UUID, key_id: str
) -> EncryptedModelConnectionSecret:
    try:
        return encrypt_model_connection_secret(
            value,
            tenant_id=DEPLOYMENT_TENANT_ID,
            connection_id=version_id,
            secret_id=secret_id,
            key_directory=_key_directory(),
            key_id=key_id,
        )
    except ModelConnectionSecretError:
        raise ModelConnectionError("model_connection_secret_unavailable") from None


def _open(
    nonce: bytes,
    ciphertext: bytes,
    version_id: uuid.UUID,
    secret_id: uuid.UUID,
    key_id: str,
) -> bytes:
    try:
        return decrypt_model_connection_secret(
            EncryptedModelConnectionSecret(nonce, ciphertext),
            tenant_id=DEPLOYMENT_TENANT_ID,
            connection_id=version_id,
            secret_id=secret_id,
            key_directory=_key_directory(),
            key_id=key_id,
        )
    except ModelConnectionSecretError:
        raise ModelConnectionError("model_connection_secret_unavailable") from None


def secret_record(
    session: Session, version: ModelConnectionVersion
) -> ModelConnectionSecret:
    value = session.get(ModelConnectionSecret, version.secret_id)
    if value is None or value.tenant_id != version.tenant_id:
        raise ModelConnectionError("model_connection_secret_unavailable")
    return value


def provider_key(session: Session, version: ModelConnectionVersion) -> str:
    value = secret_record(session, version)
    try:
        return _open(
            value.nonce, value.ciphertext, version.id, value.id, value.key_id
        ).decode()
    except UnicodeError:
        raise ModelConnectionError("model_connection_secret_unavailable") from None


def get_version(session: Session, version_id: uuid.UUID) -> ModelConnectionVersion:
    value = session.get(ModelConnectionVersion, version_id)
    if value is None or value.tenant_id != DEPLOYMENT_TENANT_ID:
        raise ModelConnectionError("model_connection_not_found")
    return value


def state_for_write(session: Session) -> ModelConnectionState:
    session.connection().execute(
        insert(ModelConnectionState)
        .values(tenant_id=DEPLOYMENT_TENANT_ID, generation=0, adopted=False)
        .on_conflict_do_nothing()
    )
    value = session.exec(
        select(ModelConnectionState)
        .where(ModelConnectionState.tenant_id == DEPLOYMENT_TENANT_ID)
        .with_for_update()
    ).one()
    return value


def audit(
    session: Session, action: str, target: uuid.UUID, actor: uuid.UUID, **facts: Any
) -> None:
    session.add(
        AuditEvent(
            actor_subject=str(actor),
            actor_type="user",
            action="model_connection." + action,
            target_type="model_connection",
            target_id=target,
            after_data=facts,
        )
    )


def _fingerprint(action: str, request: dict[str, Any], key_id: str) -> str:
    try:
        return model_connection_operation_fingerprint(
            canonical(request),
            operation=action,
            key_directory=_key_directory(),
            key_id=key_id,
        )
    except ModelConnectionSecretError:
        raise ModelConnectionError("model_connection_secret_unavailable") from None


def existing_operation(
    session: Session, actor: User, action: str, key: str, request: dict[str, Any]
) -> ModelConnectionOperation | None:
    if not key or key.strip() != key or len(key) > 255 or any(ord(c) < 32 for c in key):
        raise ModelConnectionError("model_connection_idempotency_key_invalid")
    op = session.exec(
        select(ModelConnectionOperation).where(
            ModelConnectionOperation.tenant_id == DEPLOYMENT_TENANT_ID,
            ModelConnectionOperation.actor_id == actor.id,
            ModelConnectionOperation.action == action,
            ModelConnectionOperation.idempotency_key == key,
        )
    ).first()
    if op is not None and not hmac.compare_digest(
        op.request_fingerprint, _fingerprint(action, request, op.key_id)
    ):
        raise ModelConnectionError("model_connection_intent_conflict")
    return op


def new_operation(
    session: Session,
    actor: User,
    action: str,
    key: str,
    request: dict[str, Any],
    version: ModelConnectionVersion,
    generation: int,
) -> ModelConnectionOperation:
    op = ModelConnectionOperation(
        actor_id=actor.id,
        action=action,
        idempotency_key=key,
        request_fingerprint=_fingerprint(
            action, request, settings.MODEL_CONNECTION_KEY_ID
        ),
        key_id=settings.MODEL_CONNECTION_KEY_ID,
        connection_id=version.id,
        expected_generation=generation,
    )
    session.add(op)
    return op


def binding_for_version(
    session: Session,
    version: ModelConnectionVersion,
    purpose: str,
    *,
    verify_fingerprint: bool = True,
) -> ConnectionBinding:
    if version.revoked_at is not None or version.discarded_at is not None:
        raise ModelConnectionError("model_connection_revoked")
    if (
        version.runner_build_version != settings.RUNNER_BUILD_VERSION
        or version.runtime_version != settings.AGENT_COMPOSE_RUNTIME_VERSION
    ):
        raise ModelConnectionError("model_binding_changed")
    allowed = {
        "qualification": settings.MODEL_QUALIFICATION_ALLOW_BAIZHI_TEST,
        "investigation": settings.AI_INVESTIGATION_ALLOW_BAIZHI_TEST,
        "analysis_report": settings.AI_ANALYSIS_REPORT_ALLOW_BAIZHI_TEST,
    }.get(purpose, False)
    try:
        base = model_binding(
            endpoint=version.endpoint,
            protocol=version.protocol,
            model_identity=version.model_identity,
            config_revision=str(version.id),
            runner_build_version=version.runner_build_version,
            agent_compose_runtime_version=version.runtime_version,
            allow_baizhi_test=allowed,
        )
    except ValueError:
        raise ModelConnectionError("model_binding_changed") from None
    secret = secret_record(session, version)
    digest = hashlib.sha256(
        canonical(
            {
                "base": base.config_fingerprint,
                "address": base.resolved_address,
                "connection": str(version.id),
                "secret": str(secret.id),
                "key_id": secret.key_id,
                "cipher": hashlib.sha256(secret.nonce + secret.ciphertext).hexdigest(),
            }
        )
    ).hexdigest()
    if verify_fingerprint and (
        digest != version.fingerprint
        or base.resolved_address != version.resolved_address
    ):
        raise ModelConnectionError("model_binding_changed")
    values = asdict(base)
    values["config_fingerprint"] = digest
    return ConnectionBinding(
        **values,
        connection_version_id=version.id,
        secret_version_id=secret.id,
        agent_project_id=_stable_id("project", version.runtime_project_name),
    )


def binding_for_task(
    session: Session, purpose: str, record: Any | None = None
) -> ConnectionBinding | None:
    if record is None:
        state = session.get(ModelConnectionState, DEPLOYMENT_TENANT_ID)
        if state is None or not state.adopted:
            return None
        if state.active_id is None:
            raise ModelConnectionError("model_connection_disabled")
        version = get_version(session, state.active_id)
    elif record.connection_version_id is None:
        return None  # Legacy records never borrow the current active connection.
    else:
        version = get_version(session, record.connection_version_id)
        if record.tenant_id != version.tenant_id:
            raise ModelConnectionError("model_binding_changed")
    binding = binding_for_version(session, version, purpose)
    if record is not None and record.config_fingerprint != binding.config_fingerprint:
        raise ModelConnectionError("model_binding_changed")
    if (
        not version.runtime_project_revision
        or not version.runtime_agents
        or not version.runtime_project_id
    ):
        raise ModelConnectionError("model_not_qualified")
    if version.validation_status not in {"VALIDATED", "ACTIVATING"}:
        raise ModelConnectionError("model_not_qualified")
    validation = session.get(ModelConnectionOperation, version.validation_operation_id)
    if (
        validation is None
        or validation.status != "SUCCEEDED"
        or validation.connection_id != version.id
        or not validation.evidence
        or validation.evidence.get("fingerprint") != binding.config_fingerprint
    ):
        raise ModelConnectionError("model_not_qualified")
    return binding


def client_for_binding(binding: ModelBinding) -> AgentComposeClient:
    if isinstance(binding, ConnectionBinding):
        return AgentComposeClient(
            ai_governance_draft_namespace=AgentComposeDraftNamespace(
                project_id=binding.agent_project_id, agent_name="ai-governance-draft"
            )
        )
    return AgentComposeClient()


def save_connection(
    session: Session,
    actor: User,
    request: SaveConnection,
    key: str,
    *,
    adopt: bool = False,
) -> tuple[ModelConnectionOperation, bool]:
    state = state_for_write(session)
    payload = request.model_dump(exclude={"api_key"}, mode="json")
    payload["endpoint"] = request.endpoint.rstrip("/")
    payload["api_key"] = request.api_key.get_secret_value()
    action = "ADOPT" if adopt else "SAVE"
    existing = existing_operation(session, actor, action, key, payload)
    if existing is not None:
        # Release the deployment lock before a replay enters runtime's own transaction.
        session.commit()
        session.refresh(existing)
        return existing, True
    if state.generation != request.expected_generation:
        raise ModelConnectionError("model_connection_generation_conflict")
    if state.pending_id is not None:
        raise ModelConnectionError("model_connection_pending_exists")
    version_id, secret_id = uuid.uuid4(), uuid.uuid4()
    sealed = _seal(
        request.api_key.get_secret_value().encode(),
        version_id,
        secret_id,
        settings.MODEL_CONNECTION_KEY_ID,
    )
    secret = ModelConnectionSecret(
        id=secret_id,
        key_id=settings.MODEL_CONNECTION_KEY_ID,
        nonce=sealed.nonce,
        ciphertext=sealed.ciphertext,
    )
    version = ModelConnectionVersion(
        id=version_id,
        secret_id=secret_id,
        name=request.name,
        endpoint=request.endpoint.rstrip("/"),
        protocol=request.protocol,
        model_identity=request.model_identity,
        resolved_address="",
        fingerprint="",
        runner_build_version=settings.RUNNER_BUILD_VERSION,
        runtime_version=settings.AGENT_COMPOSE_RUNTIME_VERSION,
        runtime_project_name="exposure-model-" + str(version_id),
        created_by=actor.id,
    )
    session.add(secret)
    session.flush()
    binding = binding_for_version(
        session, version, "qualification", verify_fingerprint=False
    )
    version.fingerprint = binding.config_fingerprint
    version.resolved_address = binding.resolved_address
    session.add(version)
    session.flush()
    op = new_operation(session, actor, action, key, payload, version, state.generation)
    op.status = "SUCCEEDED"
    op.completed_at = get_datetime_utc()
    state.pending_id = version.id
    state.generation += 1
    session.add(state)
    audit(
        session,
        "saved",
        version.id,
        actor.id,
        operation_id=str(op.id),
        adopted_from_legacy=adopt,
    )
    session.commit()
    session.refresh(op)
    return op, False


def version_public(session: Session, v: ModelConnectionVersion) -> ConnectionPublic:
    result = ConnectionPublic.model_validate(v, from_attributes=True)
    op = (
        session.get(ModelConnectionOperation, v.validation_operation_id)
        if v.validation_operation_id
        else None
    )
    if op is not None and op.tenant_id == v.tenant_id and op.connection_id == v.id:
        result.validation_evidence = op.evidence
        result.validation_completed_at = op.completed_at
    return result


def operation_public(op: ModelConnectionOperation) -> OperationPublic:
    return OperationPublic.model_validate(op, from_attributes=True)


def state_public(session: Session) -> ConnectionStatePublic:
    state = session.get(ModelConnectionState, DEPLOYMENT_TENANT_ID)
    return ConnectionStatePublic(
        generation=state.generation if state else 0,
        adopted=state.adopted if state else False,
        active_id=state.active_id if state else None,
        pending_id=state.pending_id if state else None,
        connections=[
            version_public(session, v)
            for v in session.exec(
                select(ModelConnectionVersion)
                .where(ModelConnectionVersion.tenant_id == DEPLOYMENT_TENANT_ID)
                .order_by(col(ModelConnectionVersion.created_at))
            ).all()
        ],
    )


def action_public(
    session: Session, op: ModelConnectionOperation
) -> ConnectionActionPublic:
    return ConnectionActionPublic(
        operation=operation_public(op), state=state_public(session)
    )


def lease_token(lease: ModelConnectionLease) -> str:
    return _open(
        lease.token_nonce,
        lease.token_ciphertext,
        lease.connection_id,
        lease.id,
        lease.key_id,
    ).decode()


def create_lease(
    session: Session,
    version: ModelConnectionVersion,
    family: str,
    purpose: str,
    task_id: uuid.UUID,
    run_id: str,
    timeout: float,
    max_requests: int,
) -> ModelConnectionLease:
    existing = session.exec(
        select(ModelConnectionLease).where(
            ModelConnectionLease.family == family,
            ModelConnectionLease.task_id == task_id,
            ModelConnectionLease.purpose == purpose,
        )
    ).first()
    if existing is not None:
        if existing.connection_id != version.id or existing.agent_run_id != run_id:
            raise ModelConnectionError("model_binding_changed")
        return existing
    token = secrets.token_urlsafe(32)
    lease_id = uuid.uuid4()
    sealed = _seal(
        token.encode(), version.id, lease_id, settings.MODEL_CONNECTION_KEY_ID
    )
    lease = ModelConnectionLease(
        id=lease_id,
        connection_id=version.id,
        family=family,
        purpose=purpose,
        task_id=task_id,
        agent_run_id=run_id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_nonce=sealed.nonce,
        token_ciphertext=sealed.ciphertext,
        key_id=settings.MODEL_CONNECTION_KEY_ID,
        expires_at=get_datetime_utc() + timedelta(seconds=timeout),
        max_requests=max_requests,
    )
    session.add(lease)
    session.flush()
    return lease


def begin_action(
    session: Session,
    actor: User,
    version_id: uuid.UUID,
    action: str,
    request: ExpectedGeneration,
    key: str,
) -> tuple[ModelConnectionOperation, bool]:
    state = state_for_write(session)
    payload = {**request.model_dump(mode="json"), "connection_id": str(version_id)}
    existing = existing_operation(session, actor, action, key, payload)
    if existing is not None:
        # Release the deployment lock before a replay enters runtime's own transaction.
        session.commit()
        session.refresh(existing)
        return existing, True
    if state.generation != request.expected_generation:
        raise ModelConnectionError("model_connection_generation_conflict")
    version = session.exec(
        select(ModelConnectionVersion)
        .where(
            ModelConnectionVersion.id == version_id,
            ModelConnectionVersion.tenant_id == DEPLOYMENT_TENANT_ID,
        )
        .with_for_update()
    ).first()
    if version is None:
        raise ModelConnectionError("model_connection_not_found")
    if action in {"VALIDATE", "ACTIVATE", "DISCARD"}:
        if state.pending_id != version.id or version.revoked_at or version.discarded_at:
            raise ModelConnectionError("model_connection_not_pending")
        if version.validation_status in {"VALIDATING", "ACTIVATING"}:
            raise ModelConnectionError("model_connection_busy")
    if action == "ACTIVATE" and version.validation_status != "VALIDATED":
        raise ModelConnectionError("model_not_qualified")
    if action in {"VALIDATE", "ACTIVATE"}:
        binding_for_version(session, version, "qualification")
        provider_key(session, version)  # A missing/tampered key never reserves work.
    op = new_operation(session, actor, action, key, payload, version, state.generation)
    if action == "VALIDATE":
        version.validation_status = "VALIDATING"
        version.validation_operation_id = op.id
        op.agent_run_id = _stable_id(
            "run",
            _stable_id("project", version.runtime_project_name),
            "model-connection-validator",
            "api",
            "model-validation:" + str(op.id),
        )
        for purpose in ["qualification", "investigation", "analysis_report"]:
            create_lease(
                session,
                version,
                "validation",
                purpose,
                op.id,
                op.agent_run_id,
                300,
                1 if purpose == "qualification" else 3,
            )
    elif action == "ACTIVATE":
        version.validation_status = "ACTIVATING"
    elif action == "REVOKE":
        version.revoked_at = version.revoked_at or get_datetime_utc()
        pending_validation = (
            session.get(ModelConnectionOperation, version.validation_operation_id)
            if version.validation_operation_id
            else None
        )
        if pending_validation is not None and pending_validation.status not in {
            "SUCCEEDED",
            "FAILED",
        }:
            pending_validation.status = "FAILED"
            pending_validation.error_code = "model_connection_revoked"
            pending_validation.completed_at = get_datetime_utc()
            version.validation_status = "FAILED"
            session.add(pending_validation)
        if state.active_id == version.id:
            state.active_id = None
        if state.pending_id == version.id:
            state.pending_id = None
        op.status = "SUCCEEDED"
        op.completed_at = get_datetime_utc()
    elif action == "DISCARD":
        version.discarded_at = get_datetime_utc()
        state.pending_id = None
        op.status = "SUCCEEDED"
        op.completed_at = get_datetime_utc()
    else:
        raise ModelConnectionError("model_connection_action_invalid")
    state.generation += 1
    session.add(version)
    session.add(state)
    session.add(op)
    audit(
        session,
        action.lower() + "_requested",
        version.id,
        actor.id,
        operation_id=str(op.id),
    )
    session.commit()
    session.refresh(op)
    return op, False


def finish_validation(
    session: Session,
    operation_id: uuid.UUID,
    evidence: dict[str, Any] | None,
    failure: str | None = None,
) -> None:
    state = state_for_write(session)
    op = session.get(ModelConnectionOperation, operation_id)
    if op is None or op.action != "VALIDATE" or op.status in {"SUCCEEDED", "FAILED"}:
        return
    version = get_version(session, op.connection_id)
    if (
        version.validation_operation_id != op.id
        or version.revoked_at
        or version.discarded_at
    ):
        failure = "model_connection_revoked"
    actor = session.get(User, op.actor_id)
    if actor is None or not actor.is_active or not actor.is_superuser:
        failure = "model_connection_authorization_revoked"
    if not failure:
        try:
            binding = binding_for_version(session, version, "qualification")
            if evidence is not None and (
                evidence.get("operation_id") != str(op.id)
                or evidence.get("agent_run_id") != op.agent_run_id
                or evidence.get("session_id") != op.session_id
                or not version.runtime_spec_hash
                or evidence.get("runtime_spec_hash") != version.runtime_spec_hash
            ):
                failure = "model_connection_runtime_conflict"
            if (
                not evidence
                or evidence.get("fingerprint") != binding.config_fingerprint
                or any(
                    evidence.get(p) != "PASS"
                    for p in [
                        "qualification",
                        "investigation",
                        "analysis_report",
                        "runtime",
                    ]
                )
            ):
                failure = "model_connection_validation_failed"
        except ModelConnectionError as error:
            failure = error.code
    op.status = "FAILED" if failure else "SUCCEEDED"
    op.error_code = failure
    op.completed_at = get_datetime_utc()
    op.evidence = evidence if evidence is not None else op.evidence
    if version.validation_operation_id == op.id:
        version.validation_status = "FAILED" if failure else "VALIDATED"
        session.add(version)
    state.generation += 1
    session.add(state)
    session.add(op)
    audit(
        session,
        "validation_completed",
        version.id,
        op.actor_id,
        operation_id=str(op.id),
        status=op.status,
        error_code=failure,
    )
    session.commit()


def validation_binding(session: Session, operation_id: uuid.UUID) -> ConnectionBinding:
    op = session.get(ModelConnectionOperation, operation_id)
    if (
        op is None
        or op.action != "VALIDATE"
        or op.status not in {"PENDING", "RUNNING", "UNKNOWN"}
    ):
        raise ModelConnectionError("model_connection_validation_inactive")
    version = get_version(session, op.connection_id)
    actor = session.get(User, op.actor_id)
    if actor is None or not actor.is_active or not actor.is_superuser:
        raise ModelConnectionError("model_connection_authorization_revoked")
    if (
        version.validation_operation_id != op.id
        or version.validation_status != "VALIDATING"
    ):
        raise ModelConnectionError("model_connection_validation_inactive")
    return binding_for_version(session, version, "qualification")


def activate_after_attestation(
    session: Session, operation_id: uuid.UUID, *, failure: str | None = None
) -> None:
    state = state_for_write(session)
    op = session.get(ModelConnectionOperation, operation_id)
    if op is None or op.action != "ACTIVATE" or op.status in {"SUCCEEDED", "FAILED"}:
        return
    version = get_version(session, op.connection_id)
    actor = session.get(User, op.actor_id)
    if actor is None or not actor.is_active or not actor.is_superuser:
        failure = "model_connection_authorization_revoked"
    if state.generation != op.expected_generation + 1:
        failure = "model_connection_generation_conflict"
    if (
        state.pending_id != version.id
        or version.revoked_at
        or version.discarded_at
        or version.validation_status != "ACTIVATING"
    ):
        failure = "model_connection_activation_conflict"
    if not failure:
        try:
            binding = binding_for_version(session, version, "qualification")
            provider_key(session, version)
            validation = session.get(
                ModelConnectionOperation, version.validation_operation_id
            )
            if (
                validation is None
                or validation.status != "SUCCEEDED"
                or validation.connection_id != version.id
                or not validation.evidence
                or validation.evidence.get("fingerprint") != binding.config_fingerprint
            ):
                failure = "model_not_qualified"
        except ModelConnectionError as error:
            failure = error.code
    if failure:
        op.status = "FAILED"
        op.error_code = failure
        if version.validation_status == "ACTIVATING":
            version.validation_status = "VALIDATED"
    else:
        state.active_id = version.id
        state.pending_id = None
        state.adopted = True
        version.validation_status = "VALIDATED"
        version.activated_at = get_datetime_utc()
        op.status = "SUCCEEDED"
    op.completed_at = get_datetime_utc()
    state.generation += 1
    session.add(op)
    session.add(version)
    session.add(state)
    audit(
        session,
        "activation_completed",
        version.id,
        op.actor_id,
        operation_id=str(op.id),
        status=op.status,
        error_code=failure,
    )
    session.commit()
