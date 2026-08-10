from __future__ import annotations

import ast
import csv
import hashlib
import inspect
import io
import textwrap
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

import app.domain.evidence_selector as evidence_selector_module
import app.domain.report_core as report_core_module
from app.domain.evidence_selector import EVIDENCE_BUNDLE_MAX_ENTRIES, select_evidence
from app.domain.report_core import REPORT_CONTRACT_VERSION, compile_report_core
from app.domain.report_renderer import HTML_EVIDENCE_MAX_ENTRIES, render_report

AS_OF = datetime(2026, 3, 20, 12, tzinfo=UTC)
SOURCE_RECORD_COUNT = 10_000
SOURCE_RECORD_COUNT_PER_SIDE = 5_000
MATCHED_RESOURCE_COUNT = 2_500
RESOURCE_COUNT_PER_SIDE = 4_000
FINDING_COUNT_PER_TYPE = 1_500
FINDING_COUNT = FINDING_COUNT_PER_TYPE * 2

# These fingerprints lock bytes rather than an unknown-hardware latency.
EXPECTED_ARTIFACT_FINGERPRINTS = {
    "canonical_json": (
        763_798,
        "d7b368765c4ad10078a1e60d2d779df651840437b7b2662d20b1c60425f9b422",
    ),
    "html": (
        8_174,
        "53d4a0a03f70027020548ba64cca158e5dcc0b731c88e6d26cf2245412b9e7eb",
    ),
    "csv": (
        693_033,
        "76113ceb54286293aedee0981bef0403ebf5c4af9057d9f30b8475df4d8ba71b",
    ),
}


def _ipv4(first_octet: int, index: int) -> str:
    return f"{first_octet}.{index // 256}.{index % 256}.1"


def _resource_keys() -> tuple[list[str], list[str], list[str], list[str]]:
    common = [
        *(_ipv4(10, index) for index in range(2_000)),
        *(f"2001:db8:1::{index + 1:x}" for index in range(500)),
    ]
    customer_only = [
        *(_ipv4(172, index) for index in range(1_000)),
        *(f"2001:db8:2::{index + 1:x}" for index in range(500)),
    ]
    cloudatlas_only = [
        *(_ipv4(192, index) for index in range(1_000)),
        *(f"2001:db8:3::{index + 1:x}" for index in range(500)),
    ]
    return (
        common + customer_only,
        common + cloudatlas_only,
        customer_only,
        cloudatlas_only,
    )


def _event() -> dict[str, object]:
    return {"run_id": "=run-10k<script>", "run_completed_at": AS_OF}


def _finding_id(finding_type: str, index: int) -> str:
    prefix = ("=", "+", "-", "@")[index] if index < 4 else ""
    suffix = "<script>" if index == 0 else ""
    return f"{prefix}{finding_type.lower()}-finding-{index:04d}{suffix}"


def _scale_fixture() -> tuple[dict[str, object], dict[str, object]]:
    customer, cloudatlas, customer_only, cloudatlas_only = _resource_keys()
    lifecycles: list[dict[str, object]] = []
    transition_candidates: list[dict[str, Any]] = []
    backlog_candidates: list[dict[str, Any]] = []
    available_facts: list[dict[str, str]] = []

    for finding_type, keys in (
        ("UNREPORTED_ASSET", cloudatlas_only),
        ("UNOBSERVED_ASSET", customer_only),
    ):
        for index, canonical_ip in enumerate(keys):
            finding_id = _finding_id(finding_type, index)
            fact_id = f"transition-{finding_type.lower()}-{index:04d}"
            if index == 0:
                fact_id += "<evidence>"
            reference = {
                "governance_run_id": "=run-10k<script>",
                "fact_type": "FINDING_TRANSITION",
                "fact_id": fact_id,
            }
            lifecycles.append(
                {
                    "finding_id": finding_id,
                    "finding_type": finding_type,
                    "canonical_ip": canonical_ip,
                    "occurrences": [_event()],
                    "transitions": [{**_event(), "transition_type": "OPENED"}],
                }
            )
            transition = {
                "finding_id": finding_id,
                "finding_type": finding_type,
                "canonical_ip": canonical_ip,
                "transition_type": "OPENED",
                "evidence_reference": reference,
            }
            transition_candidates.append(transition)
            backlog_candidates.append(
                {
                    "finding_id": finding_id,
                    "finding_type": finding_type,
                    "canonical_ip": canonical_ip,
                    "evidence_reference": reference,
                }
            )
            available_facts.append(reference)

    report_facts: dict[str, object] = {
        "run_id": "=run-10k<script>",
        "project_id": "<img src=x onerror=alert(1)>",
        "completed_at": AS_OF,
        "processing_contract_version": "<b>ip-v1</b>",
        "source_snapshots": [
            {
                "source_type": "CUSTOMER_UPLOAD",
                "source_snapshot_id": "<script>snapshot-customer</script>",
                "content_sha256": "a" * 64,
                "schema_version": '" onmouseover="alert(1)',
                "record_count": SOURCE_RECORD_COUNT_PER_SIDE,
                "complete": True,
            },
            {
                "source_type": "CLOUDATLAS",
                "source_snapshot_id": "snapshot-cloudatlas",
                "content_sha256": "b" * 64,
                "schema_version": "cloudatlas-v1",
                "record_count": SOURCE_RECORD_COUNT_PER_SIDE,
                "complete": True,
            },
        ],
        "customer_observed_resource_keys": customer,
        "cloudatlas_observed_resource_keys": cloudatlas,
        "finding_lifecycles": lifecycles,
    }
    evidence_facts: dict[str, object] = {
        "governance_run_id": "=run-10k<script>",
        "available_facts": available_facts,
        "current_run_transitions": transition_candidates,
        "open_backlog": backlog_candidates,
    }
    return report_facts, evidence_facts


def test_10k_report_pipeline_is_exact_bounded_byte_stable_and_safe() -> None:
    report_facts, evidence_facts = _scale_fixture()

    first_report = compile_report_core(report_facts, REPORT_CONTRACT_VERSION)
    first_evidence = select_evidence(evidence_facts, REPORT_CONTRACT_VERSION)
    first = render_report(first_report, first_evidence)
    second_report = compile_report_core(report_facts, REPORT_CONTRACT_VERSION)
    second_evidence = select_evidence(evidence_facts, REPORT_CONTRACT_VERSION)
    second = render_report(second_report, second_evidence)

    summary = first_report.ip_consistency_summary
    assert [
        source.record_count for source in first_report.input_completeness.sources
    ] == [SOURCE_RECORD_COUNT_PER_SIDE, SOURCE_RECORD_COUNT_PER_SIDE]
    assert (
        sum(source.record_count for source in first_report.input_completeness.sources)
        == SOURCE_RECORD_COUNT
    )
    assert summary.customer_observed_asset_count == RESOURCE_COUNT_PER_SIDE
    assert summary.cloudatlas_observed_asset_count == RESOURCE_COUNT_PER_SIDE
    assert summary.matched_asset_count == MATCHED_RESOURCE_COUNT
    assert summary.current_run_finding_count == FINDING_COUNT
    assert [item.count for item in summary.finding_counts] == [
        FINDING_COUNT_PER_TYPE,
        FINDING_COUNT_PER_TYPE,
    ]
    assert first_report.current_run_lifecycle_changes.total == FINDING_COUNT
    assert [
        item.count
        for item in first_report.current_run_lifecycle_changes.transition_counts
    ] == [FINDING_COUNT, 0, 0]
    assert first_report.open_backlog_as_of_run.total == FINDING_COUNT
    assert [
        item.count for item in first_report.open_backlog_as_of_run.finding_counts
    ] == [FINDING_COUNT_PER_TYPE, FINDING_COUNT_PER_TYPE]
    assert len(first_report.finding_export_rows) == FINDING_COUNT

    assert first_report == second_report
    assert first_evidence == second_evidence
    assert first == second
    assert len(first_evidence.entries) == EVIDENCE_BUNDLE_MAX_ENTRIES == 50
    assert (
        len(first_evidence.entries)
        <= first_report.bounded_evidence_examples.max_selected_entries
    )

    artifacts = {
        "canonical_json": first.canonical_json,
        "html": first.html,
        "csv": first.csv,
    }
    assert {
        name: (len(content), hashlib.sha256(content).hexdigest())
        for name, content in artifacts.items()
    } == EXPECTED_ARTIFACT_FINGERPRINTS
    assert first.hashes == {
        name: hashlib.sha256(content).hexdigest() for name, content in artifacts.items()
    }

    html_text = first.html.decode("utf-8")
    assert html_text.count('class="evidence-card"') == HTML_EVIDENCE_MAX_ENTRIES == 8
    assert (
        html_text.count('class="evidence-card"')
        <= first_report.bounded_evidence_examples.max_rendered_entries
    )
    assert "<script>" not in html_text
    assert "<img src=x" not in html_text
    assert "<b>ip-v1</b>" not in html_text
    assert '" onmouseover="' not in html_text
    assert "&lt;script&gt;" in html_text
    assert "&lt;img src=x onerror=alert(1)&gt;" in html_text

    rows = list(csv.DictReader(io.StringIO(first.csv.decode("utf-8"), newline="")))
    assert len(first.csv.splitlines()) == FINDING_COUNT + 1
    assert len(rows) == FINDING_COUNT
    assert all(row["governance_run_id"].startswith("'=run-10k") for row in rows)
    for prefix in "=+-@":
        assert any(row["finding_id"].startswith("'" + prefix) for row in rows)


def _scans_named_collection(node: ast.AST, names: frozenset[str]) -> bool:
    return any(
        (isinstance(child, ast.Name) and child.id in names)
        or (isinstance(child, ast.Attribute) and child.attr in names)
        for child in ast.walk(node)
    )


def _nested_scale_scans(
    function: Callable[..., object], names: frozenset[str]
) -> list[int]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    function_node = tree.body[0]
    assert isinstance(function_node, (ast.FunctionDef, ast.AsyncFunctionDef))
    violations: list[int] = []

    for node in ast.walk(function_node):
        if isinstance(node, (ast.For, ast.AsyncFor)) and _scans_named_collection(
            node.iter, names
        ):
            for statement in node.body:
                for nested in ast.walk(statement):
                    if isinstance(
                        nested, (ast.For, ast.AsyncFor)
                    ) and _scans_named_collection(nested.iter, names):
                        violations.append(nested.lineno)
                    elif isinstance(
                        nested,
                        (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp),
                    ) and any(
                        _scans_named_collection(generator.iter, names)
                        for generator in nested.generators
                    ):
                        violations.append(nested.lineno)

        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            payload: Iterable[ast.AST] = (node.elt,)
        elif isinstance(node, ast.DictComp):
            payload = (node.key, node.value)
        else:
            continue
        scale_generators = [
            generator
            for generator in node.generators
            if _scans_named_collection(generator.iter, names)
        ]
        if not scale_generators:
            continue
        if len(scale_generators) > 1:
            violations.append(node.lineno)
        for value in payload:
            for nested in ast.walk(value):
                if isinstance(
                    nested, (ast.For, ast.AsyncFor)
                ) and _scans_named_collection(nested.iter, names):
                    violations.append(nested.lineno)
                elif (
                    isinstance(
                        nested,
                        (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp),
                    )
                    and nested is not node
                    and any(
                        _scans_named_collection(generator.iter, names)
                        for generator in nested.generators
                    )
                ):
                    violations.append(nested.lineno)

    return violations


def _quadratic_guard_control(
    resources: Iterable[object], findings: Iterable[object]
) -> None:
    for resource in resources:
        for finding in findings:
            if resource == finding:
                return


def test_compiler_and_selector_have_no_nested_full_collection_scans() -> None:
    # Prove that the static guard itself recognizes a direct cross-product scan.
    assert _nested_scale_scans(
        _quadratic_guard_control, frozenset({"resources", "findings"})
    )

    # Static loop-shape evidence is deterministic across hardware. Per-Finding
    # history scans and per-transition-group scans are intentionally excluded:
    # they partition their input and are not Resource x Finding/Evidence scans.
    scan_contracts = (
        (
            report_core_module._validate_run_facts,
            frozenset(
                {
                    "customer",
                    "cloudatlas",
                    "customer_observed_resource_keys",
                    "cloudatlas_observed_resource_keys",
                    "finding_lifecycles",
                }
            ),
        ),
        (
            report_core_module._validated_lifecycles,
            frozenset(
                {
                    "customer",
                    "cloudatlas",
                    "finding_lifecycles",
                    "states",
                    "state_by_identity",
                    "expected_differences",
                }
            ),
        ),
        (
            report_core_module.compile_report_core,
            frozenset(
                {
                    "customer",
                    "cloudatlas",
                    "finding_lifecycles",
                    "states",
                    "open_findings",
                    "changes",
                }
            ),
        ),
        (
            evidence_selector_module._validate_facts,
            frozenset(
                {
                    "available_facts",
                    "current_run_transitions",
                    "open_backlog",
                    "available",
                    "transition_findings",
                    "backlog_findings",
                }
            ),
        ),
        (
            evidence_selector_module.select_evidence,
            frozenset(
                {
                    "available_facts",
                    "current_run_transitions",
                    "open_backlog",
                    "transition_groups",
                }
            ),
        ),
    )

    assert {
        function.__qualname__: _nested_scale_scans(function, names)
        for function, names in scan_contracts
    } == {function.__qualname__: [] for function, _ in scan_contracts}
