"""Independent, version-scoped CloudAtlas local read model (not GovernanceRun)."""

import uuid
from datetime import datetime
from typing import Annotated, Any, ClassVar, Literal

from pydantic import AwareDatetime, field_validator
from pydantic import Field as PydanticField
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.core.time import get_datetime_utc

Domain = Literal["ip", "port"]
SyncStatus = Literal[
    "PENDING", "RUNNING", "UNKNOWN", "SUCCEEDED", "PARTIAL_FAILED", "FAILED"
]
DomainStatus = Literal["PENDING", "RUNNING", "PUBLISHED", "FAILED", "UNKNOWN"]
_TIME: Any = DateTime(timezone=True)


class ExternalSync(SQLModel, table=True):
    __tablename__: ClassVar[str] = "external_syncs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "project_id"],
            ["source_instances.id", "source_instances.project_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "actor_id",
            "project_id",
            "source_id",
            "idempotency_key",
            name="uq_external_sync_intent",
        ),
        UniqueConstraint("id", "source_id", name="uq_external_sync_source"),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','UNKNOWN','SUCCEEDED','PARTIAL_FAILED','FAILED')",
            name="ck_external_sync_status",
        ),
        Index(
            "uq_external_sync_unfinished",
            "source_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING','RUNNING','UNKNOWN')"),
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID
    actor_id: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    idempotency_key: str = Field(max_length=128)
    request_sha256: str = Field(max_length=64)
    request: dict[str, Any] = Field(sa_type=JSONB)
    fingerprint: str = Field(max_length=64)
    token_sha256: str = Field(max_length=64)
    status: str = Field(default="PENDING", max_length=20)
    agent_run_id: str = Field(max_length=64, unique=True)
    agent_project_id: str = Field(max_length=64)
    session_id: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=_TIME)
    started_at: datetime | None = Field(default=None, sa_type=_TIME)
    completed_at: datetime | None = Field(default=None, sa_type=_TIME)
    retain_until: datetime = Field(sa_type=_TIME)
    error_code: str | None = Field(default=None, max_length=100)
    pages_read: int = 0
    records_read: int = 0


class ExternalAssetVersion(SQLModel, table=True):
    __tablename__: ClassVar[str] = "external_asset_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["sync_id", "source_id"],
            ["external_syncs.id", "external_syncs.source_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("sync_id", "domain", name="uq_external_version_domain"),
        UniqueConstraint("id", "source_id", "domain", name="uq_external_version_scope"),
        CheckConstraint("domain IN ('ip','port')", name="ck_external_version_domain"),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','PUBLISHED','FAILED','UNKNOWN')",
            name="ck_external_version_status",
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    sync_id: uuid.UUID
    source_id: uuid.UUID = Field(index=True)
    domain: str = Field(max_length=10)
    space_id: str = Field(max_length=255)
    instance_id: str = Field(max_length=255)
    capset_id: str = Field(max_length=255)
    status: str = Field(default="PENDING", max_length=20)
    record_count: int = 0
    expected_total: int | None = None
    complete: bool = False
    filter: dict[str, str] = Field(sa_type=JSONB)
    sort: str = Field(default="-id", max_length=10)
    fingerprint: str = Field(max_length=64)
    fetched_at: datetime | None = Field(default=None, sa_type=_TIME)
    published_at: datetime | None = Field(default=None, sa_type=_TIME)
    retain_until: datetime = Field(sa_type=_TIME)
    error_code: str | None = Field(default=None, max_length=100)


class ExternalAssetRecord(SQLModel, table=True):
    __tablename__: ClassVar[str] = "external_asset_records"
    __table_args__ = (
        UniqueConstraint("version_id", "source_id", name="uq_external_record_identity"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    version_id: uuid.UUID = Field(
        foreign_key="external_asset_versions.id", ondelete="RESTRICT", index=True
    )
    source_id: str = Field(max_length=100)
    ip: str = Field(max_length=45)
    canonical_ip: str = Field(max_length=45, index=True)
    fields: dict[str, Any] = Field(sa_type=JSONB)


class ExternalAssetHead(SQLModel, table=True):
    __tablename__: ClassVar[str] = "external_asset_heads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "source_id", "domain"],
            [
                "external_asset_versions.id",
                "external_asset_versions.source_id",
                "external_asset_versions.domain",
            ],
            ondelete="RESTRICT",
        ),
    )
    source_id: uuid.UUID = Field(primary_key=True)
    domain: str = Field(primary_key=True, max_length=10)
    version_id: uuid.UUID


class ExternalSourceCreate(SQLModel):
    model_config = SQLModel.model_config | {"extra": "forbid"}
    instance_id: str = Field(min_length=1, max_length=255)
    capset_id: str = Field(min_length=1, max_length=255)
    space_id: Annotated[
        str, PydanticField(min_length=1, max_length=255, pattern=r"^(0|[1-9][0-9]*)$")
    ]

    @field_validator("instance_id", "capset_id", "space_id")
    @classmethod
    def safe_identifier(cls, value: str) -> str:
        if value != value.strip() or any(c in "/?#\\" or ord(c) < 32 for c in value):
            raise ValueError("Identifiers must be path-safe")
        return value


class ExternalSourceUpdate(SQLModel):
    model_config = SQLModel.model_config | {"extra": "forbid"}
    enabled: bool | None = None
    data_access_enabled: bool | None = None


class ExternalSourcePublic(SQLModel):
    id: uuid.UUID
    instance_id: str
    capset_id: str
    space_id: str
    enabled: bool
    data_access_enabled: bool
    validation_status: str
    validated_fingerprint: str | None
    created_at: datetime
    updated_at: datetime


class ExternalSourcesPublic(SQLModel):
    data: list[ExternalSourcePublic]
    count: int
    can_manage: bool


class ExternalSyncCreate(SQLModel):
    model_config = SQLModel.model_config | {"extra": "forbid"}
    page_size: Annotated[int, PydanticField(strict=True, ge=1, le=200)]
    max_pages: Annotated[int, PydanticField(strict=True, ge=1, le=10000)]
    max_records: Annotated[int, PydanticField(strict=True, ge=1, le=1000000)]
    max_response_bytes: Annotated[int, PydanticField(strict=True, ge=1, le=16777216)]
    timeout_seconds: Annotated[int, PydanticField(strict=True, ge=1, le=300)]
    retain_until: AwareDatetime


class ExternalDomainPublic(SQLModel):
    domain: Domain
    status: DomainStatus
    version_id: uuid.UUID | None
    record_count: int
    error_code: str | None


class ExternalSyncPublic(SQLModel):
    id: uuid.UUID
    source_id: uuid.UUID
    status: SyncStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    retain_until: datetime
    error_code: str | None
    agent_run_id: str | None
    session_id: str | None
    domains: list[ExternalDomainPublic]


class ExternalSyncsPublic(SQLModel):
    data: list[ExternalSyncPublic]
    count: int


class ExternalVersionPublic(SQLModel):
    id: uuid.UUID
    source_id: uuid.UUID
    domain: Domain
    space_id: str
    status: Literal["PUBLISHED", "EXPIRED"]
    record_count: int
    filter: dict[str, str]
    sort: str
    fingerprint: str
    fetched_at: datetime
    published_at: datetime
    retain_until: datetime


class ExternalVersionsPublic(SQLModel):
    data: list[ExternalVersionPublic]
    count: int


class ExternalRecordPublic(SQLModel):
    id: uuid.UUID
    version_id: uuid.UUID
    source_id: str
    ip: str
    canonical_ip: str
    fields: dict[str, Any]


class ExternalRecordsPublic(SQLModel):
    data: list[ExternalRecordPublic]
    count: int
    version: ExternalVersionPublic | None
    state: Literal["PUBLISHED", "NOT_SYNCED", "EXPIRED"]


class ExternalRecordDetailPublic(SQLModel):
    record: ExternalRecordPublic
    version: ExternalVersionPublic
    matched_ports: list[ExternalRecordPublic]
    matched_port_count: int
    port_version: ExternalVersionPublic | None


class ExternalPurgePublic(SQLModel):
    deleted_records: int
