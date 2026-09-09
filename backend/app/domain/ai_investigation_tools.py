"""Fixed-asset, read-only supplemental material; never a model query proxy."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.core.time import get_datetime_utc
from app.domain import ai_investigations as service
from app.domain.cloudatlas_sources import (
    METHOD,
    CloudAtlasBoundaryError,
    CloudAtlasMaterialMismatchError,
    OctobusCloudAtlasClient,
)
from app.domain.governance_publication import is_published_run, published_run_predicate
from app.domain.ip_consistency import IPRecordContractError, normalize_ip
from app.domain.model_qualification import ModelBinding
from app.domain.models import (
    AiInvestigation,
    Finding,
    FindingOccurrence,
    FindingTransition,
    GovernanceReport,
    GovernanceRun,
    IPSourceComparisonFact,
    ObservationResourceLink,
    Project,
    Resource,
    SourceInstance,
)

_HISTORY_LIMIT = 5
_PAGE_SIZE = 100
_PAGE_LIMIT = 5


def _scope(record: AiInvestigation) -> service.InvestigationRequest:
    return service.InvestigationRequest(
        resource_id=record.resource_id,
        run_id=record.run_id,
        finding_id=record.finding_id,
    )


def _reauthorize(record: AiInvestigation) -> ModelBinding:
    _material, _sources, binding = service.load_material(
        project_id=record.project_id,
        user_id=record.initiated_by,
        scope=_scope(record),
        record=record,
    )
    return binding


def _readonly(session: Session) -> None:
    session.connection(
        execution_options={
            "isolation_level": "REPEATABLE READ",
            "postgresql_readonly": True,
        }
    )


def _bounded(record: AiInvestigation, result: dict[str, Any]) -> dict[str, Any]:
    if len(service.canonical_bytes(result)) > record.max_material_bytes:
        raise service.InvestigationError("material_limit")
    return result


def _history_runs(
    session: Session, record: AiInvestigation, cutoff: datetime
) -> list[GovernanceRun]:
    # Include legacy observation-backed Runs and closure-only finding events, not
    # just the newer comparison fact projection. EXISTS avoids duplicate Runs.
    membership = [
        select(model.id)
        .where(
            model.governance_run_id == GovernanceRun.id,
            model.project_id == record.project_id,
            model.tenant_id == record.tenant_id,
            model.resource_id == record.resource_id,
        )
        .exists()
        for model in (IPSourceComparisonFact, ObservationResourceLink)
    ]
    membership.extend(
        select(model.id)
        .join(Finding, col(Finding.id) == model.finding_id)
        .where(
            model.governance_run_id == GovernanceRun.id,
            model.project_id == record.project_id,
            model.tenant_id == record.tenant_id,
            Finding.project_id == record.project_id,
            Finding.tenant_id == record.tenant_id,
            Finding.resource_id == record.resource_id,
        )
        .exists()
        for model in (FindingOccurrence, FindingTransition)
    )
    return list(
        session.exec(
            select(GovernanceRun)
            .where(
                GovernanceRun.project_id == record.project_id,
                GovernanceRun.tenant_id == record.tenant_id,
                GovernanceRun.id != record.run_id,
                published_run_predicate(),
                col(GovernanceRun.completed_at) < cutoff,
                or_(*membership),
                select(GovernanceReport.id)
                .where(
                    GovernanceReport.governance_run_id == GovernanceRun.id,
                    GovernanceReport.project_id == record.project_id,
                    GovernanceReport.tenant_id == record.tenant_id,
                )
                .exists(),
            )
            .order_by(
                col(GovernanceRun.completed_at).desc(), col(GovernanceRun.id).desc()
            )
            .limit(_HISTORY_LIMIT + 1)
        ).all()
    )


def read_asset_history(*, record: AiInvestigation) -> dict[str, Any]:
    """Read at most five earlier published materials for the fixed asset."""
    queried_at = get_datetime_utc().isoformat()
    _reauthorize(record)
    try:
        with Session(engine) as session:
            _readonly(session)
            project = session.get(Project, record.project_id)
            base = session.get(GovernanceRun, record.run_id)
            if (
                project is None
                or project.tenant_id != record.tenant_id
                or base is None
                or base.project_id != record.project_id
                or base.tenant_id != record.tenant_id
                or not is_published_run(base)
                or base.completed_at is None
            ):
                raise service.InvestigationError("investigation_scope_denied")
            runs = _history_runs(session, record, base.completed_at)
            items: list[dict[str, Any]] = []
            for run in runs[:_HISTORY_LIMIT]:
                # A current Finding need not have existed in an earlier Run.
                scope = service.InvestigationRequest(
                    resource_id=record.resource_id, run_id=run.id
                )
                material, sources = service.prepare_material(
                    session=session, project=project, scope=scope
                )
                items.append(
                    {
                        "citation_id": f"history/{run.id}/{record.resource_id}",
                        "fact": {
                            "kind": "ASSET_HISTORY",
                            "project_id": str(record.project_id),
                            "resource_id": str(record.resource_id),
                            "run_id": str(record.run_id),
                            "historical_run_id": str(run.id),
                            "published_at": material["published_at"],
                            "sources": sources,
                            "material": material,
                        },
                    }
                )
            result = {
                "project_id": str(record.project_id),
                "resource_id": str(record.resource_id),
                "run_id": str(record.run_id),
                "before": base.completed_at.isoformat(),
                "queried_at": queried_at,
                "completed_at": get_datetime_utc().isoformat(),
                "result": "FOUND" if items else "NO_DATA",
                "truncated": len(runs) > _HISTORY_LIMIT,
                "gaps": ["history_window_limit"]
                if len(runs) > _HISTORY_LIMIT
                else ([] if items else ["no_published_asset_history"]),
                "items": items,
            }
    except SQLAlchemyError:
        raise service.InvestigationError("history_read_failed") from None
    binding = _reauthorize(record)
    for item in items:
        fact = item["fact"]
        service.authorize_material(
            binding=binding,
            project_id=record.project_id,
            scope=service.InvestigationRequest.model_validate(
                fact["material"]["scope"]
            ),
            material=fact["material"],
            sources=fact["sources"],
        )
    return _bounded(record, result)


def _cloudatlas_scope(record: AiInvestigation) -> tuple[SourceInstance, str, str]:
    with Session(engine) as session:
        _readonly(session)
        base = session.get(GovernanceRun, record.run_id)
        resource = session.get(Resource, record.resource_id)
        if (
            base is None
            or base.project_id != record.project_id
            or base.tenant_id != record.tenant_id
            or not is_published_run(base)
            or base.completed_at is None
            or resource is None
            or resource.project_id != record.project_id
            or resource.tenant_id != record.tenant_id
            or resource.resource_type != "IP"
        ):
            raise service.InvestigationError("investigation_scope_denied")
        source = session.get(SourceInstance, base.source_instance_id)
        if (
            source is None
            or source.project_id != record.project_id
            or source.tenant_id != record.tenant_id
            or source.source_type != "cloudatlas"
            or not source.enabled
            or source.validated_at is None
            or source.validation_error_code is not None
            or source.validated_fingerprint is None
        ):
            raise service.InvestigationError("cloudatlas_source_unavailable")
        if (
            source.validated_fingerprint != base.cloudatlas_validated_fingerprint
            or source.capset_id != base.cloudatlas_capset_id
            or base.cloudatlas_method != METHOD
            or not any(
                item.get("source_type") == "CLOUDATLAS"
                and item.get("input_id") == str(source.id)
                for item in record.sources
            )
        ):
            raise service.InvestigationError("cloudatlas_material_changed")
        return (
            source,
            normalize_ip(str(resource.canonical_key)),
            base.completed_at.isoformat(),
        )


def _matching_assets(
    client: OctobusCloudAtlasClient, source: SourceInstance, canonical_ip: str
) -> list[dict[str, str]]:
    token = settings.CLOUDATLAS_CAPSET_TOKEN.get_secret_value()
    if not token:
        raise service.InvestigationError("cloudatlas_source_unavailable")
    expected_total = None
    seen_ids: set[str] = set()
    matched = []
    for page in range(1, _PAGE_LIMIT + 1):
        payload = client.list_ip_assets_page(
            source, capset_token=token, page=page, size=_PAGE_SIZE
        )
        if not isinstance(payload, dict) or set(payload) != {
            "items",
            "page",
            "size",
            "total",
        }:
            raise service.InvestigationError("cloudatlas_response_contract_failed")
        total, items = payload["total"], payload["items"]
        if (
            type(payload["page"]) is not int
            or payload["page"] != page
            or type(payload["size"]) is not int
            or payload["size"] != _PAGE_SIZE
            or type(total) is not int
            or total < 0
            or not isinstance(items, list)
        ):
            raise service.InvestigationError("cloudatlas_response_contract_failed")
        if total > _PAGE_SIZE * _PAGE_LIMIT:
            raise service.InvestigationError("cloudatlas_read_limit")
        if expected_total is None:
            expected_total = total
        if total != expected_total or len(items) != min(
            _PAGE_SIZE, total - len(seen_ids)
        ):
            raise service.InvestigationError("cloudatlas_response_contract_failed")
        for item in items:
            if (
                not isinstance(item, dict)
                or set(item) != {"id", "ip", "status"}
                or not isinstance(item["id"], str)
                or not 1 <= len(item["id"]) <= 255
                or not item["id"].strip()
                or item["id"] in seen_ids
                or not isinstance(item["ip"], str)
                or not 1 <= len(item["ip"]) <= 64
                or item["status"] != "valid"
            ):
                raise service.InvestigationError("cloudatlas_response_contract_failed")
            try:
                ip = normalize_ip(item["ip"])
            except IPRecordContractError:
                raise service.InvestigationError(
                    "cloudatlas_response_contract_failed"
                ) from None
            seen_ids.add(item["id"])
            if ip == canonical_ip:
                matched.append({"id": item["id"], "ip": ip, "status": "valid"})
        if len(seen_ids) == total:
            return sorted(matched, key=lambda item: item["id"])
    raise service.InvestigationError("cloudatlas_read_limit")


def read_cloudatlas_asset(*, record: AiInvestigation) -> dict[str, Any]:
    """Read only the pinned CloudAtlas source; return matching normalized IPs."""
    queried_at = get_datetime_utc().isoformat()
    _reauthorize(record)
    try:
        source, canonical_ip, published_at = _cloudatlas_scope(record)
        client = OctobusCloudAtlasClient()
        if client.current_fingerprint(source).value != source.validated_fingerprint:
            raise service.InvestigationError("cloudatlas_material_changed")
        assets = _matching_assets(client, source, canonical_ip)
        if client.current_fingerprint(source).value != source.validated_fingerprint:
            raise service.InvestigationError("cloudatlas_material_changed")
        binding = _reauthorize(record)
        current, current_ip, current_published_at = _cloudatlas_scope(record)
        if (
            current.id != source.id
            or current.instance_id != source.instance_id
            or current.capset_id != source.capset_id
            or current.validated_fingerprint != source.validated_fingerprint
            or current_ip != canonical_ip
            or current_published_at != published_at
        ):
            raise service.InvestigationError("cloudatlas_material_changed")
        content = {
            "schema": "ai-cloudatlas-asset/v1",
            "project_id": str(record.project_id),
            "resource_id": str(record.resource_id),
            "run_id": str(record.run_id),
            "base_published_at": published_at,
            "source": {
                "source_type": "CLOUDATLAS",
                "source_instance_id": str(source.id),
                "instance_id": source.instance_id,
                "capset_id": source.capset_id,
                "method": METHOD,
                "fingerprint": source.validated_fingerprint,
            },
            "canonical_ip": canonical_ip,
            "result": "FOUND" if assets else "NO_DATA",
            "assets": assets,
        }
        digest = service.authorize_cloudatlas(
            record=record, binding=binding, content=content
        )
    except CloudAtlasMaterialMismatchError:
        raise service.InvestigationError("cloudatlas_material_changed") from None
    except CloudAtlasBoundaryError as exc:
        raise service.InvestigationError(exc.code) from None
    except SQLAlchemyError:
        raise service.InvestigationError("cloudatlas_read_failed") from None
    except IPRecordContractError:
        raise service.InvestigationError("investigation_material_invalid") from None
    times = {"queried_at": queried_at, "completed_at": get_datetime_utc().isoformat()}
    return _bounded(
        record,
        {
            **{key: value for key, value in content.items() if key != "assets"},
            **times,
            "content_sha256": digest,
            "truncated": False,
            "gaps": [] if assets else ["cloudatlas_asset_not_found"],
            "items": [
                {
                    "citation_id": f"cloudatlas/{uuid.uuid4()}",
                    "fact": {**content, **times},
                }
            ]
            if assets
            else [],
        },
    )
