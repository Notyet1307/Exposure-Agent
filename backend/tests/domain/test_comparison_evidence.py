import json
import uuid
from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from app.domain.comparison_evidence import (
    ReportV2EvidenceBundle,
    comparison_evidence_id,
    select_comparison_evidence,
)
from app.domain.evidence_selector import EvidenceBundle, select_evidence
from app.domain.ip_source_comparison import comparison_fact_id
from app.domain.report_candidates import (
    CanonicalReportV2,
    ReportCandidateError,
    ReportV2,
    generate_report_candidate,
)
from tests.domain.report_candidate_fixtures import ORACLE_MODES, RUN_ID, case_facts

VERSION = "deterministic-report-v2"


def _reference(row: dict[str, Any]) -> dict[str, Any]:
    # Independent oracle: stdlib UUIDv5 over the exact Issue #177 names, not helpers.
    return {
        "coverage": "IP_SOURCE_COMPARISON",
        "resource_id": row["resource_id"],
        "canonical_ip": row["canonical_ip"],
        "evidence_reference": {
            "governance_run_id": str(RUN_ID),
            "fact_type": "IP_SOURCE_COMPARISON",
            "fact_id": str(
                uuid.uuid5(RUN_ID, f"ip-source-comparison/v1/{row['canonical_ip']}")
            ),
            "content_hash": row["content_hash"],
        },
    }


@pytest.mark.parametrize("count", [0, 1, 8, 9, 50, 51, 100, 101])
@pytest.mark.parametrize("mode", ["absent", "unobserved"])
def test_separate_governance_and_comparison_budgets(count: int, mode: str) -> None:
    facts = case_facts(mode, resource_count=count)
    candidate = generate_report_candidate(facts, VERSION)
    assert isinstance(candidate.report, ReportV2)
    bundle = candidate.evidence_plan
    assert isinstance(bundle, ReportV2EvidenceBundle)
    assert (
        bundle.entries
        == select_evidence(facts.evidence, "deterministic-report-v1").entries
    )
    payload = json.loads(candidate.rendered.canonical_json)
    assert set(payload["evidence_plan"]) == {
        "governance_run_id",
        "report_contract_version",
        "max_entries",
        "entries",
        "comparison_entries",
    }
    assert bundle.max_entries == 100
    assert payload["evidence_plan"]["comparison_entries"] == [
        _reference(row.model_dump(mode="json")) for row in facts.comparison.results[:50]
    ]
    assert len(bundle.entries) == (min(count, 50) if mode == "unobserved" else 0)
    assert len(bundle.comparison_entries) == min(count, 50)
    for metadata in (
        candidate.report.bounded_evidence_examples,
        candidate.report.bounded_comparison_evidence_examples,
    ):
        assert metadata.model_dump() == {
            "selection_owner": "EVIDENCE_SELECTOR",
            "max_selected_entries": 50,
            "max_rendered_entries": 8,
        }
    html = candidate.rendered.html.decode()
    assert html.count('class="evidence-card"') == (
        min(count, 8) if mode == "unobserved" else 0
    )
    assert html.count('class="comparison-evidence-card"') == min(count, 8)
    section = html.split('<section id="comparison-evidence-examples">')[1].split(
        "</section>"
    )[0]
    assert "href=" not in section
    assert (
        f"总比较数：{count}；入选 Evidence 数：{min(count, 50)}；实际展示数：{min(count, 8)}"
        in section
    )
    assert (
        f"选择截断：{'是' if count > 50 else '否'}；展示截断：{'是' if count > 8 else '否'}"
        in section
    )
    assert "待绑定文字引用" in section
    for row in facts.comparison.results[:8]:
        assert row.canonical_ip in section
        assert row.classification in section
        assert row.classification_reason in section
        assert row.netflow_status in section
        assert row.netflow_reason in section
        assert row.content_hash in section
    if count > 8:
        assert facts.comparison.results[8].content_hash not in section
    table = html.split('<section id="ip-source-comparison">')[1].split("</section>")[0]
    assert table.count("<td>") == min(count, 100) * 9
    assert len(payload["report"]["ip_source_comparison"]["results"]) == count
    assert candidate.rendered.csv.count(b"\r\n") == count + 1


@pytest.mark.parametrize("mode", ORACLE_MODES)
def test_stable_identity_does_not_change_comparison_or_csv(mode: str) -> None:
    facts = case_facts(mode)
    entries = select_comparison_evidence(facts.comparison)
    report_id = uuid.UUID(int=99)
    for index, (entry, row) in enumerate(
        zip(entries, facts.comparison.results, strict=True)
    ):
        fact_id = uuid.uuid5(RUN_ID, f"ip-source-comparison/v1/{row.canonical_ip}")
        assert comparison_fact_id(RUN_ID, row.canonical_ip) == fact_id
        assert entry.model_dump() == _reference(row.model_dump(mode="json"))
        assert comparison_evidence_id(report_id, index, fact_id) == uuid.uuid5(
            report_id, f"{index}:IP_SOURCE_COMPARISON:{fact_id}"
        )
        assert comparison_fact_id(uuid.UUID(int=4), row.canonical_ip) != fact_id
    candidate = generate_report_candidate(facts, VERSION)
    assert isinstance(candidate.report, ReportV2)
    assert candidate.report.ip_source_comparison == facts.comparison
    assert "IP_SOURCE_COMPARISON" not in candidate.rendered.csv.decode()


@pytest.mark.parametrize("index", [50, 100])
@pytest.mark.parametrize(
    "field,value",
    [
        ("content_hash", "0" * 64),
        ("classification", "matched"),
        ("customer_upload_present", 1),
    ],
)
def test_unselected_comparison_rows_are_validated(
    index: int, field: str, value: object
) -> None:
    facts = case_facts("unobserved", resource_count=101)
    rows = list(facts.comparison.results)
    rows[index] = rows[index].model_copy(update={field: value})
    damaged = facts.comparison.model_copy(update={"results": tuple(rows)})
    with pytest.raises(ValueError):
        select_comparison_evidence(damaged)
    payload = facts.model_dump(mode="json")
    payload["comparison"]["results"][index][field] = value
    with pytest.raises(ReportCandidateError, match="^report_facts_invalid$"):
        generate_report_candidate(payload, VERSION)


@pytest.mark.parametrize("count", [0, 101])
def test_output_hash_is_validated_even_without_selected_rows(count: int) -> None:
    comparison = case_facts("absent", resource_count=count).comparison
    with pytest.raises(ValueError):
        select_comparison_evidence(
            comparison.model_copy(update={"output_hash": "0" * 64})
        )


def _bundle() -> dict[str, Any]:
    bundle = generate_report_candidate(
        case_facts("present-active"), VERSION
    ).evidence_plan
    assert isinstance(bundle, ReportV2EvidenceBundle)
    return bundle.model_dump(mode="json")


@pytest.mark.parametrize(
    "field,value",
    [
        ("coverage", "OPEN_BACKLOG"),
        ("resource_id", str(uuid.UUID(int=4)).replace("-", "")),
        ("resource_id", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"),
        ("resource_id", " " + str(uuid.UUID(int=4))),
        ("resource_id", 4),
        ("canonical_ip", "::ffff:192.0.2.1"),
        ("canonical_ip", "2001:0db8::1"),
        ("canonical_ip", "999.0.0.1"),
        ("canonical_ip", "192.0.2.1 "),
        ("url", "https://example.invalid/raw"),
        ("finding_id", str(uuid.UUID(int=4))),
    ],
)
def test_comparison_entry_rejects_invalid_fields(field: str, value: object) -> None:
    bundle = _bundle()
    bundle["comparison_entries"][0][field] = value
    with pytest.raises(ValidationError):
        ReportV2EvidenceBundle.model_validate(bundle)


@pytest.mark.parametrize(
    "field,value",
    [
        ("governance_run_id", "00000000-0000-0000-0000-000000000003 "),
        ("governance_run_id", str(uuid.UUID(int=9))),
        ("fact_type", "SOURCE_SNAPSHOT"),
        ("fact_id", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"),
        ("fact_id", str(uuid.UUID(int=9))),
        ("content_hash", "A" * 64),
        ("content_hash", "a" * 63),
        ("content_hash", "a" * 65),
        ("content_hash", 1),
        ("locator", "./evidence/raw"),
    ],
)
def test_reference_rejects_invalid_fields(field: str, value: object) -> None:
    bundle = _bundle()
    bundle["comparison_entries"][0]["evidence_reference"][field] = value
    with pytest.raises(ValidationError):
        ReportV2EvidenceBundle.model_validate(bundle)


@pytest.mark.parametrize("level", ["bundle", "entry", "reference"])
def test_every_comparison_field_is_required(level: str) -> None:
    original = _bundle()
    for key in (
        original
        if level == "bundle"
        else original["comparison_entries"][0]
        if level == "entry"
        else original["comparison_entries"][0]["evidence_reference"]
    ):
        bundle = deepcopy(original)
        target = bundle if level == "bundle" else bundle["comparison_entries"][0]
        if level == "reference":
            target = target["evidence_reference"]
        del target[key]
        with pytest.raises(ValidationError):
            ReportV2EvidenceBundle.model_validate(bundle)


@pytest.mark.parametrize(
    "mutation",
    ["duplicate", "missing", "reverse", "hash", "resource", "governance", "extra"],
)
def test_canonical_plan_must_match_validated_facts(mutation: str) -> None:
    payload = json.loads(
        generate_report_candidate(
            case_facts("present-active"), VERSION
        ).rendered.canonical_json
    )
    plan = payload["evidence_plan"]
    entries = plan["comparison_entries"]
    if mutation == "duplicate":
        entries.append(entries[0])
    elif mutation == "missing":
        entries.pop()
    elif mutation == "reverse":
        entries.reverse()
    elif mutation == "hash":
        entries[0]["evidence_reference"]["content_hash"] = "0" * 64
    elif mutation == "resource":
        entries[0]["resource_id"] = str(uuid.UUID(int=9))
    elif mutation == "governance":
        plan["entries"][0]["canonical_ip"] = "192.0.2.99"
    else:
        plan["raw"] = {}
    with pytest.raises(ValidationError):
        CanonicalReportV2.model_validate(payload)


@pytest.mark.parametrize("group", ["entries", "comparison_entries"])
def test_groups_cannot_borrow_unused_capacity(group: str) -> None:
    payload = json.loads(
        generate_report_candidate(
            case_facts("unobserved", resource_count=51), VERSION
        ).rendered.canonical_json
    )
    plan = payload["evidence_plan"]
    if group == "comparison_entries":
        plan[group].append(
            _reference(payload["report"]["ip_source_comparison"]["results"][50])
        )
        plan["entries"] = []
    else:
        entry = deepcopy(plan[group][-1])
        entry["finding_id"] = str(uuid.UUID(int=2051))
        entry["canonical_ip"] = "192.0.2.51"
        entry["evidence_reference"]["fact_id"] = str(uuid.UUID(int=3051))
        plan[group].append(entry)
        plan["comparison_entries"] = []
    with pytest.raises(ValidationError):
        ReportV2EvidenceBundle.model_validate(plan)


def test_v1_dispatch_and_target_allowlist_stay_separate() -> None:
    facts = case_facts("absent")
    v1 = generate_report_candidate(facts, "deterministic-report-v1")
    assert isinstance(v1.evidence_plan, EvidenceBundle)
    assert v1.evidence_plan == select_evidence(
        facts.evidence, "deterministic-report-v1"
    )
    assert b"comparison_entries" not in v1.rendered.canonical_json
    assert b"bounded_comparison_evidence_examples" not in v1.rendered.canonical_json
    payload = v1.evidence_plan.model_dump()
    payload["entries"][0]["evidence_reference"]["fact_type"] = "IP_SOURCE_COMPARISON"
    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate(payload)


@pytest.mark.parametrize("value", [50, 101, 100.0, "100", True, None])
def test_v2_budget_is_exact_and_strict(value: object) -> None:
    payload = _bundle()
    payload["max_entries"] = value
    with pytest.raises(ValidationError):
        ReportV2EvidenceBundle.model_validate(payload)


def test_ipv4_mapped_and_ipv6_identities_follow_existing_numeric_order() -> None:
    from app.domain.ip_consistency import normalize_ip
    from app.domain.ip_source_comparison import compile_ip_source_comparison

    resources = {
        uuid.UUID(int=1004): "2001:db8::10",
        uuid.UUID(int=1003): "2001:db8::2",
        uuid.UUID(int=1002): normalize_ip("::ffff:192.0.2.10"),
        uuid.UUID(int=1001): "192.0.2.2",
    }
    kwargs: dict[str, Any] = {
        "tenant_id": uuid.UUID(int=1),
        "project_id": uuid.UUID(int=2),
        "run_id": RUN_ID,
        "membership": {key: {"CUSTOMER_UPLOAD", "CLOUDATLAS"} for key in resources},
        "active_resources": set(),
        "netflow_present": False,
    }
    comparison = compile_ip_source_comparison(resources=resources, **kwargs)
    reverse = compile_ip_source_comparison(
        resources=dict(reversed(resources.items())), **kwargs
    )
    assert comparison == reverse
    entries = select_comparison_evidence(comparison)
    assert [entry.canonical_ip for entry in entries] == [
        "192.0.2.2",
        "192.0.2.10",
        "2001:db8::2",
        "2001:db8::10",
    ]
    assert [entry.model_dump() for entry in entries] == [
        _reference(row.model_dump(mode="json")) for row in comparison.results
    ]
