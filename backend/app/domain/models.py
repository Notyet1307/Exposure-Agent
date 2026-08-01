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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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
        CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name="ck_artifacts_sha256_format"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        default=DEPLOYMENT_TENANT_ID,
        foreign_key="tenants.id",
        ondelete="RESTRICT",
        index=True,
    )
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
        UniqueConstraint(
            "id", "project_id", name="uq_customer_uploads_id_project"
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
        CheckConstraint(
            "source_type = 'cloudatlas'", name="ck_source_instances_type"
        ),
        CheckConstraint(
            "validated_fingerprint IS NULL OR "
            "validated_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_source_instances_fingerprint_format",
        ),
        UniqueConstraint("id", "project_id", name="uq_source_instances_id_project"),
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
    PUBLISH = "PUBLISH"


class RunStepStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class SourceSnapshotType(StrEnum):
    CUSTOMER_UPLOAD = "CUSTOMER_UPLOAD"
    CLOUDATLAS = "CLOUDATLAS"


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
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["projects.id", "projects.tenant_id"],
            name="fk_governance_runs_project_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["customer_upload_id", "project_id", "tenant_id"],
            ["customer_uploads.id", "customer_uploads.project_id", "customer_uploads.tenant_id"],
            name="fk_governance_runs_customer_upload_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_instance_id", "project_id", "tenant_id"],
            ["source_instances.id", "source_instances.project_id", "source_instances.tenant_id"],
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
        UniqueConstraint("id", "project_id", "tenant_id", name="uq_governance_runs_scope"),
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


class RunStep(SQLModel, table=True):
    __tablename__: ClassVar[str] = "run_steps"
    __table_args__ = (
        CheckConstraint(
            "step_code IN ('LOAD_CUSTOMER', 'PULL_CLOUDATLAS', 'PUBLISH')",
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
            ["governance_runs.id", "governance_runs.project_id", "governance_runs.tenant_id"],
            name="fk_run_steps_governance_run_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("governance_run_id", "step_code", name="uq_run_steps_run_code"),
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
            ["governance_runs.id", "governance_runs.project_id", "governance_runs.tenant_id"],
            name="fk_source_snapshots_governance_run_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["customer_upload_id", "project_id", "tenant_id"],
            ["customer_uploads.id", "customer_uploads.project_id", "customer_uploads.tenant_id"],
            name="fk_source_snapshots_customer_upload_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_instance_id", "project_id", "tenant_id"],
            ["source_instances.id", "source_instances.project_id", "source_instances.tenant_id"],
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
    created_at: datetime
    completed_at: datetime | None
    steps: list[RunStepPublic]
    snapshots: list[SourceSnapshotPublic]


class GovernanceRunsPublic(SQLModel):
    data: list[GovernanceRunPublic]
    count: int
    can_trigger: bool
    ready: bool
    readiness_code: str | None


class GovernanceRunTriggerPublic(SQLModel):
    accepted: bool
    agent_compose_run_id: str
    agent_compose_status: str
    governance_run_id: uuid.UUID | None


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
