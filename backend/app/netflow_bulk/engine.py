"""Bounded CSV normalization and exact, spillable whole-dataset computation."""

import csv
import hashlib
import io
import ipaddress
import os
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, TextIO
from zoneinfo import ZoneInfo

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from app.netflow_bulk.contracts import (
    ENGINE,
    MAX_BATCH_BYTES,
    MAX_FIELD,
    MAX_RECORD,
    NORMALIZER,
    POLICY,
    Budget,
    BulkError,
    CIDRs,
    Filter,
    Member,
    canonical_json,
)
from app.netflow_bulk.storage import durable_directory, file_hash, sync_directory

COLUMNS = pa.schema(
    [
        ("file_id", pa.string()),
        ("row_number", pa.int64()),
        ("source_ref", pa.string()),
        ("valid", pa.bool_()),
        ("invalid_reason", pa.string()),
        ("src_ip", pa.string()),
        ("dst_ip", pa.string()),
        ("src_family", pa.int32()),
        ("dst_family", pa.int32()),
        ("src_sort", pa.string()),
        ("dst_sort", pa.string()),
        ("protocol", pa.int32()),
        ("src_port", pa.int32()),
        ("dst_port", pa.int32()),
        ("start_us", pa.int64()),
        ("end_us", pa.int64()),
        ("canonical_key", pa.string()),
        ("original", pa.string()),
    ]
)
REQUIRED = {"IP_SRC_ADDR", "IP_DST_ADDR", "PROTOCOL", "L4_SRC_PORT", "L4_DST_PORT"}
IDENTITY = ("EXPORTER", "OBSERVATION_POINT", "OBSERVATION_DOMAIN_ID", "SAMPLING_MODE")


def _address(value: str) -> str | None:
    try:
        ip = ipaddress.ip_address(value)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        return str(ip)
    except ValueError:
        return None


def _integer(value: str, maximum: int) -> int | None:
    if not value or not value.isascii() or not value.isdecimal():
        return None
    digits = value.lstrip("0") or "0"
    if len(digits) > len(str(maximum)):
        return None
    number = int(digits)
    return number if number <= maximum else None


def _time(value: str, zone: str) -> int | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            tz = ZoneInfo(zone)
            first, second = (
                parsed.replace(tzinfo=tz, fold=0),
                parsed.replace(tzinfo=tz, fold=1),
            )
            if first.utcoffset() != second.utcoffset():
                return None  # Unknown ambiguous/nonexistent wall time, never invented.
            parsed = first
        delta = parsed.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
        return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    except ValueError, OverflowError:
        return None


def normalize(values: dict[str, str], member: Member, number: int) -> dict[str, Any]:
    ref = f"sha256:{member.sha256}:row:{number:020d}"
    src, dst = _address(values["IP_SRC_ADDR"]), _address(values["IP_DST_ADDR"])
    protocol = _integer(values["PROTOCOL"], 255)
    valid = src is not None and dst is not None and protocol is not None
    start, end = (
        _time(values.get("start_time", ""), member.timezone),
        _time(values.get("end_time", ""), member.timezone),
    )
    if start is not None and end is not None and start > end:
        start = end = None
    ports = [
        _integer(values[key], 65535) if protocol in (6, 17) else None
        for key in ("L4_SRC_PORT", "L4_DST_PORT")
    ]
    # Retain all exporter/NAT/sampling/unknown columns. Only known valid fields
    # are canonicalized; malformed optional values remain part of the full key.
    key: dict[str, Any] = dict(values)
    for name, value in (
        ("IP_SRC_ADDR", src),
        ("IP_DST_ADDR", dst),
        ("PROTOCOL", protocol),
        ("L4_SRC_PORT", ports[0]),
        ("L4_DST_PORT", ports[1]),
        ("start_time", start),
        ("end_time", end),
    ):
        if value is not None:
            key[name] = value
    for name in (
        "IN_BYTES",
        "OUT_BYTES",
        "IN_PKTS",
        "OUT_PKTS",
        "TCP_FLAGS",
        "OBSERVATION_DOMAIN_ID",
    ):
        parsed = _integer(values.get(name, ""), 2**64 - 1)
        if parsed is not None:
            key[name] = parsed
    unknown_ids = {"", "unknown", "null", "none", "n/a", "-", "?"}
    identity_complete = all(values.get(name, "").strip().casefold() not in unknown_ids for name in IDENTITY[:3])
    mode = values.get("SAMPLING_MODE")
    if mode not in ("sampled", "unsampled"):
        identity_complete = False
    elif mode == "sampled":
        try:
            rate = Decimal(values.get("SAMPLING_RATE", ""))
            identity_complete = identity_complete and rate.is_finite() and 0 < rate <= 1
        except InvalidOperation:
            identity_complete = False
    if not identity_complete or start is None or end is None:
        key["__conservative_source_ref"] = ref
    # Nested arrays avoid collisions with a caller-supplied CSV column name.
    canonical_key = canonical_json(
        [
            NORMALIZER,
            key,
            None
            if identity_complete and start is not None and end is not None
            else ref,
        ]
    )
    return {
        "file_id": member.sha256,
        "row_number": number,
        "source_ref": ref,
        "valid": valid,
        "invalid_reason": None if valid else "invalid_ip_or_protocol",
        "src_ip": src,
        "dst_ip": dst,
        "src_family": ipaddress.ip_address(src).version if src else None,
        "dst_family": ipaddress.ip_address(dst).version if dst else None,
        "src_sort": f"{int(ipaddress.ip_address(src)):032x}" if src else None,
        "dst_sort": f"{int(ipaddress.ip_address(dst)):032x}" if dst else None,
        "protocol": protocol,
        "src_port": ports[0],
        "dst_port": ports[1],
        "start_us": start,
        "end_us": end,
        "canonical_key": canonical_key,
        "original": canonical_json(values),
    }


class HashingReader(io.RawIOBase):
    def __init__(self, raw: Any, maximum: int):
        self.raw = raw
        self.maximum = maximum
        self.digest = hashlib.sha256()
        self.bytes = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        size = self.raw.readinto(buffer)
        if size:
            self.digest.update(memoryview(buffer)[:size])
            self.bytes += size
            if self.bytes > self.maximum:
                raise BulkError("bulk_input_changed")
        return int(size or 0)


class BoundedLines:
    """Bound logical CSV bytes before csv.reader can allocate an entire row.

    csv.reader requests additional physical lines only inside a quoted record.
    Reset after each returned logical row, preserving legal embedded newlines.
    """

    def __init__(self, stream: TextIO):
        self.stream = stream
        self.record_bytes = 0

    def __iter__(self) -> BoundedLines:
        return self

    def __next__(self) -> str:
        line = self.stream.readline(MAX_RECORD - self.record_bytes + 1)
        if not line:
            raise StopIteration
        self.record_bytes += len(line.encode("utf-8"))
        if self.record_bytes > MAX_RECORD:
            raise BulkError("bulk_record_limit")
        return line

    def reset(self) -> None:
        self.record_bytes = 0


def normalize_file(
    path: Path,
    member: Member,
    destination: Path,
    budget: Budget,
    *,
    checkpoint: Callable[[dict[str, Any]], None],
    committed: Callable[[int], dict[str, Any] | None],
    pulse: Callable[[], None],
) -> dict[str, int]:
    durable_directory(destination)
    before = path.stat()
    if before.st_size != member.size:
        raise BulkError("bulk_input_changed")
    count = invalid = shard = bytes_in_batch = 0
    batch: list[dict[str, Any]] = []
    prior_field_limit = csv.field_size_limit(MAX_FIELD)

    def flush() -> None:
        nonlocal batch, shard, bytes_in_batch
        if not batch:
            return
        pulse()
        first, last = batch[0]["row_number"], batch[-1]["row_number"]
        old = committed(shard)
        target = destination / f"{shard:08d}.parquet"
        if old is not None:
            if (
                old["first_row"] != first
                or old["last_row"] != last
                or old["sha256"] != file_hash(Path(old["path"]))
            ):
                raise BulkError("bulk_checkpoint_integrity")
            replayed = pa.Table.from_pylist(batch, schema=COLUMNS)
            if not pq.read_table(Path(old["path"])).equals(replayed):
                raise BulkError("bulk_checkpoint_integrity")
        else:
            if (
                shutil.disk_usage(destination).free
                < budget.disk_reserve_bytes + MAX_BATCH_BYTES * 4
            ):
                raise BulkError("bulk_disk_budget")
            temporary = target.with_suffix(".tmp")
            table = pa.Table.from_pylist(batch, schema=COLUMNS)
            pq.write_table(
                table,
                temporary,
                compression="zstd",
                row_group_size=min(8192, budget.shard_rows),
            )
            with temporary.open("rb") as handle:
                os.fsync(handle.fileno())
            if pq.ParquetFile(temporary).metadata.num_rows != len(batch):
                raise BulkError("bulk_shard_validation")
            sha = file_hash(temporary)
            temporary.chmod(0o440)
            with temporary.open("rb") as sealed:
                os.fsync(sealed.fileno())
            os.replace(temporary, target)
            sync_directory(destination)
            checkpoint(
                {
                    "ordinal": shard,
                    "first_row": first,
                    "last_row": last,
                    "rows": len(batch),
                    "invalid": sum(not r["valid"] for r in batch),
                    "sha256": sha,
                    "size": target.stat().st_size,
                    "path": str(target),
                }
            )
        shard += 1
        batch = []
        bytes_in_batch = 0

    try:
        with path.open("rb") as raw:
            hashed = HashingReader(raw, member.size)
            with io.TextIOWrapper(
                io.BufferedReader(hashed),
                encoding=member.encoding,
                errors="strict",
                newline="",
            ) as text:
                lines = BoundedLines(text)
                reader = csv.reader(lines, strict=True)
                header = next(reader, None)
                lines.reset()
                if (
                    not header
                    or len(header) > 256
                    or len(set(header)) != len(header)
                    or not REQUIRED.issubset(header)
                    or any(not h or h.strip() != h or "\0" in h for h in header)
                ):
                    raise BulkError("bulk_invalid_header")
                for row in reader:
                    lines.reset()
                    if len(row) != len(header) or any("\0" in v for v in row):
                        raise BulkError("bulk_invalid_record")
                    size = sum(len(v.encode("utf-8")) for v in row)
                    if size > MAX_RECORD:
                        raise BulkError("bulk_record_limit")
                    count += 1
                    record = normalize(
                        dict(zip(header, row, strict=True)), member, count
                    )
                    invalid += not record["valid"]
                    batch.append(record)
                    # Include expanded header names and escaped JSON, not only
                    # source values: tiny rows can have very large column names.
                    bytes_in_batch += (
                        len(record["canonical_key"]) + len(record["original"]) + 512
                    )
                    if (
                        len(batch) >= budget.shard_rows
                        or bytes_in_batch >= MAX_BATCH_BYTES
                    ):
                        flush()
                flush()
            if (
                hashed.bytes != member.size
                or hashed.digest.hexdigest() != member.sha256
            ):
                raise BulkError("bulk_input_changed")
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise BulkError("bulk_input_changed")
    except (UnicodeError, csv.Error) as error:
        raise BulkError("bulk_invalid_encoding_or_csv") from error
    finally:
        csv.field_size_limit(prior_field_limit)
    return {
        "raw": count,
        "invalid": invalid,
        "shards": shard,
        "read_bytes": member.size,
    }


def connection(
    root: Path,
    budget: Budget,
    *,
    persistent: bool = True,
    allowed: list[Path] | None = None,
) -> Any:
    durable_directory(root)
    temporary = root / "spill"
    temporary.mkdir(exist_ok=True)
    con = duckdb.connect(
        str(root / "compute.duckdb") if persistent else ":memory:",
        config={
            "memory_limit": f"{budget.memory_mb}MB",
            "threads": budget.threads,
            "temp_directory": str(temporary),
            "max_temp_directory_size": f"{budget.temp_bytes}B",
            "preserve_insertion_order": False,
            "autoload_known_extensions": False,
            "autoinstall_known_extensions": False,
        },
    )
    directories = [root.resolve(), *(path.resolve() for path in (allowed or []))]
    con.execute(
        "SET allowed_directories = ["
        + ",".join(sql_literal(str(path)) for path in directories)
        + "]"
    )
    con.execute("SET enable_external_access=false")
    con.execute("SET lock_configuration=true")
    return con


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def compute(
    normalized: Path,
    root: Path,
    selection: Filter,
    budget: Budget,
    *,
    pulse: Callable[[], None],
) -> dict[str, Any]:
    """All distincts operate on the entire dataset; never add local distincts."""
    started = time.monotonic()
    con = connection(root, budget, allowed=[normalized])
    stopped = threading.Event()
    interrupted: list[Exception] = []

    def watch() -> None:
        while not stopped.wait(0.5):
            try:
                pulse()
            except Exception as error:
                interrupted.append(error)
                con.interrupt()
                return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        files = str(normalized / "*" / "*.parquet")
        if not any(normalized.glob("*/*.parquet")):
            empty = root / "empty.parquet"
            pq.write_table(pa.Table.from_pylist([], schema=COLUMNS), empty)
            files = str(empty)
        con.execute(
            "CREATE OR REPLACE VIEW normalized AS SELECT * FROM read_parquet("
            + sql_literal(files)
            + ")"
        )
        raw, invalid = con.execute(
            "SELECT count(*), count(*) FILTER (WHERE NOT valid) FROM normalized"
        ).fetchone()
        if raw and raw == invalid:
            raise BulkError("netflow_no_valid_records")
        predicates = ["valid"]
        source = "normalized"
        projection = "* EXCLUDE(original,invalid_reason,valid)"
        arguments: list[Any] = []
        if selection.protocols:
            predicates.append("protocol IN (SELECT unnest(?))")
            arguments.append(selection.protocols)
        if selection.start is not None:
            predicates.append("start_us >= ?")
            arguments.append(int(selection.start.timestamp() * 1_000_000))
        if selection.end is not None:
            predicates.append("start_us < ?")
            arguments.append(int(selection.end.timestamp() * 1_000_000))
        if selection.cidrs:
            ranges = CIDRs(selection.cidrs)
            con.execute(
                "CREATE OR REPLACE TABLE cidrs(family INTEGER, lo VARCHAR, hi VARCHAR)"
            )
            con.executemany(
                "INSERT INTO cidrs VALUES (?,?,?)",
                [
                    (f, f"{lo:032x}", f"{hi:032x}")
                    for f, values in ranges.ranges.items()
                    for lo, hi in values
                ],
            )
            # Disjoint intervals + ASOF select one nearest lower bound per IP;
            # this is not a per-record scan of every CIDR.
            source = "normalized n ASOF LEFT JOIN cidrs c ON n.src_family=c.family AND n.src_sort>=c.lo"
            projection = "n.* EXCLUDE(original,invalid_reason,valid)"
            predicates.append("n.src_sort <= c.hi")
        pulse()
        con.execute(
            f"CREATE OR REPLACE TABLE retained AS SELECT {projection} FROM {source} WHERE "
            + " AND ".join(predicates),
            arguments,
        )
        retained = con.execute("SELECT count(*) FROM retained").fetchone()[0]
        pulse()
        # Complete canonical strings decide equality; SHA is never a dedup oracle.
        con.execute(
            "CREATE OR REPLACE TABLE unique_rows AS SELECT * EXCLUDE (rank,canonical_key) FROM (SELECT *, row_number() OVER (PARTITION BY canonical_key ORDER BY file_id, row_number) AS rank FROM retained) WHERE rank=1"
        )
        unique = con.execute("SELECT count(*) FROM unique_rows").fetchone()[0]
        pulse()
        con.execute(
            "CREATE OR REPLACE TABLE observations AS SELECT sha256(to_json([src_ip, protocol::VARCHAR, src_port::VARCHAR])) AS object_key, src_ip AS ip, src_family AS family, src_sort AS ip_sort, protocol, src_port AS port, count(*) AS record_count, min(start_us) AS start_us, max(end_us) AS end_us FROM unique_rows GROUP BY src_ip,src_family,src_sort,protocol,src_port"
        )
        pulse()
        con.execute(
            "CREATE OR REPLACE TABLE peers AS SELECT sha256(to_json([dst_ip, protocol::VARCHAR, dst_port::VARCHAR])) AS object_key, dst_ip AS ip, dst_family AS family, dst_sort AS ip_sort, protocol, dst_port AS port, count(*) AS record_count, min(start_us) AS start_us, max(end_us) AS end_us FROM unique_rows GROUP BY dst_ip,dst_family,dst_sort,protocol,dst_port"
        )
        # Rank before collecting bounded refs. High-cardinality peer sets remain rows.
        for side, fields in (
            ("source", ("src_ip", "src_port")),
            ("peer", ("dst_ip", "dst_port")),
        ):
            address, port = fields
            con.execute(
                f"CREATE OR REPLACE TABLE {side}_samples AS SELECT object_key,source_ref,file_id,row_number FROM (SELECT sha256(to_json([{address}, protocol::VARCHAR, {port}::VARCHAR])) AS object_key, source_ref,file_id,row_number,row_number() OVER (PARTITION BY {address},protocol,{port} ORDER BY file_id,row_number) AS rank FROM unique_rows) WHERE rank <= ?",
                [budget.sample_limit],
            )
            pulse()
        con.execute(
            "CREATE OR REPLACE TABLE addresses AS SELECT ip,family,ip_sort,count(*) AS observation_count,sum(record_count)::BIGINT AS record_count FROM observations GROUP BY ip,family,ip_sort"
        )
        counts = {
            "raw": raw,
            "invalid": invalid,
            "filtered": raw - invalid - retained,
            "retained": retained,
            "unique": unique,
            "duplicate": retained - unique,
        }
        assert (
            counts["raw"] == counts["invalid"] + counts["filtered"] + counts["retained"]
        )
        assert counts["retained"] == counts["unique"] + counts["duplicate"]
        result: dict[str, Any] = {
            "engine": ENGINE,
            "policy": POLICY,
            "filter": selection.model_dump(mode="json"),
            "counts": counts,
            "files": {},
            "elapsed_seconds": time.monotonic() - started,
        }
        for table in (
            "observations",
            "peers",
            "addresses",
            "source_samples",
            "peer_samples",
        ):
            count = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            target = root / f"{table}.parquet"
            con.execute(
                f"COPY (SELECT * FROM {table} ORDER BY {'object_key,source_ref' if table.endswith('_samples') else 'family,ip_sort,ip' if table == 'addresses' else 'family,ip_sort,object_key'}) TO {sql_literal(str(target))} (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 8192)"
            )
            with target.open("rb") as handle:
                os.fsync(handle.fileno())
            target.chmod(0o440)
            with target.open("rb") as sealed:
                os.fsync(sealed.fileno())
            result["files"][table] = {
                "path": str(target),
                "sha256": file_hash(target),
                "size": target.stat().st_size,
                "rows": count,
            }
            pulse()
        con.execute("CHECKPOINT")
        sync_directory(root)
        result["elapsed_seconds"] = time.monotonic() - started
        return result
    except duckdb.Error:
        if interrupted:
            raise interrupted[0]
        raise
    finally:
        stopped.set()
        watcher.join(timeout=2)
        con.close()


def batches(path: Path, size: int = 1000) -> Iterator[list[dict[str, Any]]]:
    for batch in pq.ParquetFile(path).iter_batches(batch_size=size):
        yield batch.to_pylist()
