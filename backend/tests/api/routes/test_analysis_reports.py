import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from app import ai_analysis_report_runner as runner
from app.core.config import settings
from app.core.db import engine
from app.domain.models import AnalysisReport, GovernanceRun
from app.integrations.agent_compose import AgentComposeClient, AgentComposeRunStart
from tests.api.routes.test_ai_governance_draft_requests import (
    _configure_qualified_model,
)
from tests.api.routes.test_ai_investigations import _output as investigation_output
from tests.api.routes.test_ai_investigations import _pending as pending_investigation
from tests.api.routes.test_ai_investigations import _run as run_investigation
from tests.api.routes.test_ai_investigations import (
    investigation_context as investigation_context,
)
from tests.api.routes.test_governance_runs import _create_member, _create_project
from tests.api.routes.test_ip_source_comparison import comparison_run as comparison_run


def _pending(monkeypatch: MonkeyPatch) -> list[str]:
    starts: list[str] = []

    def start(
        client: AgentComposeClient, *, client_request_id: str, analysis_report_id: str
    ) -> AgentComposeRunStart:
        starts.append(analysis_report_id)
        return AgentComposeRunStart(
            run_id=client.expected_analysis_report_run_id(client_request_id),
            started=True,
            status="RUNNING",
            session_id=uuid.uuid4().hex * 2,
        )

    monkeypatch.setattr(AgentComposeClient, "start_analysis_report", start)
    monkeypatch.setattr(AgentComposeClient, "get_run", lambda _client, _run_id: None)
    return starts


def _output(material: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": {
            "business_summary": "The published Run records source reconciliation.",
            "key_differences": "See the authoritative fixed Run statistics; causes remain unverified.",
            "investigation_progress": "Only the obtained records are evidence; missing investigations remain a gap.",
            "next_steps": "Verify source discrepancies. NetFlow UNKNOWN is not zero risk.",
        },
        "citation_ids": [material["items"][0]["citation_id"]],
        "gaps": material["gaps"],
    }


def _run(monkeypatch: MonkeyPatch, report_id: str, model: Any = None) -> int:
    with Session(engine) as session:
        record = session.get(AnalysisReport, uuid.UUID(report_id))
        assert record is not None
        monkeypatch.setenv("AI_ANALYSIS_REPORT_ID", report_id)
        monkeypatch.setenv("AI_ANALYSIS_REPORT_RUN_ID", record.agent_compose_run_id)
        monkeypatch.setenv("SANDBOX_ID", record.session_id or "a" * 64)
    build = Path(settings.ARTIFACT_ROOT) / "analysis-report-build-version"
    build.write_text(settings.RUNNER_BUILD_VERSION)
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build))
    monkeypatch.setattr(sys, "argv", ["ai-analysis-report-runner"])
    monkeypatch.setattr(
        runner,
        "run_pi_investigation",
        model
        or (lambda **kwargs: _output(kwargs["tools"]["read_report_material"]({}))),
    )
    return runner.main()


def test_report_acl_scope_and_unknown_replay(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    investigation_context: Any,
    monkeypatch: MonkeyPatch,
) -> None:
    investigation_url, headers, scope = investigation_context
    url = investigation_url.replace("ai-investigations", "analysis-reports")
    body = {"run_id": scope["run_id"]}
    viewer = _create_member(
        client, superuser_token_headers, project_id=url.split("/")[4], roles=["viewer"]
    )
    starts = _pending(monkeypatch)
    assert (
        client.post(
            url, headers={**viewer, "Idempotency-Key": "viewer"}, json=body
        ).status_code
        == 404
    )
    created = client.post(url, headers={**headers, "Idempotency-Key": "one"}, json=body)
    assert created.status_code == 201, created.text
    report = created.json()
    replay = client.post(url, headers={**headers, "Idempotency-Key": "one"}, json=body)
    assert replay.status_code == 200
    assert replay.json()["id"] == report["id"]
    assert replay.json()["status"] == "GENERATING"
    assert replay.json()["failure_code"] == "agent_compose_run_unknown"
    assert starts == [report["id"]]
    assert (
        client.post(
            url,
            headers={**headers, "Idempotency-Key": "one"},
            json={"run_id": str(uuid.uuid4())},
        ).status_code
        == 409
    )
    listing = client.get(url, headers=viewer, params=body).json()
    assert listing["can_create"] is False
    assert [item["id"] for item in listing["data"]] == [report["id"]]
    other = _create_project(client, superuser_token_headers)
    assert (
        client.get(
            f"/api/v1/projects/{other['id']}/analysis-reports/{report['id']}",
            headers=superuser_token_headers,
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"{url}/{report['id']}",
            headers=viewer,
            json={"expected_revision": 1, "text": _output(report["material"])["text"]},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{url}/{report['id']}/confirm",
            headers=viewer,
            json={"expected_revision": 1},
        ).status_code
        == 404
    )


def test_edit_confirm_new_material_and_failure_preserve_old_versions(
    client: TestClient, investigation_context: Any, monkeypatch: MonkeyPatch
) -> None:
    investigation_url, headers, scope = investigation_context
    url = investigation_url.replace("ai-investigations", "analysis-reports")
    _pending(monkeypatch)
    first = client.post(
        url,
        headers={**headers, "Idempotency-Key": "first"},
        json={"run_id": scope["run_id"]},
    )
    assert first.status_code == 201, first.text
    report_id = first.json()["id"]
    assert _run(monkeypatch, report_id) == 0
    draft = client.get(f"{url}/{report_id}", headers=headers).json()
    assert draft["status"] == "DRAFT"
    assert draft["materials_changed"] is False
    revised = {
        **draft["text"],
        "next_steps": "Human: verify inventory owners before any action.",
    }
    edited = client.patch(
        f"{url}/{report_id}",
        headers=headers,
        json={"expected_revision": 1, "text": revised},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["edited_by_id"] is not None
    assert edited.json()["edited_at"] is not None
    assert edited.json()["original_output"] == draft["original_output"]
    assert (
        client.post(
            f"{url}/{report_id}/confirm", headers=headers, json={"expected_revision": 1}
        ).status_code
        == 409
    )
    confirmed = client.post(
        f"{url}/{report_id}/confirm", headers=headers, json={"expected_revision": 2}
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "CONFIRMED"
    assert (
        client.patch(
            f"{url}/{report_id}",
            headers=headers,
            json={"expected_revision": 3, "text": revised},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"{url}/{report_id}",
            headers=headers,
            json={"expected_revision": 3, "material": {}, "text": revised},
        ).status_code
        == 422
    )
    with Session(engine) as session:
        with pytest.raises(DBAPIError):
            session.execute(
                text(
                    "UPDATE analysis_reports SET material = '{}'::jsonb WHERE id = :id"
                ),
                {"id": uuid.UUID(report_id)},
            )
            session.commit()
        session.rollback()
    review = client.post(
        investigation_url.replace("ai-investigations", "manual-reviews"),
        headers=headers,
        json={
            **scope,
            "conclusion": "Operator checked inventories; cause remains unknown.",
            "pending_verification": "Re-run reconciliation.",
        },
    )
    assert review.status_code == 201, review.text
    old = client.get(f"{url}/{report_id}", headers=headers).json()
    pending_investigation(monkeypatch)
    investigation = client.post(
        investigation_url,
        headers={**headers, "Idempotency-Key": "obtained"},
        json=scope,
    )
    assert investigation.status_code == 201, investigation.text
    assert (
        run_investigation(
            monkeypatch,
            investigation.json()["id"],
            lambda **kwargs: investigation_output(
                kwargs["tools"]["read_asset_facts"]({})
            ),
        )
        == 0
    )
    assert old["materials_changed"] is True
    assert old["material"] == draft["material"]
    assert old["original_output"] == draft["original_output"]
    second = client.post(
        url,
        headers={**headers, "Idempotency-Key": "second"},
        json={"run_id": scope["run_id"]},
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] != report_id
    assert any(
        item["kind"] == "MANUAL_REVIEW" and item["identity"] == review.json()["id"]
        for item in second.json()["material"]["items"]
    )
    assert any(
        item["kind"] == "INVESTIGATION"
        and item["identity"] == investigation.json()["id"]
        for item in second.json()["material"]["items"]
    )
    assert any(
        item["kind"] == "OBTAINED_TOOL_READ"
        and item["data"]["tool_name"] == "read_asset_facts"
        for item in second.json()["material"]["items"]
    )
    assert (
        _run(
            monkeypatch,
            second.json()["id"],
            lambda **kwargs: {
                **_output(kwargs["tools"]["read_report_material"]({})),
                "citation_ids": ["invented"],
            },
        )
        == 1
    )
    listing = client.get(
        url, headers=headers, params={"run_id": scope["run_id"]}
    ).json()["data"]
    assert listing[0]["status"] == "FAILED"
    assert listing[0]["failure_code"] == "model_citation_invalid"
    assert listing[1]["status"] == "CONFIRMED"
    assert listing[1]["materials_changed"] is True
    assert listing[1]["text"] == revised


@pytest.mark.parametrize("comparison_run", ["empty", "absent"], indirect=True)
def test_no_investigations_preserves_v2_empty_and_v1_absent(
    client: TestClient,
    comparison_run: GovernanceRun,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: MonkeyPatch,
) -> None:
    _configure_qualified_model(session=db, monkeypatch=monkeypatch)
    _pending(monkeypatch)
    url = f"/api/v1/projects/{comparison_run.project_id}/analysis-reports"
    created = client.post(
        url,
        headers={**superuser_token_headers, "Idempotency-Key": "v2"},
        json={"run_id": str(comparison_run.id)},
    )
    assert created.status_code == 201, created.text
    material = created.json()["material"]
    if comparison_run.netflow_dataset_id is None:
        assert material["report_contract_version"] == "deterministic-report-v1"
        assert {
            source["source_type"]
            for source in material["summary"]["input_completeness"]["sources"]
        } == {"CUSTOMER_UPLOAD", "CLOUDATLAS"}
    else:
        assert material["report_contract_version"] == "deterministic-report-v2"
        netflow = material["summary"]["input_capabilities"]["netflow"]
        assert netflow["coverage"] == "UNKNOWN"
        assert netflow["input_state"] == "present"
        assert netflow["positive_activity_resource_count"] == 0
    assert any("UNKNOWN, never zero risk" in gap for gap in material["gaps"])
    assert any("No investigation" in gap for gap in material["gaps"])
    assert _run(monkeypatch, created.json()["id"]) == 0
    assert (
        client.get(
            f"{url}/{created.json()['id']}", headers=superuser_token_headers
        ).json()["status"]
        == "DRAFT"
    )
    missing = client.post(
        url,
        headers={**superuser_token_headers, "Idempotency-Key": "missing"},
        json={"run_id": str(uuid.uuid4())},
    )
    assert missing.status_code == 409
    assert missing.json()["detail"]["code"] == "analysis_report_material_unavailable"
