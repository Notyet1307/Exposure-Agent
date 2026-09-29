"""Two-part bounded ZIP intake, reusing the existing streamed Dataset upload sink."""

from pathlib import Path, PureWindowsPath

from fastapi import Request
from pydantic import ValidationError
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header

from app.core.config import settings
from app.domain.netflow_common import deny
from app.domain.netflow_dataset_acceptance import (
    MAX_MULTIPART_OVERHEAD_BYTES,
    NetFlowUploadError,
    StreamedNetFlowUpload,
    _NetFlowMultipartStream,
)
from app.domain.netflow_processing import ImportMetadata


class _ResultStream(_NetFlowMultipartStream):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.metadata = bytearray()
        self.metadata_seen = False
        self.metadata_finished = False
        self.current_part_is_metadata = False

    def on_part_begin(self) -> None:
        super().on_part_begin()
        self.current_part_is_metadata = False

    def on_headers_finished(self) -> None:
        disposition, options = parse_options_header(self.disposition)
        name, filename = options.get(b"name"), options.get(b"filename")
        if disposition != b"form-data":
            raise NetFlowUploadError("netflow_import_incomplete")
        if name == b"metadata" and filename is None and not self.metadata_seen:
            self.metadata_seen = self.current_part_is_metadata = True
            return
        if name != b"file" or filename is None or self.upload_seen:
            raise NetFlowUploadError("netflow_import_incomplete")
        decoded = filename.decode("utf-8")
        if (
            len(decoded) > 128
            or Path(decoded).name != decoded
            or PureWindowsPath(decoded).name != decoded
            or any(ord(c) < 32 for c in decoded)
            or Path(decoded).suffix.lower() != ".zip"
        ):
            raise NetFlowUploadError("netflow_import_media_type")
        self.filename = decoded
        self.upload_seen = self.current_part_is_upload = True
        self.destination = self.path.open("xb")

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self.current_part_is_metadata:
            if len(self.metadata) + end - start > MAX_MULTIPART_OVERHEAD_BYTES:
                raise NetFlowUploadError("netflow_import_too_large")
            self.metadata.extend(data[start:end])
        else:
            super().on_part_data(data, start, end)

    def on_part_end(self) -> None:
        if self.current_part_is_metadata:
            self.metadata_finished = True
        super().on_part_end()


async def receive_result(
    request: Request, directory: Path
) -> tuple[StreamedNetFlowUpload, ImportMetadata]:
    content_type, options = parse_options_header(request.headers.get("content-type"))
    boundary = options.get(b"boundary")
    if content_type != b"multipart/form-data" or not boundary or len(boundary) > 200:
        deny("netflow_import_media_type", 415)
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    stream = _ResultStream(directory / "source.zip")
    received = 0
    try:
        parser = MultipartParser(boundary, stream.callbacks)
        async for chunk in request.stream():
            received += len(chunk)
            if received > settings.NETFLOW_MAX_BYTES + 2 * MAX_MULTIPART_OVERHEAD_BYTES:
                raise NetFlowUploadError("netflow_import_too_large")
            parser.write(chunk)
        parser.finalize()
        if not stream.metadata_seen or not stream.metadata_finished:
            raise NetFlowUploadError("netflow_import_incomplete")
        metadata = ImportMetadata.model_validate_json(bytes(stream.metadata))
        return stream.finish(), metadata
    except NetFlowUploadError as error:
        stream.abort()
        code = error.code
        if code == "netflow_too_large":
            code = "netflow_import_too_large"
        if not code.startswith("netflow_import_"):
            code = "netflow_import_incomplete"
        deny(
            code,
            413
            if code == "netflow_import_too_large"
            else 415
            if code == "netflow_import_media_type"
            else 422,
        )
    except ValidationError, UnicodeError, ValueError:
        stream.abort()
        deny("netflow_artifact_schema_invalid", 422)
    except OSError:
        stream.abort()
        deny("netflow_execution_unavailable", 503)
    except BaseException:
        stream.abort()
        raise
