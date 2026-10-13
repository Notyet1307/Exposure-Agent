import csv
from pathlib import Path
from typing import Any

import pytest

from app.netflow_bulk.contracts import Budget, BulkError, CIDRs, Filter, Member
from app.netflow_bulk.engine import compute, normalize_file
from app.netflow_bulk.storage import file_hash

HEADERS = [
    "IP_SRC_ADDR",
    "IP_DST_ADDR",
    "PROTOCOL",
    "L4_SRC_PORT",
    "L4_DST_PORT",
    "start_time",
    "end_time",
    "EXPORTER",
    "OBSERVATION_POINT",
    "OBSERVATION_DOMAIN_ID",
    "SAMPLING_MODE",
    "NAT",
    "note",
]
BASE = [
    "192.0.2.1",
    "2001:db8::1",
    "6",
    "443",
    "50000",
    "2026-01-01T08:00:00+08:00",
    "2026-01-01T08:01:00+08:00",
    "e1",
    "p1",
    "1",
    "unsampled",
    "unknown",
    "quoted\nline",
]


def material(
    root: Path, name: str, rows: list[list[str]], shard_rows: int = 2
) -> dict[str, int]:
    path = root / name
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADERS)
        writer.writerows(rows)
    member = Member(sha256=file_hash(path), size=path.stat().st_size, name=name)
    return normalize_file(
        path,
        member,
        root / "normalized" / member.sha256,
        Budget(shard_rows=shard_rows, disk_reserve_bytes=0),
        checkpoint=lambda _: None,
        committed=lambda _: None,
        pulse=lambda: None,
    )


def test_cross_file_shard_dedup_and_filter_reuse(tmp_path: Path) -> None:
    alternate = BASE.copy()
    alternate[0] = "::ffff:192.0.2.1"
    alternate[5:7] = ["2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z"]
    material(tmp_path, "a.csv", [BASE, BASE], 1)
    material(tmp_path, "b.csv", [alternate, BASE], 1)
    result = compute(
        tmp_path / "normalized",
        tmp_path / "result",
        Filter(),
        Budget(disk_reserve_bytes=0),
        pulse=lambda: None,
    )
    assert result["counts"] == {
        "raw": 4,
        "invalid": 0,
        "filtered": 0,
        "retained": 4,
        "unique": 1,
        "duplicate": 3,
    }
    for path in tmp_path.glob("*.csv"):
        path.unlink()
    zero = compute(
        tmp_path / "normalized",
        tmp_path / "filtered",
        Filter(protocols=[17]),
        Budget(disk_reserve_bytes=0),
        pulse=lambda: None,
    )
    assert zero["counts"] == {
        "raw": 4,
        "invalid": 0,
        "filtered": 4,
        "retained": 0,
        "unique": 0,
        "duplicate": 0,
    }


@pytest.mark.parametrize(
    "index,replacement", [(5, ""), (7, ""), (8, ""), (9, ""), (10, "unknown")]
)
def test_missing_identity_preserves_records(
    tmp_path: Path, index: int, replacement: str
) -> None:
    row = BASE.copy()
    row[index] = replacement
    material(tmp_path, "a.csv", [row, row])
    result = compute(
        tmp_path / "normalized",
        tmp_path / "result",
        Filter(),
        Budget(disk_reserve_bytes=0),
        pulse=lambda: None,
    )
    assert result["counts"]["unique"] == 2


@pytest.mark.parametrize(
    "index,replacement",
    [(1, "2001:db8::2"), (8, "other-point"), (9, "2"), (10, "sampled"), (11, "mapped")],
)
def test_distinct_network_conditions_preserved(
    tmp_path: Path, index: int, replacement: str
) -> None:
    row = BASE.copy()
    row[index] = replacement
    material(tmp_path, "a.csv", [BASE, row])
    result = compute(
        tmp_path / "normalized",
        tmp_path / "result",
        Filter(),
        Budget(disk_reserve_bytes=0),
        pulse=lambda: None,
    )
    assert result["counts"]["unique"] == 2


def test_ipv6_cidr_intervals() -> None:
    ranges = CIDRs(["2001:db8::/32", "192.0.2.0/25", "192.0.2.128/25"])
    assert ranges.contains("2001:db8:ffff::1")
    assert ranges.contains("192.0.2.255")
    assert not ranges.contains("2001:db9::1")
    assert len(ranges.ranges[4]) == 1


def test_corrupt_bytes_and_hash_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_bytes(b"\xff\xff")
    member = Member(sha256=file_hash(path), size=2, name="bad.csv")
    with pytest.raises(BulkError):
        normalize_file(
            path,
            member,
            tmp_path / "normalized",
            Budget(disk_reserve_bytes=0),
            checkpoint=lambda _: None,
            committed=lambda _: None,
            pulse=lambda: None,
        )


def test_empty_dataset_and_all_invalid_are_distinct(tmp_path: Path) -> None:
    material(tmp_path, "empty.csv", [])
    empty = compute(
        tmp_path / "normalized",
        tmp_path / "empty-result",
        Filter(),
        Budget(disk_reserve_bytes=0),
        pulse=lambda: None,
    )
    assert empty["counts"]["raw"] == empty["counts"]["unique"] == 0
    bad = BASE.copy()
    bad[0] = "not-an-address"
    material(tmp_path, "bad.csv", [bad])
    with pytest.raises(BulkError, match="netflow_no_valid_records"):
        compute(
            tmp_path / "normalized",
            tmp_path / "bad-result",
            Filter(),
            Budget(disk_reserve_bytes=0),
            pulse=lambda: None,
        )


def test_safe_paths_and_compressed_inputs_are_rejected(tmp_path: Path) -> None:
    from pydantic import ValidationError

    from app.netflow_bulk.storage import safe_file

    outside = tmp_path / "secret.txt"
    outside.write_text("synthetic-only")
    root = tmp_path / "mount"
    root.mkdir()
    (root / "link.csv").symlink_to(outside)
    for value in ("../secret.txt", str(outside), "link.csv", "a/../secret.txt"):
        with pytest.raises(BulkError):
            safe_file(root, value)
    with pytest.raises(ValidationError):
        Member(sha256="a" * 64, size=1, name="input.csv.gz")


def test_engine_has_no_unrestricted_filesystem_access(tmp_path: Path) -> None:
    import duckdb

    from app.netflow_bulk.engine import connection

    outside = tmp_path / "outside.csv"
    outside.write_text("value\n1\n")
    con = connection(tmp_path / "work", Budget(disk_reserve_bytes=0))
    try:
        with pytest.raises(duckdb.PermissionException):
            con.execute("SELECT * FROM read_csv(?)", [str(outside)])
    finally:
        con.close()


@pytest.mark.parametrize(
    "cidrs,expected",
    [
        (["192.0.2.0/24"], 1),
        (["::ffff:192.0.2.0/120"], 1),
        (["2001:db8::/32"], 1),
        (["2001:db9::/32"], 0),
    ],
)
def test_asof_cidr_filter_handles_both_families(
    tmp_path: Path, cidrs: list[str], expected: int
) -> None:
    ipv6 = BASE.copy()
    ipv6[0] = "2001:db8::2"
    material(tmp_path, "input.csv", [BASE, ipv6])
    result = compute(
        tmp_path / "normalized",
        tmp_path / "result",
        Filter(cidrs=cidrs),
        Budget(disk_reserve_bytes=0),
        pulse=lambda: None,
    )
    assert result["counts"]["unique"] == expected


def test_csv_record_limit_applies_before_csv_allocates_fields(tmp_path: Path) -> None:
    from app.netflow_bulk.contracts import MAX_RECORD

    path = tmp_path / "long.csv"
    # Many short fields bypass a field-size-only guard; the physical input is bounded.
    path.write_text("," * (MAX_RECORD + 100))
    member = Member(sha256=file_hash(path), size=path.stat().st_size, name=path.name)
    with pytest.raises(BulkError, match="bulk_record_limit"):
        normalize_file(
            path,
            member,
            tmp_path / "out",
            Budget(disk_reserve_bytes=0),
            checkpoint=lambda _: None,
            committed=lambda _: None,
            pulse=lambda: None,
        )


def test_new_directories_are_synced_before_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.netflow_bulk import storage

    calls: list[Path] = []
    original = storage.sync_directory

    def sync(path: Path) -> None:
        calls.append(path)
        original(path)

    monkeypatch.setattr(storage, "sync_directory", sync)
    storage.durable_directory(tmp_path / "a" / "b")
    assert (
        tmp_path in calls and tmp_path / "a" in calls and tmp_path / "a" / "b" in calls
    )


def test_zero_ports_are_canonical_and_queryable(tmp_path: Path) -> None:
    from app.netflow_bulk.engine import batches

    a, b = BASE.copy(), BASE.copy()
    a[3:5], b[3:5] = ["0", "0"], ["00", "000"]
    material(tmp_path, "ports.csv", [a, b])
    result = compute(
        tmp_path / "normalized",
        tmp_path / "result",
        Filter(),
        Budget(disk_reserve_bytes=0),
        pulse=lambda: None,
    )
    assert result["counts"]["unique"] == 1
    assert result["counts"]["duplicate"] == 1
    assert next(batches(Path(result["files"]["observations"]["path"])))[0]["port"] == 0


def test_oversized_decimal_is_invalid_not_a_batch_exception(tmp_path: Path) -> None:
    row = BASE.copy()
    row[2] = "9" * 5000
    material(tmp_path, "oversized-number.csv", [BASE, row])
    result = compute(
        tmp_path / "normalized",
        tmp_path / "result",
        Filter(),
        Budget(disk_reserve_bytes=0),
        pulse=lambda: None,
    )
    assert result["counts"]["raw"] == 2
    assert result["counts"]["invalid"] == 1
    assert result["counts"]["unique"] == 1


def test_batch_budget_includes_expanded_header_names(tmp_path: Path) -> None:
    header = HEADERS + ["x" * 10000]
    path = tmp_path / "wide-header.csv"
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows([BASE + ["v"]] * 2000)
    member = Member(sha256=file_hash(path), size=path.stat().st_size, name=path.name)
    checkpoints: list[dict[str, Any]] = []
    normalize_file(
        path,
        member,
        tmp_path / "normalized",
        Budget(disk_reserve_bytes=0),
        checkpoint=checkpoints.append,
        committed=lambda _: None,
        pulse=lambda: None,
    )
    assert sum(item["rows"] for item in checkpoints) == 2000
    assert max(item["rows"] for item in checkpoints) < 1000


@pytest.mark.parametrize(
    "field,value",
    [
        ("EXPORTER", "unknown"),
        ("OBSERVATION_DOMAIN_ID", "N/A"),
        ("SAMPLING_RATE", "NaN"),
        ("SAMPLING_RATE", "0"),
    ],
)
def test_unknown_collection_identity_keeps_export_rows(field: str, value: str) -> None:
    from app.netflow_bulk.engine import normalize

    values = dict(zip(HEADERS, BASE, strict=True))
    values[field] = value
    if field == "SAMPLING_RATE":
        values["SAMPLING_MODE"] = "sampled"
    member = Member(sha256="a" * 64, size=1, name="fixture.csv")
    assert (
        normalize(values, member, 1)["canonical_key"]
        != normalize(values, member, 2)["canonical_key"]
    )
