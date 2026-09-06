"""Synthetic, explicitly worked comparison cases from Issue #176, not generated expectations."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.domain.report_candidates import FrozenReportCandidateFacts

AS_OF = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
TENANT_ID = uuid.UUID(int=1)
PROJECT_ID = uuid.UUID(int=2)
RUN_ID = uuid.UUID(int=3)
PROCESSING_CONTRACT = "ip-v1"
SOURCE_TYPES = ("CUSTOMER_UPLOAD", "CLOUDATLAS")
ORACLE_MODES = ("absent", "present-empty", "present-active")

# index, customer present, cloud present, positive activity, class, class reason.
SEVEN_ROWS = (
    (1, True, True, True, "matched", "observed_in_both_sources"),
    (2, True, True, False, "matched", "observed_in_both_sources"),
    (3, True, False, True, "customer_upload_only", "observed_in_customer_upload_only"),
    (4, True, False, False, "customer_upload_only", "observed_in_customer_upload_only"),
    (5, False, True, True, "cloudatlas_only", "observed_in_cloudatlas_only"),
    (6, False, True, False, "cloudatlas_only", "observed_in_cloudatlas_only"),
    (7, False, False, True, "neither_source_observed", "not_observed_in_either_source"),
)
DUAL_ROWS = (
    (1, True, True, False, "matched", "observed_in_both_sources"),
    (2, True, False, False, "customer_upload_only", "observed_in_customer_upload_only"),
    (3, False, True, False, "cloudatlas_only", "observed_in_cloudatlas_only"),
)


def reference_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def case_facts(
    mode: str, *, resource_count: int | None = None
) -> FrozenReportCandidateFacts:
    if resource_count is not None:
        if mode == "unobserved":
            rows = tuple(
                (
                    index,
                    True,
                    False,
                    False,
                    "customer_upload_only",
                    "observed_in_customer_upload_only",
                )
                for index in range(1, resource_count + 1)
            )
        else:
            rows = tuple(
                (index, True, True, False, "matched", "observed_in_both_sources")
                for index in range(1, resource_count + 1)
            )
    elif mode in {"zero", "present-zero"}:
        rows = ()
    else:
        rows = SEVEN_ROWS if mode == "present-active" else DUAL_ROWS
    present = mode.startswith("present-")
    scope = {
        "contract_version": "ip-source-comparison/v1",
        "tenant_id": str(TENANT_ID),
        "project_id": str(PROJECT_ID),
        "governance_run_id": str(RUN_ID),
    }
    results = []
    for index, customer, cloud, active, classification, reason in rows:
        row = {
            "resource_id": str(uuid.UUID(int=1000 + index)),
            "canonical_ip": f"192.0.2.{index}",
            "customer_upload_present": customer,
            "cloudatlas_present": cloud,
            "netflow_status": "ACTIVE" if active else "UNKNOWN",
            "classification": classification,
            "classification_reason": reason,
            "netflow_reason": "positive_activity_observed"
            if active
            else (
                "no_positive_activity_evidence" if present else "netflow_input_absent"
            ),
        }
        row["content_hash"] = reference_hash({**scope, **row})
        results.append(row)
    comparison = {
        **scope,
        "results": results,
        "output_hash": reference_hash({**scope, "results": results}),
    }
    sources = tuple(
        {
            "source_type": source,
            "source_snapshot_id": str(uuid.UUID(int=10 + index)),
            "content_sha256": ("a" if index == 0 else "b") * 64,
            "schema_version": "customer-schema-v1"
            if index == 0
            else "cloudatlas-schema-v1",
            "record_count": sum(row[1] if index == 0 else row[2] for row in rows),
            "complete": True,
        }
        for index, source in enumerate(SOURCE_TYPES)
    )
    snapshots = [
        {
            "governance_run_id": str(RUN_ID),
            "fact_type": "SOURCE_SNAPSHOT",
            "fact_id": str(source["source_snapshot_id"]),
        }
        for source in sources
    ]
    lifecycles = []
    available: list[dict[str, str]] = snapshots
    transitions = []
    backlog = []
    for index, customer, cloud, _active, _classification, _reason in rows:
        if customer == cloud:
            continue
        finding_id = str(uuid.UUID(int=2000 + index))
        transition_id = str(uuid.UUID(int=3000 + index))
        occurrence_id = str(uuid.UUID(int=4000 + index))
        finding_type = "UNOBSERVED_ASSET" if customer else "UNREPORTED_ASSET"
        occurrence = {"run_id": str(RUN_ID), "run_completed_at": AS_OF}
        transition = {**occurrence, "transition_type": "OPENED"}
        lifecycles.append(
            {
                "finding_id": finding_id,
                "finding_type": finding_type,
                "canonical_ip": f"192.0.2.{index}",
                "occurrences": [occurrence],
                "transitions": [transition],
            }
        )
        reference = {
            "governance_run_id": str(RUN_ID),
            "fact_type": "FINDING_TRANSITION",
            "fact_id": transition_id,
        }
        available.extend(
            [
                reference,
                {
                    "governance_run_id": str(RUN_ID),
                    "fact_type": "FINDING_OCCURRENCE",
                    "fact_id": occurrence_id,
                },
            ]
        )
        coverage = {
            "finding_id": finding_id,
            "finding_type": finding_type,
            "canonical_ip": f"192.0.2.{index}",
            "evidence_reference": reference,
        }
        transitions.append({**coverage, "transition_type": "OPENED"})
        backlog.append(coverage)
    evidence = {
        "governance_run_id": str(RUN_ID),
        "available_facts": available,
        "current_run_transitions": transitions,
        "open_backlog": backlog,
    }
    active_keys = [
        row["canonical_ip"] for row in results if row["netflow_status"] == "ACTIVE"
    ]
    aggregates = [
        {
            "canonical_ip": canonical_ip,
            "flow_count": 1,
            "peer_ips": ["198.51.100.250"],
            "protocols": [6],
            "first_seen_utc": None,
            "last_seen_utc": None,
        }
        for canonical_ip in active_keys
    ]
    result: dict[str, Any] = {
        "contract_version": "netflow-ip-activity-v1",
        "activities": aggregates,
    }
    result["output_hash"] = reference_hash(result)
    return FrozenReportCandidateFacts.model_validate(
        {
            "governance": {
                "run_id": str(RUN_ID),
                "project_id": str(PROJECT_ID),
                "completed_at": AS_OF,
                "processing_contract_version": PROCESSING_CONTRACT,
                "source_snapshots": sources,
                "customer_observed_resource_keys": [
                    row["canonical_ip"]
                    for row in results
                    if row["customer_upload_present"]
                ],
                "cloudatlas_observed_resource_keys": [
                    row["canonical_ip"] for row in results if row["cloudatlas_present"]
                ],
                "finding_lifecycles": lifecycles,
            },
            "evidence": evidence,
            "comparison": comparison,
            "netflow_snapshot": {
                "source_type": "NETFLOW",
                "source_snapshot_id": str(uuid.UUID(int=12)),
                "content_sha256": "c" * 64,
                "schema_version": "netflow-schema-v1",
                # A nonempty accepted Dataset can complete with no managed activity.
                "record_count": max(1, len(active_keys)),
            }
            if present
            else None,
            "netflow_activity": result if present else None,
        }
    )
