#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import io
import ipaddress
import json
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ORACLE_PATH = Path(__file__).with_name("oracle-v1.json")
ORACLE_SCHEMA = "exposure-agent:synthetic-netflow-fixture-oracle:v1"
FIXTURE_VERSION = "synthetic-netflow-v1"
PROVENANCE = "fully_synthetic_from_zero"
EXPECTED_CASE_IDS = (
    "accepted_mixed",
    "bad_header",
    "nul_byte",
    "unterminated_quote",
    "utf8_bom_header_only",
    "utf8_bom_only",
    "wrong_record_width",
    "zero_bytes",
)
TOP_LEVEL_KEYS = frozenset(
    {
        "schema",
        "fixture_version",
        "provenance",
        "allowed_invalid_hosts",
        "allowed_networks",
        "schema_fingerprint",
        "source_limitations",
        "negative_guards",
        "cases",
    }
)
CASE_KEYS = frozenset({"id", "input_utf8", "input_sha256", "expected"})
EXPECTED_OUTCOMES = {
    case_id: (
        "ACCEPT"
        if case_id in {"accepted_mixed", "utf8_bom_header_only"}
        else "BATCH_REJECT"
    )
    for case_id in EXPECTED_CASE_IDS
}
EXPECTED_REJECTION_CODES = {
    "bad_header": "netflow_invalid_header",
    "nul_byte": "netflow_nul_forbidden",
    "unterminated_quote": "netflow_invalid_csv",
    "utf8_bom_only": "netflow_missing_header",
    "wrong_record_width": "netflow_invalid_record_width",
    "zero_bytes": "netflow_missing_header",
}
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
SYNTHETIC_IGNORED_HEADER = "FLOW_SAMPLER_ID"
ALLOWED_INPUT_HEADERS = frozenset(
    REQUIRED_HEADERS + OPTIONAL_HEADERS + (SYNTHETIC_IGNORED_HEADER,)
)
KNOWN_PROTOCOLS = frozenset({1, 6, 17, 58})
INTEGER_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\Z", re.ASCII)
UTC_PLUS_8 = timezone(timedelta(hours=8))
DOCUMENTATION_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "192.0.2.0/24",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "2001:db8::/32",
    )
)
DOCUMENTATION_NETWORK_TEXT = [str(value) for value in DOCUMENTATION_NETWORKS]
ALLOWED_INVALID_HOSTS = ("bad.example.invalid",)
SOURCE_LIMITATIONS = {
    "coverage": {"status": "UNKNOWN", "value": None},
    "sampling_rate": {"status": "UNKNOWN", "rate": None},
    "nat": {"status": "UNKNOWN", "value": None},
    "observation_point": {"status": "UNKNOWN", "value": None},
}
NEGATIVE_GUARDS = [
    "reciprocal_ephemeral_port_53000_is_not_a_service",
    "icmp_0_and_2048_have_no_port_semantics",
    "unknown_nat_and_observation_point_forbid_direction_or_address_merge",
    "unknown_coverage_and_sampling_forbid_not_observed_zero_events_zero_risk_or_no_traffic",
]
FORBIDDEN_CONCLUSION_KEYS = frozenset(
    {
        "direction",
        "event_count",
        "findings",
        "nat_merge",
        "no_traffic",
        "not_observed",
        "risk",
        "services",
    }
)
FORBIDDEN_CONCLUSION_VALUES = frozenset(
    {"NOT_OBSERVED", "ZERO_EVENTS", "ZERO_RISK", "NO_TRAFFIC"}
)
TRUE_OBJECTS = {
    "dataset": True,
    "raw_artifact": True,
    "normalized_artifact": True,
    "accepted_audit_event": True,
}
FALSE_OBJECTS = {key: False for key in TRUE_OBJECTS}
SENSITIVE_KEY_NAMES = frozenset(
    {
        "credential",
        "credentials",
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "token",
        "tokens",
        "access_key",
        "private_key",
        "client_secret",
        "authorization",
    }
)
SENSITIVE_COMPACT_KEY_NAMES = frozenset(
    value.replace("_", "") for value in SENSITIVE_KEY_NAMES
)
CREDENTIAL_VALUE_PATTERNS = (
    re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"),
    re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9+/=_-]{8,}", re.IGNORECASE),
    re.compile(r"(?:https?|ssh|ftp)://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE),
)
IPV4_CANDIDATE = re.compile(
    r"(?<![0-9.])((?:[0-9]{1,3}\.){3}[0-9]{1,3})(/[0-9]{1,2}|:[0-9]{1,5})?(?![0-9.])"
)
BRACKETED_IPV6_CANDIDATE = re.compile(
    r"\[([0-9A-Fa-f:.]+)\](/[0-9]{1,3})?(?::[0-9]{1,5})?"
)
IPV6_CANDIDATE = re.compile(
    r"(?<![0-9A-Za-z:.])((?:[0-9A-Fa-f]{0,4}:){2,}[0-9A-Fa-f:.]*)(/[0-9]{1,3})?(?![0-9A-Za-z:.])"
)
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
EMAIL_PATTERN = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
HOSTNAME_PATTERN = re.compile(
    r"(?<![A-Za-z0-9-])(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,63}(?![A-Za-z0-9-])"
)


class FixtureError(Exception):
    pass


def fail(code: str) -> None:
    raise FixtureError(code)


def reject(code: str) -> dict[str, Any]:
    return {
        "outcome": "BATCH_REJECT",
        "candidate_error_code": code,
        "objects": FALSE_OBJECTS,
    }


def parse_uint(value: str, maximum: int) -> int | None:
    if not INTEGER_PATTERN.fullmatch(value):
        return None
    parsed = int(value)
    return parsed if parsed <= maximum else None


def canonical_ip(value: str) -> str | None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    return address.compressed


def utc_time(value: str) -> str | None:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if parsed.strftime("%Y-%m-%d %H:%M:%S") != value:
        return None
    return parsed.replace(tzinfo=UTC_PLUS_8).astimezone(UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

def is_documentation_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any(address in network for network in DOCUMENTATION_NETWORKS)


def ip_sort_key(value: str) -> tuple[int, int]:
    address = ipaddress.ip_address(value)
    return address.version, int(address)


def source_key_sort(value: str) -> int:
    return int(value.removeprefix("row:"))


def write_normalized(rows: list[dict[str, str | None]]) -> bytes:
    destination = io.StringIO(newline="")
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
    for row in rows:
        values = [row[column] for column in CANONICAL_COLUMNS]
        if any(
            isinstance(value, str) and any(character in value for character in "\r\n\0")
            for value in values
        ):
            fail("normalized_control_character")
        writer.writerow(values)
    return destination.getvalue().encode("utf-8")


def warning_list(
    warning_keys: dict[tuple[str, str | None], list[str]],
    *,
    ignored_column_count: int,
    duplicate_source_keys: list[str],
) -> list[dict[str, Any]]:
    if ignored_column_count:
        warning_keys[("netflow_ignored_input_columns", None)] = []
    if duplicate_source_keys:
        warning_keys[("netflow_duplicate_records", None)] = duplicate_source_keys

    warnings = []
    for code, field in sorted(
        warning_keys, key=lambda item: (item[0], item[1] is not None, item[1] or "")
    ):
        samples = warning_keys[(code, field)]
        count = (
            ignored_column_count
            if code == "netflow_ignored_input_columns"
            else len(samples)
        )
        warnings.append(
            {
                "code": code,
                "field": field,
                "count": count,
                "source_record_keys": samples[:20],
            }
        )
    return warnings


def aggregate(rows: list[dict[str, str | None]]) -> list[dict[str, Any]]:
    aggregates: dict[str, dict[str, Any]] = {}
    for row in rows:
        src_ip = row["src_ip"]
        dst_ip = row["dst_ip"]
        protocol = row["protocol"]
        assert src_ip is not None and dst_ip is not None and protocol is not None
        for endpoint in sorted({src_ip, dst_ip}, key=ip_sort_key):
            peer = dst_ip if endpoint == src_ip else src_ip
            current = aggregates.setdefault(
                endpoint,
                {
                    "canonical_ip": endpoint,
                    "flow_count": 0,
                    "peer_ips": set(),
                    "protocols": set(),
                    "first_seen_utc": None,
                    "last_seen_utc": None,
                },
            )
            current["flow_count"] += 1
            if peer != endpoint:
                current["peer_ips"].add(peer)
            current["protocols"].add(int(protocol))
            start = row["start_time_utc"]
            end = row["end_time_utc"]
            if start is not None and (
                current["first_seen_utc"] is None or start < current["first_seen_utc"]
            ):
                current["first_seen_utc"] = start
            if end is not None and (
                current["last_seen_utc"] is None or end > current["last_seen_utc"]
            ):
                current["last_seen_utc"] = end

    result = []
    for endpoint in sorted(aggregates, key=ip_sort_key):
        current = aggregates[endpoint]
        result.append(
            {
                **current,
                "peer_ips": sorted(current["peer_ips"], key=ip_sort_key),
                "protocols": sorted(current["protocols"]),
            }
        )
    return result


def evaluate(raw: bytes) -> dict[str, Any]:
    if not raw:
        return reject("netflow_missing_header")
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gb18030", errors="strict")
        except UnicodeDecodeError:
            return reject("netflow_invalid_encoding")
    if "\0" in text:
        return reject("netflow_nul_forbidden")

    try:
        reader = csv.reader(
            io.StringIO(text, newline=""),
            delimiter=",",
            quotechar='"',
            doublequote=True,
            escapechar=None,
            skipinitialspace=False,
            strict=True,
            quoting=csv.QUOTE_MINIMAL,
        )
        records = list(reader)
    except csv.Error:
        return reject("netflow_invalid_csv")
    if not records or not records[0] or all(value == "" for value in records[0]):
        return reject("netflow_missing_header")

    header = records[0]
    if (
        any(value == "" or value != value.strip() for value in header)
        or len(header) != len(set(header))
        or any(required not in header for required in REQUIRED_HEADERS)
    ):
        return reject("netflow_invalid_header")
    if not set(header) <= ALLOWED_INPUT_HEADERS:
        fail("privacy_input_header_invalid")
    if any(len(record) != len(header) for record in records[1:]):
        return reject("netflow_invalid_record_width")

    index = {name: position for position, name in enumerate(header)}
    ignored_column_count = len(
        set(header) - set(REQUIRED_HEADERS) - set(OPTIONAL_HEADERS)
    )
    sampler_position = index.get(SYNTHETIC_IGNORED_HEADER)
    if sampler_position is not None:
        for record in records[1:]:
            sampler = record[sampler_position]
            if sampler and not is_documentation_address(sampler):
                fail("privacy_ignored_value_invalid")
    warning_keys: dict[tuple[str, str | None], list[str]] = defaultdict(list)
    normalized_rows: list[dict[str, str | None]] = []

    def value(record: list[str], field: str) -> str:
        position = index.get(field)
        return record[position] if position is not None else ""

    for record_number, record in enumerate(records[1:], start=1):
        source_record_key = f"row:{record_number}"
        src_ip = canonical_ip(value(record, "IP_SRC_ADDR"))
        dst_ip = canonical_ip(value(record, "IP_DST_ADDR"))
        if src_ip is None:
            warning_keys[("netflow_invalid_ip", "IP_SRC_ADDR")].append(
                source_record_key
            )
        if dst_ip is None:
            warning_keys[("netflow_invalid_ip", "IP_DST_ADDR")].append(
                source_record_key
            )
        protocol = parse_uint(value(record, "PROTOCOL"), 255)
        if protocol is None:
            warning_keys[("netflow_invalid_protocol", "PROTOCOL")].append(
                source_record_key
            )
        if src_ip is None or dst_ip is None or protocol is None:
            continue

        src_port: str | None = None
        dst_port: str | None = None
        if protocol in {6, 17}:
            for field in ("L4_SRC_PORT", "L4_DST_PORT"):
                parsed_port = parse_uint(value(record, field), 65_535)
                if parsed_port is None or parsed_port == 0:
                    warning_keys[("netflow_invalid_port", field)].append(
                        source_record_key
                    )
                elif field == "L4_SRC_PORT":
                    src_port = str(parsed_port)
                else:
                    dst_port = str(parsed_port)
        elif protocol not in KNOWN_PROTOCOLS:
            warning_keys[("netflow_unknown_protocol", "PROTOCOL")].append(
                source_record_key
            )

        raw_start = value(record, "start_time")
        raw_end = value(record, "end_time")
        start = utc_time(raw_start) if raw_start else None
        end = utc_time(raw_end) if raw_end else None
        if start is None:
            warning_keys[("netflow_invalid_time", "start_time")].append(
                source_record_key
            )
        if end is None:
            warning_keys[("netflow_invalid_time", "end_time")].append(
                source_record_key
            )
        if start is not None and end is not None and end < start:
            start = None
            end = None
            warning_keys[("netflow_invalid_time_range", None)].append(
                source_record_key
            )

        counters: dict[str, str | None] = {}
        for source_field, normalized_field in (
            ("IN_BYTES", "in_bytes_estimated"),
            ("IN_PKTS", "in_packets_estimated"),
        ):
            parsed_count = parse_uint(value(record, source_field), 2**64 - 1)
            if parsed_count is None:
                warning_keys[("netflow_invalid_count", source_field)].append(
                    source_record_key
                )
                counters[normalized_field] = None
            else:
                counters[normalized_field] = str(parsed_count)

        parsed_flags = parse_uint(value(record, "TCP_FLAGS"), 255)
        if parsed_flags is None:
            warning_keys[("netflow_invalid_tcp_flags", "TCP_FLAGS")].append(
                source_record_key
            )
            flags = None
        else:
            flags = str(parsed_flags)

        normalized_rows.append(
            {
                "source_record_key": source_record_key,
                "src_ip": src_ip,
                "dst_ip": dst_ip,
                "protocol": str(protocol),
                "src_port": src_port,
                "dst_port": dst_port,
                "start_time_utc": start,
                "end_time_utc": end,
                **counters,
                "tcp_flags": flags,
            }
        )

    duplicate_groups: dict[tuple[str | None, ...], list[str]] = defaultdict(list)
    for row in normalized_rows:
        duplicate_groups[
            tuple(row[column] for column in CANONICAL_COLUMNS[1:])
        ].append(str(row["source_record_key"]))
    duplicate_source_keys = sorted(
        (
            source_key
            for group in duplicate_groups.values()
            for source_key in group[1:]
        ),
        key=source_key_sort,
    )
    duplicate_group_count = sum(
        len(source_keys) > 1 for source_keys in duplicate_groups.values()
    )

    normalized = write_normalized(normalized_rows)
    activity_valid_count = len(normalized_rows)
    return {
        "outcome": "ACCEPT",
        "candidate_error_code": None,
        "objects": TRUE_OBJECTS,
        "presence": "PRESENT",
        "selectable": activity_valid_count > 0,
        "raw_record_count": len(records) - 1,
        "activity_valid_record_count": activity_valid_count,
        "isolated_record_count": len(records) - 1 - activity_valid_count,
        "normalized_utf8": normalized.decode("utf-8"),
        "normalized_sha256": hashlib.sha256(normalized).hexdigest(),
        "schema_fingerprint": SCHEMA_FINGERPRINT,
        "warnings": warning_list(
            warning_keys,
            ignored_column_count=ignored_column_count,
            duplicate_source_keys=duplicate_source_keys,
        ),
        "duplicate_group_count": duplicate_group_count,
        "duplicate_record_count": len(duplicate_source_keys),
        "aggregates": aggregate(normalized_rows),
        "unknowns": SOURCE_LIMITATIONS,
        "defensive_run": (
            None
            if activity_valid_count
            else {
                "production_invoked": False,
                "netflow_snapshot_record_count": 0,
                "run_status": "FAILED_DATA",
            }
        ),
    }


def normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def check_credential_key(value: str) -> None:
    normalized = normalized_key(value)
    compact = normalized.replace("_", "")
    if normalized in SENSITIVE_KEY_NAMES or compact in SENSITIVE_COMPACT_KEY_NAMES:
        fail("privacy_credential_key")


def check_address_or_network(value: str) -> None:
    try:
        if "/" in value:
            network = ipaddress.ip_network(value, strict=False)
            allowed = any(
                network.version == candidate.version and network.subnet_of(candidate)
                for candidate in DOCUMENTATION_NETWORKS
            )
        else:
            address = ipaddress.ip_address(value)
            allowed = any(address in network for network in DOCUMENTATION_NETWORKS)
    except ValueError:
        return
    if not allowed:
        fail("privacy_ip_outside_documentation_ranges")


def check_string_privacy(value: str) -> None:
    lowered = value.lower()
    if "/users/" in lowered or "downloads" in lowered:
        fail("privacy_forbidden_material")
    if any(pattern.search(value) for pattern in CREDENTIAL_VALUE_PATTERNS):
        fail("privacy_credential_value")
    if UUID_PATTERN.search(value) or EMAIL_PATTERN.search(value):
        fail("privacy_identifier_found")
    for hostname in HOSTNAME_PATTERN.findall(value):
        if hostname.lower() not in ALLOWED_INVALID_HOSTS:
            fail("privacy_hostname_found")
    for match in BRACKETED_IPV6_CANDIDATE.finditer(value):
        check_address_or_network(match.group(1) + (match.group(2) or ""))
    for match in IPV4_CANDIDATE.finditer(value):
        suffix = match.group(2) or ""
        check_address_or_network(
            match.group(1) + (suffix if suffix.startswith("/") else "")
        )
    for match in IPV6_CANDIDATE.finditer(value):
        check_address_or_network(match.group(1) + (match.group(2) or ""))


def check_privacy(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                fail("privacy_non_string_key")
            check_credential_key(key)
            check_string_privacy(key)
            check_privacy(child)
    elif isinstance(value, list):
        for child in value:
            check_privacy(child)
    elif isinstance(value, str):
        check_string_privacy(value)


def check_no_forbidden_conclusions(value: Any) -> None:
    if isinstance(value, dict):
        if FORBIDDEN_CONCLUSION_KEYS & set(value):
            fail("forbidden_conclusion_present")
        for child in value.values():
            check_no_forbidden_conclusions(child)
    elif isinstance(value, list):
        for child in value:
            check_no_forbidden_conclusions(child)
    elif isinstance(value, str) and value.upper() in FORBIDDEN_CONCLUSION_VALUES:
        fail("forbidden_conclusion_present")


def require_same_shape(value: Any, template: Any, path: str) -> None:
    if type(value) is not type(template):
        fail(f"oracle_type_invalid:{path}")
    if isinstance(template, dict):
        if set(value) != set(template):
            fail(f"oracle_keys_invalid:{path}")
        for key in template:
            require_same_shape(value[key], template[key], f"{path}.{key}")
    elif isinstance(template, list):
        if len(value) != len(template):
            fail(f"oracle_list_invalid:{path}")
        for index, (item, expected_item) in enumerate(zip(value, template, strict=True)):
            require_same_shape(item, expected_item, f"{path}[{index}]")


def validate_oracle(oracle: Any) -> tuple[int, int, int]:
    if not isinstance(oracle, dict):
        fail("oracle_root_invalid")
    check_privacy(oracle)
    if set(oracle) != TOP_LEVEL_KEYS:
        fail("oracle_top_level_keys_invalid")
    if (
        oracle["schema"] != ORACLE_SCHEMA
        or oracle["fixture_version"] != FIXTURE_VERSION
        or oracle["provenance"] != PROVENANCE
        or oracle["allowed_invalid_hosts"] != list(ALLOWED_INVALID_HOSTS)
        or oracle["allowed_networks"] != DOCUMENTATION_NETWORK_TEXT
        or oracle["schema_fingerprint"] != SCHEMA_FINGERPRINT
        or oracle["source_limitations"] != SOURCE_LIMITATIONS
        or oracle["negative_guards"] != NEGATIVE_GUARDS
    ):
        fail("oracle_contract_changed")

    cases = oracle["cases"]
    if not isinstance(cases, list):
        fail("oracle_cases_invalid")
    case_ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if case_ids != list(EXPECTED_CASE_IDS):
        fail("oracle_case_order_invalid")

    accepted = 0
    rejected = 0
    for case in cases:
        if set(case) != CASE_KEYS:
            fail("oracle_case_keys_invalid")
        case_id = case["id"]
        raw = case["input_utf8"]
        expected_hash = case["input_sha256"]
        expected = case["expected"]
        if (
            not isinstance(case_id, str)
            or not isinstance(raw, str)
            or not isinstance(expected_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
            or not isinstance(expected, dict)
        ):
            fail("oracle_case_invalid")
        raw_bytes = raw.encode("utf-8")
        if hashlib.sha256(raw_bytes).hexdigest() != expected_hash:
            fail("fixture_hash_changed")

        actual = evaluate(raw_bytes)
        if actual["outcome"] != EXPECTED_OUTCOMES[case_id]:
            fail(f"oracle_outcome_invalid:{case_id}")
        if actual["outcome"] == "BATCH_REJECT":
            if actual["candidate_error_code"] != EXPECTED_REJECTION_CODES[case_id]:
                fail(f"oracle_rejection_invalid:{case_id}")
            rejected += 1
        else:
            accepted += 1
        require_same_shape(expected, actual, f"cases.{case_id}.expected")
        if actual != expected:
            fail(f"oracle_mismatch:{case_id}")
        if evaluate(raw_bytes) != actual:
            fail("fixture_nondeterministic")
        check_no_forbidden_conclusions(actual)
    return len(cases), accepted, rejected


def clone_oracle(oracle: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(oracle))


def replace_sampler_probe(oracle: dict[str, Any], replacement: str) -> None:
    case = oracle["cases"][0]
    case["input_utf8"] = case["input_utf8"].replace(
        "192.0.2.200", replacement, 1
    )
    case["input_sha256"] = hashlib.sha256(
        case["input_utf8"].encode("utf-8")
    ).hexdigest()


def expect_probe_rejected(
    oracle: dict[str, Any], expected_code: str, probe_name: str
) -> None:
    try:
        validate_oracle(oracle)
    except FixtureError as error:
        if str(error) != expected_code:
            fail(f"privacy_regression_wrong_gate:{probe_name}:{error}")
        return
    fail(f"privacy_regression_admitted:{probe_name}")


def run_privacy_regressions(oracle: dict[str, Any]) -> None:
    extra_key = clone_oracle(oracle)
    extra_key["api_key"] = "fixture-only"
    expect_probe_rejected(extra_key, "privacy_credential_key", "extra_api_key")

    probes = (
        ("8.8.8.8:443", "privacy_ip_outside_documentation_ranges", "public_host_port"),
        ("10.23.45.67/32", "privacy_ip_outside_documentation_ranges", "private_cidr"),
        ("AKIAABCDEFGHIJKLMNOP", "privacy_credential_value", "aws_access_key"),
        (
            "[2001:4860:4860::8888]:443",
            "privacy_ip_outside_documentation_ranges",
            "external_ipv6",
        ),
        (
            "2001:4860::/32",
            "privacy_ip_outside_documentation_ranges",
            "external_ipv6_cidr",
        ),
        ("synthetic-sampler", "privacy_ignored_value_invalid", "ignored_free_text"),
    )
    for replacement, expected_code, probe_name in probes:
        candidate = clone_oracle(oracle)
        replace_sampler_probe(candidate, replacement)
        expect_probe_rejected(candidate, expected_code, probe_name)


def verify() -> tuple[int, int, int]:
    try:
        oracle = json.loads(ORACLE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail("oracle_unreadable")
    result = validate_oracle(oracle)
    run_privacy_regressions(oracle)
    return result


def main() -> int:
    try:
        total, accepted, rejected = verify()
    except FixtureError as error:
        print(f"netflow-fixture-v1: FAIL ({error})", file=sys.stderr)
        return 1
    print(
        f"netflow-fixture-v1: PASS ({total} cases; {accepted} accepted; {rejected} rejected)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
