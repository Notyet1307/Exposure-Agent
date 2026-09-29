"""Scoped operation recovery and existing Artifact receipts for source-side NetFlow."""

import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.api.project_authorization import PROJECT_READ_ROLES, get_authorized_project
from app.core.config import settings
from app.domain.models import Artifact, AuditEvent, Project, ProjectRole
from app.models import User

MAX_MEMBER_BYTES = 100 * 1024 * 1024
MAX_BUNDLE_BYTES = 320 * 1024 * 1024
MAX_BUNDLE_FILES = 32


def deny(code: str, status: int = 409) -> NoReturn:
    raise HTTPException(status_code=status, detail={"code": code})


def request_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def project_for(
    session: Session,
    user: User,
    project_id: uuid.UUID,
    *,
    write: bool = False,
    admin: bool = False,
) -> Project:
    project = get_authorized_project(
        session=session,
        user=user,
        project_id=project_id,
        allowed_roles=PROJECT_READ_ROLES,
        lock=write,
    )
    if admin and not user.is_superuser:
        deny("netflow_context_admin_required", 403)
    if write:
        try:
            project = get_authorized_project(
                session=session,
                user=user,
                project_id=project_id,
                allowed_roles=(ProjectRole.OPERATOR,),
                writable=True,
            )
        except HTTPException as error:
            if error.status_code == 404:
                deny("netflow_write_forbidden", 403)
            raise
    return project


def _operation_key(key: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key):
        deny("netflow_key_conflict", 422)


def operation_result(
    session: Session,
    project: Project,
    actor_id: uuid.UUID,
    operation: str,
    key: str,
    request: dict[str, Any] | None = None,
) -> uuid.UUID | None:
    _operation_key(key)
    event = session.exec(
        select(AuditEvent).where(
            AuditEvent.tenant_id == project.tenant_id,
            AuditEvent.project_id == project.id,
            AuditEvent.actor_subject == str(actor_id),
            AuditEvent.action == "netflow.operation",
            col(AuditEvent.after_data)["operation"].as_string() == operation,
            col(AuditEvent.after_data)["operation_key"].as_string() == key,
        )
    ).one_or_none()
    if event is None:
        return None
    if event.after_data is None or (
        request is not None
        and event.after_data.get("request_sha256") != request_hash(request)
    ):
        deny("netflow_key_conflict")
    return event.target_id


def record_operation(
    session: Session,
    project: Project,
    actor_id: uuid.UUID,
    operation: str,
    key: str,
    request: dict[str, Any],
    result_id: uuid.UUID,
) -> None:
    _operation_key(key)
    session.add(
        AuditEvent(
            tenant_id=project.tenant_id,
            project_id=project.id,
            actor_subject=str(actor_id),
            actor_type="user",
            action="netflow.operation",
            target_type="netflow_operation",
            target_id=result_id,
            after_data={
                "operation": operation,
                "operation_key": key,
                "request_sha256": request_hash(request),
            },
        )
    )


def new_output_directory(project_id: uuid.UUID, purpose: str) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", purpose):
        deny("netflow_artifact_integrity_failed")
    root = settings.ARTIFACT_ROOT.resolve()
    parent = root / "netflow-processing" / str(project_id) / purpose
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink() or root not in parent.resolve().parents:
        deny("netflow_artifact_integrity_failed")
    return parent / str(uuid.uuid4())


def _safe_path(directory: Path, name: str) -> Path:
    if not isinstance(name, str) or "\\" in name or "\x00" in name:
        deny("netflow_artifact_integrity_failed")
    relative = PurePosixPath(name)
    if (
        not name
        or relative.is_absolute()
        or name != relative.as_posix()
        or any(p in (".", "..") for p in relative.parts)
    ):
        deny("netflow_artifact_integrity_failed")
    path = directory
    try:
        for part in relative.parts:
            path = path / part
            if path.is_symlink():
                deny("netflow_artifact_integrity_failed")
        if directory.resolve() not in path.resolve(strict=True).parents:
            deny("netflow_artifact_integrity_failed")
    except OSError, ValueError:
        deny("netflow_artifact_integrity_failed")
    return path


def _fingerprint(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            initial = os.fstat(stream.fileno())
            if not stat.S_ISREG(initial.st_mode) or initial.st_size > MAX_MEMBER_BYTES:
                deny("netflow_artifact_integrity_failed")
            while block := stream.read(1024 * 1024):
                size += len(block)
                if size > MAX_MEMBER_BYTES:
                    deny("netflow_processing_limit", 413)
                digest.update(block)
            final = os.fstat(stream.fileno())
            if (
                initial.st_size != size
                or final.st_size != size
                or final.st_mtime_ns != initial.st_mtime_ns
            ):
                deny("netflow_artifact_integrity_failed")
    except OSError:
        deny("netflow_artifact_integrity_failed")
    return digest.hexdigest(), size


def _root(directory: Path) -> tuple[Path, str]:
    root = settings.ARTIFACT_ROOT.resolve()
    try:
        relative = directory.relative_to(root)
        cursor = root
        for part in relative.parts:
            cursor /= part
            if cursor.is_symlink():
                deny("netflow_artifact_integrity_failed")
        if (
            not relative.parts
            or not directory.is_dir()
            or directory.resolve() != directory
        ):
            deny("netflow_artifact_integrity_failed")
    except OSError, ValueError:
        deny("netflow_artifact_integrity_failed")
    return directory, relative.as_posix()


def seal_artifacts(
    session: Session, project: Project, directory: Path, filenames: list[str]
) -> dict[str, Any]:
    directory, relative_root = _root(directory)
    if (
        not filenames
        or len(filenames) > MAX_BUNDLE_FILES
        or len(set(filenames)) != len(filenames)
    ):
        deny("netflow_processing_limit", 413)
    files: dict[str, Any] = {}
    total = 0
    for name in sorted(filenames):
        path = _safe_path(directory, name)
        digest, size = _fingerprint(path)
        total += size
        if total > MAX_BUNDLE_BYTES:
            deny("netflow_processing_limit", 413)
        artifact_id: uuid.UUID | None = None
        if size:
            storage_key = f"{relative_root}/{name}"
            artifact = session.exec(
                select(Artifact).where(
                    Artifact.storage_key == storage_key,
                )
            ).one_or_none()
            if artifact is not None:
                if (
                    artifact.project_id != project.id
                    or artifact.tenant_id != project.tenant_id
                    or artifact.sha256 != digest
                    or artifact.byte_size != size
                ):
                    deny("netflow_artifact_integrity_failed")
            else:
                artifact = Artifact(
                    tenant_id=project.tenant_id,
                    project_id=project.id,
                    storage_key=storage_key,
                    media_type="application/json"
                    if name.endswith(".json")
                    else "application/octet-stream",
                    byte_size=size,
                    sha256=digest,
                )
                session.add(artifact)
            artifact_id = artifact.id
        files[name] = {
            "artifact_id": str(artifact_id) if artifact_id else None,
            "sha256": digest,
            "byte_size": size,
        }
    return {"root": relative_root, "files": files}


def verify_receipt(session: Session, project: Project, receipt: dict[str, Any]) -> Path:
    root = settings.ARTIFACT_ROOT.resolve()
    relative = receipt.get("root")
    files = receipt.get("files")
    if (
        not isinstance(relative, str)
        or not isinstance(files, dict)
        or not files
        or len(files) > MAX_BUNDLE_FILES
    ):
        deny("netflow_artifact_integrity_failed")
    if (
        not relative
        or relative != PurePosixPath(relative).as_posix()
        or PurePosixPath(relative).is_absolute()
        or ".." in PurePosixPath(relative).parts
    ):
        deny("netflow_artifact_integrity_failed")
    directory, relative_root = _root(root / relative)
    total = 0
    for name, descriptor in files.items():
        if not isinstance(descriptor, dict):
            deny("netflow_artifact_integrity_failed")
        digest, size = _fingerprint(_safe_path(directory, name))
        total += size
        if (
            total > MAX_BUNDLE_BYTES
            or digest != descriptor.get("sha256")
            or type(descriptor.get("byte_size")) is not int
            or size != descriptor["byte_size"]
        ):
            deny("netflow_artifact_integrity_failed")
        identifier = descriptor.get("artifact_id")
        if size == 0:
            if identifier is not None:
                deny("netflow_artifact_integrity_failed")
            continue
        try:
            artifact_id = uuid.UUID(identifier)
        except ValueError, TypeError, AttributeError:
            deny("netflow_artifact_integrity_failed")
        artifact = session.exec(
            select(Artifact).where(
                Artifact.id == artifact_id,
                Artifact.tenant_id == project.tenant_id,
                Artifact.project_id == project.id,
            )
        ).one_or_none()
        if (
            artifact is None
            or artifact.sha256 != digest
            or artifact.byte_size != size
            or artifact.storage_key != f"{relative_root}/{name}"
        ):
            deny("netflow_artifact_integrity_failed")
    return directory
