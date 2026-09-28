import copy
import uuid
from typing import Any

import pytest

from app.domain import cloudatlas_dns_contract as contract
from app.domain.cloudatlas_sources import CloudAtlasBoundaryError
from app.domain.models import SourceInstance
from app.integrations.cloudatlas_assets import normalize_items
from app.integrations.cloudatlas_dns import OctobusCloudAtlasDNSClient
from tests.integrations.test_cloudatlas_assets import _metadata


def dns_row(
    identity: int = 9007199254740993, name: str = "A%_\\B.Example.test"
) -> dict[str, Any]:
    return {
        "id": str(identity),
        "domain": "Example.test",
        "subdomain": name,
        "rdtype": "CNAME",
        "record": "2001:db8::1 <script>text-only</script>",
        "status": "source-declared",
        "bu": {"id": "9007199254740993123456792", "name": ""},
        "tags": [{"pk": "9007199254740993123456789", "name": ""}],
        "created_at": "",
        "updated_at": "2026-09-27 01:02:03",
        "lastseen_at": "",
    }


def test_dns_required_fields_preserve_empty_values_large_ids_and_non_query_types() -> (
    None
):
    row = dns_row()
    extra = copy.deepcopy(row)
    extra["unapproved"] = "not persisted"
    extra["tags"][0]["unapproved"] = "not persisted"
    extra["bu"]["unapproved"] = "not persisted"
    assert normalize_items([extra, dns_row(9007199254740994)], "dns") == [
        row,
        dns_row(9007199254740994),
    ]
    for key in row:
        with pytest.raises(CloudAtlasBoundaryError):
            normalize_items(
                [{name: value for name, value in row.items() if name != key}], "dns"
            )
        with pytest.raises(CloudAtlasBoundaryError):
            normalize_items([{**row, key: None}], "dns")
    empty = {key: "" for key in row if key not in ("id", "bu", "tags")}
    assert normalize_items([{**row, **empty, "tags": []}], "dns") == [
        {**row, **empty, "tags": []}
    ]
    patch: dict[str, Any]
    for patch in (
        {"bu": ""},
        {"bu": []},
        {"bu": {}},
        {"bu": {"id": "1"}},
        {"bu": {"name": ""}},
        {"bu": {"id": None, "name": ""}},
        {"bu": {"id": "1", "name": None}},
        {"bu": {"id": "1", "name": 7}},
        {"bu": {"id": 9007199254740993, "name": ""}},
        {"bu": {"id": "1.0", "name": ""}},
        {"bu": {"id": "9" * 101, "name": ""}},
        {"tags": [{}]},
        {"tags": [{"pk": 9007199254740993, "name": ""}]},
        {"id": 9007199254740993},
    ):
        with pytest.raises(CloudAtlasBoundaryError):
            normalize_items([{**row, **patch}], "dns")
    with pytest.raises(CloudAtlasBoundaryError):
        normalize_items([row, row], "dns")


def test_dns_capability_never_admits_old_domains_or_extra_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SourceInstance(
        project_id=uuid.uuid4(),
        source_type=contract.SOURCE_TYPE,
        capability_profile=contract.CAPABILITY_PROFILE,
        instance_id="dns-fixture",
        capset_id="dns-only",
        space_id="7",
        enabled=True,
    )
    client = OctobusCloudAtlasDNSClient()
    metadata = _metadata(source, capability=contract)
    monkeypatch.setattr(
        client,
        "_request_json",
        lambda _method, path, **_kw: copy.deepcopy(metadata[path]),
    )
    client.validate_credentials(source, capset_token="synthetic-capset-token")
    for token in ("", "wrong-token"):
        with pytest.raises(CloudAtlasBoundaryError):
            client.validate_credentials(source, capset_token=token)
    for domain in ("ip", "port", "root_domain"):
        with pytest.raises(CloudAtlasBoundaryError):
            client.list_page(
                source,
                capset_token="synthetic-capset-token",
                domain=domain,
                page=1,
                size=20,
                max_response_bytes=4096,
                timeout_seconds=5,
            )
    metadata["/admin/v1/capsets/dns-only/methods"]["methods"].append(
        {
            "MethodFullName": "cloudatlas.rootdomains.v1.CloudAtlasRootDomainsService/ListRootDomains",
            "Enabled": True,
        }
    )
    with pytest.raises(CloudAtlasBoundaryError):
        client.validate_credentials(source, capset_token="synthetic-capset-token")
