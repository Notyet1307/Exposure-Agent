import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from openpyxl import Workbook  # type: ignore[import-untyped]

from app.domain.ip_consistency import (
    CLOUDATLAS_SNAPSHOT_SCHEMA,
    IP_PROCESSING_CONTRACT_VERSION,
    IPRecordContractError,
    normalize_ip,
    process_ip_snapshots,
)

DEFAULT_HEADERS = [
    "资产IP",
    "起始端口",
    "结束端口",
    "是否web界面",
    "web界面url",
]


def _write_workbook(path: Path, rows: Sequence[Sequence[object]]) -> Path:
    workbook = Workbook()
    worksheet = workbook.active
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    workbook.close()
    return path


def _write_cloudatlas(path: Path, pages: list[dict[str, object]]) -> Path:
    path.write_text(
        json.dumps(
            {"pages": pages, "schema": CLOUDATLAS_SNAPSHOT_SCHEMA},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _page(
    items: list[dict[str, str]], *, page: int = 1, size: int = 200, total: int | None = None
) -> dict[str, object]:
    return {
        "items": items,
        "page": page,
        "size": size,
        "total": len(items) if total is None else total,
    }


def test_processes_ordered_snapshots_without_collapsing_source_observations(
    tmp_path: Path,
) -> None:
    customer = _write_workbook(
        tmp_path / "customer.xlsx",
        [
            DEFAULT_HEADERS,
            ["192.0.2.10", 443, 443, "否", None],
            [" 2001:0db8:0:0:0:0:0:1 ", "22", "22", "否", None],
            ["192.0.2.10", 80, 80, "否", None],
        ],
    )
    cloudatlas = _write_cloudatlas(
        tmp_path / "cloudatlas.json",
        [
            _page(
                [
                    {"id": "cloud-1", "ip": "::ffff:192.0.2.10", "status": "valid"},
                    {"id": "cloud-2", "ip": "203.0.113.5", "status": "valid"},
                    {"id": "cloud-3", "ip": "203.0.113.5", "status": "valid"},
                ],
                total=3,
            )
        ],
    )

    result = process_ip_snapshots(customer, cloudatlas)

    assert result.processing_contract_version == IP_PROCESSING_CONTRACT_VERSION
    assert [
        (item.source_type, item.source_record_key, item.raw_ip, item.canonical_ip)
        for item in result.observations
    ] == [
        ("CUSTOMER_UPLOAD", "row:2", "192.0.2.10", "192.0.2.10"),
        (
            "CUSTOMER_UPLOAD",
            "row:3",
            " 2001:0db8:0:0:0:0:0:1 ",
            "2001:db8::1",
        ),
        ("CUSTOMER_UPLOAD", "row:4", "192.0.2.10", "192.0.2.10"),
        ("CLOUDATLAS", "page:1:item:0", "::ffff:192.0.2.10", "192.0.2.10"),
        ("CLOUDATLAS", "page:1:item:1", "203.0.113.5", "203.0.113.5"),
        ("CLOUDATLAS", "page:1:item:2", "203.0.113.5", "203.0.113.5"),
    ]
    assert result.observations[3].cloudatlas_asset_id == "cloud-1"
    assert result.observations[3].cloudatlas_status == "valid"
    assert result.observations[0].cloudatlas_asset_id is None

    assert [resource.canonical_key for resource in result.resources] == [
        "192.0.2.10",
        "203.0.113.5",
        "2001:db8::1",
    ]
    assert [link.resource_key for link in result.links] == [
        "192.0.2.10",
        "2001:db8::1",
        "192.0.2.10",
        "192.0.2.10",
        "203.0.113.5",
        "203.0.113.5",
    ]
    assert all(
        link.processing_contract_version == IP_PROCESSING_CONTRACT_VERSION
        for link in result.links
    )

    assert result.differences.customer_upload_only == ("2001:db8::1",)
    assert result.differences.cloudatlas_only == ("203.0.113.5",)
    assert result.differences.matched == ("192.0.2.10",)
    assert len(result.resources) == 3
    assert len(result.links) == len(result.observations)


def test_zero_record_cloudatlas_snapshot_is_a_valid_input(tmp_path: Path) -> None:
    customer = _write_workbook(
        tmp_path / "customer.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.10", 443, 443, "否", None]],
    )
    cloudatlas = _write_cloudatlas(
        tmp_path / "cloudatlas.json", [_page([], total=0)]
    )

    result = process_ip_snapshots(customer, cloudatlas)

    assert len(result.observations) == 1
    assert result.differences.customer_upload_only == ("192.0.2.10",)
    assert result.differences.cloudatlas_only == ()
    assert result.differences.matched == ()


@pytest.mark.parametrize(
    ("items", "code", "source_record_key"),
    [
        (
            [{"id": "cloud-1", "ip": "not-an-ip", "status": "valid"}],
            "invalid_ip",
            "page:1:item:0",
        ),
        (
            [{"id": "cloud-1", "ip": "192.0.2.10", "status": "stale"}],
            "invalid_status",
            "page:1:item:0",
        ),
    ],
)
def test_invalid_complete_snapshot_record_returns_no_partial_result(
    tmp_path: Path,
    items: list[dict[str, str]],
    code: str,
    source_record_key: str,
) -> None:
    customer = _write_workbook(
        tmp_path / "customer.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.10", 443, 443, "否", None]],
    )
    cloudatlas = _write_cloudatlas(
        tmp_path / "cloudatlas.json", [_page(items, total=len(items))]
    )

    with pytest.raises(IPRecordContractError) as caught:
        process_ip_snapshots(customer, cloudatlas)

    assert caught.value.code == code
    assert caught.value.source_type == "CLOUDATLAS"
    assert caught.value.source_record_key == source_record_key
    assert str(caught.value) == code


def test_invalid_customer_ip_is_a_stable_contract_error(tmp_path: Path) -> None:
    customer = _write_workbook(
        tmp_path / "customer.xlsx",
        [DEFAULT_HEADERS, ["example.invalid", 443, 443, "否", None]],
    )
    cloudatlas = _write_cloudatlas(
        tmp_path / "cloudatlas.json", [_page([], total=0)]
    )

    with pytest.raises(IPRecordContractError) as caught:
        process_ip_snapshots(customer, cloudatlas)

    assert caught.value.code == "invalid_required_value"
    assert caught.value.source_type == "CUSTOMER_UPLOAD"
    assert caught.value.source_record_key == "row:2"
    assert caught.value.row == 2
    assert caught.value.field == "asset_ip"
    assert str(caught.value) == "invalid_required_value"


def test_only_standard_mapped_ipv6_is_collapsed() -> None:
    assert normalize_ip("::ffff:192.0.2.10") == "192.0.2.10"
    assert normalize_ip("::FFFF:C000:020A") == "192.0.2.10"
    assert normalize_ip("::c000:020a") == "::c000:20a"

    with pytest.raises(IPRecordContractError) as caught:
        normalize_ip("192.0.2.10/32")
    assert caught.value.code == "invalid_ip"
    assert str(caught.value) == "invalid_ip"


def test_same_order_and_processing_version_have_the_same_hash(tmp_path: Path) -> None:
    customer = _write_workbook(
        tmp_path / "customer.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.10", 443, 443, "否", None]],
    )
    cloudatlas = _write_cloudatlas(
        tmp_path / "cloudatlas.json",
        [_page([{"id": "cloud-1", "ip": "192.0.2.10", "status": "valid"}])],
    )

    first = process_ip_snapshots(
        customer, cloudatlas, processing_contract_version="ip-v1"
    )
    second = process_ip_snapshots(
        customer, cloudatlas, processing_contract_version="ip-v1"
    )
    different_version = process_ip_snapshots(
        customer, cloudatlas, processing_contract_version="ip-v2"
    )

    assert first.output_hash == second.output_hash
    assert first.output_hash != different_version.output_hash
    assert len(first.output_hash) == 64


def test_record_contract_does_not_infer_endpoints_or_keep_unconfirmed_fields(
    tmp_path: Path,
) -> None:
    customer = _write_workbook(
        tmp_path / "customer.xlsx",
        [
            [*DEFAULT_HEADERS, "服务类型", "资产负责人"],
            ["192.0.2.10", 443, 443, "是", "https://example.invalid", "web", "owner"],
        ],
    )
    cloudatlas = _write_cloudatlas(
        tmp_path / "cloudatlas.json",
        [_page([{"id": "cloud-1", "ip": "192.0.2.10", "status": "valid"}])],
    )

    result = process_ip_snapshots(customer, cloudatlas)

    assert result.observations[0].as_dict() == {
        "source_type": "CUSTOMER_UPLOAD",
        "source_record_key": "row:2",
        "raw_ip": "192.0.2.10",
        "canonical_ip": "192.0.2.10",
    }
    assert result.observations[1].as_dict() == {
        "source_type": "CLOUDATLAS",
        "source_record_key": "page:1:item:0",
        "raw_ip": "192.0.2.10",
        "canonical_ip": "192.0.2.10",
        "cloudatlas_asset_id": "cloud-1",
        "cloudatlas_status": "valid",
    }
    assert "endpoint" not in result.observations[0].as_dict()
    assert "port" not in result.observations[0].as_dict()


def test_invalid_snapshot_envelope_is_stable_and_does_not_emit_output(
    tmp_path: Path,
) -> None:
    customer = _write_workbook(
        tmp_path / "customer.xlsx",
        [DEFAULT_HEADERS, ["192.0.2.10", 443, 443, "否", None]],
    )
    cloudatlas = tmp_path / "cloudatlas.json"
    cloudatlas.write_text(
        json.dumps(
            {
                "pages": [
                    _page(
                        [
                            {
                                "id": "cloud-1",
                                "ip": "192.0.2.10",
                                "status": "valid",
                            }
                        ],
                        total=2,
                    )
                ],
                "schema": CLOUDATLAS_SNAPSHOT_SCHEMA,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(IPRecordContractError) as caught:
        process_ip_snapshots(customer, cloudatlas)

    assert caught.value.code == "snapshot_incomplete"
    assert caught.value.source_type == "CLOUDATLAS"
    assert caught.value.source_record_key is None
    assert str(caught.value) == "snapshot_incomplete"
