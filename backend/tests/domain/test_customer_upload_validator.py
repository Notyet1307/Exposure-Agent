import re
import struct
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest
from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]
from openpyxl.worksheet._read_only import (  # type: ignore[import-untyped]
    ReadOnlyWorksheet,
)

from app.domain._xlsx_preflight import (
    MAX_CENTRAL_DIRECTORY_BYTES,
    MAX_ENTRY_UNCOMPRESSED_BYTES,
    MAX_TOTAL_UNCOMPRESSED_BYTES,
    MAX_ZIP_ENTRIES,
    PreflightError,
    _check_central_directory,
)
from app.domain.customer_upload_validator import (
    MAX_WARNING_NAME_CHARACTERS,
    MAX_WORKBOOK_BYTES,
    CustomerUploadValidationError,
    CustomerUploadWarning,
    validate_customer_upload_workbook,
)
from app.domain.models import CustomerUploadWarningDetailPublic
from tests.xlsx_fixtures import build_xlsx_fixture, pad_xlsx_to_size

DEFAULT_HEADERS = [
    "资产IP",
    "起始端口",
    "结束端口",
    "是否web界面",
    "web界面url",
    "服务类型",
    "资产负责人",
    "资产所属部门",
    "端口负责人",
    "部门",
]


def _save_workbook(path: Path, rows: Sequence[Sequence[object]]) -> Path:
    workbook = Workbook()
    worksheet = workbook.active
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    workbook.close()
    return path


def _rewrite_zip_member(
    path: Path, name: str, transform: Callable[[bytes], bytes]
) -> None:
    replacement = path.with_suffix(".rewritten.xlsx")
    with (
        ZipFile(path) as source,
        ZipFile(replacement, "w", compression=ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            data = source.read(info)
            if info.filename == name:
                data = transform(data)
            target.writestr(info, data)
    replacement.replace(path)


def _build_exact_size_xlsx(path: Path, size: int) -> Path:
    _save_workbook(
        path, [DEFAULT_HEADERS, ["192.0.2.1", 443, 443, "否", None]]
    )
    return pad_xlsx_to_size(path, size)


def _patch_declared_uncompressed_size(path: Path, size: int) -> None:
    data = bytearray(path.read_bytes())
    central = data.find(b"PK\x01\x02")
    assert central >= 0
    struct.pack_into("<L", data, central + 24, size)
    path.write_bytes(bytes(data))


def _move_formula_to_responsibility_field(
    data: bytes, encoding: str
) -> bytes:
    data = re.sub(rb'<c r="K2".*?</c>', b"", data, count=1)
    data = re.sub(
        rb'<c r="F2".*?</c>',
        b'<c r="F2"><f>1+1</f><v /></c>',
        data,
        count=1,
    )
    return data.decode("utf-8").encode(encoding)


def test_valid_default_v1_workbook_returns_record_count(tmp_path: Path) -> None:
    path = _save_workbook(
        tmp_path / "input.xlsx",
        [
            DEFAULT_HEADERS,
            [
                "192.0.2.10",
                443,
                443,
                "是",
                "fixture.example.invalid",
                "Fixture Service",
                "Example Owner",
                "Example Department",
                "Example Port Owner",
                "Example Operations",
            ],
            [
                "2001:db8::10",
                "22",
                "22",
                "否",
                None,
                "Fixture SSH",
                "Example Owner",
                "Example Department",
                "Example Port Owner",
                "Example Operations",
            ],
        ],
    )

    result = validate_customer_upload_workbook(path)

    assert result.record_count == 2
    assert result.warnings == ()


def _assert_rejected(
    path: Path,
    code: str,
    *,
    field: str | None = None,
    row: int | None = None,
    reason: str | None = None,
) -> None:
    with pytest.raises(CustomerUploadValidationError) as caught:
        validate_customer_upload_workbook(path)

    assert caught.value.code == code
    assert caught.value.field == field
    assert caught.value.row == row
    if reason is not None:
        assert caught.value.reason == reason
    assert str(caught.value) == code


@pytest.mark.parametrize(
    ("headers", "field"),
    [
        (DEFAULT_HEADERS[1:], "asset_ip"),
        (["资产IP ", *DEFAULT_HEADERS[1:]], "asset_ip"),
        ([*DEFAULT_HEADERS, "资产IP"], None),
        ([*DEFAULT_HEADERS[:2], None, *DEFAULT_HEADERS[3:]], None),
        ([*DEFAULT_HEADERS, "   "], None),
    ],
)
def test_headers_must_match_default_v1_exactly_and_be_unique(
    tmp_path: Path, headers: list[object], field: str | None
) -> None:
    path = _save_workbook(tmp_path / "headers.xlsx", [headers, ["partial"]])

    _assert_rejected(
        path, "missing_required_structure", field=field, row=1
    )


def test_explicit_trailing_blank_header_is_rejected(tmp_path: Path) -> None:
    path = _save_workbook(
        tmp_path / "blank-header.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.1", 443, 443, "否", None]],
    )
    _rewrite_zip_member(
        path,
        "xl/worksheets/sheet1.xml",
        lambda data: data.replace(
            b"</row>", b'<c r="K1" t="n"></c></row>', 1
        ),
    )

    _assert_rejected(path, "missing_required_structure", row=1)


def test_workbook_requires_one_visible_sheet(tmp_path: Path) -> None:
    path = _save_workbook(
        tmp_path / "sheets.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.1", 443, 443, "否", None]],
    )
    workbook = load_workbook(path)
    hidden = workbook.create_sheet("Hidden")
    hidden.sheet_state = "hidden"
    workbook.save(path)
    workbook.close()

    _assert_rejected(path, "unsupported_workbook_feature")


@pytest.mark.parametrize("merged_range", ["A1:B1", "A1:A2"])
def test_merged_header_is_rejected(
    tmp_path: Path, merged_range: str
) -> None:
    path = _save_workbook(
        tmp_path / "merged.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.1", 443, 443, "否", None]],
    )
    workbook = load_workbook(path)
    workbook.active.merge_cells(merged_range)
    workbook.save(path)
    workbook.close()

    _assert_rejected(path, "missing_required_structure", row=1)


def test_title_row_before_headers_is_rejected_as_multi_row_header(
    tmp_path: Path,
) -> None:
    path = _save_workbook(
        tmp_path / "title.xlsx",
        [["Asset Inventory"], DEFAULT_HEADERS, ["192.0.2.1", 443, 443, "否", None]],
    )

    _assert_rejected(path, "missing_required_structure", row=1)


@pytest.mark.parametrize(
    ("value", "field"),
    [
        ("192.0.2.1/32", "asset_ip"),
        ("192.0.2.1-192.0.2.2", "asset_ip"),
        ("fixture.example.invalid", "asset_ip"),
        ("192.0.2.1,198.51.100.1", "asset_ip"),
        (0, "start_port"),
        (65_536, "start_port"),
        (True, "start_port"),
        (1.5, "start_port"),
        ("1.0", "start_port"),
        ("0x50", "start_port"),
        ("1-2", "start_port"),
        ("65536", "start_port"),
    ],
)
def test_invalid_ip_and_port_values_are_rejected_with_canonical_field(
    tmp_path: Path, value: object, field: str
) -> None:
    row: list[object] = ["192.0.2.1", 443, 443, "否", None]
    row[0 if field == "asset_ip" else 1] = value
    path = _save_workbook(tmp_path / "value.xlsx", [DEFAULT_HEADERS, row])

    _assert_rejected(path, "invalid_required_value", field=field, row=2)


def test_scoped_ipv6_is_rejected_as_non_literal(tmp_path: Path) -> None:
    path = _save_workbook(
        tmp_path / "scoped-ipv6.xlsx",
        [DEFAULT_HEADERS, ["fe80::1%eth0", 443, 443, "否", None]],
    )

    _assert_rejected(
        path, "invalid_required_value", field="asset_ip", row=2
    )


def test_oversized_decimal_port_has_canonical_field_and_row(
    tmp_path: Path,
) -> None:
    path = _save_workbook(
        tmp_path / "oversized-port.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.1", "9" * 5_000, 443, "否", None]],
    )

    _assert_rejected(
        path, "invalid_required_value", field="start_port", row=2
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (1, 1),
        (65_535, 65_535),
        (10_001, 10_002),
        (1, 65_535),
        ("010001", "10002"),
    ],
)
def test_port_closed_interval_is_accepted(
    tmp_path: Path, start: object, end: object
) -> None:
    path = _save_workbook(
        tmp_path / "interval.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.1", start, end, "否", None]],
    )

    result = validate_customer_upload_workbook(path)

    assert result.record_count == 1


@pytest.mark.parametrize(
    ("start", "end", "field", "reason"),
    [
        (0, 1, "start_port", "port_out_of_range"),
        (1, 0, "end_port", "port_out_of_range"),
        (1, 65_536, "end_port", "port_out_of_range"),
        (10_002, 10_001, "end_port", "port_order"),
        (1.5, 2, "start_port", "port_not_integer"),
        (True, 1, "start_port", "port_not_integer"),
        ("1-2", 2, "start_port", "port_not_integer"),
    ],
)
def test_port_interval_rejects_bad_values_with_reason(
    tmp_path: Path, start: object, end: object, field: str, reason: str
) -> None:
    path = _save_workbook(
        tmp_path / "bad-interval.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.1", start, end, "否", None]],
    )

    _assert_rejected(
        path,
        "invalid_required_value",
        field=field,
        row=2,
        reason=reason,
    )


@pytest.mark.parametrize(
    ("web_flag", "url", "field"),
    [
        ("true", None, "is_web"),
        ("是", None, "web_url"),
        ("否", "fixture.example.invalid", "web_url"),
        ("无", "fixture.example.invalid", "web_url"),
        ("否", "   ", "web_url"),
    ],
)
def test_web_flag_and_url_combination_is_strict(
    tmp_path: Path, web_flag: str, url: str | None, field: str
) -> None:
    path = _save_workbook(
        tmp_path / "web.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.1", 443, 443, web_flag, url]],
    )

    _assert_rejected(path, "invalid_required_value", field=field, row=2)


REORDERED_HEADERS = [
    "web界面url",
    "是否web界面",
    "结束端口",
    "起始端口",
    "资产IP",
    "服务类型",
    "资产负责人",
    "资产所属部门",
    "端口负责人",
    "部门",
]


def _reordered_row(
    *,
    asset_ip: object = "192.0.2.1",
    start_port: object = 443,
    end_port: object = 443,
    is_web: object = "否",
    web_url: object = None,
) -> list[object]:
    return [
        web_url,
        is_web,
        end_port,
        start_port,
        asset_ip,
        None,
        None,
        None,
        None,
        None,
    ]


@pytest.mark.parametrize(
    ("changes", "field", "reason", "column", "limit", "unit"),
    [
        ({"asset_ip": "not-an-ip"}, "asset_ip", "invalid_ip", 5, None, None),
        (
            {"start_port": 70_000},
            "start_port",
            "port_out_of_range",
            4,
            65_535,
            "port_number",
        ),
        (
            {"start_port": "1.5"},
            "start_port",
            "port_not_integer",
            4,
            None,
            None,
        ),
        (
            {"end_port": 0},
            "end_port",
            "port_out_of_range",
            3,
            65_535,
            "port_number",
        ),
        (
            {"end_port": "1.5"},
            "end_port",
            "port_not_integer",
            3,
            None,
            None,
        ),
        (
            {"start_port": 10_002, "end_port": 10_001},
            "end_port",
            "port_order",
            3,
            None,
            None,
        ),
        ({"is_web": "maybe"}, "is_web", "web_flag", 2, None, None),
        (
            {"is_web": "是", "web_url": None},
            "web_url",
            "web_url",
            1,
            None,
            None,
        ),
        (
            {"is_web": "否", "web_url": "fixture.example.invalid"},
            "web_url",
            "web_url",
            1,
            None,
            None,
        ),
    ],
)
def test_reordered_headers_report_the_original_one_based_column(
    tmp_path: Path,
    changes: dict[str, Any],
    field: str,
    reason: str,
    column: int,
    limit: int | None,
    unit: str | None,
) -> None:
    row = _reordered_row(**changes)
    path = _save_workbook(tmp_path / "reordered.xlsx", [REORDERED_HEADERS, row])

    with pytest.raises(CustomerUploadValidationError) as caught:
        validate_customer_upload_workbook(path)

    error = caught.value
    assert error.code == "invalid_required_value"
    assert error.field == field
    assert error.row == 2
    assert error.column == column
    assert error.reason == reason
    assert error.location == "worksheet"
    assert error.limit == limit
    assert error.unit == unit


def test_structural_error_does_not_claim_a_column(tmp_path: Path) -> None:
    headers = [header for header in DEFAULT_HEADERS if header != "资产IP"]
    path = _save_workbook(
        tmp_path / "missing-ip-header.xlsx",
        [headers, ["192.0.2.1", 443, 443, "否", None]],
    )

    with pytest.raises(CustomerUploadValidationError) as caught:
        validate_customer_upload_workbook(path)

    error = caught.value
    assert error.code == "missing_required_structure"
    assert error.field == "asset_ip"
    assert error.row == 1
    assert error.column is None


def test_blank_rows_are_ignored_but_partial_rows_fail_at_actual_xlsx_row(
    tmp_path: Path,
) -> None:
    path = _save_workbook(
        tmp_path / "partial.xlsx",
        [
            DEFAULT_HEADERS,
            ["192.0.2.1", 443, 443, "否", None],
            [None] * len(DEFAULT_HEADERS),
            [None, None, None, None, None, "partial responsibility"],
        ],
    )

    _assert_rejected(
        path, "invalid_required_value", field="asset_ip", row=4
    )


def test_whitespace_only_row_is_partial_not_physically_blank(tmp_path: Path) -> None:
    path = _save_workbook(
        tmp_path / "whitespace-row.xlsx",
        [
            DEFAULT_HEADERS,
            ["192.0.2.1", 443, 443, "否", None],
            ["   "] + [None] * (len(DEFAULT_HEADERS) - 1),
        ],
    )

    _assert_rejected(
        path, "invalid_required_value", field="asset_ip", row=3
    )


def test_multiline_undefined_header_is_counted_as_an_extra_column(
    tmp_path: Path,
) -> None:
    path = _save_workbook(
        tmp_path / "extra.xlsx",
        [
            [*DEFAULT_HEADERS, "Extra\nDescription"],
            [
                "192.0.2.1",
                443,
                443,
                "否",
                None,
                "Service",
                "Owner",
                "Department",
                "Port Owner",
                "Operations",
                "Fixture",
            ],
        ],
    )

    result = validate_customer_upload_workbook(path)

    assert result.warnings == (
        CustomerUploadWarning("extra_columns_ignored", None, 1),
    )


@pytest.mark.parametrize("coordinate", ["Z1", "Z2", "XFD2000"])
def test_style_only_cells_outside_data_columns_are_ignored(
    tmp_path: Path, coordinate: str
) -> None:
    path = _save_workbook(
        tmp_path / "styled.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.1", 443, 443, "否", None]],
    )
    workbook = load_workbook(path)
    workbook.active[coordinate].number_format = "0.00"
    workbook.save(path)
    workbook.close()

    result = validate_customer_upload_workbook(path)

    assert result.record_count == 1


def test_warning_counts_cover_missing_columns_empty_values_and_extra_columns(
    tmp_path: Path,
) -> None:
    headers = [
        *DEFAULT_HEADERS[:6],
        "资产负责人",
        "序号",
        "Unmapped Fixture Column",
    ]
    path = _save_workbook(
        tmp_path / "warnings.xlsx",
        [
            headers,
            ["192.0.2.1", 443, 443, "否", None, None, "Owner", None, "x"],
            ["2001:db8::1", "22", "22", "无", None, "SSH", "  ", None, "y"],
            [None] * len(headers),
        ],
    )

    result = validate_customer_upload_workbook(path)

    assert result.record_count == 2
    assert result.warnings == (
        CustomerUploadWarning("missing_responsibility_value", "service_type", 1),
        CustomerUploadWarning("missing_responsibility_value", "asset_owner", 1),
        CustomerUploadWarning("missing_responsibility_value", "asset_department", 2),
        CustomerUploadWarning("missing_responsibility_value", "port_owner", 2),
        CustomerUploadWarning("missing_responsibility_value", "department", 2),
        CustomerUploadWarning("extra_columns_ignored", None, 1),
    )


def test_extra_column_warning_detail_is_bounded_sanitized_and_suggests_exact_matches(
    tmp_path: Path,
) -> None:
    extras = [
        "资产 IP",
        "服务 类型",
        "‮Hidden‬",
        "X" * 100,
    ]
    headers = [*DEFAULT_HEADERS, *extras]
    path = _save_workbook(
        tmp_path / "extra-detail.xlsx",
        [
            headers,
            [
                "192.0.2.1",
                443,
                443,
                "否",
                None,
                "Service",
                "Owner",
                "Department",
                "Port Owner",
                "Operations",
                *(["value"] * len(extras)),
            ],
        ],
    )

    result = validate_customer_upload_workbook(path)

    extra = next(
        warning
        for warning in result.warnings
        if warning.code == "extra_columns_ignored"
    )
    assert extra.count == 4
    assert extra.detail == {
        "names": [
            {"name": "资产 IP", "column": 11, "near_match": "asset_ip"},
            {"name": "服务 类型", "column": 12, "near_match": "service_type"},
            {"name": "Hidden", "column": 13, "near_match": None},
            {"name": "X" * 64, "column": 14, "near_match": None},
        ],
        "truncated": False,
        "omitted_count": 0,
        "names_truncated": True,
    }


def test_extra_column_warning_detail_does_not_mark_an_exact_64_character_name(
    tmp_path: Path,
) -> None:
    extras = ["Y" * MAX_WARNING_NAME_CHARACTERS]
    headers = [*DEFAULT_HEADERS, *extras]
    path = _save_workbook(
        tmp_path / "extra-exact-name.xlsx",
        [
            headers,
            [
                "192.0.2.1",
                443,
                443,
                "否",
                None,
                "Service",
                "Owner",
                "Department",
                "Port Owner",
                "Operations",
                *(["value"] * len(extras)),
            ],
        ],
    )

    result = validate_customer_upload_workbook(path)

    extra = next(
        warning
        for warning in result.warnings
        if warning.code == "extra_columns_ignored"
    )
    assert extra.detail == {
        "names": [
            {
                "name": "Y" * MAX_WARNING_NAME_CHARACTERS,
                "column": 11,
                "near_match": None,
            }
        ],
        "truncated": False,
        "omitted_count": 0,
        "names_truncated": False,
    }


def test_historical_warning_detail_defaults_names_truncated_false() -> None:
    detail = CustomerUploadWarningDetailPublic.model_validate(
        {
            "names": [{"name": "legacy-short", "column": 6, "near_match": None}],
            "truncated": True,
            "omitted_count": 2,
        }
    )

    assert detail.names_truncated is False


def test_extra_column_warning_detail_keeps_at_most_32_names(
    tmp_path: Path,
) -> None:
    extras = [f"Extra column {index}" for index in range(40)]
    headers = [*DEFAULT_HEADERS, *extras]
    path = _save_workbook(
        tmp_path / "extra-truncated.xlsx",
        [
            headers,
            [
                "192.0.2.1",
                443,
                443,
                "否",
                None,
                "Service",
                "Owner",
                "Department",
                "Port Owner",
                "Operations",
                *(["value"] * len(extras)),
            ],
        ],
    )

    result = validate_customer_upload_workbook(path)

    extra = next(
        warning
        for warning in result.warnings
        if warning.code == "extra_columns_ignored"
    )
    assert extra.count == 40
    assert extra.detail is not None
    assert len(extra.detail["names"]) == 32
    assert extra.detail["names"][0] == {
        "name": "Extra column 0",
        "column": 11,
        "near_match": None,
    }
    assert extra.detail["names"][-1]["column"] == 42
    assert extra.detail["truncated"] is True
    assert extra.detail["omitted_count"] == 8
    assert extra.detail["names_truncated"] is False


def test_workbook_requires_a_non_empty_data_row(tmp_path: Path) -> None:
    path = _save_workbook(
        tmp_path / "empty.xlsx", [DEFAULT_HEADERS, [None] * len(DEFAULT_HEADERS)]
    )

    _assert_rejected(path, "missing_required_structure")


@pytest.mark.parametrize(
    ("fixture_name", "expected_records"),
    [
        ("default_v1", 3),
        ("row_shared_style_boundary", 50_000),
    ],
)
def test_xlsx_normal_boundaries_are_accepted(
    tmp_path: Path, fixture_name: str, expected_records: int
) -> None:
    path = build_xlsx_fixture(fixture_name, tmp_path / "boundary.xlsx")

    result = validate_customer_upload_workbook(path)

    assert result.record_count == expected_records
    assert result.warnings == ()


def test_xlsx_resource_limits_are_fixed() -> None:
    assert MAX_WORKBOOK_BYTES == 50 * 1024 * 1024 == 52_428_800
    assert MAX_ZIP_ENTRIES == 2_048
    assert MAX_ENTRY_UNCOMPRESSED_BYTES == 128 * 1024 * 1024 == 134_217_728
    assert MAX_TOTAL_UNCOMPRESSED_BYTES == 256 * 1024 * 1024
    assert MAX_CENTRAL_DIRECTORY_BYTES == 4 * 1024 * 1024


def test_exact_fifty_mib_valid_xlsx_is_accepted(tmp_path: Path) -> None:
    path = _build_exact_size_xlsx(tmp_path / "exact-limit.xlsx", MAX_WORKBOOK_BYTES)

    result = validate_customer_upload_workbook(path)

    assert result.record_count == 1


def test_fifty_mib_plus_one_byte_reports_exact_capacity_diagnostic(
    tmp_path: Path,
) -> None:
    path = _build_exact_size_xlsx(
        tmp_path / "over-limit.xlsx", MAX_WORKBOOK_BYTES + 1
    )

    with pytest.raises(CustomerUploadValidationError) as caught:
        validate_customer_upload_workbook(path)

    assert caught.value.code == "upload_too_large"
    assert caught.value.reason == "workbook_bytes"
    assert caught.value.limit == MAX_WORKBOOK_BYTES
    assert caught.value.observed == MAX_WORKBOOK_BYTES + 1
    assert caught.value.measurement == "exact"
    assert caught.value.unit == "bytes"
    assert caught.value.__cause__ is None
    assert str(path) not in str(caught.value)


def test_declared_member_boundary_is_exact_at_128_mib(tmp_path: Path) -> None:
    path = tmp_path / "declared-member.xlsx"
    with ZipFile(path, "w", compression=ZIP_STORED) as archive:
        archive.writestr("fixture/member.bin", b"x")

    _patch_declared_uncompressed_size(path, MAX_ENTRY_UNCOMPRESSED_BYTES)
    _check_central_directory(path)

    _patch_declared_uncompressed_size(path, MAX_ENTRY_UNCOMPRESSED_BYTES + 1)
    with pytest.raises(PreflightError) as caught:
        _check_central_directory(path)

    assert caught.value.code == "workbook_resource_limit"
    assert caught.value.reason == "workbook_member_bytes"
    assert caught.value.limit == MAX_ENTRY_UNCOMPRESSED_BYTES
    assert caught.value.observed == MAX_ENTRY_UNCOMPRESSED_BYTES + 1
    assert caught.value.measurement == "declared"
    assert caught.value.unit == "bytes"


def test_xlsx_near_limit_static_image_is_accepted(tmp_path: Path) -> None:
    path = build_xlsx_fixture("near_request_limit", tmp_path / "static-image.xlsx")

    result = validate_customer_upload_workbook(path)

    assert result.record_count == 3
    assert result.warnings == ()


@pytest.mark.parametrize(
    "fixture_name",
    ["entry_count_bomb", "compression_bomb", "total_size_bomb"],
)
def test_xlsx_zip_bombs_have_one_stable_rejection(
    tmp_path: Path, fixture_name: str
) -> None:
    path = build_xlsx_fixture(fixture_name, tmp_path / "bomb.xlsx")

    _assert_rejected(path, "workbook_resource_limit")


def test_zip_resource_limit_stops_before_later_malformed_entry(
    tmp_path: Path,
) -> None:
    path = build_xlsx_fixture("compression_bomb", tmp_path / "bomb.xlsx")
    with ZipFile(path, "a", compression=ZIP_DEFLATED) as archive:
        archive.writestr("../after-limit", b"fixture")

    _assert_rejected(path, "workbook_resource_limit")


@pytest.mark.parametrize(
    "fixture_name",
    [
        "formula",
        "relocated_formula_without_content_type",
        "padded_relocated_formula",
        "table_formula",
        "conditional_format_formula",
        "data_validation_formula",
        "external_link",
        "data_connection",
        "hidden_sheet",
        "hidden_chartsheet",
        "visible_chartsheet",
        "embedded_object",
        "vml_button",
    ],
)
def test_xlsx_active_content_has_one_stable_rejection(
    tmp_path: Path, fixture_name: str
) -> None:
    path = build_xlsx_fixture(fixture_name, tmp_path / "active.xlsx")

    formula_row = (
        2
        if fixture_name
        in {
            "formula",
            "relocated_formula_without_content_type",
            "padded_relocated_formula",
        }
        else None
    )
    _assert_rejected(
        path, "unsupported_workbook_feature", row=formula_row
    )


def test_preflight_rejection_preserves_field_without_calling_openpyxl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = build_xlsx_fixture(
        "relocated_formula_without_content_type", tmp_path / "formula.xlsx"
    )
    _rewrite_zip_member(
        path,
        "xl/fixture/worksheet.dat",
        lambda data: _move_formula_to_responsibility_field(data, "utf-16"),
    )
    openpyxl_calls = 0

    def unexpected_openpyxl_call(*_args: object, **_kwargs: object) -> None:
        nonlocal openpyxl_calls
        openpyxl_calls += 1

    monkeypatch.setattr(
        "app.domain.customer_upload_validator.load_workbook",
        unexpected_openpyxl_call,
    )

    _assert_rejected(
        path,
        "unsupported_workbook_feature",
        field="service_type",
        row=2,
    )
    assert openpyxl_calls == 0


def test_macro_enabled_main_content_type_is_rejected_before_openpyxl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _save_workbook(
        tmp_path / "macro-type.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.1", 443, 443, "否", None]],
    )
    _rewrite_zip_member(
        path,
        "[Content_Types].xml",
        lambda data: data.replace(
            b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
            b"application/vnd.ms-excel.sheet.macroEnabled.main+xml",
        ),
    )
    openpyxl_calls = 0

    def unexpected_openpyxl_call(*_args: object, **_kwargs: object) -> None:
        nonlocal openpyxl_calls
        openpyxl_calls += 1

    monkeypatch.setattr(
        "app.domain.customer_upload_validator.load_workbook",
        unexpected_openpyxl_call,
    )

    _assert_rejected(path, "unsupported_workbook_feature")
    assert openpyxl_calls == 0


def test_utf16_undeclared_worksheet_formula_is_rejected(tmp_path: Path) -> None:
    path = build_xlsx_fixture(
        "relocated_formula_without_content_type", tmp_path / "utf16-formula.xlsx"
    )
    _rewrite_zip_member(
        path,
        "xl/fixture/worksheet.dat",
        lambda data: _move_formula_to_responsibility_field(data, "utf-16"),
    )

    _assert_rejected(
        path,
        "unsupported_workbook_feature",
        field="service_type",
        row=2,
    )


def test_defined_name_formula_is_rejected(tmp_path: Path) -> None:
    path = _save_workbook(
        tmp_path / "defined-name-formula.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.1", 443, 443, "否", None]],
    )
    _rewrite_zip_member(
        path,
        "xl/workbook.xml",
        lambda data: data.replace(
            b"</workbook>",
            (
                b'<definedNames><definedName name="FixtureFormula">'
                b"OFFSET(Sheet!$A$1,0,0)</definedName></definedNames></workbook>"
            ),
        ),
    )

    _assert_rejected(path, "unsupported_workbook_feature")


def test_declared_dimensions_do_not_control_parser_iteration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _save_workbook(
        tmp_path / "inflated-dimensions.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.1", 443, 443, "否", None]],
    )
    _rewrite_zip_member(
        path,
        "xl/worksheets/sheet1.xml",
        lambda data: re.sub(
            rb'<dimension ref="[^"]*"',
            b'<dimension ref="A1:XFD2000"',
            data,
            count=1,
        ),
    )

    original_iter_rows = ReadOnlyWorksheet.iter_rows
    observed_bounds: list[tuple[int | None, int | None]] = []

    def iter_rows_with_bounds(
        self: ReadOnlyWorksheet, *args: Any, **kwargs: Any
    ) -> Any:
        observed_bounds.append((kwargs.get("max_row"), kwargs.get("max_col")))
        return original_iter_rows(self, *args, **kwargs)

    monkeypatch.setattr(ReadOnlyWorksheet, "iter_rows", iter_rows_with_bounds)

    result = validate_customer_upload_workbook(path)

    assert result.record_count == 1
    assert observed_bounds == [(2, len(DEFAULT_HEADERS))]


def test_sparse_valid_row_outside_audit_rectangle_is_accepted(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sparse-valid-row.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    headers = [*DEFAULT_HEADERS, *(f"Extra {index}" for index in range(10))]
    for column, header in enumerate(headers, start=1):
        worksheet.cell(row=1, column=column, value=header)
    values: list[object] = [
        "192.0.2.1",
        443,
        443,
        "否",
        None,
        "Service",
        "Owner",
        "Department",
        "Port Owner",
        "Operations",
        *range(10),
    ]
    for column, value in enumerate(values, start=1):
        worksheet.cell(row=100_001, column=column, value=value)
    workbook.save(path)
    workbook.close()

    result = validate_customer_upload_workbook(path)

    assert result.record_count == 1
    assert result.warnings == (
        CustomerUploadWarning("extra_columns_ignored", None, 10),
    )


def test_sparse_data_without_a_header_is_rejected_at_header_row(
    tmp_path: Path,
) -> None:
    path = _save_workbook(
        tmp_path / "sparse-cell.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.1", 443, 443, "否", None]],
    )
    _rewrite_zip_member(
        path,
        "xl/worksheets/sheet1.xml",
        lambda data: data.replace(
            b"</sheetData>",
            b'<row r="2000"><c r="XFD2000" t="n"><v>1</v></c></row></sheetData>',
        ),
    )

    _assert_rejected(path, "missing_required_structure", row=1)


def test_actual_file_size_over_fifty_mib_is_rejected_first(tmp_path: Path) -> None:
    path = tmp_path / "oversized.xlsx"
    with path.open("wb") as oversized:
        oversized.seek(MAX_WORKBOOK_BYTES)
        oversized.write(b"x")

    _assert_rejected(
        path, "upload_too_large", reason="workbook_bytes"
    )


def test_malformed_rejection_does_not_expose_path_or_parser_details(
    tmp_path: Path,
) -> None:
    path = tmp_path / "customer-secret-name.xlsx"
    path.write_bytes(b"not an XLSX: 192.0.2.123")

    with pytest.raises(CustomerUploadValidationError) as caught:
        validate_customer_upload_workbook(path)

    assert caught.value.code == "malformed_workbook"
    assert caught.value.field is None
    assert caught.value.row is None
    assert caught.value.diagnostic.code == "malformed_workbook"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    public_text = str(caught.value)
    assert "customer-secret-name" not in public_text
    assert "192.0.2.123" not in public_text
    assert "XLSX" not in public_text


def test_invalid_value_rejection_has_no_raw_exception_chain(tmp_path: Path) -> None:
    path = _save_workbook(
        tmp_path / "value.xlsx",
        [DEFAULT_HEADERS, ["customer-secret.example", 443, 443, "否", None]],
    )

    with pytest.raises(CustomerUploadValidationError) as caught:
        validate_customer_upload_workbook(path)

    assert caught.value.code == "invalid_required_value"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
