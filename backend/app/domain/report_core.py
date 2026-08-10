"""Pure compiler for the deterministic, as-of-Run report core.

The public compiler consumes only an immutable description of already-frozen
Run publication facts.  It performs no database, artifact, Evidence selection,
or rendering work.  Validation completes before a canonical model is returned,
so callers never receive a partial report core.
"""

from __future__ import annotations

import ipaddress
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from app.domain.ip_consistency import IPRecordContractError, normalize_ip

REPORT_CONTRACT_VERSION: Final = "deterministic-report-v1"
GENERATION_MODE: Final = "DETERMINISTIC_TEMPLATE"

FindingType = Literal["UNREPORTED_ASSET", "UNOBSERVED_ASSET"]
TransitionType = Literal["OPENED", "REOPENED", "CLOSED"]
SourceType = Literal["CUSTOMER_UPLOAD", "CLOUDATLAS"]

_FINDING_TYPES: Final[tuple[FindingType, ...]] = (
    "UNREPORTED_ASSET",
    "UNOBSERVED_ASSET",
)
_TRANSITION_TYPES: Final[tuple[TransitionType, ...]] = (
    "OPENED",
    "REOPENED",
    "CLOSED",
)
_SOURCE_TYPES: Final[tuple[SourceType, ...]] = (
    "CUSTOMER_UPLOAD",
    "CLOUDATLAS",
)
_FINDING_TYPE_ORDER: Final = {
    value: index for index, value in enumerate(_FINDING_TYPES)
}

def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("blank string")
    return value


NonEmptyString = Annotated[
    str, Field(min_length=1, max_length=255), AfterValidator(_nonblank)
]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportCoreError(Exception):
    """Stable fail-closed error returned by the report-core seam."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SourceSnapshotFact(_FrozenModel):
    source_type: SourceType
    source_snapshot_id: NonEmptyString
    content_sha256: Sha256
    schema_version: NonEmptyString
    record_count: Annotated[int, Field(ge=0)]
    complete: bool


class FindingRunFact(_FrozenModel):
    run_id: NonEmptyString
    run_completed_at: datetime

    @field_validator("run_completed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone required")
        return value


class FindingTransitionFact(FindingRunFact):
    transition_type: TransitionType


class FindingLifecycleFact(_FrozenModel):
    finding_id: NonEmptyString
    finding_type: FindingType
    canonical_ip: NonEmptyString
    occurrences: tuple[FindingRunFact, ...]
    transitions: tuple[FindingTransitionFact, ...]


class FrozenRunReportFacts(_FrozenModel):
    """Complete publication facts available as of one immutable Run."""

    run_id: NonEmptyString
    project_id: NonEmptyString
    completed_at: datetime
    processing_contract_version: NonEmptyString
    source_snapshots: tuple[SourceSnapshotFact, ...]
    customer_observed_resource_keys: tuple[NonEmptyString, ...]
    cloudatlas_observed_resource_keys: tuple[NonEmptyString, ...]
    finding_lifecycles: tuple[FindingLifecycleFact, ...]

    @field_validator("completed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone required")
        return value


class ReportIdentity(_FrozenModel):
    governance_run_id: str
    project_id: str
    run_completed_at: datetime
    report_contract_version: str
    generation_mode: Literal["DETERMINISTIC_TEMPLATE"]


class InputSourceSummary(_FrozenModel):
    source_type: SourceType
    source_snapshot_id: str
    content_sha256: str
    schema_version: str
    record_count: int


class InputCompleteness(_FrozenModel):
    complete: Literal[True]
    sources: tuple[InputSourceSummary, ...]


class FindingTypeCount(_FrozenModel):
    finding_type: FindingType
    count: int


class IPConsistencySummary(_FrozenModel):
    customer_observed_asset_count: int
    cloudatlas_observed_asset_count: int
    matched_asset_count: int
    all_observed_ip_identities_matched: bool
    current_run_finding_count: int
    finding_counts: tuple[FindingTypeCount, ...]


class TransitionTypeCount(_FrozenModel):
    transition_type: TransitionType
    count: int


class LifecycleChange(_FrozenModel):
    finding_id: str
    finding_type: FindingType
    canonical_ip: str
    transition_type: TransitionType


class CurrentRunLifecycleChanges(_FrozenModel):
    total: int
    transition_counts: tuple[TransitionTypeCount, ...]
    changes: tuple[LifecycleChange, ...]


class OpenFinding(_FrozenModel):
    finding_id: str
    finding_type: FindingType
    canonical_ip: str


class OpenBacklogAsOfRun(_FrozenModel):
    as_of_governance_run_id: str
    total: int
    finding_counts: tuple[FindingTypeCount, ...]
    findings: tuple[OpenFinding, ...]


class BoundedEvidenceExamples(_FrozenModel):
    """Explicit hand-off boundary; this module never chooses Evidence."""

    selection_owner: Literal["EVIDENCE_SELECTOR"] = "EVIDENCE_SELECTOR"
    max_selected_entries: Literal[50] = 50
    max_rendered_entries: Literal[8] = 8


class FindingTypeDirection(_FrozenModel):
    finding_type: FindingType
    present: bool
    direction: str


class FindingTypeDirectionsAndLimitations(_FrozenModel):
    directions: tuple[FindingTypeDirection, ...]
    limitations: tuple[str, ...]


class Provenance(_FrozenModel):
    governance_run_id: str
    processing_contract_version: str
    source_snapshot_ids: tuple[str, ...]
    source_snapshot_hashes: tuple[str, ...]
    finding_lifecycle_fact_count: int


class CanonicalReportCore(_FrozenModel):
    """The fixed canonical section set for deterministic report generation."""

    report_identity: ReportIdentity
    input_completeness: InputCompleteness
    ip_consistency_summary: IPConsistencySummary
    current_run_lifecycle_changes: CurrentRunLifecycleChanges
    open_backlog_as_of_run: OpenBacklogAsOfRun
    bounded_evidence_examples: BoundedEvidenceExamples
    finding_type_directions_and_limitations: FindingTypeDirectionsAndLimitations
    provenance: Provenance


class _LifecycleState(_FrozenModel):
    fact: FindingLifecycleFact
    status: Literal["OPEN", "CLOSED"]
    current_transition: TransitionType | None


def _canonical_ip(value: str) -> str:
    """Require the already-frozen Resource key to be contract-canonical."""

    try:
        canonical = normalize_ip(value)
    except IPRecordContractError:
        raise ReportCoreError("fact_schema_invalid") from None
    if canonical != value:
        raise ReportCoreError("fact_schema_invalid")
    return canonical


def _ip_sort_key(value: str) -> tuple[int, int]:
    address = ipaddress.ip_address(value)
    return address.version, int(address)


def _finding_sort_key(
    finding_type: FindingType, canonical_ip: str, finding_id: str
) -> tuple[int, tuple[int, int], str]:
    return _FINDING_TYPE_ORDER[finding_type], _ip_sort_key(canonical_ip), finding_id


def _validate_run_facts(facts: FrozenRunReportFacts) -> None:
    if len(facts.source_snapshots) != 2:
        raise ReportCoreError("run_facts_inconsistent")
    sources = {snapshot.source_type: snapshot for snapshot in facts.source_snapshots}
    if (
        set(sources) != set(_SOURCE_TYPES)
        or not all(snapshot.complete for snapshot in facts.source_snapshots)
        or len({snapshot.source_snapshot_id for snapshot in facts.source_snapshots})
        != 2
    ):
        raise ReportCoreError("run_facts_inconsistent")

    customer = facts.customer_observed_resource_keys
    cloudatlas = facts.cloudatlas_observed_resource_keys
    if (
        len(set(customer)) != len(customer)
        or len(set(cloudatlas)) != len(cloudatlas)
        or len(customer) > sources["CUSTOMER_UPLOAD"].record_count
        or len(cloudatlas) > sources["CLOUDATLAS"].record_count
    ):
        raise ReportCoreError("run_facts_inconsistent")
    for canonical_ip in (*customer, *cloudatlas):
        _canonical_ip(canonical_ip)

    ids: set[str] = set()
    identities: set[tuple[FindingType, str]] = set()
    for finding in facts.finding_lifecycles:
        _canonical_ip(finding.canonical_ip)
        identity = (finding.finding_type, finding.canonical_ip)
        if finding.finding_id in ids or identity in identities:
            raise ReportCoreError("finding_lifecycle_invalid")
        ids.add(finding.finding_id)
        identities.add(identity)


def _validate_event_as_of(
    event: FindingRunFact, *, current_run_id: str, completed_at: datetime
) -> None:
    if event.run_id == current_run_id:
        if event.run_completed_at != completed_at:
            raise ReportCoreError("as_of_relation_invalid")
    elif event.run_completed_at >= completed_at:
        raise ReportCoreError("as_of_relation_invalid")


def _lifecycle_state(
    finding: FindingLifecycleFact, *, current_run_id: str, completed_at: datetime
) -> _LifecycleState:
    occurrence_by_run: dict[str, datetime] = {}
    for occurrence in finding.occurrences:
        _validate_event_as_of(
            occurrence, current_run_id=current_run_id, completed_at=completed_at
        )
        if occurrence.run_id in occurrence_by_run:
            raise ReportCoreError("finding_lifecycle_invalid")
        occurrence_by_run[occurrence.run_id] = occurrence.run_completed_at

    transition_by_run: dict[str, FindingTransitionFact] = {}
    for transition in finding.transitions:
        _validate_event_as_of(
            transition, current_run_id=current_run_id, completed_at=completed_at
        )
        if transition.run_id in transition_by_run:
            raise ReportCoreError("finding_lifecycle_invalid")
        transition_by_run[transition.run_id] = transition

    if not occurrence_by_run or not transition_by_run:
        raise ReportCoreError("finding_lifecycle_invalid")

    run_times: dict[str, datetime] = dict(occurrence_by_run)
    for run_id, transition_fact in transition_by_run.items():
        existing = run_times.setdefault(run_id, transition_fact.run_completed_at)
        if existing != transition_fact.run_completed_at:
            raise ReportCoreError("finding_lifecycle_invalid")
    if len(set(run_times.values())) != len(run_times):
        raise ReportCoreError("as_of_relation_invalid")

    status: Literal["OPEN", "CLOSED"] | None = None
    for run_id in sorted(run_times, key=lambda value: run_times[value]):
        has_occurrence = run_id in occurrence_by_run
        run_transition = transition_by_run.get(run_id)
        transition_type = (
            run_transition.transition_type if run_transition is not None else None
        )
        if status is None:
            if not has_occurrence or transition_type != "OPENED":
                raise ReportCoreError("finding_lifecycle_invalid")
            status = "OPEN"
        elif status == "OPEN":
            if transition_type is None:
                if not has_occurrence:
                    raise ReportCoreError("finding_lifecycle_invalid")
            elif transition_type == "CLOSED" and not has_occurrence:
                status = "CLOSED"
            else:
                raise ReportCoreError("finding_lifecycle_invalid")
        elif not has_occurrence or transition_type != "REOPENED":
            raise ReportCoreError("finding_lifecycle_invalid")
        else:
            status = "OPEN"

    assert status is not None
    current_transition = transition_by_run.get(current_run_id)
    return _LifecycleState(
        fact=finding,
        status=status,
        current_transition=(
            current_transition.transition_type
            if current_transition is not None
            else None
        ),
    )


def _validated_lifecycles(
    facts: FrozenRunReportFacts,
    *,
    customer: set[str],
    cloudatlas: set[str],
) -> tuple[_LifecycleState, ...]:
    states = tuple(
        _lifecycle_state(
            finding,
            current_run_id=facts.run_id,
            completed_at=facts.completed_at,
        )
        for finding in facts.finding_lifecycles
    )
    state_by_identity = {
        (state.fact.finding_type, state.fact.canonical_ip): state for state in states
    }
    expected_differences: dict[tuple[FindingType, str], None] = {
        **{("UNREPORTED_ASSET", ip): None for ip in cloudatlas - customer},
        **{("UNOBSERVED_ASSET", ip): None for ip in customer - cloudatlas},
    }
    matched = customer & cloudatlas

    if not set(expected_differences).issubset(state_by_identity):
        raise ReportCoreError("finding_lifecycle_invalid")

    for identity, state in state_by_identity.items():
        current_occurrences = [
            occurrence
            for occurrence in state.fact.occurrences
            if occurrence.run_id == facts.run_id
        ]
        is_difference = identity in expected_differences
        if len(current_occurrences) != int(is_difference):
            raise ReportCoreError("finding_lifecycle_invalid")

        prior_transitions = sorted(
            (
                transition
                for transition in state.fact.transitions
                if transition.run_id != facts.run_id
            ),
            key=lambda transition: transition.run_completed_at,
        )
        prior_status: Literal["OPEN", "CLOSED"] | None = None
        if prior_transitions:
            prior_status = (
                "CLOSED"
                if prior_transitions[-1].transition_type == "CLOSED"
                else "OPEN"
            )
        if is_difference:
            expected_transition: TransitionType | None = (
                "OPENED"
                if prior_status is None
                else "REOPENED"
                if prior_status == "CLOSED"
                else None
            )
        elif state.fact.canonical_ip in matched and prior_status == "OPEN":
            expected_transition = "CLOSED"
        else:
            expected_transition = None
        if state.current_transition != expected_transition:
            raise ReportCoreError("finding_lifecycle_invalid")

    return states


def _finding_counts(counter: Counter[FindingType]) -> tuple[FindingTypeCount, ...]:
    return tuple(
        FindingTypeCount(finding_type=finding_type, count=counter[finding_type])
        for finding_type in _FINDING_TYPES
    )


def compile_report_core(
    frozen_run_facts: FrozenRunReportFacts | Mapping[str, object],
    report_contract_version: str,
) -> CanonicalReportCore:
    """Validate frozen facts and atomically return the canonical report core."""

    if report_contract_version != REPORT_CONTRACT_VERSION:
        raise ReportCoreError("unsupported_report_contract_version")
    try:
        facts = (
            frozen_run_facts
            if isinstance(frozen_run_facts, FrozenRunReportFacts)
            else FrozenRunReportFacts.model_validate(frozen_run_facts)
        )
    except (ValidationError, TypeError):
        raise ReportCoreError("fact_schema_invalid") from None

    _validate_run_facts(facts)
    customer = set(facts.customer_observed_resource_keys)
    cloudatlas = set(facts.cloudatlas_observed_resource_keys)
    states = _validated_lifecycles(facts, customer=customer, cloudatlas=cloudatlas)

    current_counts: Counter[FindingType] = Counter()
    current_counts["UNREPORTED_ASSET"] = len(cloudatlas - customer)
    current_counts["UNOBSERVED_ASSET"] = len(customer - cloudatlas)
    matched = customer & cloudatlas

    changes = tuple(
        LifecycleChange(
            finding_id=state.fact.finding_id,
            finding_type=state.fact.finding_type,
            canonical_ip=state.fact.canonical_ip,
            transition_type=state.current_transition,
        )
        for state in sorted(
            (state for state in states if state.current_transition is not None),
            key=lambda item: _finding_sort_key(
                item.fact.finding_type,
                item.fact.canonical_ip,
                item.fact.finding_id,
            ),
        )
        if state.current_transition is not None
    )
    transition_counts: Counter[TransitionType] = Counter(
        change.transition_type for change in changes
    )

    open_findings = tuple(
        OpenFinding(
            finding_id=state.fact.finding_id,
            finding_type=state.fact.finding_type,
            canonical_ip=state.fact.canonical_ip,
        )
        for state in sorted(
            (state for state in states if state.status == "OPEN"),
            key=lambda item: _finding_sort_key(
                item.fact.finding_type,
                item.fact.canonical_ip,
                item.fact.finding_id,
            ),
        )
    )
    open_counts: Counter[FindingType] = Counter(
        finding.finding_type for finding in open_findings
    )
    present_types = {
        finding_type
        for finding_type in _FINDING_TYPES
        if current_counts[finding_type] or open_counts[finding_type]
    } | {change.finding_type for change in changes}

    snapshots = {snapshot.source_type: snapshot for snapshot in facts.source_snapshots}
    ordered_snapshots = tuple(snapshots[source_type] for source_type in _SOURCE_TYPES)
    current_finding_count = sum(current_counts.values())

    return CanonicalReportCore(
        report_identity=ReportIdentity(
            governance_run_id=facts.run_id,
            project_id=facts.project_id,
            run_completed_at=facts.completed_at,
            report_contract_version=report_contract_version,
            generation_mode=GENERATION_MODE,
        ),
        input_completeness=InputCompleteness(
            complete=True,
            sources=tuple(
                InputSourceSummary(
                    source_type=snapshot.source_type,
                    source_snapshot_id=snapshot.source_snapshot_id,
                    content_sha256=snapshot.content_sha256,
                    schema_version=snapshot.schema_version,
                    record_count=snapshot.record_count,
                )
                for snapshot in ordered_snapshots
            ),
        ),
        ip_consistency_summary=IPConsistencySummary(
            customer_observed_asset_count=len(customer),
            cloudatlas_observed_asset_count=len(cloudatlas),
            matched_asset_count=len(matched),
            all_observed_ip_identities_matched=current_finding_count == 0,
            current_run_finding_count=current_finding_count,
            finding_counts=_finding_counts(current_counts),
        ),
        current_run_lifecycle_changes=CurrentRunLifecycleChanges(
            total=len(changes),
            transition_counts=tuple(
                TransitionTypeCount(
                    transition_type=transition_type,
                    count=transition_counts[transition_type],
                )
                for transition_type in _TRANSITION_TYPES
            ),
            changes=changes,
        ),
        open_backlog_as_of_run=OpenBacklogAsOfRun(
            as_of_governance_run_id=facts.run_id,
            total=len(open_findings),
            finding_counts=_finding_counts(open_counts),
            findings=open_findings,
        ),
        bounded_evidence_examples=BoundedEvidenceExamples(),
        finding_type_directions_and_limitations=FindingTypeDirectionsAndLimitations(
            directions=(
                FindingTypeDirection(
                    finding_type="UNREPORTED_ASSET",
                    present="UNREPORTED_ASSET" in present_types,
                    direction="向客户系统补充资产记录",
                ),
                FindingTypeDirection(
                    finding_type="UNOBSERVED_ASSET",
                    present="UNOBSERVED_ASSET" in present_types,
                    direction="补充扫描目标并重新扫描",
                ),
            ),
            limitations=(
                "未观测资产不表示资产不存在",
                "本报告不分配严重性、优先级、责任、置信度或根因",
                "本报告不构成已批准动作，也不提供资产级处置动作",
            ),
        ),
        provenance=Provenance(
            governance_run_id=facts.run_id,
            processing_contract_version=facts.processing_contract_version,
            source_snapshot_ids=tuple(
                snapshot.source_snapshot_id for snapshot in ordered_snapshots
            ),
            source_snapshot_hashes=tuple(
                snapshot.content_sha256 for snapshot in ordered_snapshots
            ),
            finding_lifecycle_fact_count=len(states),
        ),
    )
