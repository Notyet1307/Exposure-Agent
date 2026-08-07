from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, NoReturn, cast

import httpx
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session

from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain.audit import commit_with_audit
from app.domain.models import (
    AuditEvent,
    CloudAtlasSourceCreate,
    CloudAtlasSourcePublic,
    CloudAtlasSourceUpdate,
    Project,
    SourceInstance,
)

SERVICE_ID = "cloudatlas-read"
METHOD = "cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets"
FINGERPRINT_SCHEMA = "exposure-agent.cloudatlas-source-fingerprint.v1"
PACKAGE_SHA256 = "1d487b2773d0dc2457d5c552d5a5d9cd34b4e7c732f9a810cf0115cdab3f069c"
DESCRIPTOR_SHA256 = "3fada7cb00f3bca132c28d316ea61158522a1a07d3e80a83f9e68010d1a588e0"
MATERIAL_CHANGED_ERROR = "cloudatlas_material_changed"

_SAFE_ERROR_STATUS = {
    "octobus_authentication_failed": 401,
    "cloudatlas_authentication_failed": 401,
    "cloudatlas_authorization_failed": 403,
    "cloudatlas_connectivity_failed": 503,
    "cloudatlas_upstream_failed": 503,
    "cloudatlas_response_contract_failed": 500,
}


class CloudAtlasBoundaryError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = _SAFE_ERROR_STATUS[code]


class CloudAtlasMaterialMismatchError(CloudAtlasBoundaryError):
    """Current control-plane material proves the stored validation is stale."""


class CloudAtlasStateError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ActiveSourceConflictError(Exception):
    pass


def _boundary_error(code: str) -> NoReturn:
    raise CloudAtlasBoundaryError(code)


def _material_error(code: str) -> NoReturn:
    raise CloudAtlasMaterialMismatchError(code)


def _required_string(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        _boundary_error("cloudatlas_response_contract_failed")
    return value


def _required_bool(payload: dict[str, Any], name: str) -> bool:
    value = payload.get(name)
    if not isinstance(value, bool):
        _boundary_error("cloudatlas_response_contract_failed")
    return value


def _required_list(payload: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = payload.get(name)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        _boundary_error("cloudatlas_response_contract_failed")
    return cast(list[dict[str, Any]], value)


def _require_sha256(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        _boundary_error("cloudatlas_response_contract_failed")
    return value


def _canonical_fingerprint(material: dict[str, Any]) -> str:
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CloudAtlasFingerprint:
    value: str


class OctobusCloudAtlasClient:
    def __init__(self) -> None:
        self.base_url = settings.OCTOBUS_URL.rstrip("/")

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, Any] | None = None,
        missing_is_material_change: bool = False,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"} if token is not None else None
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=settings.OCTOBUS_TIMEOUT_SECONDS,
            ) as client:
                response = client.request(method, path, headers=headers, json=body)
        except httpx.HTTPError:
            _boundary_error("cloudatlas_connectivity_failed")

        if response.status_code != 200:
            if response.status_code == 404 and missing_is_material_change:
                _material_error("cloudatlas_response_contract_failed")
            try:
                error_payload = response.json()
            except ValueError:
                error_payload = {}
            safe_message = (
                error_payload.get("message")
                if isinstance(error_payload, dict)
                else None
            )
            if response.status_code == 401:
                if safe_message == "cloudatlas_authentication_failed":
                    _boundary_error("cloudatlas_authentication_failed")
                _boundary_error("octobus_authentication_failed")
            if response.status_code == 403:
                _boundary_error("cloudatlas_authorization_failed")
            if response.status_code >= 500:
                if safe_message in _SAFE_ERROR_STATUS:
                    _boundary_error(cast(str, safe_message))
                _boundary_error("cloudatlas_upstream_failed")
            _boundary_error("cloudatlas_response_contract_failed")
        try:
            payload = response.json()
        except ValueError:
            _boundary_error("cloudatlas_response_contract_failed")
        if not isinstance(payload, dict):
            _boundary_error("cloudatlas_response_contract_failed")
        return cast(dict[str, Any], payload)

    def _request_material(self, path: str) -> dict[str, Any]:
        return self._request_json(
            "GET", path, missing_is_material_change=True
        )

    def current_fingerprint(self, source: SourceInstance) -> CloudAtlasFingerprint:
        admin = "/admin/v1"
        service = self._request_material(f"{admin}/services/{SERVICE_ID}")
        instance = self._request_material(
            f"{admin}/instances/{source.instance_id}"
        )
        capset = self._request_material(f"{admin}/capsets/{source.capset_id}")
        instances_payload = self._request_material(
            f"{admin}/capsets/{source.capset_id}/instances"
        )
        methods_payload = self._request_material(
            f"{admin}/capsets/{source.capset_id}/methods"
        )
        tokens_payload = self._request_material(
            f"{admin}/capsets/{source.capset_id}/tokens"
        )

        service_id = _required_string(service, "ID")
        package_sha256 = _require_sha256(
            _required_string(service, "PackageSHA256")
        )
        package_version = service.get("PackageVersion")
        descriptor_sha256 = _require_sha256(
            _required_string(service, "DescriptorSHA256")
        )
        if (
            service_id != SERVICE_ID
            or package_sha256 != PACKAGE_SHA256
            or descriptor_sha256 != DESCRIPTOR_SHA256
            or not isinstance(package_version, str)
        ):
            _material_error("cloudatlas_response_contract_failed")

        instance_id = _required_string(instance, "ID")
        instance_service_id = _required_string(instance, "ServiceID")
        if instance_id != source.instance_id or instance_service_id != SERVICE_ID:
            _material_error("cloudatlas_response_contract_failed")

        capset_id = _required_string(capset, "ID")
        capset_enabled = _required_bool(capset, "Enabled")
        if capset_id != source.capset_id or not capset_enabled:
            _material_error("cloudatlas_authorization_failed")

        instance_bindings = [
            {
                "service_id": _required_string(item, "ServiceID"),
                "instance_id": _required_string(item, "InstanceID"),
                "enabled": _required_bool(item, "Enabled"),
                "include_all_methods": _required_bool(item, "IncludeAllMethods"),
            }
            for item in _required_list(instances_payload, "instances")
        ]
        expected_binding = {
            "service_id": SERVICE_ID,
            "instance_id": source.instance_id,
            "enabled": True,
            "include_all_methods": False,
        }
        if instance_bindings != [expected_binding]:
            _material_error("cloudatlas_authorization_failed")

        method_bindings = []
        for item in _required_list(methods_payload, "methods"):
            method_name = _required_string(item, "MethodFullName").lstrip("/")
            method_bindings.append(
                {"name": method_name, "enabled": _required_bool(item, "Enabled")}
            )
        expected_method = {"name": METHOD, "enabled": True}
        if method_bindings != [expected_method]:
            _material_error("cloudatlas_authorization_failed")

        token_bindings: list[dict[str, str]] = sorted(
            [
                {
                    "id": _required_string(item, "ID"),
                    "token_hash": _require_sha256(
                        _required_string(item, "TokenHash")
                    ),
                }
                for item in _required_list(tokens_payload, "tokens")
            ],
            key=lambda item: item["id"],
        )
        if not token_bindings:
            _material_error("cloudatlas_authorization_failed")

        material = {
            "schema": FINGERPRINT_SCHEMA,
            "service": {
                "id": service_id,
                "package_sha256": package_sha256,
                "package_version": package_version,
                "descriptor_sha256": descriptor_sha256,
            },
            "instance": {
                "id": instance_id,
                "service_id": instance_service_id,
                "config_sha256": _require_sha256(
                    _required_string(instance, "ConfigSHA256")
                ),
                "secret_sha256": _require_sha256(
                    _required_string(instance, "SecretSHA256")
                ),
            },
            "capset": {
                "id": capset_id,
                "enabled": capset_enabled,
                "token_bindings": token_bindings,
                "instances": instance_bindings,
                "methods": method_bindings,
            },
            "selected_method": METHOD,
        }
        return CloudAtlasFingerprint(_canonical_fingerprint(material))

    def list_ip_assets_page(
        self,
        source: SourceInstance,
        *,
        capset_token: str,
        page: int,
        size: int,
    ) -> dict[str, Any]:
        payload = self._request_json(
            "POST",
            (
                f"/capsets/{source.capset_id}/connect/{source.instance_id}/"
                f"{METHOD}"
            ),
            token=capset_token,
            body={"status": "valid", "page": page, "size": size},
        )
        items = payload.get("items")
        returned_page = payload.get("page")
        returned_size = payload.get("size")
        total = payload.get("total")
        if (
            not isinstance(items, list)
            or not all(
                isinstance(item, dict)
                and set(item) == {"id", "ip", "status"}
                and isinstance(item.get("id"), str)
                and isinstance(item.get("ip"), str)
                and isinstance(item.get("status"), str)
                for item in items
            )
            or not isinstance(returned_page, int)
            or isinstance(returned_page, bool)
            or returned_page != page
            or not isinstance(returned_size, int)
            or isinstance(returned_size, bool)
            or returned_size != size
            or not isinstance(total, int)
            or isinstance(total, bool)
            or total < 0
        ):
            _boundary_error("cloudatlas_response_contract_failed")
        return payload

    def validate_read(
        self, source: SourceInstance, *, capset_token: str
    ) -> CloudAtlasFingerprint:
        before = self.current_fingerprint(source)
        self.list_ip_assets_page(
            source,
            capset_token=capset_token,
            page=1,
            size=1,
        )
        after = self.current_fingerprint(source)
        if before != after:
            _boundary_error("cloudatlas_response_contract_failed")
        return after


def _audit_snapshot(source: SourceInstance, *, status: str) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "source_type": source.source_type,
        "instance_id": source.instance_id,
        "capset_id": source.capset_id,
        "enabled": source.enabled,
        "validation_status": status,
        "fingerprint_summary": (
            source.validated_fingerprint[:12]
            if source.validated_fingerprint is not None
            else None
        ),
    }
    if status == "failed" and source.validation_error_code is not None:
        snapshot["result_code"] = source.validation_error_code
    return snapshot


def _audit_event(
    *,
    source: SourceInstance,
    actor_subject: str,
    action: str,
    before_data: dict[str, Any] | None,
    after_status: str,
    ip_address: str | None,
    actor_type: str = "user",
) -> AuditEvent:
    return AuditEvent(
        tenant_id=source.tenant_id,
        project_id=source.project_id,
        actor_subject=actor_subject,
        actor_type=actor_type,
        action=action,
        target_type="source_instance",
        target_id=source.id,
        before_data=before_data,
        after_data=_audit_snapshot(source, status=after_status),
        ip_address=ip_address,
    )


def _stored_validation_status(source: SourceInstance) -> str:
    if source.validation_error_code == MATERIAL_CHANGED_ERROR:
        return "invalid"
    if source.validated_fingerprint is not None:
        return "validated"
    return "failed" if source.validation_error_code else "not_validated"


def _invalidate_material_validation(
    *, session: Session, source: SourceInstance
) -> SourceInstance:
    if source.validation_error_code == MATERIAL_CHANGED_ERROR:
        return source
    before = _audit_snapshot(source, status=_stored_validation_status(source))
    source.validation_error_code = MATERIAL_CHANGED_ERROR
    source.updated_at = get_datetime_utc()
    event = _audit_event(
        source=source,
        actor_subject="octobus-control-plane",
        actor_type="system",
        action="source_instance.validation_invalidated",
        before_data=before,
        after_status="invalid",
        ip_address=None,
    )
    return commit_with_audit(session=session, record=source, audit_event=event)


def source_public(
    source: SourceInstance,
    *,
    check_current: bool = True,
    session: Session | None = None,
) -> CloudAtlasSourcePublic:
    status = _stored_validation_status(source)
    if status == "validated" and check_current:
        try:
            current = OctobusCloudAtlasClient().current_fingerprint(source)
        except CloudAtlasMaterialMismatchError:
            status = "invalid"
        except CloudAtlasBoundaryError:
            status = "unavailable"
        else:
            status = (
                "validated"
                if current.value == source.validated_fingerprint
                else "invalid"
            )
        if status == "invalid":
            if session is None:
                raise RuntimeError("session is required to persist validation drift")
            source = _invalidate_material_validation(session=session, source=source)
    return CloudAtlasSourcePublic(
        id=source.id,
        source_type=source.source_type,
        instance_id=source.instance_id,
        capset_id=source.capset_id,
        enabled=source.enabled,
        validation_status=status,
        fingerprint_summary=(
            source.validated_fingerprint[:12]
            if source.validated_fingerprint is not None
            else None
        ),
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def create_source(
    *,
    session: Session,
    project: Project,
    source_in: CloudAtlasSourceCreate,
    actor_subject: str,
    ip_address: str | None,
) -> SourceInstance:
    source = SourceInstance(
        tenant_id=project.tenant_id,
        project_id=project.id,
        instance_id=source_in.instance_id,
        capset_id=source_in.capset_id,
    )
    event = _audit_event(
        source=source,
        actor_subject=actor_subject,
        action="source_instance.created",
        before_data=None,
        after_status="not_validated",
        ip_address=ip_address,
    )
    try:
        return commit_with_audit(session=session, record=source, audit_event=event)
    except IntegrityError:
        session.rollback()
        raise ActiveSourceConflictError


def update_source(
    *,
    session: Session,
    source: SourceInstance,
    source_in: CloudAtlasSourceUpdate,
    actor_subject: str,
    ip_address: str | None,
) -> SourceInstance:
    if (
        source.instance_id == source_in.instance_id
        and source.capset_id == source_in.capset_id
    ):
        return source
    before = _audit_snapshot(source, status=_stored_validation_status(source))
    source.instance_id = source_in.instance_id
    source.capset_id = source_in.capset_id
    source.enabled = False
    source.validated_fingerprint = None
    source.validated_at = None
    source.validation_error_code = None
    source.updated_at = get_datetime_utc()
    event = _audit_event(
        source=source,
        actor_subject=actor_subject,
        action="source_instance.configured",
        before_data=before,
        after_status="not_validated",
        ip_address=ip_address,
    )
    return commit_with_audit(session=session, record=source, audit_event=event)


def validate_source(
    *,
    session: Session,
    source: SourceInstance,
    capset_token: str,
    actor_subject: str,
    ip_address: str | None,
) -> SourceInstance:
    before = _audit_snapshot(source, status=_stored_validation_status(source))
    try:
        fingerprint = OctobusCloudAtlasClient().validate_read(
            source, capset_token=capset_token
        )
    except CloudAtlasBoundaryError as error:
        source.validated_fingerprint = None
        source.validated_at = None
        source.validation_error_code = error.code
        source.updated_at = get_datetime_utc()
        event = _audit_event(
            source=source,
            actor_subject=actor_subject,
            action="source_instance.validation_failed",
            before_data=before,
            after_status="failed",
            ip_address=ip_address,
        )
        commit_with_audit(session=session, record=source, audit_event=event)
        raise

    changed_at = get_datetime_utc()
    source.validated_fingerprint = fingerprint.value
    source.validated_at = changed_at
    source.validation_error_code = None
    source.updated_at = changed_at
    event = _audit_event(
        source=source,
        actor_subject=actor_subject,
        action="source_instance.validated",
        before_data=before,
        after_status="validated",
        ip_address=ip_address,
    )
    return commit_with_audit(session=session, record=source, audit_event=event)


def set_source_enabled(
    *,
    session: Session,
    source: SourceInstance,
    enabled: bool,
    actor_subject: str,
    ip_address: str | None,
) -> SourceInstance:
    if enabled:
        if (
            source.validated_fingerprint is None
            or source.validation_error_code == MATERIAL_CHANGED_ERROR
        ):
            raise CloudAtlasStateError("cloudatlas_validation_required")
        try:
            current = OctobusCloudAtlasClient().current_fingerprint(source)
        except CloudAtlasMaterialMismatchError:
            _invalidate_material_validation(session=session, source=source)
            raise CloudAtlasStateError("cloudatlas_validation_required")
        if current.value != source.validated_fingerprint:
            _invalidate_material_validation(session=session, source=source)
            raise CloudAtlasStateError("cloudatlas_validation_required")
    before = _audit_snapshot(source, status=_stored_validation_status(source))
    source.enabled = enabled
    source.updated_at = get_datetime_utc()
    event = _audit_event(
        source=source,
        actor_subject=actor_subject,
        action=f"source_instance.{'enabled' if enabled else 'disabled'}",
        before_data=before,
        after_status=_stored_validation_status(source),
        ip_address=ip_address,
    )
    try:
        return commit_with_audit(session=session, record=source, audit_event=event)
    except IntegrityError:
        session.rollback()
        raise ActiveSourceConflictError
    except SQLAlchemyError:
        session.rollback()
        raise
