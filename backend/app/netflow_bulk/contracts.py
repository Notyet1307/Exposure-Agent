"""Bounded request and storage contracts. No runtime or deployment settings here."""

import hashlib
import ipaddress
import json
from bisect import bisect_right
from datetime import datetime
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VERSION: Final = "netflow-bulk-v1"
POLICY = "bulk-export-row-v1"
ENGINE = "bulk-engine-1"
NORMALIZER = "bulk-normalizer-1"
SCHEMA = hashlib.sha256(f"{VERSION}:{NORMALIZER}".encode()).hexdigest()
MAX_MANIFEST = 2 * 1024 * 1024
MAX_FILES = 4096
MAX_FIELD = 65536
MAX_RECORD = 262144
MAX_BATCH_BYTES = 16 * 1024 * 1024


class BulkError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Member(Strict):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=128)
    encoding: Literal["utf-8-sig", "gb18030"] = "utf-8-sig"
    timezone: str = "UTC"
    schema_version: Literal["export-csv-v1"] = "export-csv-v1"

    @field_validator("name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        if (
            value in (".", "..")
            or "/" in value
            or "\\" in value
            or "\0" in value
            or not value.lower().endswith((".csv", ".txt"))
        ):
            raise ValueError("bulk_invalid_filename")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value


class Ready(Strict):
    version: Literal["netflow-bulk-v1"] = VERSION
    tenant_id: str
    project_id: str
    source_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    files: list[Member] = Field(min_length=1, max_length=MAX_FILES)

    @model_validator(mode="after")
    def unique_members(self) -> Ready:
        if len({m.sha256 for m in self.files}) != len(self.files):
            raise ValueError("bulk_duplicate_file")
        self.files.sort(key=lambda m: m.sha256)
        return self


class Filter(Strict):
    cidrs: list[str] = Field(default_factory=list, max_length=4096)
    protocols: list[int] = Field(default_factory=list, max_length=256)
    start: datetime | None = None
    end: datetime | None = None

    @model_validator(mode="after")
    def valid(self) -> Filter:
        self.cidrs = sorted(
            {str(ipaddress.ip_network(c, strict=True)) for c in self.cidrs}
        )
        if any(p < 0 or p > 255 for p in self.protocols):
            raise ValueError("bulk_invalid_protocol")
        self.protocols = sorted(set(self.protocols))
        if any(t is not None and t.utcoffset() is None for t in (self.start, self.end)):
            raise ValueError("bulk_timezone_required")
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("bulk_invalid_window")
        return self


class Budget(Strict):
    memory_mb: int = Field(default=512, ge=64, le=65536)
    threads: int = Field(default=2, ge=1, le=32)
    temp_bytes: int = Field(default=8 * 1024**3, ge=1024**2)
    disk_reserve_bytes: int = Field(default=2 * 1024**3, ge=0)
    rss_bytes: int = Field(default=2 * 1024**3, ge=128 * 1024**2)
    timeout_seconds: int = Field(default=86400, ge=1)
    shard_rows: int = Field(default=65536, ge=1, le=131072)
    sample_limit: int = Field(default=20, ge=1, le=20)


class CIDRs:
    """Disjoint intervals: O(log N) per address, including IPv6."""

    def __init__(self, cidrs: list[str]):
        self.ranges: dict[int, list[tuple[int, int]]] = {4: [], 6: []}
        for value in cidrs:
            network = ipaddress.ip_network(value)
            self.ranges[network.version].append(
                (int(network.network_address), int(network.broadcast_address))
            )
        for family, ranges in self.ranges.items():
            merged: list[tuple[int, int]] = []
            for start, end in sorted(ranges):
                if merged and start <= merged[-1][1] + 1:
                    merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
                else:
                    merged.append((start, end))
            self.ranges[family] = merged
        self.starts = {f: [lo for lo, _ in r] for f, r in self.ranges.items()}

    def contains(self, address: str) -> bool:
        ip = ipaddress.ip_address(address)
        index = bisect_right(self.starts[ip.version], int(ip)) - 1
        return index >= 0 and int(ip) <= self.ranges[ip.version][index][1]
