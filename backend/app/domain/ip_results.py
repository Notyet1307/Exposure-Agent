from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import distinct, func
from sqlmodel import Session, col, select

from app.domain.ip_consistency import (
    CLOUDATLAS_SOURCE_TYPE,
    CUSTOMER_UPLOAD_SOURCE_TYPE,
    IP_PROCESSING_CONTRACT_VERSION,
    ip_observation_sort_key,
)
from app.domain.models import (
    Finding,
    FindingDetailPublic,
    FindingOccurrence,
    FindingOccurrenceObservation,
    FindingOccurrencePublic,
    FindingOccurrenceSnapshot,
    FindingPublic,
    FindingsPublic,
    FindingTransition,
    FindingTransitionObservation,
    FindingTransitionPublic,
    FindingTransitionSnapshot,
    GovernanceRun,
    GovernanceRunStatus,
    IPAssetDetailPublic,
    IPAssetPublic,
    IPAssetsPublic,
    IPObservationPublic,
    Observation,
    ObservationResourceLink,
    Project,
    Resource,
    ResourceType,
    RunStep,
    RunStepCode,
    RunStepStatus,
    SourceSnapshot,
    SourceSnapshotPublic,
)


@dataclass(frozen=True, slots=True)
class PublishedRunView:
    latest_run: GovernanceRun | None
    compatible_run: GovernanceRun | None
    compatibility_code: str | None


def _is_compatible_run(session: Session, run: GovernanceRun) -> bool:
    if (
        run.status != GovernanceRunStatus.COMPLETED.value
        or run.processing_contract_version != IP_PROCESSING_CONTRACT_VERSION
    ):
        return False
    steps = session.exec(
        select(RunStep).where(RunStep.governance_run_id == run.id)
    ).all()
    step_statuses = {step.step_code: step.status for step in steps}
    return all(
        step_statuses.get(step_code.value) == RunStepStatus.SUCCEEDED.value
        for step_code in (
            RunStepCode.NORMALIZE,
            RunStepCode.RESOLVE,
            RunStepCode.CHECK_FINDINGS,
            RunStepCode.PUBLISH,
        )
    )


def published_run_view(*, session: Session, project: Project) -> PublishedRunView:
    latest_run = None
    if project.latest_completed_run_id is not None:
        latest_run = session.exec(
            select(GovernanceRun).where(
                GovernanceRun.id == project.latest_completed_run_id,
                GovernanceRun.project_id == project.id,
                GovernanceRun.tenant_id == project.tenant_id,
            )
        ).one_or_none()
    if latest_run is None:
        return PublishedRunView(
            latest_run=None,
            compatible_run=None,
            compatibility_code="stage4_run_required",
        )
    if not _is_compatible_run(session, latest_run):
        return PublishedRunView(
            latest_run=latest_run,
            compatible_run=None,
            compatibility_code="stage4_run_required",
        )
    return PublishedRunView(
        latest_run=latest_run,
        compatible_run=latest_run,
        compatibility_code=None,
    )


def _canonical_key(value: object) -> str:
    return str(value)


def _observation_public(observation: Observation) -> IPObservationPublic:
    return IPObservationPublic(
        id=observation.id,
        source_type=observation.source_type,
        source_record_key=observation.source_record_key,
        raw_ip=observation.raw_ip,
        canonical_ip=_canonical_key(observation.canonical_ip),
        cloudatlas_asset_id=observation.cloudatlas_asset_id,
        cloudatlas_status=observation.cloudatlas_status,
        source_snapshot_id=observation.source_snapshot_id,
    )


def _resource_ids_for_run(*, project_id: Any, run_id: Any) -> Any:
    return (
        select(col(ObservationResourceLink.resource_id))
        .where(
            col(ObservationResourceLink.project_id) == project_id,
            col(ObservationResourceLink.governance_run_id) == run_id,
        )
        .distinct()
    )


def _asset_counts(
    *, session: Session, run_id: Any, resource_ids: list[Any]
) -> dict[Any, dict[str, int]]:
    counts: dict[Any, dict[str, int]] = defaultdict(
        lambda: {CUSTOMER_UPLOAD_SOURCE_TYPE: 0, CLOUDATLAS_SOURCE_TYPE: 0}
    )
    if not resource_ids:
        return counts
    rows = session.exec(
        select(
            col(ObservationResourceLink.resource_id),
            col(Observation.source_type),
            func.count(col(Observation.id)),
        )
        .join(
            Observation,
            col(Observation.id) == col(ObservationResourceLink.observation_id),
        )
        .where(
            col(ObservationResourceLink.governance_run_id) == run_id,
            col(ObservationResourceLink.resource_id).in_(resource_ids),
        )
        .group_by(
            col(ObservationResourceLink.resource_id),
            col(Observation.source_type),
        )
    ).all()
    for resource_id, source_type, count in rows:
        counts[resource_id][source_type] = int(count)
    return counts


def _open_findings(
    *, session: Session, project_id: Any, resource_ids: list[Any]
) -> dict[Any, Finding]:
    if not resource_ids:
        return {}
    findings = session.exec(
        select(Finding).where(
            col(Finding.project_id) == project_id,
            col(Finding.resource_id).in_(resource_ids),
            col(Finding.status) == "OPEN",
        )
    ).all()
    findings_by_resource: dict[Any, Finding] = {}
    for finding in sorted(findings, key=lambda item: (item.finding_type, str(item.id))):
        findings_by_resource.setdefault(finding.resource_id, finding)
    return findings_by_resource


def _asset_public(
    *,
    resource: Resource,
    counts: dict[str, int],
    open_finding: Finding | None,
) -> IPAssetPublic:
    customer_count = counts.get(CUSTOMER_UPLOAD_SOURCE_TYPE, 0)
    cloudatlas_count = counts.get(CLOUDATLAS_SOURCE_TYPE, 0)
    canonical_ip = _canonical_key(resource.canonical_key)
    return IPAssetPublic(
        id=resource.id,
        resource_id=resource.id,
        resource_type=resource.resource_type,
        canonical_key=canonical_ip,
        canonical_ip=canonical_ip,
        customer_observation_count=customer_count,
        cloudatlas_observation_count=cloudatlas_count,
        observation_count=customer_count + cloudatlas_count,
        customer_observed=customer_count > 0,
        cloudatlas_observed=cloudatlas_count > 0,
        open_finding_id=open_finding.id if open_finding is not None else None,
        open_finding_type=(
            open_finding.finding_type if open_finding is not None else None
        ),
    )


def list_ip_assets(
    *,
    session: Session,
    project: Project,
    skip: int,
    limit: int,
) -> IPAssetsPublic:
    published = published_run_view(session=session, project=project)
    latest_run = published.latest_run
    if published.compatible_run is None:
        return IPAssetsPublic(
            data=[],
            count=0,
            latest_run_id=latest_run.id if latest_run is not None else None,
            latest_run_completed_at=(
                latest_run.completed_at if latest_run is not None else None
            ),
            compatible=False,
            compatibility_code=published.compatibility_code,
        )
    run = published.compatible_run
    resource_id_query = _resource_ids_for_run(project_id=project.id, run_id=run.id)
    count = session.exec(
        select(func.count(distinct(col(Resource.id))))
        .select_from(Resource)
        .where(
            col(Resource.project_id) == project.id,
            col(Resource.tenant_id) == project.tenant_id,
            col(Resource.resource_type) == ResourceType.IP.value,
            col(Resource.id).in_(resource_id_query),
        )
    ).one()
    resources = session.exec(
        select(Resource)
        .where(
            col(Resource.project_id) == project.id,
            col(Resource.tenant_id) == project.tenant_id,
            col(Resource.resource_type) == ResourceType.IP.value,
            col(Resource.id).in_(resource_id_query),
        )
        .order_by(col(Resource.canonical_key), col(Resource.id))
        .offset(skip)
        .limit(limit)
    ).all()
    resource_ids = [resource.id for resource in resources]
    counts = _asset_counts(
        session=session,
        run_id=run.id,
        resource_ids=resource_ids,
    )
    open_findings = _open_findings(
        session=session,
        project_id=project.id,
        resource_ids=resource_ids,
    )
    return IPAssetsPublic(
        data=[
            _asset_public(
                resource=resource,
                counts=counts[resource.id],
                open_finding=open_findings.get(resource.id),
            )
            for resource in resources
        ],
        count=int(count),
        latest_run_id=run.id,
        latest_run_completed_at=run.completed_at,
        compatible=True,
        compatibility_code=None,
    )


def get_ip_asset(
    *, session: Session, project: Project, resource_id: Any
) -> IPAssetDetailPublic | None:
    published = published_run_view(session=session, project=project)
    run = published.compatible_run
    if run is None:
        return None
    resource = session.exec(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.project_id == project.id,
            Resource.tenant_id == project.tenant_id,
            col(Resource.resource_type) == ResourceType.IP.value,
            col(Resource.id).in_(
                _resource_ids_for_run(project_id=project.id, run_id=run.id)
            ),
        )
    ).one_or_none()
    if resource is None:
        return None
    links = session.exec(
        select(ObservationResourceLink).where(
            ObservationResourceLink.resource_id == resource.id,
            ObservationResourceLink.governance_run_id == run.id,
            ObservationResourceLink.project_id == project.id,
            ObservationResourceLink.tenant_id == project.tenant_id,
        )
    ).all()
    observation_ids = [link.observation_id for link in links]
    observations = (
        session.exec(
            select(Observation).where(col(Observation.id).in_(observation_ids))
        ).all()
        if observation_ids
        else []
    )
    ordered_observations = sorted(
        observations,
        key=lambda observation: ip_observation_sort_key(
            observation.source_type,
            observation.source_record_key,
            observation.id,
        ),
    )
    counts = _asset_counts(
        session=session,
        run_id=run.id,
        resource_ids=[resource.id],
    )
    open_finding = _open_findings(
        session=session,
        project_id=project.id,
        resource_ids=[resource.id],
    ).get(resource.id)
    asset = _asset_public(
        resource=resource,
        counts=counts[resource.id],
        open_finding=open_finding,
    )
    return IPAssetDetailPublic(
        **asset.model_dump(),
        observations=[_observation_public(item) for item in ordered_observations],
    )


def _finding_times(
    *, session: Session, finding_ids: list[Any]
) -> tuple[
    dict[Any, int],
    dict[Any, int],
    dict[Any, datetime | None],
    dict[Any, datetime | None],
]:
    occurrence_counts: dict[Any, int] = {}
    transition_counts: dict[Any, int] = {}
    latest_occurrences: dict[Any, datetime | None] = {}
    latest_transitions: dict[Any, datetime | None] = {}
    if not finding_ids:
        return (
            occurrence_counts,
            transition_counts,
            latest_occurrences,
            latest_transitions,
        )
    occurrence_rows = session.exec(
        select(
            col(FindingOccurrence.finding_id),
            func.count(col(FindingOccurrence.id)),
            func.max(col(FindingOccurrence.created_at)),
        )
        .where(col(FindingOccurrence.finding_id).in_(finding_ids))
        .group_by(col(FindingOccurrence.finding_id))
    ).all()
    for finding_id, count, latest in occurrence_rows:
        occurrence_counts[finding_id] = int(count)
        latest_occurrences[finding_id] = latest
    transition_rows = session.exec(
        select(
            col(FindingTransition.finding_id),
            func.count(col(FindingTransition.id)),
            func.max(col(FindingTransition.created_at)),
        )
        .where(col(FindingTransition.finding_id).in_(finding_ids))
        .group_by(col(FindingTransition.finding_id))
    ).all()
    for finding_id, count, latest in transition_rows:
        transition_counts[finding_id] = int(count)
        latest_transitions[finding_id] = latest
    return (
        occurrence_counts,
        transition_counts,
        latest_occurrences,
        latest_transitions,
    )


def _finding_public(
    *,
    finding: Finding,
    resource: Resource,
    occurrence_count: int,
    transition_count: int,
    latest_occurrence: datetime | None,
    latest_transition: datetime | None,
) -> FindingPublic:
    return FindingPublic(
        id=finding.id,
        resource_id=finding.resource_id,
        finding_type=finding.finding_type,
        status=finding.status,
        canonical_ip=_canonical_key(resource.canonical_key),
        first_detected_at=finding.first_detected_at,
        last_detected_at=finding.last_detected_at,
        latest_occurrence_at=latest_occurrence,
        latest_transition_at=latest_transition,
        occurrence_count=occurrence_count,
        transition_count=transition_count,
    )


def _finding_sort_time(
    finding: Finding,
    latest_occurrence: datetime | None,
    latest_transition: datetime | None,
) -> datetime:
    values = [
        value
        for value in (
            latest_occurrence,
            latest_transition,
            finding.last_detected_at,
            finding.created_at,
        )
        if value is not None
    ]
    return max(values)


def list_findings(
    *,
    session: Session,
    project: Project,
    status: str,
    skip: int,
    limit: int,
) -> FindingsPublic:
    published = published_run_view(session=session, project=project)
    latest_run = published.latest_run
    if published.compatible_run is None:
        return FindingsPublic(
            data=[],
            count=0,
            status=status,
            latest_run_id=latest_run.id if latest_run is not None else None,
            latest_run_completed_at=(
                latest_run.completed_at if latest_run is not None else None
            ),
            compatible=False,
            compatibility_code=published.compatibility_code,
        )
    findings = list(
        session.exec(
            select(Finding).where(
                col(Finding.project_id) == project.id,
                col(Finding.tenant_id) == project.tenant_id,
                col(Finding.status) == status,
            )
        ).all()
    )
    finding_ids = [finding.id for finding in findings]
    occurrence_counts, transition_counts, latest_occurrences, latest_transitions = (
        _finding_times(session=session, finding_ids=finding_ids)
    )
    resource_ids = [finding.resource_id for finding in findings]
    resources = (
        session.exec(
            select(Resource).where(
                Resource.project_id == project.id,
                col(Resource.tenant_id) == project.tenant_id,
                col(Resource.id).in_(resource_ids),
            )
        ).all()
        if resource_ids
        else []
    )
    resources_by_id = {resource.id: resource for resource in resources}
    findings.sort(
        key=lambda finding: (
            -_finding_sort_time(
                finding,
                latest_occurrences.get(finding.id),
                latest_transitions.get(finding.id),
            ).timestamp(),
            str(finding.id),
        )
    )
    page = findings[skip : skip + limit]
    return FindingsPublic(
        data=[
            _finding_public(
                finding=finding,
                resource=resources_by_id[finding.resource_id],
                occurrence_count=occurrence_counts.get(finding.id, 0),
                transition_count=transition_counts.get(finding.id, 0),
                latest_occurrence=latest_occurrences.get(finding.id),
                latest_transition=latest_transitions.get(finding.id),
            )
            for finding in page
        ],
        count=len(findings),
        status=status,
        latest_run_id=published.compatible_run.id,
        latest_run_completed_at=published.compatible_run.completed_at,
        compatible=True,
        compatibility_code=None,
    )


def _occurrence_public(
    *, session: Session, occurrence: FindingOccurrence, trace_limit: int
) -> FindingOccurrencePublic:
    observation_ids = session.exec(
        select(FindingOccurrenceObservation.observation_id)
        .where(FindingOccurrenceObservation.finding_occurrence_id == occurrence.id)
        .order_by(col(FindingOccurrenceObservation.observation_id))
        .limit(trace_limit)
    ).all()
    snapshot_ids = session.exec(
        select(FindingOccurrenceSnapshot.source_snapshot_id)
        .where(FindingOccurrenceSnapshot.finding_occurrence_id == occurrence.id)
        .order_by(col(FindingOccurrenceSnapshot.source_snapshot_id))
        .limit(trace_limit)
    ).all()
    observations = (
        session.exec(
            select(Observation).where(col(Observation.id).in_(observation_ids))
        ).all()
        if observation_ids
        else []
    )
    source_snapshots = (
        session.exec(
            select(SourceSnapshot).where(col(SourceSnapshot.id).in_(snapshot_ids))
        ).all()
        if snapshot_ids
        else []
    )
    return FindingOccurrencePublic(
        id=occurrence.id,
        governance_run_id=occurrence.governance_run_id,
        created_at=occurrence.created_at,
        observation_ids=list(observation_ids),
        source_snapshot_ids=list(snapshot_ids),
        source_snapshots=[
            SourceSnapshotPublic.model_validate(snapshot)
            for snapshot in sorted(
                source_snapshots,
                key=lambda snapshot: (snapshot.source_type, str(snapshot.id)),
            )
        ],
        observations=[
            _observation_public(item)
            for item in sorted(
                observations,
                key=lambda observation: ip_observation_sort_key(
                    observation.source_type,
                    observation.source_record_key,
                    observation.id,
                ),
            )
        ],
    )


def _transition_public(
    *, session: Session, transition: FindingTransition, trace_limit: int
) -> FindingTransitionPublic:
    observation_ids = session.exec(
        select(FindingTransitionObservation.observation_id)
        .where(FindingTransitionObservation.finding_transition_id == transition.id)
        .order_by(col(FindingTransitionObservation.observation_id))
        .limit(trace_limit)
    ).all()
    snapshot_ids = session.exec(
        select(FindingTransitionSnapshot.source_snapshot_id)
        .where(FindingTransitionSnapshot.finding_transition_id == transition.id)
        .order_by(col(FindingTransitionSnapshot.source_snapshot_id))
        .limit(trace_limit)
    ).all()
    observations = (
        session.exec(
            select(Observation).where(col(Observation.id).in_(observation_ids))
        ).all()
        if observation_ids
        else []
    )
    source_snapshots = (
        session.exec(
            select(SourceSnapshot).where(col(SourceSnapshot.id).in_(snapshot_ids))
        ).all()
        if snapshot_ids
        else []
    )
    return FindingTransitionPublic(
        id=transition.id,
        governance_run_id=transition.governance_run_id,
        transition_type=transition.transition_type,
        created_at=transition.created_at,
        observation_ids=list(observation_ids),
        source_snapshot_ids=list(snapshot_ids),
        source_snapshots=[
            SourceSnapshotPublic.model_validate(snapshot)
            for snapshot in sorted(
                source_snapshots,
                key=lambda snapshot: (snapshot.source_type, str(snapshot.id)),
            )
        ],
        observations=[
            _observation_public(item)
            for item in sorted(
                observations,
                key=lambda observation: ip_observation_sort_key(
                    observation.source_type,
                    observation.source_record_key,
                    observation.id,
                ),
            )
        ],
    )


def get_finding_detail(
    *, session: Session, project: Project, finding_id: Any, trace_limit: int
) -> FindingDetailPublic | None:
    published = published_run_view(session=session, project=project)
    if published.compatible_run is None:
        return None
    finding = session.exec(
        select(Finding).where(
            Finding.id == finding_id,
            Finding.project_id == project.id,
            Finding.tenant_id == project.tenant_id,
        )
    ).one_or_none()
    if finding is None:
        return None
    resource = session.exec(
        select(Resource).where(
            Resource.id == finding.resource_id,
            Resource.project_id == project.id,
            Resource.tenant_id == project.tenant_id,
        )
    ).one()
    occurrence_count, transition_count, latest_occurrence, latest_transition = (
        _finding_times(session=session, finding_ids=[finding.id])
    )
    occurrences = session.exec(
        select(FindingOccurrence)
        .where(FindingOccurrence.finding_id == finding.id)
        .order_by(
            col(FindingOccurrence.created_at).desc(),
            col(FindingOccurrence.id).asc(),
        )
        .limit(trace_limit)
    ).all()
    transitions = session.exec(
        select(FindingTransition)
        .where(FindingTransition.finding_id == finding.id)
        .order_by(
            col(FindingTransition.created_at).desc(),
            col(FindingTransition.id).asc(),
        )
        .limit(trace_limit)
    ).all()
    summary = _finding_public(
        finding=finding,
        resource=resource,
        occurrence_count=occurrence_count.get(finding.id, 0),
        transition_count=transition_count.get(finding.id, 0),
        latest_occurrence=latest_occurrence.get(finding.id),
        latest_transition=latest_transition.get(finding.id),
    )
    return FindingDetailPublic(
        **summary.model_dump(),
        occurrences=[
            _occurrence_public(
                session=session,
                occurrence=occurrence,
                trace_limit=trace_limit,
            )
            for occurrence in occurrences
        ],
        transitions=[
            _transition_public(
                session=session,
                transition=transition,
                trace_limit=trace_limit,
            )
            for transition in transitions
        ],
    )
