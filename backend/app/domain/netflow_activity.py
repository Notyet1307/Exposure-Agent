from __future__ import annotations

import csv
import hashlib
import ipaddress
import json
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.ip_consistency import IPRecordContractError, normalize_ip
from app.domain.netflow_datasets import CANONICAL_COLUMNS

NETFLOW_ACTIVITY_CONTRACT_VERSION = "netflow-ip-activity-v1"


class NetFlowActivityContractError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class NetFlowIPActivityAggregate:
    canonical_ip: str
    flow_count: int
    peer_ips: tuple[str, ...]
    protocols: tuple[int, ...]
    first_seen_utc: datetime | None
    last_seen_utc: datetime | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonical_ip": self.canonical_ip,
            "flow_count": self.flow_count,
            "peer_ips": list(self.peer_ips),
            "protocols": list(self.protocols),
            "first_seen_utc": _timestamp(self.first_seen_utc),
            "last_seen_utc": _timestamp(self.last_seen_utc),
        }


@dataclass(frozen=True, slots=True)
class NetFlowIPActivityResult:
    contract_version: str
    activities: tuple[NetFlowIPActivityAggregate, ...]
    output_hash: str


@dataclass(slots=True)
class _Accumulator:
    flow_count: int = 0
    peer_ips: set[str] = field(default_factory=set)
    protocols: set[int] = field(default_factory=set)
    first_seen_utc: datetime | None = None
    last_seen_utc: datetime | None = None


def _timestamp(value: datetime | None) -> str | None:
    return (
        None if value is None else value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _ip_sort_key(value: str) -> tuple[int, int]:
    address = ipaddress.ip_address(value)
    return address.version, int(address)


def _canonical_ip(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise NetFlowActivityContractError("netflow_activity_ip_invalid")
    try:
        canonical = normalize_ip(value)
    except IPRecordContractError:
        raise NetFlowActivityContractError("netflow_activity_ip_invalid") from None
    if canonical != value:
        raise NetFlowActivityContractError("netflow_activity_ip_invalid")
    return canonical


def _protocol(value: object) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise NetFlowActivityContractError("netflow_activity_protocol_invalid")
    parsed = int(value)
    if str(parsed) != value or parsed > 255:
        raise NetFlowActivityContractError("netflow_activity_protocol_invalid")
    return parsed


def _time(value: object) -> datetime | None:
    if value == "":
        return None
    if not isinstance(value, str):
        raise NetFlowActivityContractError("netflow_activity_time_invalid")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise NetFlowActivityContractError("netflow_activity_time_invalid") from None
    if _timestamp(parsed) != value:
        raise NetFlowActivityContractError("netflow_activity_time_invalid")
    return parsed


def _output_hash(activities: tuple[NetFlowIPActivityAggregate, ...]) -> str:
    payload = {
        "contract_version": NETFLOW_ACTIVITY_CONTRACT_VERSION,
        "activities": [activity.as_dict() for activity in activities],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def aggregate_netflow_ip_activity(
    path: Path, managed_ips: Collection[str]
) -> NetFlowIPActivityResult:
    """Count accepted records touching each managed IP, not sessions or events.

    Both managed endpoints get positive evidence; a self-flow counts once.
    Duplicate records remain samples. No service-port or direction is inferred.
    """
    managed = frozenset(normalize_ip(value) for value in managed_ips)
    aggregates: dict[str, _Accumulator] = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as source:
            reader = csv.DictReader(
                source,
                delimiter=",",
                quotechar='"',
                doublequote=True,
                escapechar=None,
                skipinitialspace=False,
                strict=True,
            )
            if tuple(reader.fieldnames or ()) != CANONICAL_COLUMNS:
                raise NetFlowActivityContractError("netflow_activity_schema_invalid")
            for row in reader:
                if set(row) != set(CANONICAL_COLUMNS) or any(
                    value is None for value in row.values()
                ):
                    raise NetFlowActivityContractError(
                        "netflow_activity_record_invalid"
                    )
                source_ip = _canonical_ip(row["src_ip"])
                destination_ip = _canonical_ip(row["dst_ip"])
                protocol = _protocol(row["protocol"])
                first_seen = _time(row["start_time_utc"])
                last_seen = _time(row["end_time_utc"])
                for endpoint in {source_ip, destination_ip} & managed:
                    peer = destination_ip if endpoint == source_ip else source_ip
                    current = aggregates.get(endpoint)
                    if current is None:
                        current = aggregates[endpoint] = _Accumulator()
                    current.flow_count += 1
                    if peer != endpoint:
                        current.peer_ips.add(peer)
                    current.protocols.add(protocol)
                    if first_seen is not None and (
                        current.first_seen_utc is None
                        or first_seen < current.first_seen_utc
                    ):
                        current.first_seen_utc = first_seen
                    if last_seen is not None and (
                        current.last_seen_utc is None
                        or last_seen > current.last_seen_utc
                    ):
                        current.last_seen_utc = last_seen
    except (UnicodeDecodeError, csv.Error) as error:
        raise NetFlowActivityContractError("netflow_activity_record_invalid") from error

    activities = tuple(
        NetFlowIPActivityAggregate(
            canonical_ip=canonical_ip,
            flow_count=current.flow_count,
            peer_ips=tuple(sorted(current.peer_ips, key=_ip_sort_key)),
            protocols=tuple(sorted(current.protocols)),
            first_seen_utc=current.first_seen_utc,
            last_seen_utc=current.last_seen_utc,
        )
        for canonical_ip, current in sorted(
            aggregates.items(), key=lambda item: _ip_sort_key(item[0])
        )
    )
    return NetFlowIPActivityResult(
        contract_version=NETFLOW_ACTIVITY_CONTRACT_VERSION,
        activities=activities,
        output_hash=_output_hash(activities),
    )
