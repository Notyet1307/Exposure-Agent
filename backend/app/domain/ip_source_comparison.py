from __future__ import annotations

import hashlib
import ipaddress
import json
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, col, select

from app.domain.governance_publication import is_published_run
from app.domain.ip_consistency import (
    IP_PROCESSING_CONTRACT_VERSION,
    IPObservation,
    ip_observation_sort_key,
    normalize_ip,
)
from app.domain.models import (
    AuditEvent,
    Evidence,
    GovernanceReport,
    GovernanceRun,
    GovernanceRunSourcePublic,
    GovernanceRunSourcesPublic,
    IPSourceComparisonFact,
    IPSourceComparisonPublic,
    IPSourceComparisonsPublic,
    NetFlowIPActivity,
    Observation,
    ObservationResourceLink,
    Project,
    Resource,
    RunStep,
    SourceSnapshot,
)
from app.domain.netflow_activity import (
    NETFLOW_ACTIVITY_CONTRACT_VERSION,
    NetFlowIPActivityAggregate,
    netflow_activity_content_hash,
    netflow_activity_output_hash,
)
from app.domain.netflow_datasets import NETFLOW_DATASET_CONTRACT_VERSION

COMPARISON_CONTRACT_VERSION: Literal["ip-source-comparison/v1"] = (
    "ip-source-comparison/v1"
)
_CLASSIFICATIONS = {
    (True, True): ("matched", "observed_in_both_sources"),
    (True, False): ("customer_upload_only", "observed_in_customer_upload_only"),
    (False, True): ("cloudatlas_only", "observed_in_cloudatlas_only"),
    (False, False): ("neither_source_observed", "not_observed_in_either_source"),
}


class IPSourceComparisonError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class IPSourceComparison(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    resource_id: uuid.UUID
    canonical_ip: str
    customer_upload_present: bool
    cloudatlas_present: bool
    netflow_status: Literal["ACTIVE", "UNKNOWN"]
    classification: str
    classification_reason: str
    netflow_reason: str
    content_hash: str


class RunIPSourceComparison(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["ip-source-comparison/v1"] = COMPARISON_CONTRACT_VERSION
    tenant_id: uuid.UUID
    project_id: uuid.UUID
    governance_run_id: uuid.UUID
    results: tuple[IPSourceComparison, ...]
    output_hash: str


def comparison_fact_id(governance_run_id: uuid.UUID, canonical_ip: str) -> uuid.UUID:
    """Stable Run-scoped identity, independent of classification and content."""
    if normalize_ip(canonical_ip) != canonical_ip:
        raise ValueError("comparison IP is not canonical")
    return uuid.uuid5(
        governance_run_id, f"{COMPARISON_CONTRACT_VERSION}/{canonical_ip}"
    )


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _require(condition: bool) -> None:
    if not condition:
        raise IPSourceComparisonError("comparison_facts_invalid")


def _ip_order(value: str) -> tuple[int, int]:
    address = ipaddress.ip_address(value)
    return address.version, int(address)


@dataclass(frozen=True)
class _PublishedIPSourceFacts:
    resources: dict[uuid.UUID, str]
    membership: dict[uuid.UUID, set[str]]
    activities: list[NetFlowIPActivity]
    netflow_status: Literal[
        "INPUT_UNMODELED", "INPUT_ABSENT", "ACTIVITY_UNMODELED", "NO_POSITIVE_ACTIVITY"
    ]


def read_published_netflow_activities(
    *, session: Session, run: GovernanceRun
) -> tuple[
    Literal[
        "INPUT_UNMODELED", "INPUT_ABSENT", "ACTIVITY_UNMODELED", "NO_POSITIVE_ACTIVITY"
    ],
    list[NetFlowIPActivity],
]:
    """Return the complete, verified immutable collection, without Artifact I/O."""
    with session.no_autoflush:
        facts = _read_published_facts(
            session=session,
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            run_id=run.id,
            allow_unmodeled=True,
        )
        return facts.netflow_status, facts.activities


def read_ip_source_comparison(
    *, session: Session, tenant_id: uuid.UUID, project_id: uuid.UUID, run_id: uuid.UUID
) -> RunIPSourceComparison:
    """Derive a historical comparison solely from immutable published DB facts.

    No Artifact reads, current Project selections, Finding reads or writes. The
    publication audit carries the atomic aggregation receipt, including zero rows.
    """
    with session.no_autoflush:
        facts = _read_published_facts(
            session=session, tenant_id=tenant_id, project_id=project_id, run_id=run_id
        )
        return compile_ip_source_comparison(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            resources=facts.resources,
            membership=facts.membership,
            active_resources={item.resource_id for item in facts.activities},
            netflow_present=facts.netflow_status != "INPUT_ABSENT",
        )


def _published_comparison_context(
    *, session: Session, project: Project, run_id: uuid.UUID
) -> tuple[GovernanceRun, GovernanceReport, RunIPSourceComparison]:
    run = session.exec(
        select(GovernanceRun).where(
            GovernanceRun.id == run_id,
            GovernanceRun.project_id == project.id,
            GovernanceRun.tenant_id == project.tenant_id,
        )
    ).one_or_none()
    if run is None:
        raise IPSourceComparisonError("run_not_found")
    if not is_published_run(run):
        raise IPSourceComparisonError("run_not_published")

    # Local import keeps the report validator's comparison dependency acyclic.
    from app.domain.governance_reports import (
        SUPPORTED_REPORT_CONTRACT_VERSIONS,
        validate_published_report,
    )
    from app.domain.report_core import REPORT_CONTRACT_VERSION

    if run.report_contract_version not in SUPPORTED_REPORT_CONTRACT_VERSIONS:
        raise IPSourceComparisonError("comparison_contract_unsupported")
    comparison = read_ip_source_comparison(
        session=session,
        tenant_id=project.tenant_id,
        project_id=project.id,
        run_id=run_id,
    )
    reports = session.exec(
        select(GovernanceReport).where(
            GovernanceReport.governance_run_id == run.id,
            GovernanceReport.project_id == project.id,
            GovernanceReport.tenant_id == project.tenant_id,
        )
    ).all()
    _require(
        len(reports) == 1
        and reports[0].report_contract_version == run.report_contract_version
    )
    report = reports[0]
    publications = session.exec(
        select(AuditEvent).where(
            AuditEvent.target_id == run.id,
            AuditEvent.target_type == "governance_run",
            AuditEvent.action == "governance_run.published",
            AuditEvent.project_id == project.id,
            AuditEvent.tenant_id == project.tenant_id,
        )
    ).all()
    _require(
        len(publications) == 1
        and isinstance(publications[0].after_data, dict)
        and publications[0].after_data.get("governance_report_id") == str(report.id)
    )
    validate_published_report(session=session, project=project, report=report)
    if report.report_contract_version == REPORT_CONTRACT_VERSION:
        _require(
            session.exec(
                select(IPSourceComparisonFact.id)
                .where(IPSourceComparisonFact.governance_run_id == run.id)
                .limit(1)
            ).first()
            is None
        )
        _require(
            session.exec(
                select(Evidence.id)
                .where(
                    Evidence.governance_run_id == run.id,
                    col(Evidence.ip_source_comparison_fact_id).is_not(None),
                )
                .limit(1)
            ).first()
            is None
        )
    return run, report, comparison


def read_governance_run_sources(
    *, session: Session, project: Project, run_id: uuid.UUID
) -> GovernanceRunSourcesPublic:
    run, report, _comparison = _published_comparison_context(
        session=session, project=project, run_id=run_id
    )
    return _project_governance_run_sources(
        session=session, project=project, run=run, report=report
    )


def _project_governance_run_sources(
    *, session: Session, project: Project, run: GovernanceRun, report: GovernanceReport
) -> GovernanceRunSourcesPublic:
    """Project slots only after the shared published context has been verified."""
    snapshots = session.exec(
        select(SourceSnapshot).where(
            SourceSnapshot.governance_run_id == run.id,
            SourceSnapshot.project_id == project.id,
            SourceSnapshot.tenant_id == project.tenant_id,
        )
    ).all()
    by_source = {snapshot.source_type: snapshot for snapshot in snapshots}
    expected_sources = {"CUSTOMER_UPLOAD", "CLOUDATLAS"}
    if run.netflow_dataset_id is not None:
        expected_sources.add("NETFLOW")
    _require(set(by_source) == expected_sources and len(snapshots) == len(by_source))

    sources: list[GovernanceRunSourcePublic] = []
    for source_type in ("CUSTOMER_UPLOAD", "CLOUDATLAS", "NETFLOW"):
        snapshot = by_source.get(source_type)
        if snapshot is None:
            _require(source_type == "NETFLOW" and run.netflow_dataset_id is None)
            sources.append(
                GovernanceRunSourcePublic(
                    source_type="NETFLOW",
                    state="ABSENT",
                    snapshot_id=None,
                    input_id=None,
                    content_sha256=None,
                    schema_fingerprint=None,
                    method_fingerprint=None,
                    record_count=None,
                    valid_time_start_utc=None,
                    valid_time_end_utc=None,
                )
            )
            continue
        input_ids = (
            snapshot.customer_upload_id,
            snapshot.source_instance_id,
            snapshot.netflow_dataset_id,
        )
        present_input_ids = [input_id for input_id in input_ids if input_id is not None]
        _require(len(present_input_ids) == 1)
        sources.append(
            GovernanceRunSourcePublic.model_validate(
                {
                    "source_type": source_type,
                    "state": "PRESENT",
                    "snapshot_id": snapshot.id,
                    "input_id": present_input_ids[0],
                    "content_sha256": snapshot.content_sha256,
                    "schema_fingerprint": snapshot.schema_fingerprint,
                    "method_fingerprint": snapshot.method_fingerprint,
                    "record_count": snapshot.record_count,
                    "valid_time_start_utc": snapshot.valid_time_start_utc,
                    "valid_time_end_utc": snapshot.valid_time_end_utc,
                }
            )
        )
    _require(run.completed_at is not None)
    return GovernanceRunSourcesPublic.model_validate(
        {
            "project_id": project.id,
            "governance_run_id": run.id,
            "governance_report_id": report.id,
            "run_status": run.status,
            "completed_at": run.completed_at,
            "input_contract_version": run.input_contract_version,
            "processing_contract_version": run.processing_contract_version,
            "report_contract_version": report.report_contract_version,
            "sources": sources,
        }
    )


def list_governance_run_ip_source_comparisons(
    *,
    session: Session,
    project: Project,
    run_id: uuid.UUID,
    classification: str | None,
    netflow_status: str | None,
    skip: int,
    limit: int,
) -> IPSourceComparisonsPublic:
    _run, report, comparison = _published_comparison_context(
        session=session, project=project, run_id=run_id
    )
    filtered = (
        row
        for row in comparison.results
        if (classification is None or row.classification == classification)
        and (netflow_status is None or row.netflow_status == netflow_status)
    )
    ordered = sorted(
        filtered,
        key=lambda row: (_ip_order(row.canonical_ip), str(row.resource_id)),
    )
    page = ordered[skip : skip + limit]
    return IPSourceComparisonsPublic(
        project_id=project.id,
        governance_run_id=run_id,
        governance_report_id=report.id,
        report_contract_version=cast(
            Literal["deterministic-report-v1", "deterministic-report-v2"],
            report.report_contract_version,
        ),
        contract_version=COMPARISON_CONTRACT_VERSION,
        output_hash=comparison.output_hash,
        data=[
            IPSourceComparisonPublic.model_validate(row.model_dump()) for row in page
        ],
        count=len(ordered),
        page_size=len(page),
    )


def _verify_publication(
    *,
    run: GovernanceRun,
    steps: Mapping[str, RunStep],
    publications: Sequence[AuditEvent],
) -> dict[str, Any]:
    for code in ("NORMALIZE", "RESOLVE", "CHECK_FINDINGS", "PUBLISH"):
        _require(
            code in steps
            and steps[code].status == "SUCCEEDED"
            and steps[code].output_hash is not None
        )
    _require(len(publications) == 1 and isinstance(publications[0].after_data, dict))
    _require(
        publications[0].tenant_id == run.tenant_id
        and publications[0].project_id == run.project_id
    )
    publication = publications[0].after_data
    assert publication is not None
    publish_output: dict[str, Any] = {
        "processing_contract_version": run.processing_contract_version,
        "check_findings_output_hash": steps["CHECK_FINDINGS"].output_hash,
    }
    if "netflow_activity" in publication:
        publish_output["netflow_activity"] = publication["netflow_activity"]
    if run.report_contract_version is not None:
        _require(
            "VALIDATE_REPORT" in steps
            and steps["VALIDATE_REPORT"].status == "SUCCEEDED"
            and steps["VALIDATE_REPORT"].output_hash is not None
        )
        _require(isinstance(publication.get("governance_report_id"), str))
        publish_output.update(
            validated_report_output_hash=steps["VALIDATE_REPORT"].output_hash,
            governance_report_id=publication["governance_report_id"],
        )
    _require(_hash(publish_output) == steps["PUBLISH"].output_hash)
    return publication


def _read_published_facts(
    *,
    session: Session,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    allow_unmodeled: bool = False,
) -> _PublishedIPSourceFacts:
    run = session.exec(
        select(GovernanceRun).where(
            GovernanceRun.id == run_id,
            GovernanceRun.project_id == project_id,
            GovernanceRun.tenant_id == tenant_id,
        )
    ).one_or_none()
    if run is None:
        raise IPSourceComparisonError("run_not_found")
    if not is_published_run(run):
        raise IPSourceComparisonError("run_not_published")
    if allow_unmodeled and run.input_contract_version is None:
        _require(
            all(
                value is None
                for value in (
                    run.input_hash,
                    run.netflow_dataset_id,
                    run.netflow_content_sha256,
                    run.netflow_dataset_contract_version,
                )
            )
        )
        _require(
            session.exec(
                select(SourceSnapshot.id)
                .where(
                    SourceSnapshot.governance_run_id == run_id,
                    SourceSnapshot.source_type == "NETFLOW",
                )
                .limit(1)
            ).first()
            is None
        )
        _require(
            session.exec(
                select(NetFlowIPActivity.id)
                .where(NetFlowIPActivity.governance_run_id == run_id)
                .limit(1)
            ).first()
            is None
        )
        publications = session.exec(
            select(AuditEvent).where(
                AuditEvent.target_id == run_id,
                AuditEvent.target_type == "governance_run",
                AuditEvent.action == "governance_run.published",
            )
        ).all()
        _require(
            all(
                isinstance(item.after_data, dict)
                and "netflow_activity" not in item.after_data
                for item in publications
            )
        )
        if publications:
            steps = {
                step.step_code: step
                for step in session.exec(
                    select(RunStep).where(
                        RunStep.governance_run_id == run_id,
                        RunStep.project_id == project_id,
                        RunStep.tenant_id == tenant_id,
                    )
                ).all()
            }
            _verify_publication(run=run, steps=steps, publications=publications)
        return _PublishedIPSourceFacts({}, {}, [], "INPUT_UNMODELED")
    if (
        run.input_contract_version != "governance-run-input-v1"
        or run.processing_contract_version != IP_PROCESSING_CONTRACT_VERSION
    ):
        raise IPSourceComparisonError("comparison_contract_unsupported")
    # The runner also consumes comparison DTOs; defer this canonical pin helper.
    from app.domain.governance_runs import pinned_inputs_for_run

    netflow_pins = (
        run.netflow_dataset_id,
        run.netflow_content_sha256,
        run.netflow_dataset_contract_version,
    )
    _require(
        all(value is None for value in netflow_pins)
        or all(value is not None for value in netflow_pins)
    )
    _require(
        run.netflow_dataset_contract_version in (None, NETFLOW_DATASET_CONTRACT_VERSION)
        and run.input_hash == pinned_inputs_for_run(run).input_hash()
    )

    steps = {
        step.step_code: step
        for step in session.exec(
            select(RunStep).where(
                RunStep.governance_run_id == run_id,
                RunStep.project_id == project_id,
                RunStep.tenant_id == tenant_id,
            )
        ).all()
    }
    publications = session.exec(
        select(AuditEvent).where(
            AuditEvent.target_id == run_id,
            AuditEvent.target_type == "governance_run",
            AuditEvent.action == "governance_run.published",
        )
    ).all()
    publication = _verify_publication(run=run, steps=steps, publications=publications)
    receipt = publication.get("netflow_activity")
    # A missing receipt is a compatibility distinction; malformed receipts fail below.
    if (
        not allow_unmodeled
        and run.netflow_dataset_id is not None
        and "netflow_activity" not in publication
    ):
        raise IPSourceComparisonError("comparison_contract_unsupported")

    by_source, observations, links = read_comparison_source_facts(
        session=session, run=run, steps=steps
    )
    links_by_observation = {link.observation_id: link for link in links}
    activities = session.exec(
        select(NetFlowIPActivity).where(
            NetFlowIPActivity.governance_run_id == run_id,
        )
    ).all()
    _require(
        all(
            item.project_id == project_id and item.tenant_id == tenant_id
            for item in activities
        )
    )
    resource_ids = {link.resource_id for link in links} | {
        item.resource_id for item in activities
    }
    # A subquery avoids an unbounded SQL parameter list for large Run populations.
    linked_ids = select(ObservationResourceLink.resource_id).where(
        ObservationResourceLink.governance_run_id == run_id,
        ObservationResourceLink.project_id == project_id,
        ObservationResourceLink.tenant_id == tenant_id,
    )
    active_ids = select(NetFlowIPActivity.resource_id).where(
        NetFlowIPActivity.governance_run_id == run_id,
        NetFlowIPActivity.project_id == project_id,
        NetFlowIPActivity.tenant_id == tenant_id,
    )
    resources = session.exec(
        select(Resource).where(
            Resource.project_id == project_id,
            Resource.tenant_id == tenant_id,
            Resource.resource_type == "IP",
            col(Resource.id).in_(linked_ids.union(active_ids)),
        )
    ).all()
    resources_by_id = {resource.id: resource for resource in resources}
    _require(set(resources_by_id) == resource_ids)
    for resource in resources:
        _require(
            normalize_ip(str(resource.canonical_key)) == str(resource.canonical_key)
        )
    membership: dict[uuid.UUID, set[str]] = {
        resource_id: set() for resource_id in resource_ids
    }
    for observation in observations:
        link = links_by_observation[observation.id]
        _require(link.processing_contract_version == run.processing_contract_version)
        _require(
            str(resources_by_id[link.resource_id].canonical_key)
            == str(observation.canonical_ip)
        )
        membership[link.resource_id].add(observation.source_type)

    netflow_status: Literal[
        "INPUT_UNMODELED", "INPUT_ABSENT", "ACTIVITY_UNMODELED", "NO_POSITIVE_ACTIVITY"
    ] = "NO_POSITIVE_ACTIVITY"
    if run.netflow_dataset_id is None:
        netflow_status = "INPUT_ABSENT"
        _require("LOAD_NETFLOW" not in steps)
        _require(
            receipt is None and "netflow_activity" not in publication and not activities
        )
        _require(
            run.netflow_content_sha256 is None
            and run.netflow_dataset_contract_version is None
        )
    else:
        snapshot = by_source["NETFLOW"]
        _require(
            snapshot.netflow_dataset_id == run.netflow_dataset_id
            and snapshot.content_sha256 == run.netflow_content_sha256
        )
        _require(
            "LOAD_NETFLOW" in steps
            and steps["LOAD_NETFLOW"].status == "SUCCEEDED"
            and steps["LOAD_NETFLOW"].output_hash == run.netflow_content_sha256
        )
        if "netflow_activity" not in publication:
            _require(not activities)
            return _PublishedIPSourceFacts(
                resources={item.id: str(item.canonical_key) for item in resources},
                membership=membership,
                activities=[],
                netflow_status="ACTIVITY_UNMODELED",
            )
        _require(isinstance(receipt, dict))
        assert isinstance(receipt, dict)
        _require(
            set(receipt)
            == {
                "contract_version",
                "source_snapshot_id",
                "activity_count",
                "output_hash",
            }
        )
        _require(
            isinstance(receipt["contract_version"], str)
            and bool(receipt["contract_version"].strip())
        )
        _require(receipt["contract_version"] == NETFLOW_ACTIVITY_CONTRACT_VERSION)
        _require(receipt["source_snapshot_id"] == str(snapshot.id))
        _require(
            type(receipt["activity_count"]) is int
            and receipt["activity_count"] == len(activities)
        )
        aggregates = []
        for activity in sorted(
            activities,
            key=lambda item: _ip_order(
                str(resources_by_id[item.resource_id].canonical_key)
            ),
        ):
            canonical_ip = str(resources_by_id[activity.resource_id].canonical_key)
            _require(
                activity.source_snapshot_id == snapshot.id
                and activity.source_type == "NETFLOW"
            )
            _require(
                activity.aggregation_contract_version
                == NETFLOW_ACTIVITY_CONTRACT_VERSION
                and type(activity.flow_count) is int
                and 1 <= activity.flow_count <= 2147483647
            )
            _require(
                activity.id
                == uuid.uuid5(
                    run_id, f"{NETFLOW_ACTIVITY_CONTRACT_VERSION}/{canonical_ip}"
                )
            )
            aggregate = NetFlowIPActivityAggregate(
                canonical_ip=canonical_ip,
                flow_count=activity.flow_count,
                peer_ips=tuple(str(ip) for ip in activity.peer_ips),
                protocols=tuple(activity.protocols),
                first_seen_utc=activity.first_seen_utc,
                last_seen_utc=activity.last_seen_utc,
            )
            _require(
                netflow_activity_content_hash(aggregate) == activity.content_sha256
            )
            aggregates.append(aggregate)
        _require(len({item.resource_id for item in activities}) == len(activities))
        _require(
            netflow_activity_output_hash(tuple(aggregates)) == receipt["output_hash"]
        )

    return _PublishedIPSourceFacts(
        resources={item.id: str(item.canonical_key) for item in resources},
        membership=membership,
        activities=list(activities),
        netflow_status=netflow_status,
    )


def compile_ip_source_comparison(
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    resources: Mapping[uuid.UUID, str],
    membership: Mapping[uuid.UUID, Set[str]],
    active_resources: Set[uuid.UUID],
    netflow_present: bool,
) -> RunIPSourceComparison:
    """Project validated scoped facts; callers own their lifecycle proof."""
    included = set(membership) | set(active_resources)
    _require(included <= resources.keys())
    _require(netflow_present or not active_resources)
    _require(len(set(resources.values())) == len(resources))
    for resource_id in included:
        _require(normalize_ip(resources[resource_id]) == resources[resource_id])
        _require(
            membership.get(resource_id, set()) <= {"CUSTOMER_UPLOAD", "CLOUDATLAS"}
        )
    scope = {
        "contract_version": COMPARISON_CONTRACT_VERSION,
        "tenant_id": str(tenant_id),
        "project_id": str(project_id),
        "governance_run_id": str(run_id),
    }
    results = []
    for resource_id in sorted(included, key=lambda key: _ip_order(resources[key])):
        sources = membership.get(resource_id, set())
        customer = "CUSTOMER_UPLOAD" in sources
        cloudatlas = "CLOUDATLAS" in sources
        active = resource_id in active_resources
        if not customer and not cloudatlas and not active:
            continue
        classification, reason = _CLASSIFICATIONS[customer, cloudatlas]
        row = {
            "resource_id": str(resource_id),
            "canonical_ip": resources[resource_id],
            "customer_upload_present": customer,
            "cloudatlas_present": cloudatlas,
            "netflow_status": "ACTIVE" if active else "UNKNOWN",
            "classification": classification,
            "classification_reason": reason,
            "netflow_reason": "positive_activity_observed"
            if active
            else (
                "netflow_input_absent"
                if not netflow_present
                else "no_positive_activity_evidence"
            ),
        }
        row["content_hash"] = _hash({**scope, **row})
        results.append(row)
    return RunIPSourceComparison.model_validate(
        {
            **scope,
            "results": results,
            "output_hash": _hash({**scope, "results": results}),
        }
    )


def read_comparison_source_facts(
    *, session: Session, run: GovernanceRun, steps: Mapping[str, RunStep]
) -> tuple[dict[str, SourceSnapshot], list[Observation], list[ObservationResourceLink]]:
    """Read fixed source facts shared by pre- and post-publication adapters."""
    run_id, project_id, tenant_id = run.id, run.project_id, run.tenant_id
    snapshots = session.exec(
        select(SourceSnapshot).where(
            SourceSnapshot.governance_run_id == run_id,
        )
    ).all()
    _require(
        all(
            item.project_id == project_id and item.tenant_id == tenant_id
            for item in snapshots
        )
    )
    by_source = {snapshot.source_type: snapshot for snapshot in snapshots}
    expected_sources = {"CUSTOMER_UPLOAD", "CLOUDATLAS"}
    if run.netflow_dataset_id is not None:
        expected_sources.add("NETFLOW")
    _require(
        set(by_source) == expected_sources and len(snapshots) == len(expected_sources)
    )
    _require(by_source["CUSTOMER_UPLOAD"].customer_upload_id == run.customer_upload_id)
    _require(by_source["CUSTOMER_UPLOAD"].content_sha256 == run.customer_upload_sha256)
    _require(by_source["CLOUDATLAS"].source_instance_id == run.source_instance_id)
    for source, step_code in (
        ("CUSTOMER_UPLOAD", "LOAD_CUSTOMER"),
        ("CLOUDATLAS", "PULL_CLOUDATLAS"),
    ):
        _require(
            step_code in steps
            and steps[step_code].status == "SUCCEEDED"
            and steps[step_code].output_hash == by_source[source].content_sha256
        )

    observations = sorted(
        session.exec(
            select(Observation).where(
                Observation.governance_run_id == run_id,
            )
        ).all(),
        key=lambda item: ip_observation_sort_key(
            item.source_type, item.source_record_key, item.id
        ),
    )
    observation_counts = Counter(item.source_type for item in observations)
    for source in ("CUSTOMER_UPLOAD", "CLOUDATLAS"):
        _require(observation_counts[source] == by_source[source].record_count)
    normalized = []
    for observation in observations:
        _require(
            observation.project_id == project_id and observation.tenant_id == tenant_id
        )
        _require(observation.source_type in {"CUSTOMER_UPLOAD", "CLOUDATLAS"})
        _require(
            observation.source_snapshot_id == by_source[observation.source_type].id
        )
        normalized.append(
            IPObservation(
                source_type=observation.source_type,
                source_record_key=observation.source_record_key,
                raw_ip=observation.raw_ip,
                canonical_ip=str(observation.canonical_ip),
                cloudatlas_asset_id=observation.cloudatlas_asset_id,
                cloudatlas_status=observation.cloudatlas_status,
            ).as_dict()
        )
    _require(
        _hash(
            {
                "processing_contract_version": run.processing_contract_version,
                "observations": normalized,
            }
        )
        == steps["NORMALIZE"].output_hash
    )

    links = session.exec(
        select(ObservationResourceLink).where(
            ObservationResourceLink.governance_run_id == run_id,
        )
    ).all()
    _require(
        all(
            item.project_id == project_id and item.tenant_id == tenant_id
            for item in links
        )
    )
    links_by_observation = {link.observation_id: link for link in links}
    _require(
        len(links) == len(observations)
        and set(links_by_observation) == {item.id for item in observations}
    )
    return by_source, observations, list(links)
