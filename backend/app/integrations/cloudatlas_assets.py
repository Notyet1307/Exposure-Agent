from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
from typing import Any, NoReturn
from urllib.parse import urlsplit

from app.domain import cloudatlas_assets_contract as contract
from app.domain.cloudatlas_sources import (
    CloudAtlasBoundaryError,
    CloudAtlasFingerprint,
    CloudAtlasMaterialMismatchError,
    OctobusCloudAtlasClient,
)
from app.domain.models import SourceInstance

_ID = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_SPACE = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_COMMON: dict[str, Any] = {
    "id": "identity",
    "ip": "string",
    "status": "string",
    "bu": {"id": "identity", "name": "string"},
    "tags": [{"pk": "identity", "name": "string"}],
    "created_at": "string",
    "updated_at": "string",
    "lastseen_at": "string",
}
# E10 declared types, with the E12 object-shaped IP bu override.
_FIELDS = {
    "ip": {
        **_COMMON,
        "version": "integer",
        "subnet": "nullable_string",
        "live_port": "integer",
        "provider": "string",
        "as_name": "string",
        "as_num": "string",
        "location": "string",
        "country": "string",
        "province": "string",
        "city": "string",
        "sources": [
            {
                "source": "string",
                "reason": "string",
                "factor": "string",
                "lastseen_at": "string",
            }
        ],
    },
    "port": {
        **_COMMON,
        "port": "integer",
        "protocol": "string",
        "service": "string",
        "tunnel": "string",
        "product": "string",
        "version": "string",
        "banner": "nullable_string",
        "categories": ["string"],
    },
    "root_domain": {
        "id": "identity",
        "root_domain": "string",
        "status": "string",
        "icp_date": "nullable_string",
        "icp_num": "nullable_string",
        "icp_official_name": "nullable_string",
        "whois_registrant": "nullable_string",
        "whois_email": "nullable_string",
        "whois_expiration_time": "nullable_string",
        "valid_subdomain": "integer",
        "sources": [{"source": "string", "reason": "string", "factor": "string"}],
        "created_at": "string",
        "updated_at": "string",
        "lastseen_at": "string",
    },
}


def _fail() -> NoReturn:
    raise CloudAtlasBoundaryError("cloudatlas_response_contract_failed")


def _project(value: Any, schema: Any, *, required: bool = False) -> Any:
    if schema == "identity":
        if not isinstance(value, str) or not _ID.fullmatch(value):
            _fail()
        return value
    if schema == "integer":
        if type(value) is not int or abs(value) > 9007199254740991:
            _fail()
        return value
    if schema == "nullable_string" and value is None:
        return None
    if isinstance(schema, str):
        if not isinstance(value, str):
            _fail()
        return value
    if isinstance(schema, list):
        if not isinstance(value, list):
            _fail()
        return [_project(item, schema[0], required=required) for item in value]
    if not isinstance(value, dict):
        _fail()
    if required and not schema.keys() <= value.keys():
        _fail()
    return {
        key: _project(value[key], field_type, required=required)
        for key, field_type in schema.items()
        if key in value
    }


def normalize_items(items: Any, domain: str) -> list[dict[str, Any]]:
    """Validate normalized decimal identities and whitelist only the frozen fields."""
    if domain not in _FIELDS or not isinstance(items, list):
        _fail()
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        identity_field = "root_domain" if domain == "root_domain" else "ip"
        if not isinstance(item, dict) or "id" not in item or identity_field not in item:
            _fail()
        row = _project(item, _FIELDS[domain], required=domain == "root_domain")
        if row["id"] in seen:
            _fail()
        seen.add(row["id"])
        if domain == "root_domain":
            if (
                len(row["id"]) > 100
                or not row["root_domain"].strip()
                or not row["status"].strip()
            ):
                _fail()
            result.append(row)
            continue
        try:
            ipaddress.ip_address(row["ip"])
        except ValueError:
            _fail()
        if "%" in row["ip"]:
            _fail()
        if domain == "ip" and row.get("status") != "valid":
            _fail()
        if domain == "port" and ("port" not in row or not 0 <= row["port"] <= 65535):
            _fail()
        if "bu" in row and "id" not in row["bu"]:
            _fail()
        if "tags" in row and any("pk" not in tag for tag in row["tags"]):
            _fail()
        result.append(row)
    return result


class OctobusCloudAtlasAssetsClient(OctobusCloudAtlasClient):
    SERVICE_ID = contract.SERVICE_ID
    PACKAGE_SHA256 = contract.PACKAGE_SHA256
    DESCRIPTOR_SHA256 = contract.DESCRIPTOR_SHA256
    METHODS = tuple(contract.METHODS.values())
    FINGERPRINT_SCHEMA = contract.FINGERPRINT_SCHEMA
    CAPABILITY_PROFILE = contract.CAPABILITY_PROFILE
    SOURCE_TYPE = "cloudatlas"
    DOMAIN_METHODS = contract.METHODS

    def current_fingerprint(self, source: SourceInstance) -> CloudAtlasFingerprint:
        if (
            source.capability_profile != self.CAPABILITY_PROFILE
            or source.source_type != self.SOURCE_TYPE
            or not isinstance(source.space_id, str)
            or not _SPACE.fullmatch(source.space_id)
        ):
            raise CloudAtlasMaterialMismatchError("cloudatlas_response_contract_failed")
        before = self._request_material(f"/admin/v1/instances/{source.instance_id}")
        fingerprint = super().current_fingerprint(source)
        after = self._request_material(f"/admin/v1/instances/{source.instance_id}")
        for instance in (before, after):
            config = instance.get("ConfigJSON")
            if (
                instance.get("Enabled") is not True
                or instance.get("HasSecret") is not True
                or not isinstance(config, dict)
                or config.get("spaceId") != source.space_id
                or not isinstance(config.get("baseUrl"), str)
            ):
                raise CloudAtlasMaterialMismatchError("cloudatlas_authorization_failed")
            try:
                base = urlsplit(config["baseUrl"])
                valid_origin = (
                    base.scheme == "https"
                    and bool(base.hostname)
                    and base.port != 0
                    and not base.username
                    and not base.password
                    and not base.query
                    and not base.fragment
                    and base.path in ("", "/", "/openapi", "/openapi/")
                )
            except ValueError:
                valid_origin = False
            if not valid_origin:
                raise CloudAtlasMaterialMismatchError(
                    "cloudatlas_response_contract_failed"
                )
        if any(
            before.get(key) != after.get(key)
            for key in ("ConfigSHA256", "SecretSHA256", "ConfigJSON", "Enabled")
        ):
            raise CloudAtlasMaterialMismatchError("cloudatlas_response_contract_failed")
        return fingerprint

    def validate_credentials(
        self, source: SourceInstance, *, capset_token: str
    ) -> CloudAtlasFingerprint:
        if not isinstance(capset_token, str) or not capset_token.strip():
            raise CloudAtlasBoundaryError("octobus_authentication_failed")
        before = self.current_fingerprint(source)
        payload = self._request_material(f"/admin/v1/capsets/{source.capset_id}/tokens")
        tokens = payload.get("tokens")
        # OctoBus v0.1.0 domain.CapsetTokenHash hashes the raw UTF-8 token with SHA-256.
        digest = hashlib.sha256(capset_token.encode()).hexdigest()
        if not isinstance(tokens, list) or not any(
            isinstance(token, dict)
            and isinstance(token.get("TokenHash"), str)
            and re.fullmatch(r"[0-9a-f]{64}", token["TokenHash"]) is not None
            and hmac.compare_digest(token["TokenHash"], digest)
            for token in tokens
        ):
            raise CloudAtlasBoundaryError("octobus_authentication_failed")
        if self.current_fingerprint(source) != before:
            raise CloudAtlasMaterialMismatchError("cloudatlas_response_contract_failed")
        return before

    def list_page(
        self,
        source: SourceInstance,
        *,
        capset_token: str,
        domain: str,
        page: int,
        size: int,
        max_response_bytes: int,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        if (
            domain not in self.DOMAIN_METHODS
            or type(page) is not int
            or not 1 <= page <= 2147483647
            or type(size) is not int
            or not 1 <= size <= 200
            or type(max_response_bytes) is not int
            or not 1 <= max_response_bytes <= 16777216
            or type(timeout_seconds) is not int
            or not 1 <= timeout_seconds <= 300
        ):
            _fail()
        if not source.enabled or not source.data_access_enabled:
            raise CloudAtlasBoundaryError("cloudatlas_authorization_failed")
        before = self.validate_credentials(source, capset_token=capset_token)
        # Deliberately does not call the legacy client's retrying IP-only method.
        payload = self._request_json(
            "POST",
            f"/capsets/{source.capset_id}/connect/{source.instance_id}/{self.DOMAIN_METHODS[domain]}",
            token=capset_token,
            body={
                "page": page,
                "size": size,
                "maxResponseBytes": max_response_bytes,
                "timeoutSeconds": timeout_seconds,
            },
        )
        if self.validate_credentials(source, capset_token=capset_token) != before:
            raise CloudAtlasMaterialMismatchError("cloudatlas_response_contract_failed")
        # Proto3 JSON omits zero; the pinned package already requires upstream total.
        total = payload.get("total", 0)
        text = payload.get("itemsJson")
        if (
            type(payload.get("page")) is not int
            or payload["page"] != page
            or type(payload.get("size")) is not int
            or payload["size"] != size
            or type(total) is not int
            or not 0 <= total <= 2147483647
            or payload.get("spaceId") != source.space_id
            or not isinstance(text, str)
            or len(text.encode()) > max_response_bytes * 4 + 1024
        ):
            _fail()
        try:
            decoded = json.loads(text)
        except ValueError, RecursionError:
            _fail()
        items = normalize_items(decoded, domain)
        if len(items) > size or len(items) > total:
            _fail()
        return {
            "page": page,
            "size": size,
            "total": total,
            "space_id": source.space_id,
            "items": items,
        }
