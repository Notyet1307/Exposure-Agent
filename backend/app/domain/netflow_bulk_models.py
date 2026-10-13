"""PostgreSQL identities/checkpoints and bounded bulk query projections."""

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.core.time import get_datetime_utc

_TIME: Any = DateTime(timezone=True)


class BulkDataset(SQLModel, table=True):
    __tablename__: ClassVar[str] = "netflow_bulk_datasets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "project_id", "tenant_id"],
            [
                "netflow_datasets.id",
                "netflow_datasets.project_id",
                "netflow_datasets.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id", "project_id", "source_id", "ready_id", name="uq_bulk_ready"
        ),
    )
    dataset_id: uuid.UUID = Field(primary_key=True)
    tenant_id: uuid.UUID
    project_id: uuid.UUID = Field(index=True)
    source_id: str = Field(max_length=64)
    ready_id: str = Field(max_length=64)
    manifest: dict[str, Any] = Field(sa_type=JSONB)
    normalizer: str = Field(max_length=64)
    complete: bool = False
    invalidated: bool = False


class BulkMember(SQLModel, table=True):
    __tablename__: ClassVar[str] = "netflow_bulk_members"
    dataset_id: uuid.UUID = Field(
        foreign_key="netflow_bulk_datasets.dataset_id",
        primary_key=True,
        ondelete="RESTRICT",
    )
    file_id: str = Field(max_length=64, primary_key=True)
    complete: bool = False
    raw_count: int = Field(default=0, sa_type=BigInteger)
    invalid_count: int = Field(default=0, sa_type=BigInteger)
    byte_size: int = Field(sa_type=BigInteger)
    shard_count: int = 0


class BulkShard(SQLModel, table=True):
    __tablename__: ClassVar[str] = "netflow_bulk_shards"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "file_id"],
            ["netflow_bulk_members.dataset_id", "netflow_bulk_members.file_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(sealed_inode IS NULL AND sealed_mtime_ns IS NULL AND sealed_ctime_ns IS NULL) OR (sealed_inode IS NOT NULL AND sealed_mtime_ns IS NOT NULL AND sealed_ctime_ns IS NOT NULL)",
            name="ck_bulk_shard_seal",
        ),
        CheckConstraint(
            "first_row > 0 AND last_row >= first_row AND rows = last_row-first_row+1 AND invalid >= 0 AND invalid <= rows",
            name="ck_bulk_shard_counts",
        ),
    )
    dataset_id: uuid.UUID = Field(primary_key=True)
    file_id: str = Field(max_length=64, primary_key=True)
    ordinal: int = Field(primary_key=True)
    storage_key: str = Field(max_length=1024)
    sha256: str = Field(max_length=64)
    size: int = Field(sa_type=BigInteger)
    first_row: int = Field(sa_type=BigInteger)
    last_row: int = Field(sa_type=BigInteger)
    rows: int = Field(sa_type=BigInteger)
    invalid: int = Field(sa_type=BigInteger)
    sealed_inode: int | None = Field(default=None, sa_type=BigInteger)
    sealed_mtime_ns: int | None = Field(default=None, sa_type=BigInteger)
    sealed_ctime_ns: int | None = Field(default=None, sa_type=BigInteger)


class BulkJob(SQLModel, table=True):
    __tablename__: ClassVar[str] = "netflow_bulk_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["analysis_id", "dataset_id", "project_id", "tenant_id"],
            [
                "netflow_analyses.id",
                "netflow_analyses.dataset_id",
                "netflow_analyses.project_id",
                "netflow_analyses.tenant_id",
            ],
            name="fk_bulk_analysis_dataset_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["analysis_id", "project_id", "tenant_id"],
            [
                "netflow_analyses.id",
                "netflow_analyses.project_id",
                "netflow_analyses.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("fence >= 0", name="ck_bulk_fence"),
        Index("ix_bulk_lease", "lease_until"),
    )
    analysis_id: uuid.UUID = Field(primary_key=True)
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    dataset_id: uuid.UUID = Field(
        foreign_key="netflow_bulk_datasets.dataset_id", index=True, ondelete="RESTRICT"
    )
    fence: int = 0
    lease_until: datetime | None = Field(default=None, sa_type=_TIME)
    heartbeat_at: datetime | None = Field(default=None, sa_type=_TIME)
    cancel_requested: bool = False
    invalidated: bool = False
    phase: str = Field(default="PENDING", max_length=32)
    selection: dict[str, Any] = Field(sa_type=JSONB)
    metrics: dict[str, Any] = Field(default_factory=dict, sa_type=JSONB)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=_TIME)


class BulkObject(SQLModel, table=True):
    __tablename__: ClassVar[str] = "netflow_bulk_objects"
    __table_args__ = (
        Index("ix_bulk_object_page", "analysis_id", "family", "ip_sort", "object_key"),
        Index("ix_bulk_object_filter", "analysis_id", "ip", "protocol", "port"),
        CheckConstraint(
            "record_count >= 0 AND family IN (4,6)", name="ck_bulk_object_count"
        ),
    )
    analysis_id: uuid.UUID = Field(
        foreign_key="netflow_bulk_jobs.analysis_id",
        primary_key=True,
        ondelete="RESTRICT",
    )
    object_key: str = Field(max_length=64, primary_key=True)
    ip: str = Field(max_length=45)
    family: int
    ip_sort: str = Field(max_length=32)
    protocol: int
    port: int | None
    record_count: int = Field(sa_type=BigInteger)
    start_us: int | None = Field(default=None, sa_type=BigInteger)
    end_us: int | None = Field(default=None, sa_type=BigInteger)


class BulkAddress(SQLModel, table=True):
    __tablename__: ClassVar[str] = "netflow_bulk_addresses"
    __table_args__ = (
        Index("ix_bulk_address_page", "analysis_id", "family", "ip_sort"),
    )
    analysis_id: uuid.UUID = Field(
        foreign_key="netflow_bulk_jobs.analysis_id",
        primary_key=True,
        ondelete="RESTRICT",
    )
    ip: str = Field(max_length=45, primary_key=True)
    family: int
    ip_sort: str = Field(max_length=32)
    observation_count: int = Field(sa_type=BigInteger)
    record_count: int = Field(sa_type=BigInteger)
