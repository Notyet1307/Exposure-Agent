import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import SecretStr, field_validator
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB
from sqlmodel import Field, SQLModel

from app.core.time import get_datetime_utc

DEPLOYMENT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class Tenant(SQLModel, table=True):
    __tablename__: ClassVar[str] = "tenants"

    id: uuid.UUID = Field(default=DEPLOYMENT_TENANT_ID, primary_key=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class ProjectBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)


class ProjectCreate(ProjectBase):
    model_config = SQLModel.model_config | {"extra": "forbid"}


class ProjectUpdate(ProjectBase):
    model_config = SQLModel.model_config | {"extra": "forbid"}


class Project(ProjectBase, table=True):
    __tablename__: ClassVar[str] = "projects"
    __table_args__ = (
        CheckConstraint(
            "(governance_launch_trigger_id IS NULL AND "
            "governance_launch_control_run_id IS NULL AND "
            "governance_launch_input_hash IS NULL) OR "
            "(governance_launch_trigger_id IS NOT NULL AND "
            "governance_launch_control_run_id IS NOT NULL AND "
            "governance_launch_input_hash IS NOT NULL)",
            name="ck_projects_governance_launch_complete",
        ),
        ForeignKeyConstraint(
            ["current_customer_upload_profile_id", "id"],
            ["customer_upload_profiles.id", "customer_upload_profiles.project_id"],
            name="fk_projects_current_customer_upload_profile",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["current_customer_upload_id", "id"],
            ["customer_uploads.id", "customer_uploads.project_id"],
            name="fk_projects_current_customer_upload",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["latest_completed_run_id", "id", "tenant_id"],
            [
                "governance_runs.id",
                "governance_runs.project_id",
                "governance_runs.tenant_id",
            ],
            name="fk_projects_latest_completed_run",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_projects_id_tenant"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        default=DEPLOYMENT_TENANT_ID,
        foreign_key="tenants.id",
        ondelete="RESTRICT",
        index=True,
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    archived_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    current_customer_upload_profile_id: uuid.UUID = Field(index=True)
    current_customer_upload_id: uuid.UUID | None = Field(default=None, index=True)
    latest_completed_run_id: uuid.UUID | None = Field(default=None, index=True)
    governance_launch_trigger_id: str | None = Field(default=None, max_length=255)
    governance_launch_control_run_id: str | None = Field(default=None, max_length=64)
    governance_launch_input_hash: str | None = Field(default=None, max_length=64)


class ProjectPublic(ProjectBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class ProjectsPublic(SQLModel):
    data: list[ProjectPublic]
    count: int


class CustomerUploadProfileDefinition(SQLModel):
    model_config = SQLModel.model_config | {"extra": "forbid"}

    required_headers: list[str]
    warning_headers: list[str]
    optional_headers: list[str]


class CustomerUploadProfile(SQLModel, table=True):
    __tablename__: ClassVar[str] = "customer_upload_profiles"
    __table_args__ = (
        CheckConstraint(
            "version > 0", name="ck_customer_upload_profiles_version_positive"
        ),
        UniqueConstraint(
            "id", "project_id", name="uq_customer_upload_profiles_id_project"
        ),
        UniqueConstraint(
            "id",
            "project_id",
            "version",
            name="uq_customer_upload_profiles_id_project_version",
        ),
        UniqueConstraint(
            "project_id",
            "version",
            name="uq_customer_upload_profiles_project_version",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        default=DEPLOYMENT_TENANT_ID,
        foreign_key="tenants.id",
        ondelete="RESTRICT",
        index=True,
    )
    project_id: uuid.UUID = Field(
        foreign_key="projects.id", ondelete="RESTRICT", index=True
    )
    version: int
    definition: dict[str, Any] = Field(sa_type=JSONB)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class CustomerUploadProfilePublic(CustomerUploadProfileDefinition):
    id: uuid.UUID
    version: int


class Artifact(SQLModel, table=True):
    __tablename__: ClassVar[str] = "artifacts"
    __table_args__ = (
        CheckConstraint("byte_size > 0", name="ck_artifacts_byte_size_positive"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_artifacts_sha256_format"),
        CheckConstraint(
            "governance_run_id IS NULL OR project_id IS NOT NULL",
            name="ck_artifacts_governance_run_project",
        ),
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["projects.id", "projects.tenant_id"],
            name="fk_artifacts_project_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["governance_run_id", "project_id", "tenant_id"],
            [
                "governance_runs.id",
                "governance_runs.project_id",
                "governance_runs.tenant_id",
            ],
            name="fk_artifacts_governance_run_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_artifacts_id_tenant"),
        UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            "sha256",
            name="uq_artifacts_report_scope_hash",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        default=DEPLOYMENT_TENANT_ID,
        foreign_key="tenants.id",
        ondelete="RESTRICT",
        index=True,
    )
    project_id: uuid.UUID | None = Field(default=None, index=True)
    governance_run_id: uuid.UUID | None = Field(default=None, index=True)
    storage_key: str = Field(max_length=255, unique=True)
    media_type: str = Field(max_length=255)
    byte_size: int
    sha256: str = Field(max_length=64, index=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class CustomerUploadWarningPublic(SQLModel):
    code: str
    field: str | None
    count: int


class CustomerUpload(SQLModel, table=True):
    __tablename__: ClassVar[str] = "customer_uploads"
    __table_args__ = (
        CheckConstraint(
            "raw_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_customer_uploads_raw_sha256_format",
        ),
        CheckConstraint(
            "profile_version > 0",
            name="ck_customer_uploads_profile_version_positive",
        ),
        CheckConstraint(
            "record_count > 0", name="ck_customer_uploads_record_count_positive"
        ),
        ForeignKeyConstraint(
            ["profile_id", "project_id", "profile_version"],
            [
                "customer_upload_profiles.id",
                "customer_upload_profiles.project_id",
                "customer_upload_profiles.version",
            ],
            name="fk_customer_uploads_profile_project_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "project_id", name="uq_customer_uploads_id_project"),
        UniqueConstraint(
            "id",
            "project_id",
            "tenant_id",
            name="uq_customer_uploads_scope",
        ),
        UniqueConstraint(
            "project_id",
            "raw_sha256",
            "profile_id",
            "profile_version",
            name="uq_customer_uploads_idempotency",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        default=DEPLOYMENT_TENANT_ID,
        foreign_key="tenants.id",
        ondelete="RESTRICT",
        index=True,
    )
    project_id: uuid.UUID = Field(
        foreign_key="projects.id", ondelete="RESTRICT", index=True
    )
    artifact_id: uuid.UUID = Field(
        foreign_key="artifacts.id", ondelete="RESTRICT", unique=True
    )
    display_filename: str = Field(max_length=128)
    raw_sha256: str = Field(max_length=64, index=True)
    profile_id: uuid.UUID = Field(index=True)
    profile_version: int
    record_count: int
    warnings: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSONB)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class CustomerUploadPublic(SQLModel):
    id: uuid.UUID
    display_filename: str
    raw_sha256: str
    record_count: int
    profile_id: uuid.UUID
    profile_version: int
    warnings: list[CustomerUploadWarningPublic]
    created_at: datetime


class CustomerUploadsPublic(SQLModel):
    data: list[CustomerUploadPublic]
    count: int
    current_customer_upload_id: uuid.UUID | None
    can_upload: bool
    can_select: bool


CLOUDATLAS_SOURCE_TYPE = "cloudatlas"


class CloudAtlasSourceBinding(SQLModel):
    instance_id: str = Field(min_length=1, max_length=255)
    capset_id: str = Field(min_length=1, max_length=255)

    @field_validator("instance_id", "capset_id")
    @classmethod
    def octobus_id_must_be_path_safe(cls, value: str) -> str:
        if value != value.strip() or any(
            character in "/?#\\" or ord(character) < 32 for character in value
        ):
            raise ValueError("OctoBus identifiers must be path-safe")
        return value


class CloudAtlasSourceCreate(CloudAtlasSourceBinding):
    model_config = SQLModel.model_config | {"extra": "forbid"}


class CloudAtlasSourceUpdate(CloudAtlasSourceBinding):
    model_config = SQLModel.model_config | {"extra": "forbid"}


class CloudAtlasSourceValidationRequest(SQLModel):
    model_config = SQLModel.model_config | {"extra": "forbid"}

    capset_token: SecretStr = Field(min_length=1, max_length=4096)


class SourceInstance(SQLModel, table=True):
    __tablename__: ClassVar[str] = "source_instances"
    __table_args__ = (
        CheckConstraint("source_type = 'cloudatlas'", name="ck_source_instances_type"),
        CheckConstraint(
            "validated_fingerprint IS NULL OR validated_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_source_instances_fingerprint_format",
        ),
        UniqueConstraint("id", "project_id", name="uq_source_instances_id_project"),
        UniqueConstraint(
            "id",
            "project_id",
            "tenant_id",
            name="uq_source_instances_scope",
        ),
        Index(
            "uq_source_instances_one_enabled_type_per_project",
            "project_id",
            "source_type",
            unique=True,
            postgresql_where=text("enabled"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        default=DEPLOYMENT_TENANT_ID,
        foreign_key="tenants.id",
        ondelete="RESTRICT",
        index=True,
    )
    project_id: uuid.UUID = Field(
        foreign_key="projects.id", ondelete="RESTRICT", index=True
    )
    source_type: str = Field(default=CLOUDATLAS_SOURCE_TYPE, max_length=30)
    instance_id: str = Field(max_length=255)
    capset_id: str = Field(max_length=255)
    enabled: bool = Field(default=False)
    validated_fingerprint: str | None = Field(default=None, max_length=64)
    validated_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    validation_error_code: str | None = Field(default=None, max_length=100)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class CloudAtlasSourcePublic(SQLModel):
    id: uuid.UUID
    source_type: str
    instance_id: str
    capset_id: str
    enabled: bool
    validation_status: str
    fingerprint_summary: str | None
    created_at: datetime
    updated_at: datetime


class CloudAtlasSourcesPublic(SQLModel):
    data: list[CloudAtlasSourcePublic]
    count: int
    can_manage: bool


class GovernanceRunStatus(StrEnum):
    RUNNING = "RUNNING"
    FAILED_DATA = "FAILED_DATA"
    FAILED_PROCESSING = "FAILED_PROCESSING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"


class RunStepCode(StrEnum):
    LOAD_CUSTOMER = "LOAD_CUSTOMER"
    PULL_CLOUDATLAS = "PULL_CLOUDATLAS"
    NORMALIZE = "NORMALIZE"
    RESOLVE = "RESOLVE"
    CHECK_FINDINGS = "CHECK_FINDINGS"
    BUILD_REPORT = "BUILD_REPORT"
    VALIDATE_REPORT = "VALIDATE_REPORT"
    PUBLISH = "PUBLISH"


class RunStepStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class SourceSnapshotType(StrEnum):
    CUSTOMER_UPLOAD = "CUSTOMER_UPLOAD"
    CLOUDATLAS = "CLOUDATLAS"


class ResourceType(StrEnum):
    IP = "IP"


class FindingType(StrEnum):
    UNREPORTED_ASSET = "UNREPORTED_ASSET"
    UNOBSERVED_ASSET = "UNOBSERVED_ASSET"


class FindingStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FindingTransitionType(StrEnum):
    OPENED = "OPENED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class GovernanceRun(SQLModel, table=True):
    __tablename__: ClassVar[str] = "governance_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'FAILED_DATA', 'FAILED_PROCESSING', "
            "'COMPLETED', 'COMPLETED_WITH_WARNINGS')",
            name="ck_governance_runs_status",
        ),
        CheckConstraint(
            "customer_upload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_governance_runs_customer_sha256",
        ),
        CheckConstraint(
            "cloudatlas_validated_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_governance_runs_cloudatlas_fingerprint",
        ),
        CheckConstraint(
            "package_sha256 ~ '^[0-9a-f]{64}$' AND "
            "descriptor_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_governance_runs_package_fingerprints",
        ),
        CheckConstraint(
            "customer_upload_profile_version > 0",
            name="ck_governance_runs_profile_version_positive",
        ),
        CheckConstraint(
            "processing_contract_version IS NULL OR "
            "btrim(processing_contract_version) <> ''",
            name="ck_governance_runs_processing_contract_version",
        ),
        CheckConstraint(
            "report_contract_version IS NULL OR btrim(report_contract_version) <> ''",
            name="ck_governance_runs_report_contract_version",
        ),
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["projects.id", "projects.tenant_id"],
            name="fk_governance_runs_project_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["customer_upload_id", "project_id", "tenant_id"],
            [
                "customer_uploads.id",
                "customer_uploads.project_id",
                "customer_uploads.tenant_id",
            ],
            name="fk_governance_runs_customer_upload_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_instance_id", "project_id", "tenant_id"],
            [
                "source_instances.id",
                "source_instances.project_id",
                "source_instances.tenant_id",
            ],
            name="fk_governance_runs_source_instance_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "customer_upload_profile_id",
                "project_id",
                "customer_upload_profile_version",
            ],
            [
                "customer_upload_profiles.id",
                "customer_upload_profiles.project_id",
                "customer_upload_profiles.version",
            ],
            name="fk_governance_runs_profile_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id", "project_id", "tenant_id", name="uq_governance_runs_scope"
        ),
        UniqueConstraint(
            "id",
            "project_id",
            "tenant_id",
            "report_contract_version",
            name="uq_governance_runs_report_contract_scope",
        ),
        UniqueConstraint("project_id", "trigger_id", name="uq_governance_runs_trigger"),
        UniqueConstraint("session_id", name="uq_governance_runs_session"),
        Index(
            "uq_governance_runs_one_active_per_project",
            "project_id",
            unique=True,
            postgresql_where=text("status = 'RUNNING'"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    trigger_id: str = Field(max_length=255)
    session_id: str = Field(max_length=64)
    requested_by: str = Field(max_length=255)
    status: str = Field(default=GovernanceRunStatus.RUNNING.value, max_length=30)
    customer_upload_id: uuid.UUID = Field(index=True)
    customer_upload_sha256: str = Field(max_length=64)
    customer_upload_profile_id: uuid.UUID = Field(index=True)
    customer_upload_profile_version: int
    source_instance_id: uuid.UUID = Field(index=True)
    cloudatlas_validated_fingerprint: str = Field(max_length=64)
    cloudatlas_capset_id: str = Field(max_length=255)
    cloudatlas_method: str = Field(max_length=255)
    package_sha256: str = Field(max_length=64)
    descriptor_sha256: str = Field(max_length=64)
    runner_build_version: str = Field(max_length=255)
    processing_contract_version: str | None = Field(default=None, max_length=100)
    report_contract_version: str | None = Field(default=None, max_length=100)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    session_terminal_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    session_recovery_code: str | None = Field(default=None, max_length=100)


class GovernanceReport(SQLModel, table=True):
    __tablename__: ClassVar[str] = "governance_reports"
    __table_args__ = (
        CheckConstraint(
            "btrim(report_contract_version) <> ''",
            name="ck_governance_reports_contract_version",
        ),
        CheckConstraint(
            "generation_mode = 'DETERMINISTIC_TEMPLATE'",
            name="ck_governance_reports_generation_mode",
        ),
        CheckConstraint(
            "jsonb_typeof(canonical_content) = 'object' "
            "AND canonical_content <> '{}'::jsonb",
            name="ck_governance_reports_canonical_content",
        ),
        CheckConstraint(
            "html_sha256 ~ '^[0-9a-f]{64}$' "
            "AND csv_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_governance_reports_artifact_hashes",
        ),
        CheckConstraint(
            "html_artifact_id <> csv_artifact_id",
            name="ck_governance_reports_distinct_artifacts",
        ),
        ForeignKeyConstraint(
            [
                "governance_run_id",
                "project_id",
                "tenant_id",
                "report_contract_version",
            ],
            [
                "governance_runs.id",
                "governance_runs.project_id",
                "governance_runs.tenant_id",
                "governance_runs.report_contract_version",
            ],
            name="fk_governance_reports_run_contract_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "html_artifact_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
                "html_sha256",
            ],
            [
                "artifacts.id",
                "artifacts.governance_run_id",
                "artifacts.project_id",
                "artifacts.tenant_id",
                "artifacts.sha256",
            ],
            name="fk_governance_reports_html_artifact_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "csv_artifact_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
                "csv_sha256",
            ],
            [
                "artifacts.id",
                "artifacts.governance_run_id",
                "artifacts.project_id",
                "artifacts.tenant_id",
                "artifacts.sha256",
            ],
            name="fk_governance_reports_csv_artifact_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            name="uq_governance_reports_scope",
        ),
        UniqueConstraint(
            "governance_run_id", name="uq_governance_reports_governance_run"
        ),
        UniqueConstraint(
            "html_artifact_id", name="uq_governance_reports_html_artifact_id"
        ),
        UniqueConstraint(
            "csv_artifact_id", name="uq_governance_reports_csv_artifact_id"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    governance_run_id: uuid.UUID
    report_contract_version: str = Field(max_length=100)
    generation_mode: str = Field(default="DETERMINISTIC_TEMPLATE", max_length=30)
    canonical_content: dict[str, Any] = Field(sa_type=JSONB)
    html_artifact_id: uuid.UUID
    html_sha256: str = Field(max_length=64)
    csv_artifact_id: uuid.UUID
    csv_sha256: str = Field(max_length=64)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class Evidence(SQLModel, table=True):
    __tablename__: ClassVar[str] = "evidence"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(source_snapshot_id, observation_id, "
            "finding_occurrence_id, finding_transition_id) = 1",
            name="ck_evidence_exactly_one_target",
        ),
        ForeignKeyConstraint(
            [
                "governance_report_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
            ],
            [
                "governance_reports.id",
                "governance_reports.governance_run_id",
                "governance_reports.project_id",
                "governance_reports.tenant_id",
            ],
            name="fk_evidence_governance_report_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "source_snapshot_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
            ],
            [
                "source_snapshots.id",
                "source_snapshots.governance_run_id",
                "source_snapshots.project_id",
                "source_snapshots.tenant_id",
            ],
            name="fk_evidence_source_snapshot_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["observation_id", "governance_run_id", "project_id", "tenant_id"],
            [
                "observations.id",
                "observations.governance_run_id",
                "observations.project_id",
                "observations.tenant_id",
            ],
            name="fk_evidence_observation_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "finding_occurrence_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
            ],
            [
                "finding_occurrences.id",
                "finding_occurrences.governance_run_id",
                "finding_occurrences.project_id",
                "finding_occurrences.tenant_id",
            ],
            name="fk_evidence_finding_occurrence_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "finding_transition_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
            ],
            [
                "finding_transitions.id",
                "finding_transitions.governance_run_id",
                "finding_transitions.project_id",
                "finding_transitions.tenant_id",
            ],
            name="fk_evidence_finding_transition_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            name="uq_evidence_scope",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    governance_run_id: uuid.UUID = Field(index=True)
    governance_report_id: uuid.UUID = Field(index=True)
    source_snapshot_id: uuid.UUID | None = Field(default=None, index=True)
    observation_id: uuid.UUID | None = Field(default=None, index=True)
    finding_occurrence_id: uuid.UUID | None = Field(default=None, index=True)
    finding_transition_id: uuid.UUID | None = Field(default=None, index=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class RunStep(SQLModel, table=True):
    __tablename__: ClassVar[str] = "run_steps"
    __table_args__ = (
        CheckConstraint(
            "step_code IN ('LOAD_CUSTOMER', 'PULL_CLOUDATLAS', 'NORMALIZE', "
            "'RESOLVE', 'CHECK_FINDINGS', 'BUILD_REPORT', 'VALIDATE_REPORT', "
            "'PUBLISH')",
            name="ck_run_steps_code",
        ),
        CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_run_steps_status",
        ),
        CheckConstraint("attempt > 0", name="ck_run_steps_attempt_positive"),
        CheckConstraint(
            "input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_run_steps_input_hash",
        ),
        CheckConstraint(
            "output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'",
            name="ck_run_steps_output_hash",
        ),
        ForeignKeyConstraint(
            ["governance_run_id", "project_id", "tenant_id"],
            [
                "governance_runs.id",
                "governance_runs.project_id",
                "governance_runs.tenant_id",
            ],
            name="fk_run_steps_governance_run_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "governance_run_id", "step_code", name="uq_run_steps_run_code"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    governance_run_id: uuid.UUID = Field(index=True)
    step_code: str = Field(max_length=30)
    status: str = Field(default=RunStepStatus.RUNNING.value, max_length=20)
    attempt: int = Field(default=1)
    input_hash: str | None = Field(default=None, max_length=64)
    output_hash: str | None = Field(default=None, max_length=64)
    error_code: str | None = Field(default=None, max_length=100)
    started_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class SourceSnapshot(SQLModel, table=True):
    __tablename__: ClassVar[str] = "source_snapshots"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('CUSTOMER_UPLOAD', 'CLOUDATLAS')",
            name="ck_source_snapshots_type",
        ),
        CheckConstraint(
            "(source_type = 'CUSTOMER_UPLOAD' AND customer_upload_id IS NOT NULL "
            "AND source_instance_id IS NULL AND method_fingerprint IS NULL) OR "
            "(source_type = 'CLOUDATLAS' AND customer_upload_id IS NULL "
            "AND source_instance_id IS NOT NULL AND method_fingerprint IS NOT NULL)",
            name="ck_source_snapshots_source_reference",
        ),
        CheckConstraint("record_count >= 0", name="ck_source_snapshots_record_count"),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$' AND "
            "schema_fingerprint ~ '^[0-9a-f]{64}$' AND "
            "(method_fingerprint IS NULL OR method_fingerprint ~ '^[0-9a-f]{64}$')",
            name="ck_source_snapshots_fingerprints",
        ),
        ForeignKeyConstraint(
            ["governance_run_id", "project_id", "tenant_id"],
            [
                "governance_runs.id",
                "governance_runs.project_id",
                "governance_runs.tenant_id",
            ],
            name="fk_source_snapshots_governance_run_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["customer_upload_id", "project_id", "tenant_id"],
            [
                "customer_uploads.id",
                "customer_uploads.project_id",
                "customer_uploads.tenant_id",
            ],
            name="fk_source_snapshots_customer_upload_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_instance_id", "project_id", "tenant_id"],
            [
                "source_instances.id",
                "source_instances.project_id",
                "source_instances.tenant_id",
            ],
            name="fk_source_snapshots_source_instance_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "tenant_id"],
            ["artifacts.id", "artifacts.tenant_id"],
            name="fk_source_snapshots_artifact_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "governance_run_id", "source_type", name="uq_source_snapshots_run_type"
        ),
        UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            name="uq_source_snapshots_scope",
        ),
        UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            "source_type",
            name="uq_source_snapshots_scope_type",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    governance_run_id: uuid.UUID = Field(index=True)
    source_type: str = Field(max_length=30)
    customer_upload_id: uuid.UUID | None = Field(default=None, index=True)
    source_instance_id: uuid.UUID | None = Field(default=None, index=True)
    artifact_id: uuid.UUID = Field(index=True)
    content_sha256: str = Field(max_length=64)
    schema_fingerprint: str = Field(max_length=64)
    method_fingerprint: str | None = Field(default=None, max_length=64)
    record_count: int
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class Resource(SQLModel, table=True):
    __tablename__: ClassVar[str] = "resources"
    __table_args__ = (
        CheckConstraint("resource_type = 'IP'", name="ck_resources_type"),
        CheckConstraint(
            "masklen(canonical_key) = CASE WHEN family(canonical_key) = 4 "
            "THEN 32 ELSE 128 END",
            name="ck_resources_canonical_ip_host",
        ),
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["projects.id", "projects.tenant_id"],
            name="fk_resources_project_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "project_id", "tenant_id", name="uq_resources_scope"),
        UniqueConstraint(
            "project_id",
            "resource_type",
            "canonical_key",
            name="uq_resources_project_type_key",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    resource_type: str = Field(max_length=30)
    canonical_key: str = Field(sa_type=INET)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class Observation(SQLModel, table=True):
    __tablename__: ClassVar[str] = "observations"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('CUSTOMER_UPLOAD', 'CLOUDATLAS')",
            name="ck_observations_source_type",
        ),
        CheckConstraint(
            "btrim(source_record_key) <> ''",
            name="ck_observations_source_record_key",
        ),
        CheckConstraint("btrim(raw_ip) <> ''", name="ck_observations_raw_ip"),
        CheckConstraint(
            "masklen(canonical_ip) = CASE WHEN family(canonical_ip) = 4 "
            "THEN 32 ELSE 128 END",
            name="ck_observations_canonical_ip_host",
        ),
        CheckConstraint(
            "(source_type = 'CUSTOMER_UPLOAD' AND cloudatlas_asset_id IS NULL "
            "AND cloudatlas_status IS NULL) OR "
            "(source_type = 'CLOUDATLAS' AND cloudatlas_asset_id IS NOT NULL "
            "AND cloudatlas_status IS NOT NULL "
            "AND btrim(cloudatlas_asset_id) <> '' "
            "AND btrim(cloudatlas_status) <> '')",
            name="ck_observations_cloudatlas_fields",
        ),
        ForeignKeyConstraint(
            ["governance_run_id", "project_id", "tenant_id"],
            [
                "governance_runs.id",
                "governance_runs.project_id",
                "governance_runs.tenant_id",
            ],
            name="fk_observations_governance_run_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "source_snapshot_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
                "source_type",
            ],
            [
                "source_snapshots.id",
                "source_snapshots.governance_run_id",
                "source_snapshots.project_id",
                "source_snapshots.tenant_id",
                "source_snapshots.source_type",
            ],
            name="fk_observations_source_snapshot_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            name="uq_observations_scope",
        ),
        UniqueConstraint(
            "source_snapshot_id",
            "source_record_key",
            name="uq_observations_snapshot_record",
        ),
        Index(
            "ix_observations_run_snapshot",
            "governance_run_id",
            "source_snapshot_id",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    governance_run_id: uuid.UUID = Field(index=True)
    source_snapshot_id: uuid.UUID = Field(index=True)
    source_type: str = Field(max_length=30)
    source_record_key: str = Field(max_length=255)
    raw_ip: str = Field(max_length=255)
    canonical_ip: str = Field(sa_type=INET, index=True)
    cloudatlas_asset_id: str | None = Field(default=None, max_length=255)
    cloudatlas_status: str | None = Field(default=None, max_length=30)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class ObservationResourceLink(SQLModel, table=True):
    __tablename__: ClassVar[str] = "observation_resource_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["governance_run_id", "project_id", "tenant_id"],
            [
                "governance_runs.id",
                "governance_runs.project_id",
                "governance_runs.tenant_id",
            ],
            name="fk_observation_resource_links_run_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["observation_id", "governance_run_id", "project_id", "tenant_id"],
            [
                "observations.id",
                "observations.governance_run_id",
                "observations.project_id",
                "observations.tenant_id",
            ],
            name="fk_observation_resource_links_observation_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["resource_id", "project_id", "tenant_id"],
            ["resources.id", "resources.project_id", "resources.tenant_id"],
            name="fk_observation_resource_links_resource_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            name="uq_observation_resource_links_scope",
        ),
        UniqueConstraint(
            "observation_id", name="uq_observation_resource_links_observation"
        ),
        CheckConstraint(
            "btrim(processing_contract_version) <> ''",
            name="ck_observation_resource_links_processing_contract_version",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    governance_run_id: uuid.UUID = Field(index=True)
    observation_id: uuid.UUID = Field(index=True)
    resource_id: uuid.UUID = Field(index=True)
    processing_contract_version: str = Field(max_length=100)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class Finding(SQLModel, table=True):
    __tablename__: ClassVar[str] = "findings"
    __table_args__ = (
        CheckConstraint(
            "finding_type IN ('UNREPORTED_ASSET', 'UNOBSERVED_ASSET')",
            name="ck_findings_type",
        ),
        CheckConstraint("status IN ('OPEN', 'CLOSED')", name="ck_findings_status"),
        CheckConstraint("btrim(dedupe_key) <> ''", name="ck_findings_dedupe_key"),
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["projects.id", "projects.tenant_id"],
            name="fk_findings_project_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["resource_id", "project_id", "tenant_id"],
            ["resources.id", "resources.project_id", "resources.tenant_id"],
            name="fk_findings_resource_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "project_id", "tenant_id", name="uq_findings_scope"),
        UniqueConstraint("project_id", "dedupe_key", name="uq_findings_project_dedupe"),
        UniqueConstraint(
            "project_id",
            "finding_type",
            "resource_id",
            name="uq_findings_project_type_resource",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    resource_id: uuid.UUID = Field(index=True)
    finding_type: str = Field(max_length=50, index=True)
    dedupe_key: str = Field(max_length=255)
    status: str = Field(max_length=20, index=True)
    first_detected_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    last_detected_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class FindingOccurrence(SQLModel, table=True):
    __tablename__: ClassVar[str] = "finding_occurrences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["finding_id", "project_id", "tenant_id"],
            ["findings.id", "findings.project_id", "findings.tenant_id"],
            name="fk_finding_occurrences_finding_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["governance_run_id", "project_id", "tenant_id"],
            [
                "governance_runs.id",
                "governance_runs.project_id",
                "governance_runs.tenant_id",
            ],
            name="fk_finding_occurrences_run_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            name="uq_finding_occurrences_scope",
        ),
        UniqueConstraint(
            "finding_id",
            "governance_run_id",
            name="uq_finding_occurrences_finding_run",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    finding_id: uuid.UUID = Field(index=True)
    governance_run_id: uuid.UUID = Field(index=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class FindingTransition(SQLModel, table=True):
    __tablename__: ClassVar[str] = "finding_transitions"
    __table_args__ = (
        CheckConstraint(
            "transition_type IN ('OPENED', 'CLOSED', 'REOPENED')",
            name="ck_finding_transitions_type",
        ),
        ForeignKeyConstraint(
            ["finding_id", "project_id", "tenant_id"],
            ["findings.id", "findings.project_id", "findings.tenant_id"],
            name="fk_finding_transitions_finding_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["governance_run_id", "project_id", "tenant_id"],
            [
                "governance_runs.id",
                "governance_runs.project_id",
                "governance_runs.tenant_id",
            ],
            name="fk_finding_transitions_run_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            name="uq_finding_transitions_scope",
        ),
        UniqueConstraint(
            "finding_id",
            "governance_run_id",
            name="uq_finding_transitions_finding_run",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    finding_id: uuid.UUID = Field(index=True)
    governance_run_id: uuid.UUID = Field(index=True)
    transition_type: str = Field(max_length=20)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class FindingOccurrenceObservation(SQLModel, table=True):
    __tablename__: ClassVar[str] = "finding_occurrence_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["finding_occurrence_id", "governance_run_id", "project_id", "tenant_id"],
            [
                "finding_occurrences.id",
                "finding_occurrences.governance_run_id",
                "finding_occurrences.project_id",
                "finding_occurrences.tenant_id",
            ],
            name="fk_finding_occurrence_observations_occurrence_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["observation_id", "governance_run_id", "project_id", "tenant_id"],
            [
                "observations.id",
                "observations.governance_run_id",
                "observations.project_id",
                "observations.tenant_id",
            ],
            name="fk_finding_occurrence_observations_observation_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "finding_occurrence_id",
            "observation_id",
            name="uq_finding_occurrence_observations_pair",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    governance_run_id: uuid.UUID = Field(index=True)
    finding_occurrence_id: uuid.UUID = Field(index=True)
    observation_id: uuid.UUID = Field(index=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class FindingOccurrenceSnapshot(SQLModel, table=True):
    __tablename__: ClassVar[str] = "finding_occurrence_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["finding_occurrence_id", "governance_run_id", "project_id", "tenant_id"],
            [
                "finding_occurrences.id",
                "finding_occurrences.governance_run_id",
                "finding_occurrences.project_id",
                "finding_occurrences.tenant_id",
            ],
            name="fk_finding_occurrence_snapshots_occurrence_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_snapshot_id", "governance_run_id", "project_id", "tenant_id"],
            [
                "source_snapshots.id",
                "source_snapshots.governance_run_id",
                "source_snapshots.project_id",
                "source_snapshots.tenant_id",
            ],
            name="fk_finding_occurrence_snapshots_snapshot_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "finding_occurrence_id",
            "source_snapshot_id",
            name="uq_finding_occurrence_snapshots_pair",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    governance_run_id: uuid.UUID = Field(index=True)
    finding_occurrence_id: uuid.UUID = Field(index=True)
    source_snapshot_id: uuid.UUID = Field(index=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class FindingTransitionObservation(SQLModel, table=True):
    __tablename__: ClassVar[str] = "finding_transition_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["finding_transition_id", "governance_run_id", "project_id", "tenant_id"],
            [
                "finding_transitions.id",
                "finding_transitions.governance_run_id",
                "finding_transitions.project_id",
                "finding_transitions.tenant_id",
            ],
            name="fk_finding_transition_observations_transition_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["observation_id", "governance_run_id", "project_id", "tenant_id"],
            [
                "observations.id",
                "observations.governance_run_id",
                "observations.project_id",
                "observations.tenant_id",
            ],
            name="fk_finding_transition_observations_observation_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "finding_transition_id",
            "observation_id",
            name="uq_finding_transition_observations_pair",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    governance_run_id: uuid.UUID = Field(index=True)
    finding_transition_id: uuid.UUID = Field(index=True)
    observation_id: uuid.UUID = Field(index=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class FindingTransitionSnapshot(SQLModel, table=True):
    __tablename__: ClassVar[str] = "finding_transition_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["finding_transition_id", "governance_run_id", "project_id", "tenant_id"],
            [
                "finding_transitions.id",
                "finding_transitions.governance_run_id",
                "finding_transitions.project_id",
                "finding_transitions.tenant_id",
            ],
            name="fk_finding_transition_snapshots_transition_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_snapshot_id", "governance_run_id", "project_id", "tenant_id"],
            [
                "source_snapshots.id",
                "source_snapshots.governance_run_id",
                "source_snapshots.project_id",
                "source_snapshots.tenant_id",
            ],
            name="fk_finding_transition_snapshots_snapshot_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "finding_transition_id",
            "source_snapshot_id",
            name="uq_finding_transition_snapshots_pair",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    governance_run_id: uuid.UUID = Field(index=True)
    finding_transition_id: uuid.UUID = Field(index=True)
    source_snapshot_id: uuid.UUID = Field(index=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class GovernanceReportSummaryPublic(SQLModel):
    id: uuid.UUID
    governance_run_id: uuid.UUID
    run_completed_at: datetime
    report_contract_version: str
    generation_mode: str
    html_sha256: str
    csv_sha256: str
    created_at: datetime


class EvidenceReferencePublic(SQLModel):
    id: uuid.UUID
    governance_run_id: uuid.UUID
    fact_type: str
    fact_id: uuid.UUID


class GovernanceReportDetailPublic(GovernanceReportSummaryPublic):
    canonical_content: dict[str, Any]
    evidence: list[EvidenceReferencePublic] = Field(default_factory=list)
    evidence_count: int
    evidence_max_entries: int


class GovernanceReportsPublic(SQLModel):
    data: list[GovernanceReportSummaryPublic]
    count: int
    page_size: int
    next_cursor: str | None
    compatible: bool
    compatibility_code: str | None
    latest_completed_run_id: uuid.UUID | None
    latest_completed_run_at: datetime | None


class RunStepPublic(SQLModel):
    step_code: str
    status: str
    attempt: int
    input_hash: str | None
    output_hash: str | None
    error_code: str | None
    started_at: datetime
    completed_at: datetime | None


class SourceSnapshotPublic(SQLModel):
    id: uuid.UUID
    source_type: str
    content_sha256: str
    schema_fingerprint: str
    method_fingerprint: str | None
    record_count: int
    created_at: datetime


class GovernanceRunPublic(SQLModel):
    id: uuid.UUID
    trigger_id: str
    session_id: str
    status: str
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
    created_at: datetime
    completed_at: datetime | None
    session_terminal_at: datetime | None
    session_recovery_code: str | None
    steps: list[RunStepPublic]
    snapshots: list[SourceSnapshotPublic]
    reused_snapshot_count: int = 0
    can_retry: bool = False
    can_rerun: bool = False
    blocking_code: str | None = None


class GovernanceRunsPublic(SQLModel):
    data: list[GovernanceRunPublic]
    count: int
    can_trigger: bool
    ready: bool
    readiness_code: str | None
    launch_blocking_code: str | None = None


class IPObservationPublic(SQLModel):
    id: uuid.UUID
    source_type: str
    source_record_key: str
    raw_ip: str
    canonical_ip: str
    cloudatlas_asset_id: str | None
    cloudatlas_status: str | None
    source_snapshot_id: uuid.UUID


class IPAssetPublic(SQLModel):
    id: uuid.UUID
    resource_id: uuid.UUID
    resource_type: str
    canonical_key: str
    canonical_ip: str
    customer_observation_count: int
    cloudatlas_observation_count: int
    observation_count: int
    customer_observed: bool
    cloudatlas_observed: bool
    open_finding_id: uuid.UUID | None
    open_finding_type: str | None


class IPAssetDetailPublic(IPAssetPublic):
    observations: list[IPObservationPublic] = Field(default_factory=list)


class IPAssetsPublic(SQLModel):
    data: list[IPAssetPublic]
    count: int
    latest_run_id: uuid.UUID | None
    latest_run_completed_at: datetime | None
    compatible: bool
    compatibility_code: str | None


class FindingOccurrencePublic(SQLModel):
    id: uuid.UUID
    governance_run_id: uuid.UUID
    created_at: datetime
    observation_ids: list[uuid.UUID] = Field(default_factory=list)
    source_snapshot_ids: list[uuid.UUID] = Field(default_factory=list)
    source_snapshots: list[SourceSnapshotPublic] = Field(default_factory=list)
    observations: list[IPObservationPublic] = Field(default_factory=list)


class FindingTransitionPublic(SQLModel):
    id: uuid.UUID
    governance_run_id: uuid.UUID
    transition_type: str
    created_at: datetime
    observation_ids: list[uuid.UUID] = Field(default_factory=list)
    source_snapshot_ids: list[uuid.UUID] = Field(default_factory=list)
    source_snapshots: list[SourceSnapshotPublic] = Field(default_factory=list)
    observations: list[IPObservationPublic] = Field(default_factory=list)


class FindingPublic(SQLModel):
    id: uuid.UUID
    resource_id: uuid.UUID
    finding_type: str
    status: str
    canonical_ip: str
    first_detected_at: datetime | None
    last_detected_at: datetime | None
    latest_occurrence_at: datetime | None
    latest_occurrence_run_id: uuid.UUID | None
    latest_transition_at: datetime | None
    occurrence_count: int
    transition_count: int


class FindingDetailPublic(FindingPublic):
    occurrences: list[FindingOccurrencePublic] = Field(default_factory=list)
    transitions: list[FindingTransitionPublic] = Field(default_factory=list)


class FindingsPublic(SQLModel):
    data: list[FindingPublic]
    count: int
    status: str
    latest_run_id: uuid.UUID | None
    latest_run_completed_at: datetime | None
    compatible: bool
    compatibility_code: str | None


class GovernanceRunTriggerPublic(SQLModel):
    accepted: bool
    agent_compose_run_id: str
    agent_compose_status: str
    governance_run_id: uuid.UUID | None


class GovernanceRunActionPublic(SQLModel):
    accepted: bool
    action: str
    governance_run_id: uuid.UUID | None
    source_governance_run_id: uuid.UUID | None = None
    session_id: str | None
    agent_compose_run_id: str | None
    agent_compose_status: str
    code: str | None = None


class ProjectRole(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    APPROVER = "approver"


class ProjectMembershipRoles(SQLModel):
    roles: list[ProjectRole] = Field(min_length=1)

    @field_validator("roles")
    @classmethod
    def roles_must_be_unique(cls, roles: list[ProjectRole]) -> list[ProjectRole]:
        if len(roles) != len(set(roles)):
            raise ValueError("roles must not contain duplicates")
        return roles


class ProjectMembershipCreate(ProjectMembershipRoles):
    model_config = SQLModel.model_config | {"extra": "forbid"}

    user_id: uuid.UUID


class ProjectMembershipUpdate(ProjectMembershipRoles):
    model_config = SQLModel.model_config | {"extra": "forbid"}


class ProjectMembership(SQLModel, table=True):
    __tablename__: ClassVar[str] = "project_memberships"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "user_id", name="uq_project_memberships_project_user"
        ),
        CheckConstraint(
            "cardinality(roles) > 0", name="ck_project_memberships_roles_nonempty"
        ),
        CheckConstraint(
            "roles <@ ARRAY['viewer', 'operator', 'approver']::varchar[]",
            name="ck_project_memberships_roles_known",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        default=DEPLOYMENT_TENANT_ID,
        foreign_key="tenants.id",
        ondelete="RESTRICT",
        index=True,
    )
    project_id: uuid.UUID = Field(
        foreign_key="projects.id", ondelete="RESTRICT", index=True
    )
    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT", index=True)
    roles: list[str] = Field(sa_column=Column(ARRAY(String(20)), nullable=False))
    revoked_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class ProjectMembershipPublic(ProjectMembershipRoles):
    id: uuid.UUID
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProjectMembershipsPublic(SQLModel):
    data: list[ProjectMembershipPublic]
    count: int


class AuditEvent(SQLModel, table=True):
    __tablename__: ClassVar[str] = "audit_events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        default=DEPLOYMENT_TENANT_ID,
        foreign_key="tenants.id",
        ondelete="RESTRICT",
        index=True,
    )
    project_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="projects.id",
        ondelete="RESTRICT",
        index=True,
    )
    actor_subject: str = Field(max_length=255)
    actor_type: str = Field(max_length=50)
    action: str = Field(max_length=100, index=True)
    target_type: str = Field(max_length=100)
    target_id: uuid.UUID
    before_data: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    after_data: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    ip_address: str | None = Field(default=None, max_length=45)
    occurred_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
        index=True,
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class AuditEventPublic(SQLModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    project_id: uuid.UUID | None
    actor_subject: str
    actor_type: str
    action: str
    target_type: str
    target_id: uuid.UUID
    before_data: dict[str, Any] | None
    after_data: dict[str, Any] | None
    ip_address: str | None
    occurred_at: datetime
    created_at: datetime
    updated_at: datetime


class AuditEventsPublic(SQLModel):
    data: list[AuditEventPublic]
    count: int
