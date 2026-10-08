import json
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.config import settings
from app.domain import ai_analysis_reports as reports
from app.domain import v2_analysis_reports as v2
from app.domain.model_qualification import ModelBinding
from app.domain.models import AnalysisReport

RESULT = "10000000-0000-4000-8000-000000000298"
ADDRESS = "addr:" + "a" * 64


def material() -> dict[str, Any]:
    core = f"core:{RESULT}"
    address = f"address:{RESULT}:{ADDRESS}"
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "subject": {
            "subject_kind": "core_comparison_v2",
            "project_id": str(uuid.uuid4()),
            "result_id": RESULT,
            "supplement_binding_id": None,
            "audience": "management",
            "language": "zh",
            "address_key": None,
        },
        "identity": {"input_sha256": "a" * 64},
        "facts": {
            f"fact:{RESULT}:counts": {
                "kind": "counts",
                "value": {
                    "total_addresses": 3,
                    "both": 1,
                    "cloud_only": 1,
                    "customer_only": 1,
                },
                "evidence_refs": [core],
            }
        },
        "items": [{"citation_id": core}, {"citation_id": address}],
        "samples": [{"address_key": ADDRESS, "evidence_refs": [address]}],
        "limitations": ["本报告仅解读固定的客户与云图资料。"],
    }


def output(data: dict[str, Any]) -> dict[str, Any]:
    core, address = [item["citation_id"] for item in data["items"]]
    return {
        "contract_version": v2.OUTPUT_VERSION,
        "text": {
            "summary": ["fixed", "check"],
            "sections": [
                {
                    "id": key,
                    "claim_ids": [
                        "fixed" if key in ("conclusion", "appendix") else "check"
                    ],
                }
                for key in v2.REPORT_SECTIONS
            ],
            "claims": [
                {
                    "id": "fixed",
                    "type": "fact",
                    "fact_refs": list(data["facts"]),
                    "evidence_refs": [core],
                },
                {
                    "id": "check",
                    "type": "action",
                    "text": "请核对登记依据与云图采集范围，补充可比材料。",
                    "fact_refs": [],
                    "evidence_refs": [core],
                },
            ],
            "priority_cases": [
                {
                    "address_key": ADDRESS,
                    "why_review": "两侧资料需进一步核对。",
                    "next_check": "请补充登记及来源采集依据。",
                    "evidence_refs": [address],
                }
            ],
            "limitations": [],
        },
    }


def test_facts_are_references_and_mandatory_limits_cannot_be_omitted() -> None:
    data = material()
    parsed = v2.validate_output(
        output(data), data, {item["citation_id"] for item in data["items"]}, 32768
    )
    assert parsed["text"]["limitations"] == data["limitations"]
    assert "text" not in parsed["text"]["claims"][0]
    assert data["facts"][f"fact:{RESULT}:counts"]["value"]["total_addresses"] == 3


def test_output_requires_fixed_counts_and_the_exact_address_fact() -> None:
    data = material()
    proposal = output(data)
    proposal["text"]["claims"] = [proposal["text"]["claims"][1]]
    proposal["text"]["summary"] = ["check"]
    for section in proposal["text"]["sections"]:
        section["claim_ids"] = ["check"]
    with pytest.raises(reports.AnalysisReportError, match="model_output_invalid"):
        v2.validate_output(
            proposal, data, {item["citation_id"] for item in data["items"]}, 32768
        )

    data = material()
    data["subject"]["address_key"] = ADDRESS
    data["facts"][f"fact:{RESULT}:{ADDRESS}"] = {
        "kind": "address",
        "value": {"canonical_ip": "192.0.2.10"},
        "evidence_refs": [data["items"][1]["citation_id"]],
    }
    proposal = output(data)
    proposal["text"]["sections"] = [
        {"id": key, "claim_ids": ["fixed"]} for key in v2.ADDRESS_SECTIONS
    ]
    proposal["text"]["claims"][0]["fact_refs"] = [f"fact:{RESULT}:counts"]
    with pytest.raises(reports.AnalysisReportError, match="model_output_invalid"):
        v2.validate_output(
            proposal, data, {item["citation_id"] for item in data["items"]}, 32768
        )


@pytest.mark.parametrize(
    "case",
    [
        "number",
        "foreign_fact",
        "foreign_evidence",
        "foreign_address",
        "severity",
        "recent_activity",
        "remediation",
        "section",
    ],
)
def test_unsupported_output_is_rejected(case: str) -> None:
    data = material()
    proposal = output(data)
    if case == "number":
        proposal["text"]["claims"][0]["text"] = "全集为999"
    elif case == "foreign_fact":
        proposal["text"]["claims"][0]["fact_refs"] = ["fact:another-result:counts"]
    elif case == "foreign_evidence":
        proposal["text"]["claims"][1]["evidence_refs"] = ["core:another-project"]
    elif case == "foreign_address":
        proposal["text"]["priority_cases"][0]["address_key"] = "addr:" + "c" * 64
    elif case == "severity":
        proposal["text"]["claims"][1]["text"] = "这是高危漏洞。"
    elif case == "recent_activity":
        proposal["text"]["claims"][1]["text"] = "最近24小时仍在运行。"
    elif case == "remediation":
        proposal["text"]["claims"][1]["text"] = "相关差异已处置。"
    else:
        proposal["text"]["sections"].reverse()
    with pytest.raises(reports.AnalysisReportError):
        v2.validate_output(
            proposal, data, {item["citation_id"] for item in data["items"]}, 32768
        )


def test_manual_edit_only_changes_narrative_and_keeps_fact_refs() -> None:
    data = material()
    original = v2.validate_output(
        output(data), data, {item["citation_id"] for item in data["items"]}, 32768
    )["text"]
    record = AnalysisReport(text=deepcopy(original))
    edited = v2.edit_text(
        record,
        v2.Update(
            expected_revision=1, edits={"check": "请先核实这份登记对应的采集范围。"}
        ),
    )
    assert edited["claims"][0] == original["claims"][0]
    assert (
        edited["claims"][1]["evidence_refs"] == original["claims"][1]["evidence_refs"]
    )
    assert edited["claims"][1]["text"] != original["claims"][1]["text"]
    with pytest.raises(reports.AnalysisReportError, match="fact_edit_denied"):
        v2.edit_text(
            record, v2.Update(expected_revision=1, edits={"fixed": "修改统计"})
        )


def test_v2_synthetic_permission_cannot_borrow_a_run_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = material()
    project = uuid.UUID(data["subject"]["project_id"])
    sources = [
        {
            "kind": kind,
            "version_id": str(uuid.uuid4()),
            "domain": domain,
            "content_sha256": "b" * 64,
        }
        for kind, domain in (("CUSTOMER", "customer"), ("CLOUD", "ip"))
    ]
    binding = ModelBinding(
        endpoint="https://ai-api-gateway.app.baizhi.cloud/api/openai",
        resolved_address="1.1.1.1",
        model_identity="fixture",
        protocol="responses",
        config_revision="fixture",
        runner_build_version="fixture",
        agent_compose_runtime_version="fixture",
        config_fingerprint="c" * 64,
    )
    monkeypatch.setattr(settings, "AI_ANALYSIS_REPORT_ALLOW_BAIZHI_TEST", True)
    monkeypatch.setattr(settings, "AI_ANALYSIS_REPORT_SYNTHETIC_MANIFEST", "[]")
    args: dict[str, Any] = {
        "binding": binding,
        "project_id": project,
        "run_id": None,
        "material": data,
        "sources": sources,
    }
    with pytest.raises(reports.AnalysisReportError, match="synthetic_material_denied"):
        reports.authorize_material(**args)
    permission = v2.SyntheticPermission.model_validate(
        {
            **{key: data["subject"][key] for key in v2.Request.model_fields},
            "project_id": str(project),
            "core_input_sha256": "a" * 64,
            "binding_revision": None,
            "valid_until": None,
            "material_sha256": reports.material_hash(data),
            "sources": sources,
        }
    )
    monkeypatch.setattr(
        settings,
        "AI_ANALYSIS_REPORT_SYNTHETIC_MANIFEST",
        json.dumps([permission.model_dump(mode="json")]),
    )
    reports.authorize_material(**args)
    changed = deepcopy(data)
    changed["subject"]["result_id"] = str(uuid.uuid4())
    with pytest.raises(reports.AnalysisReportError, match="synthetic_material_denied"):
        reports.authorize_material(**{**args, "material": changed})
