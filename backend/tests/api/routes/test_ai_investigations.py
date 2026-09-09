import json
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app import ai_investigation_runner as runner
from app.core.config import settings
from app.core.db import engine
from app.domain import ai_investigations as service
from app.domain.models import AiInvestigation, Finding, GovernanceReport, GovernanceRun
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
    AgentComposeRunStart,
)
from tests.api.routes.test_ai_governance_draft_requests import (
    _configure_qualified_model,
    _operator_draft_request_context,
)
from tests.api.routes.test_governance_runs import _create_member, _create_project
from tests.api.routes.test_ip_source_comparison import comparison_run as comparison_run


@pytest.fixture
def investigation_context(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> tuple[str, dict[str, str], dict[str, str]]:
    project, report, headers, finding_id, _url = _operator_draft_request_context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    finding = db.get(Finding, uuid.UUID(finding_id))
    assert finding is not None
    body = {
        "resource_id": str(finding.resource_id),
        "run_id": str(report.governance_run_id),
        "finding_id": finding_id,
    }
    return f"/api/v1/projects/{project['id']}/ai-investigations", headers, body


def _pending(monkeypatch: MonkeyPatch) -> list[str]:
    starts: list[str] = []

    def start(
        client: AgentComposeClient, *, client_request_id: str, investigation_id: str
    ) -> AgentComposeRunStart:
        starts.append(investigation_id)
        return AgentComposeRunStart(
            run_id=client.expected_ai_investigation_run_id(client_request_id),
            started=True,
            status="RUNNING",
            session_id=uuid.uuid4().hex * 2,
        )

    monkeypatch.setattr(AgentComposeClient, "start_ai_investigation", start)
    monkeypatch.setattr(AgentComposeClient, "get_run", lambda _client, _run_id: None)
    return starts


def _run(
    monkeypatch: MonkeyPatch,
    investigation_id: str,
    model: Any,
    *,
    actual_session_id: str | None = None,
) -> int:
    with Session(engine) as session:
        record = session.get(AiInvestigation, uuid.UUID(investigation_id))
        assert record is not None
        monkeypatch.setenv("AI_INVESTIGATION_ID", investigation_id)
        monkeypatch.setenv("AI_INVESTIGATION_RUN_ID", record.agent_compose_run_id)
        monkeypatch.setenv(
            "SANDBOX_ID", actual_session_id or record.session_id or "a" * 64
        )
    build_file = Path(settings.ARTIFACT_ROOT) / "investigation-runner-build-version"
    build_file.write_text(settings.RUNNER_BUILD_VERSION)
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_file))
    monkeypatch.setattr(sys, "argv", ["ai-investigation-runner"])
    monkeypatch.setattr(runner, "run_pi_investigation", model)
    return runner.main()


def _output(material: dict[str, Any]) -> dict[str, Any]:
    citation = next(
        item["citation_id"]
        for item in material["items"]
        if item["fact"]["kind"] == "COMPARISON"
    )
    return {
        "facts": [
            {
                "text": "The fixed published comparison records the source discrepancy.",
                "citation_ids": [citation],
            }
        ],
        "explanations": ["This is a hypothesis, not a verified cause."],
        "gaps": [],
        "next_steps": ["Verify the source inventories."],
    }


def test_operator_scope_viewer_read_and_unknown_idempotency(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    investigation_context: Any,
    monkeypatch: MonkeyPatch,
) -> None:
    url, headers, body = investigation_context
    project_id = url.split("/")[4]
    viewer = _create_member(
        client, superuser_token_headers, project_id=project_id, roles=["viewer"]
    )
    starts = _pending(monkeypatch)
    assert (
        client.post(
            url, headers={**viewer, "Idempotency-Key": "viewer"}, json=body
        ).status_code
        == 404
    )
    response = client.post(
        url, headers={**headers, "Idempotency-Key": "same"}, json=body
    )
    assert response.status_code == 201, response.text
    record = response.json()
    replay = client.post(url, headers={**headers, "Idempotency-Key": "same"}, json=body)
    assert replay.status_code == 200
    assert replay.json()["id"] == record["id"]
    assert replay.json()["status"] == "GENERATING"
    assert replay.json()["failure_code"] == "agent_compose_run_unknown"
    assert starts == [record["id"]]
    conflict = client.post(
        url,
        headers={**headers, "Idempotency-Key": "same"},
        json={**body, "finding_id": None},
    )
    assert conflict.status_code == 409
    listing = client.get(url, headers=viewer, params=body).json()
    assert listing["can_create"] is False
    assert [item["id"] for item in listing["data"]] == [record["id"]]
    unscoped = client.get(
        url,
        headers=viewer,
        params={key: value for key, value in body.items() if key != "finding_id"},
    ).json()
    assert unscoped["data"] == []
    other = _create_project(client, superuser_token_headers)
    assert (
        client.get(
            f"/api/v1/projects/{other['id']}/ai-investigations/{record['id']}",
            headers=superuser_token_headers,
        ).status_code
        == 404
    )


def test_malformed_control_plane_identity_does_not_poison_runner(
    client: TestClient,
    investigation_context: Any,
    monkeypatch: MonkeyPatch,
) -> None:
    url, headers, body = investigation_context
    _pending(monkeypatch)
    monkeypatch.setattr(
        AgentComposeClient,
        "start_ai_investigation",
        lambda client, **kwargs: AgentComposeRunStart(
            run_id=client.expected_ai_investigation_run_id(kwargs["client_request_id"]),
            started=True,
            status="RUNNING",
            session_id="invalid-session",
        ),
    )
    response = client.post(
        url, headers={**headers, "Idempotency-Key": "malformed-session"}, json=body
    )
    assert response.status_code == 201, response.text
    record_id = response.json()["id"]
    assert (
        _run(
            monkeypatch,
            record_id,
            lambda **kwargs: _output(kwargs["tools"]["read_asset_facts"]({})),
            actual_session_id="a" * 64,
        )
        == 0
    )
    assert (
        client.get(f"{url}/{record_id}", headers=headers).json()["status"]
        == "COMPLETED"
    )


@pytest.mark.parametrize("finding_type", ["UNOBSERVED_ASSET", "UNREPORTED_ASSET"])
def test_success_cites_real_read_and_finished_rows_are_immutable(
    client: TestClient,
    investigation_context: Any,
    monkeypatch: MonkeyPatch,
    finding_type: str,
) -> None:
    url, headers, body = investigation_context
    with Session(engine) as session:
        finding = session.exec(
            select(Finding).where(
                Finding.project_id == uuid.UUID(url.split("/")[4]),
                Finding.finding_type == finding_type,
            )
        ).one()
        body = {
            **body,
            "resource_id": str(finding.resource_id),
            "finding_id": str(finding.id),
        }
        run = session.get(GovernanceRun, uuid.UUID(body["run_id"]))
        assert run is not None
        run_before = run.model_dump(mode="json")
        report_before = (
            session.exec(
                select(GovernanceReport).where(
                    GovernanceReport.governance_run_id == uuid.UUID(body["run_id"])
                )
            )
            .one()
            .model_dump(mode="json")
        )
        finding_before = finding.model_dump(mode="json")
    starts = _pending(monkeypatch)
    response = client.post(
        url, headers={**headers, "Idempotency-Key": "success"}, json=body
    )
    assert response.status_code == 201, response.text
    record_id = response.json()["id"]
    assert (
        _run(
            monkeypatch,
            record_id,
            lambda **kwargs: _output(kwargs["tools"]["read_asset_facts"]({})),
        )
        == 0
    )
    result = client.get(f"{url}/{record_id}", headers=headers).json()
    assert result["status"] == "COMPLETED"
    assert result["output"] == _output(result["material"])
    assert starts == [record_id]
    with Session(engine) as session:
        run = session.get(GovernanceRun, uuid.UUID(body["run_id"]))
        assert run is not None
        assert run.model_dump(mode="json") == run_before
        assert (
            session.exec(
                select(GovernanceReport).where(
                    GovernanceReport.governance_run_id == uuid.UUID(body["run_id"])
                )
            )
            .one()
            .model_dump(mode="json")
            == report_before
        )
        saved_finding = session.get(Finding, uuid.UUID(body["finding_id"]))
        assert saved_finding is not None
        assert saved_finding.model_dump(mode="json") == finding_before
        with pytest.raises(DBAPIError, match="immutable"):
            session.connection().execute(
                text("UPDATE ai_investigations SET output = '{}' WHERE id = :id"),
                {"id": record_id},
            )
        session.rollback()


def test_runner_image_drift_fails_before_model_call(
    client: TestClient, investigation_context: Any, monkeypatch: MonkeyPatch
) -> None:
    url, headers, body = investigation_context
    _pending(monkeypatch)
    response = client.post(
        url, headers={**headers, "Idempotency-Key": "image-drift"}, json=body
    )
    assert response.status_code == 201
    monkeypatch.setattr(runner, "_runner_build_version", lambda: "different-image")
    model_calls: list[bool] = []

    def model(**kwargs: Any) -> dict[str, Any]:
        model_calls.append(True)
        return _output(kwargs["tools"]["read_asset_facts"]({}))

    assert _run(monkeypatch, response.json()["id"], model) == 1
    assert model_calls == []
    result = client.get(f"{url}/{response.json()['id']}", headers=headers).json()
    assert result["status"] == "FAILED"
    assert result["failure_code"] == "model_binding_changed"


@pytest.mark.parametrize("failure", ["citation", "no-tool", "scope"])
def test_failed_model_attempt_preserves_readable_failure_and_allows_manual_new_attempt(
    client: TestClient,
    investigation_context: Any,
    monkeypatch: MonkeyPatch,
    failure: str,
) -> None:
    url, headers, body = investigation_context
    starts = _pending(monkeypatch)
    response = client.post(
        url, headers={**headers, "Idempotency-Key": "failure"}, json=body
    )
    assert response.status_code == 201, response.text
    record_id = response.json()["id"]

    def invalid(**kwargs: Any) -> dict[str, Any]:
        if failure == "scope":
            return _output(
                kwargs["tools"]["read_asset_facts"]({"resource_id": str(uuid.uuid4())})
            )
        output = _output(
            response.json()["material"]
            if failure == "no-tool"
            else kwargs["tools"]["read_asset_facts"]({})
        )
        output["facts"][0]["citation_ids"] = ["comparison/foreign-run/foreign-resource"]
        return output

    assert _run(monkeypatch, record_id, invalid) == 1
    result = client.get(f"{url}/{record_id}", headers=headers).json()
    assert result["status"] == "FAILED"
    assert (
        result["failure_code"]
        == {
            "citation": "model_citation_invalid",
            "no-tool": "tool_required",
            "scope": "tool_scope_denied",
        }[failure]
    )
    retry = client.post(
        url, headers={**headers, "Idempotency-Key": "manual-new-attempt"}, json=body
    )
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] != record_id
    assert client.get(f"{url}/{record_id}", headers=headers).json() == result
    assert starts == [record_id, retry.json()["id"]]


def test_lost_launch_response_never_restarts_unknown_run(
    client: TestClient, investigation_context: Any, monkeypatch: MonkeyPatch
) -> None:
    url, headers, body = investigation_context
    starts = _pending(monkeypatch)

    def unavailable(_client: AgentComposeClient, **kwargs: Any) -> Any:
        starts.append(kwargs["investigation_id"])
        raise AgentComposeBoundaryError("agent_compose_unavailable")

    monkeypatch.setattr(AgentComposeClient, "start_ai_investigation", unavailable)
    first = client.post(
        url, headers={**headers, "Idempotency-Key": "lost-response"}, json=body
    )
    assert first.status_code == 201, first.text
    for _ in range(2):
        replay = client.post(
            url, headers={**headers, "Idempotency-Key": "lost-response"}, json=body
        )
        assert replay.json()["status"] == "GENERATING"
        assert replay.json()["id"] == first.json()["id"]
    assert len(starts) == 1


@pytest.mark.parametrize("comparison_run", ["active"], indirect=True)
def test_v2_asset_investigation_accepts_explicit_published_run(
    client: TestClient,
    comparison_run: GovernanceRun,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: MonkeyPatch,
) -> None:
    _configure_qualified_model(session=db, monkeypatch=monkeypatch)
    url = f"/api/v1/projects/{comparison_run.project_id}"
    comparison = client.get(
        f"{url}/governance-runs/{comparison_run.id}/ip-source-comparisons",
        headers=superuser_token_headers,
    )
    assert comparison.status_code == 200, comparison.text
    body = {
        "resource_id": comparison.json()["data"][0]["resource_id"],
        "run_id": str(comparison_run.id),
    }
    _pending(monkeypatch)
    response = client.post(
        f"{url}/ai-investigations",
        headers={**superuser_token_headers, "Idempotency-Key": "v2"},
        json=body,
    )
    assert response.status_code == 201, response.text
    assert (
        response.json()["material"]["report_contract_version"]
        == "deterministic-report-v2"
    )
    assert (
        _run(
            monkeypatch,
            response.json()["id"],
            lambda **kwargs: _output(kwargs["tools"]["read_asset_facts"]({})),
        )
        == 0
    )


def test_external_manifest_matches_exact_scope_sources_and_material(
    monkeypatch: MonkeyPatch,
) -> None:
    from app.domain.model_qualification import ModelBinding

    project_id = uuid.uuid4()
    scope = service.InvestigationRequest(resource_id=uuid.uuid4(), run_id=uuid.uuid4())
    material = {"bounded": "synthetic"}
    sources = [
        {
            "source_type": "CUSTOMER_UPLOAD",
            "input_id": str(uuid.uuid4()),
            "snapshot_id": str(uuid.uuid4()),
            "content_sha256": "a" * 64,
        }
    ]
    permission = {
        "project_id": str(project_id),
        **scope.model_dump(mode="json"),
        "material_sha256": service.material_hash(material),
        "sources": sources,
    }
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
    monkeypatch.setattr(settings, "AI_INVESTIGATION_ALLOW_BAIZHI_TEST", True)
    monkeypatch.setattr(
        settings, "AI_INVESTIGATION_SYNTHETIC_MANIFEST", json.dumps([permission])
    )
    service.authorize_material(
        binding=binding,
        project_id=project_id,
        scope=scope,
        material=material,
        sources=sources,
    )
    for changed in (
        {"project_id": uuid.uuid4()},
        {"material": {"bounded": "customer-upload"}},
        {"sources": [{**sources[0], "input_id": str(uuid.uuid4())}]},
    ):
        args: dict[str, Any] = {
            "binding": binding,
            "project_id": project_id,
            "scope": scope,
            "material": material,
            "sources": sources,
            **changed,
        }
        with pytest.raises(
            service.InvestigationError, match="synthetic_material_denied"
        ):
            service.authorize_material(**args)


@pytest.mark.parametrize("revocation", ["before-model", "at-tool"])
def test_material_permission_is_rechecked_before_model_and_every_tool(
    client: TestClient,
    investigation_context: Any,
    monkeypatch: MonkeyPatch,
    revocation: str,
) -> None:
    url, headers, body = investigation_context
    starts = _pending(monkeypatch)
    response = client.post(
        url, headers={**headers, "Idempotency-Key": "sealed"}, json=body
    )
    assert response.status_code == 201, response.text
    record_id = response.json()["id"]
    with Session(engine) as session:
        record = session.get(AiInvestigation, uuid.UUID(record_id))
        assert record is not None
        binding = replace(
            service.require_model(session, record),
            endpoint="https://ai-api-gateway.app.baizhi.cloud/api/openai",
        )
        permission = {
            "project_id": str(record.project_id),
            **body,
            "material_sha256": record.material_sha256,
            "sources": record.sources,
        }
    monkeypatch.setattr(service, "require_model", lambda *_args: binding)
    monkeypatch.setattr(settings, "AI_INVESTIGATION_ALLOW_BAIZHI_TEST", True)
    monkeypatch.setattr(
        settings,
        "AI_INVESTIGATION_SYNTHETIC_MANIFEST",
        "[]" if revocation == "before-model" else json.dumps([permission]),
    )
    model_calls = []

    def model(**kwargs: Any) -> dict[str, Any]:
        model_calls.append(True)
        monkeypatch.setattr(settings, "AI_INVESTIGATION_SYNTHETIC_MANIFEST", "[]")
        return _output(kwargs["tools"]["read_asset_facts"]({}))

    assert _run(monkeypatch, record_id, model) == 1
    result = client.get(f"{url}/{record_id}", headers=headers).json()
    assert result["failure_code"] == "synthetic_material_denied"
    assert model_calls == ([] if revocation == "before-model" else [True])
    rejected = client.post(
        url, headers={**headers, "Idempotency-Key": "new-denied"}, json=body
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "synthetic_material_denied"
    assert starts == [record_id]
