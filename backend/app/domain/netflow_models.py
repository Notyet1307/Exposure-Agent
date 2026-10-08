"""Fixed source-side processing receipts; no Resource or GovernanceRun replacement."""

import uuid
from datetime import datetime
from typing import Any, ClassVar, Final

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.core.time import get_datetime_utc

_TIME: Any = DateTime(timezone=True)
CONTRACT_VERSION: Final = "netflow-correlation-v1"


class NetFlowContextRevision(SQLModel, table=True):
    __tablename__: ClassVar[str] = "netflow_context_revisions"
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
            "id", "dataset_id", "project_id", "tenant_id", name="uq_nf_context_scope"
        ),
        ForeignKeyConstraint(
            ["parent_id", "dataset_id", "project_id", "tenant_id"],
            [
                "netflow_context_revisions.id",
                "netflow_context_revisions.dataset_id",
                "netflow_context_revisions.project_id",
                "netflow_context_revisions.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("dataset_id", "revision", name="uq_nf_context_revision"),
        UniqueConstraint(
            "project_id",
            "dataset_id",
            "created_by",
            "operation_key",
            name="uq_nf_context_operation",
        ),
        UniqueConstraint("parent_id", name="uq_nf_context_successor"),
        Index(
            "uq_nf_context_root",
            "dataset_id",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
        CheckConstraint(
            "revision > 0 AND state IN ('CONFIRMED','UNKNOWN','CONFLICT','REVOKED')",
            name="ck_nf_context_state",
        ),
        CheckConstraint(
            "network_namespace ~ '^[a-z][a-z0-9_-]{0,63}$'",
            name="ck_nf_context_namespace",
        ),
        CheckConstraint(
            "raw_sha256 ~ '^[0-9a-f]{64}$' AND normalized_sha256 ~ '^[0-9a-f]{64}$' AND request_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_nf_context_hashes",
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID
    project_id: uuid.UUID = Field(index=True)
    dataset_id: uuid.UUID = Field(index=True)
    parent_id: uuid.UUID | None = None
    revision: int
    network_namespace: str = Field(max_length=64)
    state: str = Field(max_length=16)
    collection_scope: str | None = Field(default=None, max_length=128)
    collection_scope_evidence: str | None = Field(default=None, max_length=2048)
    raw_sha256: str = Field(max_length=64)
    normalized_sha256: str = Field(max_length=64)
    payload: dict[str, Any] = Field(sa_type=JSONB)
    created_by: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    operation_key: str = Field(max_length=128)
    request_sha256: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=_TIME)


class NetFlowAnalysis(SQLModel, table=True):
    __tablename__: ClassVar[str] = "netflow_analyses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["context_revision_id", "dataset_id", "project_id", "tenant_id"],
            [
                "netflow_context_revisions.id",
                "netflow_context_revisions.dataset_id",
                "netflow_context_revisions.project_id",
                "netflow_context_revisions.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "project_id", "tenant_id", name="uq_nf_analysis_scope"),
        UniqueConstraint(
            "id",
            "processing_identity_sha256",
            "project_id",
            "tenant_id",
            name="uq_nf_analysis_identity_scope",
        ),
        ForeignKeyConstraint(
            [
                "retry_of_analysis_id",
                "processing_identity_sha256",
                "project_id",
                "tenant_id",
            ],
            [
                "netflow_analyses.id",
                "netflow_analyses.processing_identity_sha256",
                "netflow_analyses.project_id",
                "netflow_analyses.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("retry_of_analysis_id", name="uq_nf_analysis_retry"),
        Index(
            "uq_nf_analysis_identity_root",
            "project_id",
            "processing_identity_sha256",
            unique=True,
            postgresql_where=text("retry_of_analysis_id IS NULL"),
        ),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','SUCCEEDED_WITH_WARNINGS','FAILED','UNKNOWN')",
            name="ck_nf_analysis_status",
        ),
        CheckConstraint(
            "processing_identity_sha256 ~ '^[0-9a-f]{64}$' AND agent_run_id ~ '^[0-9a-f]{64}$' AND agent_project_id ~ '^[0-9a-f]{64}$'",
            name="ck_nf_analysis_identity",
        ),
        CheckConstraint(
            "network_namespace ~ '^[a-z][a-z0-9_-]{0,63}$'",
            name="ck_nf_analysis_namespace",
        ),
        CheckConstraint(
            "(status IN ('SUCCEEDED','SUCCEEDED_WITH_WARNINGS') AND result IS NOT NULL AND completed_at IS NOT NULL AND initial_feedback_revision_id IS NOT NULL AND session_id IS NOT NULL) OR (status NOT IN ('SUCCEEDED','SUCCEEDED_WITH_WARNINGS') AND result IS NULL AND initial_feedback_revision_id IS NULL)",
            name="ck_nf_analysis_publication",
        ),
        ForeignKeyConstraint(
            ["initial_feedback_revision_id", "id", "project_id", "tenant_id"],
            [
                "netflow_feedback_revisions.id",
                "netflow_feedback_revisions.analysis_id",
                "netflow_feedback_revisions.project_id",
                "netflow_feedback_revisions.tenant_id",
            ],
            name="fk_nf_analysis_initial_feedback",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID
    project_id: uuid.UUID = Field(index=True)
    dataset_id: uuid.UUID = Field(index=True)
    context_revision_id: uuid.UUID
    network_namespace: str = Field(max_length=64)
    processing_identity_sha256: str = Field(max_length=64)
    identity: dict[str, Any] = Field(sa_type=JSONB)
    request: dict[str, Any] = Field(sa_type=JSONB)
    quality: dict[str, Any] = Field(sa_type=JSONB)
    test_fixture: bool = False
    created_by: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    retry_of_analysis_id: uuid.UUID | None = None
    status: str = Field(default="PENDING", max_length=32)
    agent_run_id: str = Field(max_length=64, unique=True)
    agent_project_id: str = Field(max_length=64)
    session_id: str | None = Field(default=None, max_length=255)
    runner_build_version: str = Field(max_length=255)
    result: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    initial_feedback_revision_id: uuid.UUID | None = None
    error_code: str | None = Field(default=None, max_length=100)
    terminal_confirmed: bool = False
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=_TIME)
    started_at: datetime | None = Field(default=None, sa_type=_TIME)
    completed_at: datetime | None = Field(default=None, sa_type=_TIME)


class NetFlowFeedbackRevision(SQLModel, table=True):
    __tablename__: ClassVar[str] = "netflow_feedback_revisions"
    __table_args__ = (
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
            "id", "analysis_id", "project_id", "tenant_id", name="uq_nf_feedback_scope"
        ),
        ForeignKeyConstraint(
            ["parent_id", "analysis_id", "project_id", "tenant_id"],
            [
                "netflow_feedback_revisions.id",
                "netflow_feedback_revisions.analysis_id",
                "netflow_feedback_revisions.project_id",
                "netflow_feedback_revisions.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("analysis_id", "revision", name="uq_nf_feedback_revision"),
        UniqueConstraint("parent_id", name="uq_nf_feedback_successor"),
        Index(
            "uq_nf_feedback_root",
            "analysis_id",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
        CheckConstraint(
            "revision > 0 AND (parent_id IS NOT NULL OR revision = 1)",
            name="ck_nf_feedback_revision",
        ),
        CheckConstraint(
            "NOT system_generated OR (created_by IS NULL AND parent_id IS NULL)",
            name="ck_nf_feedback_system_author",
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID
    project_id: uuid.UUID = Field(index=True)
    analysis_id: uuid.UUID = Field(index=True)
    parent_id: uuid.UUID | None = None
    revision: int
    created_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="RESTRICT"
    )
    system_generated: bool = False
    human_note: str | None = Field(default=None, max_length=2048)
    # Artifact receipts seal original component bytes; no answers are written to AuditEvent.
    artifact_manifest: dict[str, Any] = Field(sa_type=JSONB)
    provider_claim: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=_TIME)


class SourceCorrelationRevision(SQLModel, table=True):
    __tablename__: ClassVar[str] = "source_correlation_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["projects.id", "projects.tenant_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id", "root_id", "project_id", "tenant_id", name="uq_nf_correlation_scope"
        ),
        ForeignKeyConstraint(
            ["parent_id", "root_id", "project_id", "tenant_id"],
            [
                "source_correlation_revisions.id",
                "source_correlation_revisions.root_id",
                "source_correlation_revisions.project_id",
                "source_correlation_revisions.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("root_id", "revision", name="uq_nf_correlation_revision"),
        UniqueConstraint("parent_id", name="uq_nf_correlation_successor"),
        Index(
            "uq_nf_correlation_root",
            "root_id",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
        CheckConstraint(
            "revision > 0 AND ((parent_id IS NULL AND root_id = id AND revision = 1) OR parent_id IS NOT NULL)",
            name="ck_nf_correlation_root",
        ),
        CheckConstraint(
            "scope_state IN ('UNKNOWN','CONFIRMED','REVOKED')",
            name="ck_nf_correlation_state",
        ),
        CheckConstraint(
            "network_namespace ~ '^[a-z][a-z0-9_-]{0,63}$'",
            name="ck_nf_correlation_namespace",
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID
    project_id: uuid.UUID = Field(index=True)
    root_id: uuid.UUID = Field(index=True)
    parent_id: uuid.UUID | None = None
    revision: int
    network_namespace: str = Field(max_length=64)
    scope_state: str = Field(default="UNKNOWN", max_length=16)
    selection: dict[str, Any] = Field(sa_type=JSONB)
    # Fixed identities/hashes only; never copies ExternalAssetRecord fields or address sets.
    pins: dict[str, Any] = Field(sa_type=JSONB)
    evidence: str | None = Field(default=None, max_length=2048)
    created_by: uuid.UUID = Field(foreign_key="user.id", ondelete="RESTRICT")
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=_TIME)
