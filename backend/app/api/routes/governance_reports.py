import hashlib
import os
import stat
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated, BinaryIO

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select
from starlette.responses import StreamingResponse

from app.api.deps import CurrentUser, SessionDep
from app.api.project_authorization import (
    PROJECT_READ_ROLES,
    get_authorized_project,
    project_access_filter,
)
from app.core.config import settings
from app.domain import ai_governance_drafts as draft_service
from app.domain import governance_reports as report_service
from app.domain.model_qualification import (
    ModelBinding,
    current_model_is_qualified,
    model_binding,
)
from app.domain.models import (
    AiGovernanceDraft,
    AiGovernanceDraftPublic,
    AiGovernanceDraftRequest,
    Artifact,
    AuditEvent,
    GovernanceReport,
    GovernanceReportDetailPublic,
    GovernanceReportsPublic,
    Project,
    ProjectRole,
)
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
    AgentComposeRunStart,
)

router = APIRouter(prefix="/projects", tags=["governance-reports"])

_CSV_MEDIA_TYPE = "text/csv"
_STREAM_CHUNK_SIZE = 64 * 1024

_DRAFT_ERROR_MESSAGES = {
    "draft_idempotency_key_required": "Provide a stable Idempotency-Key.",
    "draft_idempotency_conflict": (
        "The Idempotency-Key is already bound to another governance report."
    ),
    "draft_generation_active": "This report already has an active draft generation.",
    "draft_generation_after_failure_not_supported": (
        "A new draft attempt after failure is not available in this release."
    ),
    "draft_project_archived": "This Project is archived and read-only.",
    "report_not_found": "The governance report was not found.",
    "report_not_published": "The governance report is not published.",
    "finding_not_selected": "Every selected Finding must be eligible in this report.",
    "evidence_not_bound": "A selected Finding has no matching persisted Evidence.",
    "invalid_bindings": "Select between one and eight distinct eligible Findings.",
    "report_evidence_plan_invalid": "The published report Evidence plan is invalid.",
    "model_not_qualified": "The current model is not qualified for draft generation.",
    "agent_compose_unavailable": "The draft Session control plane is unavailable.",
    "agent_compose_start_failed": "The draft Session could not be started.",
    "agent_compose_session_pending": (
        "The draft Run was accepted; its Session identity is not visible yet."
    ),
    "agent_compose_run_status_unknown": (
        "The draft Run status is not yet recognized; retry with the same "
        "Idempotency-Key."
    ),
    "agent_compose_response_contract_failed": (
        "The draft Session control plane returned an invalid response."
    ),
}


class ModelBindingChangedError(Exception):
    """The immutable draft binding no longer matches deployment configuration."""


class ReportCSVArtifactError(Exception):
    pass


def _idempotency_key(value: str | None) -> str:
    if (
        value is None
        or not value.strip()
        or value != value.strip()
        or len(value) > 255
        or any(ord(character) < 32 for character in value)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "draft_idempotency_key_required",
                "message": _DRAFT_ERROR_MESSAGES["draft_idempotency_key_required"],
            },
        )
    return value


def _draft_state_error(
    error: draft_service.AiGovernanceDraftStateError,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": error.code,
            "message": _DRAFT_ERROR_MESSAGES.get(
                error.code, "Draft generation failed."
            ),
        },
    )


def _agent_compose_error(error: AgentComposeBoundaryError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": error.code,
            "message": _DRAFT_ERROR_MESSAGES.get(
                error.code, "The draft Session control plane failed."
            ),
        },
    )


def _draft_client_request_id(draft: AiGovernanceDraft) -> str:
    return f"ai-governance-draft:{draft.id}"


def _require_current_model_binding(
    *,
    session: SessionDep,
    draft: AiGovernanceDraft | None = None,
) -> ModelBinding:
    try:
        if not settings.MODEL_API_KEY.get_secret_value():
            raise ValueError("model_configuration_invalid")
        binding = model_binding(
            endpoint=settings.MODEL_API_ENDPOINT,
            model_identity=settings.MODEL_IDENTITY,
            protocol=settings.MODEL_API_PROTOCOL,
            config_revision=settings.MODEL_CONFIG_REVISION,
            runner_build_version=settings.RUNNER_BUILD_VERSION,
            agent_compose_runtime_version=settings.AGENT_COMPOSE_RUNTIME_VERSION,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "model_not_qualified",
                "message": _DRAFT_ERROR_MESSAGES["model_not_qualified"],
            },
        ) from None
    if draft is not None and (
        binding.model_identity != draft.model_identity
        or binding.config_fingerprint != draft.config_fingerprint
    ):
        raise ModelBindingChangedError
    if not current_model_is_qualified(
        session=session,
        endpoint=binding.endpoint,
        model_identity=binding.model_identity,
        config_fingerprint=binding.config_fingerprint,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "model_not_qualified",
                "message": _DRAFT_ERROR_MESSAGES["model_not_qualified"],
            },
        )
    return binding


def _start_draft_or_recover_response(
    *,
    client: AgentComposeClient,
    draft: AiGovernanceDraft,
    client_request_id: str,
    run_id: str,
) -> AgentComposeRunStart:
    try:
        return client.start_ai_governance_draft(
            client_request_id=client_request_id,
            draft_id=str(draft.id),
        )
    except AgentComposeBoundaryError as start_error:
        observed = client.get_run(run_id)
        if observed is None:
            raise start_error
        return observed


def _launch_or_reconcile_draft_session(
    *,
    session: SessionDep,
    draft: AiGovernanceDraft,
    launch_now: bool,
    authorize_start: Callable[[], object],
) -> AiGovernanceDraft:
    if draft.status != "GENERATING":
        return draft

    # Once the dedicated Session is durably bound, the idempotency contract is
    # complete: return that persisted generation identity without consulting
    # the mutable control-plane configuration again. Execution and
    # terminal-output reconciliation are deliberately outside this
    # request-creation endpoint's scope.
    if draft.session_id is not None:
        return draft

    client = AgentComposeClient()
    client_request_id = _draft_client_request_id(draft)
    expected_run_id = client.expected_ai_governance_draft_run_id(client_request_id)
    if draft.agent_compose_run_id is not None and (
        draft.agent_compose_run_id != expected_run_id
    ):
        raise AgentComposeBoundaryError("agent_compose_response_contract_failed")

    reserved = draft
    observed: AgentComposeRunStart | None = None
    reserved = draft_service.reserve_draft_run_identity(
        session=session,
        draft=draft,
        agent_compose_run_id=expected_run_id,
    )
    # Reservation commits to release the Project lock.  Re-read and lock the
    # draft again through reconciliation so a concurrent same-key replay sees
    # the authoritative binding or terminal result before contacting the
    # control plane, and cannot lose a later transition race.
    reserved = draft_service.lock_draft_for_session_reconciliation(
        session=session,
        draft=reserved,
        agent_compose_run_id=expected_run_id,
    )
    if reserved.status != "GENERATING" or reserved.session_id is not None:
        return reserved
    if observed is None and not launch_now:
        observed = client.get_run(expected_run_id)
    if observed is None:
        # A missing Run means this request would create a new Session. Recheck
        # the persisted model binding and latest qualification at that boundary.
        try:
            authorize_start()
        except ModelBindingChangedError:
            return draft_service.fail_draft(
                session=session,
                draft=reserved,
                failure_code="model_binding_changed",
                actor_subject="agent-compose-control-plane",
            )
        # Qualification is a database read.  Do not carry its transaction into
        # agent-compose: the control plane may synchronously persist this
        # Session through a separate connection before returning its response.
        session.commit()
        observed = _start_draft_or_recover_response(
            client=client,
            draft=reserved,
            client_request_id=client_request_id,
            run_id=expected_run_id,
        )
    if observed.run_id != expected_run_id:
        raise AgentComposeBoundaryError("agent_compose_response_contract_failed")
    if not observed.is_terminal and not observed.is_active:
        # An unknown status can be a newer active control-plane state.  The
        # deterministic Run identity is already reserved, so leave this draft
        # recoverable and reconcile that exact Run on the next replay.
        raise AgentComposeBoundaryError("agent_compose_run_status_unknown")
    if observed.session_id is None and not observed.is_terminal:
        refreshed = client.get_run(expected_run_id)
        if refreshed is not None:
            observed = refreshed
            if observed.run_id != expected_run_id:
                raise AgentComposeBoundaryError(
                    "agent_compose_response_contract_failed"
                )
            if not observed.is_terminal and not observed.is_active:
                raise AgentComposeBoundaryError("agent_compose_run_status_unknown")
    if observed.is_terminal and (not observed.succeeded or observed.session_id is None):
        failure_binding = (
            {
                "agent_compose_run_id": expected_run_id,
                "session_id": observed.session_id,
            }
            if observed.session_id is not None
            else {}
        )
        return draft_service.fail_draft(
            session=session,
            draft=reserved,
            failure_code="agent_compose_run_failed",
            actor_subject="agent-compose-control-plane",
            **failure_binding,
        )
    if observed.session_id is None:
        raise AgentComposeBoundaryError("agent_compose_session_pending")
    return draft_service.bind_draft_session(
        session=session,
        draft=reserved,
        agent_compose_run_id=expected_run_id,
        session_id=observed.session_id,
    )


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
    except OSError, RuntimeError, ValueError:
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
    except OSError, ReportCSVArtifactError:
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
    can_request_ai_governance_draft = project.archived_at is None and (
        session.exec(
            select(Project.id).where(
                Project.id == project.id,
                Project.tenant_id == project.tenant_id,
                project_access_filter(
                    user=current_user, allowed_roles=(ProjectRole.OPERATOR,)
                ),
            )
        ).first()
        is not None
    )
    report = report_service.get_report(
        session=session,
        project=project,
        report_id=report_id,
        can_request_ai_governance_draft=can_request_ai_governance_draft,
    )
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return report


@router.post(
    "/{project_id}/governance-reports/{report_id}/ai-governance-drafts",
    response_model=AiGovernanceDraftPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_ai_governance_draft(
    *,
    session: SessionDep,
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    request_body: AiGovernanceDraftRequest,
    current_user: CurrentUser,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> AiGovernanceDraftPublic:
    key = _idempotency_key(idempotency_key)
    project = get_authorized_project(
        session=session,
        user=current_user,
        project_id=project_id,
        allowed_roles=(ProjectRole.OPERATOR,),
        writable=True,
        lock=True,
    )
    existing = session.exec(
        select(AiGovernanceDraft).where(
            AiGovernanceDraft.tenant_id == project.tenant_id,
            AiGovernanceDraft.project_id == project.id,
            AiGovernanceDraft.idempotency_key == key,
        )
    ).one_or_none()
    if existing is not None:
        if existing.governance_report_id != report_id:
            raise _draft_state_error(
                draft_service.AiGovernanceDraftStateError("draft_idempotency_conflict")
            )
        try:
            existing = _launch_or_reconcile_draft_session(
                session=session,
                draft=existing,
                launch_now=False,
                authorize_start=lambda: _require_current_model_binding(
                    session=session, draft=existing
                ),
            )
        except AgentComposeBoundaryError as error:
            raise _agent_compose_error(error) from None
        except draft_service.AiGovernanceDraftStateError as error:
            raise _draft_state_error(error) from None
        response.status_code = status.HTTP_200_OK
        return report_service.ai_governance_draft_public(
            session=session, draft=existing
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
    failed_draft = session.exec(
        select(AiGovernanceDraft.id).where(
            AiGovernanceDraft.tenant_id == project.tenant_id,
            AiGovernanceDraft.project_id == project.id,
            AiGovernanceDraft.governance_report_id == report.id,
            AiGovernanceDraft.status == "FAILED",
        )
    ).first()
    if failed_draft is not None:
        raise _draft_state_error(
            draft_service.AiGovernanceDraftStateError(
                "draft_generation_after_failure_not_supported"
            )
        )
    active_draft = session.exec(
        select(AiGovernanceDraft.id).where(
            AiGovernanceDraft.tenant_id == project.tenant_id,
            AiGovernanceDraft.project_id == project.id,
            AiGovernanceDraft.governance_report_id == report.id,
            AiGovernanceDraft.status == "GENERATING",
        )
    ).first()
    if active_draft is not None:
        raise _draft_state_error(
            draft_service.AiGovernanceDraftStateError("draft_generation_active")
        )
    try:
        report = draft_service.require_published_report_for_draft(
            session=session, report=report
        )
        bindings = draft_service.draft_finding_bindings_for_request(
            session=session,
            report=report,
            finding_ids=request_body.finding_ids,
        )
    except draft_service.AiGovernanceDraftStateError as error:
        raise _draft_state_error(error) from None
    binding = _require_current_model_binding(session=session)
    try:
        creation = draft_service.create_ai_governance_draft(
            session=session,
            report=report,
            initiated_by=str(current_user.id),
            idempotency_key=key,
            model_identity=binding.model_identity,
            config_fingerprint=binding.config_fingerprint,
            bindings=bindings,
        )
    except draft_service.AiGovernanceDraftStateError as error:
        raise _draft_state_error(error) from None
    try:
        draft = _launch_or_reconcile_draft_session(
            session=session,
            draft=creation.draft,
            launch_now=creation.created,
            authorize_start=lambda: _require_current_model_binding(
                session=session, draft=creation.draft
            ),
        )
    except AgentComposeBoundaryError as error:
        raise _agent_compose_error(error) from None
    except draft_service.AiGovernanceDraftStateError as error:
        raise _draft_state_error(error) from None
    if not creation.created:
        response.status_code = status.HTTP_200_OK
    return report_service.ai_governance_draft_public(session=session, draft=draft)


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
