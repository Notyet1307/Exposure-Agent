from collections.abc import Callable
from copy import deepcopy
from typing import Any

import pytest

from app.domain.evidence_selector import (
    EVIDENCE_BUNDLE_MAX_ENTRIES,
    EvidenceSelectorError,
    select_evidence,
)
from app.domain.report_core import REPORT_CONTRACT_VERSION

RUN_ID = "run-current"


def _reference(fact_type: str, fact_id: str, run_id: str = RUN_ID) -> dict[str, str]:
    return {
        "governance_run_id": run_id,
        "fact_type": fact_type,
        "fact_id": fact_id,
    }


def _transition(
    finding_id: str,
    finding_type: str,
    canonical_ip: str,
    transition_type: str,
    fact_id: str,
) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "finding_type": finding_type,
        "canonical_ip": canonical_ip,
        "transition_type": transition_type,
        "evidence_reference": _reference("FINDING_TRANSITION", fact_id),
    }


def _backlog(
    finding_id: str,
    finding_type: str,
    canonical_ip: str,
    fact_type: str,
    fact_id: str,
) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "finding_type": finding_type,
        "canonical_ip": canonical_ip,
        "evidence_reference": _reference(fact_type, fact_id),
    }


def _facts() -> dict[str, Any]:
    available = [
        _reference("SOURCE_SNAPSHOT", "snapshot-customer"),
        _reference("SOURCE_SNAPSHOT", "snapshot-cloudatlas"),
    ]
    transitions = [
        _transition(
            "finding-closed",
            "UNREPORTED_ASSET",
            "192.0.2.1",
            "CLOSED",
            "transition-closed",
        ),
        _transition(
            "finding-opened-z",
            "UNREPORTED_ASSET",
            "192.0.2.20",
            "OPENED",
            "transition-opened-z",
        ),
        _transition(
            "finding-opened-a",
            "UNREPORTED_ASSET",
            "192.0.2.10",
            "OPENED",
            "transition-opened-a",
        ),
        _transition(
            "finding-reopened",
            "UNOBSERVED_ASSET",
            "2001:db8::2",
            "REOPENED",
            "transition-reopened",
        ),
    ]
    backlog = [
        _backlog(
            "finding-old-v6",
            "UNOBSERVED_ASSET",
            "2001:db8::10",
            "SOURCE_SNAPSHOT",
            "snapshot-cloudatlas",
        ),
        _backlog(
            "finding-old-v4",
            "UNOBSERVED_ASSET",
            "198.51.100.9",
            "OBSERVATION",
            "observation-old-v4-support",
        ),
        _backlog(
            "finding-opened-a",
            "UNREPORTED_ASSET",
            "192.0.2.10",
            "FINDING_TRANSITION",
            "transition-opened-a",
        ),
    ]
    for candidate in transitions + backlog:
        reference = candidate["evidence_reference"]
        if reference not in available:
            available.append(dict(reference))
    return {
        "governance_run_id": RUN_ID,
        "available_facts": available,
        "current_run_transitions": transitions,
        "open_backlog": backlog,
    }


def test_zero_finding_facts_produce_an_empty_bounded_plan() -> None:
    facts = {
        "governance_run_id": RUN_ID,
        "available_facts": [
            _reference("SOURCE_SNAPSHOT", "snapshot-customer"),
            _reference("SOURCE_SNAPSHOT", "snapshot-cloudatlas"),
        ],
        "current_run_transitions": [],
        "open_backlog": [],
    }

    bundle = select_evidence(facts, REPORT_CONTRACT_VERSION)

    assert bundle.model_dump() == {
        "governance_run_id": RUN_ID,
        "report_contract_version": REPORT_CONTRACT_VERSION,
        "max_entries": 50,
        "entries": (),
    }


def test_transition_coverage_precedes_stably_ordered_open_backlog() -> None:
    bundle = select_evidence(_facts(), REPORT_CONTRACT_VERSION)

    assert [
        (
            entry.coverage,
            entry.finding_type,
            entry.transition_type,
            entry.finding_id,
            entry.evidence_reference.fact_type,
            entry.evidence_reference.fact_id,
        )
        for entry in bundle.entries
    ] == [
        (
            "CURRENT_RUN_TRANSITION",
            "UNREPORTED_ASSET",
            "OPENED",
            "finding-opened-a",
            "FINDING_TRANSITION",
            "transition-opened-a",
        ),
        (
            "CURRENT_RUN_TRANSITION",
            "UNREPORTED_ASSET",
            "CLOSED",
            "finding-closed",
            "FINDING_TRANSITION",
            "transition-closed",
        ),
        (
            "CURRENT_RUN_TRANSITION",
            "UNOBSERVED_ASSET",
            "REOPENED",
            "finding-reopened",
            "FINDING_TRANSITION",
            "transition-reopened",
        ),
        (
            "OPEN_BACKLOG",
            "UNOBSERVED_ASSET",
            None,
            "finding-old-v4",
            "OBSERVATION",
            "observation-old-v4-support",
        ),
        (
            "OPEN_BACKLOG",
            "UNOBSERVED_ASSET",
            None,
            "finding-old-v6",
            "SOURCE_SNAPSHOT",
            "snapshot-cloudatlas",
        ),
    ]


def test_same_facts_in_different_input_order_produce_the_same_plan() -> None:
    facts = _facts()
    reversed_facts = deepcopy(facts)
    reversed_facts["available_facts"].reverse()
    reversed_facts["current_run_transitions"].reverse()
    reversed_facts["open_backlog"].reverse()

    first = select_evidence(facts, REPORT_CONTRACT_VERSION)
    second = select_evidence(reversed_facts, REPORT_CONTRACT_VERSION)

    assert first == second


def test_transition_ties_use_canonical_ip_then_finding_id_not_input_order() -> None:
    facts = _facts()
    tied = _transition(
        "finding-opened-00",
        "UNREPORTED_ASSET",
        "192.0.2.10",
        "OPENED",
        "transition-opened-00",
    )
    facts["current_run_transitions"].insert(0, tied)
    facts["available_facts"].append(tied["evidence_reference"])

    bundle = select_evidence(facts, REPORT_CONTRACT_VERSION)

    assert bundle.entries[0].finding_id == "finding-opened-00"


def test_any_input_scale_is_capped_at_fifty_entries() -> None:
    available: list[dict[str, str]] = []
    backlog: list[dict[str, Any]] = []
    for index in range(1_000):
        fact_id = f"occurrence-{index:04d}"
        available.append(_reference("FINDING_OCCURRENCE", fact_id))
        backlog.append(
            _backlog(
                f"finding-{index:04d}",
                "UNOBSERVED_ASSET",
                f"2001:db8::{index + 1:x}",
                "FINDING_OCCURRENCE",
                fact_id,
            )
        )

    bundle = select_evidence(
        {
            "governance_run_id": RUN_ID,
            "available_facts": available,
            "current_run_transitions": [],
            "open_backlog": backlog,
        },
        REPORT_CONTRACT_VERSION,
    )

    assert len(bundle.entries) == EVIDENCE_BUNDLE_MAX_ENTRIES == 50
    assert bundle.entries[0].finding_id == "finding-0000"
    assert bundle.entries[-1].finding_id == "finding-0049"


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda facts: facts["current_run_transitions"][0][
                "evidence_reference"
            ].update(governance_run_id="run-other"),
            "evidence_reference_out_of_scope",
        ),
        (
            lambda facts: facts["current_run_transitions"][0][
                "evidence_reference"
            ].update(fact_id="transition-missing"),
            "evidence_reference_missing",
        ),
        (
            lambda facts: facts["available_facts"][0].update(fact_type="RAW_ARTIFACT"),
            "evidence_reference_unsupported",
        ),
        (
            lambda facts: facts["current_run_transitions"][0][
                "evidence_reference"
            ].update(fact_type="OBSERVATION"),
            "evidence_reference_unsupported",
        ),
    ],
)
def test_invalid_references_fail_atomically_with_stable_errors(
    mutate: Callable[[dict[str, Any]], object], expected_code: str
) -> None:
    facts = deepcopy(_facts())
    mutate(facts)

    with pytest.raises(EvidenceSelectorError) as caught:
        select_evidence(facts, REPORT_CONTRACT_VERSION)

    assert caught.value.code == expected_code
    assert str(caught.value) == expected_code
    assert not hasattr(caught.value, "partial_plan")


def test_unknown_contract_and_raw_or_risk_fields_are_rejected() -> None:
    with pytest.raises(EvidenceSelectorError) as version_error:
        select_evidence(_facts(), "deterministic-report-v2")
    assert version_error.value.code == "unsupported_report_contract_version"

    facts = _facts()
    facts["open_backlog"][0]["severity"] = "HIGH"
    with pytest.raises(EvidenceSelectorError) as schema_error:
        select_evidence(facts, REPORT_CONTRACT_VERSION)
    assert schema_error.value.code == "fact_schema_invalid"
