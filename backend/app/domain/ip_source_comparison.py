from __future__ import annotations

import hashlib
import ipaddress
import json
import uuid
from collections import Counter
from collections.abc import Mapping, Set
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, col, select

from app.domain.ip_consistency import (
    IP_PROCESSING_CONTRACT_VERSION,
    IPObservation,
    ip_observation_sort_key,
    normalize_ip,
)
from app.domain.models import (
    AuditEvent,
    GovernanceRun,
    NetFlowIPActivity,
    Observation,
    ObservationResourceLink,
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


def read_ip_source_comparison(
    *, session: Session, tenant_id: uuid.UUID, project_id: uuid.UUID, run_id: uuid.UUID
) -> RunIPSourceComparison:
    """Derive a historical comparison solely from immutable published DB facts.

    No Artifact reads, current Project selections, Finding reads or writes. The
    publication audit carries the atomic aggregation receipt, including zero rows.
    """
    with session.no_autoflush:
        return _read_comparison(
            session=session, tenant_id=tenant_id, project_id=project_id, run_id=run_id
        )


def _read_comparison(
    *, session: Session, tenant_id: uuid.UUID, project_id: uuid.UUID, run_id: uuid.UUID
) -> RunIPSourceComparison:
    run = session.exec(
        select(GovernanceRun).where(
            GovernanceRun.id == run_id,
            GovernanceRun.project_id == project_id,
            GovernanceRun.tenant_id == tenant_id,
        )
    ).one_or_none()
    if run is None:
        raise IPSourceComparisonError("run_not_found")
    if (
        run.status not in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}
        or run.completed_at is None
    ):
        raise IPSourceComparisonError("run_not_published")
    if (
        run.input_contract_version != "governance-run-input-v1"
        or run.processing_contract_version != IP_PROCESSING_CONTRACT_VERSION
    ):
        raise IPSourceComparisonError("comparison_contract_unsupported")

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
    for code in ("NORMALIZE", "RESOLVE", "CHECK_FINDINGS", "PUBLISH"):
        _require(
            code in steps
            and steps[code].status == "SUCCEEDED"
            and steps[code].output_hash is not None
        )
    publications = session.exec(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.project_id == project_id,
            AuditEvent.target_id == run_id,
            AuditEvent.target_type == "governance_run",
            AuditEvent.action == "governance_run.published",
        )
    ).all()
    _require(len(publications) == 1 and isinstance(publications[0].after_data, dict))
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
    receipt = publication.get("netflow_activity")
    if run.netflow_dataset_id is not None and "netflow_activity" not in publication:
        raise IPSourceComparisonError("comparison_contract_unsupported")

    by_source, observations, links = read_comparison_source_facts(
        session=session, run=run, steps=steps
    )
    links_by_observation = {link.observation_id: link for link in links}
    activities = session.exec(
        select(NetFlowIPActivity).where(
            NetFlowIPActivity.governance_run_id == run_id,
            NetFlowIPActivity.project_id == project_id,
            NetFlowIPActivity.tenant_id == tenant_id,
        )
    ).all()
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

    if run.netflow_dataset_id is None:
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
        if receipt["contract_version"] != NETFLOW_ACTIVITY_CONTRACT_VERSION:
            raise IPSourceComparisonError("comparison_contract_unsupported")
        _require(
            "LOAD_NETFLOW" in steps
            and steps["LOAD_NETFLOW"].status == "SUCCEEDED"
            and steps["LOAD_NETFLOW"].output_hash == run.netflow_content_sha256
        )
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
                and activity.flow_count > 0
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

    return compile_ip_source_comparison(
        tenant_id=tenant_id,
        project_id=project_id,
        run_id=run_id,
        resources={item.id: str(item.canonical_key) for item in resources},
        membership=membership,
        active_resources={item.resource_id for item in activities},
        netflow_present=run.netflow_dataset_id is not None,
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
            SourceSnapshot.project_id == project_id,
            SourceSnapshot.tenant_id == tenant_id,
        )
    ).all()
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
                Observation.project_id == project_id,
                Observation.tenant_id == tenant_id,
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
            ObservationResourceLink.project_id == project_id,
            ObservationResourceLink.tenant_id == tenant_id,
        )
    ).all()
    links_by_observation = {link.observation_id: link for link in links}
    _require(
        len(links) == len(observations)
        and set(links_by_observation) == {item.id for item in observations}
    )
    return by_source, observations, list(links)
