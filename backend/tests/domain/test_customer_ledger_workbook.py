import uuid
from pathlib import Path
from typing import cast

import pytest
from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]

from app.core.config import settings
from app.domain import customer_ledger as ledger
from app.domain import customer_upload_validator
from app.domain.customer_ledger import Cell, FieldName, LedgerEntry
from app.domain.customer_upload_validator import CustomerUploadValidationError
from app.domain.diagnostics import Diagnostic


def _entry(
    position: int,
    start_port: int = 10_001,
    *,
    archived: bool = False,
    service_type: str | None = None,
) -> LedgerEntry:
    return LedgerEntry(
        entry_id=uuid.uuid4(),
        position=position,
        canonical_ip="192.0.2.1",
        fields=cast(
            dict[FieldName, Cell],
            {
                "asset_ip": "192.0.2.1",
                "start_port": start_port,
                "end_port": 10_002,
                "is_web": "否",
                "web_url": None,
                "service_type": service_type,
            },
        ),
        archived=archived,
    )


def test_whole_workbook_limit_has_no_ledger_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(customer_upload_validator, "MAX_WORKBOOK_BYTES", 1)
    rows = [_entry(2), _entry(3, archived=True), _entry(7)]

    with pytest.raises(ledger.LedgerError) as rejection:
        ledger._write_workbook(rows)

    diagnostic = rejection.value.diagnostic
    assert diagnostic.code == "ledger_fields_invalid"
    assert diagnostic.row is None
    assert diagnostic.column is None
    assert diagnostic.location == "ledger"
    assert diagnostic.reason == "workbook_bytes"
    assert diagnostic.limit == 1
    assert diagnostic.observed is not None and diagnostic.observed > 1
    assert diagnostic.measurement == "exact"
    assert diagnostic.unit == "bytes"
    assert list(tmp_path.glob("*.xlsx")) == []


@pytest.mark.parametrize("position", [2, 7])
def test_row_local_rejection_keeps_the_exact_ledger_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, position: int
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    rows = [
        _entry(2, start_port=0 if position == 2 else 10_001),
        _entry(3, archived=True),
        _entry(7, start_port=0 if position == 7 else 10_001),
    ]

    with pytest.raises(ledger.LedgerError) as rejection:
        ledger._write_workbook(rows)

    diagnostic = rejection.value.diagnostic
    assert diagnostic.code == "ledger_fields_invalid"
    assert diagnostic.row == position
    assert diagnostic.column is None
    assert diagnostic.field == "start_port"
    assert diagnostic.reason == "port_out_of_range"
    assert diagnostic.location == "ledger"
    assert diagnostic.limit == 65_535
    assert diagnostic.unit == "port_number"


def test_in_row_illegal_character_keeps_the_exact_ledger_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    rows = [_entry(2, service_type="bad\x01value"), _entry(7)]

    with pytest.raises(ledger.LedgerError) as rejection:
        ledger._write_workbook(rows)

    diagnostic = rejection.value.diagnostic
    assert rejection.value.code == "ledger_fields_invalid"
    assert rejection.value.status == 422
    assert diagnostic.row == 2
    assert diagnostic.column is None
    assert diagnostic.location == "ledger"
    assert diagnostic.reason == "unsupported_character"
    assert list(tmp_path.glob("*.xlsx")) == []


@pytest.mark.parametrize("error_type", [ValueError, TypeError, OverflowError])
def test_save_stage_failure_has_no_ledger_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    rows = [_entry(2), _entry(7)]

    def fail_save(_workbook: object, _path: Path) -> None:
        raise error_type("injected save failure")

    monkeypatch.setattr(Workbook, "save", fail_save)

    with pytest.raises(ledger.LedgerError) as rejection:
        ledger._write_workbook(rows)

    diagnostic = rejection.value.diagnostic
    assert rejection.value.code == "ledger_fields_invalid"
    assert rejection.value.status == 422
    assert diagnostic.row is None
    assert diagnostic.column is None
    assert diagnostic.location == "ledger"
    assert diagnostic.reason == "unsupported_cell_value"
    assert list(tmp_path.glob("*.xlsx")) == []


@pytest.mark.parametrize(
    ("worksheet_row", "expected"),
    [(1, None), (2, 2), (3, 4), (4, 7), (5, None)],
)
def test_post_save_worksheet_row_maps_only_when_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    worksheet_row: int,
    expected: int | None,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)

    def reject(_path: Path) -> None:
        raise CustomerUploadValidationError(
            "invalid_required_value",
            diagnostic=Diagnostic(
                code="invalid_required_value",
                field="asset_ip",
                row=worksheet_row,
                column=1,
                reason="invalid_ip",
                location="worksheet",
            ),
        )

    monkeypatch.setattr(ledger, "validate_customer_upload_workbook", reject)
    rows = [_entry(2), _entry(3, archived=True), _entry(4), _entry(7)]

    with pytest.raises(ledger.LedgerError) as rejection:
        ledger._write_workbook(rows)

    diagnostic = rejection.value.diagnostic
    assert diagnostic.code == "ledger_fields_invalid"
    assert diagnostic.row == expected
    assert diagnostic.column is None
    assert diagnostic.field == "asset_ip"
    assert diagnostic.reason == "invalid_ip"
    assert diagnostic.location == "ledger"


def _typed_entry(
    position: int,
    *,
    archived: bool = False,
    **values: Cell,
) -> LedgerEntry:
    entry = _entry(position, archived=archived)
    entry.fields.update(cast(dict[FieldName, Cell], values))
    return entry


def _write_and_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rows: list[LedgerEntry],
) -> tuple[Path, Workbook]:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    path = ledger._write_workbook(rows)
    return path, load_workbook(path, read_only=False, data_only=False)


def test_text_values_are_written_as_literals_in_fixed_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        _typed_entry(
            1,
            start_port=10_001,
            end_port=10_002,
            service_type="=SUM(A1:A2)",
            asset_owner="+1",
            asset_department="-1",
            port_owner="@external",
            department="#N/A",
            serial="容量验收修订",
        )
    ]

    _path, workbook = _write_and_load(tmp_path, monkeypatch, rows)

    sheet = workbook.worksheets[0]
    assert [cell.value for cell in sheet[1]] == list(ledger.HEADERS)
    assert all(cell.data_type == "s" for cell in sheet[1])
    row = list(sheet[2])
    assert [cell.value for cell in row] == [
        "192.0.2.1",
        10_001,
        10_002,
        "否",
        None,
        "=SUM(A1:A2)",
        "+1",
        "-1",
        "@external",
        "#N/A",
        "容量验收修订",
    ]
    assert row[1].data_type == "n"
    assert row[2].data_type == "n"
    for cell in row:
        if isinstance(cell.value, str):
            assert cell.data_type == "s"
    workbook.close()


def test_empty_and_missing_values_stay_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        _typed_entry(
            1,
            service_type=None,
            asset_owner="",
            asset_department=None,
            port_owner="",
            department=None,
            serial=None,
        )
    ]

    _path, workbook = _write_and_load(tmp_path, monkeypatch, rows)

    row = list(workbook.worksheets[0][2])
    assert [cell.value for cell in row[5:]] == [None, None, None, None, None, None]
    assert all(cell.data_type != "f" for cell in row)
    workbook.close()


def test_archived_rows_at_every_edge_keep_active_row_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        _typed_entry(4, archived=True, service_type="archived-first"),
        _typed_entry(9, service_type="keep-nine"),
        _typed_entry(12, archived=True, service_type="archived-middle"),
        _typed_entry(20, service_type="keep-twenty"),
        _typed_entry(31, archived=True, service_type="archived-last"),
    ]

    _path, workbook = _write_and_load(tmp_path, monkeypatch, rows)

    sheet = workbook.worksheets[0]
    assert sheet.max_row == 3
    assert [cell.value for cell in sheet[2]] == [
        "192.0.2.1",
        10_001,
        10_002,
        "否",
        None,
        "keep-nine",
        None,
        None,
        None,
        None,
        None,
    ]
    assert [cell.value for cell in sheet[3]] == [
        "192.0.2.1",
        10_001,
        10_002,
        "否",
        None,
        "keep-twenty",
        None,
        None,
        None,
        None,
        None,
    ]
    assert ledger._ledger_position_for_worksheet_row(1, rows) is None
    assert ledger._ledger_position_for_worksheet_row(2, rows) == 9
    assert ledger._ledger_position_for_worksheet_row(3, rows) == 20
    assert ledger._ledger_position_for_worksheet_row(4, rows) is None
    workbook.close()
