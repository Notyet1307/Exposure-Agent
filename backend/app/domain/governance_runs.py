from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain.cloudatlas_sources import (
    DESCRIPTOR_SHA256,
    METHOD,
    PACKAGE_SHA256,
    CloudAtlasBoundaryError,
    OctobusCloudAtlasClient,
)
from app.domain.ip_consistency import (
    CLOUDATLAS_SOURCE_TYPE as IP_CLOUDATLAS_SOURCE_TYPE,
)
from app.domain.ip_consistency import (
    CUSTOMER_UPLOAD_SOURCE_TYPE as IP_CUSTOMER_UPLOAD_SOURCE_TYPE,
)
from app.domain.ip_consistency import (
    IP_PROCESSING_CONTRACT_VERSION,
    IPObservation,
    IPRecordContractError,
    check_ip_differences,
    ip_observation_sort_key,
    process_ip_snapshots,
)
from app.domain.models import (
    Artifact,
    AuditEvent,
    CustomerUpload,
    CustomerUploadProfile,
    Finding,
    FindingOccurrence,
    FindingOccurrenceObservation,
    FindingOccurrenceSnapshot,
    FindingTransition,
    FindingTransitionObservation,
    FindingTransitionSnapshot,
    GovernanceRun,
    GovernanceRunPublic,
    GovernanceRunStatus,
    Observation,
    ObservationResourceLink,
    Project,
    Resource,
    ResourceType,
    RunStep,
    RunStepCode,
    RunStepPublic,
    RunStepStatus,
    SourceInstance,
    SourceSnapshot,
    SourceSnapshotPublic,
    SourceSnapshotType,
)
from app.integrations.agent_compose import (
    AgentComposeClient,
    AgentComposeSessionObservation,
)

logger = logging.getLogger(__name__)

CLOUDATLAS_SNAPSHOT_MEDIA_TYPE = "application/json"
CLOUDATLAS_SNAPSHOT_SCHEMA = "exposure-agent.cloudatlas-ip-assets.snapshot.v1"
CLOUDATLAS_PAGE_SIZE = 200
_STEP_ORDER = {
    RunStepCode.LOAD_CUSTOMER.value: 0,
    RunStepCode.PULL_CLOUDATLAS.value: 1,
    RunStepCode.NORMALIZE.value: 2,
    RunStepCode.RESOLVE.value: 3,
    RunStepCode.CHECK_FINDINGS.value: 4,
    RunStepCode.PUBLISH.value: 5,
}
COMPLETED_RUN_STATUSES = frozenset({GovernanceRunStatus.COMPLETED.value})
_NON_RETRYABLE_PREFIX = "non_retryable:"


class GovernanceRunStateError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class GovernanceRunExecutionError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class GovernanceRunProcessingError(GovernanceRunExecutionError):
    pass


@dataclass(frozen=True)
class PinnedTriggerInputs:
    project_id: uuid.UUID
    tenant_id: uuid.UUID
    customer_upload_id: uuid.UUID
    customer_upload_sha256: str
    customer_upload_profile_id: uuid.UUID
    customer_upload_profile_version: int
    source_instance_id: uuid.UUID
    cloudatlas_validated_fingerprint: str
    cloudatlas_capset_id: str
    cloudatlas_method: str
    package_sha256: str
    descriptor_sha256: str
    runner_build_version: str
    processing_contract_version: str | None

    def input_hash(self) -> str:
        environment = self.runner_environment(trigger_id="-", requested_by="-")
        environment.pop("GOVERNANCE_TRIGGER_ID")
        environment.pop("GOVERNANCE_REQUESTED_BY")
        return _fingerprint(environment)

    def runner_environment(
        self,
        *,
        trigger_id: str,
        requested_by: str,
    ) -> dict[str, str]:
        return {
            "GOVERNANCE_PROJECT_ID": str(self.project_id),
            "GOVERNANCE_TRIGGER_ID": trigger_id,
            "GOVERNANCE_REQUESTED_BY": requested_by,
            "GOVERNANCE_CUSTOMER_UPLOAD_ID": str(self.customer_upload_id),
            "GOVERNANCE_CUSTOMER_UPLOAD_SHA256": self.customer_upload_sha256,
            "GOVERNANCE_CUSTOMER_PROFILE_ID": str(self.customer_upload_profile_id),
            "GOVERNANCE_CUSTOMER_PROFILE_VERSION": str(
                self.customer_upload_profile_version
            ),
            "GOVERNANCE_SOURCE_INSTANCE_ID": str(self.source_instance_id),
            "GOVERNANCE_CLOUDATLAS_FINGERPRINT": (
                self.cloudatlas_validated_fingerprint
            ),
            "GOVERNANCE_CLOUDATLAS_CAPSET_ID": self.cloudatlas_capset_id,
            "GOVERNANCE_CLOUDATLAS_METHOD": self.cloudatlas_method,
            "GOVERNANCE_PACKAGE_SHA256": self.package_sha256,
            "GOVERNANCE_DESCRIPTOR_SHA256": self.descriptor_sha256,
            "GOVERNANCE_RUNNER_BUILD_VERSION": self.runner_build_version,
            "GOVERNANCE_PROCESSING_CONTRACT_VERSION": (
                self.processing_contract_version or ""
            ),
        }


@dataclass(frozen=True)
class RunnerInputs:
    project_id: uuid.UUID
    trigger_id: str
    session_id: str
    requested_by: str
    customer_upload_id: uuid.UUID
    customer_upload_sha256: str
    customer_upload_profile_id: uuid.UUID
    customer_upload_profile_version: int
    source_instance_id: uuid.UUID
    cloudatlas_validated_fingerprint: str
    cloudatlas_capset_id: str
    cloudatlas_method: str
    package_sha256: str
    descriptor_sha256: str
    runner_build_version: str
    processing_contract_version: str | None

    @classmethod
    def from_environment(cls, environment: dict[str, str]) -> RunnerInputs:
        def required(name: str) -> str:
            value = environment.get(name, "").strip()
            if not value:
                raise GovernanceRunExecutionError("runner_input_invalid")
            return value

        try:
            profile_version = int(required("GOVERNANCE_CUSTOMER_PROFILE_VERSION"))
            raw_processing_contract = environment.get(
                "GOVERNANCE_PROCESSING_CONTRACT_VERSION", ""
            ).strip()
            inputs = cls(
                project_id=uuid.UUID(required("GOVERNANCE_PROJECT_ID")),
                trigger_id=required("GOVERNANCE_TRIGGER_ID"),
                session_id=required("SANDBOX_ID"),
                requested_by=required("GOVERNANCE_REQUESTED_BY"),
                customer_upload_id=uuid.UUID(required("GOVERNANCE_CUSTOMER_UPLOAD_ID")),
                customer_upload_sha256=required("GOVERNANCE_CUSTOMER_UPLOAD_SHA256"),
                customer_upload_profile_id=uuid.UUID(
                    required("GOVERNANCE_CUSTOMER_PROFILE_ID")
                ),
                customer_upload_profile_version=profile_version,
                source_instance_id=uuid.UUID(required("GOVERNANCE_SOURCE_INSTANCE_ID")),
                cloudatlas_validated_fingerprint=required(
                    "GOVERNANCE_CLOUDATLAS_FINGERPRINT"
                ),
                cloudatlas_capset_id=required("GOVERNANCE_CLOUDATLAS_CAPSET_ID"),
                cloudatlas_method=required("GOVERNANCE_CLOUDATLAS_METHOD"),
                package_sha256=required("GOVERNANCE_PACKAGE_SHA256"),
                descriptor_sha256=required("GOVERNANCE_DESCRIPTOR_SHA256"),
                runner_build_version=required("GOVERNANCE_RUNNER_BUILD_VERSION"),
                processing_contract_version=raw_processing_contract or None,
            )
        except ValueError:
            raise GovernanceRunExecutionError("runner_input_invalid")
        if (
            profile_version < 1
            or len(inputs.trigger_id) > 255
            or len(inputs.session_id) != 64
            or any(
                character not in "0123456789abcdef" for character in inputs.session_id
            )
            or (
                inputs.processing_contract_version is not None
                and len(inputs.processing_contract_version) > 100
            )
        ):
            raise GovernanceRunExecutionError("runner_input_invalid")
        return inputs


@dataclass(frozen=True)
class CloudAtlasArtifactDraft:
    temporary_path: Path
    byte_size: int
    sha256: str
    record_count: int


def _execution_error(code: str) -> NoReturn:
    raise GovernanceRunExecutionError(code)


def _processing_error(code: str) -> NoReturn:
    raise GovernanceRunProcessingError(code)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def require_trigger_readiness(
    *,
    session: Session,
    project: Project,
    verify_current_fingerprint: bool = True,
) -> PinnedTriggerInputs:
    if project.current_customer_upload_id is None:
        raise GovernanceRunStateError("run_customer_upload_not_ready")
    upload = session.exec(
        select(CustomerUpload).where(
            CustomerUpload.id == project.current_customer_upload_id,
            CustomerUpload.project_id == project.id,
            CustomerUpload.tenant_id == project.tenant_id,
        )
    ).one_or_none()
    if upload is None:
        raise GovernanceRunStateError("run_customer_upload_not_ready")
    source = session.exec(
        select(SourceInstance).where(
            SourceInstance.project_id == project.id,
            SourceInstance.tenant_id == project.tenant_id,
            SourceInstance.enabled,
        )
    ).one_or_none()
    if (
        source is None
        or source.validated_fingerprint is None
        or source.validation_error_code is not None
    ):
        raise GovernanceRunStateError("run_cloudatlas_source_not_ready")
    assert source.validated_fingerprint is not None
    validated_fingerprint = source.validated_fingerprint
    if verify_current_fingerprint:
        try:
            current = OctobusCloudAtlasClient().current_fingerprint(source)
        except CloudAtlasBoundaryError:
            raise GovernanceRunStateError("run_cloudatlas_source_not_ready")
        if current.value != validated_fingerprint:
            raise GovernanceRunStateError("run_cloudatlas_source_not_ready")
        validated_fingerprint = current.value
    if not settings.CLOUDATLAS_CAPSET_TOKEN.get_secret_value():
        raise GovernanceRunStateError("run_cloudatlas_credential_not_ready")
    return PinnedTriggerInputs(
        project_id=project.id,
        tenant_id=project.tenant_id,
        customer_upload_id=upload.id,
        customer_upload_sha256=upload.raw_sha256,
        customer_upload_profile_id=upload.profile_id,
        customer_upload_profile_version=upload.profile_version,
        source_instance_id=source.id,
        cloudatlas_validated_fingerprint=validated_fingerprint,
        cloudatlas_capset_id=source.capset_id,
        cloudatlas_method=METHOD,
        package_sha256=PACKAGE_SHA256,
        descriptor_sha256=DESCRIPTOR_SHA256,
        runner_build_version=settings.RUNNER_BUILD_VERSION,
        processing_contract_version=IP_PROCESSING_CONTRACT_VERSION,
    )


def _audit_event(
    *,
    run: GovernanceRun,
    action: str,
    target_type: str,
    target_id: uuid.UUID,
    before_data: dict[str, Any] | None,
    after_data: dict[str, Any] | None,
    request_ip: str | None,
    actor_subject: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        actor_subject=actor_subject or run.requested_by,
        actor_type="user",
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_data=before_data,
        after_data=after_data,
        ip_address=request_ip,
    )


def _validate_runner_inputs(
    *,
    session: Session,
    inputs: RunnerInputs,
    allow_legacy_processing_contract: bool = False,
) -> tuple[Project, CustomerUpload, SourceInstance]:
    project = session.exec(
        select(Project).where(Project.id == inputs.project_id).with_for_update()
    ).one_or_none()
    if project is None or project.archived_at is not None:
        _execution_error("runner_project_not_ready")
    if project.governance_launch_trigger_id not in (None, inputs.trigger_id):
        _execution_error("runner_project_has_active_launch")
    if inputs.processing_contract_version is None:
        if not allow_legacy_processing_contract:
            _execution_error("runner_processing_contract_required")
    elif inputs.processing_contract_version != IP_PROCESSING_CONTRACT_VERSION:
        _execution_error("runner_processing_contract_unsupported")
    if not settings.CLOUDATLAS_CAPSET_TOKEN.get_secret_value():
        _execution_error("runner_cloudatlas_credential_not_ready")
    upload = session.exec(
        select(CustomerUpload).where(
            CustomerUpload.id == inputs.customer_upload_id,
            CustomerUpload.project_id == project.id,
            CustomerUpload.tenant_id == project.tenant_id,
        )
    ).one_or_none()
    if (
        upload is None
        or project.current_customer_upload_id != upload.id
        or upload.raw_sha256 != inputs.customer_upload_sha256
        or upload.profile_id != inputs.customer_upload_profile_id
        or upload.profile_version != inputs.customer_upload_profile_version
    ):
        _execution_error("runner_customer_input_changed")
    source = session.exec(
        select(SourceInstance).where(
            SourceInstance.id == inputs.source_instance_id,
            SourceInstance.project_id == project.id,
            SourceInstance.tenant_id == project.tenant_id,
        )
    ).one_or_none()
    if (
        source is None
        or not source.enabled
        or source.capset_id != inputs.cloudatlas_capset_id
        or source.validated_fingerprint != inputs.cloudatlas_validated_fingerprint
        or source.validation_error_code is not None
        or inputs.cloudatlas_method != METHOD
        or inputs.package_sha256 != PACKAGE_SHA256
        or inputs.descriptor_sha256 != DESCRIPTOR_SHA256
        or inputs.runner_build_version != settings.RUNNER_BUILD_VERSION
    ):
        _execution_error("runner_cloudatlas_input_changed")
    try:
        current = OctobusCloudAtlasClient().current_fingerprint(source)
    except CloudAtlasBoundaryError:
        _execution_error("runner_cloudatlas_input_unavailable")
    if current.value != inputs.cloudatlas_validated_fingerprint:
        _execution_error("runner_cloudatlas_input_changed")
    return project, upload, source


def establish_governance_run(
    *, session: Session, inputs: RunnerInputs
) -> GovernanceRun:
    existing = session.exec(
        select(GovernanceRun).where(
            GovernanceRun.project_id == inputs.project_id,
            GovernanceRun.trigger_id == inputs.trigger_id,
        )
    ).one_or_none()
    if existing is not None:
        if existing.session_id != inputs.session_id:
            _execution_error("runner_trigger_session_conflict")
        if existing.processing_contract_version != inputs.processing_contract_version:
            _execution_error("runner_processing_contract_changed")
        if (
            existing.status == GovernanceRunStatus.RUNNING.value
            and existing.session_recovery_code == "retry_prepared"
        ):
            _validate_runner_inputs(
                session=session,
                inputs=inputs,
                allow_legacy_processing_contract=(
                    existing.processing_contract_version is None
                ),
            )
            existing.session_terminal_at = None
            existing.session_recovery_code = None
            existing.updated_at = get_datetime_utc()
            session.add(existing)
            session.commit()
            session.refresh(existing)
        return existing

    project, upload, source = _validate_runner_inputs(session=session, inputs=inputs)
    latest = session.exec(
        select(GovernanceRun)
        .where(GovernanceRun.project_id == project.id)
        .order_by(
            col(GovernanceRun.created_at).desc(),
            col(GovernanceRun.id).desc(),
        )
    ).first()
    if (
        latest is not None
        and latest.status
        in {
            GovernanceRunStatus.FAILED_DATA.value,
            GovernanceRunStatus.FAILED_PROCESSING.value,
        }
        and latest.trigger_id != inputs.trigger_id
        and not rerun_request_was_recorded(
            session=session,
            source_run=latest,
            trigger_id=inputs.trigger_id,
        )
    ):
        _execution_error("runner_rerun_required")
    run = GovernanceRun(
        tenant_id=project.tenant_id,
        project_id=project.id,
        trigger_id=inputs.trigger_id,
        session_id=inputs.session_id,
        requested_by=inputs.requested_by,
        customer_upload_id=upload.id,
        customer_upload_sha256=upload.raw_sha256,
        customer_upload_profile_id=upload.profile_id,
        customer_upload_profile_version=upload.profile_version,
        source_instance_id=source.id,
        cloudatlas_validated_fingerprint=inputs.cloudatlas_validated_fingerprint,
        cloudatlas_capset_id=source.capset_id,
        cloudatlas_method=inputs.cloudatlas_method,
        package_sha256=inputs.package_sha256,
        descriptor_sha256=inputs.descriptor_sha256,
        runner_build_version=inputs.runner_build_version,
        processing_contract_version=inputs.processing_contract_version,
    )
    triggered = _audit_event(
        run=run,
        action="governance_run.triggered",
        target_type="governance_run",
        target_id=run.id,
        before_data=None,
        after_data={
            "status": GovernanceRunStatus.RUNNING.value,
            "trigger_id": run.trigger_id,
        },
        request_ip=None,
    )
    session_fixed = _audit_event(
        run=run,
        action="governance_run.session_fixed",
        target_type="governance_run",
        target_id=run.id,
        before_data=None,
        after_data={"session_id": run.session_id},
        request_ip=None,
    )
    try:
        session.add(run)
        session.flush()
        if project.governance_launch_trigger_id == inputs.trigger_id:
            project.governance_launch_trigger_id = None
            project.governance_launch_control_run_id = None
            project.governance_launch_input_hash = None
            project.updated_at = get_datetime_utc()
            session.add(project)
        session.add(triggered)
        session.add(session_fixed)
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(
            select(GovernanceRun).where(
                GovernanceRun.project_id == inputs.project_id,
                GovernanceRun.trigger_id == inputs.trigger_id,
            )
        ).one_or_none()
        if existing is not None and existing.session_id == inputs.session_id:
            return existing
        _execution_error("runner_project_has_active_run")
    session.refresh(run)
    return run


def _begin_step(
    *,
    session: Session,
    run: GovernanceRun,
    step_code: RunStepCode,
    input_hash: str,
    request_ip: str | None,
) -> tuple[RunStep, bool]:
    existing = session.exec(
        select(RunStep).where(
            RunStep.governance_run_id == run.id,
            RunStep.step_code == step_code.value,
        )
    ).one_or_none()
    if existing is not None:
        if existing.status == RunStepStatus.SUCCEEDED.value:
            return existing, False
        if existing.status == RunStepStatus.RUNNING.value:
            return existing, True
        return existing, False
    step = RunStep(
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        governance_run_id=run.id,
        step_code=step_code.value,
        input_hash=input_hash,
    )
    event = _audit_event(
        run=run,
        action="run_step.started",
        target_type="run_step",
        target_id=step.id,
        before_data=None,
        after_data={"step_code": step.step_code, "status": step.status},
        request_ip=request_ip,
    )
    try:
        session.add(step)
        session.flush()
        session.add(event)
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(step)
    return step, True


def _begin_step_or_fail(
    *,
    session: Session,
    run: GovernanceRun,
    step_code: RunStepCode,
    input_hash: str,
    request_ip: str | None,
) -> tuple[RunStep, bool]:
    try:
        return _begin_step(
            session=session,
            run=run,
            step_code=step_code,
            input_hash=input_hash,
            request_ip=request_ip,
        )
    except SQLAlchemyError:
        session.rollback()
        failed_step = RunStep(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            governance_run_id=run.id,
            step_code=step_code.value,
            input_hash=input_hash,
        )
        try:
            _fail_run(
                session=session,
                run=run,
                step=failed_step,
                run_status=GovernanceRunStatus.FAILED_PROCESSING,
                error_code="step_start_failed",
                request_ip=request_ip,
            )
        except SQLAlchemyError:
            session.rollback()
        raise GovernanceRunProcessingError("step_start_failed")


def _complete_snapshot_step(
    *,
    session: Session,
    run: GovernanceRun,
    step: RunStep,
    snapshot: SourceSnapshot,
    output_hash: str,
    request_ip: str | None,
    artifact: Artifact | None = None,
) -> None:
    completed_at = get_datetime_utc()
    step.status = RunStepStatus.SUCCEEDED.value
    step.output_hash = output_hash
    step.completed_at = completed_at
    step.updated_at = completed_at
    event = _audit_event(
        run=run,
        action="run_step.succeeded",
        target_type="run_step",
        target_id=step.id,
        before_data={"status": RunStepStatus.RUNNING.value},
        after_data={
            "step_code": step.step_code,
            "status": step.status,
            "snapshot_id": str(snapshot.id),
            "record_count": snapshot.record_count,
            "content_sha256": snapshot.content_sha256,
        },
        request_ip=request_ip,
    )
    try:
        if artifact is not None:
            session.add(artifact)
            session.flush()
        session.add(snapshot)
        session.flush()
        session.add(step)
        session.add(event)
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise


def _fail_run(
    *,
    session: Session,
    run: GovernanceRun,
    step: RunStep,
    run_status: GovernanceRunStatus,
    error_code: str,
    request_ip: str | None,
    retryable: bool = True,
) -> None:
    failed_at = get_datetime_utc()
    step.status = RunStepStatus.FAILED.value
    step.error_code = error_code
    step.completed_at = failed_at
    step.updated_at = failed_at
    run.status = run_status.value
    run.session_recovery_code = (
        None if retryable else f"{_NON_RETRYABLE_PREFIX}{error_code}"
    )
    run.updated_at = failed_at
    step_event = _audit_event(
        run=run,
        action="run_step.failed",
        target_type="run_step",
        target_id=step.id,
        before_data={"status": RunStepStatus.RUNNING.value},
        after_data={
            "step_code": step.step_code,
            "status": step.status,
            "error_code": error_code,
        },
        request_ip=request_ip,
    )
    run_event = _audit_event(
        run=run,
        action="governance_run.failed",
        target_type="governance_run",
        target_id=run.id,
        before_data={"status": GovernanceRunStatus.RUNNING.value},
        after_data={"status": run.status, "error_code": error_code},
        request_ip=request_ip,
    )
    try:
        session.add(step)
        session.add(run)
        session.add(step_event)
        session.add(run_event)
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise


def _artifact_path(artifact: Artifact) -> Path:
    root = settings.ARTIFACT_ROOT.resolve()
    path = (root / artifact.storage_key).resolve()
    if root not in path.parents:
        _execution_error("artifact_reference_invalid")
    return path


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError:
        _execution_error("artifact_read_failed")
    return digest.hexdigest(), size


def _load_customer_snapshot(
    *, session: Session, run: GovernanceRun, request_ip: str | None
) -> None:
    step, created = _begin_step_or_fail(
        session=session,
        run=run,
        step_code=RunStepCode.LOAD_CUSTOMER,
        input_hash=run.customer_upload_sha256,
        request_ip=request_ip,
    )
    if not created:
        if step.status == RunStepStatus.SUCCEEDED.value:
            return
        _execution_error("runner_step_already_started")
    try:
        upload = session.exec(
            select(CustomerUpload).where(
                CustomerUpload.id == run.customer_upload_id,
                CustomerUpload.project_id == run.project_id,
                CustomerUpload.tenant_id == run.tenant_id,
            )
        ).one()
        profile = session.exec(
            select(CustomerUploadProfile).where(
                CustomerUploadProfile.id == run.customer_upload_profile_id,
                CustomerUploadProfile.project_id == run.project_id,
                CustomerUploadProfile.version == run.customer_upload_profile_version,
            )
        ).one()
        artifact = session.exec(
            select(Artifact).where(
                Artifact.id == upload.artifact_id,
                Artifact.tenant_id == run.tenant_id,
            )
        ).one()
        file_hash, byte_size = _file_sha256(_artifact_path(artifact))
        if (
            upload.raw_sha256 != run.customer_upload_sha256
            or artifact.sha256 != run.customer_upload_sha256
            or file_hash != run.customer_upload_sha256
            or byte_size != artifact.byte_size
        ):
            _execution_error("customer_artifact_changed")
        schema_fingerprint = _fingerprint(
            {
                "profile_id": str(profile.id),
                "version": profile.version,
                "definition": profile.definition,
            }
        )
        snapshot = SourceSnapshot(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            governance_run_id=run.id,
            source_type=SourceSnapshotType.CUSTOMER_UPLOAD.value,
            customer_upload_id=upload.id,
            artifact_id=artifact.id,
            content_sha256=file_hash,
            schema_fingerprint=schema_fingerprint,
            record_count=upload.record_count,
        )
        _complete_snapshot_step(
            session=session,
            run=run,
            step=step,
            snapshot=snapshot,
            output_hash=file_hash,
            request_ip=request_ip,
        )
    except GovernanceRunExecutionError as error:
        logger.error("Customer snapshot failed: %s", error.code)
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_DATA,
            error_code="customer_snapshot_failed",
            request_ip=request_ip,
        )
        raise GovernanceRunExecutionError("customer_snapshot_failed")
    except SQLAlchemyError:
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code="customer_snapshot_processing_failed",
            request_ip=request_ip,
        )
        raise GovernanceRunExecutionError("customer_snapshot_processing_failed")


def _write_cloudatlas_artifact(
    *, source: SourceInstance, artifact_root: Path
) -> CloudAtlasArtifactDraft:
    directory = artifact_root / "cloudatlas_snapshots"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        _processing_error("cloudatlas_artifact_write_failed")
    temporary_path = directory / f".{uuid.uuid4()}.tmp.json"
    digest = hashlib.sha256()
    byte_size = 0
    record_count = 0
    expected_total: int | None = None
    page = 1
    client = OctobusCloudAtlasClient()
    token = settings.CLOUDATLAS_CAPSET_TOKEN.get_secret_value()

    def write(destination: Any, value: bytes) -> None:
        nonlocal byte_size
        written = destination.write(value)
        if written != len(value):
            _processing_error("cloudatlas_artifact_write_failed")
        digest.update(value)
        byte_size += len(value)

    try:
        with temporary_path.open("xb") as destination:
            write(destination, b'{"pages":[')
            while True:
                payload = client.list_ip_assets_page(
                    source,
                    capset_token=token,
                    page=page,
                    size=CLOUDATLAS_PAGE_SIZE,
                )
                if not isinstance(payload, dict) or set(payload) != {
                    "items",
                    "page",
                    "size",
                    "total",
                }:
                    _execution_error("cloudatlas_response_contract_failed")
                returned_page = payload.get("page")
                returned_size = payload.get("size")
                total = payload.get("total")
                items = payload.get("items")
                if (
                    not isinstance(returned_page, int)
                    or isinstance(returned_page, bool)
                    or returned_page != page
                    or not isinstance(returned_size, int)
                    or isinstance(returned_size, bool)
                    or returned_size != CLOUDATLAS_PAGE_SIZE
                    or not isinstance(total, int)
                    or isinstance(total, bool)
                    or total < 0
                    or not isinstance(items, list)
                    or not all(
                        isinstance(item, dict)
                        and set(item) == {"id", "ip", "status"}
                        and isinstance(item.get("id"), str)
                        and isinstance(item.get("ip"), str)
                        and isinstance(item.get("status"), str)
                        for item in items
                    )
                    or len(items) > CLOUDATLAS_PAGE_SIZE
                ):
                    _execution_error("cloudatlas_response_contract_failed")
                if expected_total is None:
                    expected_total = total
                if total != expected_total or record_count + len(items) > total:
                    _execution_error("cloudatlas_response_contract_failed")
                if page > 1:
                    write(destination, b",")
                write(destination, _canonical_bytes(payload))
                record_count += len(items)
                if record_count == total:
                    break
                if not items:
                    _execution_error("cloudatlas_response_contract_failed")
                page += 1
            write(
                destination,
                b'],"schema":"' + CLOUDATLAS_SNAPSHOT_SCHEMA.encode() + b'"}\n',
            )
            destination.flush()
            os.fsync(destination.fileno())
    except (OSError, CloudAtlasBoundaryError, GovernanceRunExecutionError):
        temporary_path.unlink(missing_ok=True)
        raise
    return CloudAtlasArtifactDraft(
        temporary_path=temporary_path,
        byte_size=byte_size,
        sha256=digest.hexdigest(),
        record_count=record_count,
    )


def _pull_cloudatlas_snapshot(
    *, session: Session, run: GovernanceRun, request_ip: str | None
) -> None:
    step, created = _begin_step_or_fail(
        session=session,
        run=run,
        step_code=RunStepCode.PULL_CLOUDATLAS,
        input_hash=run.cloudatlas_validated_fingerprint,
        request_ip=request_ip,
    )
    if not created:
        if step.status == RunStepStatus.SUCCEEDED.value:
            return
        _execution_error("runner_step_already_started")
    draft: CloudAtlasArtifactDraft | None = None
    final_path: Path | None = None
    try:
        source = session.exec(
            select(SourceInstance).where(
                SourceInstance.id == run.source_instance_id,
                SourceInstance.project_id == run.project_id,
                SourceInstance.tenant_id == run.tenant_id,
            )
        ).one()
        before = OctobusCloudAtlasClient().current_fingerprint(source)
        if before.value != run.cloudatlas_validated_fingerprint:
            _execution_error("cloudatlas_material_changed")
        draft = _write_cloudatlas_artifact(
            source=source, artifact_root=settings.ARTIFACT_ROOT
        )
        after = OctobusCloudAtlasClient().current_fingerprint(source)
        if after.value != run.cloudatlas_validated_fingerprint:
            _execution_error("cloudatlas_material_changed")
        artifact_id = uuid.uuid4()
        storage_key = f"cloudatlas_snapshots/{artifact_id}.json"
        final_path = settings.ARTIFACT_ROOT / storage_key
        os.replace(draft.temporary_path, final_path)
        final_path.chmod(0o440)
        artifact = Artifact(
            id=artifact_id,
            tenant_id=run.tenant_id,
            storage_key=storage_key,
            media_type=CLOUDATLAS_SNAPSHOT_MEDIA_TYPE,
            byte_size=draft.byte_size,
            sha256=draft.sha256,
        )
        method_fingerprint = _fingerprint(
            {
                "method": run.cloudatlas_method,
                "package_sha256": run.package_sha256,
                "descriptor_sha256": run.descriptor_sha256,
            }
        )
        snapshot = SourceSnapshot(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            governance_run_id=run.id,
            source_type=SourceSnapshotType.CLOUDATLAS.value,
            source_instance_id=source.id,
            artifact_id=artifact.id,
            content_sha256=draft.sha256,
            schema_fingerprint=run.descriptor_sha256,
            method_fingerprint=method_fingerprint,
            record_count=draft.record_count,
        )
        _complete_snapshot_step(
            session=session,
            run=run,
            step=step,
            snapshot=snapshot,
            output_hash=draft.sha256,
            request_ip=request_ip,
            artifact=artifact,
        )
    except (
        OSError,
        CloudAtlasBoundaryError,
        GovernanceRunExecutionError,
        SQLAlchemyError,
    ) as error:
        session.rollback()
        if draft is not None:
            draft.temporary_path.unlink(missing_ok=True)
        if final_path is not None:
            final_path.unlink(missing_ok=True)
        processing_failure = isinstance(
            error, (OSError, GovernanceRunProcessingError, SQLAlchemyError)
        )
        error_code = (
            "cloudatlas_snapshot_processing_failed"
            if processing_failure
            else "cloudatlas_snapshot_failed"
        )
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=(
                GovernanceRunStatus.FAILED_PROCESSING
                if processing_failure
                else GovernanceRunStatus.FAILED_DATA
            ),
            error_code=error_code,
            request_ip=request_ip,
        )
        raise GovernanceRunExecutionError(error_code)


def _stage4_snapshots(
    *, session: Session, run: GovernanceRun
) -> tuple[SourceSnapshot, SourceSnapshot]:
    snapshots = session.exec(
        select(SourceSnapshot).where(
            SourceSnapshot.governance_run_id == run.id,
            SourceSnapshot.project_id == run.project_id,
            SourceSnapshot.tenant_id == run.tenant_id,
        )
    ).all()
    by_type = {snapshot.source_type: snapshot for snapshot in snapshots}
    if len(snapshots) != 2:
        _processing_error("stage4_snapshots_incomplete")
    customer = by_type.get(SourceSnapshotType.CUSTOMER_UPLOAD.value)
    cloudatlas = by_type.get(SourceSnapshotType.CLOUDATLAS.value)
    if customer is None or cloudatlas is None or len(by_type) != 2:
        _processing_error("stage4_snapshots_incomplete")
    assert customer is not None
    assert cloudatlas is not None
    if (
        customer.customer_upload_id != run.customer_upload_id
        or cloudatlas.source_instance_id != run.source_instance_id
    ):
        _processing_error("stage4_snapshot_scope_invalid")
    return customer, cloudatlas


def _stage4_snapshot_paths(
    *, session: Session, run: GovernanceRun
) -> tuple[SourceSnapshot, SourceSnapshot, Path, Path]:
    customer_snapshot, cloudatlas_snapshot = _stage4_snapshots(session=session, run=run)
    _verify_snapshot_artifact(session=session, snapshot=customer_snapshot)
    _verify_snapshot_artifact(session=session, snapshot=cloudatlas_snapshot)
    artifacts = session.exec(
        select(Artifact).where(
            col(Artifact.id).in_(
                (customer_snapshot.artifact_id, cloudatlas_snapshot.artifact_id)
            ),
            Artifact.tenant_id == run.tenant_id,
        )
    ).all()
    artifacts_by_id = {artifact.id: artifact for artifact in artifacts}
    customer_artifact = artifacts_by_id.get(customer_snapshot.artifact_id)
    cloudatlas_artifact = artifacts_by_id.get(cloudatlas_snapshot.artifact_id)
    if customer_artifact is None or cloudatlas_artifact is None:
        _processing_error("stage4_snapshot_artifact_missing")
    assert customer_artifact is not None
    assert cloudatlas_artifact is not None
    return (
        customer_snapshot,
        cloudatlas_snapshot,
        _artifact_path(customer_artifact),
        _artifact_path(cloudatlas_artifact),
    )


def _stage4_result(
    *, session: Session, run: GovernanceRun
) -> tuple[Any, SourceSnapshot, SourceSnapshot]:
    customer_snapshot, cloudatlas_snapshot, customer_path, cloudatlas_path = (
        _stage4_snapshot_paths(session=session, run=run)
    )
    result = process_ip_snapshots(
        customer_path,
        cloudatlas_path,
        processing_contract_version=run.processing_contract_version
        or IP_PROCESSING_CONTRACT_VERSION,
    )
    return result, customer_snapshot, cloudatlas_snapshot


def _ip_observation_from_model(observation: Observation) -> IPObservation:
    return IPObservation(
        source_type=observation.source_type,
        source_record_key=observation.source_record_key,
        raw_ip=observation.raw_ip,
        canonical_ip=str(observation.canonical_ip),
        cloudatlas_asset_id=observation.cloudatlas_asset_id,
        cloudatlas_status=observation.cloudatlas_status,
    )


def _normalize_ip_observations(
    *, session: Session, run: GovernanceRun, request_ip: str | None
) -> None:
    snapshot_hashes = session.exec(
        select(SourceSnapshot.content_sha256).where(
            SourceSnapshot.governance_run_id == run.id
        )
    ).all()
    input_hash = _fingerprint(
        {
            "processing_contract_version": run.processing_contract_version,
            "snapshot_hashes": sorted(snapshot_hashes),
        }
    )
    step, created = _begin_step_or_fail(
        session=session,
        run=run,
        step_code=RunStepCode.NORMALIZE,
        input_hash=input_hash,
        request_ip=request_ip,
    )
    if not created:
        if step.status == RunStepStatus.SUCCEEDED.value:
            return
        _execution_error("runner_step_already_started")
    try:
        result, customer_snapshot, cloudatlas_snapshot = _stage4_result(
            session=session, run=run
        )
        observations = [
            Observation(
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                governance_run_id=run.id,
                source_snapshot_id=(
                    customer_snapshot.id
                    if item.source_type == IP_CUSTOMER_UPLOAD_SOURCE_TYPE
                    else cloudatlas_snapshot.id
                ),
                source_type=item.source_type,
                source_record_key=item.source_record_key,
                raw_ip=item.raw_ip,
                canonical_ip=item.canonical_ip,
                cloudatlas_asset_id=item.cloudatlas_asset_id,
                cloudatlas_status=item.cloudatlas_status,
            )
            for item in result.observations
        ]
        output_hash = _fingerprint(
            {
                "processing_contract_version": run.processing_contract_version,
                "observations": [item.as_dict() for item in result.observations],
            }
        )
        completed_at = get_datetime_utc()
        step.status = RunStepStatus.SUCCEEDED.value
        step.output_hash = output_hash
        step.completed_at = completed_at
        step.updated_at = completed_at
        session.add_all(observations)
        session.add(step)
        session.add(
            _audit_event(
                run=run,
                action="run_step.succeeded",
                target_type="run_step",
                target_id=step.id,
                before_data={"status": RunStepStatus.RUNNING.value},
                after_data={
                    "step_code": step.step_code,
                    "status": step.status,
                    "observation_count": len(observations),
                    "output_hash": output_hash,
                },
                request_ip=request_ip,
            )
        )
        session.commit()
    except IPRecordContractError:
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code="normalize_contract_failed",
            request_ip=request_ip,
            retryable=False,
        )
        raise GovernanceRunProcessingError("normalize_contract_failed")
    except GovernanceRunProcessingError:
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code="normalize_contract_failed",
            request_ip=request_ip,
            retryable=False,
        )
        raise GovernanceRunProcessingError("normalize_contract_failed")
    except GovernanceRunExecutionError as error:
        session.rollback()
        non_retryable = error.code in {
            "artifact_reference_invalid",
            "snapshot_artifact_changed",
            "stage4_snapshots_incomplete",
            "stage4_snapshot_scope_invalid",
            "stage4_snapshot_artifact_missing",
        }
        error_code = (
            "normalize_contract_failed"
            if non_retryable
            else "normalize_snapshot_failed"
        )
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code=error_code,
            request_ip=request_ip,
            retryable=not non_retryable,
        )
        raise GovernanceRunProcessingError(error_code)
    except OSError:
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code="normalize_snapshot_unavailable",
            request_ip=request_ip,
        )
        raise GovernanceRunProcessingError("normalize_snapshot_unavailable")
    except SQLAlchemyError:
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code="normalize_persistence_failed",
            request_ip=request_ip,
        )
        raise GovernanceRunProcessingError("normalize_persistence_failed")
    except Exception as unexpected_error:
        logger.error(
            "IP normalization failed unexpectedly: %s",
            type(unexpected_error).__name__,
        )
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code="normalize_unexpected_failure",
            request_ip=request_ip,
        )
        raise GovernanceRunProcessingError("normalize_unexpected_failure")


def _resolve_ip_observations(
    *, session: Session, run: GovernanceRun, request_ip: str | None
) -> None:
    normalize_step = session.exec(
        select(RunStep).where(
            RunStep.governance_run_id == run.id,
            RunStep.step_code == RunStepCode.NORMALIZE.value,
        )
    ).one_or_none()
    if normalize_step is None or normalize_step.status != RunStepStatus.SUCCEEDED.value:
        _processing_error("normalize_step_incomplete")
    assert normalize_step.output_hash is not None
    input_hash = _fingerprint(
        {
            "processing_contract_version": run.processing_contract_version,
            "normalize_output_hash": normalize_step.output_hash,
        }
    )
    step, created = _begin_step_or_fail(
        session=session,
        run=run,
        step_code=RunStepCode.RESOLVE,
        input_hash=input_hash,
        request_ip=request_ip,
    )
    if not created:
        if step.status == RunStepStatus.SUCCEEDED.value:
            return
        _execution_error("runner_step_already_started")
    try:
        observations = sorted(
            session.exec(
                select(Observation).where(
                    Observation.governance_run_id == run.id,
                    Observation.project_id == run.project_id,
                    Observation.tenant_id == run.tenant_id,
                )
            ).all(),
            key=lambda observation: ip_observation_sort_key(
                observation.source_type,
                observation.source_record_key,
                observation.id,
            ),
        )
        if not observations:
            _processing_error("resolve_observations_missing")
        canonical_keys = sorted({str(item.canonical_ip) for item in observations})
        resources = session.exec(
            select(Resource).where(
                Resource.project_id == run.project_id,
                Resource.tenant_id == run.tenant_id,
                col(Resource.resource_type) == ResourceType.IP.value,
                col(Resource.canonical_key).in_(canonical_keys),
            )
        ).all()
        resources_by_key = {
            str(resource.canonical_key): resource for resource in resources
        }
        for canonical_key in canonical_keys:
            if canonical_key not in resources_by_key:
                resource = Resource(
                    tenant_id=run.tenant_id,
                    project_id=run.project_id,
                    resource_type=ResourceType.IP.value,
                    canonical_key=canonical_key,
                )
                session.add(resource)
                session.flush()
                resources_by_key[canonical_key] = resource
        existing_link_rows = session.exec(
            select(
                col(ObservationResourceLink.observation_id),
                col(ObservationResourceLink.resource_id),
            ).where(
                ObservationResourceLink.governance_run_id == run.id,
                ObservationResourceLink.project_id == run.project_id,
                ObservationResourceLink.tenant_id == run.tenant_id,
            )
        ).all()
        links_by_observation = dict(existing_link_rows)
        new_links: list[ObservationResourceLink] = []
        for observation in observations:
            resource = resources_by_key[str(observation.canonical_ip)]
            existing_resource_id = links_by_observation.get(observation.id)
            if existing_resource_id is not None:
                if existing_resource_id != resource.id:
                    _processing_error("resolve_link_mismatch")
                continue
            new_links.append(
                ObservationResourceLink(
                    tenant_id=run.tenant_id,
                    project_id=run.project_id,
                    governance_run_id=run.id,
                    observation_id=observation.id,
                    resource_id=resource.id,
                    processing_contract_version=(
                        run.processing_contract_version
                        or IP_PROCESSING_CONTRACT_VERSION
                    ),
                )
            )
        session.add_all(new_links)
        output_hash = _fingerprint(
            {
                "processing_contract_version": run.processing_contract_version,
                "resources": [
                    {
                        "resource_type": ResourceType.IP.value,
                        "canonical_key": key,
                    }
                    for key in canonical_keys
                ],
                "links": [
                    {
                        "source_type": observation.source_type,
                        "source_record_key": observation.source_record_key,
                        "resource_key": str(observation.canonical_ip),
                    }
                    for observation in observations
                ],
            }
        )
        completed_at = get_datetime_utc()
        step.status = RunStepStatus.SUCCEEDED.value
        step.output_hash = output_hash
        step.completed_at = completed_at
        step.updated_at = completed_at
        session.add(step)
        session.add(
            _audit_event(
                run=run,
                action="run_step.succeeded",
                target_type="run_step",
                target_id=step.id,
                before_data={"status": RunStepStatus.RUNNING.value},
                after_data={
                    "step_code": step.step_code,
                    "status": step.status,
                    "resource_count": len(resources_by_key),
                    "link_count": len(observations),
                    "output_hash": output_hash,
                },
                request_ip=request_ip,
            )
        )
        session.commit()
    except GovernanceRunProcessingError:
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code="resolve_contract_failed",
            request_ip=request_ip,
            retryable=False,
        )
        raise GovernanceRunProcessingError("resolve_contract_failed")
    except GovernanceRunExecutionError:
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code="resolve_contract_failed",
            request_ip=request_ip,
            retryable=False,
        )
        raise GovernanceRunProcessingError("resolve_contract_failed")
    except SQLAlchemyError:
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code="resolve_persistence_failed",
            request_ip=request_ip,
        )
        raise GovernanceRunProcessingError("resolve_persistence_failed")


def _check_ip_findings(
    *, session: Session, run: GovernanceRun, request_ip: str | None
) -> None:
    resolve_step = session.exec(
        select(RunStep).where(
            RunStep.governance_run_id == run.id,
            RunStep.step_code == RunStepCode.RESOLVE.value,
        )
    ).one_or_none()
    if resolve_step is None or resolve_step.status != RunStepStatus.SUCCEEDED.value:
        _processing_error("resolve_step_incomplete")
    assert resolve_step.output_hash is not None
    input_hash = _fingerprint(
        {
            "processing_contract_version": run.processing_contract_version,
            "resolve_output_hash": resolve_step.output_hash,
        }
    )
    step, created = _begin_step_or_fail(
        session=session,
        run=run,
        step_code=RunStepCode.CHECK_FINDINGS,
        input_hash=input_hash,
        request_ip=request_ip,
    )
    if not created:
        if step.status == RunStepStatus.SUCCEEDED.value:
            return
        _execution_error("runner_step_already_started")
    try:
        observations = sorted(
            session.exec(
                select(Observation).where(
                    Observation.governance_run_id == run.id,
                    Observation.project_id == run.project_id,
                    Observation.tenant_id == run.tenant_id,
                )
            ).all(),
            key=lambda observation: ip_observation_sort_key(
                observation.source_type,
                observation.source_record_key,
                observation.id,
            ),
        )
        link_observation_ids = session.exec(
            select(col(ObservationResourceLink.observation_id)).where(
                ObservationResourceLink.governance_run_id == run.id,
                ObservationResourceLink.project_id == run.project_id,
                ObservationResourceLink.tenant_id == run.tenant_id,
            )
        ).all()
        if len(link_observation_ids) != len(observations) or set(
            link_observation_ids
        ) != {observation.id for observation in observations}:
            _processing_error("resolve_links_incomplete")
        differences, check_payload = _stage4_check_payload(
            run=run, observations=observations
        )
        output_hash = _fingerprint(check_payload)
        completed_at = get_datetime_utc()
        step.status = RunStepStatus.SUCCEEDED.value
        step.output_hash = output_hash
        step.completed_at = completed_at
        step.updated_at = completed_at
        session.add(step)
        session.add(
            _audit_event(
                run=run,
                action="run_step.succeeded",
                target_type="run_step",
                target_id=step.id,
                before_data={"status": RunStepStatus.RUNNING.value},
                after_data={
                    "step_code": step.step_code,
                    "status": step.status,
                    "output_hash": output_hash,
                    "difference_count": sum(
                        len(items)
                        for items in (
                            differences.cloudatlas_only,
                            differences.customer_upload_only,
                        )
                    ),
                },
                request_ip=request_ip,
            )
        )
        session.commit()
    except (GovernanceRunProcessingError, IPRecordContractError):
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code="check_findings_contract_failed",
            request_ip=request_ip,
            retryable=False,
        )
        raise GovernanceRunProcessingError("check_findings_contract_failed")
    except SQLAlchemyError:
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code="check_findings_persistence_failed",
            request_ip=request_ip,
        )
        raise GovernanceRunProcessingError("check_findings_persistence_failed")


def _verify_snapshot_artifact(*, session: Session, snapshot: SourceSnapshot) -> None:
    artifact = session.exec(
        select(Artifact).where(
            Artifact.id == snapshot.artifact_id,
            Artifact.tenant_id == snapshot.tenant_id,
        )
    ).one()
    file_hash, byte_size = _file_sha256(_artifact_path(artifact))
    if (
        file_hash != artifact.sha256
        or file_hash != snapshot.content_sha256
        or byte_size != artifact.byte_size
    ):
        _execution_error("snapshot_artifact_changed")


def _stage4_check_payload(
    *, run: GovernanceRun, observations: list[Observation]
) -> tuple[Any, dict[str, Any]]:
    differences = check_ip_differences(
        [_ip_observation_from_model(observation) for observation in observations]
    )
    payload = {
        "processing_contract_version": run.processing_contract_version,
        "differences": differences.as_dict(),
        "resource_keys": sorted(
            {str(observation.canonical_ip) for observation in observations}
        ),
    }
    return differences, payload


def _publish_stage4_run(
    *, session: Session, run: GovernanceRun, request_ip: str | None
) -> None:
    snapshots = session.exec(
        select(SourceSnapshot).where(
            SourceSnapshot.governance_run_id == run.id,
            SourceSnapshot.project_id == run.project_id,
            SourceSnapshot.tenant_id == run.tenant_id,
        )
    ).all()
    publish_input_hash = _fingerprint(
        {
            "processing_contract_version": run.processing_contract_version,
            "snapshot_hashes": sorted(
                snapshot.content_sha256 for snapshot in snapshots
            ),
        }
    )
    step, created = _begin_step_or_fail(
        session=session,
        run=run,
        step_code=RunStepCode.PUBLISH,
        input_hash=publish_input_hash,
        request_ip=request_ip,
    )
    if not created:
        if step.status == RunStepStatus.SUCCEEDED.value:
            return
        _execution_error("runner_step_already_started")
    try:
        customer_snapshot, cloudatlas_snapshot = _stage4_snapshots(
            session=session, run=run
        )
        _verify_snapshot_artifact(session=session, snapshot=customer_snapshot)
        _verify_snapshot_artifact(session=session, snapshot=cloudatlas_snapshot)
        check_step = session.exec(
            select(RunStep).where(
                RunStep.governance_run_id == run.id,
                RunStep.step_code == RunStepCode.CHECK_FINDINGS.value,
            )
        ).one_or_none()
        if (
            check_step is None
            or check_step.status != RunStepStatus.SUCCEEDED.value
            or check_step.output_hash is None
        ):
            _processing_error("check_findings_step_incomplete")
        observations = sorted(
            session.exec(
                select(Observation).where(
                    Observation.governance_run_id == run.id,
                    Observation.project_id == run.project_id,
                    Observation.tenant_id == run.tenant_id,
                )
            ).all(),
            key=lambda observation: ip_observation_sort_key(
                observation.source_type,
                observation.source_record_key,
                observation.id,
            ),
        )
        link_observation_ids = session.exec(
            select(col(ObservationResourceLink.observation_id)).where(
                ObservationResourceLink.governance_run_id == run.id,
                ObservationResourceLink.project_id == run.project_id,
                ObservationResourceLink.tenant_id == run.tenant_id,
            )
        ).all()
        if len(link_observation_ids) != len(observations) or set(
            link_observation_ids
        ) != {observation.id for observation in observations}:
            _processing_error("publish_links_incomplete")
        differences, check_payload = _stage4_check_payload(
            run=run, observations=observations
        )
        if _fingerprint(check_payload) != check_step.output_hash:
            _processing_error("check_findings_hash_changed")
        canonical_keys = sorted(
            {str(observation.canonical_ip) for observation in observations}
        )
        resources = session.exec(
            select(Resource).where(
                Resource.project_id == run.project_id,
                Resource.tenant_id == run.tenant_id,
                col(Resource.resource_type) == ResourceType.IP.value,
                col(Resource.canonical_key).in_(canonical_keys),
            )
        ).all()
        resources_by_key = {
            str(resource.canonical_key): resource for resource in resources
        }
        if set(resources_by_key) != set(canonical_keys):
            _processing_error("publish_resources_incomplete")
        observations_by_ip: defaultdict[str, list[Observation]] = defaultdict(list)
        for observation in observations:
            observations_by_ip[str(observation.canonical_ip)].append(observation)
        differences_by_type = (
            (
                "UNREPORTED_ASSET",
                differences.cloudatlas_only,
                IP_CLOUDATLAS_SOURCE_TYPE,
            ),
            (
                "UNOBSERVED_ASSET",
                differences.customer_upload_only,
                IP_CUSTOMER_UPLOAD_SOURCE_TYPE,
            ),
        )
        published_occurrence_count = 0
        published_transition_count = 0
        detected_at = get_datetime_utc()
        for finding_type, canonical_ips, appearing_source_type in differences_by_type:
            for canonical_ip in canonical_ips:
                resource = resources_by_key.get(canonical_ip)
                if resource is None:
                    _processing_error("publish_resource_missing")
                assert resource is not None
                finding = session.exec(
                    select(Finding).where(
                        Finding.project_id == run.project_id,
                        Finding.tenant_id == run.tenant_id,
                        Finding.finding_type == finding_type,
                        Finding.resource_id == resource.id,
                    )
                ).one_or_none()
                is_new_finding = finding is None
                if finding is None:
                    finding = Finding(
                        tenant_id=run.tenant_id,
                        project_id=run.project_id,
                        resource_id=resource.id,
                        finding_type=finding_type,
                        dedupe_key=f"{finding_type}:{canonical_ip}",
                        status="OPEN",
                        first_detected_at=detected_at,
                        last_detected_at=detected_at,
                    )
                    session.add(finding)
                    session.flush()
                else:
                    if finding.status == "OPEN":
                        finding.last_detected_at = detected_at
                        finding.updated_at = detected_at
                        session.add(finding)
                occurrence = session.exec(
                    select(FindingOccurrence).where(
                        FindingOccurrence.finding_id == finding.id,
                        FindingOccurrence.governance_run_id == run.id,
                    )
                ).one_or_none()
                if occurrence is None:
                    occurrence = FindingOccurrence(
                        tenant_id=run.tenant_id,
                        project_id=run.project_id,
                        finding_id=finding.id,
                        governance_run_id=run.id,
                    )
                    session.add(occurrence)
                    session.flush()
                    appearing_observations = [
                        observation
                        for observation in observations_by_ip[canonical_ip]
                        if observation.source_type == appearing_source_type
                    ]
                    session.add_all(
                        FindingOccurrenceObservation(
                            tenant_id=run.tenant_id,
                            project_id=run.project_id,
                            governance_run_id=run.id,
                            finding_occurrence_id=occurrence.id,
                            observation_id=observation.id,
                        )
                        for observation in appearing_observations
                    )
                    session.add_all(
                        (
                            FindingOccurrenceSnapshot(
                                tenant_id=run.tenant_id,
                                project_id=run.project_id,
                                governance_run_id=run.id,
                                finding_occurrence_id=occurrence.id,
                                source_snapshot_id=customer_snapshot.id,
                            ),
                            FindingOccurrenceSnapshot(
                                tenant_id=run.tenant_id,
                                project_id=run.project_id,
                                governance_run_id=run.id,
                                finding_occurrence_id=occurrence.id,
                                source_snapshot_id=cloudatlas_snapshot.id,
                            ),
                        )
                    )
                    published_occurrence_count += 1
                if is_new_finding:
                    transition = FindingTransition(
                        tenant_id=run.tenant_id,
                        project_id=run.project_id,
                        finding_id=finding.id,
                        governance_run_id=run.id,
                        transition_type="OPENED",
                    )
                    session.add(transition)
                    session.flush()
                    occurrence_observations = session.exec(
                        select(FindingOccurrenceObservation).where(
                            FindingOccurrenceObservation.finding_occurrence_id
                            == occurrence.id
                        )
                    ).all()
                    session.add_all(
                        FindingTransitionObservation(
                            tenant_id=run.tenant_id,
                            project_id=run.project_id,
                            governance_run_id=run.id,
                            finding_transition_id=transition.id,
                            observation_id=reference.observation_id,
                        )
                        for reference in occurrence_observations
                    )
                    session.add_all(
                        (
                            FindingTransitionSnapshot(
                                tenant_id=run.tenant_id,
                                project_id=run.project_id,
                                governance_run_id=run.id,
                                finding_transition_id=transition.id,
                                source_snapshot_id=customer_snapshot.id,
                            ),
                            FindingTransitionSnapshot(
                                tenant_id=run.tenant_id,
                                project_id=run.project_id,
                                governance_run_id=run.id,
                                finding_transition_id=transition.id,
                                source_snapshot_id=cloudatlas_snapshot.id,
                            ),
                        )
                    )
                    published_transition_count += 1
        completed_at = get_datetime_utc()
        step.status = RunStepStatus.SUCCEEDED.value
        step.output_hash = _fingerprint(
            {
                "processing_contract_version": run.processing_contract_version,
                "check_findings_output_hash": check_step.output_hash,
            }
        )
        step.completed_at = completed_at
        step.updated_at = completed_at
        run.status = GovernanceRunStatus.COMPLETED.value
        run.completed_at = completed_at
        run.session_recovery_code = None
        run.updated_at = completed_at
        project = session.exec(
            select(Project)
            .where(
                Project.id == run.project_id,
                Project.tenant_id == run.tenant_id,
            )
            .with_for_update()
        ).one()
        project.latest_completed_run_id = run.id
        project.updated_at = completed_at
        session.add(step)
        session.add(run)
        session.add(project)
        session.add(
            _audit_event(
                run=run,
                action="run_step.succeeded",
                target_type="run_step",
                target_id=step.id,
                before_data={"status": RunStepStatus.RUNNING.value},
                after_data={
                    "step_code": step.step_code,
                    "status": step.status,
                    "output_hash": step.output_hash,
                },
                request_ip=request_ip,
            )
        )
        session.add(
            _audit_event(
                run=run,
                action="governance_run.published",
                target_type="governance_run",
                target_id=run.id,
                before_data={"status": GovernanceRunStatus.RUNNING.value},
                after_data={
                    "status": run.status,
                    "source_snapshot_count": 2,
                    "observation_count": len(observations),
                    "resource_count": len(resources_by_key),
                    "finding_count": published_occurrence_count,
                    "transition_count": published_transition_count,
                },
                request_ip=request_ip,
            )
        )
        session.commit()
    except (GovernanceRunProcessingError, IPRecordContractError):
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code="publish_contract_failed",
            request_ip=request_ip,
            retryable=False,
        )
        raise GovernanceRunProcessingError("publish_contract_failed")
    except GovernanceRunExecutionError:
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code="publish_failed",
            request_ip=request_ip,
        )
        raise GovernanceRunExecutionError("publish_failed")
    except SQLAlchemyError:
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code="publish_failed",
            request_ip=request_ip,
        )
        raise GovernanceRunExecutionError("publish_failed")


def _publish_run(
    *, session: Session, run: GovernanceRun, request_ip: str | None
) -> None:
    if run.processing_contract_version is not None:
        _publish_stage4_run(session=session, run=run, request_ip=request_ip)
        return
    snapshots = session.exec(
        select(SourceSnapshot).where(SourceSnapshot.governance_run_id == run.id)
    ).all()
    publish_input_hash = _fingerprint(
        sorted(snapshot.content_sha256 for snapshot in snapshots)
    )
    step, created = _begin_step_or_fail(
        session=session,
        run=run,
        step_code=RunStepCode.PUBLISH,
        input_hash=publish_input_hash,
        request_ip=request_ip,
    )
    if not created:
        _execution_error("runner_step_already_started")
    try:
        if {snapshot.source_type for snapshot in snapshots} != {
            SourceSnapshotType.CUSTOMER_UPLOAD.value,
            SourceSnapshotType.CLOUDATLAS.value,
        }:
            _execution_error("publish_snapshots_incomplete")
        for snapshot in snapshots:
            if (
                snapshot.project_id != run.project_id
                or snapshot.tenant_id != run.tenant_id
                or (
                    snapshot.source_type == SourceSnapshotType.CUSTOMER_UPLOAD.value
                    and snapshot.customer_upload_id != run.customer_upload_id
                )
                or (
                    snapshot.source_type == SourceSnapshotType.CLOUDATLAS.value
                    and snapshot.source_instance_id != run.source_instance_id
                )
            ):
                _execution_error("publish_snapshot_scope_invalid")
            _verify_snapshot_artifact(session=session, snapshot=snapshot)
        project = session.exec(
            select(Project).where(Project.id == run.project_id).with_for_update()
        ).one()
        completed_at = get_datetime_utc()
        step.status = RunStepStatus.SUCCEEDED.value
        step.output_hash = publish_input_hash
        step.completed_at = completed_at
        step.updated_at = completed_at
        run.status = GovernanceRunStatus.COMPLETED.value
        run.completed_at = completed_at
        run.updated_at = completed_at
        project.latest_completed_run_id = run.id
        project.updated_at = completed_at
        step_event = _audit_event(
            run=run,
            action="run_step.succeeded",
            target_type="run_step",
            target_id=step.id,
            before_data={"status": RunStepStatus.RUNNING.value},
            after_data={"step_code": step.step_code, "status": step.status},
            request_ip=request_ip,
        )
        publish_event = _audit_event(
            run=run,
            action="governance_run.published",
            target_type="governance_run",
            target_id=run.id,
            before_data={"status": GovernanceRunStatus.RUNNING.value},
            after_data={
                "status": run.status,
                "source_snapshot_count": 2,
            },
            request_ip=request_ip,
        )
        session.add(step)
        session.add(run)
        session.add(project)
        session.add(step_event)
        session.add(publish_event)
        session.commit()
    except (GovernanceRunExecutionError, SQLAlchemyError):
        session.rollback()
        _fail_run(
            session=session,
            run=run,
            step=step,
            run_status=GovernanceRunStatus.FAILED_PROCESSING,
            error_code="publish_failed",
            request_ip=request_ip,
        )
        raise GovernanceRunExecutionError("publish_failed")


def pinned_inputs_for_run(run: GovernanceRun) -> PinnedTriggerInputs:
    return PinnedTriggerInputs(
        project_id=run.project_id,
        tenant_id=run.tenant_id,
        customer_upload_id=run.customer_upload_id,
        customer_upload_sha256=run.customer_upload_sha256,
        customer_upload_profile_id=run.customer_upload_profile_id,
        customer_upload_profile_version=run.customer_upload_profile_version,
        source_instance_id=run.source_instance_id,
        cloudatlas_validated_fingerprint=run.cloudatlas_validated_fingerprint,
        cloudatlas_capset_id=run.cloudatlas_capset_id,
        cloudatlas_method=run.cloudatlas_method,
        package_sha256=run.package_sha256,
        descriptor_sha256=run.descriptor_sha256,
        runner_build_version=run.runner_build_version,
        processing_contract_version=run.processing_contract_version,
    )


def require_retry_readiness(
    *,
    session: Session,
    project: Project,
    run: GovernanceRun,
    verify_current_fingerprint: bool = True,
) -> PinnedTriggerInputs:
    if project.governance_launch_trigger_id is not None:
        raise GovernanceRunStateError("run_launch_in_progress")
    latest = session.exec(
        select(GovernanceRun)
        .where(GovernanceRun.project_id == project.id)
        .order_by(
            col(GovernanceRun.created_at).desc(),
            col(GovernanceRun.id).desc(),
        )
    ).first()
    if latest is None or latest.id != run.id:
        raise GovernanceRunStateError("run_retry_newer_run_exists")
    if run.status in COMPLETED_RUN_STATUSES:
        raise GovernanceRunStateError("run_retry_completed")
    if run.session_recovery_code is not None and run.session_recovery_code.startswith(
        _NON_RETRYABLE_PREFIX
    ):
        raise GovernanceRunStateError("run_processing_not_retryable")
    if project.archived_at is not None:
        raise GovernanceRunStateError("run_project_archived")
    upload = session.exec(
        select(CustomerUpload).where(
            CustomerUpload.id == run.customer_upload_id,
            CustomerUpload.project_id == run.project_id,
            CustomerUpload.tenant_id == run.tenant_id,
        )
    ).one_or_none()
    if (
        upload is None
        or project.current_customer_upload_id != run.customer_upload_id
        or upload.raw_sha256 != run.customer_upload_sha256
        or upload.profile_id != run.customer_upload_profile_id
        or upload.profile_version != run.customer_upload_profile_version
    ):
        raise GovernanceRunStateError("run_retry_customer_input_changed")
    source = session.exec(
        select(SourceInstance).where(
            SourceInstance.id == run.source_instance_id,
            SourceInstance.project_id == run.project_id,
            SourceInstance.tenant_id == run.tenant_id,
        )
    ).one_or_none()
    if (
        source is None
        or not source.enabled
        or source.capset_id != run.cloudatlas_capset_id
        or source.validated_fingerprint != run.cloudatlas_validated_fingerprint
        or run.cloudatlas_method != METHOD
        or run.package_sha256 != PACKAGE_SHA256
        or run.descriptor_sha256 != DESCRIPTOR_SHA256
        or run.runner_build_version != settings.RUNNER_BUILD_VERSION
    ):
        raise GovernanceRunStateError("run_retry_cloudatlas_input_changed")
    if source.validation_error_code is not None:
        raise GovernanceRunStateError("run_cloudatlas_source_not_ready")
    if not settings.CLOUDATLAS_CAPSET_TOKEN.get_secret_value():
        raise GovernanceRunStateError("run_cloudatlas_credential_not_ready")
    if verify_current_fingerprint:
        try:
            current = OctobusCloudAtlasClient().current_fingerprint(source)
        except CloudAtlasBoundaryError:
            raise GovernanceRunStateError("run_retry_cloudatlas_input_unavailable")
        if current.value != run.cloudatlas_validated_fingerprint:
            raise GovernanceRunStateError("run_retry_cloudatlas_input_changed")
    return pinned_inputs_for_run(run)


def converge_terminal_run(
    *,
    session: Session,
    run: GovernanceRun,
    actor_subject: str,
    request_ip: str | None,
) -> None:
    if run.status != GovernanceRunStatus.RUNNING.value:
        return
    terminal_at = get_datetime_utc()
    step = session.exec(
        select(RunStep).where(
            RunStep.governance_run_id == run.id,
            RunStep.status == RunStepStatus.RUNNING.value,
        )
    ).first()
    if step is not None:
        step.status = RunStepStatus.FAILED.value
        step.error_code = "session_terminated"
        step.completed_at = terminal_at
        step.updated_at = terminal_at
        session.add(step)
        session.add(
            _audit_event(
                run=run,
                action="run_step.failed",
                target_type="run_step",
                target_id=step.id,
                before_data={"status": RunStepStatus.RUNNING.value},
                after_data={
                    "step_code": step.step_code,
                    "status": step.status,
                    "error_code": step.error_code,
                    "attempt": step.attempt,
                },
                request_ip=request_ip,
                actor_subject=actor_subject,
            )
        )
    run.status = GovernanceRunStatus.FAILED_PROCESSING.value
    run.session_terminal_at = terminal_at
    run.updated_at = terminal_at
    session.add(run)
    session.add(
        _audit_event(
            run=run,
            action="governance_run.session_terminal_converged",
            target_type="governance_run",
            target_id=run.id,
            before_data={"status": GovernanceRunStatus.RUNNING.value},
            after_data={
                "status": run.status,
                "reason": "session_terminated",
            },
            request_ip=request_ip,
            actor_subject=actor_subject,
        )
    )


def prepare_retry(
    *,
    session: Session,
    run: GovernanceRun,
    actor_subject: str,
    request_ip: str | None,
) -> RunStep:
    steps = session.exec(
        select(RunStep)
        .where(RunStep.governance_run_id == run.id)
        .order_by(
            col(RunStep.attempt).asc(),
            col(RunStep.started_at).asc(),
            col(RunStep.id).asc(),
        )
    ).all()
    step = next(
        (item for item in steps if item.status == RunStepStatus.FAILED.value),
        None,
    )
    started_new_step = step is None
    attempted_at = get_datetime_utc()
    if step is None:
        existing_codes = {item.step_code for item in steps}
        step_order = (
            (
                RunStepCode.LOAD_CUSTOMER,
                RunStepCode.PULL_CLOUDATLAS,
                RunStepCode.NORMALIZE,
                RunStepCode.RESOLVE,
                RunStepCode.CHECK_FINDINGS,
                RunStepCode.PUBLISH,
            )
            if run.processing_contract_version is not None
            else (
                RunStepCode.LOAD_CUSTOMER,
                RunStepCode.PULL_CLOUDATLAS,
                RunStepCode.PUBLISH,
            )
        )
        next_code = next(
            (code for code in step_order if code.value not in existing_codes),
            None,
        )
        if next_code is None:
            raise GovernanceRunStateError("run_retry_no_failed_step")
        snapshots = session.exec(
            select(SourceSnapshot).where(SourceSnapshot.governance_run_id == run.id)
        ).all()
        snapshot_hashes = sorted(snapshot.content_sha256 for snapshot in snapshots)
        if next_code is RunStepCode.LOAD_CUSTOMER:
            input_hash = run.customer_upload_sha256
        elif next_code is RunStepCode.PULL_CLOUDATLAS:
            input_hash = run.cloudatlas_validated_fingerprint
        elif next_code is RunStepCode.NORMALIZE:
            input_hash = _fingerprint(
                {
                    "processing_contract_version": run.processing_contract_version,
                    "snapshot_hashes": snapshot_hashes,
                }
            )
        elif next_code is RunStepCode.RESOLVE:
            normalize_step = next(
                (
                    item
                    for item in steps
                    if item.step_code == RunStepCode.NORMALIZE.value
                ),
                None,
            )
            if normalize_step is None or normalize_step.output_hash is None:
                raise GovernanceRunStateError("run_retry_no_failed_step")
            input_hash = _fingerprint(
                {
                    "processing_contract_version": run.processing_contract_version,
                    "normalize_output_hash": normalize_step.output_hash,
                }
            )
        elif next_code is RunStepCode.CHECK_FINDINGS:
            resolve_step = next(
                (
                    item
                    for item in steps
                    if item.step_code == RunStepCode.RESOLVE.value
                ),
                None,
            )
            if resolve_step is None or resolve_step.output_hash is None:
                raise GovernanceRunStateError("run_retry_no_failed_step")
            input_hash = _fingerprint(
                {
                    "processing_contract_version": run.processing_contract_version,
                    "resolve_output_hash": resolve_step.output_hash,
                }
            )
        else:
            input_hash = (
                _fingerprint(
                    {
                        "processing_contract_version": run.processing_contract_version,
                        "snapshot_hashes": snapshot_hashes,
                    }
                )
                if run.processing_contract_version is not None
                else _fingerprint(snapshot_hashes)
            )
        step = RunStep(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            governance_run_id=run.id,
            step_code=next_code.value,
            input_hash=input_hash,
            started_at=attempted_at,
            updated_at=attempted_at,
        )
    else:
        step.status = RunStepStatus.RUNNING.value
        step.attempt += 1
        step.output_hash = None
        step.error_code = None
        step.started_at = attempted_at
        step.completed_at = None
        step.updated_at = attempted_at
    previous_status = run.status
    run.status = GovernanceRunStatus.RUNNING.value
    run.completed_at = None
    run.session_terminal_at = attempted_at
    run.session_recovery_code = "retry_prepared"
    run.updated_at = attempted_at
    session.add(step)
    session.add(run)
    session.add(
        _audit_event(
            run=run,
            action=("run_step.started" if started_new_step else "run_step.attempted"),
            target_type="run_step",
            target_id=step.id,
            before_data=(
                None if started_new_step else {"status": RunStepStatus.FAILED.value}
            ),
            after_data={
                "step_code": step.step_code,
                "status": step.status,
                "attempt": step.attempt,
            },
            request_ip=request_ip,
            actor_subject=actor_subject,
        )
    )
    session.add(
        _audit_event(
            run=run,
            action="governance_run.retry_started",
            target_type="governance_run",
            target_id=run.id,
            before_data={"status": previous_status},
            after_data={
                "status": run.status,
                "session_id": run.session_id,
                "attempt": step.attempt,
            },
            request_ip=request_ip,
            actor_subject=actor_subject,
        )
    )
    session.commit()
    session.refresh(step)
    session.refresh(run)
    return step


def fail_retry_start(
    *,
    session: Session,
    run: GovernanceRun,
    actor_subject: str,
    request_ip: str | None,
) -> None:
    step = session.exec(
        select(RunStep).where(
            RunStep.governance_run_id == run.id,
            RunStep.status == RunStepStatus.RUNNING.value,
        )
    ).first()
    failed_at = get_datetime_utc()
    if step is not None:
        step.status = RunStepStatus.FAILED.value
        step.error_code = "session_not_recoverable"
        step.completed_at = failed_at
        step.updated_at = failed_at
        session.add(step)
    run.status = GovernanceRunStatus.FAILED_PROCESSING.value
    run.session_terminal_at = failed_at
    run.session_recovery_code = "run_session_not_recoverable"
    run.updated_at = failed_at
    session.add(run)
    session.add(
        _audit_event(
            run=run,
            action="governance_run.retry_rejected",
            target_type="governance_run",
            target_id=run.id,
            before_data={"status": GovernanceRunStatus.RUNNING.value},
            after_data={
                "status": run.status,
                "reason": run.session_recovery_code,
            },
            request_ip=request_ip,
            actor_subject=actor_subject,
        )
    )
    session.commit()
    session.refresh(run)


def reconcile_launch_reservation(
    *,
    session: Session,
    project: Project,
    client: AgentComposeClient,
    actor_subject: str,
    request_ip: str | None,
) -> str | None:
    trigger_id = project.governance_launch_trigger_id
    control_run_id = project.governance_launch_control_run_id
    if trigger_id is None or control_run_id is None:
        return None
    control_run = client.get_run(control_run_id)
    if control_run is None:
        return None
    if control_run.session_id is None:
        if not control_run.is_terminal:
            return None
        reason = "control_run_terminated_before_session"
    else:
        control_session = client.get_session(control_run.session_id)
        if (
            control_session is None
            or control_session.observation
            is not AgentComposeSessionObservation.TERMINAL
        ):
            return None
        reason = "session_terminated_before_run"
    project.governance_launch_trigger_id = None
    project.governance_launch_control_run_id = None
    project.governance_launch_input_hash = None
    project.updated_at = get_datetime_utc()
    session.add(project)
    session.add(
        AuditEvent(
            tenant_id=project.tenant_id,
            project_id=project.id,
            actor_subject=actor_subject,
            actor_type="user",
            action="governance_run.launch_terminal_converged",
            target_type="project",
            target_id=project.id,
            before_data={"trigger_id": trigger_id},
            after_data={"reason": reason},
            ip_address=request_ip,
        )
    )
    return trigger_id


def reserve_run_launch(
    *,
    session: Session,
    project: Project,
    trigger_id: str,
    control_run_id: str,
    pinned: PinnedTriggerInputs,
) -> bool:
    input_hash = pinned.input_hash()
    if project.governance_launch_trigger_id is not None:
        if (
            project.governance_launch_trigger_id == trigger_id
            and project.governance_launch_control_run_id == control_run_id
            and project.governance_launch_input_hash == input_hash
        ):
            return False
        raise GovernanceRunStateError("run_launch_in_progress")
    project.governance_launch_trigger_id = trigger_id
    project.governance_launch_control_run_id = control_run_id
    project.governance_launch_input_hash = input_hash
    project.updated_at = get_datetime_utc()
    session.add(project)
    return True


def rerun_request_was_recorded(
    *, session: Session, source_run: GovernanceRun, trigger_id: str
) -> bool:
    requests = session.exec(
        select(AuditEvent.after_data).where(
            AuditEvent.target_id == source_run.id,
            AuditEvent.action == "governance_run.rerun_requested",
        )
    ).all()
    return any(
        isinstance(data, dict) and data.get("trigger_id") == trigger_id
        for data in requests
    )


def record_run_action(
    *,
    session: Session,
    run: GovernanceRun,
    action: str,
    actor_subject: str,
    request_ip: str | None,
    after_data: dict[str, Any],
) -> None:
    session.add(
        _audit_event(
            run=run,
            action=action,
            target_type="governance_run",
            target_id=run.id,
            before_data={"status": run.status},
            after_data=after_data,
            request_ip=request_ip,
            actor_subject=actor_subject,
        )
    )
    session.commit()


def record_project_action(
    *,
    session: Session,
    project: Project,
    action: str,
    actor_subject: str,
    request_ip: str | None,
    after_data: dict[str, Any],
) -> None:
    session.add(
        AuditEvent(
            tenant_id=project.tenant_id,
            project_id=project.id,
            actor_subject=actor_subject,
            actor_type="user",
            action=action,
            target_type="project",
            target_id=project.id,
            before_data=None,
            after_data=after_data,
            ip_address=request_ip,
        )
    )
    session.commit()


def execute_governance_run(*, session: Session, inputs: RunnerInputs) -> GovernanceRun:
    run = establish_governance_run(session=session, inputs=inputs)
    if run.status != GovernanceRunStatus.RUNNING.value:
        return run
    _load_customer_snapshot(session=session, run=run, request_ip=None)
    _pull_cloudatlas_snapshot(session=session, run=run, request_ip=None)
    if run.processing_contract_version is not None:
        _normalize_ip_observations(session=session, run=run, request_ip=None)
        _resolve_ip_observations(session=session, run=run, request_ip=None)
        _check_ip_findings(session=session, run=run, request_ip=None)
    _publish_run(session=session, run=run, request_ip=None)
    session.refresh(run)
    return run


def governance_run_public(
    *, session: Session, run: GovernanceRun
) -> GovernanceRunPublic:
    steps = session.exec(
        select(RunStep).where(RunStep.governance_run_id == run.id)
    ).all()
    snapshots = session.exec(
        select(SourceSnapshot).where(SourceSnapshot.governance_run_id == run.id)
    ).all()
    reused_snapshot_count = 0
    retry_started = session.exec(
        select(AuditEvent.id).where(
            AuditEvent.target_id == run.id,
            AuditEvent.action == "governance_run.retry_started",
        )
    ).first()
    if retry_started is not None:
        attempts = {step.step_code: step.attempt for step in steps}
        reused_snapshot_count = sum(
            attempts.get(
                RunStepCode.LOAD_CUSTOMER.value
                if snapshot.source_type == SourceSnapshotType.CUSTOMER_UPLOAD.value
                else RunStepCode.PULL_CLOUDATLAS.value
            )
            == 1
            for snapshot in snapshots
        )
    return GovernanceRunPublic(
        **run.model_dump(),
        steps=[
            RunStepPublic.model_validate(step)
            for step in sorted(steps, key=lambda item: _STEP_ORDER[item.step_code])
        ],
        snapshots=[
            SourceSnapshotPublic.model_validate(snapshot)
            for snapshot in sorted(snapshots, key=lambda item: item.source_type)
        ],
        reused_snapshot_count=reused_snapshot_count,
    )


def list_project_runs(
    *, session: Session, project_id: uuid.UUID
) -> list[GovernanceRun]:
    return list(
        session.exec(
            select(GovernanceRun)
            .where(GovernanceRun.project_id == project_id)
            .order_by(
                col(GovernanceRun.created_at).desc(),
                col(GovernanceRun.id).desc(),
            )
        ).all()
    )
