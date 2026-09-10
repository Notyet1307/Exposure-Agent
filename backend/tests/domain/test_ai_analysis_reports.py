import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from app.core.config import settings
from app.domain import ai_analysis_reports as service
from app.domain.model_qualification import ModelBinding
from app.domain.models import Project


def test_report_permission_pins_scope_sources_content_but_not_capture_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, run_id = uuid.uuid4(), uuid.uuid4()
    material = {
        "captured_at": "2026-09-10T00:00:00Z",
        "summary": {"count": 0},
        "items": [],
        "gaps": ["UNKNOWN"],
    }
    sources = [
        {
            "source_type": "CUSTOMER_UPLOAD",
            "input_id": str(uuid.uuid4()),
            "snapshot_id": str(uuid.uuid4()),
            "content_sha256": "a" * 64,
        }
    ]
    binding = ModelBinding(
        endpoint="https://ai-api-gateway.app.baizhi.cloud/api/openai",
        resolved_address="1.1.1.1",
        model_identity="fixture",
        protocol="responses",
        config_revision="fixture",
        runner_build_version="fixture",
        agent_compose_runtime_version="fixture",
        config_fingerprint="b" * 64,
    )
    monkeypatch.setattr(settings, "AI_ANALYSIS_REPORT_ALLOW_BAIZHI_TEST", True)
    monkeypatch.setattr(
        settings,
        "AI_ANALYSIS_REPORT_SYNTHETIC_MANIFEST",
        json.dumps(
            [
                {
                    "project_id": str(project_id),
                    "run_id": str(run_id),
                    "sources": sources,
                    "material_sha256": service.material_hash(material),
                }
            ]
        ),
    )
    arguments: dict[str, Any] = {
        "binding": binding,
        "project_id": project_id,
        "run_id": run_id,
        "material": material,
        "sources": sources,
    }
    service.authorize_material(
        **{**arguments, "material": {**material, "captured_at": "2026-09-10T01:00:00Z"}}
    )
    for changed in (
        {"project_id": uuid.uuid4()},
        {"run_id": uuid.uuid4()},
        {"material": {**material, "summary": {"customer_text": "not synthetic"}}},
        {"sources": [{**sources[0], "input_id": str(uuid.uuid4())}]},
    ):
        with pytest.raises(
            service.AnalysisReportError, match="^synthetic_material_denied$"
        ):
            service.authorize_material(**{**arguments, **changed})
    monkeypatch.setattr(settings, "AI_ANALYSIS_REPORT_ALLOW_BAIZHI_TEST", False)
    with pytest.raises(
        service.AnalysisReportError, match="^synthetic_material_denied$"
    ):
        service.authorize_material(**arguments)


def test_prepared_material_keeps_different_asset_histories_and_query_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Input attribution regression, not a claim to validate generated prose."""
    project = Project(id=uuid.uuid4(), tenant_id=uuid.uuid4(), name="Synthetic report")
    runs = [str(uuid.uuid4()) for _ in range(4)]
    run_id, report_id = uuid.UUID(runs[-1]), uuid.uuid4()
    now = datetime.now(UTC).isoformat()
    trajectories = {
        "198.51.100.81": [
            ("customer_upload_only", "OPENED"),
            ("matched", "CLOSED"),
            ("matched", None),
            ("customer_upload_only", "REOPENED"),
        ],
        "203.0.113.6": [
            ("customer_upload_only", "OPENED"),
            ("customer_upload_only", None),
            ("matched", "CLOSED"),
            ("matched", None),
        ],
    }
    investigations = []
    expected = {}
    for ip, trajectory in trajectories.items():
        resource_id = str(uuid.uuid4())
        expected[resource_id] = ip
        snapshots: list[dict[str, Any]] = []
        for historical_run, (classification, transition) in zip(
            runs, trajectory, strict=True
        ):
            identity = {"canonical_ip": ip, "resource_id": resource_id}
            facts: list[dict[str, Any]] = [
                {"kind": "COMPARISON", **identity, "classification": classification}
            ]
            if transition or classification == "customer_upload_only":
                facts.append(
                    {
                        "kind": "FINDING",
                        **identity,
                        "transition_type": transition,
                        "occurrence_id": str(uuid.uuid4())
                        if classification == "customer_upload_only"
                        else None,
                    }
                )
            snapshots.append(
                {
                    "scope": {"run_id": historical_run, "resource_id": resource_id},
                    "items": [
                        {"citation_id": str(uuid.uuid4()), "fact": fact}
                        for fact in facts
                    ],
                }
            )
        history = [
            {
                "citation_id": str(uuid.uuid4()),
                "fact": {
                    "kind": "ASSET_HISTORY",
                    "resource_id": resource_id,
                    "run_id": runs[-1],
                    "historical_run_id": snapshot["scope"]["run_id"],
                    "material": snapshot,
                },
            }
            for snapshot in reversed(snapshots[:-1])
        ]
        live = {
            "canonical_ip": ip,
            "resource_id": resource_id,
            "run_id": runs[-1],
            "queried_at": now,
            "result": "FOUND" if ip == "203.0.113.6" else "NO_DATA",
        }
        reads = []
        for tool_name, items, result in (
            ("read_asset_facts", snapshots[-1]["items"], {"result": "FOUND"}),
            ("read_asset_history", history, {"result": "FOUND"}),
            (
                "read_cloudatlas_asset",
                [{"citation_id": str(uuid.uuid4()), "fact": live}]
                if live["result"] == "FOUND"
                else [],
                live,
            ),
        ):
            reads.append(
                {
                    "id": str(uuid.uuid4()),
                    "status": "SUCCEEDED",
                    "tool_name": tool_name,
                    "completed_at": now,
                    "queried_at": now,
                    "result": result,
                    "items": items,
                }
            )
        investigations.append(
            SimpleNamespace(
                id=uuid.uuid4(),
                resource_id=resource_id,
                status="FAILED",
                tool_reads=reads,
            )
        )
    summary = {
        "report_identity": {"run_completed_at": now},
        "input_completeness": {"sources": []},
        "ip_consistency_summary": {"matched": 1, "customer_upload_only": 1},
        "finding_type_directions_and_limitations": {},
        "provenance": {},
        "current_run_lifecycle_changes": {"changes": [], "reopened": 1},
        "open_backlog_as_of_run": {"findings": []},
    }
    report = SimpleNamespace(
        id=report_id,
        report_contract_version="deterministic-report-v1",
        canonical_content={"report": summary},
    )
    session = Mock()
    session.get.return_value = SimpleNamespace(id=run_id)
    session.exec.side_effect = [
        Mock(one_or_none=lambda: report),
        Mock(all=lambda: investigations),
        Mock(all=list),
    ]
    monkeypatch.setattr(service, "get_published_report_record", lambda **kwargs: report)
    monkeypatch.setattr(service, "validate_published_report", lambda **kwargs: None)
    material, _ = service.prepare_material(
        session=session,
        project=project,
        run_id=run_id,
        max_bytes=65536,
    )
    assert (
        material["summary"]["ip_consistency_summary"]
        == summary["ip_consistency_summary"]
    )
    assert material["truncated"] is False
    obtained = [
        item["data"]
        for item in material["items"]
        if item["kind"] == "OBTAINED_TOOL_READ"
    ]
    assert len(obtained) == 6
    for data in obtained:
        resource_id = data["resource_id"]
        ip = expected[resource_id]
        assert data["run_id"] == runs[-1]
        if data["tool_name"] == "read_cloudatlas_asset":
            assert data["result"]["queried_at"] == data["queried_at"]
            assert data["result"]["canonical_ip"] == ip
            if ip == "198.51.100.81":
                assert data["items"] == [] and data["result"]["result"] == "NO_DATA"
                assert any(
                    f"Tool read {item['identity']} returned no evidence items."
                    in material["gaps"]
                    for item in material["items"]
                    if item["data"] == data
                )
            else:
                assert data["items"][0]["fact"]["canonical_ip"] == ip
            continue
        if data["tool_name"] == "read_asset_history":
            snapshots_to_check = []
            for entry in reversed(data["items"]):
                fact = entry["fact"]
                assert fact["run_id"] == runs[-1]
                assert fact["resource_id"] == resource_id
                assert fact["historical_run_id"] == fact["material"]["scope"]["run_id"]
                assert fact["material"]["scope"]["resource_id"] == resource_id
                snapshots_to_check.append(
                    (fact["historical_run_id"], fact["material"]["items"])
                )
            assert [run for run, _ in snapshots_to_check] == runs[:-1]
        else:
            snapshots_to_check = [(runs[-1], data["items"])]
        for fact_run, items in snapshots_to_check:
            facts = [item["fact"] for item in items]
            assert all(
                (fact["canonical_ip"], fact["resource_id"]) == (ip, resource_id)
                for fact in facts
            )
            comparison = next(fact for fact in facts if fact["kind"] == "COMPARISON")
            finding = next((fact for fact in facts if fact["kind"] == "FINDING"), {})
            assert (
                comparison["classification"],
                finding.get("transition_type"),
            ) == trajectories[ip][runs.index(fact_run)]
            if ip == "203.0.113.6" and fact_run == runs[1]:
                assert finding["occurrence_id"] is not None
