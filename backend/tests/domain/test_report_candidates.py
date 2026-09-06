import uuid
from dataclasses import replace

from app.domain.ip_source_comparison import compile_ip_source_comparison


def test_comparison_projection_preserves_union_order_and_unknown_reason() -> None:
    tenant, project, run = (uuid.UUID(int=value) for value in (1, 2, 3))
    resources = {uuid.UUID(int=4): "192.0.2.10", uuid.UUID(int=5): "192.0.2.2"}
    result = compile_ip_source_comparison(
        tenant_id=tenant,
        project_id=project,
        run_id=run,
        resources=resources,
        membership={uuid.UUID(int=4): {"CUSTOMER_UPLOAD", "CLOUDATLAS"}},
        active_resources={uuid.UUID(int=5)},
        netflow_present=True,
    )
    assert [row.canonical_ip for row in result.results] == ["192.0.2.2", "192.0.2.10"]
    assert [
        (row.classification, row.netflow_status, row.netflow_reason)
        for row in result.results
    ] == [
        ("neither_source_observed", "ACTIVE", "positive_activity_observed"),
        ("matched", "UNKNOWN", "no_positive_activity_evidence"),
    ]


def test_absent_candidate_is_rebuildable_and_rejects_tampering() -> None:
    import pytest

    from app.domain.report_candidates import (
        FrozenReportCandidateFacts,
        ReportCandidateError,
        ReportV2,
        generate_report_candidate,
        validate_report_candidate,
    )

    facts = FrozenReportCandidateFacts.model_validate(
        {
            "governance": {
                "run_id": str(uuid.UUID(int=3)),
                "project_id": str(uuid.UUID(int=2)),
                "completed_at": "2026-09-06T00:00:00Z",
                "processing_contract_version": "ip-v1",
                "source_snapshots": [
                    {
                        "source_type": source,
                        "source_snapshot_id": str(uuid.UUID(int=index)),
                        "content_sha256": digit * 64,
                        "schema_version": "ip-v1",
                        "record_count": 0,
                        "complete": True,
                    }
                    for source, index, digit in (
                        ("CUSTOMER_UPLOAD", 10, "a"),
                        ("CLOUDATLAS", 11, "b"),
                    )
                ],
                "customer_observed_resource_keys": [],
                "cloudatlas_observed_resource_keys": [],
                "finding_lifecycles": [],
            },
            "evidence": {
                "governance_run_id": str(uuid.UUID(int=3)),
                "available_facts": [],
                "current_run_transitions": [],
                "open_backlog": [],
            },
            "comparison": compile_ip_source_comparison(
                tenant_id=uuid.UUID(int=1),
                project_id=uuid.UUID(int=2),
                run_id=uuid.UUID(int=3),
                resources={},
                membership={},
                active_resources=set(),
                netflow_present=False,
            ).model_dump(mode="json"),
            "netflow_snapshot": None,
        }
    )
    candidate = generate_report_candidate(facts, "deterministic-report-v2")
    assert isinstance(candidate.report, ReportV2)
    assert candidate.report.input_capabilities.netflow.status == "NOT_REQUESTED"
    assert candidate.report.ip_source_comparison_summary.resource_count == 0
    assert candidate.rendered.csv.count(b"\r\n") == 1
    assert generate_report_candidate(facts, "deterministic-report-v2") == candidate
    validate_report_candidate(facts, candidate)
    damaged = candidate.model_copy(
        update={"rendered": replace(candidate.rendered, csv=b"changed")}
    )
    with pytest.raises(ReportCandidateError, match="report_candidate_invalid"):
        validate_report_candidate(facts, damaged)
