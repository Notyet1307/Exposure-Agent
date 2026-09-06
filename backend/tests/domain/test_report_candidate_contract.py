import csv
import hashlib
import html
import io
import json
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.domain.report_candidates import (
    CanonicalReportV2,
    ReportCandidateError,
    ReportV2,
    generate_report_candidate,
    validate_report_candidate,
)
from tests.domain.report_candidate_fixtures import (
    DUAL_ROWS,
    ORACLE_MODES,
    SEVEN_ROWS,
    case_facts,
    reference_hash,
)

VERSION = "deterministic-report-v2"
GOLDEN_DIR = Path(__file__).with_name("golden")
CSV_COLUMNS = (
    "contract_version",
    "tenant_id",
    "project_id",
    "governance_run_id",
    "resource_id",
    "canonical_ip",
    "customer_upload_present",
    "cloudatlas_present",
    "netflow_status",
    "classification",
    "classification_reason",
    "netflow_reason",
    "content_hash",
)


def _set(payload: dict[str, Any], path: tuple[str | int, ...], value: object) -> None:
    target: Any = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


@pytest.mark.parametrize("mode", ORACLE_MODES)
def test_fixed_oracles_preserve_complete_bytes_hashes_and_governance(mode: str) -> None:
    facts = case_facts(mode)
    candidate = generate_report_candidate(facts, VERSION)
    assert isinstance(candidate.report, ReportV2)
    report = candidate.report
    expected = json.loads((GOLDEN_DIR / "report_candidates_oracles.json").read_text())
    assert report.ip_source_comparison_summary.model_dump() == expected[mode]
    # The fixture's rows and hash preimages are literal #175/#176 examples,
    # independent of the production classification/summary/hash implementation.
    assert report.ip_source_comparison == facts.comparison
    present = mode != "absent"
    active = mode == "present-active"
    capability = report.input_capabilities.netflow
    assert capability.input_state == ("present" if present else "absent")
    assert capability.status == ("COMPLETED" if present else "NOT_REQUESTED")
    assert capability.source_snapshot_id == (uuid.UUID(int=12) if present else None)
    assert capability.positive_activity_resource_count == (
        4 if active else 0 if present else None
    )
    assert capability.capability == "POSITIVE_IP_ACTIVITY"
    assert capability.coverage == "UNKNOWN"
    assert report.input_capabilities.customer_upload.resource_count == (
        4 if active else 2
    )
    assert report.input_capabilities.cloudatlas.resource_count == (4 if active else 2)
    assert [source.source_type for source in report.input_completeness.sources] == (
        ["CUSTOMER_UPLOAD", "CLOUDATLAS", "NETFLOW"]
        if present
        else ["CUSTOMER_UPLOAD", "CLOUDATLAS"]
    )
    assert report.provenance.source_snapshot_ids == tuple(
        str(source.source_snapshot_id) for source in report.input_completeness.sources
    )
    assert report.provenance.source_snapshot_hashes == tuple(
        source.content_sha256 for source in report.input_completeness.sources
    )
    assert report.ip_consistency_summary.current_run_finding_count == (
        4 if active else 2
    )
    assert report.ip_consistency_summary.matched_asset_count == (2 if active else 1)
    assert report.current_run_lifecycle_changes.total == (4 if active else 2)
    assert report.open_backlog_as_of_run.total == (4 if active else 2)
    assert report.provenance.finding_lifecycle_fact_count == (4 if active else 2)
    assert len(candidate.evidence_plan.entries) == (4 if active else 2)
    assert {entry.canonical_ip for entry in candidate.evidence_plan.entries} == (
        {"192.0.2.3", "192.0.2.4", "192.0.2.5", "192.0.2.6"}
        if active
        else {"192.0.2.2", "192.0.2.3"}
    )
    rows = SEVEN_ROWS if active else DUAL_ROWS
    assert [
        (
            row.classification,
            row.classification_reason,
            row.netflow_status,
            row.netflow_reason,
        )
        for row in report.ip_source_comparison.results
    ] == [
        (
            classification,
            reason,
            "ACTIVE" if positive else "UNKNOWN",
            "positive_activity_observed"
            if positive
            else "no_positive_activity_evidence"
            if present
            else "netflow_input_absent",
        )
        for _index, _customer, _cloud, positive, classification, reason in rows
    ]
    hashes = json.loads(
        (GOLDEN_DIR / f"report_candidates_{mode}.sha256.json").read_text()
    )
    for attribute, extension in (
        ("canonical_json", "json"),
        ("html", "html"),
        ("csv", "csv"),
    ):
        output = getattr(candidate.rendered, attribute)
        assert (
            output
            == (GOLDEN_DIR / f"report_candidates_{mode}.{extension}").read_bytes()
        )
        assert getattr(candidate.rendered, f"{attribute}_sha256") == hashes[attribute]
        assert hashlib.sha256(output).hexdigest() == hashes[attribute]
    assert generate_report_candidate(facts, VERSION) == candidate
    validate_report_candidate(facts, candidate)


@pytest.mark.parametrize("mode", ORACLE_MODES)
def test_canonical_encoding_csv_contract_and_unknown_semantics(mode: str) -> None:
    candidate = generate_report_candidate(case_facts(mode), VERSION)
    assert isinstance(candidate.report, ReportV2)
    rendered = candidate.rendered
    payload = json.loads(rendered.canonical_json)
    assert set(payload) == {"schema_version", "report", "evidence_plan"}
    assert rendered.canonical_json == json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert (
        payload["report"]["report_identity"]["run_completed_at"]
        == "2026-09-06T12:00:00Z"
    )
    assert "finding_export_rows" not in payload["report"]
    assert not rendered.csv.startswith(b"\xef\xbb\xbf")
    assert rendered.csv.endswith(b"\r\n")
    assert b"\n" not in rendered.csv.replace(b"\r\n", b"")
    csv_rows = list(csv.reader(io.StringIO(rendered.csv.decode("utf-8"), newline="")))
    assert tuple(csv_rows[0]) == CSV_COLUMNS
    comparison = candidate.report.ip_source_comparison
    expected_rows = []
    for row in comparison.results:
        values = {**comparison.model_dump(mode="json"), **row.model_dump(mode="json")}
        expected_rows.append(
            [
                str(values[column]).lower()
                if isinstance(values[column], bool)
                else str(values[column])
                for column in CSV_COLUMNS
            ]
        )
    assert csv_rows[1:] == expected_rows
    html_text = rendered.html.decode("utf-8")
    for limitation in (
        "matched 仅表示双来源出现",
        "only 仅比较 CustomerUpload/CloudAtlas",
        "UNKNOWN 不表示不存在或无流量",
        "NetFlow 仅提供正向活动",
        "覆盖范围 UNKNOWN",
    ):
        assert limitation in html_text
    for row in comparison.results:
        assert f"<td>{row.netflow_reason}</td>" in html_text
    comparison_section = html_text.split('<section id="ip-source-comparison">', 1)[
        1
    ].split("</section>", 1)[0]
    assert "href=" not in comparison_section
    assert 'class="evidence-card"' not in comparison_section
    assert "<script" not in html_text
    assert 'src="http' not in html_text


@pytest.mark.parametrize("count", [0, 100, 101])
def test_html_limit_does_not_truncate_json_csv_or_summary(count: int) -> None:
    candidate = generate_report_candidate(
        case_facts("absent", resource_count=count), VERSION
    )
    assert isinstance(candidate.report, ReportV2)
    summary = candidate.report.ip_source_comparison_summary
    assert summary.resource_count == count
    assert summary.classification_counts.model_dump() == {
        "matched": count,
        "customer_upload_only": 0,
        "cloudatlas_only": 0,
        "neither_source_observed": 0,
    }
    assert summary.netflow_status_counts.model_dump() == {"ACTIVE": 0, "UNKNOWN": count}
    assert summary.netflow_reason_counts.model_dump() == {
        "positive_activity_observed": 0,
        "netflow_input_absent": count,
        "no_positive_activity_evidence": 0,
    }
    payload = json.loads(candidate.rendered.canonical_json)
    assert len(payload["report"]["ip_source_comparison"]["results"]) == count
    csv_rows = list(csv.DictReader(io.StringIO(candidate.rendered.csv.decode("utf-8"))))
    assert [row["canonical_ip"] for row in csv_rows] == [
        f"192.0.2.{index}" for index in range(1, count + 1)
    ]
    html_text = candidate.rendered.html.decode("utf-8")
    assert (
        f"总条数：{count}；展示条数：{min(count, 100)}；截断：{'是' if count > 100 else '否'}"
        in html_text
    )
    if count:
        assert "<td>192.0.2.100</td>" in html_text
        assert "<td>192.0.2.101</td>" not in html_text
    else:
        assert "本 Run 无可比较的资产" in html_text
        assert candidate.evidence_plan.entries == ()
        comparison = payload["report"]["ip_source_comparison"]
        assert comparison["output_hash"] == reference_hash(
            {key: value for key, value in comparison.items() if key != "output_hash"}
        )


def test_evidence_fifty_and_html_eight_are_independent_of_comparison_hundred() -> None:
    facts = case_facts("unobserved", resource_count=101)
    candidate = generate_report_candidate(facts, VERSION)
    assert isinstance(candidate.report, ReportV2)
    entries = candidate.evidence_plan.entries
    assert candidate.evidence_plan.max_entries == 50
    assert len(entries) == 50
    assert [entry.finding_id for entry in entries] == [
        str(uuid.UUID(int=2000 + index)) for index in range(1, 51)
    ]
    assert entries[0].coverage == "CURRENT_RUN_TRANSITION"
    assert {entry.coverage for entry in entries[1:]} == {"OPEN_BACKLOG"}
    assert len({entry.evidence_reference.fact_id for entry in entries}) == 50
    assert {entry.evidence_reference.fact_type for entry in entries} == {
        "FINDING_TRANSITION"
    }
    assert candidate.report.bounded_evidence_examples.model_dump() == {
        "selection_owner": "EVIDENCE_SELECTOR",
        "max_selected_entries": 50,
        "max_rendered_entries": 8,
    }
    assert candidate.report.current_run_lifecycle_changes.total == 101
    assert candidate.report.open_backlog_as_of_run.total == 101
    assert (
        candidate.report.ip_source_comparison_summary.classification_counts.customer_upload_only
        == 101
    )
    payload = json.loads(candidate.rendered.canonical_json)
    assert len(payload["evidence_plan"]["entries"]) == 50
    assert len(payload["report"]["ip_source_comparison"]["results"]) == 101
    assert candidate.rendered.csv.count(b"\r\n") == 102
    html_text = candidate.rendered.html.decode("utf-8")
    assert html_text.count('class="evidence-card"') == 8
    assert str(uuid.UUID(int=2008)) in html_text
    assert str(uuid.UUID(int=2009)) not in html_text
    assert "<td>192.0.2.100</td>" in html_text
    assert "<td>192.0.2.101</td>" not in html_text


@pytest.mark.parametrize("mode", ["present-active", "unobserved"])
def test_fixed_fact_input_order_does_not_change_bytes_or_evidence(mode: str) -> None:
    facts = case_facts(mode, resource_count=101 if mode == "unobserved" else None)
    expected = generate_report_candidate(facts, VERSION)
    payload = facts.model_dump(mode="json")
    for key in (
        "source_snapshots",
        "customer_observed_resource_keys",
        "cloudatlas_observed_resource_keys",
        "finding_lifecycles",
    ):
        payload["governance"][key].reverse()
    for key in ("available_facts", "current_run_transitions", "open_backlog"):
        payload["evidence"][key].reverse()
    assert generate_report_candidate(payload, VERSION) == expected


def test_source_schema_text_is_escaped_only_in_html() -> None:
    payload = case_facts("present-active").model_dump(mode="json")
    source_text = '<script>alert("来源&")</script>'
    payload["governance"]["source_snapshots"][0]["schema_version"] = source_text
    payload["netflow_snapshot"]["schema_version"] = source_text
    candidate = generate_report_candidate(payload, VERSION)
    html_text = candidate.rendered.html.decode("utf-8")
    assert source_text not in html_text
    assert html.escape(source_text) in html_text
    encoded = json.loads(candidate.rendered.canonical_json)
    assert (
        encoded["report"]["input_completeness"]["sources"][0]["schema_version"]
        == source_text
    )
    assert "来源".encode() in candidate.rendered.canonical_json


@pytest.mark.parametrize("attribute", ["canonical_json", "html", "csv"])
@pytest.mark.parametrize("damage", ["bytes", "hash", "bytes-and-hash"])
def test_validation_rebuilds_each_complete_output(attribute: str, damage: str) -> None:
    facts = case_facts("present-active")
    candidate = generate_report_candidate(facts, VERSION)
    changed = getattr(candidate.rendered, attribute) + b"tampered"
    updates = {}
    if damage != "hash":
        updates[attribute] = changed
    if damage != "bytes":
        updates[f"{attribute}_sha256"] = hashlib.sha256(changed).hexdigest()
    damaged = candidate.model_copy(
        update={"rendered": replace(candidate.rendered, **updates)}
    )
    with pytest.raises(ReportCandidateError, match="^report_candidate_invalid$"):
        validate_report_candidate(facts, damaged)


@pytest.mark.parametrize("part", ["report", "evidence_plan"])
def test_validation_rejects_typed_model_copy_tampering(part: str) -> None:
    facts = case_facts("present-active")
    candidate = generate_report_candidate(facts, VERSION)
    assert isinstance(candidate.report, ReportV2)
    damaged_part: object
    if part == "report":
        damaged_part = candidate.report.model_copy(
            update={
                "ip_source_comparison_summary": candidate.report.ip_source_comparison_summary.model_copy(
                    update={"resource_count": 999}
                ),
            }
        )
    else:
        damaged_part = candidate.evidence_plan.model_copy(update={"entries": ()})
    damaged = candidate.model_copy(update={part: damaged_part})
    with pytest.raises(ReportCandidateError, match="^report_candidate_invalid$"):
        validate_report_candidate(facts, damaged)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("unexpected",), True),
        (("schema_version",), "deterministic-report-v1"),
        (("report", "ip_source_comparison_summary", "resource_count"), -1),
        (("report", "ip_source_comparison_summary", "resource_count"), True),
        (("report", "ip_source_comparison_summary", "resource_count"), float("nan")),
        (("report", "ip_source_comparison_summary", "resource_count"), float("inf")),
        (("report", "ip_source_comparison_summary", "resource_count"), 100),
        (("report", "input_capabilities", "netflow", "coverage"), "COMPLETE"),
        (
            ("report", "ip_source_comparison", "results", 0, "classification_reason"),
            "observed_in_customer_upload_only",
        ),
        (("report", "ip_source_comparison", "results", 0, "content_hash"), "0" * 64),
        (("report", "ip_source_comparison", "output_hash"), "0" * 64),
        (("report", "report_identity", "project_id"), str(uuid.UUID(int=999))),
        (("report", "provenance", "source_snapshot_hashes", 0), "0" * 64),
        (("evidence_plan", "governance_run_id"), str(uuid.UUID(int=999))),
    ],
)
def test_canonical_schema_rejects_invalid_values(
    path: tuple[str | int, ...], value: object
) -> None:
    payload = json.loads(
        generate_report_candidate(
            case_facts("present-active"), VERSION
        ).rendered.canonical_json
    )
    _set(payload, path, value)
    with pytest.raises(ValidationError):
        CanonicalReportV2.model_validate(payload)


@pytest.mark.parametrize(
    "path",
    [
        ("schema_version",),
        ("report", "input_capabilities"),
        ("report", "input_completeness", "complete"),
        ("report", "input_capabilities", "customer_upload", "capability"),
        ("report", "input_capabilities", "cloudatlas", "status"),
        ("report", "input_capabilities", "netflow", "coverage"),
        ("report", "input_capabilities", "netflow", "positive_activity_resource_count"),
    ],
)
def test_canonical_schema_requires_explicit_fields(path: tuple[str, ...]) -> None:
    payload = json.loads(
        generate_report_candidate(case_facts("absent"), VERSION).rendered.canonical_json
    )
    target = payload
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    with pytest.raises(ValidationError):
        CanonicalReportV2.model_validate(payload)


@pytest.mark.parametrize("version", [None, "", "deterministic-report-v3"])
def test_unknown_or_null_version_never_falls_back(version: str | None) -> None:
    with pytest.raises(ReportCandidateError, match="^report_contract_unsupported$"):
        generate_report_candidate(case_facts("absent"), version)


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        (("netflow_activity",), None, "report_facts_invalid"),
        (("netflow_activity", "activities"), [], "report_facts_invalid"),
        (("netflow_activity", "output_hash"), "0" * 64, "report_facts_invalid"),
        (
            ("netflow_activity", "activities", 0, "flow_count"),
            0,
            "report_facts_invalid",
        ),
        (("netflow_activity", "activities", 0, "peer_ips"), [], "report_facts_invalid"),
        (
            ("netflow_activity", "contract_version"),
            "netflow-ip-activity-v99",
            "comparison_contract_unsupported",
        ),
        (
            ("comparison", "contract_version"),
            "ip-source-comparison/v99",
            "comparison_contract_unsupported",
        ),
        (
            ("governance", "processing_contract_version"),
            "unmodeled",
            "comparison_contract_unsupported",
        ),
        (("governance", "run_id"), str(uuid.UUID(int=999)), "report_facts_invalid"),
        (("governance", "project_id"), str(uuid.UUID(int=999)), "report_facts_invalid"),
        (("comparison", "tenant_id"), str(uuid.UUID(int=999)), "report_facts_invalid"),
        (
            ("comparison", "results", 0, "canonical_ip"),
            "::ffff:192.0.2.1",
            "report_facts_invalid",
        ),
        (("governance", "customer_observed_resource_keys"), [], "report_facts_invalid"),
        (("evidence", "available_facts"), [], "report_facts_invalid"),
        (("netflow_snapshot", "source_type"), "CLOUDATLAS", "report_facts_invalid"),
    ],
)
def test_invalid_fixed_facts_fail_instead_of_becoming_unknown(
    path: tuple[str | int, ...],
    value: object,
    code: str,
) -> None:
    payload = case_facts("present-active").model_dump(mode="json")
    _set(payload, path, value)
    with pytest.raises(ReportCandidateError, match=f"^{code}$"):
        generate_report_candidate(payload, VERSION)


def test_empty_activity_collection_requires_full_aggregation_proof() -> None:
    payload = case_facts("present-empty").model_dump(mode="json")
    payload["netflow_activity"] = {"status": "COMPLETED", "activities": []}
    with pytest.raises(ReportCandidateError, match="^report_facts_invalid$"):
        generate_report_candidate(payload, VERSION)


@pytest.mark.parametrize("missing", ["all", "current_run_transitions", "open_backlog"])
def test_existing_governance_evidence_cannot_be_silently_omitted(missing: str) -> None:
    payload = case_facts("absent").model_dump(mode="json")
    keys = (
        ("available_facts", "current_run_transitions", "open_backlog")
        if missing == "all"
        else (missing,)
    )
    for key in keys:
        payload["evidence"][key] = []
    with pytest.raises(ReportCandidateError, match="^report_facts_invalid$"):
        generate_report_candidate(payload, VERSION)


def test_completed_self_flow_without_peers_remains_positive(tmp_path: Path) -> None:
    from app.domain.netflow_activity import aggregate_netflow_ip_activity
    from app.domain.netflow_datasets import parse_netflow_dataset

    facts = case_facts("present-active")
    ips = [
        row.canonical_ip
        for row in facts.comparison.results
        if row.netflow_status == "ACTIVE"
    ]
    raw = tmp_path / "self-flows.csv"
    raw.write_text(
        "IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
        + "".join(f"{ip},{ip},6,443,443\n" for ip in ips)
    )
    parsed = parse_netflow_dataset(raw)
    activity = aggregate_netflow_ip_activity(parsed.normalized_path, ips)
    assert len(activity.activities) == 4
    assert all(
        item.flow_count == 1 and item.peer_ips == () for item in activity.activities
    )
    fixed = facts.model_copy(update={"netflow_activity": activity})
    candidate = generate_report_candidate(fixed, VERSION)
    assert candidate == generate_report_candidate(facts, VERSION)
    validate_report_candidate(fixed, candidate)
