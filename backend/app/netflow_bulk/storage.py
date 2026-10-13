"""Offline snapshot sealing and safe immutable file publication."""

import hashlib
import json
import os
import shutil
import stat
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from app.netflow_bulk.contracts import (
    MAX_MANIFEST,
    BulkError,
    Member,
    Ready,
    canonical_json,
    digest,
)


def safe_file(root: Path, relative: str) -> Path:
    if not relative or relative.startswith("/") or "\\" in relative or "\0" in relative:
        raise BulkError("bulk_unsafe_path")
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise BulkError("bulk_unsafe_path")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise BulkError("bulk_unsafe_path")
    if (
        not current.is_file()
        or not stat.S_ISREG(current.stat().st_mode)
        or root.resolve() not in current.resolve().parents
    ):
        raise BulkError("bulk_unsafe_path")
    return current


def file_hash(path: Path, *, pulse: Callable[[], None] | None = None) -> str:
    value = hashlib.sha256()
    since_check = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
            since_check += len(block)
            if pulse is not None and since_check >= 64 * 1024 * 1024:
                pulse()
                since_check = 0
    if pulse is not None:
        pulse()
    return value.hexdigest()


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_directory(path: Path, mode: int = 0o750) -> None:
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    for created in reversed(missing):
        sync_directory(created)
        sync_directory(created.parent)


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(value))
        stream.flush()
        os.fchmod(stream.fileno(), 0o440)
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


def seal(
    source: Path,
    root: Path,
    *,
    tenant: str,
    project: str,
    source_id: str,
    encoding: Literal["utf-8-sig", "gb18030"] = "utf-8-sig",
    timezone: str = "UTC",
    reserve_bytes: int = 2 * 1024**3,
) -> tuple[str, Ready]:
    """Copy closed files into a private snapshot, then atomically expose ready.

    The operator owns root; application users must never have write access.
    Original input may remain writable; only the independent copy is admitted.
    """
    tenant, project = str(uuid.UUID(tenant)), str(uuid.UUID(project))
    Ready(
        tenant_id=tenant,
        project_id=project,
        source_id=source_id,
        files=[Member(sha256="0" * 64, size=1, name="validation.csv")],
    )
    parent = root / tenant / project / source_id
    durable_directory(parent)
    if any(
        p.is_symlink() for p in (root, root / tenant, root / tenant / project, parent)
    ):
        raise BulkError("bulk_unsafe_path")
    temporary = parent / f".{uuid.uuid4()}.staging"
    durable_directory(temporary, mode=0o700)
    members: list[Member] = []
    try:
        entries = sorted(source.iterdir())
        if not entries or len(entries) > 4096:
            raise BulkError("bulk_file_limit")
        for candidate in entries:
            path = safe_file(source, candidate.name)
            before = path.stat()
            if before.st_size + reserve_bytes > shutil.disk_usage(parent).free:
                raise BulkError("bulk_disk_budget")
            # The name validation deliberately rejects compression and other formats.
            Member(
                sha256="0" * 64,
                size=before.st_size,
                name=path.name,
                encoding=encoding,
                timezone=timezone,
            )
            copied = temporary / f".{uuid.uuid4()}.copy"
            checksum = hashlib.sha256()
            size = 0
            with (
                os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as incoming,
                copied.open("xb") as outgoing,
            ):
                while block := incoming.read(1024 * 1024):
                    checksum.update(block)
                    size += len(block)
                    if size > before.st_size or shutil.disk_usage(
                        parent
                    ).free < reserve_bytes + len(block):
                        raise BulkError("bulk_input_changed_or_disk_budget")
                    outgoing.write(block)
                outgoing.flush()
                os.fchmod(outgoing.fileno(), 0o440)
                os.fsync(outgoing.fileno())
            after = path.stat()
            if (
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ) or size != before.st_size:
                raise BulkError("bulk_input_changed")
            sha = checksum.hexdigest()
            destination = temporary / sha
            if destination.exists():
                raise BulkError("bulk_duplicate_file")
            copied.rename(destination)
            members.append(
                Member(
                    sha256=sha,
                    size=size,
                    name=path.name,
                    encoding=encoding,
                    timezone=timezone,
                )
            )
        ready = Ready(
            tenant_id=tenant, project_id=project, source_id=source_id, files=members
        )
        value = ready.model_dump(mode="json")
        identity = digest(value)
        if len(canonical_json(value).encode()) > MAX_MANIFEST:
            raise BulkError("bulk_manifest_limit")
        atomic_json(temporary / "ready.json", value)
        target = parent / identity
        if target.exists():
            existing = read_ready(root, tenant, project, source_id, identity)
            if existing != ready:
                raise BulkError("bulk_input_changed")
            shutil.rmtree(temporary)
        else:
            temporary.chmod(0o550)
            temporary.rename(target)
            sync_directory(target)
            sync_directory(parent)
        return identity, ready
    except BaseException:
        # Only the private, unpublished staging directory created above is removed.
        if temporary.exists():
            temporary.chmod(0o700)
            shutil.rmtree(temporary)
        raise


def read_ready(
    root: Path, tenant: str, project: str, source_id: str, identity: str
) -> Ready:
    import re

    tenant, project = str(uuid.UUID(tenant)), str(uuid.UUID(project))
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", source_id) or not re.fullmatch(
        r"[0-9a-f]{64}", identity
    ):
        raise BulkError("bulk_unsafe_path")
    path = safe_file(root, f"{tenant}/{project}/{source_id}/{identity}/ready.json")
    if path.stat().st_size > MAX_MANIFEST:
        raise BulkError("bulk_manifest_limit")
    with path.open("rb") as stream:
        raw = stream.read(MAX_MANIFEST + 1)
    if len(raw) > MAX_MANIFEST:
        raise BulkError("bulk_manifest_limit")
    ready = Ready.model_validate(json.loads(raw))
    if (ready.tenant_id, ready.project_id, ready.source_id) != (
        tenant,
        project,
        source_id,
    ) or digest(ready.model_dump(mode="json")) != identity:
        raise BulkError("bulk_input_changed")
    return ready
