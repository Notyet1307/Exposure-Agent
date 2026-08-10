"""Pure, deterministic selection of bounded Run-scoped Evidence references.

The selector consumes a frozen catalog of facts and coverage candidates.  It
never reads those facts, copies source content, ranks risk, or performs I/O.
Validation completes before an immutable plan is returned, so callers can use
exactly the same plan for rendering and later persistence.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from typing import Annotated, Final, Literal, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from app.domain.ip_consistency import IPRecordContractError, normalize_ip
from app.domain.report_core import (
    REPORT_CONTRACT_VERSION,
    FindingType,
    TransitionType,
)

EVIDENCE_BUNDLE_MAX_ENTRIES: Final = 50

EvidenceFactType = Literal[
    "SOURCE_SNAPSHOT",
    "OBSERVATION",
    "FINDING_OCCURRENCE",
    "FINDING_TRANSITION",
]
EvidenceCoverage = Literal["CURRENT_RUN_TRANSITION", "OPEN_BACKLOG"]

_SUPPORTED_FACT_TYPES: Final[tuple[EvidenceFactType, ...]] = (
    "SOURCE_SNAPSHOT",
    "OBSERVATION",
    "FINDING_OCCURRENCE",
    "FINDING_TRANSITION",
)
_FINDING_TYPES: Final[tuple[FindingType, ...]] = (
    "UNREPORTED_ASSET",
    "UNOBSERVED_ASSET",
)
_TRANSITION_TYPES: Final[tuple[TransitionType, ...]] = (
    "OPENED",
    "REOPENED",
    "CLOSED",
)
_FINDING_TYPE_ORDER: Final = {
    value: index for index, value in enumerate(_FINDING_TYPES)
}
_TRANSITION_TYPE_ORDER: Final = {
    value: index for index, value in enumerate(_TRANSITION_TYPES)
}


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("blank string")
    return value


NonEmptyString = Annotated[
    str, Field(min_length=1, max_length=255), AfterValidator(_nonblank)
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceSelectorError(Exception):
    """Stable fail-closed error returned by the Evidence selector seam."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class FrozenEvidenceFactReference(_FrozenModel):
    """Input reference whose type is checked explicitly for stable errors."""

    governance_run_id: NonEmptyString
    fact_type: NonEmptyString
    fact_id: NonEmptyString


class CurrentRunTransitionEvidenceCandidate(_FrozenModel):
    finding_id: NonEmptyString
    finding_type: FindingType
    canonical_ip: NonEmptyString
    transition_type: TransitionType
    evidence_reference: FrozenEvidenceFactReference


class OpenBacklogEvidenceCandidate(_FrozenModel):
    finding_id: NonEmptyString
    finding_type: FindingType
    canonical_ip: NonEmptyString
    evidence_reference: FrozenEvidenceFactReference


class FrozenRunEvidenceFacts(_FrozenModel):
    """Complete current-Run fact catalog and bounded-report coverage inputs."""

    governance_run_id: NonEmptyString
    available_facts: tuple[FrozenEvidenceFactReference, ...]
    current_run_transitions: tuple[CurrentRunTransitionEvidenceCandidate, ...]
    open_backlog: tuple[OpenBacklogEvidenceCandidate, ...]


class EvidenceFactReference(_FrozenModel):
    governance_run_id: str
    fact_type: EvidenceFactType
    fact_id: str


class EvidencePlanEntry(_FrozenModel):
    coverage: EvidenceCoverage
    finding_id: str
    finding_type: FindingType
    canonical_ip: str
    transition_type: TransitionType | None
    evidence_reference: EvidenceFactReference


class EvidenceBundle(_FrozenModel):
    governance_run_id: str
    report_contract_version: str
    max_entries: Literal[50] = EVIDENCE_BUNDLE_MAX_ENTRIES
    entries: tuple[EvidencePlanEntry, ...]


type _Candidate = CurrentRunTransitionEvidenceCandidate | OpenBacklogEvidenceCandidate
type _ReferenceKey = tuple[str, str, str]
type _FindingIdentity = tuple[FindingType, str, str]


def _reference_key(reference: FrozenEvidenceFactReference) -> _ReferenceKey:
    return (
        reference.governance_run_id,
        reference.fact_type,
        reference.fact_id,
    )


def _canonical_ip(value: str) -> str:
    try:
        canonical = normalize_ip(value)
    except IPRecordContractError:
        raise EvidenceSelectorError("fact_schema_invalid") from None
    if canonical != value:
        raise EvidenceSelectorError("fact_schema_invalid")
    return canonical


def _ip_sort_key(value: str) -> tuple[int, int]:
    address = ipaddress.ip_address(value)
    return address.version, int(address)


def _candidate_sort_key(
    candidate: _Candidate,
) -> tuple[int, tuple[int, int], str, str, str]:
    reference = candidate.evidence_reference
    return (
        _FINDING_TYPE_ORDER[candidate.finding_type],
        _ip_sort_key(candidate.canonical_ip),
        candidate.finding_id,
        reference.fact_type,
        reference.fact_id,
    )


def _finding_identity(candidate: _Candidate) -> _FindingIdentity:
    return candidate.finding_type, candidate.canonical_ip, candidate.finding_id


def _validate_reference(
    reference: FrozenEvidenceFactReference,
    *,
    run_id: str,
    available: set[_ReferenceKey],
    required_type: EvidenceFactType | None = None,
) -> None:
    if reference.governance_run_id != run_id:
        raise EvidenceSelectorError("evidence_reference_out_of_scope")
    if reference.fact_type not in _SUPPORTED_FACT_TYPES:
        raise EvidenceSelectorError("evidence_reference_unsupported")
    if required_type is not None and reference.fact_type != required_type:
        raise EvidenceSelectorError("evidence_reference_unsupported")
    if _reference_key(reference) not in available:
        raise EvidenceSelectorError("evidence_reference_missing")


def _validate_facts(facts: FrozenRunEvidenceFacts) -> None:
    available: set[_ReferenceKey] = set()
    for reference in facts.available_facts:
        if reference.governance_run_id != facts.governance_run_id:
            raise EvidenceSelectorError("evidence_reference_out_of_scope")
        if reference.fact_type not in _SUPPORTED_FACT_TYPES:
            raise EvidenceSelectorError("evidence_reference_unsupported")
        key = _reference_key(reference)
        if key in available:
            raise EvidenceSelectorError("fact_schema_invalid")
        available.add(key)

    transition_findings: dict[str, _FindingIdentity] = {}
    transition_references: set[_ReferenceKey] = set()
    for transition_candidate in facts.current_run_transitions:
        _canonical_ip(transition_candidate.canonical_ip)
        _validate_reference(
            transition_candidate.evidence_reference,
            run_id=facts.governance_run_id,
            available=available,
            required_type="FINDING_TRANSITION",
        )
        identity = _finding_identity(transition_candidate)
        if transition_candidate.finding_id in transition_findings:
            raise EvidenceSelectorError("fact_schema_invalid")
        transition_findings[transition_candidate.finding_id] = identity
        reference_key = _reference_key(transition_candidate.evidence_reference)
        if reference_key in transition_references:
            raise EvidenceSelectorError("fact_schema_invalid")
        transition_references.add(reference_key)

    backlog_findings: dict[str, _FindingIdentity] = {}
    for backlog_candidate in facts.open_backlog:
        _canonical_ip(backlog_candidate.canonical_ip)
        _validate_reference(
            backlog_candidate.evidence_reference,
            run_id=facts.governance_run_id,
            available=available,
        )
        identity = _finding_identity(backlog_candidate)
        if backlog_candidate.finding_id in backlog_findings:
            raise EvidenceSelectorError("fact_schema_invalid")
        backlog_findings[backlog_candidate.finding_id] = identity
        transition_identity = transition_findings.get(backlog_candidate.finding_id)
        if transition_identity is not None and transition_identity != identity:
            raise EvidenceSelectorError("fact_schema_invalid")


def _output_reference(
    reference: FrozenEvidenceFactReference,
) -> EvidenceFactReference:
    # _validate_facts has established that this string is one of the Literals.
    fact_type = cast(EvidenceFactType, reference.fact_type)
    return EvidenceFactReference(
        governance_run_id=reference.governance_run_id,
        fact_type=fact_type,
        fact_id=reference.fact_id,
    )


def _plan_entry(
    candidate: _Candidate,
    *,
    coverage: EvidenceCoverage,
) -> EvidencePlanEntry:
    transition_type = (
        candidate.transition_type
        if isinstance(candidate, CurrentRunTransitionEvidenceCandidate)
        else None
    )
    return EvidencePlanEntry(
        coverage=coverage,
        finding_id=candidate.finding_id,
        finding_type=candidate.finding_type,
        canonical_ip=candidate.canonical_ip,
        transition_type=transition_type,
        evidence_reference=_output_reference(candidate.evidence_reference),
    )


def select_evidence(
    frozen_run_facts: FrozenRunEvidenceFacts | Mapping[str, object],
    report_contract_version: str,
) -> EvidenceBundle:
    """Validate frozen facts and return one complete deterministic plan.

    One stable representative is selected for every present Finding-type and
    transition-type pair.  Remaining capacity is filled with open Findings in
    Finding type, canonical IP, and Finding ID order.  A Finding or target
    already represented by transition coverage is not duplicated.
    """

    if report_contract_version != REPORT_CONTRACT_VERSION:
        raise EvidenceSelectorError("unsupported_report_contract_version")
    try:
        facts = (
            frozen_run_facts
            if isinstance(frozen_run_facts, FrozenRunEvidenceFacts)
            else FrozenRunEvidenceFacts.model_validate(frozen_run_facts)
        )
    except ValidationError, TypeError:
        raise EvidenceSelectorError("fact_schema_invalid") from None

    _validate_facts(facts)

    transition_groups: dict[
        tuple[FindingType, TransitionType], list[CurrentRunTransitionEvidenceCandidate]
    ] = {}
    for transition_candidate in facts.current_run_transitions:
        transition_groups.setdefault(
            (
                transition_candidate.finding_type,
                transition_candidate.transition_type,
            ),
            [],
        ).append(transition_candidate)

    selected: list[EvidencePlanEntry] = []
    selected_findings: set[str] = set()
    selected_references: set[_ReferenceKey] = set()
    for coverage_key in sorted(
        transition_groups,
        key=lambda value: (
            _FINDING_TYPE_ORDER[value[0]],
            _TRANSITION_TYPE_ORDER[value[1]],
        ),
    ):
        transition_candidate = min(
            transition_groups[coverage_key], key=_candidate_sort_key
        )
        selected.append(
            _plan_entry(transition_candidate, coverage="CURRENT_RUN_TRANSITION")
        )
        selected_findings.add(transition_candidate.finding_id)
        selected_references.add(_reference_key(transition_candidate.evidence_reference))

    for backlog_candidate in sorted(facts.open_backlog, key=_candidate_sort_key):
        if len(selected) == EVIDENCE_BUNDLE_MAX_ENTRIES:
            break
        reference_key = _reference_key(backlog_candidate.evidence_reference)
        if (
            backlog_candidate.finding_id in selected_findings
            or reference_key in selected_references
        ):
            continue
        selected.append(_plan_entry(backlog_candidate, coverage="OPEN_BACKLOG"))
        selected_findings.add(backlog_candidate.finding_id)
        selected_references.add(reference_key)

    return EvidenceBundle(
        governance_run_id=facts.governance_run_id,
        report_contract_version=report_contract_version,
        entries=tuple(selected),
    )
