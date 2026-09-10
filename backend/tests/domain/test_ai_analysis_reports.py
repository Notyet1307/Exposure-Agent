import json
import uuid
from typing import Any

import pytest

from app.core.config import settings
from app.domain import ai_analysis_reports as service
from app.domain.model_qualification import ModelBinding


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
