"""Frozen #281 fields and single-method profiles; not a user-defined rules API."""

from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path
from typing import Any, Literal

StructuredDomain = Literal[
    "subdomain",
    "cert",
    "openport",
    "web",
    "dir",
    "appfinger",
    "crawler",
    "seed_enterprise",
    "seed_keyword",
    "seed_domain",
    "seed_email",
    "seed_cert",
    "seed_icon",
    "seed_title",
]
StructuredProfile = Literal[
    "subdomain-v1",
    "cert-v1",
    "openport-v1",
    "web-v1",
    "dir-v1",
    "appfinger-v1",
    "crawler-v1",
    "seed-enterprise-v1",
    "seed-keyword-v1",
    "seed-domain-v1",
    "seed-email-v1",
    "seed-cert-v1",
    "seed-icon-v1",
    "seed-title-v1",
]
SERVICE_ID = "cloudatlas-structured"
PACKAGE_SHA256 = "f77dfb022970efae0b18b35b970d7a9470f845028d343b44f55ffae9d57291c7"
DESCRIPTOR_SHA256 = "8fc1ace9c01e4b2c4d48a8f49ec0affc269714a1d5d0c52c6a1f8aca37409a6a"
FINGERPRINT_SCHEMA = "exposure-agent.cloudatlas-structured-fingerprint.v1"
SCHEMA_PATH = Path(__file__).with_name("cloudatlas_structured.schema.json")
DOMAINS: dict[str, Any] = json.loads(SCHEMA_PATH.read_text())["domains"]
PROFILES = {value["profile"]: domain for domain, value in DOMAINS.items()}
SOURCE_TYPES = {value["source_type"] for value in DOMAINS.values()}
SEARCH_FIELDS = tuple(
    sorted(
        {
            field
            for value in DOMAINS.values()
            for field in [
                *value["text_fields"],
                *value["exact_fields"],
                "confidence",
                "type",
            ]
        }
    )
)
_ID = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")


def _project(value: Any, schema: dict[str, Any]) -> Any:
    if value is None and schema.get("nullable"):
        return None
    kind = schema["type"]
    if kind == "identity":
        if not isinstance(value, str) or len(value) > 100 or not _ID.fullmatch(value):
            raise ValueError("invalid structured identity")
        return value
    if kind == "integer":
        if type(value) is not int or abs(value) > 9007199254740991:
            raise ValueError("invalid structured integer")
        return value
    if kind == "boolean":
        if type(value) is not bool:
            raise ValueError("invalid structured boolean")
        return value
    if kind == "string":
        if not isinstance(value, str) or (
            "enum" in schema and value not in schema["enum"]
        ):
            raise ValueError("invalid structured string")
        value.encode("utf-8")
        return value
    if kind == "array":
        if not isinstance(value, list):
            raise ValueError("invalid structured array")
        return [_project(item, schema["items"]) for item in value]
    if kind != "object" or not isinstance(value, dict):
        raise ValueError("invalid structured object")
    if not set(schema["required"]) <= value.keys():
        raise ValueError("missing structured field")
    return {
        key: _project(value[key], child)
        for key, child in schema["properties"].items()
        if key in value
    }


def normalize_items(items: Any, domain: str) -> list[dict[str, Any]]:
    """Validate the already projected RPC payload; never accept arbitrary fields."""
    if domain not in DOMAINS or not isinstance(items, list):
        raise ValueError("invalid structured domain")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        row = _project(item, DOMAINS[domain]["schema"])
        if row["id"] in seen:
            raise ValueError("duplicate structured identity")
        seen.add(row["id"])
        if domain == "openport":
            if "%" in row["ip"] or not 0 <= row["port"] <= 65535:
                raise ValueError("invalid open port")
            ipaddress.ip_address(row["ip"])
        result.append(row)
    return result
