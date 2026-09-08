from __future__ import annotations

import uuid
from collections.abc import Generator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.api.deps import CurrentUser, SessionDep, TokenDep, get_current_user
from app.api.project_authorization import PROJECT_READ_ROLES, get_authorized_project
from app.core.db import engine
from app.domain import ip_results as ip_result_service
from app.domain.governance_publication import is_published_run
from app.domain.ip_consistency import (
    IP_PROCESSING_CONTRACT_VERSION,
    IPRecordContractError,
)
from app.domain.ip_source_comparison import (
    IPSourceComparisonError,
)
from app.domain.ip_source_comparison import (
    list_governance_run_ip_source_comparisons as list_published_run_comparisons,
)
from app.domain.ip_source_comparison import (
    read_governance_run_sources as read_published_run_sources,
)
from app.domain.lineage import (
    read_governance_run_lineage as read_published_run_lineage,
)
from app.domain.models import (
    FindingDetailPublic,
    FindingsPublic,
    GovernanceRun,
    GovernanceRunLineagePublic,
    GovernanceRunSourcesPublic,
    IPAssetDetailPublic,
    IPAssetsPublic,
    IPSourceComparisonsPublic,
    Project,
)
from app.domain.report_candidates import REPORT_V2_CONTRACT_VERSION
from app.domain.report_comparison_evidence import ReportComparisonEvidenceError

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


def _run_result_error(
    *,
    error: IPSourceComparisonError,
    session: Session,
    project: Project,
    run_id: uuid.UUID,
) -> HTTPException:
    if error.code == "comparison_contract_unsupported":
        with session.no_autoflush:
            run = session.exec(
                select(GovernanceRun).where(
                    GovernanceRun.id == run_id,
                    GovernanceRun.project_id == project.id,
                    GovernanceRun.tenant_id == project.tenant_id,
                )
            ).one_or_none()
        # Only v2 requires this receipt; pre-cutover v1 may lack it by design.
        if (
            run is not None
            and is_published_run(run)
            and run.input_contract_version == "governance-run-input-v1"
            and run.processing_contract_version == IP_PROCESSING_CONTRACT_VERSION
            and run.report_contract_version == REPORT_V2_CONTRACT_VERSION
        ):
            return HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Run result integrity verification failed",
            )
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if error.code in {"run_not_found", "run_not_published"}:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Run result integrity verification failed",
    )


@router.get(
    "/{project_id}/governance-runs/{governance_run_id}/sources",
    response_model=GovernanceRunSourcesPublic,
)
def read_governance_run_sources(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    governance_run_id: uuid.UUID,
    current_user: CurrentUser,
) -> GovernanceRunSourcesPublic:
    project = _read_project(
        session=session,
        project_id=project_id,
        current_user=current_user,
    )
    try:
        return read_published_run_sources(
            session=session, project=project, run_id=governance_run_id
        )
    except IPSourceComparisonError as error:
        raise _run_result_error(
            error=error,
            session=session,
            project=project,
            run_id=governance_run_id,
        ) from None
    except (
        ReportComparisonEvidenceError,
        IPRecordContractError,
        SQLAlchemyError,
        ValueError,
        TypeError,
        KeyError,
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Run result integrity verification failed",
        ) from None


@router.get(
    "/{project_id}/governance-runs/{governance_run_id}/ip-source-comparisons",
    response_model=IPSourceComparisonsPublic,
)
def read_governance_run_ip_source_comparisons(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    governance_run_id: uuid.UUID,
    current_user: CurrentUser,
    classification: Annotated[
        Literal[
            "matched",
            "customer_upload_only",
            "cloudatlas_only",
            "neither_source_observed",
        ]
        | None,
        Query(),
    ] = None,
    netflow_status: Annotated[Literal["ACTIVE", "UNKNOWN"] | None, Query()] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> IPSourceComparisonsPublic:
    project = _read_project(
        session=session,
        project_id=project_id,
        current_user=current_user,
    )
    try:
        return list_published_run_comparisons(
            session=session,
            project=project,
            run_id=governance_run_id,
            classification=classification,
            netflow_status=netflow_status,
            skip=skip,
            limit=limit,
        )
    except IPSourceComparisonError as error:
        raise _run_result_error(
            error=error,
            session=session,
            project=project,
            run_id=governance_run_id,
        ) from None
    except (
        ReportComparisonEvidenceError,
        IPRecordContractError,
        SQLAlchemyError,
        ValueError,
        TypeError,
        KeyError,
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Run result integrity verification failed",
        ) from None


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


def _finding_read_session() -> Generator[Session]:
    # Authentication and every detail query share a fresh identity map and snapshot.
    with Session(engine) as session:
        session.connection(
            execution_options={
                "isolation_level": "REPEATABLE READ",
                "postgresql_readonly": True,
            }
        )
        yield session


@router.get(
    "/{project_id}/governance-runs/{governance_run_id}/lineage",
    response_model=GovernanceRunLineagePublic,
    response_model_by_alias=True,
)
def read_governance_run_lineage(
    *,
    session: Annotated[Session, Depends(_finding_read_session)],
    project_id: uuid.UUID,
    governance_run_id: uuid.UUID,
    token: TokenDep,
    response: Response,
    resource_id: Annotated[uuid.UUID | None, Query()] = None,
) -> GovernanceRunLineagePublic:
    current_user = get_current_user(session=session, token=token)
    project = _read_project(
        session=session,
        project_id=project_id,
        current_user=current_user,
    )
    try:
        lineage = read_published_run_lineage(
            session=session,
            project=project,
            run_id=governance_run_id,
            resource_id=resource_id,
        )
    except IPSourceComparisonError as error:
        if error.code == "lineage_resource_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
        raise _run_result_error(
            error=error,
            session=session,
            project=project,
            run_id=governance_run_id,
        ) from None
    except (
        ReportComparisonEvidenceError,
        IPRecordContractError,
        SQLAlchemyError,
        ValueError,
        TypeError,
        KeyError,
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Run result integrity verification failed",
        ) from None
    response.headers["Cache-Control"] = "private, no-store"
    return lineage


@router.get(
    "/{project_id}/findings/{finding_id}",
    response_model=FindingDetailPublic,
)
def read_finding(
    *,
    session: Annotated[Session, Depends(_finding_read_session)],
    project_id: uuid.UUID,
    finding_id: uuid.UUID,
    token: TokenDep,
    occurrence_skip: Annotated[int, Query(ge=0)] = 0,
    transition_skip: Annotated[int, Query(ge=0)] = 0,
    trace_limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> Any:
    current_user = get_current_user(session=session, token=token)
    project = _read_project(
        session=session,
        project_id=project_id,
        current_user=current_user,
    )
    try:
        finding = ip_result_service.get_finding_detail(
            session=session,
            project=project,
            finding_id=finding_id,
            occurrence_skip=occurrence_skip,
            transition_skip=transition_skip,
            trace_limit=trace_limit,
        )
    except IPSourceComparisonError, IPRecordContractError, ValueError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal Server Error",
        ) from None
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return finding
