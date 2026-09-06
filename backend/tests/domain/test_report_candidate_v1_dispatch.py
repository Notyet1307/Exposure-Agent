from dataclasses import replace
from pathlib import Path

import pytest

from app.domain.evidence_selector import select_evidence
from app.domain.report_candidates import (
    FrozenGovernanceCandidateFacts,
    ReportCandidateError,
    generate_report_candidate,
    validate_report_candidate,
)
from app.domain.report_core import (
    REPORT_CONTRACT_VERSION,
    CanonicalReportCore,
    compile_report_core,
)
from app.domain.report_renderer import render_report
from tests.domain.report_candidate_fixtures import case_facts


def test_minimal_v1_dispatch_retains_original_golden_bytes() -> None:
    facts = FrozenGovernanceCandidateFacts.model_validate(
        {
            "governance": {
                "run_id": "run-current",
                "project_id": "project-1",
                "completed_at": "2026-03-20T12:00:00Z",
                "processing_contract_version": "ip-v1",
                "source_snapshots": [
                    {
                        "source_type": source,
                        "source_snapshot_id": f"snapshot-{digit}",
                        "content_sha256": digit * 64,
                        "schema_version": f"{source.lower()}-v1",
                        "record_count": 1,
                        "complete": True,
                    }
                    for source, digit in (("CUSTOMER_UPLOAD", "a"), ("CLOUDATLAS", "b"))
                ],
                "customer_observed_resource_keys": ["192.0.2.1"],
                "cloudatlas_observed_resource_keys": ["192.0.2.1"],
                "finding_lifecycles": [],
            },
            "evidence": {
                "governance_run_id": "run-current",
                "available_facts": [],
                "current_run_transitions": [],
                "open_backlog": [],
            },
        }
    )
    candidate = generate_report_candidate(facts, REPORT_CONTRACT_VERSION)
    golden = Path(__file__).with_name("golden")
    assert (
        candidate.rendered.canonical_json
        == (golden / "report_renderer_zero.json").read_bytes()
    )
    assert (
        candidate.rendered.html == (golden / "report_renderer_zero.html").read_bytes()
    )
    assert (
        candidate.rendered.csv_sha256
        == "1d416360af82d280b2a8090647173e922ed7e4d7cc52f0f9889a351cbde6f09d"
    )
    validate_report_candidate(facts, candidate)
    assert (
        generate_report_candidate(
            facts.model_dump(mode="python"), REPORT_CONTRACT_VERSION
        )
        == candidate
    )


def test_v1_nonzero_findings_validate_and_keep_complete_csv() -> None:
    rich = case_facts("absent")
    facts = FrozenGovernanceCandidateFacts(
        governance=rich.governance, evidence=rich.evidence
    )
    candidate = generate_report_candidate(facts, REPORT_CONTRACT_VERSION)
    expected = render_report(
        compile_report_core(facts.governance, REPORT_CONTRACT_VERSION),
        select_evidence(facts.evidence, REPORT_CONTRACT_VERSION),
    )
    assert isinstance(candidate.report, CanonicalReportCore)
    assert candidate.report.ip_consistency_summary.current_run_finding_count == 2
    assert len(candidate.evidence_plan.entries) == 2
    assert len(candidate.report.finding_export_rows) == 2
    assert candidate.rendered == expected
    validate_report_candidate(facts, candidate)
    damaged = candidate.model_copy(
        update={"rendered": replace(candidate.rendered, csv=b"changed")}
    )
    with pytest.raises(ReportCandidateError, match="^report_candidate_invalid$"):
        validate_report_candidate(facts, damaged)


@pytest.mark.parametrize(
    "damage", ["missing_activity", "bad_activity_hash", "unsupported_comparison"]
)
def test_v1_rich_input_does_not_validate_irrelevant_v2_proof(damage: str) -> None:
    facts = case_facts("present-active")
    expected = generate_report_candidate(facts, REPORT_CONTRACT_VERSION)
    if damage == "missing_activity":
        damaged = facts.model_copy(update={"netflow_activity": None})
    elif damage == "bad_activity_hash":
        assert facts.netflow_activity is not None
        damaged = facts.model_copy(
            update={
                "netflow_activity": replace(
                    facts.netflow_activity, output_hash="0" * 64
                ),
            }
        )
    else:
        damaged = facts.model_copy(
            update={
                "comparison": facts.comparison.model_copy(
                    update={"contract_version": "unsupported"}
                ),
            }
        )
    assert generate_report_candidate(damaged, REPORT_CONTRACT_VERSION) == expected
    validate_report_candidate(damaged, expected)
    serialized = damaged.model_dump(mode="python")
    assert generate_report_candidate(serialized, REPORT_CONTRACT_VERSION) == expected
    validate_report_candidate(serialized, expected)
    with pytest.raises(ReportCandidateError, match="^report_facts_invalid$"):
        generate_report_candidate(
            {**serialized, "unexpected": True}, REPORT_CONTRACT_VERSION
        )
    error = (
        "comparison_contract_unsupported"
        if damage == "unsupported_comparison"
        else "report_facts_invalid"
    )
    with pytest.raises(ReportCandidateError, match=f"^{error}$"):
        generate_report_candidate(damaged, "deterministic-report-v2")


@pytest.mark.parametrize("field", ["governance", "evidence"])
def test_v1_revalidates_relevant_typed_facts(field: str) -> None:
    facts = case_facts("absent")
    if field == "governance":
        damaged = facts.model_copy(
            update={
                "governance": facts.governance.model_copy(
                    update={"source_snapshots": ()}
                ),
            }
        )
    else:
        damaged = facts.model_copy(
            update={
                "evidence": facts.evidence.model_copy(
                    update={"governance_run_id": "wrong-run"}
                ),
            }
        )
    with pytest.raises(ReportCandidateError, match="^report_facts_invalid$"):
        generate_report_candidate(damaged, REPORT_CONTRACT_VERSION)


@pytest.mark.parametrize("version", [None, "", "deterministic-report-v3"])
def test_v1_dispatch_never_falls_back_for_unknown_version(version: str | None) -> None:
    with pytest.raises(ReportCandidateError, match="^report_contract_unsupported$"):
        generate_report_candidate({}, version)
