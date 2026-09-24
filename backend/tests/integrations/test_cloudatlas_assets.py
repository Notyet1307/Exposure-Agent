import copy
import hashlib
import json
import uuid
from types import SimpleNamespace
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
        "capset_token": "synthetic-capset-token",
        "domain": "ip",
        "page": 1,
        "size": 2,
        "max_response_bytes": 4096,
        "timeout_seconds": 5,
    }
    page = client.list_page(source, **options)
    assert page["total"] == 0 and page["items"] == []
    response["itemsJson"] = '[{"id":"1","ip":"192.0.2.1","status":"valid"}]'
    with pytest.raises(CloudAtlasBoundaryError):
        client.list_page(source, **options)


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    source = _source()
    state = SimpleNamespace(
        client=OctobusCloudAtlasAssetsClient(),
        source=source,
        metadata=_metadata(source),
        calls=[],
        response={
            "page": 1,
            "size": 2,
            "total": 1,
            "spaceId": "7",
            "itemsJson": '[{"id":"1","ip":"192.0.2.1","status":"valid"}]',
        },
        options={
            "capset_token": "synthetic-capset-token",
            "domain": "ip",
            "page": 1,
            "size": 2,
            "max_response_bytes": 4096,
            "timeout_seconds": 5,
        },
    )

    def request(method: str, path: str, **_kwargs: Any) -> dict[str, Any]:
        state.calls.append((method, path))
        return copy.deepcopy(
            state.response if method == "POST" else state.metadata[path]
        )

    monkeypatch.setattr(state.client, "_request_json", request)
    return state


@pytest.mark.parametrize(
    ("domain", "items"),
    [
        pytest.param("ip", {}, id="non-array-page"),
        pytest.param("ip", [{"id": "1"}], id="missing-address"),
        pytest.param(
            "ip",
            [{"id": "1", "ip": "not-an-address", "status": "valid"}],
            id="invalid-address",
        ),
        pytest.param(
            "ip",
            [{"id": "1", "ip": "fe80::1%eth0", "status": "valid"}],
            id="zone-scoped-address",
        ),
        pytest.param(
            "ip",
            [{"id": "1", "ip": "192.0.2.1", "status": "deleted"}],
            id="outside-valid-filter",
        ),
        pytest.param(
            "port", [{"id": "1", "ip": "192.0.2.1", "port": True}], id="boolean-integer"
        ),
        pytest.param(
            "port", [{"id": "1", "ip": "192.0.2.1", "port": 65536}], id="port-range"
        ),
        pytest.param(
            "ip",
            [{"id": "1", "ip": "192.0.2.1", "status": "valid", "tags": {}}],
            id="object-in-array-field",
        ),
        pytest.param(
            "ip",
            [
                {
                    "id": "1",
                    "ip": "192.0.2.1",
                    "status": "valid",
                    "bu": {"name": "unidentified"},
                }
            ],
            id="business-unit-without-identity",
        ),
        pytest.param(
            "ip",
            [
                {
                    "id": "1",
                    "ip": "192.0.2.1",
                    "status": "valid",
                    "tags": [{"name": "unidentified"}],
                }
            ],
            id="tag-without-identity",
        ),
    ],
)
def test_projected_page_rejects_invalid_domain_records_without_partial_results(
    transport: SimpleNamespace, domain: str, items: Any
) -> None:
    transport.options["domain"] = domain
    transport.response["itemsJson"] = json.dumps(items)
    with pytest.raises(CloudAtlasBoundaryError) as error:
        transport.client.list_page(transport.source, **transport.options)
    assert error.value.code == "cloudatlas_response_contract_failed"
    assert sum(method == "POST" for method, _path in transport.calls) == 1


def test_projected_page_rejects_duplicate_identity_even_when_addresses_differ(
    transport: SimpleNamespace,
) -> None:
    transport.response.update(
        total=2,
        itemsJson=json.dumps(
            [
                {"id": "1", "ip": "192.0.2.1", "status": "valid"},
                {"id": "1", "ip": "192.0.2.2", "status": "valid"},
            ]
        ),
    )
    with pytest.raises(CloudAtlasBoundaryError) as error:
        transport.client.list_page(transport.source, **transport.options)
    assert error.value.code == "cloudatlas_response_contract_failed"


@pytest.mark.parametrize(
    "drift",
    ["instance", "binding", "methods", "space-type", "enabled-type", "source-type"],
)
def test_scope_or_type_drift_prevents_any_asset_data_request(
    transport: SimpleNamespace, drift: str
) -> None:
    source = transport.source
    instance = transport.metadata[f"/admin/v1/instances/{source.instance_id}"]
    if drift == "instance":
        instance["ID"] = "another-instance"
    elif drift == "binding":
        transport.metadata[f"/admin/v1/capsets/{source.capset_id}/instances"][
            "instances"
        ][0]["IncludeAllMethods"] = True
    elif drift == "methods":
        transport.metadata[f"/admin/v1/capsets/{source.capset_id}/methods"][
            "methods"
        ].append({"MethodFullName": "unapproved.AssetService/Delete", "Enabled": True})
    elif drift == "space-type":
        instance["ConfigJSON"]["spaceId"] = 7
    elif drift == "enabled-type":
        instance["Enabled"] = "true"
    else:
        source.source_type = "unapproved"
    with pytest.raises(CloudAtlasBoundaryError):
        transport.client.list_page(source, **transport.options)
    assert all(method == "GET" for method, _path in transport.calls)


@pytest.mark.parametrize(
    "origin",
    [
        "https://user:synthetic-secret@cloudatlas.invalid/openapi",
        "https://cloudatlas.invalid:invalid/openapi",
    ],
)
def test_configured_origin_must_be_valid_and_cannot_embed_credentials(
    transport: SimpleNamespace, origin: str
) -> None:
    transport.metadata[f"/admin/v1/instances/{transport.source.instance_id}"][
        "ConfigJSON"
    ]["baseUrl"] = origin
    with pytest.raises(CloudAtlasBoundaryError) as error:
        transport.client.list_page(transport.source, **transport.options)
    assert error.value.code == "cloudatlas_response_contract_failed"
    assert "synthetic-secret" not in str(error.value)
    assert all(method == "GET" for method, _path in transport.calls)


@pytest.mark.parametrize("phase", ["fingerprint", "credential-check"])
def test_material_rotation_during_admission_cannot_authorize_a_data_call(
    transport: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    client: OctobusCloudAtlasAssetsClient = transport.client
    request = client._request_json
    path = (
        f"/admin/v1/instances/{transport.source.instance_id}"
        if phase == "fingerprint"
        else f"/admin/v1/capsets/{transport.source.capset_id}/tokens"
    )
    reads = 0

    def rotate(method: str, requested_path: str, **options: Any) -> dict[str, Any]:
        nonlocal reads
        if requested_path == path:
            reads += 1
            if reads == 2:
                transport.metadata[
                    f"/admin/v1/instances/{transport.source.instance_id}"
                ]["ConfigSHA256"] = "c" * 64
        return request(method, requested_path, **options)

    monkeypatch.setattr(transport.client, "_request_json", rotate)
    with pytest.raises(CloudAtlasBoundaryError) as error:
        transport.client.list_page(transport.source, **transport.options)
    assert error.value.code == "cloudatlas_response_contract_failed"
    assert all(method == "GET" for method, _path in transport.calls)


@pytest.mark.parametrize(
    "failure",
    ["invalid-json", "deep-json", "oversized-envelope", "wrong-size", "wrong-space"],
)
def test_page_envelope_is_bounded_and_pinned_before_returning_records(
    transport: SimpleNamespace, failure: str
) -> None:
    if failure == "invalid-json":
        transport.response["itemsJson"] = '{"secret":"synthetic-secret"'
    elif failure == "deep-json":
        transport.response["itemsJson"] = "[" * 2000 + "]" * 2000
    elif failure == "oversized-envelope":
        transport.options["max_response_bytes"] = 1
        transport.response["itemsJson"] = " " * 1029
    elif failure == "wrong-size":
        transport.response["size"] = 3
    else:
        transport.response["spaceId"] = "8"
    with pytest.raises(CloudAtlasBoundaryError) as error:
        transport.client.list_page(transport.source, **transport.options)
    assert error.value.code == "cloudatlas_response_contract_failed"
    assert "synthetic-secret" not in str(error.value)
    assert sum(method == "POST" for method, _path in transport.calls) == 1


@pytest.mark.parametrize(
    "denial", ["unknown-domain", "unbounded-budget", "revoked-access", "blank-token"]
)
def test_local_admission_denies_unsafe_requests_without_transport(
    transport: SimpleNamespace, denial: str
) -> None:
    if denial == "unknown-domain":
        transport.options["domain"] = "delete"
    elif denial == "unbounded-budget":
        transport.options["max_response_bytes"] = 16777217
    elif denial == "revoked-access":
        transport.source.data_access_enabled = False
    else:
        transport.options["capset_token"] = " "
    with pytest.raises(CloudAtlasBoundaryError) as error:
        transport.client.list_page(transport.source, **transport.options)
    assert (
        error.value.code
        == {
            "unknown-domain": "cloudatlas_response_contract_failed",
            "unbounded-budget": "cloudatlas_response_contract_failed",
            "revoked-access": "cloudatlas_authorization_failed",
            "blank-token": "octobus_authentication_failed",
        }[denial]
    )
    assert transport.calls == []
