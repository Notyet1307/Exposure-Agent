from __future__ import annotations

import hashlib
import os
import stat
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePath, PureWindowsPath
from typing import TYPE_CHECKING, BinaryIO

from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session, select
from starlette.requests import Request

from app.core.config import settings
from app.core.time import get_datetime_utc
from app.domain.audit import commit_with_audit
from app.domain.models import Artifact, AuditEvent, NetFlowDataset, Project
from app.domain.netflow_datasets import NetFlowAcceptanceError, parse_netflow_dataset

if TYPE_CHECKING:
    from python_multipart.multipart import MultipartCallbacks

RAW_MEDIA_TYPE = "text/csv"
NORMALIZED_MEDIA_TYPE = "text/csv"
MAX_MULTIPART_OVERHEAD_BYTES = 64 * 1024


class NetFlowUploadError(Exception):
    def __init__(
        self, code: str, *, field: str | None = None, row: int | None = None
    ) -> None:
        super().__init__(code)
        self.code = code
        self.field = field
        self.row = row


def _display_filename(filename: str) -> str:
    if (
        not filename
        or len(filename) > 128
        or PurePath(filename).name != filename
        or PureWindowsPath(filename).name != filename
        or any(unicodedata.category(character) == "Cc" for character in filename)
    ):
        raise NetFlowUploadError("netflow_invalid_filename")
    if Path(filename).suffix.lower() not in {".csv", ".txt"}:
        raise NetFlowUploadError("netflow_unsupported_type")
    return filename


@dataclass(frozen=True)
class StreamedNetFlowUpload:
    temporary_path: Path
    display_filename: str
    byte_size: int
    raw_sha256: str


class _NetFlowMultipartStream:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.destination: BinaryIO | None = None
        self.digest = hashlib.sha256()
        self.byte_size = 0
        self.filename: str | None = None
        self.upload_seen = False
        self.upload_finished = False
        self.multipart_complete = False
        self.current_part_is_upload = False
        self.partial_name = bytearray()
        self.partial_value = bytearray()
        self.disposition: bytes | None = None

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
        self.disposition = None

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if not self.current_part_is_upload:
            return
        chunk = data[start:end]
        self.byte_size += len(chunk)
        if self.byte_size > settings.NETFLOW_MAX_BYTES:
            raise NetFlowUploadError("netflow_too_large")
        self.digest.update(chunk)
        assert self.destination is not None
        try:
            if self.destination.write(chunk) != len(chunk):
                raise OSError
        except OSError as error:
            raise NetFlowUploadError("netflow_storage_failed") from error

    def on_part_end(self) -> None:
        if self.current_part_is_upload:
            self.upload_finished = True

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self.partial_name.extend(data[start:end])

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self.partial_value.extend(data[start:end])

    def on_header_end(self) -> None:
        if bytes(self.partial_name).lower() == b"content-disposition":
            self.disposition = bytes(self.partial_value)
        self.partial_name.clear()
        self.partial_value.clear()

    def on_headers_finished(self) -> None:
        disposition, options = parse_options_header(self.disposition)
        filename = options.get(b"filename")
        if filename is None:
            return
        if (
            disposition != b"form-data"
            or options.get(b"name") != b"file"
            or self.upload_seen
        ):
            raise NetFlowUploadError("netflow_incomplete_upload")
        self.upload_seen = True
        self.current_part_is_upload = True
        try:
            decoded = filename.decode("utf-8")
        except UnicodeDecodeError:
            decoded = filename.decode("latin-1")
        self.filename = _display_filename(decoded)
        try:
            self.destination = self.path.open("xb")
        except OSError as error:
            raise NetFlowUploadError("netflow_storage_failed") from error

    def on_end(self) -> None:
        self.multipart_complete = True

    def finish(self) -> StreamedNetFlowUpload:
        if (
            not self.multipart_complete
            or not self.upload_seen
            or not self.upload_finished
            or self.destination is None
            or self.filename is None
        ):
            raise NetFlowUploadError("netflow_incomplete_upload")
        try:
            self.destination.flush()
            os.fsync(self.destination.fileno())
            self.destination.close()
        except OSError as error:
            self.abort()
            raise NetFlowUploadError("netflow_storage_failed") from error
        return StreamedNetFlowUpload(
            self.path, self.filename, self.byte_size, self.digest.hexdigest()
        )

    def abort(self) -> None:
        if self.destination is not None:
            try:
                self.destination.close()
            except OSError:
                pass
        try:
            self.path.unlink()
        except OSError:
            pass


async def stream_netflow_upload(
    request: Request, artifact_root: Path
) -> StreamedNetFlowUpload:
    content_type, options = parse_options_header(request.headers.get("content-type"))
    boundary = options.get(b"boundary")
    if content_type != b"multipart/form-data" or boundary is None:
        raise NetFlowUploadError("netflow_incomplete_upload")
    directory = artifact_root / "netflow_datasets"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise NetFlowUploadError("netflow_storage_failed") from error
    temporary_path = directory / f".{uuid.uuid4()}.tmp"
    stream = _NetFlowMultipartStream(temporary_path)
    received = 0
    try:
        parser = MultipartParser(boundary, stream.callbacks)
        async for chunk in request.stream():
            if chunk:
                received += len(chunk)
                if received > settings.NETFLOW_MAX_BYTES + MAX_MULTIPART_OVERHEAD_BYTES:
                    raise NetFlowUploadError("netflow_too_large")
                parser.write(chunk)
        parser.finalize()
        return stream.finish()
    except NetFlowUploadError:
        stream.abort()
        raise
    except Exception as error:
        stream.abort()
        raise NetFlowUploadError("netflow_incomplete_upload") from error
    except BaseException:
        stream.abort()
        raise


def _remove(*paths: Path | None) -> bool:
    failed = False
    for path in paths:
        if path is None:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            failed = True
    return not failed


def _verify_file(path: Path, expected_size: int, expected_sha256: str) -> bool:
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size != expected_size:
            return False
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest() == expected_sha256
    except OSError:
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _audit(
    dataset: NetFlowDataset, actor_subject: str, ip_address: str | None
) -> AuditEvent:
    return AuditEvent(
        tenant_id=dataset.tenant_id,
        project_id=dataset.project_id,
        actor_subject=actor_subject,
        actor_type="user",
        action="netflow_dataset.accepted",
        target_type="netflow_dataset",
        target_id=dataset.id,
        before_data=None,
        after_data={
            "dataset_contract_version": dataset.dataset_contract_version,
            "raw_sha256": dataset.raw_sha256,
            "normalized_sha256": dataset.normalized_sha256,
            "raw_record_count": dataset.raw_record_count,
            "activity_valid_record_count": dataset.activity_valid_record_count,
            "isolated_record_count": dataset.isolated_record_count,
            "warning_count": len(dataset.warnings),
        },
        ip_address=ip_address,
    )


def accept_netflow_dataset(
    *,
    session: Session,
    project: Project,
    streamed_upload: StreamedNetFlowUpload,
    artifact_root: Path,
    actor_subject: str,
    ip_address: str | None,
) -> tuple[NetFlowDataset, bool]:
    temporary = streamed_upload.temporary_path
    normalized_tmp: Path | None = None
    raw_path: Path | None = None
    normalized_path: Path | None = None
    try:
        suffix = Path(streamed_upload.display_filename).suffix.lower()
        if suffix not in {".csv", ".txt"}:
            raise NetFlowUploadError("netflow_unsupported_type")
        try:
            if temporary.stat().st_size > settings.NETFLOW_MAX_BYTES:
                raise NetFlowUploadError("netflow_too_large")
            parsed = parse_netflow_dataset(temporary)
            normalized_tmp = parsed.normalized_path
        except NetFlowAcceptanceError as error:
            raise NetFlowUploadError(
                error.code, field=error.field, row=error.row
            ) from error
        if (
            parsed.raw_sha256 != streamed_upload.raw_sha256
            or parsed.raw_byte_size != streamed_upload.byte_size
            or parsed.raw_byte_size > settings.NETFLOW_MAX_BYTES
        ):
            raise NetFlowUploadError("netflow_content_changed")
        try:
            existing = session.exec(
                select(NetFlowDataset).where(
                    NetFlowDataset.project_id == project.id,
                    NetFlowDataset.tenant_id == project.tenant_id,
                    NetFlowDataset.raw_sha256 == parsed.raw_sha256,
                    NetFlowDataset.dataset_contract_version == parsed.contract_version,
                )
            ).one_or_none()
        except SQLAlchemyError as error:
            session.rollback()
            raise NetFlowUploadError("netflow_storage_failed") from error
        if existing is not None:
            if not _remove(temporary, normalized_tmp):
                raise NetFlowUploadError("netflow_storage_failed")
            return existing, False
        raw_id, normalized_id, dataset_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        raw_path = artifact_root / f"netflow_datasets/{raw_id}.raw"
        normalized_path = artifact_root / f"netflow_datasets/{normalized_id}.csv"
        try:
            with normalized_tmp.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, raw_path)
            os.replace(normalized_tmp, normalized_path)
            raw_path.chmod(0o440)
            normalized_path.chmod(0o440)
        except OSError as error:
            _remove(temporary, normalized_tmp, raw_path, normalized_path)
            raise NetFlowUploadError("netflow_storage_failed") from error
        raw_artifact = Artifact(
            id=raw_id,
            tenant_id=project.tenant_id,
            project_id=project.id,
            storage_key=f"netflow_datasets/{raw_id}.raw",
            media_type=RAW_MEDIA_TYPE,
            byte_size=parsed.raw_byte_size,
            sha256=parsed.raw_sha256,
        )
        normalized_artifact = Artifact(
            id=normalized_id,
            tenant_id=project.tenant_id,
            project_id=project.id,
            storage_key=f"netflow_datasets/{normalized_id}.csv",
            media_type=NORMALIZED_MEDIA_TYPE,
            byte_size=parsed.normalized_byte_size,
            sha256=parsed.normalized_sha256,
        )
        dataset = NetFlowDataset(
            id=dataset_id,
            tenant_id=project.tenant_id,
            project_id=project.id,
            raw_artifact_id=raw_id,
            normalized_artifact_id=normalized_id,
            display_filename=streamed_upload.display_filename,
            raw_sha256=parsed.raw_sha256,
            normalized_sha256=parsed.normalized_sha256,
            dataset_contract_version=parsed.contract_version,
            schema_fingerprint=parsed.schema_fingerprint,
            encoding=parsed.encoding,
            byte_size=parsed.raw_byte_size,
            raw_record_count=parsed.raw_record_count,
            activity_valid_record_count=parsed.activity_valid_record_count,
            isolated_record_count=parsed.isolated_record_count,
            valid_time_start_utc=(
                datetime.fromisoformat(parsed.valid_time_start_utc.replace("Z", "+00:00"))
                if parsed.valid_time_start_utc is not None else None
            ),
            valid_time_end_utc=(
                datetime.fromisoformat(parsed.valid_time_end_utc.replace("Z", "+00:00"))
                if parsed.valid_time_end_utc is not None else None
            ),
            duplicate_group_count=parsed.duplicate_group_count,
            duplicate_record_count=parsed.duplicate_record_count,
            warnings=list(parsed.warnings),
        )
        try:
            if not _verify_file(
                raw_path, parsed.raw_byte_size, parsed.raw_sha256
            ) or not _verify_file(
                normalized_path, parsed.normalized_byte_size, parsed.normalized_sha256
            ):
                raise NetFlowUploadError("netflow_storage_failed")
            session.add(raw_artifact)
            session.add(normalized_artifact)
            session.add(dataset)
            session.add(_audit(dataset, actor_subject, ip_address))
            session.commit()
        except IntegrityError:
            session.rollback()
            cleanup_succeeded = _remove(raw_path, normalized_path)
            try:
                existing = session.exec(
                    select(NetFlowDataset).where(
                        NetFlowDataset.project_id == project.id,
                        NetFlowDataset.tenant_id == project.tenant_id,
                        NetFlowDataset.raw_sha256 == parsed.raw_sha256,
                        NetFlowDataset.dataset_contract_version
                        == parsed.contract_version,
                    )
                ).one_or_none()
            except SQLAlchemyError as error:
                session.rollback()
                raise NetFlowUploadError("netflow_storage_failed") from error
            if existing is None or not cleanup_succeeded:
                raise NetFlowUploadError("netflow_storage_failed")
            return existing, False
        except (SQLAlchemyError, NetFlowUploadError) as error:
            session.rollback()
            _remove(raw_path, normalized_path)
            if isinstance(error, NetFlowUploadError):
                raise
            raise NetFlowUploadError("netflow_storage_failed") from error
        return dataset, True
    except NetFlowUploadError:
        _remove(temporary, normalized_tmp, raw_path, normalized_path)
        raise
    except BaseException:
        session.rollback()
        _remove(temporary, normalized_tmp, raw_path, normalized_path)
        raise


def set_current_netflow_dataset(
    *,
    session: Session,
    project: Project,
    dataset: NetFlowDataset | None,
    actor_subject: str,
    ip_address: str | None,
) -> None:
    previous_dataset_id = project.current_netflow_dataset_id
    selected_dataset_id = dataset.id if dataset is not None else None
    if previous_dataset_id == selected_dataset_id:
        return

    target_id = selected_dataset_id or previous_dataset_id
    assert target_id is not None
    project.current_netflow_dataset_id = selected_dataset_id
    project.updated_at = get_datetime_utc()
    audit_event = AuditEvent(
        tenant_id=project.tenant_id,
        project_id=project.id,
        actor_subject=actor_subject,
        actor_type="user",
        action=(
            "netflow_dataset.selected"
            if selected_dataset_id is not None
            else "netflow_dataset.cleared"
        ),
        target_type="netflow_dataset",
        target_id=target_id,
        before_data={
            "current_netflow_dataset_id": (
                str(previous_dataset_id) if previous_dataset_id is not None else None
            )
        },
        after_data={
            "current_netflow_dataset_id": (
                str(selected_dataset_id) if selected_dataset_id is not None else None
            )
        },
        ip_address=ip_address,
    )
    commit_with_audit(session=session, record=project, audit_event=audit_event)
