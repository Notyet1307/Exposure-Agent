import copy
import hashlib
import json
import uuid
from typing import Any

import pytest

from app.domain import cloudatlas_assets_contract as contract
from app.domain.cloudatlas_sources import CloudAtlasBoundaryError
from app.domain.models import SourceInstance
from app.integrations.cloudatlas_assets import (
    OctobusCloudAtlasAssetsClient,
    normalize_items,
)


def _source() -> SourceInstance:
    return SourceInstance(
        project_id=uuid.uuid4(),
        instance_id="assets-fixture",
        capset_id="assets-only",
        capability_profile=contract.CAPABILITY_PROFILE,
        space_id="7",
        enabled=True,
    )


def _metadata(source: SourceInstance) -> dict[str, dict[str, Any]]:
    return {
        f"/admin/v1/services/{contract.SERVICE_ID}": {
            "ID": contract.SERVICE_ID,
            "PackageSHA256": contract.PACKAGE_SHA256,
            "DescriptorSHA256": contract.DESCRIPTOR_SHA256,
            "PackageVersion": "",
        },
        f"/admin/v1/instances/{source.instance_id}": {
            "ID": source.instance_id,
            "ServiceID": contract.SERVICE_ID,
            "Enabled": True,
            "HasSecret": True,
            "ConfigJSON": {
                "baseUrl": "https://cloudatlas.invalid/openapi",
                "spaceId": "7",
            },
            "ConfigSHA256": "a" * 64,
            "SecretSHA256": "b" * 64,
        },
        f"/admin/v1/capsets/{source.capset_id}": {
            "ID": source.capset_id,
            "Enabled": True,
        },
        f"/admin/v1/capsets/{source.capset_id}/instances": {
            "instances": [
                {
                    "ServiceID": contract.SERVICE_ID,
                    "InstanceID": source.instance_id,
                    "Enabled": True,
                    "IncludeAllMethods": False,
                }
            ]
        },
        f"/admin/v1/capsets/{source.capset_id}/methods": {
            "methods": [
                {"MethodFullName": method, "Enabled": True}
                for method in contract.METHODS.values()
            ]
        },
        f"/admin/v1/capsets/{source.capset_id}/tokens": {
            "tokens": [
                {
                    "ID": "fixture-token",
                    "TokenHash": hashlib.sha256(b"synthetic-capset-token").hexdigest(),
                }
            ]
        },
    }


def test_normalized_identity_and_field_contract_preserves_absence() -> None:
    row = {
        "id": "900719925474099312345",
        "ip": "2001:db8::1",
        "status": "valid",
        "bu": {"id": "9007199254740993", "name": "", "unapproved": "drop"},
        "tags": [{"pk": "9007199254740995", "name": "tag"}],
        "subnet": None,
        "sources": [],
        "unapproved": {"sensitive": "drop"},
    }
    result = normalize_items([row], "ip")[0]
    assert result == {
        key: value for key, value in row.items() if key != "unapproved"
    } | {"bu": {"id": "9007199254740993", "name": ""}}
    assert "provider" not in result
    for invalid_id in [900719925474099312345, True, None, "1.0", "1e3"]:
        with pytest.raises(CloudAtlasBoundaryError):
            normalize_items([{**row, "id": invalid_id}], "ip")
    with pytest.raises(CloudAtlasBoundaryError):
        normalize_items([{**row, "bu": ""}], "ip")
    with pytest.raises(CloudAtlasBoundaryError):
        normalize_items([{**row, "provider": None}], "ip")
    with pytest.raises(CloudAtlasBoundaryError):
        normalize_items([{**row, "sources": [{"factor": ["not-a-string"]}]}], "ip")


def test_credentials_are_metadata_only_and_reject_wrong_space_and_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OctobusCloudAtlasAssetsClient()
    source = _source()
    metadata = _metadata(source)
    calls: list[str] = []

    def request(method: str, path: str, **_kwargs: Any) -> dict[str, Any]:
        calls.append(method)
        return copy.deepcopy(metadata[path])

    monkeypatch.setattr(client, "_request_json", request)
    accepted = client.validate_credentials(
        source, capset_token="synthetic-capset-token"
    )
    assert accepted == client.current_fingerprint(source)
    assert set(calls) == {"GET"}
    with pytest.raises(CloudAtlasBoundaryError):
        client.validate_credentials(source, capset_token="wrong-token")
    metadata[f"/admin/v1/capsets/{source.capset_id}/tokens"]["tokens"] = []
    with pytest.raises(CloudAtlasBoundaryError):
        client.validate_credentials(source, capset_token="synthetic-capset-token")
    metadata = _metadata(source)
    metadata[f"/admin/v1/instances/{source.instance_id}"]["ConfigJSON"]["spaceId"] = "8"
    with pytest.raises(CloudAtlasBoundaryError):
        client.validate_credentials(source, capset_token="synthetic-capset-token")
    metadata = _metadata(source)
    source.capability_profile = "legacy-ip-v1"
    with pytest.raises(CloudAtlasBoundaryError):
        client.validate_credentials(source, capset_token="synthetic-capset-token")
    assert "POST" not in calls


def test_page_rejects_drift_and_failure_without_source_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OctobusCloudAtlasAssetsClient()
    source = _source()
    metadata = _metadata(source)
    calls: list[str] = []
    fail_upstream = False
    drift_after_page = False
    response = {
        "page": 1,
        "size": 2,
        "total": 1,
        "spaceId": "7",
        "itemsJson": json.dumps(
            [{"id": "9007199254740993", "ip": "192.0.2.1", "port": 443, "banner": None}]
        ),
    }

    def request(method: str, path: str, **_kwargs: Any) -> dict[str, Any]:
        if method == "POST":
            calls.append(path)
            if fail_upstream:
                raise CloudAtlasBoundaryError("cloudatlas_connectivity_failed")
            if drift_after_page:
                metadata[f"/admin/v1/instances/{source.instance_id}"][
                    "SecretSHA256"
                ] = "c" * 64
            return copy.deepcopy(response)
        return copy.deepcopy(metadata[path])

    monkeypatch.setattr(client, "_request_json", request)
    options: dict[str, Any] = {
        "capset_token": "synthetic-capset-token",
        "domain": "port",
        "page": 1,
        "size": 2,
        "max_response_bytes": 4096,
        "timeout_seconds": 5,
    }
    result = client.list_page(source, **options)
    assert result["items"][0]["id"] == "9007199254740993"
    assert result["items"][0]["banner"] is None
    assert "tunnel" not in result["items"][0]
    assert result["space_id"] == "7"
    response["spaceId"] = "8"
    with pytest.raises(CloudAtlasBoundaryError):
        client.list_page(source, **options)
    response["spaceId"] = "7"
    response["page"] = True
    with pytest.raises(CloudAtlasBoundaryError):
        client.list_page(source, **options)
    response["page"] = 1
    drift_after_page = True
    with pytest.raises(CloudAtlasBoundaryError):
        client.list_page(source, **options)
    drift_after_page = False
    fail_upstream = True
    before = len(calls)
    with pytest.raises(CloudAtlasBoundaryError):
        client.list_page(source, **options)
    assert len(calls) == before + 1


def test_proto3_omitted_zero_total_accepts_only_an_empty_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OctobusCloudAtlasAssetsClient()
    source = _source()
    metadata = _metadata(source)
    response = {"page": 1, "size": 2, "spaceId": "7", "itemsJson": "[]"}

    def request(method: str, path: str, **_kwargs: Any) -> dict[str, Any]:
        return copy.deepcopy(response if method == "POST" else metadata[path])

    monkeypatch.setattr(client, "_request_json", request)
    options: dict[str, Any] = {
        "capset_token": "synthetic-capset-token", "domain": "ip", "page": 1,
        "size": 2, "max_response_bytes": 4096, "timeout_seconds": 5,
    }
    page = client.list_page(source, **options)
    assert page["total"] == 0 and page["items"] == []
    response["itemsJson"] = '[{"id":"1","ip":"192.0.2.1","status":"valid"}]'
    with pytest.raises(CloudAtlasBoundaryError):
        client.list_page(source, **options)
