from __future__ import annotations

import hashlib
import os
import unicodedata
import uuid
from contextlib import suppress
from pathlib import Path, PurePath, PureWindowsPath
from typing import NoReturn
from zipfile import is_zipfile

from fastapi import UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.domain.customer_upload_validator import (
    MAX_WORKBOOK_BYTES,
    CustomerUploadValidationError,
    validate_customer_upload_workbook,
)
from app.domain.models import (
    Artifact,
    AuditEvent,
    CustomerUpload,
    CustomerUploadProfile,
    Project,
)

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_STREAM_CHUNK_SIZE = 1024 * 1024


class CustomerUploadAcceptanceError(Exception):
    """A stable upload failure that carries no customer-provided content."""

    def __init__(
        self, code: str, *, field: str | None = None, row: int | None = None
    ) -> None:
        super().__init__(code)
        self.code = code
        self.field = field
        self.row = row


def _raise(code: str) -> NoReturn:
    raise CustomerUploadAcceptanceError(code)


def _display_filename(filename: str | None) -> str:
    if (
        not filename
        or len(filename) > 128
        or PurePath(filename).name != filename
        or PureWindowsPath(filename).name != filename
        or any(unicodedata.category(character) == "Cc" for character in filename)
    ):
        _raise("invalid_filename")
    if not filename.endswith(".xlsx"):
        _raise("unsupported_workbook_type")
    return filename


def _remove_file(path: Path) -> None:
    with suppress(OSError):
        path.unlink(missing_ok=True)


def _stream_to_temporary_file(
    *, upload_file: UploadFile, temporary_path: Path
) -> tuple[int, str]:
    digest = hashlib.sha256()
    byte_size = 0
    try:
        destination = temporary_path.open("xb")
    except OSError:
        _raise("upload_storage_failed")

    try:
        with destination:
            while True:
                try:
                    chunk = upload_file.file.read(_STREAM_CHUNK_SIZE)
                except Exception:
                    _raise("incomplete_upload")
                if not chunk:
                    break
                byte_size += len(chunk)
                if byte_size > MAX_WORKBOOK_BYTES:
                    _raise("upload_too_large")
                digest.update(chunk)
                try:
                    written = destination.write(chunk)
                except OSError:
                    _raise("upload_storage_failed")
                if written != len(chunk):
                    _raise("upload_storage_failed")
            try:
                destination.flush()
                os.fsync(destination.fileno())
            except OSError:
                _raise("upload_storage_failed")
    except CustomerUploadAcceptanceError:
        _remove_file(temporary_path)
        raise
    return byte_size, digest.hexdigest()


def _validate_workbook(path: Path) -> tuple[int, list[dict[str, str | int | None]]]:
    if not is_zipfile(path):
        _raise("unsupported_workbook_type")
    try:
        result = validate_customer_upload_workbook(path)
    except CustomerUploadValidationError as error:
        raise CustomerUploadAcceptanceError(
            error.code, field=error.field, row=error.row
        )
    except Exception:
        _raise("upload_storage_failed")
    return result.record_count, [
        {"code": warning.code, "field": warning.field, "count": warning.count}
        for warning in result.warnings
    ]


def _accepted_audit_event(
    *,
    upload: CustomerUpload,
    actor_subject: str,
    ip_address: str | None,
) -> AuditEvent:
    return AuditEvent(
        tenant_id=upload.tenant_id,
        project_id=upload.project_id,
        actor_subject=actor_subject,
        actor_type="user",
        action="customer_upload.accepted",
        target_type="customer_upload",
        target_id=upload.id,
        before_data=None,
        after_data={
            "profile_id": str(upload.profile_id),
            "profile_version": upload.profile_version,
            "record_count": upload.record_count,
            "warning_count": len(upload.warnings),
        },
        ip_address=ip_address,
    )


def accept_customer_upload(
    *,
    session: Session,
    project: Project,
    upload_file: UploadFile,
    artifact_root: Path,
    actor_subject: str,
    ip_address: str | None,
) -> tuple[CustomerUpload, bool]:
    display_filename = _display_filename(upload_file.filename)
    profile = session.exec(
        select(CustomerUploadProfile).where(
            CustomerUploadProfile.id == project.current_customer_upload_profile_id,
            CustomerUploadProfile.project_id == project.id,
        )
    ).one()

    upload_directory = artifact_root / "customer_uploads"
    try:
        upload_directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        _raise("upload_storage_failed")
    temporary_path = upload_directory / f".{uuid.uuid4()}.tmp.xlsx"
    byte_size, raw_sha256 = _stream_to_temporary_file(
        upload_file=upload_file, temporary_path=temporary_path
    )

    try:
        record_count, warnings = _validate_workbook(temporary_path)
        existing = session.exec(
            select(CustomerUpload).where(
                CustomerUpload.project_id == project.id,
                CustomerUpload.raw_sha256 == raw_sha256,
                CustomerUpload.profile_id == profile.id,
                CustomerUpload.profile_version == profile.version,
            )
        ).one_or_none()
        if existing is not None:
            _remove_file(temporary_path)
            return existing, False

        artifact_id = uuid.uuid4()
        storage_key = f"customer_uploads/{artifact_id}.xlsx"
        final_path = artifact_root / storage_key
        try:
            os.replace(temporary_path, final_path)
            final_path.chmod(0o440)
        except OSError:
            _remove_file(temporary_path)
            _remove_file(final_path)
            _raise("upload_storage_failed")

        artifact = Artifact(
            id=artifact_id,
            tenant_id=project.tenant_id,
            storage_key=storage_key,
            media_type=XLSX_MEDIA_TYPE,
            byte_size=byte_size,
            sha256=raw_sha256,
        )
        customer_upload = CustomerUpload(
            tenant_id=project.tenant_id,
            project_id=project.id,
            artifact_id=artifact.id,
            display_filename=display_filename,
            raw_sha256=raw_sha256,
            profile_id=profile.id,
            profile_version=profile.version,
            record_count=record_count,
            warnings=warnings,
        )
        audit_event = _accepted_audit_event(
            upload=customer_upload,
            actor_subject=actor_subject,
            ip_address=ip_address,
        )
        try:
            session.add(artifact)
            session.flush()
            session.add(customer_upload)
            session.flush()
            session.add(audit_event)
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            _remove_file(final_path)
            _raise("upload_storage_failed")
        session.refresh(customer_upload)
        return customer_upload, True
    except CustomerUploadAcceptanceError:
        _remove_file(temporary_path)
        raise
