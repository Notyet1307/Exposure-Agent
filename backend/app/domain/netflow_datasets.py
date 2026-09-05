from __future__ import annotations

import csv
import hashlib
import ipaddress
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import TextIO

NETFLOW_DATASET_CONTRACT_VERSION = "netflow-dataset-v1"
CANONICAL_COLUMNS = (
    "source_record_key",
    "src_ip",
    "dst_ip",
    "protocol",
    "src_port",
    "dst_port",
    "start_time_utc",
    "end_time_utc",
    "in_bytes_estimated",
    "in_packets_estimated",
    "tcp_flags",
)
CANONICAL_HEADER = ",".join(CANONICAL_COLUMNS) + "\n"
SCHEMA_FINGERPRINT = hashlib.sha256(CANONICAL_HEADER.encode()).hexdigest()
REQUIRED_HEADERS = (
    "IP_SRC_ADDR",
    "IP_DST_ADDR",
    "PROTOCOL",
    "L4_SRC_PORT",
    "L4_DST_PORT",
)
OPTIONAL_HEADERS = ("start_time", "end_time", "IN_BYTES", "IN_PKTS", "TCP_FLAGS")
RECOGNIZED_HEADERS = frozenset(REQUIRED_HEADERS + OPTIONAL_HEADERS)
INTEGER_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\Z", re.ASCII)
UTC_PLUS_8 = timezone(timedelta(hours=8))


class NetFlowAcceptanceError(Exception):
    def __init__(
        self, code: str, *, field: str | None = None, row: int | None = None
    ) -> None:
        super().__init__(code)
        self.code = code
        self.field = field
        self.row = row


@dataclass(frozen=True)
class ParsedNetFlow:
    raw_sha256: str
    raw_byte_size: int
    encoding: str
    contract_version: str
    schema_fingerprint: str
    raw_record_count: int
    activity_valid_record_count: int
    isolated_record_count: int
    warnings: tuple[dict[str, object], ...]
    normalized_path: Path
    normalized_byte_size: int
    normalized_sha256: str
    valid_time_start_utc: str | None
    valid_time_end_utc: str | None
    duplicate_group_count: int
    duplicate_record_count: int


def _canonical_ip(value: str) -> str | None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    return address.compressed


def _uint(value: str, maximum: int) -> int | None:
    if not INTEGER_PATTERN.fullmatch(value):
        return None
    parsed = int(value)
    return parsed if parsed <= maximum else None


def _time(value: str) -> str | None:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if parsed.strftime("%Y-%m-%d %H:%M:%S") != value:
        return None
    return (
        parsed.replace(tzinfo=UTC_PLUS_8).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )



def _value(record: list[str], indexes: dict[str, int], name: str) -> str:
    position = indexes.get(name)
    return record[position] if position is not None else ""


def _detect_encoding(path: Path) -> str:
    import codecs

    for encoding in ("utf-8-sig", "gb18030"):
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
        try:
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    decoder.decode(chunk)
                decoder.decode(b"", final=True)
            return encoding
        except UnicodeDecodeError:
            continue
        except OSError as error:
            raise NetFlowAcceptanceError("netflow_processing_failed") from error
    raise NetFlowAcceptanceError("netflow_invalid_encoding")


def _warning(
    code: str, field: str | None, count: int, rows: list[str]
) -> dict[str, object]:
    return {
        "code": code,
        "field": field,
        "count": count,
        "source_record_keys": rows[:20],
    }


def _remove_temp(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def parse_netflow_dataset(path: Path) -> ParsedNetFlow:
    try:
        if path.stat().st_size == 0:
            raise NetFlowAcceptanceError("netflow_missing_header")
    except OSError as error:
        raise NetFlowAcceptanceError("netflow_processing_failed") from error
    normalized_path = path.with_name(
        f".{path.name}.{uuid.uuid4().hex}.normalized.tmp"
    )
    db_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.scan.sqlite")
    source: TextIO | None = None
    conn: sqlite3.Connection | None = None
    scan_succeeded = False
    try:
        encoding = _detect_encoding(path)
        source = path.open("r", encoding=encoding, newline="")
        reader = csv.reader(
            source,
            delimiter=",",
            quotechar='"',
            doublequote=True,
            escapechar=None,
            skipinitialspace=False,
            strict=True,
            quoting=csv.QUOTE_MINIMAL,
        )
        try:
            header = next(reader)
        except StopIteration:
            raise NetFlowAcceptanceError("netflow_missing_header") from None
        except csv.Error as error:
            raise NetFlowAcceptanceError("netflow_invalid_csv") from error
        if not header or all(value == "" for value in header):
            raise NetFlowAcceptanceError("netflow_missing_header")
        if (
            any(value == "" or value != value.strip() for value in header)
            or len(header) != len(set(header))
            or any(required not in header for required in REQUIRED_HEADERS)
        ):
            raise NetFlowAcceptanceError("netflow_invalid_header")
        if any("\0" in value for value in header):
            raise NetFlowAcceptanceError("netflow_nul_forbidden")
        ignored_headers = len(
            set(header) - set(REQUIRED_HEADERS) - set(OPTIONAL_HEADERS)
        )
        indexes = {name: index for index, name in enumerate(header)}
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE duplicates (canonical TEXT NOT NULL, source_key TEXT NOT NULL)"
        )
        warning_rows: dict[tuple[str, str | None], tuple[int, list[str]]] = {}
        raw_count = isolated = valid_count = 0
        valid_start: str | None = None
        valid_end: str | None = None
        duplicate_rows: list[str] = []

        def add_warning(code: str, field: str | None, key: str | None = None) -> None:
            count, samples = warning_rows.get((code, field), (0, []))
            count += 1
            if key is not None and len(samples) < 20:
                samples.append(key)
            warning_rows[(code, field)] = (count, samples)

        with normalized_path.open("w", encoding="utf-8", newline="") as destination:
            writer = csv.writer(
                destination,
                delimiter=",",
                quotechar='"',
                doublequote=True,
                escapechar=None,
                lineterminator="\n",
                quoting=csv.QUOTE_MINIMAL,
            )
            writer.writerow(CANONICAL_COLUMNS)
            for record in reader:
                raw_count += 1
                key = f"row:{raw_count}"
                if len(record) != len(header):
                    raise NetFlowAcceptanceError("netflow_invalid_record_width")
                if any("\0" in value for value in record):
                    raise NetFlowAcceptanceError("netflow_nul_forbidden")

                # Values absent from optional columns are intentionally empty.

                src = _canonical_ip(_value(record, indexes, "IP_SRC_ADDR"))
                dst = _canonical_ip(_value(record, indexes, "IP_DST_ADDR"))
                protocol = _uint(_value(record, indexes, "PROTOCOL"), 255)
                if src is None:
                    add_warning("netflow_invalid_ip", "IP_SRC_ADDR", key)
                if dst is None:
                    add_warning("netflow_invalid_ip", "IP_DST_ADDR", key)
                if protocol is None:
                    add_warning("netflow_invalid_protocol", "PROTOCOL", key)
                if src is None or dst is None or protocol is None:
                    isolated += 1
                    continue
                src_port = dst_port = None
                if protocol in (6, 17):
                    for field in ("L4_SRC_PORT", "L4_DST_PORT"):
                        parsed = _uint(_value(record, indexes, field), 65535)
                        if parsed is None or parsed == 0:
                            add_warning("netflow_invalid_port", field, key)
                        elif field == "L4_SRC_PORT":
                            src_port = str(parsed)
                        else:
                            dst_port = str(parsed)
                elif protocol not in (1, 6, 17, 58):
                    add_warning("netflow_unknown_protocol", "PROTOCOL", key)
                start = _time(_value(record, indexes, "start_time"))
                end = _time(_value(record, indexes, "end_time"))
                if start is None:
                    add_warning("netflow_invalid_time", "start_time", key)
                if end is None:
                    add_warning("netflow_invalid_time", "end_time", key)
                if start is not None and end is not None and end < start:
                    start = end = None
                    add_warning("netflow_invalid_time_range", None, key)
                if start is not None and (valid_start is None or start < valid_start):
                    valid_start = start
                if end is not None and (valid_end is None or end > valid_end):
                    valid_end = end
                counters: list[str | None] = []
                for field in ("IN_BYTES", "IN_PKTS"):
                    parsed = _uint(_value(record, indexes, field), 2**64 - 1)
                    if parsed is None:
                        add_warning("netflow_invalid_count", field, key)
                        counters.append(None)
                    else:
                        counters.append(str(parsed))
                parsed_flags = _uint(_value(record, indexes, "TCP_FLAGS"), 255)
                if parsed_flags is None:
                    add_warning("netflow_invalid_tcp_flags", "TCP_FLAGS", key)
                    flags = None
                else:
                    flags = str(parsed_flags)
                row = [
                    key,
                    src,
                    dst,
                    str(protocol),
                    src_port,
                    dst_port,
                    start,
                    end,
                    counters[0],
                    counters[1],
                    flags,
                ]
                writer.writerow(row)
                canonical = "\x1f".join(value or "" for value in row[1:])
                conn.execute(
                    "INSERT INTO duplicates(canonical, source_key) VALUES (?, ?)",
                    (canonical, key),
                )
                valid_count += 1
            destination.flush()
        conn.commit()
        duplicate_groups, duplicate_count = conn.execute(
            "SELECT count(*) FILTER (WHERE n > 1), coalesce(sum(n - 1) FILTER (WHERE n > 1), 0) FROM (SELECT count(*) AS n FROM duplicates GROUP BY canonical)"
        ).fetchone()
        duplicate_rows = [
            row[0]
            for row in conn.execute(
                "SELECT source_key FROM (SELECT source_key, row_number() OVER (PARTITION BY canonical ORDER BY CAST(substr(source_key, 5) AS INTEGER)) AS n FROM duplicates) WHERE n > 1 ORDER BY CAST(substr(source_key, 5) AS INTEGER) LIMIT 20"
            )
        ]
        if duplicate_count:
            warning_rows[("netflow_duplicate_records", None)] = (
                int(duplicate_count),
                duplicate_rows,
            )
        if ignored_headers:
            warning_rows[("netflow_ignored_input_columns", None)] = (
                ignored_headers,
                [],
            )
        warnings = tuple(
            _warning(code, field, count, samples)
            for (code, field), (count, samples) in sorted(
                warning_rows.items(),
                key=lambda item: (item[0][0], item[0][1] is not None, item[0][1] or ""),
            )
        )
        digest = hashlib.sha256()
        size = 0
        with normalized_path.open("rb") as normalized:
            while chunk := normalized.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        with path.open("rb") as raw:
            raw_digest = hashlib.sha256()
            raw_size = 0
            while chunk := raw.read(1024 * 1024):
                raw_digest.update(chunk)
                raw_size += len(chunk)
        scan_succeeded = True
        return ParsedNetFlow(
            raw_digest.hexdigest(),
            raw_size,
            encoding,
            NETFLOW_DATASET_CONTRACT_VERSION,
            SCHEMA_FINGERPRINT,
            raw_count,
            valid_count,
            isolated,
            warnings,
            normalized_path,
            size,
            digest.hexdigest(),
            valid_start,
            valid_end,
            int(duplicate_groups),
            int(duplicate_count),
        )
    except NetFlowAcceptanceError:
        _remove_temp(normalized_path)
        raise
    except (OSError, csv.Error, sqlite3.Error) as error:
        _remove_temp(normalized_path)
        if isinstance(error, csv.Error):
            raise NetFlowAcceptanceError("netflow_invalid_csv") from error
        raise NetFlowAcceptanceError("netflow_processing_failed") from error
    finally:
        cleanup_failed = False
        if source is not None:
            try:
                source.close()
            except OSError:
                cleanup_failed = True
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                cleanup_failed = True
        if not _remove_temp(db_path):
            cleanup_failed = True
        if scan_succeeded and cleanup_failed:
            _remove_temp(normalized_path)
            raise NetFlowAcceptanceError("netflow_processing_failed")
