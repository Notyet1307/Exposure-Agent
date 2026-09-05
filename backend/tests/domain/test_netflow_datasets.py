import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.domain.netflow_datasets import (
    NETFLOW_DATASET_CONTRACT_VERSION,
    NetFlowAcceptanceError,
    parse_netflow_dataset,
)


def test_parse_netflow_dataset_produces_deterministic_normalized_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "flows.csv"
    path.write_bytes(
        b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT,start_time,end_time\n"
        b"198.51.100.20,192.0.2.10,6,53000,443,2026-09-04 10:00:00,2026-09-04 10:00:01\n"
    )

    parsed = parse_netflow_dataset(path)

    assert parsed.contract_version == NETFLOW_DATASET_CONTRACT_VERSION
    assert parsed.raw_record_count == 1
    assert parsed.activity_valid_record_count == 1
    assert parsed.isolated_record_count == 0
    assert parsed.encoding == "utf-8-sig"
    assert parsed.valid_time_start_utc == "2026-09-04T02:00:00Z"
    assert parsed.valid_time_end_utc == "2026-09-04T02:00:01Z"
    assert parsed.normalized_path.read_bytes() == (
        b"source_record_key,src_ip,dst_ip,protocol,src_port,dst_port,start_time_utc,end_time_utc,in_bytes_estimated,in_packets_estimated,tcp_flags\n"
        b"row:1,198.51.100.20,192.0.2.10,6,53000,443,2026-09-04T02:00:00Z,2026-09-04T02:00:01Z,,,\n"
    )


def test_parse_netflow_dataset_rejects_empty_input_with_stable_code(
    tmp_path: Path,
) -> None:
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")

    with pytest.raises(NetFlowAcceptanceError) as caught:
        parse_netflow_dataset(path)

    assert caught.value.code == "netflow_missing_header"
    assert str(caught.value) == "netflow_missing_header"


def test_parser_matches_shared_oracle_cases(tmp_path: Path) -> None:
    oracle_path = (
        Path(__file__).resolve().parents[3] / "tests/netflow_fixture/oracle-v1.json"
    )
    oracle = json.loads(oracle_path.read_text())
    for case in oracle["cases"]:
        path = tmp_path / f"{case['id']}.csv"
        path.write_bytes(case["input_utf8"].encode("utf-8"))
        expected = case["expected"]
        if expected["outcome"] == "BATCH_REJECT":
            with pytest.raises(NetFlowAcceptanceError) as caught:
                parse_netflow_dataset(path)
            assert caught.value.code == expected["candidate_error_code"]
            continue
        parsed = parse_netflow_dataset(path)
        assert parsed.normalized_path.read_text() == expected["normalized_utf8"]
        assert parsed.normalized_sha256 == expected["normalized_sha256"]
        assert parsed.raw_sha256 == case["input_sha256"]
        assert parsed.schema_fingerprint == expected["schema_fingerprint"]
        assert parsed.raw_record_count == expected["raw_record_count"]
        assert (
            parsed.activity_valid_record_count
            == expected["activity_valid_record_count"]
        )
        assert parsed.isolated_record_count == expected["isolated_record_count"]
        assert list(parsed.warnings) == expected["warnings"]
        assert parsed.duplicate_group_count == expected["duplicate_group_count"]
        assert parsed.duplicate_record_count == expected["duplicate_record_count"]


@pytest.mark.parametrize("value", [None, "x", "0", str(50 * 1024 * 1024 + 1)])
def test_netflow_max_bytes_rejects_invalid_configuration(
    value: str | None, tmp_path: Path
) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "PROJECT_NAME": "x",
            "POSTGRES_SERVER": "x",
            "POSTGRES_USER": "x",
            "FIRST_SUPERUSER": "settings@example.com",
            "FIRST_SUPERUSER_PASSWORD": "long-password",
        }
    )
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    if value is None:
        environment.pop("NETFLOW_MAX_BYTES", None)
    else:
        environment["NETFLOW_MAX_BYTES"] = value
    result = subprocess.run(
        [sys.executable, "-c", "import app.core.config"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0


@pytest.mark.parametrize("value", [1, 1024 * 1024, 50 * 1024 * 1024])
def test_netflow_max_bytes_accepts_positive_deployment_limit(
    value: int, tmp_path: Path
) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "PROJECT_NAME": "x",
            "POSTGRES_SERVER": "x",
            "POSTGRES_USER": "x",
            "FIRST_SUPERUSER": "settings@example.com",
            "FIRST_SUPERUSER_PASSWORD": "long-password",
        }
    )
    environment["NETFLOW_MAX_BYTES"] = str(value)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    result = subprocess.run(
        [sys.executable, "-c", "import app.core.config"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_netflow_parser_accepts_arbitrary_ignored_values_and_gb18030(
    tmp_path: Path,
) -> None:
    chunk_size = 1024 * 1024
    header = b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT,FLOW_SAMPLER_ID,EXTRA\n"
    row = b"198.51.100.20,192.0.2.10,6,53000,443,production-free-form,ascii\n"
    final_prefix = b"198.51.100.20,192.0.2.10,6,53000,443,production-free-form,"
    row_count = (chunk_size - 1 - len(header) - len(final_prefix)) // len(row)
    prefix = header + row * row_count + final_prefix
    content = (
        prefix + (b"a" * (chunk_size - 1 - len(prefix))) + "中\n".encode("gb18030")
    )
    assert content[chunk_size - 1 : chunk_size + 1] == "中".encode("gb18030")
    path = tmp_path / "gb.txt"
    path.write_bytes(content)
    parsed = parse_netflow_dataset(path)
    assert parsed.encoding == "gb18030"
    ignored = next(
        warning
        for warning in parsed.warnings
        if warning["code"] == "netflow_ignored_input_columns"
    )
    assert ignored == {
        "code": "netflow_ignored_input_columns",
        "field": None,
        "count": 2,
        "source_record_keys": [],
    }


def test_netflow_parser_rejects_invalid_encoding(tmp_path: Path) -> None:
    path = tmp_path / "invalid.txt"
    path.write_bytes(b"\x81")
    with pytest.raises(NetFlowAcceptanceError) as caught:
        parse_netflow_dataset(path)
    assert caught.value.code == "netflow_invalid_encoding"


def test_parser_cleanup_failure_does_not_mask_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "invalid.csv"
    path.write_text(
        "IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
        "192.0.2.1,198.51.100.1,6\n"
    )
    original_unlink = Path.unlink

    def fail_cleanup(self: Path, missing_ok: bool = False) -> None:
        if self.name.startswith(".invalid.csv."):
            raise OSError("cleanup failed")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    with pytest.raises(NetFlowAcceptanceError) as caught:
        parse_netflow_dataset(path)
    assert caught.value.code == "netflow_invalid_record_width"


def test_successful_scan_cleanup_failure_becomes_stable_processing_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "flows.csv"
    path.write_bytes(
        b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
        b"192.0.2.1,198.51.100.1,6,12345,443\n"
    )
    original_unlink = Path.unlink

    def fail_scan_db_cleanup(self: Path, missing_ok: bool = False) -> None:
        if self.name.endswith(".scan.sqlite"):
            raise OSError("cleanup failed")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_scan_db_cleanup)
    with pytest.raises(NetFlowAcceptanceError) as caught:
        parse_netflow_dataset(path)
    assert caught.value.code == "netflow_processing_failed"
    assert not list(tmp_path.glob("*.normalized.tmp"))
