from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook  # type: ignore[import-untyped]
from probe import (
    MAX_ENTRY_UNCOMPRESSED_BYTES,
    MAX_TOTAL_UNCOMPRESSED_BYTES,
    MAX_ZIP_ENTRIES,
    WorkbookRejected,
    build_fixture,
    inspect_workbook,
    run_probe,
)


def test_fixed_resource_limits_are_the_measured_global_contract() -> None:
    assert MAX_ZIP_ENTRIES == 2_048
    assert MAX_ENTRY_UNCOMPRESSED_BYTES == 64 * 1024 * 1024
    assert MAX_TOTAL_UNCOMPRESSED_BYTES == 256 * 1024 * 1024


@pytest.mark.parametrize(
    ("fixture_name", "reason"),
    [
        ("formula", "formula"),
        ("relocated_formula_without_content_type", "formula"),
        ("table_formula", "formula"),
        ("conditional_format_formula", "formula"),
        ("data_validation_formula", "formula"),
        ("external_link", "external_link"),
        ("data_connection", "data_connection"),
        ("hidden_sheet", "hidden_sheet"),
        ("embedded_object", "embedded_active_object"),
        ("vml_button", "embedded_active_object"),
    ],
)
def test_forbidden_workbook_features_are_reliably_identified(
    tmp_path: Path, fixture_name: str, reason: str
) -> None:
    workbook = build_fixture(fixture_name, tmp_path / f"{fixture_name}.xlsx")

    with pytest.raises(WorkbookRejected) as caught:
        inspect_workbook(workbook)

    assert caught.value.category == "unsupported_workbook_feature"
    assert caught.value.reason == reason


@pytest.mark.parametrize(
    "fixture_name", ["external_link", "data_connection", "embedded_object"]
)
def test_package_features_are_declared_not_orphan_parts(
    tmp_path: Path, fixture_name: str
) -> None:
    workbook = build_fixture(fixture_name, tmp_path / f"{fixture_name}.xlsx")

    with ZipFile(workbook) as archive:
        content_types = archive.read("[Content_Types].xml")
        relationships = b"".join(
            archive.read(name) for name in archive.namelist() if name.endswith(".rels")
        )

    assert b"fixture/" in content_types
    assert b"fixture/" in relationships


def test_vml_button_fixture_contains_legacy_form_control_markup(tmp_path: Path) -> None:
    workbook = build_fixture("vml_button", tmp_path / "vml-button.xlsx")

    with ZipFile(workbook) as archive:
        vml = archive.read("xl/drawings/vmlDrawing1.vml")
        relationships = archive.read("xl/worksheets/_rels/sheet1.xml.rels")

    assert b'ObjectType="Button"' in vml
    assert b"/vmlDrawing" in relationships


def test_vml_button_markup_is_detected_without_vml_declarations(tmp_path: Path) -> None:
    workbook = build_fixture("vml_button", tmp_path / "vml-button.xlsx")
    rewritten = tmp_path / "vml-button-disguised.xlsx"
    with ZipFile(workbook) as source, ZipFile(rewritten, "w") as target:
        for info in source.infolist():
            data = source.read(info)
            if info.filename == "[Content_Types].xml":
                data = data.replace(
                    b"application/vnd.openxmlformats-officedocument.vmlDrawing",
                    b"application/xml",
                )
            elif info.filename == "xl/worksheets/_rels/sheet1.xml.rels":
                data = data.replace(b"/vmlDrawing", b"/drawing")
            target.writestr(info, data)

    with pytest.raises(WorkbookRejected) as caught:
        inspect_workbook(rewritten)

    assert caught.value.category == "unsupported_workbook_feature"
    assert caught.value.reason == "embedded_active_object"


def test_formula_is_found_in_relationship_targeted_non_xml_part(
    tmp_path: Path,
) -> None:
    workbook = build_fixture("relocated_formula", tmp_path / "relocated.xlsx")
    parsed = load_workbook(workbook, read_only=True, data_only=False, keep_links=True)
    assert parsed.worksheets[0]["K2"].value == "=1+1"
    parsed.close()

    with pytest.raises(WorkbookRejected) as caught:
        inspect_workbook(workbook)

    assert caught.value.category == "unsupported_workbook_feature"
    assert caught.value.reason == "formula"


@pytest.mark.parametrize(
    ("fixture_name", "reason"),
    [
        ("entry_count_bomb", "zip_entry_count"),
        ("compression_bomb", "single_entry_uncompressed_size"),
        ("total_size_bomb", "total_uncompressed_size"),
    ],
)
def test_each_resource_bomb_stops_at_the_central_directory(
    tmp_path: Path, fixture_name: str, reason: str
) -> None:
    workbook = build_fixture(fixture_name, tmp_path / f"{fixture_name}.xlsx")

    with pytest.raises(WorkbookRejected) as caught:
        inspect_workbook(workbook)

    assert caught.value.category == "workbook_resource_limit"
    assert caught.value.reason == reason
    assert caught.value.phase == "central_directory"


def test_fixture_bytes_are_reproducible(tmp_path: Path) -> None:
    first = build_fixture("default_v1", tmp_path / "first.xlsx")
    second = build_fixture("default_v1", tmp_path / "second.xlsx")

    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        core_properties = archive.read("docProps/core.xml")
    assert core_properties.count(b"2026-01-01T00:00:00Z") == 2


@pytest.mark.parametrize(
    ("fixture_name", "expected_rows"),
    [
        ("default_v1", 3),
        ("near_request_limit", 3),
        ("row_shared_style_boundary", 50_000),
    ],
)
def test_normal_boundary_fixtures_parse_at_the_public_seam(
    tmp_path: Path, fixture_name: str, expected_rows: int
) -> None:
    workbook = build_fixture(fixture_name, tmp_path / f"{fixture_name}.xlsx")

    result = inspect_workbook(workbook)

    assert result.status == "accepted"
    assert result.rows == expected_rows
    assert result.zip_stats.entries >= 7


def test_probe_has_one_entrypoint_and_leaves_no_temporary_files(tmp_path: Path) -> None:
    report = run_probe(temp_parent=tmp_path, fixture_names=("default_v1",))

    assert report["parser"] == {
        "name": "openpyxl",
        "version": "3.1.5",
        "xml_guard": {
            "name": "defusedxml",
            "version": "0.7.1",
            "openpyxl_enabled": True,
        },
    }
    assert report["fixtures"][0]["status"] == "accepted"
    assert list(tmp_path.iterdir()) == []
    serialized = json.dumps(report, ensure_ascii=False)
    assert str(Path.home()) not in serialized
    assert "token" not in serialized.lower()
