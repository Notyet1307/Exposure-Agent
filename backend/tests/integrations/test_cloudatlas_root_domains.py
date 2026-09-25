import copy
import json
import uuid
from typing import Any

import pytest

from app.domain import cloudatlas_assets_contract as assets_contract
from app.domain import cloudatlas_root_domains_contract as contract
from app.domain.cloudatlas_sources import CloudAtlasBoundaryError
from app.domain.models import SourceInstance
from app.integrations.cloudatlas_assets import (
    OctobusCloudAtlasAssetsClient,
    normalize_items,
)
from app.integrations.cloudatlas_root_domains import OctobusCloudAtlasRootDomainsClient
from tests.integrations.test_cloudatlas_assets import _metadata


def _row() -> dict[str, Any]:
    return {
        "id": "9007199254740993123456789",
        "root_domain": "MiXeD.Example.invalid",
        "status": "source-reported-status",
        "icp_date": None,
        "icp_num": "",
        "icp_official_name": None,
        "whois_registrant": "",
        "whois_email": None,
        "whois_expiration_time": None,
        "valid_subdomain": 7,
        "sources": [
            {"source": "declared", "reason": "<script>text</script>", "factor": ""}
        ],
        "created_at": "2026-01-02 03:04:05",
        "updated_at": "",
        "lastseen_at": "2026-01-03T00:00:00+08:00",
    }


def test_root_projection_preserves_identity_strings_and_all_required_fields() -> None:
    row = _row()
    extra = copy.deepcopy(row)
    extra["unapproved"] = {"secret": "discard"}
    extra["sources"][0]["private"] = "discard"
    assert normalize_items([extra], "root_domain") == [row]
    same_name = {**row, "id": "9007199254740993123456790", "sources": []}
    assert normalize_items([row, same_name], "root_domain") == [row, same_name]
    for key in row:
        missing = {name: value for name, value in row.items() if name != key}
        with pytest.raises(CloudAtlasBoundaryError):
            normalize_items([missing], "root_domain")
        nullable = key in {
            "icp_date",
            "icp_num",
            "icp_official_name",
            "whois_registrant",
            "whois_email",
            "whois_expiration_time",
        }
        if nullable:
            assert normalize_items([{**row, key: None}], "root_domain")[0][key] is None
        else:
            with pytest.raises(CloudAtlasBoundaryError):
                normalize_items([{**row, key: None}], "root_domain")
    for key in row["sources"][0]:
        missing = {
            name: value for name, value in row["sources"][0].items() if name != key
        }
        with pytest.raises(CloudAtlasBoundaryError):
            normalize_items([{**row, "sources": [missing]}], "root_domain")
        with pytest.raises(CloudAtlasBoundaryError):
            normalize_items(
                [{**row, "sources": [{**row["sources"][0], key: None}]}], "root_domain"
            )
    invalid_values: list[dict[str, Any]] = [
        {"id": 9007199254740993},
        {"id": "1e3"},
        {"id": "9" * 101},
        {"root_domain": "  "},
        {"status": ""},
        {"valid_subdomain": True},
        {"valid_subdomain": 1.5},
        {"sources": {}},
        {"whois_email": 7},
    ]
    for patch in invalid_values:
        with pytest.raises(CloudAtlasBoundaryError):
            normalize_items([{**row, **patch}], "root_domain")
    with pytest.raises(CloudAtlasBoundaryError):
        normalize_items([row, row], "root_domain")


def test_root_client_isolates_capability_and_rechecks_material_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SourceInstance(
        project_id=uuid.uuid4(),
        source_type=contract.SOURCE_TYPE,
        capability_profile=contract.CAPABILITY_PROFILE,
        instance_id="root-fixture",
        capset_id="root-only",
        space_id="7",
        enabled=True,
    )
    client = OctobusCloudAtlasRootDomainsClient()
    metadata = _metadata(source, capability=contract)
    calls: list[tuple[str, str]] = []
    drift = False
    fail = False
    response = {
        "page": 1,
        "size": 2,
        "total": 1,
        "spaceId": "7",
        "itemsJson": json.dumps([_row()]),
    }

    def request(method: str, path: str, **_kwargs: Any) -> dict[str, Any]:
        calls.append((method, path))
        if method == "POST":
            if fail:
                raise CloudAtlasBoundaryError("cloudatlas_connectivity_failed")
            if drift:
                metadata[f"/admin/v1/instances/{source.instance_id}"][
                    "SecretSHA256"
                ] = "c" * 64
            return copy.deepcopy(response)
        return copy.deepcopy(metadata[path])

    monkeypatch.setattr(client, "_request_json", request)
    options: dict[str, Any] = {
        "capset_token": "synthetic-capset-token",
        "domain": "root_domain",
        "page": 1,
        "size": 2,
        "max_response_bytes": 4096,
        "timeout_seconds": 5,
    }
    page = client.list_page(source, **options)
    assert page["items"] == [_row()]
    assert [path for method, path in calls if method == "POST"] == [
        f"/capsets/root-only/connect/root-fixture/{contract.METHODS['root_domain']}"
    ]
    for domain in ("ip", "port"):
        with pytest.raises(CloudAtlasBoundaryError):
            client.list_page(source, **{**options, "domain": domain})
    assert sum(method == "POST" for method, _path in calls) == 1
    with pytest.raises(CloudAtlasBoundaryError):
        OctobusCloudAtlasAssetsClient().current_fingerprint(source)
    for attribute, value in [
        ("source_type", "cloudatlas"),
        ("capability_profile", "assets-v1"),
    ]:
        original = getattr(source, attribute)
        setattr(source, attribute, value)
        with pytest.raises(CloudAtlasBoundaryError):
            client.current_fingerprint(source)
        setattr(source, attribute, original)
    methods = metadata[f"/admin/v1/capsets/{source.capset_id}/methods"]["methods"]
    methods.append({"MethodFullName": assets_contract.METHODS["ip"], "Enabled": True})
    with pytest.raises(CloudAtlasBoundaryError):
        client.list_page(source, **options)
    methods.pop()
    for token in ("", "wrong-token"):
        with pytest.raises(CloudAtlasBoundaryError):
            client.list_page(source, **{**options, "capset_token": token})
    assert sum(method == "POST" for method, _path in calls) == 1
    drift = True
    with pytest.raises(CloudAtlasBoundaryError):
        client.list_page(source, **options)
    drift = False
    fail = True
    before = sum(method == "POST" for method, _path in calls)
    with pytest.raises(CloudAtlasBoundaryError):
        client.list_page(source, **options)
    assert sum(method == "POST" for method, _path in calls) == before + 1
