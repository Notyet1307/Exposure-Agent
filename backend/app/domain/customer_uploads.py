from __future__ import annotations

import hashlib
import os
import unicodedata
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePath, PureWindowsPath
from typing import TYPE_CHECKING, BinaryIO, NoReturn
from zipfile import is_zipfile

from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session, select
from starlette.requests import Request

if TYPE_CHECKING:
    from python_multipart.multipart import MultipartCallbacks

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
MAX_MULTIPART_OVERHEAD_BYTES = 64 * 1024


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


def _remove_files(*paths: Path) -> None:
    cleanup_failed = False
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            cleanup_failed = True
    if cleanup_failed:
        _raise("upload_storage_failed")


@dataclass(frozen=True)
class StreamedCustomerUpload:
    temporary_path: Path
    display_filename: str
    byte_size: int
    raw_sha256: str


class _CustomerUploadMultipartStream:
    def __init__(self, temporary_path: Path) -> None:
        self.temporary_path = temporary_path
        self.destination: BinaryIO | None = None
        self.digest = hashlib.sha256()
        self.byte_size = 0
        self.display_filename: str | None = None
        self.upload_seen = False
        self.upload_finished = False
        self.multipart_complete = False
        self.current_part_is_upload = False
        self.partial_header_name = bytearray()
        self.partial_header_value = bytearray()
        self.content_disposition: bytes | None = None

    @property
    def callbacks(self) -> MultipartCallbacks:
        return {
            "on_part_begin": self.on_part_begin,
            "on_part_data": self.on_part_data,
            "on_part_end": self.on_part_end,
            "on_header_field": self.on_header_field,
            "on_header_value": self.on_header_value,
            "on_header_end": self.on_header_end,
            "on_headers_finished": self.on_headers_finished,
            "on_end": self.on_end,
        }

    def on_part_begin(self) -> None:
        self.current_part_is_upload = False
        self.content_disposition = None

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if not self.current_part_is_upload:
            return
        chunk = data[start:end]
        self.byte_size += len(chunk)
        if self.byte_size > MAX_WORKBOOK_BYTES:
            _raise("upload_too_large")
        self.digest.update(chunk)
        assert self.destination is not None
        try:
            written = self.destination.write(chunk)
        except OSError:
            _raise("upload_storage_failed")
        if written != len(chunk):
            _raise("upload_storage_failed")

    def on_part_end(self) -> None:
        if self.current_part_is_upload:
            self.upload_finished = True

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self.partial_header_name.extend(data[start:end])

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self.partial_header_value.extend(data[start:end])

    def on_header_end(self) -> None:
        if bytes(self.partial_header_name).lower() == b"content-disposition":
            self.content_disposition = bytes(self.partial_header_value)
        self.partial_header_name.clear()
        self.partial_header_value.clear()

    def on_headers_finished(self) -> None:
        disposition, options = parse_options_header(self.content_disposition)
        field_name = options.get(b"name")
        filename = options.get(b"filename")
        if filename is None:
            return
        if disposition != b"form-data" or field_name != b"file" or self.upload_seen:
            _raise("incomplete_upload")
        self.upload_seen = True
        self.current_part_is_upload = True
        try:
            decoded_filename = filename.decode("utf-8")
        except UnicodeDecodeError:
            decoded_filename = filename.decode("latin-1")
        self.display_filename = _display_filename(decoded_filename)
        try:
            self.destination = self.temporary_path.open("xb")
        except OSError:
            _raise("upload_storage_failed")

    def on_end(self) -> None:
        self.multipart_complete = True

    def finish(self) -> StreamedCustomerUpload:
        if (
            not self.multipart_complete
            or not self.upload_seen
            or not self.upload_finished
            or self.destination is None
            or self.display_filename is None
        ):
            _raise("incomplete_upload")
        try:
            self.destination.flush()
            os.fsync(self.destination.fileno())
            self.destination.close()
        except OSError:
            self.abort()
            _raise("upload_storage_failed")
        return StreamedCustomerUpload(
            temporary_path=self.temporary_path,
            display_filename=self.display_filename,
            byte_size=self.byte_size,
            raw_sha256=self.digest.hexdigest(),
        )

    def abort(self) -> None:
        if self.destination is not None:
            with suppress(OSError):
                self.destination.close()
        _remove_files(self.temporary_path)


async def stream_customer_upload_request(
    *, request: Request, artifact_root: Path
) -> StreamedCustomerUpload:
    content_type, options = parse_options_header(request.headers.get("content-type"))
    boundary = options.get(b"boundary")
    if content_type != b"multipart/form-data" or boundary is None:
        _raise("incomplete_upload")

    upload_directory = artifact_root / "customer_uploads"
    try:
        upload_directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        _raise("upload_storage_failed")
    temporary_path = upload_directory / f".{uuid.uuid4()}.tmp.xlsx"
    stream = _CustomerUploadMultipartStream(temporary_path)
    received_bytes = 0
    try:
        parser = MultipartParser(boundary, stream.callbacks)
        async for chunk in request.stream():
            if chunk:
                received_bytes += len(chunk)
                if received_bytes > (
                    MAX_WORKBOOK_BYTES + MAX_MULTIPART_OVERHEAD_BYTES
                ):
                    _raise("upload_too_large")
                parser.write(chunk)
        parser.finalize()
        return stream.finish()
    except CustomerUploadAcceptanceError:
        stream.abort()
        raise
    except Exception:
        stream.abort()
        _raise("incomplete_upload")
    except BaseException:
        stream.abort()
        raise


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


def _find_existing_upload(
    *,
    session: Session,
    project: Project,
    profile: CustomerUploadProfile,
    raw_sha256: str,
) -> CustomerUpload | None:
    return session.exec(
        select(CustomerUpload).where(
            CustomerUpload.project_id == project.id,
            CustomerUpload.raw_sha256 == raw_sha256,
            CustomerUpload.profile_id == profile.id,
            CustomerUpload.profile_version == profile.version,
        )
    ).one_or_none()


def accept_customer_upload(
    *,
    session: Session,
    project: Project,
    streamed_upload: StreamedCustomerUpload,
    artifact_root: Path,
    actor_subject: str,
    ip_address: str | None,
) -> tuple[CustomerUpload, bool]:
    temporary_path = streamed_upload.temporary_path
    try:
        try:
            profile = session.exec(
                select(CustomerUploadProfile).where(
                    CustomerUploadProfile.id
                    == project.current_customer_upload_profile_id,
                    CustomerUploadProfile.project_id == project.id,
                )
            ).one()
        except SQLAlchemyError:
            session.rollback()
            _raise("upload_storage_failed")

        record_count, warnings = _validate_workbook(temporary_path)
        try:
            existing = _find_existing_upload(
                session=session,
                project=project,
                profile=profile,
                raw_sha256=streamed_upload.raw_sha256,
            )
        except SQLAlchemyError:
            session.rollback()
            _raise("upload_storage_failed")
        if existing is not None:
            _remove_files(temporary_path)
            return existing, False

        artifact_id = uuid.uuid4()
        storage_key = f"customer_uploads/{artifact_id}.xlsx"
        final_path = artifact_root / storage_key
        try:
            os.replace(temporary_path, final_path)
            final_path.chmod(0o440)
        except OSError:
            _remove_files(temporary_path, final_path)
            _raise("upload_storage_failed")

        artifact = Artifact(
            id=artifact_id,
            tenant_id=project.tenant_id,
            storage_key=storage_key,
            media_type=XLSX_MEDIA_TYPE,
            byte_size=streamed_upload.byte_size,
            sha256=streamed_upload.raw_sha256,
        )
        customer_upload = CustomerUpload(
            tenant_id=project.tenant_id,
            project_id=project.id,
            artifact_id=artifact.id,
            display_filename=streamed_upload.display_filename,
            raw_sha256=streamed_upload.raw_sha256,
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
            session.flush()
            session.expunge(customer_upload)
            session.commit()
        except IntegrityError:
            session.rollback()
            _remove_files(final_path)
            try:
                existing = _find_existing_upload(
                    session=session,
                    project=project,
                    profile=profile,
                    raw_sha256=streamed_upload.raw_sha256,
                )
            except SQLAlchemyError:
                _raise("upload_storage_failed")
            if existing is None:
                _raise("upload_storage_failed")
            return existing, False
        except SQLAlchemyError:
            session.rollback()
            _remove_files(final_path)
            _raise("upload_storage_failed")
        return customer_upload, True
    except CustomerUploadAcceptanceError:
        _remove_files(temporary_path)
        raise
