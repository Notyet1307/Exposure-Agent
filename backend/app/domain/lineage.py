"""Bounded display projection of one verified, immutable published Run."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Table, and_, case, func, or_, select, union
from sqlalchemy.orm import class_mapper
from sqlmodel import Session, SQLModel

from app.domain.ip_consistency import IPRecordContractError, normalize_ip
from app.domain.ip_source_comparison import (
    COMPARISON_CONTRACT_VERSION,
    IPSourceComparisonError,
    _ip_order,
    _project_governance_run_sources,
    _published_comparison_context,
    _require,
)
from app.domain.models import (
    Evidence,
    Finding,
    FindingOccurrence,
    FindingOccurrenceObservation,
    FindingOccurrenceSnapshot,
    FindingTransition,
    FindingTransitionObservation,
    FindingTransitionSnapshot,
    GovernanceReport,
    GovernanceRun,
    GovernanceRunLineagePublic,
    GovernanceRunSourcesPublic,
    IPSourceComparisonFact,
    LineageComparisonNodePublic,
    LineageEdgePublic,
    LineageEvidenceReferencePublic,
    LineageEvidenceReferencesPublic,
    LineageFindingNodePublic,
    LineageNodePublic,
    LineageObservationReferencePublic,
    LineageObservationReferencesPublic,
    LineageProcessNodePublic,
    LineageReportNodePublic,
    LineageReportSummaryPublic,
    LineageSnapshotNodePublic,
    LineageSourceNodePublic,
    Observation,
    ObservationResourceLink,
    Project,
    Resource,
    SourceSnapshot,
)
from app.domain.report_core import (
    REPORT_CONTRACT_VERSION,
    BoundedEvidenceExamples,
    CurrentRunLifecycleChanges,
    FindingTypeDirectionsAndLimitations,
    InputCompleteness,
    IPConsistencySummary,
    OpenBacklogAsOfRun,
    Provenance,
    ReportIdentity,
)

_LIMIT = 20
_SOURCE_TYPES = ("CUSTOMER_UPLOAD", "CLOUDATLAS", "NETFLOW")
_EDGE_TYPES = (
    "SOURCE_SNAPSHOT",
    "SNAPSHOT_PROCESS",
    "ABSENT_SOURCE_PROCESS",
    "PROCESS_COMPARISON",
    "PROCESS_FINDING",
    "PROCESS_REPORT",
    "COMPARISON_REPORT_CONTEXT",
    "FINDING_REPORT_CONTEXT",
)


def _table(model: type[SQLModel]) -> Table:
    return cast(Table, class_mapper(model).local_table)


def _scope(table: Any, run: GovernanceRun) -> Any:
    return and_(
        table.c.tenant_id == run.tenant_id,
        table.c.project_id == run.project_id,
        table.c.governance_run_id == run.id,
    )


def _reject_rows(session: Session, query: Any) -> None:
    _require(session.connection().execute(query.limit(1)).first() is None)


def _report_summary(
    report: GovernanceReport, run: GovernanceRun, sources: GovernanceRunSourcesPublic
) -> LineageReportSummaryPublic:
    envelope = report.canonical_content
    _require(isinstance(envelope, dict))
    _require(envelope.get("schema_version") == report.report_contract_version)
    content = envelope["report"]
    _require(isinstance(content, dict))
    if report.report_contract_version == REPORT_CONTRACT_VERSION:
        # Persisted JSON deliberately excludes CanonicalReportCore.finding_export_rows.
        # Parse wire sections directly; strict JSON validation still accepts timestamps.
        identity = ReportIdentity.model_validate_json(
            json.dumps(content["report_identity"]), strict=True
        )
        _require(
            identity.governance_run_id == str(run.id)
            and identity.project_id == str(run.project_id)
            and identity.report_contract_version == report.report_contract_version
            and identity.generation_mode == report.generation_mode
            and identity.run_completed_at.tzinfo is not None
            and identity.run_completed_at == run.completed_at
        )
        inputs = InputCompleteness.model_validate_json(
            json.dumps(content["input_completeness"]), strict=True
        )
        _require(
            tuple(item.source_type for item in inputs.sources) == _SOURCE_TYPES[:2]
        )
        for item, source in zip(inputs.sources, sources.sources[:2], strict=True):
            _require(
                item.source_snapshot_id == str(source.snapshot_id)
                and item.content_sha256 == source.content_sha256
                and item.schema_version == source.schema_fingerprint
                and item.record_count == source.record_count
                and item.record_count >= 0
            )
        summary = IPConsistencySummary.model_validate_json(
            json.dumps(content["ip_consistency_summary"]), strict=True
        )
        changes = CurrentRunLifecycleChanges.model_validate_json(
            json.dumps(content["current_run_lifecycle_changes"]), strict=True
        )
        backlog = OpenBacklogAsOfRun.model_validate_json(
            json.dumps(content["open_backlog_as_of_run"]), strict=True
        )
        _require(backlog.as_of_governance_run_id == str(run.id))
        _require(all(item.count >= 0 for item in summary.finding_counts))
        _require(all(item.count >= 0 for item in changes.transition_counts))
        _require(all(item.count >= 0 for item in backlog.finding_counts))
        examples = content["bounded_evidence_examples"]
        _require(isinstance(examples, dict))
        _require(BoundedEvidenceExamples.model_fields.keys() <= examples.keys())
        BoundedEvidenceExamples.model_validate_json(json.dumps(examples), strict=True)
        FindingTypeDirectionsAndLimitations.model_validate_json(
            json.dumps(content["finding_type_directions_and_limitations"]), strict=True
        )
        provenance = Provenance.model_validate_json(
            json.dumps(content["provenance"]), strict=True
        )
        _require(
            provenance.governance_run_id == str(run.id)
            and provenance.processing_contract_version
            == run.processing_contract_version
            and provenance.source_snapshot_ids
            == tuple(item.source_snapshot_id for item in inputs.sources)
            and provenance.source_snapshot_hashes
            == tuple(item.content_sha256 for item in inputs.sources)
            and provenance.finding_lifecycle_fact_count >= 0
        )
    values = content["ip_consistency_summary"]
    return LineageReportSummaryPublic.model_validate(
        {
            "customer_observed_asset_count": values["customer_observed_asset_count"],
            "cloudatlas_observed_asset_count": values[
                "cloudatlas_observed_asset_count"
            ],
            "matched_asset_count": values["matched_asset_count"],
            "current_run_finding_count": values["current_run_finding_count"],
            "current_run_transition_count": content["current_run_lifecycle_changes"][
                "total"
            ],
            "open_backlog_count": content["open_backlog_as_of_run"]["total"],
        }
    )


@dataclass
class _FindingEvent:
    finding_id: UUID
    resource_id: UUID
    canonical_ip: str
    finding_type: str
    occurrence_id: UUID | None = None
    transition_id: UUID | None = None
    transition_type: str | None = None


def _finding_events(session: Session, run: GovernanceRun) -> list[_FindingEvent]:
    finding, resource = _table(Finding), _table(Resource)
    events: dict[UUID, _FindingEvent] = {}
    for model in (FindingOccurrence, FindingTransition):
        event = _table(model)
        columns = [
            event.c.id,
            event.c.finding_id,
            event.c.tenant_id,
            event.c.project_id,
            finding.c.resource_id,
            finding.c.finding_type,
            finding.c.tenant_id.label("finding_tenant"),
            finding.c.project_id.label("finding_project"),
            resource.c.canonical_key,
            resource.c.resource_type,
            resource.c.tenant_id.label("resource_tenant"),
            resource.c.project_id.label("resource_project"),
        ]
        if model is FindingTransition:
            columns.append(event.c.transition_type)
        rows = (
            session.connection()
            .execute(
                select(*columns)
                .select_from(
                    event.outerjoin(
                        finding, finding.c.id == event.c.finding_id
                    ).outerjoin(resource, resource.c.id == finding.c.resource_id)
                )
                .where(event.c.governance_run_id == run.id)
            )
            .mappings()
        )
        for row in rows:
            _require(
                row.tenant_id
                == row.finding_tenant
                == row.resource_tenant
                == run.tenant_id
                and row.project_id
                == row.finding_project
                == row.resource_project
                == run.project_id
                and row.resource_type == "IP"
                and row.finding_type in ("UNREPORTED_ASSET", "UNOBSERVED_ASSET")
            )
            canonical_ip = str(row.canonical_key)
            _require(normalize_ip(canonical_ip) == canonical_ip)
            value = events.get(row.finding_id)
            if value is None:
                value = _FindingEvent(
                    row.finding_id, row.resource_id, canonical_ip, row.finding_type
                )
                events[row.finding_id] = value
            if model is FindingOccurrence:
                _require(value.occurrence_id is None)
                value.occurrence_id = row.id
            else:
                _require(value.transition_id is None)
                _require(row.transition_type in ("OPENED", "CLOSED", "REOPENED"))
                value.transition_id, value.transition_type = row.id, row.transition_type
    _require(
        all(
            (item.occurrence_id is None) == (item.transition_type == "CLOSED")
            for item in events.values()
        )
    )
    return sorted(
        events.values(),
        key=lambda item: (
            _ip_order(item.canonical_ip),
            item.finding_type,
            str(item.finding_id),
        ),
    )


def _event_links(session: Session, run: GovernanceRun) -> tuple[Any, Any]:
    """Validate *all* event links before selecting bounded reference projections."""
    finding = _table(Finding)
    observation, resource_link = _table(Observation), _table(ObservationResourceLink)
    snapshot = _table(SourceSnapshot)
    observation_queries, snapshot_queries = [], []
    for event_model, observation_model, snapshot_model, event_column in (
        (
            FindingOccurrence,
            FindingOccurrenceObservation,
            FindingOccurrenceSnapshot,
            "finding_occurrence_id",
        ),
        (
            FindingTransition,
            FindingTransitionObservation,
            FindingTransitionSnapshot,
            "finding_transition_id",
        ),
    ):
        event, obs_link, snap_link = map(
            _table, (event_model, observation_model, snapshot_model)
        )
        event_ids = select(event.c.id).where(event.c.governance_run_id == run.id)
        for link, target, target_column in (
            (obs_link, observation, "observation_id"),
            (snap_link, snapshot, "source_snapshot_id"),
        ):
            owned = or_(
                link.c.governance_run_id == run.id, link.c[event_column].in_(event_ids)
            )
            joined = link.outerjoin(
                event, event.c.id == link.c[event_column]
            ).outerjoin(target, target.c.id == link.c[target_column])
            _reject_rows(
                session,
                select(link.c.id)
                .select_from(joined)
                .where(
                    owned,
                    or_(
                        event.c.id.is_(None),
                        target.c.id.is_(None),
                        ~_scope(link, run),
                        ~_scope(event, run),
                        ~_scope(target, run),
                        target.c.source_type.not_in(_SOURCE_TYPES[:2]),
                    ),
                ),
            )
            _reject_rows(
                session,
                select(link.c[event_column])
                .where(owned)
                .group_by(link.c[event_column], link.c[target_column])
                .having(func.count() > 1),
            )
        # ip-v1 events require both input snapshots and positive observation basis.
        # Check each event before unioning references, so a sibling cannot hide loss.
        _reject_rows(
            session,
            select(event.c.id).where(
                event.c.governance_run_id == run.id,
                or_(
                    select(func.count())
                    .select_from(snap_link)
                    .where(snap_link.c[event_column] == event.c.id)
                    .scalar_subquery()
                    != 2,
                    ~select(obs_link.c.id)
                    .where(obs_link.c[event_column] == event.c.id)
                    .exists(),
                ),
            ),
        )
        joined_observations = (
            obs_link.join(event, event.c.id == obs_link.c[event_column])
            .join(finding, finding.c.id == event.c.finding_id)
            .join(observation, observation.c.id == obs_link.c.observation_id)
            .outerjoin(
                resource_link, resource_link.c.observation_id == observation.c.id
            )
        )
        _reject_rows(
            session,
            select(obs_link.c.id)
            .select_from(joined_observations)
            .where(
                event.c.governance_run_id == run.id,
                or_(
                    resource_link.c.id.is_(None),
                    ~_scope(resource_link, run),
                    resource_link.c.resource_id != finding.c.resource_id,
                    ~select(snap_link.c.id)
                    .where(
                        snap_link.c[event_column] == event.c.id,
                        snap_link.c.source_snapshot_id
                        == observation.c.source_snapshot_id,
                    )
                    .exists(),
                ),
            ),
        )
        observation_queries.append(
            select(
                event.c.finding_id.label("owner"),
                observation.c.id.label("id"),
                observation.c.source_snapshot_id.label("snapshot_id"),
                observation.c.source_type.label("source_type"),
            )
            .select_from(joined_observations)
            .where(event.c.governance_run_id == run.id)
        )
        snapshot_queries.append(
            select(
                event.c.finding_id.label("owner"),
                snapshot.c.id.label("id"),
                snapshot.c.source_type,
            )
            .select_from(
                snap_link.join(event, event.c.id == snap_link.c[event_column]).join(
                    snapshot, snapshot.c.id == snap_link.c.source_snapshot_id
                )
            )
            .where(event.c.governance_run_id == run.id)
        )
    return union(*observation_queries).subquery(), union(*snapshot_queries).subquery()


def _evidence_query(
    session: Session, run: GovernanceRun, report: GovernanceReport
) -> Any:
    evidence = _table(Evidence)
    targets = (
        (SourceSnapshot, "source_snapshot_id", "SOURCE_SNAPSHOT"),
        (Observation, "observation_id", "OBSERVATION"),
        (FindingOccurrence, "finding_occurrence_id", "FINDING_OCCURRENCE"),
        (FindingTransition, "finding_transition_id", "FINDING_TRANSITION"),
        (
            IPSourceComparisonFact,
            "ip_source_comparison_fact_id",
            "IP_SOURCE_COMPARISON",
        ),
    )
    owned = or_(
        evidence.c.governance_run_id == run.id,
        evidence.c.governance_report_id == report.id,
    )
    _reject_rows(
        session,
        select(evidence.c.id).where(
            owned,
            or_(
                ~_scope(evidence, run),
                evidence.c.governance_report_id != report.id,
                func.num_nonnulls(*(evidence.c[column] for _, column, _ in targets))
                != 1,
            ),
        ),
    )
    joined: Any = evidence
    for model, column, _ in targets:
        target = _table(model)
        _reject_rows(
            session,
            select(evidence.c.id)
            .select_from(evidence.outerjoin(target, target.c.id == evidence.c[column]))
            .where(
                owned,
                evidence.c[column].is_not(None),
                or_(target.c.id.is_(None), ~_scope(target, run)),
            ),
        )
        joined = joined.outerjoin(target, target.c.id == evidence.c[column])
    if report.report_contract_version == REPORT_CONTRACT_VERSION:
        _reject_rows(
            session,
            select(evidence.c.id).where(
                owned, evidence.c.ip_source_comparison_fact_id.is_not(None)
            ),
        )
    return (
        select(
            evidence.c.id,
            evidence.c.governance_run_id,
            case(
                *[
                    (evidence.c[column].is_not(None), kind)
                    for _, column, kind in targets
                ]
            ).label("fact_type"),
            func.coalesce(*(evidence.c[column] for _, column, _ in targets)).label(
                "fact_id"
            ),
            func.coalesce(
                _table(FindingOccurrence).c.finding_id,
                _table(FindingTransition).c.finding_id,
            ).label("finding_id"),
            _table(IPSourceComparisonFact).c.resource_id,
        )
        .select_from(joined)
        .where(evidence.c.governance_report_id == report.id)
        .subquery()
    )


def _bounded_rows(session: Session, query: Any, order: Sequence[Any]) -> Any:
    """Count complete deduplicated partitions in SQL; transfer at most 20 each."""
    refs = query.subquery()
    ranked = select(
        refs,
        func.count().over(partition_by=refs.c.owner).label("count"),
        func.row_number()
        .over(
            partition_by=refs.c.owner,
            order_by=[
                refs.c[column] if isinstance(column, str) else column(refs)
                for column in order
            ],
        )
        .label("rank"),
    ).subquery()
    return (
        session.connection()
        .execute(
            select(ranked)
            .where(ranked.c.rank <= _LIMIT)
            .order_by(ranked.c.owner, ranked.c.rank)
        )
        .mappings()
    )


def _source_order(refs: Any) -> Any:
    return case(
        {source: rank for rank, source in enumerate(_SOURCE_TYPES)},
        value=refs.c.source_type,
    )


def _observation_references(
    session: Session, query: Any
) -> dict[UUID, LineageObservationReferencesPublic]:
    result: dict[UUID, LineageObservationReferencesPublic] = {}
    for row in _bounded_rows(session, query, (_source_order, "id")):
        wrapper = result.get(row.owner)
        if wrapper is None:
            wrapper = LineageObservationReferencesPublic(
                count=row.count, data=[], truncated=row.count > _LIMIT
            )
            result[row.owner] = wrapper
        wrapper.data.append(
            LineageObservationReferencePublic(
                observation_id=row.id, source_snapshot_id=row.snapshot_id
            )
        )
    return result


def _evidence_references(
    session: Session, query: Any
) -> dict[UUID, LineageEvidenceReferencesPublic]:
    result: dict[UUID, LineageEvidenceReferencesPublic] = {}
    for row in _bounded_rows(session, query, ("id",)):
        wrapper = result.get(row.owner)
        if wrapper is None:
            wrapper = LineageEvidenceReferencesPublic(
                count=row.count, data=[], truncated=row.count > _LIMIT
            )
            result[row.owner] = wrapper
        wrapper.data.append(
            LineageEvidenceReferencePublic.model_validate(
                {
                    "id": row.id,
                    "governance_run_id": row.governance_run_id,
                    "fact_type": row.fact_type,
                    "fact_id": row.fact_id,
                }
            )
        )
    return result


def read_governance_run_lineage(
    *, session: Session, project: Project, run_id: UUID, resource_id: UUID | None = None
) -> GovernanceRunLineagePublic:
    """Caller owns authorization and a fresh read-only REPEATABLE READ Session."""
    try:
        with session.no_autoflush:
            return _read_lineage(
                session=session, project=project, run_id=run_id, resource_id=resource_id
            )
    except ValidationError, ValueError, TypeError, KeyError, IPRecordContractError:
        raise IPSourceComparisonError("comparison_facts_invalid") from None


def _read_lineage(
    *, session: Session, project: Project, run_id: UUID, resource_id: UUID | None
) -> GovernanceRunLineagePublic:
    run, report, comparison = _published_comparison_context(
        session=session, project=project, run_id=run_id
    )
    sources = _project_governance_run_sources(
        session=session, project=project, run=run, report=report
    )
    summary = _report_summary(report, run, sources)
    events = _finding_events(session, run)
    _require(
        sum(item.occurrence_id is not None for item in events)
        == summary.current_run_finding_count
        and sum(item.transition_id is not None for item in events)
        == summary.current_run_transition_count
    )
    event_observations, event_snapshots = _event_links(session, run)
    evidence = _evidence_query(session, run, report)
    comparisons_in_scope = [
        row
        for row in comparison.results
        if resource_id is None or row.resource_id == resource_id
    ]
    events_in_scope = [
        item
        for item in events
        if resource_id is None or item.resource_id == resource_id
    ]
    if resource_id is not None and not comparisons_in_scope and not events_in_scope:
        raise IPSourceComparisonError("lineage_resource_not_found")
    selected_comparisons = sorted(
        comparisons_in_scope,
        key=lambda item: (_ip_order(item.canonical_ip), str(item.resource_id)),
    )[:_LIMIT]
    selected_events = events_in_scope[:_LIMIT]
    resource_ids = [row.resource_id for row in selected_comparisons]
    finding_ids = [item.finding_id for item in selected_events]
    observation, link = _table(Observation), _table(ObservationResourceLink)
    comparison_observations = _observation_references(
        session,
        select(
            link.c.resource_id.label("owner"),
            observation.c.id,
            observation.c.source_snapshot_id.label("snapshot_id"),
            observation.c.source_type,
        )
        .select_from(link.join(observation, observation.c.id == link.c.observation_id))
        .where(link.c.governance_run_id == run.id, link.c.resource_id.in_(resource_ids))
        .distinct(),
    )
    finding_observations = _observation_references(
        session,
        select(event_observations).where(event_observations.c.owner.in_(finding_ids)),
    )
    snapshot_ids: dict[UUID, list[UUID]] = {}
    for finding_id, snapshot_id in (
        session.connection()
        .execute(
            select(event_snapshots.c.owner, event_snapshots.c.id)
            .where(event_snapshots.c.owner.in_(finding_ids))
            .order_by(
                event_snapshots.c.owner,
                _source_order(event_snapshots),
                event_snapshots.c.id,
            )
        )
        .tuples()
    ):
        snapshot_ids.setdefault(finding_id, []).append(snapshot_id)
    for ids in snapshot_ids.values():
        _require(len(ids) <= 3)
    comparison_evidence = _evidence_references(
        session,
        select(
            evidence.c.resource_id.label("owner"),
            evidence,
        ).where(evidence.c.resource_id.in_(resource_ids)),
    )
    finding_evidence = _evidence_references(
        session,
        select(
            evidence.c.finding_id.label("owner"),
            evidence,
        ).where(evidence.c.finding_id.in_(finding_ids)),
    )
    evidence_table = _table(Evidence)
    report_evidence = _evidence_references(
        session,
        select(
            evidence_table.c.governance_report_id.label("owner"),
            evidence,
        ).select_from(
            evidence.join(evidence_table, evidence_table.c.id == evidence.c.id)
        ),
    )
    fact_table = _table(IPSourceComparisonFact)
    # Result has keys() but no mapping access; consume its row iterator.
    fact_ids: dict[UUID, UUID] = dict(
        iter(
            session.connection()
            .execute(
                select(fact_table.c.resource_id, fact_table.c.id).where(
                    fact_table.c.governance_run_id == run.id,
                    fact_table.c.resource_id.in_(resource_ids),
                )
            )
            .tuples()
        )
    )
    if report.report_contract_version != REPORT_CONTRACT_VERSION:
        _require(set(fact_ids) == set(resource_ids))
    empty_observations = LineageObservationReferencesPublic(
        count=0, data=[], truncated=False
    )
    empty_evidence = LineageEvidenceReferencesPublic(count=0, data=[], truncated=False)
    process_key, report_key = f"process/{run.id}", f"report/{report.id}"
    nodes: list[LineageNodePublic] = []
    edges: list[LineageEdgePublic] = []

    def add_edge(kind: str, from_key: str, to_key: str) -> None:
        edges.append(
            LineageEdgePublic.model_validate(
                {
                    "key": f"edge/{kind}/{from_key}/{to_key}",
                    "kind": kind,
                    "from": from_key,
                    "to": to_key,
                }
            )
        )

    for source in sources.sources:
        key = f"source/{run.id}/{source.source_type}"
        nodes.append(
            LineageSourceNodePublic(
                kind="SOURCE",
                key=key,
                source_type=source.source_type,
                state=source.state,
                input_id=source.input_id,
            )
        )
        if source.state == "ABSENT":
            add_edge("ABSENT_SOURCE_PROCESS", key, process_key)
        else:
            add_edge("SOURCE_SNAPSHOT", key, f"snapshot/{source.snapshot_id}")
    for source in sources.sources:
        if source.state == "ABSENT":
            continue
        key = f"snapshot/{source.snapshot_id}"
        nodes.append(
            LineageSnapshotNodePublic.model_validate(
                {
                    "key": key,
                    "kind": "SNAPSHOT",
                    **source.model_dump(exclude={"state", "input_id"}),
                }
            )
        )
        add_edge("SNAPSHOT_PROCESS", key, process_key)
    nodes.append(
        LineageProcessNodePublic.model_validate(
            {
                "key": process_key,
                "kind": "PROCESS",
                "governance_run_id": run.id,
                "processing_contract_version": run.processing_contract_version,
                "comparison_contract_version": COMPARISON_CONTRACT_VERSION,
                "report_contract_version": report.report_contract_version,
            }
        )
    )
    for row in selected_comparisons:
        key = f"comparison/{run.id}/{row.resource_id}"
        nodes.append(
            LineageComparisonNodePublic.model_validate(
                {
                    "key": key,
                    "kind": "COMPARISON",
                    **row.model_dump(),
                    "comparison_fact_id": fact_ids.get(row.resource_id),
                    "observations": comparison_observations.get(
                        row.resource_id, empty_observations
                    ),
                    "evidence": comparison_evidence.get(
                        row.resource_id, empty_evidence
                    ),
                }
            )
        )
        add_edge("PROCESS_COMPARISON", process_key, key)
        add_edge("COMPARISON_REPORT_CONTEXT", key, report_key)
    for item in selected_events:
        key = f"finding/{run.id}/{item.finding_id}"
        nodes.append(
            LineageFindingNodePublic.model_validate(
                {
                    "key": key,
                    "kind": "FINDING",
                    "finding_id": item.finding_id,
                    "resource_id": item.resource_id,
                    "canonical_ip": item.canonical_ip,
                    "finding_type": item.finding_type,
                    "occurrence_id": item.occurrence_id,
                    "transition_id": item.transition_id,
                    "transition_type": item.transition_type,
                    "source_snapshot_ids": snapshot_ids.get(item.finding_id, []),
                    "observations": finding_observations.get(
                        item.finding_id, empty_observations
                    ),
                    "evidence": finding_evidence.get(item.finding_id, empty_evidence),
                }
            )
        )
        add_edge("PROCESS_FINDING", process_key, key)
        add_edge("FINDING_REPORT_CONTEXT", key, report_key)
    nodes.append(
        LineageReportNodePublic.model_validate(
            {
                "key": report_key,
                "kind": "REPORT",
                "governance_report_id": report.id,
                "report_contract_version": report.report_contract_version,
                "generation_mode": report.generation_mode,
                "html_sha256": report.html_sha256,
                "csv_sha256": report.csv_sha256,
                "summary": summary,
                "evidence": report_evidence.get(report.id, empty_evidence),
            }
        )
    )
    add_edge("PROCESS_REPORT", process_key, report_key)
    edges.sort(
        key=lambda edge: (_EDGE_TYPES.index(edge.kind), edge.from_, edge.to, edge.key)
    )
    reasons = []
    if len(comparisons_in_scope) > len(selected_comparisons):
        reasons.append("comparison_limit")
    if len(events_in_scope) > len(selected_events):
        reasons.append("finding_limit")
    if any(
        ref.truncated
        for refs in (comparison_observations, finding_observations)
        for ref in refs.values()
    ):
        reasons.append("observation_reference_limit")
    if any(
        ref.truncated
        for refs in (comparison_evidence, finding_evidence, report_evidence)
        for ref in refs.values()
    ):
        reasons.append("evidence_reference_limit")
    return GovernanceRunLineagePublic.model_validate(
        {
            "projection_version": "published-lineage/v1",
            **sources.model_dump(exclude={"sources"}),
            "view": "OVERVIEW" if resource_id is None else "RESOURCE",
            "resource_id": resource_id,
            "comparison_output_hash": comparison.output_hash,
            "status": "PARTIAL"
            if reasons
            else ("COMPLETE" if comparisons_in_scope or events_in_scope else "EMPTY"),
            "truncated": bool(reasons),
            "truncation_reasons": reasons,
            "totals": {
                "comparison_count": len(comparison.results),
                "finding_event_count": len(events),
            },
            "coverage": {
                "comparison_count": len(comparisons_in_scope),
                "comparison_returned": len(selected_comparisons),
                "finding_event_count": len(events_in_scope),
                "finding_returned": len(selected_events),
            },
            "nodes": nodes,
            "edges": edges,
        }
    )
