import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import EmailStr
from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


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


class ProjectPublic(ProjectBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ProjectsPublic(SQLModel):
    data: list[ProjectPublic]
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


class AuditEventsPublic(SQLModel):
    data: list[AuditEventPublic]
    count: int


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Internal properties used to bootstrap the first superuser
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


# Properties accepted when a global Admin creates an ordinary account
class UserCreateByAdmin(SQLModel):
    model_config = SQLModel.model_config | {"extra": "forbid"}

    email: EmailStr = Field(max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=8, max_length=128)


# Internal update properties, all optional
class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


# Properties a global Admin can update, all optional
class UserUpdateByAdmin(SQLModel):
    model_config = SQLModel.model_config | {"extra": "forbid"}

    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None
