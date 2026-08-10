from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from app.domain.report_core import (
    REPORT_CONTRACT_VERSION,
    ReportCoreError,
    compile_report_core,
)

AS_OF = datetime(2026, 3, 20, 12, tzinfo=UTC)
OLDER = datetime(2026, 3, 1, 12, tzinfo=UTC)
OLDEST = datetime(2026, 2, 1, 12, tzinfo=UTC)


def _snapshot(source_type: str, suffix: str, record_count: int) -> dict[str, object]:
    return {
        "source_type": source_type,
        "source_snapshot_id": f"snapshot-{suffix}",
        "content_sha256": suffix * 64,
        "schema_version": f"{source_type.lower()}-v1",
        "record_count": record_count,
        "complete": True,
    }


def _facts() -> dict[str, object]:
    return {
        "run_id": "run-current",
        "project_id": "project-1",
        "completed_at": AS_OF,
        "processing_contract_version": "ip-v1",
        "source_snapshots": [
            _snapshot("CUSTOMER_UPLOAD", "a", 2),
            _snapshot("CLOUDATLAS", "b", 2),
        ],
        "customer_observed_resource_keys": ["192.0.2.1", "2001:db8::1"],
        "cloudatlas_observed_resource_keys": ["192.0.2.1", "2001:db8::1"],
        "finding_lifecycles": [],
    }


def _event(run_id: str, completed_at: datetime) -> dict[str, object]:
    return {"run_id": run_id, "run_completed_at": completed_at}


def test_zero_finding_facts_produce_the_complete_canonical_core() -> None:
    report = compile_report_core(_facts(), REPORT_CONTRACT_VERSION)

    assert report.model_dump(mode="json") == {
        "report_identity": {
            "governance_run_id": "run-current",
            "project_id": "project-1",
            "run_completed_at": "2026-03-20T12:00:00Z",
            "report_contract_version": "deterministic-report-v1",
            "generation_mode": "DETERMINISTIC_TEMPLATE",
        },
        "input_completeness": {
            "complete": True,
            "sources": [
                {
                    "source_type": "CUSTOMER_UPLOAD",
                    "source_snapshot_id": "snapshot-a",
                    "content_sha256": "a" * 64,
                    "schema_version": "customer_upload-v1",
                    "record_count": 2,
                },
                {
                    "source_type": "CLOUDATLAS",
                    "source_snapshot_id": "snapshot-b",
                    "content_sha256": "b" * 64,
                    "schema_version": "cloudatlas-v1",
                    "record_count": 2,
                },
            ],
        },
        "ip_consistency_summary": {
            "customer_observed_asset_count": 2,
            "cloudatlas_observed_asset_count": 2,
            "matched_asset_count": 2,
            "all_observed_ip_identities_matched": True,
            "current_run_finding_count": 0,
            "finding_counts": [
                {"finding_type": "UNREPORTED_ASSET", "count": 0},
                {"finding_type": "UNOBSERVED_ASSET", "count": 0},
            ],
        },
        "current_run_lifecycle_changes": {
            "total": 0,
            "transition_counts": [
                {"transition_type": "OPENED", "count": 0},
                {"transition_type": "REOPENED", "count": 0},
                {"transition_type": "CLOSED", "count": 0},
            ],
            "changes": [],
        },
        "open_backlog_as_of_run": {
            "as_of_governance_run_id": "run-current",
            "total": 0,
            "finding_counts": [
                {"finding_type": "UNREPORTED_ASSET", "count": 0},
                {"finding_type": "UNOBSERVED_ASSET", "count": 0},
            ],
            "findings": [],
        },
        "bounded_evidence_examples": {
            "selection_owner": "EVIDENCE_SELECTOR",
            "max_selected_entries": 50,
            "max_rendered_entries": 8,
        },
        "finding_type_directions_and_limitations": {
            "directions": [
                {
                    "finding_type": "UNREPORTED_ASSET",
                    "present": False,
                    "direction": "向客户系统补充资产记录",
                },
                {
                    "finding_type": "UNOBSERVED_ASSET",
                    "present": False,
                    "direction": "补充扫描目标并重新扫描",
                },
            ],
            "limitations": [
                "未观测资产不表示资产不存在",
                "本报告不分配严重性、优先级、责任、置信度或根因",
                "本报告不构成已批准动作，也不提供资产级处置动作",
            ],
        },
        "provenance": {
            "governance_run_id": "run-current",
            "processing_contract_version": "ip-v1",
            "source_snapshot_ids": ["snapshot-a", "snapshot-b"],
            "source_snapshot_hashes": ["a" * 64, "b" * 64],
            "finding_lifecycle_fact_count": 0,
        },
    }


def test_mixed_and_cross_run_facts_compute_authoritative_as_of_lifecycle() -> None:
    facts = _facts()
    facts["customer_observed_resource_keys"] = ["192.0.2.1", "192.0.2.20"]
    facts["cloudatlas_observed_resource_keys"] = ["192.0.2.1", "192.0.2.10"]
    facts["finding_lifecycles"] = [
        {
            "finding_id": "finding-opened",
            "finding_type": "UNREPORTED_ASSET",
            "canonical_ip": "192.0.2.10",
            "occurrences": [_event("run-current", AS_OF)],
            "transitions": [
                {**_event("run-current", AS_OF), "transition_type": "OPENED"}
            ],
        },
        {
            "finding_id": "finding-reopened",
            "finding_type": "UNOBSERVED_ASSET",
            "canonical_ip": "192.0.2.20",
            "occurrences": [
                _event("run-oldest", OLDEST),
                _event("run-current", AS_OF),
            ],
            "transitions": [
                {**_event("run-oldest", OLDEST), "transition_type": "OPENED"},
                {**_event("run-older", OLDER), "transition_type": "CLOSED"},
                {**_event("run-current", AS_OF), "transition_type": "REOPENED"},
            ],
        },
        {
            "finding_id": "finding-closed",
            "finding_type": "UNREPORTED_ASSET",
            "canonical_ip": "192.0.2.1",
            "occurrences": [_event("run-oldest", OLDEST)],
            "transitions": [
                {**_event("run-oldest", OLDEST), "transition_type": "OPENED"},
                {**_event("run-current", AS_OF), "transition_type": "CLOSED"},
            ],
        },
        {
            "finding_id": "finding-old-backlog",
            "finding_type": "UNOBSERVED_ASSET",
            "canonical_ip": "198.51.100.99",
            "occurrences": [_event("run-oldest", OLDEST)],
            "transitions": [
                {**_event("run-oldest", OLDEST), "transition_type": "OPENED"}
            ],
        },
    ]

    report = compile_report_core(facts, REPORT_CONTRACT_VERSION)

    assert report.ip_consistency_summary.matched_asset_count == 1
    assert [
        item.model_dump() for item in report.ip_consistency_summary.finding_counts
    ] == [
        {"finding_type": "UNREPORTED_ASSET", "count": 1},
        {"finding_type": "UNOBSERVED_ASSET", "count": 1},
    ]
    assert [
        item.transition_type for item in report.current_run_lifecycle_changes.changes
    ] == [
        "CLOSED",
        "OPENED",
        "REOPENED",
    ]
    assert [
        item.count for item in report.current_run_lifecycle_changes.transition_counts
    ] == [
        1,
        1,
        1,
    ]
    assert [item.finding_id for item in report.open_backlog_as_of_run.findings] == [
        "finding-opened",
        "finding-reopened",
        "finding-old-backlog",
    ]
    assert report.open_backlog_as_of_run.total == 3
    assert [item.count for item in report.open_backlog_as_of_run.finding_counts] == [
        1,
        2,
    ]
    assert all(
        direction.present
        for direction in report.finding_type_directions_and_limitations.directions
    )


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda facts: facts.update(
                source_snapshots=[_snapshot("CUSTOMER_UPLOAD", "a", 2)]
            ),
            "run_facts_inconsistent",
        ),
        (
            lambda facts: facts.update(
                customer_observed_resource_keys=["192.0.2.1", "192.0.2.1"]
            ),
            "run_facts_inconsistent",
        ),
        (
            lambda facts: facts.update(completed_at=datetime(2026, 3, 20, 12)),
            "fact_schema_invalid",
        ),
    ],
)
def test_invalid_schema_or_run_facts_return_only_a_stable_error(
    mutate: Callable[[dict[str, object]], object], expected_code: str
) -> None:
    facts = deepcopy(_facts())
    mutate(facts)

    with pytest.raises(ReportCoreError) as caught:
        compile_report_core(facts, REPORT_CONTRACT_VERSION)

    assert caught.value.code == expected_code
    assert str(caught.value) == expected_code


def test_inconsistent_lifecycle_and_future_as_of_facts_fail_atomically() -> None:
    facts = _facts()
    facts["finding_lifecycles"] = [
        {
            "finding_id": "finding-future",
            "finding_type": "UNREPORTED_ASSET",
            "canonical_ip": "192.0.2.10",
            "occurrences": [_event("run-future", datetime(2026, 4, 1, tzinfo=UTC))],
            "transitions": [
                {
                    **_event("run-future", datetime(2026, 4, 1, tzinfo=UTC)),
                    "transition_type": "OPENED",
                }
            ],
        }
    ]

    with pytest.raises(ReportCoreError) as caught:
        compile_report_core(facts, REPORT_CONTRACT_VERSION)

    assert caught.value.code == "as_of_relation_invalid"
    assert not hasattr(caught.value, "partial_model")


def test_current_run_differences_must_equal_occurrence_and_transition_facts() -> None:
    facts = _facts()
    facts["cloudatlas_observed_resource_keys"] = [
        "192.0.2.1",
        "192.0.2.10",
        "2001:db8::1",
    ]
    facts["source_snapshots"] = [
        _snapshot("CUSTOMER_UPLOAD", "a", 2),
        _snapshot("CLOUDATLAS", "b", 3),
    ]

    with pytest.raises(ReportCoreError) as caught:
        compile_report_core(facts, REPORT_CONTRACT_VERSION)

    assert caught.value.code == "finding_lifecycle_invalid"


def test_canonical_output_has_no_asset_governance_decision_fields() -> None:
    payload = compile_report_core(_facts(), REPORT_CONTRACT_VERSION).model_dump()
    prohibited = {
        "severity",
        "priority",
        "responsibility",
        "confidence",
        "root_cause",
        "asset_action",
    }

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {
                nested_key
                for nested_value in value.values()
                for nested_key in keys(nested_value)
            }
        if isinstance(value, (list, tuple)):
            return {
                nested_key
                for nested_value in value
                for nested_key in keys(nested_value)
            }
        return set()

    assert keys(payload).isdisjoint(prohibited)


def test_unknown_report_contract_and_extra_governance_fields_are_rejected() -> None:
    with pytest.raises(ReportCoreError) as version_error:
        compile_report_core(_facts(), "deterministic-report-v2")
    assert version_error.value.code == "unsupported_report_contract_version"

    facts = _facts()
    facts["severity"] = "HIGH"
    with pytest.raises(ReportCoreError) as schema_error:
        compile_report_core(facts, REPORT_CONTRACT_VERSION)
    assert schema_error.value.code == "fact_schema_invalid"
