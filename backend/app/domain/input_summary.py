"""Read-only input summary over existing readiness, source and NetFlow owners."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, func, select

from app.domain import comparison_results, external_assets, netflow_processing
from app.domain.models import CustomerUpload, NetFlowDataset, Project
from app.models import User

logger = logging.getLogger(__name__)

CONTRACT_VERSION: Literal["input-summary-v1"] = "input-summary-v1"
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class CustomerSummary(BaseModel):
    applied_upload_id: uuid.UUID | None
    applied_revision_id: uuid.UUID | None
    accepted_upload_count: int
    unapplied_upload_count: int


class CloudSourceFact(BaseModel):
    source_instance_id: uuid.UUID
    instance_id: str
    space_id: str | None
    enabled: bool
    data_access_enabled: bool
    validation_status: str


class CloudSummary(BaseModel):
    sources: list[CloudSourceFact]


class NetFlowScopeFact(BaseModel):
    scope_id: str
    network_namespace: str
    collection_scope: str | None
    label: str


class NetFlowBase(BaseModel):
    dataset_count: int | None
    current_dataset_id: uuid.UUID | None


class NetFlowRead(NetFlowBase):
    read_state: Literal["READ"] = "READ"
    scope_id: str | None
    scopes: list[NetFlowScopeFact]
    current_analysis_id: uuid.UUID | None
    latest_attempt_status: str | None
    latest_attempt_error_code: str | None


class NetFlowReadFailed(NetFlowBase):
    read_state: Literal["READ_FAILED"] = "READ_FAILED"
    error_status: int | None
    error_code: str


NetFlowSummary = Annotated[NetFlowRead | NetFlowReadFailed, Field(discriminator="read_state")]


class InputSummary(BaseModel):
    contract_version: Literal["input-summary-v1"] = CONTRACT_VERSION
    project_id: uuid.UUID
    customer: CustomerSummary
    cloud: CloudSummary
    core_readiness: comparison_results.Readiness
    netflow: NetFlowSummary


def _safe_code(error: HTTPException) -> str:
    if isinstance(error.detail, dict):
        value = error.detail.get("code")
        if isinstance(value, str) and _SAFE_CODE.fullmatch(value):
            return value
    return "netflow_read_failed"


def _customer(session: Session, project: Project) -> CustomerSummary:
    scope = (
        CustomerUpload.project_id == project.id,
        CustomerUpload.tenant_id == project.tenant_id,
    )
    accepted = session.exec(
        select(func.count()).select_from(CustomerUpload).where(*scope)
    ).one()
    applied = 0
    if project.current_customer_upload_id is not None:
        applied = session.exec(
            select(func.count())
            .select_from(CustomerUpload)
            .where(*scope, CustomerUpload.id == project.current_customer_upload_id)
        ).one()
    return CustomerSummary(
        applied_upload_id=project.current_customer_upload_id,
        applied_revision_id=project.current_customer_ledger_revision_id,
        accepted_upload_count=accepted,
        unapplied_upload_count=accepted - applied,
    )


def _cloud(session: Session, project: Project) -> CloudSummary:
    facts = []
    for source in comparison_results.assets_v1_sources(session, project):
        public = external_assets.source_public(source)
        facts.append(
            CloudSourceFact(
                source_instance_id=public.id,
                instance_id=public.instance_id,
                space_id=public.space_id or None,
                enabled=public.enabled,
                data_access_enabled=public.data_access_enabled,
                validation_status=public.validation_status,
            )
        )
    return CloudSummary(sources=facts)


def _netflow(session: Session, project: Project) -> NetFlowSummary:
    scope = (
        NetFlowDataset.project_id == project.id,
        NetFlowDataset.tenant_id == project.tenant_id,
    )
    try:
        dataset_count = session.exec(
            select(func.count()).select_from(NetFlowDataset).where(*scope)
        ).one()
    except Exception:
        logger.warning("Input summary could not count optional NetFlow datasets")
        return NetFlowReadFailed(
            dataset_count=None,
            current_dataset_id=project.current_netflow_dataset_id,
            error_status=None,
            error_code="netflow_summary_unavailable",
        )
    try:
        value = netflow_processing.current_netflow(session, project)
    except HTTPException as error:
        return NetFlowReadFailed(
            dataset_count=dataset_count,
            current_dataset_id=project.current_netflow_dataset_id,
            error_status=error.status_code,
            error_code=_safe_code(error),
        )
    except Exception:
        logger.warning("Input summary could not read optional NetFlow state")
        return NetFlowReadFailed(
            dataset_count=dataset_count,
            current_dataset_id=project.current_netflow_dataset_id,
            error_status=None,
            error_code="netflow_summary_unavailable",
        )
    return NetFlowRead(
        dataset_count=dataset_count,
        current_dataset_id=project.current_netflow_dataset_id,
        scope_id=value.scope_id,
        scopes=[
            NetFlowScopeFact(
                scope_id=scope_id.scope_id,
                network_namespace=scope_id.network_namespace,
                collection_scope=scope_id.collection_scope,
                label=scope_id.label,
            )
            for scope_id in value.scopes
        ],
        current_analysis_id=value.current.analysis_id if value.current else None,
        latest_attempt_status=value.latest_attempt.status
        if value.latest_attempt
        else None,
        latest_attempt_error_code=value.latest_attempt.error_code
        if value.latest_attempt
        else None,
    )


def compose(session: Session, project: Project, actor: User) -> InputSummary:
    customer = _customer(session, project)
    cloud = _cloud(session, project)
    readiness = comparison_results.readiness_safely(
        session, project, actor, base=None
    )
    netflow = _netflow(session, project)
    return InputSummary(
        project_id=project.id,
        customer=customer,
        cloud=cloud,
        core_readiness=readiness,
        netflow=netflow,
    )
