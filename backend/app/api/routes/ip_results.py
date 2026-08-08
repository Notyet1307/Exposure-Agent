from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, SessionDep
from app.api.project_authorization import PROJECT_READ_ROLES, get_authorized_project
from app.domain import ip_results as ip_result_service
from app.domain.models import (
    FindingDetailPublic,
    FindingsPublic,
    IPAssetDetailPublic,
    IPAssetsPublic,
    Project,
)

router = APIRouter(prefix="/projects", tags=["ip-results"])

_FINDING_STATUSES = frozenset({"OPEN", "CLOSED"})


def _read_project(
    *, session: SessionDep, project_id: uuid.UUID, current_user: CurrentUser
) -> Project:
    return get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )


def _validate_status(value: str) -> str:
    normalized = value.upper()
    if normalized not in _FINDING_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "finding_status_invalid",
                "message": "Finding status must be OPEN or CLOSED.",
            },
        )
    return normalized


@router.get(
    "/{project_id}/ip-assets",
    response_model=IPAssetsPublic,
    name="read_ip_assets",
)
def read_ip_assets(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    current_user: CurrentUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> Any:
    project = _read_project(
        session=session,
        project_id=project_id,
        current_user=current_user,
    )
    return ip_result_service.list_ip_assets(
        session=session,
        project=project,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{project_id}/ip-assets/{resource_id}",
    response_model=IPAssetDetailPublic,
    name="read_ip_asset",
)
def read_ip_asset(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    resource_id: uuid.UUID,
    current_user: CurrentUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> Any:
    project = _read_project(
        session=session,
        project_id=project_id,
        current_user=current_user,
    )
    asset = ip_result_service.get_ip_asset(
        session=session,
        project=project,
        resource_id=resource_id,
        skip=skip,
        limit=limit,
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return asset


@router.get(
    "/{project_id}/findings",
    response_model=FindingsPublic,
)
def read_findings(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    current_user: CurrentUser,
    finding_status: Annotated[str, Query(alias="status")] = "OPEN",
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> Any:
    project = _read_project(
        session=session,
        project_id=project_id,
        current_user=current_user,
    )
    return ip_result_service.list_findings(
        session=session,
        project=project,
        status=_validate_status(finding_status),
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{project_id}/findings/{finding_id}",
    response_model=FindingDetailPublic,
)
def read_finding(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    finding_id: uuid.UUID,
    current_user: CurrentUser,
    occurrence_skip: Annotated[int, Query(ge=0)] = 0,
    transition_skip: Annotated[int, Query(ge=0)] = 0,
    trace_limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> Any:
    project = _read_project(
        session=session,
        project_id=project_id,
        current_user=current_user,
    )
    finding = ip_result_service.get_finding_detail(
        session=session,
        project=project,
        finding_id=finding_id,
        occurrence_skip=occurrence_skip,
        transition_skip=transition_skip,
        trace_limit=trace_limit,
    )
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return finding
