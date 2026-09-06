"""Read fixed Run facts for internal report candidates without publishing them."""

from __future__ import annotations

import uuid

from pydantic import ValidationError
from sqlmodel import Session, col, select

from app.domain.governance_runs import (
    GovernanceRunExecutionError,
    _netflow_activity_result,
    _report_candidate_facts,
)
from app.domain.ip_consistency import (
    IP_PROCESSING_CONTRACT_VERSION,
    IPRecordContractError,
    normalize_ip,
)
from app.domain.ip_source_comparison import (
    IPSourceComparisonError,
    compile_ip_source_comparison,
    read_comparison_source_facts,
    read_ip_source_comparison,
)
from app.domain.models import (
    GovernanceRun,
    NetFlowIPActivity,
    ObservationResourceLink,
    Resource,
    RunStep,
    SourceSnapshot,
)
from app.domain.netflow_activity import (
    NETFLOW_ACTIVITY_CONTRACT_VERSION,
    NetFlowActivityContractError,
    NetFlowIPActivityAggregate,
    NetFlowIPActivityResult,
    netflow_activity_output_hash,
)
from app.domain.netflow_datasets import NETFLOW_DATASET_CONTRACT_VERSION
from app.domain.report_candidates import (
    REPORT_V2_CONTRACT_VERSION,
    CandidateSourceSnapshot,
    FrozenGovernanceCandidateFacts,
    FrozenReportCandidateFacts,
    ReportCandidate,
    ReportCandidateError,
    generate_report_candidate,
)
from app.domain.report_core import REPORT_CONTRACT_VERSION, ReportCoreError


def _require(condition: bool) -> None:
    if not condition:
        raise ReportCandidateError("report_facts_invalid")


def _source_summary(snapshot: SourceSnapshot) -> CandidateSourceSnapshot:
    return CandidateSourceSnapshot(
        source_type="NETFLOW",
        source_snapshot_id=snapshot.id,
        content_sha256=snapshot.content_sha256,
        schema_version=snapshot.schema_fingerprint,
        record_count=snapshot.record_count,
    )


def _read_ready_run(
    *,
    session: Session,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    comparison_required: bool = False,
) -> tuple[GovernanceRun, dict[str, RunStep]]:
    run = session.exec(
        select(GovernanceRun).where(
            GovernanceRun.id == run_id,
            GovernanceRun.tenant_id == tenant_id,
            GovernanceRun.project_id == project_id,
        )
    ).one_or_none()
    _require(run is not None)
    assert run is not None
    if comparison_required and (
        run.input_contract_version != "governance-run-input-v1"
        or run.processing_contract_version != IP_PROCESSING_CONTRACT_VERSION
        or run.report_contract_version
        not in {REPORT_CONTRACT_VERSION, REPORT_V2_CONTRACT_VERSION}
    ):
        raise ReportCandidateError("comparison_contract_unsupported")
    _require(
        run.status
        in {
            "RUNNING",
            "FAILED_PROCESSING",
            "COMPLETED",
            "COMPLETED_WITH_WARNINGS",
        }
    )
    if run.status in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}:
        _require(run.completed_at is not None)
    else:
        _require(run.completed_at is None)
    steps = {
        step.step_code: step
        for step in session.exec(
            select(RunStep).where(
                RunStep.governance_run_id == run_id,
                RunStep.tenant_id == tenant_id,
                RunStep.project_id == project_id,
            )
        ).all()
    }
    for code in ("NORMALIZE", "RESOLVE", "CHECK_FINDINGS"):
        _require(
            code in steps
            and steps[code].status == "SUCCEEDED"
            and steps[code].output_hash is not None
        )
    _require("BUILD_REPORT" in steps)
    _require(steps["BUILD_REPORT"].started_at is not None)
    return run, steps


def _read_facts(
    *, session: Session, tenant_id: uuid.UUID, project_id: uuid.UUID, run_id: uuid.UUID
) -> FrozenReportCandidateFacts:
    run, steps = _read_ready_run(
        session=session,
        tenant_id=tenant_id,
        project_id=project_id,
        run_id=run_id,
        comparison_required=True,
    )
    snapshots, observations, links = read_comparison_source_facts(
        session=session, run=run, steps=steps
    )
    published = run.completed_at is not None
    activity_result: NetFlowIPActivityResult | None = None
    if (
        run.netflow_dataset_id is not None
        and run.netflow_dataset_contract_version != NETFLOW_DATASET_CONTRACT_VERSION
    ):
        raise ReportCandidateError("comparison_contract_unsupported")
    if published:
        # Only this adapter reads immutable activity rows and publication receipts.
        comparison = read_ip_source_comparison(
            session=session, tenant_id=tenant_id, project_id=project_id, run_id=run_id
        )
        if run.netflow_dataset_id is not None:
            activities_by_resource = {
                activity.resource_id: activity
                for activity in session.exec(
                    select(NetFlowIPActivity).where(
                        NetFlowIPActivity.governance_run_id == run_id,
                        NetFlowIPActivity.tenant_id == tenant_id,
                        NetFlowIPActivity.project_id == project_id,
                    )
                ).all()
            }
            aggregates = []
            for row in comparison.results:
                if row.netflow_status != "ACTIVE":
                    continue
                activity = activities_by_resource[row.resource_id]
                aggregates.append(
                    NetFlowIPActivityAggregate(
                        canonical_ip=row.canonical_ip,
                        flow_count=activity.flow_count,
                        peer_ips=tuple(str(peer) for peer in activity.peer_ips),
                        protocols=tuple(activity.protocols),
                        first_seen_utc=activity.first_seen_utc,
                        last_seen_utc=activity.last_seen_utc,
                    )
                )
            aggregate_tuple = tuple(aggregates)
            activity_result = NetFlowIPActivityResult(
                contract_version=NETFLOW_ACTIVITY_CONTRACT_VERSION,
                activities=aggregate_tuple,
                output_hash=netflow_activity_output_hash(aggregate_tuple),
            )
    else:
        # A candidate cannot borrow activity rows from an incomplete publication.
        existing_activity = session.exec(
            select(NetFlowIPActivity.id)
            .where(
                NetFlowIPActivity.governance_run_id == run_id,
                NetFlowIPActivity.tenant_id == tenant_id,
                NetFlowIPActivity.project_id == project_id,
            )
            .limit(1)
        ).first()
        _require(existing_activity is None)
        _require("PUBLISH" not in steps or steps["PUBLISH"].status != "SUCCEEDED")
        links_by_observation = {link.observation_id: link for link in links}
        linked_ids = select(ObservationResourceLink.resource_id).where(
            ObservationResourceLink.governance_run_id == run_id,
            ObservationResourceLink.tenant_id == tenant_id,
            ObservationResourceLink.project_id == project_id,
        )
        linked_resources = session.exec(
            select(Resource).where(
                Resource.tenant_id == tenant_id,
                Resource.project_id == project_id,
                Resource.resource_type == "IP",
                col(Resource.id).in_(linked_ids),
            )
        ).all()
        resources_by_id = {resource.id: resource for resource in linked_resources}
        _require(set(resources_by_id) == {link.resource_id for link in links})
        resource_keys = {
            resource.id: str(resource.canonical_key) for resource in linked_resources
        }
        membership: dict[uuid.UUID, set[str]] = {}
        for observation in observations:
            link = links_by_observation[observation.id]
            _require(
                link.processing_contract_version == run.processing_contract_version
            )
            _require(resource_keys[link.resource_id] == str(observation.canonical_ip))
            _require(
                normalize_ip(resource_keys[link.resource_id])
                == resource_keys[link.resource_id]
            )
            membership.setdefault(link.resource_id, set()).add(observation.source_type)
        active_resources: set[uuid.UUID] = set()
        if run.netflow_dataset_id is not None:
            if run.netflow_dataset_contract_version != NETFLOW_DATASET_CONTRACT_VERSION:
                raise ReportCandidateError("comparison_contract_unsupported")
            activity_result, activity_snapshot, managed_by_key = (
                _netflow_activity_result(
                    session=session,
                    run=run,
                    resource_as_of=steps["BUILD_REPORT"].started_at,
                )
            )
            if activity_result.contract_version != NETFLOW_ACTIVITY_CONTRACT_VERSION:
                raise ReportCandidateError("comparison_contract_unsupported")
            _require(activity_snapshot.id == snapshots["NETFLOW"].id)
            _require(
                activity_result.output_hash
                == netflow_activity_output_hash(activity_result.activities)
            )
            _require(
                len({item.canonical_ip for item in activity_result.activities})
                == len(activity_result.activities)
            )
            for aggregate in activity_result.activities:
                _require(
                    aggregate.flow_count > 0
                    and aggregate.canonical_ip in managed_by_key
                )
                _require(normalize_ip(aggregate.canonical_ip) == aggregate.canonical_ip)
                resource = managed_by_key[aggregate.canonical_ip]
                _require(
                    resource.tenant_id == tenant_id
                    and resource.project_id == project_id
                )
                _require(resource.resource_type == "IP")
                _require(str(resource.canonical_key) == aggregate.canonical_ip)
                resource_keys[resource.id] = aggregate.canonical_ip
                active_resources.add(resource.id)
                membership.setdefault(resource.id, set())
        else:
            _require(run.netflow_content_sha256 is None)
            _require(run.netflow_dataset_contract_version is None)
        comparison = compile_ip_source_comparison(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            resources=resource_keys,
            membership=membership,
            active_resources=active_resources,
            netflow_present=run.netflow_dataset_id is not None,
        )
    governance, evidence = _report_candidate_facts(session=session, run=run)
    expected_snapshot_ids = {
        snapshot.source_type: snapshot.source_snapshot_id
        for snapshot in governance.source_snapshots
    }
    _require(
        expected_snapshot_ids
        == {
            source: str(snapshot.id)
            for source, snapshot in snapshots.items()
            if source in {"CUSTOMER_UPLOAD", "CLOUDATLAS"}
        }
    )
    candidate_netflow_snapshot = (
        _source_summary(snapshots["NETFLOW"])
        if run.netflow_dataset_id is not None
        else None
    )
    return FrozenReportCandidateFacts(
        governance=governance,
        evidence=evidence,
        comparison=comparison,
        netflow_snapshot=candidate_netflow_snapshot,
        netflow_activity=activity_result,
    )


def read_report_candidate_facts(
    *, session: Session, tenant_id: uuid.UUID, project_id: uuid.UUID, run_id: uuid.UUID
) -> FrozenReportCandidateFacts:
    """Capture a detached immutable input bundle; do not flush caller changes.

    Before Publish, the existing aggregator executes over validated normalized
    input. After Publish, only persisted immutable activity/receipt facts count.
    Captured inputs can be rebuilt independently of subsequent database changes.
    """
    try:
        with session.no_autoflush:
            return _read_facts(
                session=session,
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=run_id,
            )
    except IPSourceComparisonError as error:
        code = (
            "comparison_contract_unsupported"
            if error.code == "comparison_contract_unsupported"
            else "report_facts_invalid"
        )
        raise ReportCandidateError(code) from None
    except GovernanceRunExecutionError as error:
        if error.code in {"artifact_read_failed", "netflow_artifact_unavailable"}:
            raise
        raise ReportCandidateError("report_facts_invalid") from None
    except (
        ValidationError,
        ValueError,
        TypeError,
        ReportCoreError,
        IPRecordContractError,
        NetFlowActivityContractError,
    ):
        raise ReportCandidateError("report_facts_invalid") from None


def generate_run_report_candidate(
    *,
    session: Session,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    report_contract_version: str | None,
) -> ReportCandidate:
    """Scoped DB-backed candidate entry; selection never changes the Run pin."""
    if report_contract_version not in {
        REPORT_CONTRACT_VERSION,
        REPORT_V2_CONTRACT_VERSION,
    }:
        raise ReportCandidateError("report_contract_unsupported")
    if report_contract_version == REPORT_CONTRACT_VERSION:
        try:
            with session.no_autoflush:
                run, _steps = _read_ready_run(
                    session=session,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    run_id=run_id,
                )
                governance, evidence = _report_candidate_facts(session=session, run=run)
                facts = FrozenGovernanceCandidateFacts(
                    governance=governance, evidence=evidence
                )
                return generate_report_candidate(facts, report_contract_version)
        except GovernanceRunExecutionError as error:
            if error.code in {"artifact_read_failed", "netflow_artifact_unavailable"}:
                raise
            raise ReportCandidateError("report_facts_invalid") from None
        except (
            ValidationError,
            ValueError,
            TypeError,
            ReportCoreError,
            IPRecordContractError,
        ):
            raise ReportCandidateError("report_facts_invalid") from None
    comparison_facts = read_report_candidate_facts(
        session=session, tenant_id=tenant_id, project_id=project_id, run_id=run_id
    )
    return generate_report_candidate(comparison_facts, report_contract_version)
