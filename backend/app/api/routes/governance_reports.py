import hashlib
import os
import stat
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, BinaryIO

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select
from starlette.responses import StreamingResponse

from app.api.deps import CurrentUser, SessionDep
from app.api.project_authorization import PROJECT_READ_ROLES, get_authorized_project
from app.core.config import settings
from app.domain import governance_reports as report_service
from app.domain.models import (
    Artifact,
    AuditEvent,
    GovernanceReport,
    GovernanceReportDetailPublic,
    GovernanceReportsPublic,
    ProjectRole,
)

router = APIRouter(prefix="/projects", tags=["governance-reports"])

_CSV_MEDIA_TYPE = "text/csv"
_STREAM_CHUNK_SIZE = 64 * 1024


class ReportCSVArtifactError(Exception):
    pass


def _report_artifact_path(artifact: Artifact) -> Path:
    relative = Path(artifact.storage_key)
    if (
        len(relative.parts) != 2
        or relative.parts[0] != "report_candidates"
        or relative.suffix != ".csv"
    ):
        raise ReportCSVArtifactError
    try:
        uuid.UUID(relative.stem)
        root = settings.ARTIFACT_ROOT.resolve()
        path = (root / relative).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise ReportCSVArtifactError from None
    if root not in path.parents:
        raise ReportCSVArtifactError
    return path


def _open_verified_csv(*, report: GovernanceReport, artifact: Artifact) -> BinaryIO:
    if (
        artifact.media_type != _CSV_MEDIA_TYPE
        or artifact.sha256 != report.csv_sha256
        or artifact.byte_size <= 0
    ):
        raise ReportCSVArtifactError
    try:
        source = _report_artifact_path(artifact).open("rb")
    except OSError:
        raise ReportCSVArtifactError from None
    try:
        # fstat verifies the opened object, rather than trusting path metadata.
        opened_stat = os.fstat(source.fileno())
        is_regular_file = stat.S_ISREG(opened_stat.st_mode)
        digest = hashlib.sha256()
        byte_size = 0
        while chunk := source.read(_STREAM_CHUNK_SIZE):
            digest.update(chunk)
            byte_size += len(chunk)
        if (
            not is_regular_file
            or opened_stat.st_size != artifact.byte_size
            or byte_size != artifact.byte_size
            or digest.hexdigest() != report.csv_sha256
        ):
            raise ReportCSVArtifactError
        source.seek(0)
        return source
    except (OSError, ReportCSVArtifactError):
        source.close()
        raise ReportCSVArtifactError from None


def _stream_open_file(source: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := source.read(_STREAM_CHUNK_SIZE):
            yield chunk
    finally:
        source.close()


@router.get(
    "/{project_id}/governance-reports",
    response_model=GovernanceReportsPublic,
)
def read_governance_reports(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    current_user: CurrentUser,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=report_service.REPORT_LIST_MAX_PAGE_SIZE,
        ),
    ] = report_service.REPORT_LIST_DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
) -> GovernanceReportsPublic:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    try:
        decoded_cursor = (
            report_service.decode_report_cursor(cursor) if cursor is not None else None
        )
    except report_service.ReportCursorError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "report_cursor_invalid",
                "message": "The report page cursor is invalid.",
            },
        ) from None
    return report_service.list_reports(
        session=session,
        project=project,
        limit=limit,
        cursor=decoded_cursor,
    )


@router.get(
    "/{project_id}/governance-reports/{report_id}",
    response_model=GovernanceReportDetailPublic,
)
def read_governance_report(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    current_user: CurrentUser,
) -> GovernanceReportDetailPublic:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
    )
    report = report_service.get_report(
        session=session,
        project=project,
        report_id=report_id,
    )
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return report


@router.get(
    "/{project_id}/governance-reports/{report_id}/csv",
    response_class=StreamingResponse,
)
def download_governance_report_csv(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    current_user: CurrentUser,
) -> StreamingResponse:
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=(ProjectRole.OPERATOR,),
    )
    report = session.exec(
        select(GovernanceReport).where(
            GovernanceReport.id == report_id,
            GovernanceReport.project_id == project.id,
            GovernanceReport.tenant_id == project.tenant_id,
        )
    ).one_or_none()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    artifact = session.exec(
        select(Artifact).where(
            Artifact.id == report.csv_artifact_id,
            Artifact.governance_run_id == report.governance_run_id,
            Artifact.project_id == project.id,
            Artifact.tenant_id == project.tenant_id,
            Artifact.sha256 == report.csv_sha256,
        )
    ).one_or_none()
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    try:
        source = _open_verified_csv(report=report, artifact=artifact)
    except ReportCSVArtifactError:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR) from None
    filename = f"governance-report-{report.id}-run-{report.governance_run_id}.csv"
    byte_size = artifact.byte_size

    session.add(
        AuditEvent(
            tenant_id=project.tenant_id,
            project_id=project.id,
            actor_subject=str(current_user.id),
            actor_type="user",
            action="governance_report.csv_download_started",
            target_type="governance_report",
            target_id=report.id,
            after_data={"artifact_sha256": report.csv_sha256},
        )
    )
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        source.close()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR) from None

    return StreamingResponse(
        _stream_open_file(source),
        media_type=_CSV_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(byte_size),
        },
    )
