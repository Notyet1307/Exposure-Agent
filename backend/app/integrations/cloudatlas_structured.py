"""Fourteen fixed single-method capabilities sharing one immutable package."""

import json
import re
from typing import Any

from app.domain import cloudatlas_structured_contract as contract
from app.domain.cloudatlas_sources import CloudAtlasBoundaryError
from app.domain.models import SourceInstance
from app.integrations.cloudatlas_assets import OctobusCloudAtlasAssetsClient


class OctobusCloudAtlasStructuredClient(OctobusCloudAtlasAssetsClient):
    SERVICE_ID = contract.SERVICE_ID
    PACKAGE_SHA256 = contract.PACKAGE_SHA256
    DESCRIPTOR_SHA256 = contract.DESCRIPTOR_SHA256
    FINGERPRINT_SCHEMA = contract.FINGERPRINT_SCHEMA

    def __init__(self, profile: str) -> None:
        if profile not in contract.PROFILES:
            raise CloudAtlasBoundaryError("cloudatlas_response_contract_failed")
        domain = contract.PROFILES[profile]
        definition = contract.DOMAINS[domain]
        self.CAPABILITY_PROFILE = profile
        self.SOURCE_TYPE = definition["source_type"]
        self.DOMAIN_METHODS = {domain: definition["method"]}
        self.METHODS = (definition["method"],)
        super().__init__()

    def diagnose_page(
        self, source: SourceInstance, *, capset_token: str
    ) -> dict[str, Any]:
        """One fixed, non-publishing shape probe; returns no source record values."""
        if not source.enabled or not source.data_access_enabled:
            raise CloudAtlasBoundaryError("cloudatlas_authorization_failed")
        before = self.validate_credentials(source, capset_token=capset_token)
        domain = contract.PROFILES[self.CAPABILITY_PROFILE]
        payload = self._request_json(
            "POST",
            f"/capsets/{source.capset_id}/connect/{source.instance_id}/{self.DOMAIN_METHODS[domain]}",
            token=capset_token,
            body={
                "page": 1,
                "size": 20,
                "maxResponseBytes": 4194304,
                "timeoutSeconds": 120,
                "diagnosticsOnly": True,
            },
        )
        if self.validate_credentials(source, capset_token=capset_token) != before:
            raise CloudAtlasBoundaryError("cloudatlas_response_contract_failed")
        try:
            total = payload.get("total", 0)
            if (
                type(payload.get("page")) is not int
                or type(payload.get("size")) is not int
                or payload.get("page") != 1
                or payload.get("size") != 20
                or payload.get("spaceId") != source.space_id
                or type(total) is not int
                or not 0 <= total <= 2147483647
                or payload.get("itemsJson") != "[]"
            ):
                raise ValueError
            stats = json.loads(payload["diagnosticsJson"])
            if set(stats) != {
                "itemCount",
                "fields",
                "unknownFieldCount",
                "responseSha256",
            }:
                raise ValueError
            for key in ("itemCount", "unknownFieldCount"):
                if type(stats[key]) is not int or not 0 <= stats[key] <= 4194304:
                    raise ValueError
            if stats["itemCount"] > min(20, total) or not re.fullmatch(
                r"[0-9a-f]{64}", stats["responseSha256"]
            ):
                raise ValueError
            paths: set[str] = set()

            def register(schema: dict[str, Any], path: str) -> None:
                paths.add(path)
                for key, child in schema.get("properties", {}).items():
                    register(child, path + "." + key)
                if "items" in schema:
                    register(schema["items"], path + "[]")

            register(contract.DOMAINS[domain]["schema"], "$")
            if "bu" in contract.DOMAINS[domain]["schema"]["properties"]:
                paths.update({"$.bu.id", "$.bu.name"})
            if (
                not isinstance(stats["fields"], dict)
                or not stats["fields"].keys() <= paths
            ):
                raise ValueError
            for counter in stats["fields"].values():
                if set(counter) != {"present", "missing", "types", "invalidEnum"}:
                    raise ValueError
                if not isinstance(counter["types"], dict) or not counter[
                    "types"
                ].keys() <= {
                    "integer",
                    "number",
                    "string",
                    "boolean",
                    "object",
                    "array",
                    "null",
                }:
                    raise ValueError
                if any(
                    type(value) is not int or not 0 <= value <= 4194304
                    for value in [
                        counter["present"],
                        counter["missing"],
                        counter["invalidEnum"],
                        *counter["types"].values(),
                    ]
                ):
                    raise ValueError
        except KeyError, TypeError, ValueError:
            raise CloudAtlasBoundaryError(
                "cloudatlas_response_contract_failed"
            ) from None
        return {
            "domain": domain,
            "page": 1,
            "size": 20,
            "total": total,
            "fingerprint": before.value,
            **stats,
        }
