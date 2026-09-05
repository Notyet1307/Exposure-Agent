import asyncio
import hashlib
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request
from starlette.types import Message, Scope

from app.domain.netflow_dataset_acceptance import (
    NetFlowUploadError,
    StreamedNetFlowUpload,
    accept_netflow_dataset,
    stream_netflow_upload,
)


class FailingSession:
    def exec(self, _statement: object) -> Any:
        raise SQLAlchemyError("query failed")

    def rollback(self) -> None:
        pass


def test_initial_query_failure_cleans_every_scan_file(tmp_path: Path) -> None:
    directory = tmp_path / "netflow_datasets"
    directory.mkdir()
    raw = directory / ".upload.tmp"
    content = (
        b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
        b"198.51.100.20,192.0.2.10,6,53000,443\n"
    )
    raw.write_bytes(content)
    streamed = StreamedNetFlowUpload(
        temporary_path=raw,
        display_filename="flows.csv",
        byte_size=len(content),
        raw_sha256=hashlib.sha256(content).hexdigest(),
    )
    project = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    with pytest.raises(NetFlowUploadError) as caught:
        accept_netflow_dataset(
            session=FailingSession(),  # type: ignore[arg-type]
            project=project,  # type: ignore[arg-type]
            streamed_upload=streamed,
            artifact_root=tmp_path,
            actor_subject="actor",
            ip_address=None,
        )
    assert caught.value.code == "netflow_storage_failed"
    assert list(directory.iterdir()) == []


def test_cancelled_multipart_stream_removes_temporary_file(tmp_path: Path) -> None:
    boundary = b"netflow-boundary"
    first_chunk = b"--" + boundary + b'\r\nContent-Disposition: form-data; name="file"; filename="flows.csv"\r\nContent-Type: text/csv\r\n\r\npartial'
    messages: list[Message] = [{"type": "http.request", "body": first_chunk, "more_body": True}]

    async def receive() -> Message:
        if messages:
            return messages.pop()
        raise asyncio.CancelledError

    scope: Scope = {"type": "http", "method": "POST", "headers": [(b"content-type", b"multipart/form-data; boundary=" + boundary)]}
    request = Request(scope, receive)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(stream_netflow_upload(request, tmp_path))
    assert not list((tmp_path / "netflow_datasets").iterdir())
