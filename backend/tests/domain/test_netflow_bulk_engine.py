import csv
from pathlib import Path

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
