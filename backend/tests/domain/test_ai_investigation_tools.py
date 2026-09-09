import json
import uuid
from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr
from pytest import MonkeyPatch

from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain import ai_investigation_tools as tools
from app.domain import ai_investigations as service
from app.domain.cloudatlas_sources import (
    METHOD,
    CloudAtlasBoundaryError,
    CloudAtlasFingerprint,
    OctobusCloudAtlasClient,
)
from app.domain.model_qualification import ModelBinding, model_binding
from app.domain.models import (
    AiInvestigation,
    GovernanceRun,
    Project,
    Resource,
    SourceInstance,
)
from tests.api.routes.test_ip_source_comparison import comparison_run as comparison_run


def _record() -> AiInvestigation:
    return AiInvestigation(
        project_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        initiated_by=uuid.uuid4(),
        material_sha256="a" * 64,
        max_material_bytes=100_000,
        sources=[
            {
                "source_type": "CLOUDATLAS",
                "input_id": str(uuid.uuid4()),
                "snapshot_id": str(uuid.uuid4()),
                "content_sha256": "b" * 64,
            }
        ],
    )


def _binding(endpoint: str = "http://127.0.0.1/v1") -> ModelBinding:
    return replace(
        model_binding(
            endpoint="http://127.0.0.1/v1",
            model_identity="fixture-model",
            protocol="responses",
            config_revision="fixture-v1",
            runner_build_version="fixture-v1",
            agent_compose_runtime_version="fixture-v1",
        ),
        endpoint=endpoint,
    )


@pytest.fixture
def live_context(monkeypatch: MonkeyPatch) -> tuple[AiInvestigation, SourceInstance]:
    record = _record()
    source = SourceInstance(
        id=uuid.UUID(record.sources[0]["input_id"]),
        tenant_id=record.tenant_id,
        project_id=record.project_id,
        instance_id="fixture-instance",
        capset_id="fixture-capset",
        enabled=True,
        validated_at=get_datetime_utc(),
        validated_fingerprint="c" * 64,
    )
    monkeypatch.setattr(settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-token"))
    monkeypatch.setattr(service, "load_material", lambda **_: ({}, [], _binding()))
    monkeypatch.setattr(
        tools,
        "_cloudatlas_scope",
        lambda _: (source, "192.0.2.10", "2026-09-01T00:00:00+00:00"),
    )
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "current_fingerprint",
        lambda *_: CloudAtlasFingerprint("c" * 64),
    )
    return record, source


def _pages(monkeypatch: MonkeyPatch, assets: list[dict[str, str]]) -> None:
    def page(
        _client: Any, _source: Any, *, page: int, size: int, **_kwargs: Any
    ) -> dict[str, Any]:
        return {
            "items": assets[(page - 1) * size : page * size],
            "page": page,
            "size": size,
            "total": len(assets),
        }

    monkeypatch.setattr(OctobusCloudAtlasClient, "list_ip_assets_page", page)


def test_live_read_filters_normalized_asset_and_retains_time_and_source(
    monkeypatch: MonkeyPatch, live_context: tuple[AiInvestigation, SourceInstance]
) -> None:
    record, source = live_context
    assets = [
        {"id": f"foreign-{index}", "ip": "198.51.100.20", "status": "valid"}
        for index in range(100)
    ]
    assets.append({"id": "matching", "ip": "::ffff:192.0.2.10", "status": "valid"})
    _pages(monkeypatch, assets)
    result = tools.read_cloudatlas_asset(record=record)
    fact = result["items"][0]["fact"]
    assert fact["assets"] == [{"id": "matching", "ip": "192.0.2.10", "status": "valid"}]
    assert "foreign-" not in json.dumps(result)
    assert fact["source"]["source_instance_id"] == str(source.id)
    assert fact["run_id"] == str(record.run_id)
    assert fact["queried_at"] <= fact["completed_at"]
    content = {
        key: value
        for key, value in fact.items()
        if key not in {"queried_at", "completed_at"}
    }
    assert result["content_sha256"] == service.material_hash(content)


def test_no_matching_data_is_not_a_successful_citation_or_truncated_read(
    monkeypatch: MonkeyPatch, live_context: tuple[AiInvestigation, SourceInstance]
) -> None:
    record, _source = live_context
    _pages(monkeypatch, [{"id": "foreign", "ip": "198.51.100.20", "status": "valid"}])
    result = tools.read_cloudatlas_asset(record=record)
    assert result["result"] == "NO_DATA"
    assert result["items"] == []
    assert result["truncated"] is False
    assert result["gaps"] == ["cloudatlas_asset_not_found"]
    assert result["source"]["method"] == METHOD
    _pages(
        monkeypatch,
        [{"id": str(i), "ip": "192.0.2.10", "status": "valid"} for i in range(501)],
    )
    with pytest.raises(service.InvestigationError, match="cloudatlas_read_limit"):
        tools.read_cloudatlas_asset(record=record)


@pytest.mark.parametrize(
    "corruption",
    [
        "total_changed",
        "short_page",
        "duplicate_id",
        "invalid_ip",
        "invalid_status",
        "oversized_id",
        "wrong_page",
    ],
)
def test_malformed_or_incomplete_pages_never_return_partial_facts(
    monkeypatch: MonkeyPatch,
    live_context: tuple[AiInvestigation, SourceInstance],
    corruption: str,
) -> None:
    record, _source = live_context

    def page(_client: Any, _source: Any, **kwargs: Any) -> dict[str, Any]:
        number = kwargs["page"]
        items = [
            {"id": str(index), "ip": "192.0.2.10", "status": "valid"}
            for index in (range(100) if number == 1 else [100])
        ]
        payload = {"items": items, "page": number, "size": 100, "total": 101}
        if number == 2:
            if corruption == "total_changed":
                payload["total"] = 102
            elif corruption == "short_page":
                payload["items"] = []
            elif corruption == "duplicate_id":
                items[0]["id"] = "0"
            elif corruption == "invalid_ip":
                items[0]["ip"] = "not-an-ip"
            elif corruption == "invalid_status":
                items[0]["status"] = "deleted"
            elif corruption == "oversized_id":
                items[0]["id"] = "x" * 256
            else:
                payload["page"] = 1
        return payload

    monkeypatch.setattr(OctobusCloudAtlasClient, "list_ip_assets_page", page)
    with pytest.raises(
        service.InvestigationError, match="cloudatlas_response_contract_failed"
    ):
        tools.read_cloudatlas_asset(record=record)


def test_upstream_failure_and_fingerprint_change_discard_matching_facts(
    monkeypatch: MonkeyPatch, live_context: tuple[AiInvestigation, SourceInstance]
) -> None:
    record, _source = live_context
    _pages(monkeypatch, [{"id": "matching", "ip": "192.0.2.10", "status": "valid"}])
    fingerprints = iter(["c" * 64, "d" * 64])
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "current_fingerprint",
        lambda *_: CloudAtlasFingerprint(next(fingerprints)),
    )
    with pytest.raises(service.InvestigationError, match="cloudatlas_material_changed"):
        tools.read_cloudatlas_asset(record=record)

    def fail(*_: Any) -> Any:
        raise CloudAtlasBoundaryError("cloudatlas_upstream_failed")

    monkeypatch.setattr(OctobusCloudAtlasClient, "current_fingerprint", fail)
    with pytest.raises(service.InvestigationError, match="cloudatlas_upstream_failed"):
        tools.read_cloudatlas_asset(record=record)


def test_revoked_operator_cannot_read_even_an_enabled_source(
    monkeypatch: MonkeyPatch, live_context: tuple[AiInvestigation, SourceInstance]
) -> None:
    record, _source = live_context
    _pages(monkeypatch, [])

    def denied(**_: Any) -> Any:
        raise service.InvestigationError("investigation_scope_denied")

    monkeypatch.setattr(service, "load_material", denied)
    with pytest.raises(service.InvestigationError, match="investigation_scope_denied"):
        tools.read_cloudatlas_asset(record=record)
    with pytest.raises(service.InvestigationError, match="investigation_scope_denied"):
        tools.read_asset_history(record=record)


def test_live_synthetic_permission_pins_normalized_content_not_project(
    monkeypatch: MonkeyPatch, live_context: tuple[AiInvestigation, SourceInstance]
) -> None:
    record, source = live_context
    _pages(monkeypatch, [{"id": "matching", "ip": "192.0.2.10", "status": "valid"}])
    approved = tools.read_cloudatlas_asset(record=record)
    permission = service.SyntheticPermission(
        project_id=record.project_id,
        run_id=record.run_id,
        resource_id=record.resource_id,
        material_sha256=record.material_sha256,
        sources=[
            service.SyntheticSource.model_validate(source) for source in record.sources
        ],
    )
    monkeypatch.setattr(settings, "AI_INVESTIGATION_ALLOW_BAIZHI_TEST", True)
    monkeypatch.setattr(
        settings,
        "AI_INVESTIGATION_SYNTHETIC_MANIFEST",
        json.dumps([permission.model_dump(mode="json")]),
    )
    monkeypatch.setattr(
        service,
        "load_material",
        lambda **_: (
            {},
            [],
            _binding("https://ai-api-gateway.app.baizhi.cloud/api/openai"),
        ),
    )
    with pytest.raises(service.InvestigationError, match="synthetic_material_denied"):
        tools.read_cloudatlas_asset(record=record)
    assert source.validated_fingerprint is not None
    permission.cloudatlas_reads.append(
        service.SyntheticCloudAtlasReadPermission(
            source_instance_id=source.id,
            instance_id=source.instance_id,
            capset_id=source.capset_id,
            fingerprint=source.validated_fingerprint,
            content_sha256=approved["content_sha256"],
        )
    )
    monkeypatch.setattr(
        settings,
        "AI_INVESTIGATION_SYNTHETIC_MANIFEST",
        json.dumps([permission.model_dump(mode="json")]),
    )
    # A later query/citation identity does not change approved content.
    assert (
        tools.read_cloudatlas_asset(record=record)["content_sha256"]
        == approved["content_sha256"]
    )
    _pages(
        monkeypatch,
        [{"id": "unapproved-upload", "ip": "192.0.2.10", "status": "valid"}],
    )
    with pytest.raises(service.InvestigationError, match="synthetic_material_denied"):
        tools.read_cloudatlas_asset(record=record)
    _pages(monkeypatch, [])
    with pytest.raises(service.InvestigationError, match="synthetic_material_denied"):
        tools.read_cloudatlas_asset(record=record)


def test_history_authorizes_each_material_and_reports_bounded_window(
    monkeypatch: MonkeyPatch,
) -> None:
    record = _record()
    binding = _binding("https://ai-api-gateway.app.baizhi.cloud/api/openai")
    base = GovernanceRun(
        id=record.run_id,
        project_id=record.project_id,
        tenant_id=record.tenant_id,
        completed_at=get_datetime_utc(),
        status="COMPLETED",
    )
    project = Project(id=record.project_id, tenant_id=record.tenant_id)
    session = SimpleNamespace(
        connection=lambda **_: None,
        get=lambda model, _id: project if model is Project else base,
    )
    monkeypatch.setattr(tools, "Session", lambda _: nullcontext(session))
    monkeypatch.setattr(service, "load_material", lambda **_: ({}, [], binding))
    runs = [GovernanceRun(id=uuid.uuid4()) for _ in range(6)]
    monkeypatch.setattr(tools, "_history_runs", lambda *_: runs)

    def material(**kwargs: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        scope = kwargs["scope"]
        return {
            "project_id": str(record.project_id),
            "scope": scope.model_dump(mode="json"),
            "published_at": "2026-09-01T00:00:00+00:00",
            "items": [
                {
                    "citation_id": f"comparison/{scope.run_id}",
                    "fact": {"classification": "MISSING"},
                }
            ],
        }, record.sources

    monkeypatch.setattr(service, "prepare_material", material)
    monkeypatch.setattr(settings, "AI_INVESTIGATION_ALLOW_BAIZHI_TEST", True)
    monkeypatch.setattr(settings, "AI_INVESTIGATION_SYNTHETIC_MANIFEST", "[]")
    with pytest.raises(service.InvestigationError, match="synthetic_material_denied"):
        tools.read_asset_history(record=record)
    permissions = []
    for run in runs[:5]:
        scope = service.InvestigationRequest(
            resource_id=record.resource_id, run_id=run.id
        )
        data, sources = material(scope=scope)
        permissions.append(
            service.SyntheticPermission(
                project_id=record.project_id,
                **scope.model_dump(),
                material_sha256=service.material_hash(data),
                sources=[
                    service.SyntheticSource.model_validate(source) for source in sources
                ],
            ).model_dump(mode="json")
        )
    # One permitted historical Run must not authorize the rest of the project.
    monkeypatch.setattr(
        settings, "AI_INVESTIGATION_SYNTHETIC_MANIFEST", json.dumps(permissions[:1])
    )
    with pytest.raises(service.InvestigationError, match="synthetic_material_denied"):
        tools.read_asset_history(record=record)
    monkeypatch.setattr(
        settings, "AI_INVESTIGATION_SYNTHETIC_MANIFEST", json.dumps(permissions)
    )
    result = tools.read_asset_history(record=record)
    assert [item["fact"]["historical_run_id"] for item in result["items"]] == [
        str(run.id) for run in runs[:5]
    ]
    assert result["truncated"] is True
    assert result["gaps"] == ["history_window_limit"]
    monkeypatch.setattr(tools, "_history_runs", lambda *_: [])
    result = tools.read_asset_history(record=record)
    assert result["items"] == []
    assert result["result"] == "NO_DATA"
    assert result["truncated"] is False


@pytest.mark.parametrize(
    "changed", ["project", "resource", "disabled", "fingerprint", "base_source"]
)
def test_cloudatlas_scope_rejects_unpinned_sources_and_assets(
    monkeypatch: MonkeyPatch, changed: str
) -> None:
    record = _record()
    source = SourceInstance(
        id=uuid.UUID(record.sources[0]["input_id"]),
        project_id=record.project_id,
        tenant_id=record.tenant_id,
        instance_id="fixture-instance",
        capset_id="fixture-capset",
        enabled=True,
        validated_at=get_datetime_utc(),
        validated_fingerprint="c" * 64,
    )
    base = GovernanceRun(
        id=record.run_id,
        project_id=record.project_id,
        tenant_id=record.tenant_id,
        completed_at=get_datetime_utc(),
        status="COMPLETED",
        source_instance_id=source.id,
        cloudatlas_validated_fingerprint="c" * 64,
        cloudatlas_capset_id=source.capset_id,
        cloudatlas_method=METHOD,
    )
    resource = Resource(
        id=record.resource_id,
        project_id=record.project_id,
        tenant_id=record.tenant_id,
        resource_type="IP",
        canonical_key="192.0.2.10",
    )
    if changed == "project":
        source.project_id = uuid.uuid4()
    elif changed == "resource":
        resource.project_id = uuid.uuid4()
    elif changed == "disabled":
        source.enabled = False
    elif changed == "fingerprint":
        source.validated_fingerprint = "d" * 64
    else:
        record.sources[0]["input_id"] = str(uuid.uuid4())
    records = {GovernanceRun: base, Resource: resource, SourceInstance: source}
    session = SimpleNamespace(
        connection=lambda **_: None, get=lambda model, _id: records[model]
    )
    monkeypatch.setattr(tools, "Session", lambda _: nullcontext(session))
    with pytest.raises(service.InvestigationError):
        tools._cloudatlas_scope(record)
