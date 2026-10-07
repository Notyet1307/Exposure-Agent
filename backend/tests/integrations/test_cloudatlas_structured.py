"""Fixed capabilities and sanitized diagnostics without real upstream traffic."""

import copy
import importlib.util
import json
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

from app.domain import cloudatlas_structured_contract as contract
from app.domain.cloudatlas_sources import CloudAtlasBoundaryError
from app.domain.models import SourceInstance
from app.integrations.cloudatlas_structured import OctobusCloudAtlasStructuredClient
from tests.api.routes.test_external_structured_assets import sample
from tests.integrations.test_cloudatlas_assets import _metadata


@pytest.mark.parametrize("domain", contract.DOMAINS)
def test_profile_has_its_own_method_token_and_strict_normalized_page(
    domain: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition = contract.DOMAINS[domain]
    client = OctobusCloudAtlasStructuredClient(definition["profile"])
    source = SourceInstance(
        project_id=uuid.uuid4(),
        source_type=definition["source_type"],
        capability_profile=definition["profile"],
        instance_id="structured-fixture",
        capset_id="structured-only",
        space_id="7",
        enabled=True,
    )
    capability = SimpleNamespace(
        SERVICE_ID=client.SERVICE_ID,
        PACKAGE_SHA256=client.PACKAGE_SHA256,
        DESCRIPTOR_SHA256=client.DESCRIPTOR_SHA256,
        METHODS=client.DOMAIN_METHODS,
    )
    metadata = _metadata(source, capability=cast(ModuleType, capability))
    methods: list[str] = []
    row = sample(definition["schema"])
    envelope = {
        "page": 1,
        "size": 20,
        "total": 1,
        "spaceId": "7",
        "itemsJson": json.dumps([row]),
        "omittedFieldCount": 3,
    }

    def request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        methods.append(method)
        if method == "GET":
            return copy.deepcopy(metadata[path])
        assert path.endswith("/" + definition["method"])
        assert kwargs["token"] == "synthetic-capset-token"
        assert kwargs["body"] == {
            "page": 1,
            "size": 20,
            "maxResponseBytes": 4096,
            "timeoutSeconds": 60,
        }
        return envelope

    monkeypatch.setattr(client, "_request_json", request)
    client.validate_credentials(source, capset_token="synthetic-capset-token")
    assert set(methods) == {"GET"}
    result = client.list_page(
        source,
        capset_token="synthetic-capset-token",
        domain=domain,
        page=1,
        size=20,
        max_response_bytes=4096,
        timeout_seconds=60,
    )
    assert result["items"] == [row] and result["omitted_field_count"] == 3
    with pytest.raises(CloudAtlasBoundaryError):
        client.validate_credentials(source, capset_token="other-profile-token")
    metadata[f"/admin/v1/capsets/{source.capset_id}/methods"]["methods"].append(
        {"MethodFullName": "unapproved/Other", "Enabled": True}
    )
    with pytest.raises(CloudAtlasBoundaryError):
        client.current_fingerprint(source)
    with pytest.raises(CloudAtlasBoundaryError):
        client.list_page(
            source,
            capset_token="synthetic-capset-token",
            domain="ip",
            page=1,
            size=20,
            max_response_bytes=4096,
            timeout_seconds=60,
        )


def test_shape_probe_rejects_raw_records_and_unapproved_diagnostic_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    domain = "web"
    definition = contract.DOMAINS[domain]
    client = OctobusCloudAtlasStructuredClient(definition["profile"])
    source = SourceInstance(
        project_id=uuid.uuid4(),
        source_type=definition["source_type"],
        capability_profile=definition["profile"],
        instance_id="structured-fixture",
        capset_id="structured-only",
        space_id="7",
        enabled=True,
    )
    capability = SimpleNamespace(
        SERVICE_ID=client.SERVICE_ID,
        PACKAGE_SHA256=client.PACKAGE_SHA256,
        DESCRIPTOR_SHA256=client.DESCRIPTOR_SHA256,
        METHODS=client.DOMAIN_METHODS,
    )
    metadata = _metadata(source, capability=cast(ModuleType, capability))
    stats: dict[str, Any] = {
        "itemCount": 1,
        "fields": {
            "$.id": {
                "present": 1,
                "missing": 0,
                "types": {"integer": 1},
                "invalidEnum": 0,
            }
        },
        "unknownFieldCount": 2,
        "responseSha256": "b" * 64,
    }
    envelope = {
        "page": 1,
        "size": 20,
        "total": 1,
        "spaceId": "7",
        "itemsJson": "[]",
        "diagnosticsJson": json.dumps(stats),
    }

    def request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if method == "GET":
            return copy.deepcopy(metadata[path])
        assert kwargs["body"] == {
            "page": 1,
            "size": 20,
            "maxResponseBytes": 4194304,
            "timeoutSeconds": 120,
            "diagnosticsOnly": True,
        }
        return envelope

    monkeypatch.setattr(client, "_request_json", request)
    assert (
        client.diagnose_page(source, capset_token="synthetic-capset-token")["itemCount"]
        == 1
    )
    envelope["itemsJson"] = '[{"private":"value"}]'
    with pytest.raises(CloudAtlasBoundaryError):
        client.diagnose_page(source, capset_token="synthetic-capset-token")
    envelope["itemsJson"] = "[]"
    envelope["diagnosticsJson"] = json.dumps(
        stats | {"fields": {"$.unapproved_private_key": stats["fields"]["$.id"]}}
    )
    with pytest.raises(CloudAtlasBoundaryError):
        client.diagnose_page(source, capset_token="synthetic-capset-token")
    envelope["diagnosticsJson"] = json.dumps(stats | {"raw": "private"})
    with pytest.raises(CloudAtlasBoundaryError):
        client.diagnose_page(source, capset_token="synthetic-capset-token")


def test_fixed_schema_copies_and_migration_registry_cannot_drift() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (root / "app/domain/cloudatlas_structured.schema.json").read_bytes() == (
        root.parent / "octobus/cloudatlas-structured/contract.json"
    ).read_bytes()
    file = root / "app/alembic/versions/ca2810000001_structured_cloudatlas_domains.py"
    spec = importlib.util.spec_from_file_location("structured_migration", file)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert set(migration.NEW_DOMAINS) == contract.DOMAINS.keys()
    assert set(migration.NEW_PROFILES) == contract.PROFILES.keys()
    assert set(migration.SEARCH_FIELDS) == set(contract.SEARCH_FIELDS)
