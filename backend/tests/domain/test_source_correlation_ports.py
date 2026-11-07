from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]

from app.domain.customer_upload_profiles import REQUIRED_HEADERS
from app.domain.customer_upload_validator import (
    CustomerUploadValidationError,
    validate_customer_upload_workbook,
)
from app.domain.source_correlations import EvidenceRecord, _compare


def _customer(start_port: object, end_port: object) -> EvidenceRecord:
    return EvidenceRecord(
        source="CUSTOMER",
        record_key="customer-row",
        version_id="customer-version",
        domain="service",
        canonical_ip="192.0.2.10",
        original={
            "fields": {"start_port": start_port, "end_port": end_port}
        },
        availability={},
    )


def _customer_fields(fields: dict[str, object]) -> EvidenceRecord:
    return EvidenceRecord(
        source="CUSTOMER",
        record_key="customer-row",
        version_id="customer-version",
        domain="service",
        canonical_ip="192.0.2.1",
        original={"fields": fields},
        availability={},
    )


def _cloud(port: object) -> EvidenceRecord:
    return EvidenceRecord(
        source="CLOUD",
        record_key="cloud-row",
        version_id="cloud-version",
        domain="service",
        canonical_ip="192.0.2.1",
        original={"port": port, "protocol": "tcp"},
        availability={},
    )


def _save_customer_workbook(path: Path, start: object, end: object) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(list(REQUIRED_HEADERS))
    sheet.append(["192.0.2.1", start, end, "否", None])
    workbook.save(path)
    workbook.close()
    return path


def _read_back_fields(path: Path) -> dict[str, object]:
    assert validate_customer_upload_workbook(path).record_count == 1
    workbook = load_workbook(path, read_only=True)
    try:
        sheet = workbook.active
        assert sheet is not None
        rows = list(sheet.iter_rows(min_row=2, max_row=2, values_only=True))
    finally:
        workbook.close()
    assert len(rows) == 1
    return dict(
        zip(
            ("asset_ip", "start_port", "end_port", "is_web", "web_url"),
            rows[0],
            strict=True,
        )
    )


def _relation(port: int, fields: dict[str, object]) -> str:
    return _compare(6, port, _customer_fields(fields)).port_relation


@pytest.mark.parametrize(
    ("port", "relation"),
    [
        (10_000, "OUT_OF_RANGE"),
        (10_001, "IN_RANGE"),
        (10_002, "IN_RANGE"),
        (10_003, "OUT_OF_RANGE"),
    ],
)
def test_customer_port_interval_is_compared_as_a_closed_interval(
    port: int, relation: str
) -> None:
    comparison = _compare(6, port, _customer(10_001, 10_002))

    assert comparison.port_relation == relation


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (" 10001 ", " 10002 "),
        ("0" * 5000 + "10001", "0" * 5000 + "10002"),
    ],
)
def test_accepted_text_endpoints_survive_real_upload_and_comparison(
    tmp_path: Path, start: str, end: str
) -> None:
    path = _save_customer_workbook(tmp_path / "endpoints.xlsx", start, end)

    fields = _read_back_fields(path)

    assert fields["start_port"] == start
    assert fields["end_port"] == end
    assert _relation(10_001, fields) == "IN_RANGE"
    assert _relation(10_002, fields) == "IN_RANGE"
    assert _relation(10_000, fields) == "OUT_OF_RANGE"
    assert _relation(10_003, fields) == "OUT_OF_RANGE"


@pytest.mark.parametrize(
    ("start", "end", "hits", "misses"),
    [
        (1, 1, (1,), (2,)),
        (65_535, 65_535, (65_535,), (65_534,)),
        (1, 65_535, (1, 32_768, 65_535), (0,)),
        (10_001, 10_002, (10_001, 10_002), (10_000, 10_003)),
    ],
)
def test_closed_intervals_survive_real_upload_and_comparison(
    tmp_path: Path,
    start: int,
    end: int,
    hits: tuple[int, ...],
    misses: tuple[int, ...],
) -> None:
    path = _save_customer_workbook(tmp_path / "interval.xlsx", start, end)

    fields = _read_back_fields(path)

    assert fields["start_port"] == start
    assert fields["end_port"] == end
    for port in hits:
        assert _relation(port, fields) == "IN_RANGE"
    for port in misses:
        assert _relation(port, fields) == "OUT_OF_RANGE"


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (0, "port_out_of_range"),
        (65_536, "port_out_of_range"),
        ("1.0", "port_not_integer"),
        ("1-2", "port_not_integer"),
        ("0x50", "port_not_integer"),
        (True, "port_not_integer"),
        (1.5, "port_not_integer"),
        ("9" * 5000, "port_out_of_range"),
    ],
)
def test_upload_rejects_unaccepted_port_values_without_a_value_error(
    tmp_path: Path, value: object, reason: str
) -> None:
    path = _save_customer_workbook(tmp_path / "rejected.xlsx", value, 1)

    with pytest.raises(CustomerUploadValidationError) as rejection:
        validate_customer_upload_workbook(path)

    assert rejection.value.field == "start_port"
    assert rejection.value.row == 2
    assert rejection.value.reason == reason


@pytest.mark.parametrize(
    "value",
    [0, 65_536, "1.0", "1-2", "0x50", True, 1.5, "9" * 5000, None, "  "],
)
def test_unaccepted_customer_endpoints_compare_unknown_without_raising(
    value: object,
) -> None:
    fields = {"start_port": value, "end_port": 10_002}

    assert _relation(10_001, fields) == "UNKNOWN"


def test_non_customer_ports_keep_zero_and_do_not_accept_whitespace() -> None:
    assert _compare(6, 0, _cloud(0)).port_relation == "EQUAL"
    assert _compare(6, 65_535, _cloud("65535")).port_relation == "EQUAL"
    assert _compare(6, 10_001, _cloud(" 10001 ")).port_relation == "UNKNOWN"
