"""#281 synthetic HTTP/worker/database checks for the fourteen fixed domains."""

import hashlib
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain import cloudatlas_structured_contract as contract
from app.domain import external_assets as service
from app.domain import source_correlations
from app.domain.cloudatlas_sources import CloudAtlasFingerprint
from app.domain.external_asset_models import (
    ExternalAssetVersion,
)
from app.domain.models import Project
from app.integrations.cloudatlas_assets import OctobusCloudAtlasAssetsClient
from app.integrations.cloudatlas_structured import OctobusCloudAtlasStructuredClient
from tests.api.routes.test_external_assets import assets as assets
from tests.api.routes.test_external_assets import execute, listing, submit


def sample(shape: dict[str, Any], key: str = "") -> Any:
    if "enum" in shape:
        return shape["enum"][0]
    kind = shape["type"]
    if kind == "identity":
        return "900719925474099312345"
    if kind == "integer":
        return 443 if key == "port" else 1
    if kind == "boolean":
        return True
    if kind == "string":
        return (
            "valid"
            if key == "status"
            else "2001:db8::1"
            if key == "ip"
            else "Synthetic%_\\\0\0text\x01\x02"
        )
    if kind == "array":
        return [sample(shape["items"])]
    return {name: sample(child, name) for name, child in shape["properties"].items()}


@pytest.fixture(params=list(contract.DOMAINS))
def structured_assets(
    assets: SimpleNamespace,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> SimpleNamespace:
    state = assets
    domain = request.param
    definition = contract.DOMAINS[domain]
    token = "synthetic-structured-" + domain
    state.domain = domain
    state.definition = definition
    state.now = get_datetime_utc()
    state.body["retain_until"] = (state.now + timedelta(hours=1)).isoformat()
    monkeypatch.setattr(service, "get_datetime_utc", lambda: state.now)
    monkeypatch.setattr(
        "app.api.routes.external_assets.get_datetime_utc", lambda: state.now
    )
    monkeypatch.setattr(
        settings, f"CLOUDATLAS_{domain.upper()}_CAPSET_TOKEN", SecretStr(token)
    )
    fingerprint = hashlib.sha256(domain.encode()).hexdigest()

    def page(self: Any, source: Any, **kwargs: Any) -> dict[str, Any]:
        result = OctobusCloudAtlasAssetsClient.list_page(self, source, **kwargs)
        return result | {"omitted_field_count": 1 if result["items"] else 0}

    monkeypatch.setattr(OctobusCloudAtlasStructuredClient, "list_page", page)

    def credentials(
        self: OctobusCloudAtlasStructuredClient, source: Any, *, capset_token: str
    ) -> CloudAtlasFingerprint:
        assert capset_token == token
        assert (
            self.CAPABILITY_PROFILE
            == source.capability_profile
            == definition["profile"]
        )
        assert self.DOMAIN_METHODS == {domain: definition["method"]}
        return CloudAtlasFingerprint(fingerprint)

    monkeypatch.setattr(
        OctobusCloudAtlasStructuredClient, "validate_credentials", credentials
    )
    response = state.client.post(
        state.base + "/sources",
        headers=state.headers,
        json={
            "instance_id": "synthetic-" + domain,
            "capset_id": "synthetic-" + domain,
            "space_id": "7",
            "capability_profile": definition["profile"],
        },
    )
    assert response.status_code == 201, response.text
    state.source_id = response.json()["id"]
    state.path = state.base + "/sources/" + state.source_id
    assert (
        state.client.post(state.path + "/validate", headers=state.headers).json()[
            "validation_status"
        ]
        == "validated"
    )
    assert state.calls == []
    assert (
        state.client.patch(
            state.path, headers=state.headers, json={"enabled": True}
        ).status_code
        == 200
    )
    first = sample(definition["schema"])
    second = json.loads(json.dumps(first)) | {"id": "2"}
    if definition["text_fields"]:
        second[definition["text_fields"][0]] = "Other synthetic record"
        for field in definition["text_fields"][1:]:
            second[field] = "Other"
    state.pages[domain] = [[first], [second]]
    return state


def test_each_domain_publishes_fixed_fields_partial_then_complete_and_reads_locally(
    structured_assets: SimpleNamespace,
) -> None:
    state = structured_assets
    partial = execute(state, submit(state, max_pages=1, max_records=1))
    assert partial["status"] == "PARTIAL_SUCCEEDED"
    assert (
        len(partial["domains"]) == 1 and partial["domains"][0]["domain"] == state.domain
    )
    partial_version = partial["domains"][0]["version_id"]
    complete = execute(state, submit(state, max_pages=2, max_records=2))
    assert complete["status"] == "SUCCEEDED", complete
    version_id = complete["domains"][0]["version_id"]
    assert complete["domains"][0]["complete"] is True
    project = state.db.get(Project, uuid.UUID(state.project_id))
    assert project is not None
    with pytest.raises(HTTPException) as rejected:
        source_correlations._external(
            state.db,
            project,
            source_correlations.ExternalSelection(
                kind="external_versions",
                source_instance_id=uuid.UUID(state.source_id),
                ip_version_id=uuid.UUID(version_id),
            ),
        )
    assert rejected.value.status_code == 404
    assert state.calls == [(state.domain, 1), (state.domain, 1), (state.domain, 2)]
    data = listing(state, state.domain, version_id=version_id)
    assert data["count"] == 2
    assert data["version"]["filter"] == state.definition["filters"]
    assert data["version"]["pages_read"] == 2
    assert data["version"]["omitted_field_count"] == 2
    assert listing(state, state.domain, version_id=partial_version)["count"] == 1
    rows = {row["source_id"]: row for row in data["data"]}
    assert rows["900719925474099312345"]["fields"] == state.pages[state.domain][0][0]
    assert (
        all(row["ip"] is None and row["canonical_ip"] is None for row in rows.values())
        if state.domain != "openport"
        else rows["2"]["canonical_ip"] == "2001:db8::1"
    )
    record_id = rows["900719925474099312345"]["id"]
    detail = state.client.get(
        state.path + f"/versions/{version_id}/records/{record_id}",
        headers=state.headers,
    )
    assert detail.status_code == 200
    assert detail.json()["record"]["fields"] == rows["900719925474099312345"]["fields"]
    if state.definition["text_fields"]:
        assert (
            listing(state, state.domain, version_id=version_id, q="%_\\\0\0TeXt")[
                "count"
            ]
            == 1
        )
        assert (
            listing(state, state.domain, version_id=version_id, q="%_\\text")["count"]
            == 0
        )
        assert (
            listing(state, state.domain, version_id=version_id, q="\\u0000")["count"]
            == 0
        )
    if state.domain == "openport":
        assert (
            listing(state, state.domain, version_id=version_id, ip="2001:0db8::1")[
                "count"
            ]
            == 2
        )
    for field in state.definition["exact_fields"]:
        value = state.pages[state.domain][0][0][field]
        assert (
            listing(state, state.domain, version_id=version_id, **{field: value})[
                "count"
            ]
            == 2
        )
        assert (
            listing(state, state.domain, version_id=version_id, **{field: "no-match"})[
                "count"
            ]
            == 0
        )
    if state.domain.startswith("seed_") and state.domain != "seed_icon":
        assert (
            listing(state, state.domain, version_id=version_id, seed_enabled=True)[
                "count"
            ]
            == 2
        )
        assert (
            listing(state, state.domain, version_id=version_id, seed_enabled=False)[
                "count"
            ]
            == 0
        )
        assert (
            listing(
                state,
                state.domain,
                version_id=version_id,
                confidence=state.pages[state.domain][0][0]["confidence"],
            )["count"]
            == 2
        )
    assert state.calls == [(state.domain, 1), (state.domain, 1), (state.domain, 2)]
    wrong = state.client.get(
        state.path + "/records",
        headers=state.headers,
        params={"domain": "ip", "version_id": version_id},
    )
    assert wrong.status_code in (404, 422)
    # Revocation removes fixed-version reads, not just the default page.
    assert (
        state.client.patch(
            state.path, headers=state.headers, json={"data_access_enabled": False}
        ).status_code
        == 200
    )
    assert (
        state.client.get(
            state.path + "/records",
            headers=state.headers,
            params={"domain": state.domain, "version_id": version_id},
        ).status_code
        == 403
    )


def test_each_domain_database_rejects_wrong_scope_fields_and_projection(
    structured_assets: SimpleNamespace,
) -> None:
    state = structured_assets
    sync = submit(state)
    version = state.db.exec(
        select(ExternalAssetVersion).where(
            ExternalAssetVersion.sync_id == uuid.UUID(sync["id"])
        )
    ).one()
    version.status = "RUNNING"
    state.db.add(version)
    state.db.commit()
    fields = state.pages[state.domain][0][0]
    search = {
        k: fields[k].split("\0")
        for k in contract.SEARCH_FIELDS
        if isinstance(fields.get(k), str)
    }
    columns = {
        "id": uuid.uuid4(),
        "version": version.id,
        "source": fields["id"],
        "ip": fields.get("ip") if state.domain == "openport" else None,
        "canonical": "2001:db8::1" if state.domain == "openport" else None,
        "fields": json.dumps(fields),
        "search": json.dumps(search),
        "root": None,
        "sub": fields["subdomain"].split("\0") if "subdomain" in fields else None,
        "status": fields["status"].split("\0") if "status" in fields else None,
    }
    statement = text("""INSERT INTO external_asset_records(id,version_id,source_id,ip,canonical_ip,fields,search_fields,root_domain_segments,subdomain_segments,status_segments)
        VALUES(:id,:version,:source,:ip,:canonical,CAST(:fields AS json),CAST(:search AS jsonb),:root,:sub,:status)""")
    # Direct SQL cannot inject a non-whitelisted field or private crawler material.
    for extra in [{"not_allowed": "value"}, {"headers": "private value"}]:
        with pytest.raises(SQLAlchemyError), state.db.begin_nested():
            state.db.execute(
                statement, columns | {"fields": json.dumps(fields | extra)}
            )
    if search:
        forged = search | {next(iter(search)): ["forged"]}
        with pytest.raises(SQLAlchemyError), state.db.begin_nested():
            state.db.execute(statement, columns | {"search": json.dumps(forged)})
    with state.db.begin_nested():
        state.db.execute(statement, columns)
    with pytest.raises(SQLAlchemyError), state.db.begin_nested():
        state.db.execute(
            text(
                "UPDATE external_syncs SET request=jsonb_set(request,'{domain}','\"ip\"') WHERE id=:id"
            ),
            {"id": uuid.UUID(sync["id"])},
        )
    with pytest.raises(SQLAlchemyError), state.db.begin_nested():
        state.db.execute(
            text("UPDATE external_asset_versions SET domain='ip' WHERE id=:id"),
            {"id": version.id},
        )
    state.db.rollback()


def test_each_domain_failure_preserves_history_empty_and_expiry_are_distinct(
    structured_assets: SimpleNamespace,
) -> None:
    state = structured_assets
    complete = execute(state, submit(state, max_pages=2, max_records=2))
    version_id = complete["domains"][0]["version_id"]
    bad = json.loads(json.dumps(state.pages[state.domain][0][0]))
    bad["id"] = True
    state.pages[state.domain] = [[bad]]
    failed = execute(state, submit(state, max_pages=1, max_records=1))
    assert failed["status"] == "FAILED"
    assert failed["domains"][0]["version_id"] is None
    assert listing(state, state.domain, version_id=version_id)["count"] == 2
    state.pages[state.domain] = [[]]
    empty = execute(state, submit(state, max_pages=1, max_records=1))
    assert empty["status"] == "SUCCEEDED" and empty["domains"][0]["complete"]
    empty_id = empty["domains"][0]["version_id"]
    result = listing(state, state.domain, version_id=empty_id)
    assert result["state"] == "PUBLISHED" and result["count"] == 0
    assert result["version"]["omitted_field_count"] == 0
    state.now += timedelta(hours=2)
    expired = listing(state, state.domain, version_id=version_id)
    assert expired["state"] == "EXPIRED" and expired["data"] == []
