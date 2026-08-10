import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.domain.evidence_selector import EvidenceBundle, select_evidence
from app.domain.report_core import (
    REPORT_CONTRACT_VERSION,
    CanonicalReportCore,
    compile_report_core,
)
from app.domain.report_renderer import ReportRendererError, render_report

GOLDEN_DIR = Path(__file__).with_name("golden")
AS_OF = datetime(2026, 3, 20, 12, tzinfo=UTC)
OLDER = datetime(2026, 3, 1, 12, tzinfo=UTC)
OLDEST = datetime(2026, 2, 1, 12, tzinfo=UTC)


def _snapshot(
    source_type: str,
    suffix: str,
    *,
    record_count: int = 1,
    snapshot_id: str | None = None,
    schema_version: str | None = None,
) -> dict[str, object]:
    return {
        "source_type": source_type,
        "source_snapshot_id": snapshot_id or f"snapshot-{suffix}",
        "content_sha256": suffix * 64,
        "schema_version": schema_version or f"{source_type.lower()}-v1",
        "record_count": record_count,
        "complete": True,
    }


def _event(run_id: str, completed_at: datetime) -> dict[str, object]:
    return {"run_id": run_id, "run_completed_at": completed_at}


def _reference(fact_type: str, fact_id: str) -> dict[str, str]:
    return {
        "governance_run_id": "=run<script>",
        "fact_type": fact_type,
        "fact_id": fact_id,
    }


def _zero_report(
    *, completed_at: datetime = AS_OF
) -> tuple[CanonicalReportCore, EvidenceBundle]:
    report = compile_report_core(
        {
            "run_id": "run-current",
            "project_id": "project-1",
            "completed_at": completed_at,
            "processing_contract_version": "ip-v1",
            "source_snapshots": [
                _snapshot("CUSTOMER_UPLOAD", "a"),
                _snapshot("CLOUDATLAS", "b"),
            ],
            "customer_observed_resource_keys": ["192.0.2.1"],
            "cloudatlas_observed_resource_keys": ["192.0.2.1"],
            "finding_lifecycles": [],
        },
        REPORT_CONTRACT_VERSION,
    )
    evidence = select_evidence(
        {
            "governance_run_id": "run-current",
            "available_facts": [],
            "current_run_transitions": [],
            "open_backlog": [],
        },
        REPORT_CONTRACT_VERSION,
    )
    return report, evidence


def _mixed_report() -> tuple[CanonicalReportCore, EvidenceBundle]:
    closed_id = "+CLOSED<tag>"
    opened_id = "=OPEN<script>"
    backlog_id = "-OLD<img>"
    reopened_id = "@REOPEN&"
    report = compile_report_core(
        {
            "run_id": "=run<script>",
            "project_id": "<img src=x onerror=alert(1)>",
            "completed_at": AS_OF,
            "processing_contract_version": "<b>ip-v1</b>",
            "source_snapshots": [
                _snapshot(
                    "CUSTOMER_UPLOAD",
                    "a",
                    record_count=2,
                    snapshot_id="<script>snapshot-customer</script>",
                    schema_version='" onmouseover="alert(1)',
                ),
                _snapshot("CLOUDATLAS", "b", record_count=2),
            ],
            "customer_observed_resource_keys": ["192.0.2.1", "2001:db8::2"],
            "cloudatlas_observed_resource_keys": ["192.0.2.1", "192.0.2.10"],
            "finding_lifecycles": [
                {
                    "finding_id": closed_id,
                    "finding_type": "UNREPORTED_ASSET",
                    "canonical_ip": "192.0.2.1",
                    "occurrences": [_event("run-oldest", OLDEST)],
                    "transitions": [
                        {**_event("run-oldest", OLDEST), "transition_type": "OPENED"},
                        {**_event("=run<script>", AS_OF), "transition_type": "CLOSED"},
                    ],
                },
                {
                    "finding_id": opened_id,
                    "finding_type": "UNREPORTED_ASSET",
                    "canonical_ip": "192.0.2.10",
                    "occurrences": [_event("=run<script>", AS_OF)],
                    "transitions": [
                        {**_event("=run<script>", AS_OF), "transition_type": "OPENED"}
                    ],
                },
                {
                    "finding_id": backlog_id,
                    "finding_type": "UNOBSERVED_ASSET",
                    "canonical_ip": "198.51.100.99",
                    "occurrences": [_event("run-oldest", OLDEST)],
                    "transitions": [
                        {**_event("run-oldest", OLDEST), "transition_type": "OPENED"}
                    ],
                },
                {
                    "finding_id": reopened_id,
                    "finding_type": "UNOBSERVED_ASSET",
                    "canonical_ip": "2001:db8::2",
                    "occurrences": [
                        _event("run-oldest", OLDEST),
                        _event("=run<script>", AS_OF),
                    ],
                    "transitions": [
                        {**_event("run-oldest", OLDEST), "transition_type": "OPENED"},
                        {**_event("run-older", OLDER), "transition_type": "CLOSED"},
                        {
                            **_event("=run<script>", AS_OF),
                            "transition_type": "REOPENED",
                        },
                    ],
                },
            ],
        },
        REPORT_CONTRACT_VERSION,
    )

    transition_candidates = [
        {
            "finding_id": closed_id,
            "finding_type": "UNREPORTED_ASSET",
            "canonical_ip": "192.0.2.1",
            "transition_type": "CLOSED",
            "evidence_reference": _reference(
                "FINDING_TRANSITION", "<transition-closed>"
            ),
        },
        {
            "finding_id": opened_id,
            "finding_type": "UNREPORTED_ASSET",
            "canonical_ip": "192.0.2.10",
            "transition_type": "OPENED",
            "evidence_reference": _reference(
                "FINDING_TRANSITION", "=transition-opened<script>"
            ),
        },
        {
            "finding_id": reopened_id,
            "finding_type": "UNOBSERVED_ASSET",
            "canonical_ip": "2001:db8::2",
            "transition_type": "REOPENED",
            "evidence_reference": _reference(
                "FINDING_TRANSITION", "+transition-reopened"
            ),
        },
    ]
    backlog_candidates = [
        {
            "finding_id": opened_id,
            "finding_type": "UNREPORTED_ASSET",
            "canonical_ip": "192.0.2.10",
            "evidence_reference": transition_candidates[1]["evidence_reference"],
        },
        {
            "finding_id": backlog_id,
            "finding_type": "UNOBSERVED_ASSET",
            "canonical_ip": "198.51.100.99",
            "evidence_reference": _reference("OBSERVATION", "@observation-old"),
        },
        {
            "finding_id": reopened_id,
            "finding_type": "UNOBSERVED_ASSET",
            "canonical_ip": "2001:db8::2",
            "evidence_reference": transition_candidates[2]["evidence_reference"],
        },
    ]
    available = []
    for candidate in transition_candidates + backlog_candidates:
        reference = candidate["evidence_reference"]
        if reference not in available:
            available.append(reference)
    evidence = select_evidence(
        {
            "governance_run_id": "=run<script>",
            "available_facts": available,
            "current_run_transitions": transition_candidates,
            "open_backlog": backlog_candidates,
        },
        REPORT_CONTRACT_VERSION,
    )
    return report, evidence


def test_renderer_returns_complete_byte_stable_zero_finding_artifacts() -> None:
    report, evidence = _zero_report()

    first = render_report(report, evidence)
    second = render_report(report, evidence)

    assert first == second
    assert (
        first.canonical_json == (GOLDEN_DIR / "report_renderer_zero.json").read_bytes()
    )
    assert first.html == (GOLDEN_DIR / "report_renderer_zero.html").read_bytes()
    assert first.canonical_json.startswith(
        b'{"schema_version":"deterministic-report-v1","report":'
    )
    assert first.canonical_json.endswith(
        b',"evidence_plan":{"governance_run_id":"run-current",'
        b'"report_contract_version":"deterministic-report-v1",'
        b'"max_entries":50,"entries":[]}}'
    )
    assert first.csv == (
        b"report_contract_version,governance_run_id,finding_id,canonical_ip,"
        b"finding_type,status_as_of_run,current_run_transition,"
        b"first_occurrence_at,last_occurrence_at,occurrence_count_as_of_run,"
        b"transition_count_as_of_run,evidence_reference,detail_reference\r\n"
    )
    assert first.canonical_json_sha256 == (
        "7cc983edcc31808348d216053bb70ad20c1142aee61b0c59dc0e9d26369c1ca5"
    )
    assert first.html_sha256 == (
        "e730379dd8dc013cfdcc62ca64ab670225966c8d9770f50ba5a37fa9463b1e58"
    )
    assert first.csv_sha256 == (
        "1d416360af82d280b2a8090647173e922ed7e4d7cc52f0f9889a351cbde6f09d"
    )
    assert first.hashes == {
        "canonical_json": hashlib.sha256(first.canonical_json).hexdigest(),
        "html": hashlib.sha256(first.html).hexdigest(),
        "csv": hashlib.sha256(first.csv).hexdigest(),
    }


def test_canonical_json_normalizes_timestamps_and_has_fixed_section_order() -> None:
    report, evidence = _zero_report(
        completed_at=datetime(2026, 3, 20, 20, tzinfo=timezone(timedelta(hours=8)))
    )

    rendered = render_report(report, evidence)

    assert b'"run_completed_at":"2026-03-20T12:00:00Z"' in rendered.canonical_json
    section_names = [
        b'"report_identity":',
        b'"input_completeness":',
        b'"ip_consistency_summary":',
        b'"current_run_lifecycle_changes":',
        b'"open_backlog_as_of_run":',
        b'"bounded_evidence_examples":',
        b'"finding_type_directions_and_limitations":',
        b'"provenance":',
    ]
    positions = [rendered.canonical_json.index(name) for name in section_names]
    assert positions == sorted(positions)


def test_html_escapes_source_text_and_csv_is_exact_deduplicated_and_safe() -> None:
    report, evidence = _mixed_report()

    rendered = render_report(report, evidence)
    html_text = rendered.html.decode("utf-8")

    assert "<script>" not in html_text
    assert "<img src=x" not in html_text
    assert "<b>ip-v1</b>" not in html_text
    assert '" onmouseover="' not in html_text
    assert "&lt;script&gt;" in html_text
    assert "&lt;img src=x onerror=alert(1)&gt;" in html_text
    assert "&lt;b&gt;ip-v1&lt;/b&gt;" in html_text
    assert "&quot; onmouseover=&quot;alert(1)" in html_text
    assert rendered.csv == (
        b"report_contract_version,governance_run_id,finding_id,canonical_ip,finding_type,status_as_of_run,current_run_transition,first_occurrence_at,last_occurrence_at,occurrence_count_as_of_run,transition_count_as_of_run,evidence_reference,detail_reference\r\n"
        b"deterministic-report-v1,'=run<script>,'+CLOSED<tag>,192.0.2.1,UNREPORTED_ASSET,CLOSED,CLOSED,2026-02-01T12:00:00Z,2026-02-01T12:00:00Z,1,2,./evidence/FINDING_TRANSITION/%3Ctransition-closed%3E,./findings/%2BCLOSED%3Ctag%3E?run=%3Drun%3Cscript%3E\r\n"
        b"deterministic-report-v1,'=run<script>,'=OPEN<script>,192.0.2.10,UNREPORTED_ASSET,OPEN,OPENED,2026-03-20T12:00:00Z,2026-03-20T12:00:00Z,1,1,./evidence/FINDING_TRANSITION/%3Dtransition-opened%3Cscript%3E,./findings/%3DOPEN%3Cscript%3E?run=%3Drun%3Cscript%3E\r\n"
        b"deterministic-report-v1,'=run<script>,'-OLD<img>,198.51.100.99,UNOBSERVED_ASSET,OPEN,,2026-02-01T12:00:00Z,2026-02-01T12:00:00Z,1,1,./evidence/OBSERVATION/%40observation-old,./findings/-OLD%3Cimg%3E?run=%3Drun%3Cscript%3E\r\n"
        b"deterministic-report-v1,'=run<script>,'@REOPEN&,2001:db8::2,UNOBSERVED_ASSET,OPEN,REOPENED,2026-02-01T12:00:00Z,2026-03-20T12:00:00Z,2,3,./evidence/FINDING_TRANSITION/%2Btransition-reopened,./findings/%40REOPEN%26?run=%3Drun%3Cscript%3E\r\n"
    )
    assert len(rendered.csv.decode("utf-8").splitlines()) == 5


def test_html_renders_all_fixed_sections_and_at_most_eight_evidence_cards() -> None:
    lifecycles = []
    available = []
    backlog = []
    for index in range(9):
        finding_id = f"finding-{index}"
        canonical_ip = f"198.51.100.{index + 1}"
        lifecycles.append(
            {
                "finding_id": finding_id,
                "finding_type": "UNOBSERVED_ASSET",
                "canonical_ip": canonical_ip,
                "occurrences": [_event("run-oldest", OLDEST)],
                "transitions": [
                    {**_event("run-oldest", OLDEST), "transition_type": "OPENED"}
                ],
            }
        )
        reference = {
            "governance_run_id": "run-current",
            "fact_type": "OBSERVATION",
            "fact_id": f"observation-{index}",
        }
        available.append(reference)
        backlog.append(
            {
                "finding_id": finding_id,
                "finding_type": "UNOBSERVED_ASSET",
                "canonical_ip": canonical_ip,
                "evidence_reference": reference,
            }
        )
    report = compile_report_core(
        {
            "run_id": "run-current",
            "project_id": "project-1",
            "completed_at": AS_OF,
            "processing_contract_version": "ip-v1",
            "source_snapshots": [
                _snapshot("CUSTOMER_UPLOAD", "a", record_count=0),
                _snapshot("CLOUDATLAS", "b", record_count=0),
            ],
            "customer_observed_resource_keys": [],
            "cloudatlas_observed_resource_keys": [],
            "finding_lifecycles": lifecycles,
        },
        REPORT_CONTRACT_VERSION,
    )
    evidence = select_evidence(
        {
            "governance_run_id": "run-current",
            "available_facts": available,
            "current_run_transitions": [],
            "open_backlog": backlog,
        },
        REPORT_CONTRACT_VERSION,
    )

    html_text = render_report(report, evidence).html.decode("utf-8")

    assert html_text.count('<section id="') == 8
    assert html_text.count('class="evidence-card"') == 8
    assert "finding-7" in html_text
    assert "finding-8" not in html_text


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("schema", "report_schema_invalid"),
        ("evidence", "evidence_plan_invalid"),
        ("render", "render_failed"),
        ("hash", "hash_failed"),
    ],
)
def test_any_failure_returns_only_a_stable_error(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected_code: str,
) -> None:
    import app.domain.report_renderer as renderer

    report, evidence = _zero_report()
    report_input: CanonicalReportCore | Mapping[str, object] = report
    evidence_input: EvidenceBundle | Mapping[str, object] = evidence
    if failure == "schema":
        report_input = {"unexpected": "model"}
    elif failure == "evidence":
        evidence_input = evidence.model_copy(update={"governance_run_id": "run-other"})
    elif failure == "render":
        monkeypatch.setattr(renderer, "_render_html", _raise_runtime_error)
    else:
        monkeypatch.setattr(hashlib, "sha256", _raise_runtime_error)

    with pytest.raises(ReportRendererError) as caught:
        render_report(report_input, evidence_input)

    assert caught.value.code == expected_code
    assert str(caught.value) == expected_code
    assert not hasattr(caught.value, "partial_report")


def _raise_runtime_error(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("sensitive internal failure")
