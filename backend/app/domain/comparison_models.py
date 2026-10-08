"""Immutable C/A publication identities and independently expiring NetFlow bindings."""

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.time import get_datetime_utc

_TIME: Any = DateTime(timezone=True)


class CoreComparisonResult(SQLModel, table=True):
    __tablename__: ClassVar[str] = "core_comparison_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["projects.id", "projects.tenant_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["scope_confirmation_id"],
            ["source_correlation_revisions.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "project_id", "tenant_id", name="uq_core_result_scope"),
        CheckConstraint(
            "purpose IN ('regular','custom')", name="ck_core_result_purpose"
        ),
        CheckConstraint(
            "(status = 'PUBLISHED' AND published_at IS NOT NULL AND error_code IS NULL) OR (status = 'FAILED' AND published_at IS NULL AND error_code IS NOT NULL)",
            name="ck_core_result_publication",
        ),
        CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$' AND scope_key ~ '^[0-9a-f]{64}$'",
            name="ck_core_result_hashes",
        ),
        Index(
            "ix_core_result_scope_published",
            "project_id",
            "scope_key",
            "published_at",
            "id",
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID
    project_id: uuid.UUID = Field(index=True)
    scope_key: str = Field(max_length=64)
    scope_confirmation_id: uuid.UUID
    purpose: str = Field(max_length=16)
    rule_version: str = Field(default="canonical-ip-presence-v1", max_length=64)
    status: str = Field(max_length=16)
    error_code: str | None = Field(default=None, max_length=100)
    published_at: datetime | None = Field(default=None, sa_type=_TIME)
    selection: dict[str, Any] = Field(sa_type=JSONB)
    pins: dict[str, Any] = Field(sa_type=JSONB)
    input_sha256: str = Field(max_length=64)
    customer_applied_at: datetime | None = Field(default=None, sa_type=_TIME)
    created_by: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=_TIME)


class CoreComparisonSupplement(SQLModel, table=True):
    __tablename__: ClassVar[str] = "core_comparison_supplements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["result_id", "project_id", "tenant_id"],
            [
                "core_comparison_results.id",
                "core_comparison_results.project_id",
                "core_comparison_results.tenant_id",
            ],
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
        UniqueConstraint(
            "id",
            "result_id",
            "project_id",
            "tenant_id",
            name="uq_core_supplement_scope",
        ),
        ForeignKeyConstraint(
            ["parent_id", "result_id", "project_id", "tenant_id"],
            [
                "core_comparison_supplements.id",
                "core_comparison_supplements.result_id",
                "core_comparison_supplements.project_id",
                "core_comparison_supplements.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["qualification_confirmation_id"],
            ["source_correlation_revisions.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("result_id", "revision", name="uq_core_supplement_revision"),
        UniqueConstraint("parent_id", name="uq_core_supplement_successor"),
        Index(
            "uq_core_supplement_root",
            "result_id",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
        CheckConstraint(
            "revision > 0 AND ((parent_id IS NULL AND revision = 1) OR (parent_id IS NOT NULL AND revision > 1))",
            name="ck_core_supplement_revision",
        ),
        CheckConstraint(
            "(analysis_id IS NULL AND valid_until IS NULL AND qualification_confirmation_id IS NULL AND qualification_evidence IS NULL) OR (analysis_id IS NOT NULL AND valid_until > created_at AND (qualification_confirmation_id IS NOT NULL OR coalesce(length(btrim(qualification_evidence)),0) > 0))",
            name="ck_core_supplement_binding",
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    result_id: uuid.UUID = Field(index=True)
    parent_id: uuid.UUID | None = None
    revision: int
    analysis_id: uuid.UUID | None = None
    qualification_confirmation_id: uuid.UUID | None = None
    qualification_evidence: str | None = Field(default=None, max_length=2048)
    valid_until: datetime | None = Field(default=None, sa_type=_TIME)
    observation_window: dict[str, str] = Field(default_factory=dict, sa_type=JSONB)
    created_by: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=_TIME)
