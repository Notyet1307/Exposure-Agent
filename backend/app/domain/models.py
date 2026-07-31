import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import field_validator
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
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
            "project_id",
            "version",
            name="uq_customer_upload_profiles_project_version",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(
        foreign_key="projects.id", ondelete="RESTRICT", index=True
    )
    version: int
    definition: dict[str, Any] = Field(sa_type=JSONB)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class CustomerUploadProfilePublic(CustomerUploadProfileDefinition):
    id: uuid.UUID
    version: int


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
