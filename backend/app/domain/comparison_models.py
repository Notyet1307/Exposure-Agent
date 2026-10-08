"""Persistent identities for V2 C/A results and optional NetFlow bindings."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.time import get_datetime_utc


class CoreComparisonResult(SQLModel, table=True):
    __tablename__: ClassVar[str] = "core_comparison_results"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "tenant_id"], ["projects.id", "projects.tenant_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["scope_confirmation_id"], ["source_correlation_revisions.id"], ondelete="RESTRICT"),
        CheckConstraint("purpose IN ('regular','custom')", name="ck_core_result_purpose"),
        CheckConstraint("status IN ('PUBLISHED','FAILED','UNKNOWN')", name="ck_core_result_status"),
        CheckConstraint("input_sha256 ~ '^[0-9a-f]{64}$'", name="ck_core_result_input_hash"),
        Index("ix_core_result_scope_published", "project_id", "scope_key", "published_at", "id"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    project_id: uuid.UUID = Field(index=True)
    scope_key: str = Field(max_length=64, index=True)
    scope_confirmation_id: uuid.UUID
    purpose: str = Field(max_length=16)
    status: str = Field(max_length=16)
    published_at: datetime | None = None
    selection: dict[str, Any] = Field(sa_type=JSONB)
    pins: dict[str, Any] = Field(sa_type=JSONB)
    input_sha256: str = Field(max_length=64)
    created_by: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    created_at: datetime = Field(default_factory=get_datetime_utc)


class CoreComparisonSupplement(SQLModel, table=True):
    __tablename__: ClassVar[str] = "core_comparison_supplements"
    __table_args__ = (
        ForeignKeyConstraint(["result_id"], ["core_comparison_results.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["analysis_id"], ["netflow_analyses.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["qualification_confirmation_id"], ["source_correlation_revisions.id"], ondelete="RESTRICT"),
        UniqueConstraint("result_id", "revision", name="uq_core_supplement_revision"),
        UniqueConstraint("result_id", "parent_id", name="uq_core_supplement_successor"),
        Index("uq_core_supplement_root", "result_id", unique=True, postgresql_where=text("parent_id IS NULL")),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    result_id: uuid.UUID = Field(index=True)
    parent_id: uuid.UUID | None = None
    revision: int
    analysis_id: uuid.UUID | None = None
    qualification_confirmation_id: uuid.UUID | None = None
    valid_until: datetime | None = None
    observation_window: dict[str, Any] = Field(default_factory=dict, sa_type=JSONB)
    created_by: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    operation_key: str = Field(max_length=128)
    request_sha256: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=get_datetime_utc)
