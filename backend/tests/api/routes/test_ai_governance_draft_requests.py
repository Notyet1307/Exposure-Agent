import hashlib
import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlmodel import Session, select

from app.api.routes import governance_reports as governance_report_routes
from app.core.config import settings
from app.core.db import engine
from app.domain import ai_governance_drafts as draft_service
from app.domain import governance_runs as governance_runs_domain
from app.domain.ai_governance_drafts import bind_draft_session, fail_draft
from app.domain.cloudatlas_sources import OctobusCloudAtlasClient
from app.domain.model_qualification import (
    QualificationEvaluation,
    model_config_fingerprint,
    persist_qualification_result,
)
from app.domain.models import (
    AiGovernanceDraft,
    AiGovernanceDraftFindingBinding,
    Artifact,
    AuditEvent,
    Evidence,
    GovernanceReport,
    GovernanceRun,
)
from app.governance_runner import main as run_governance_runner
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
    AgentComposeRunStart,
)
from tests.api.routes.test_governance_runs import (
    _create_member,
    _create_project,
    _mock_cloudatlas,
    _prepare_ready_project,
    _trigger_stage5_run,
)


def _draft_url(*, project_id: object, report_id: uuid.UUID) -> str:
    return (
        f"{settings.API_V1_STR}/projects/{project_id}/governance-reports/"
        f"{report_id}/ai-governance-drafts"
    )


def _publish_report_with_unobserved_asset(
    *,
    client: TestClient,
    headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    omit_unobserved_evidence: bool = False,
) -> tuple[dict[str, object], GovernanceReport]:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _client, _source, *, capset_token, page, size: {
            "items": [{"id": "fixture-asset-2", "ip": "192.0.2.20", "status": "valid"}],
            "page": page,
            "size": size,
            "total": 1,
        },
    )
    if omit_unobserved_evidence:
        publication_records = governance_runs_domain._report_publication_records

        def publication_records_without_unobserved_evidence(
            *,
            run: GovernanceRun,
            candidate: governance_runs_domain.ReportCandidate,
        ) -> tuple[list[Artifact], GovernanceReport, list[Evidence]]:
            artifacts, report, evidence = publication_records(
                run=run,
                candidate=candidate,
            )
            retained_evidence = [
                record
                for entry, record in zip(
                    candidate.evidence_plan.entries,
                    evidence,
                    strict=True,
                )
                if entry.finding_type != "UNOBSERVED_ASSET"
            ]
            return artifacts, report, retained_evidence

        monkeypatch.setattr(
            governance_runs_domain,
            "_report_publication_records",
            publication_records_without_unobserved_evidence,
        )
    project = _create_project(client, headers)
    _prepare_ready_project(client=client, headers=headers, project=project)
    _trigger_stage5_run(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project=project,
        trigger_id=f"draft-request-{uuid.uuid4()}",
    )
    assert run_governance_runner() == 0
    with Session(engine) as session:
        report = session.exec(
            select(GovernanceReport).where(
                GovernanceReport.project_id == uuid.UUID(str(project["id"]))
            )
        ).one()
        session.expunge(report)
    return project, report


def _configure_qualified_model(*, session: Session, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MODEL_API_ENDPOINT", "http://127.0.0.1/v1")
    monkeypatch.setattr(settings, "MODEL_IDENTITY", "customer-model")
    monkeypatch.setattr(settings, "MODEL_API_PROTOCOL", "chat_completions")
    monkeypatch.setattr(settings, "MODEL_CONFIG_REVISION", "fixture-v1")
    monkeypatch.setattr(settings, "AGENT_COMPOSE_RUNTIME_VERSION", "compose-v1")
    monkeypatch.setattr(settings, "MODEL_API_KEY", SecretStr("fixture-secret"))
    fingerprint = model_config_fingerprint(
        endpoint=settings.MODEL_API_ENDPOINT,
        model_identity=settings.MODEL_IDENTITY,
        protocol=settings.MODEL_API_PROTOCOL,
        config_revision=settings.MODEL_CONFIG_REVISION,
        runner_build_version=settings.RUNNER_BUILD_VERSION,
        agent_compose_runtime_version=settings.AGENT_COMPOSE_RUNTIME_VERSION,
    )
    persist_qualification_result(
        session=session,
        endpoint=settings.MODEL_API_ENDPOINT,
        model_identity=settings.MODEL_IDENTITY,
        config_fingerprint=fingerprint,
        agent_compose_run_id=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        evaluation=QualificationEvaluation(
            fixture_version="model-qualification-v1",
            status="PASS",
            availability_numerator=3,
            availability_denominator=4,
            traceable_citations=4,
            total_citations=4,
            hallucination_count=0,
            finding_modification_count=0,
            unauthorized_side_effect_count=0,
            failure_code=None,
        ),
    )


def test_operator_request_is_canonical_idempotent_and_audited(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, report = _publish_report_with_unobserved_asset(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    archived_project, archived_report = _publish_report_with_unobserved_asset(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    operator_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["operator"],
    )
    viewer_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["viewer"],
    )
    archived_operator_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=archived_project["id"],
        roles=["operator"],
    )
    report_detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-reports/{report.id}",
        headers=operator_headers,
    ).json()
    selected_entry = next(
        entry
        for entry in report_detail["canonical_content"]["evidence_plan"]["entries"]
        if entry["finding_type"] == "UNOBSERVED_ASSET"
    )
    selected_id = selected_entry["finding_id"]
    wrong_type_id = next(
        entry["finding_id"]
        for entry in report_detail["canonical_content"]["evidence_plan"]["entries"]
        if entry["finding_type"] == "UNREPORTED_ASSET"
    )
    url = _draft_url(project_id=project["id"], report_id=report.id)

    unqualified = client.post(
        url,
        headers={**operator_headers, "Idempotency-Key": "draft-1"},
        json={"finding_ids": [selected_id]},
    )
    assert unqualified.status_code == 409
    assert unqualified.json()["detail"]["code"] == "model_not_qualified"
    with Session(engine) as session:
        assert (
            session.exec(
                select(AiGovernanceDraft).where(
                    AiGovernanceDraft.project_id == uuid.UUID(str(project["id"]))
                )
            ).all()
            == []
        )

    _configure_qualified_model(session=db, monkeypatch=monkeypatch)
    calls: list[tuple[str, str]] = []

    def start_draft(
        _client: object, *, client_request_id: str, draft_id: str
    ) -> AgentComposeRunStart:
        calls.append((client_request_id, draft_id))
        run_id = AgentComposeClient().expected_ai_governance_draft_run_id(
            client_request_id
        )
        session_id = hashlib.sha256(draft_id.encode()).hexdigest()
        with Session(engine) as runner_session:
            persisted = runner_session.get(AiGovernanceDraft, uuid.UUID(draft_id))
            assert persisted is not None
            assert persisted.agent_compose_run_id == run_id
            assert persisted.session_id is None
            bind_draft_session(
                session=runner_session,
                draft=persisted,
                agent_compose_run_id=run_id,
                session_id=session_id,
            )
        return AgentComposeRunStart(
            run_id=run_id,
            started=True,
            status="RUN_STATUS_PENDING",
            session_id=session_id,
        )

    monkeypatch.setattr(AgentComposeClient, "start_ai_governance_draft", start_draft)
    invalid_requests = (
        ({"finding_ids": [selected_id, selected_id]}, "invalid_bindings"),
        ({"finding_ids": [wrong_type_id]}, "finding_not_selected"),
        ({"finding_ids": [str(uuid.uuid4())]}, "finding_not_selected"),
    )
    for index, (payload, code) in enumerate(invalid_requests):
        invalid = client.post(
            url,
            headers={**operator_headers, "Idempotency-Key": f"invalid-{index}"},
            json=payload,
        )
        assert invalid.status_code == 409
        assert invalid.json()["detail"]["code"] == code
    for payload in ({"finding_ids": []}, {"finding_ids": [selected_id] * 9}):
        invalid = client.post(
            url,
            headers={
                **operator_headers,
                "Idempotency-Key": f"invalid-size-{uuid.uuid4()}",
            },
            json=payload,
        )
        assert invalid.status_code == 422
    assert calls == []
    with Session(engine) as session:
        assert (
            session.exec(
                select(AiGovernanceDraft).where(
                    AiGovernanceDraft.project_id == uuid.UUID(str(project["id"]))
                )
            ).all()
            == []
        )

    approver_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["approver"],
    )
    for restricted_headers in (viewer_headers, approver_headers):
        forbidden = client.post(
            url,
            headers={**restricted_headers, "Idempotency-Key": str(uuid.uuid4())},
            json={"finding_ids": [selected_id]},
        )
        assert forbidden.status_code == 404
    other_project = _create_project(client, superuser_token_headers)
    cross_project = client.post(
        _draft_url(project_id=other_project["id"], report_id=report.id),
        headers={**operator_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"finding_ids": [selected_id]},
    )
    assert cross_project.status_code == 404
    assert calls == []

    archived_report_detail = client.get(
        f"{settings.API_V1_STR}/projects/{archived_project['id']}/governance-reports/{archived_report.id}",
        headers=archived_operator_headers,
    ).json()
    archived_selected_id = next(
        entry["finding_id"]
        for entry in archived_report_detail["canonical_content"]["evidence_plan"][
            "entries"
        ]
        if entry["finding_type"] == "UNOBSERVED_ASSET"
    )
    archive = client.post(
        f"{settings.API_V1_STR}/projects/{archived_project['id']}/archive",
        headers=superuser_token_headers,
    )
    assert archive.status_code == 200
    archived = client.post(
        _draft_url(
            project_id=archived_project["id"],
            report_id=archived_report.id,
        ),
        headers={**archived_operator_headers, "Idempotency-Key": "archived-draft"},
        json={"finding_ids": [archived_selected_id]},
    )
    assert archived.status_code == 409
    assert archived.json()["detail"] == "Archived project is read-only"
    assert calls == []
    archived_detail = client.get(
        f"{settings.API_V1_STR}/projects/{archived_project['id']}/governance-reports/{archived_report.id}",
        headers=archived_operator_headers,
    )
    assert archived_detail.status_code == 200
    assert archived_detail.json()["can_request_ai_governance_draft"] is False

    created = client.post(
        url,
        headers={**operator_headers, "Idempotency-Key": "draft-1"},
        json={"finding_ids": [selected_id]},
    )
    assert created.status_code == 202, created.text
    body = created.json()
    assert body["finding_ids"] == [selected_id]
    assert body["status"] == "GENERATING"
    assert body["session_id"] is not None
    assert len(calls) == 1
    reference = selected_entry["evidence_reference"]
    evidence_id_field = {
        "SOURCE_SNAPSHOT": "source_snapshot_id",
        "OBSERVATION": "observation_id",
        "FINDING_OCCURRENCE": "finding_occurrence_id",
        "FINDING_TRANSITION": "finding_transition_id",
    }[reference["fact_type"]]
    with Session(engine) as session:
        binding = session.exec(
            select(AiGovernanceDraftFindingBinding).where(
                AiGovernanceDraftFindingBinding.draft_id == uuid.UUID(body["id"])
            )
        ).one()
        assert binding.finding_id == uuid.UUID(selected_id)
        evidence = session.get(Evidence, binding.evidence_id)
        assert evidence is not None
        assert getattr(evidence, evidence_id_field) == uuid.UUID(reference["fact_id"])

    replay = client.post(
        url,
        headers={**operator_headers, "Idempotency-Key": "draft-1"},
        json={"finding_ids": [str(uuid.uuid4())]},
    )
    assert replay.status_code == 200
    assert replay.json() == body
    assert len(calls) == 1
    cross_report_replay = client.post(
        _draft_url(project_id=project["id"], report_id=uuid.uuid4()),
        headers={**operator_headers, "Idempotency-Key": "draft-1"},
        json={"finding_ids": [selected_id]},
    )
    assert cross_report_replay.status_code == 409
    assert cross_report_replay.json()["detail"]["code"] == (
        "draft_idempotency_conflict"
    )
    assert len(calls) == 1
    monkeypatch.setattr(
        "app.api.routes.governance_reports.current_model_is_qualified",
        lambda **_kwargs: False,
    )
    conflict = client.post(
        url,
        headers={**operator_headers, "Idempotency-Key": "draft-2"},
        json={"finding_ids": [selected_id]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "draft_generation_active"
    assert len(calls) == 1
    assert calls == [
        (f"ai-governance-draft:{body['id']}", body["id"]),
    ]

    with Session(engine) as session:
        event = session.exec(
            select(AuditEvent).where(
                AuditEvent.action == "ai_governance_draft.generation_requested"
            )
        ).one()
        assert event.project_id == uuid.UUID(str(project["id"]))
        assert event.target_id == uuid.UUID(body["id"])
        assert event.after_data == {
            "governance_report_id": str(report.id),
            "status": "GENERATING",
            "finding_count": 1,
        }


def test_request_rejects_missing_persisted_evidence_before_session_creation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, report = _publish_report_with_unobserved_asset(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        omit_unobserved_evidence=True,
    )
    operator_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["operator"],
    )
    detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-reports/{report.id}",
        headers=operator_headers,
    ).json()
    entry = next(
        entry
        for entry in detail["canonical_content"]["evidence_plan"]["entries"]
        if entry["finding_type"] == "UNOBSERVED_ASSET"
    )
    _configure_qualified_model(session=db, monkeypatch=monkeypatch)
    calls: list[object] = []
    monkeypatch.setattr(
        AgentComposeClient,
        "start_ai_governance_draft",
        lambda *_args, **_kwargs: calls.append(None),
    )
    response = client.post(
        _draft_url(project_id=project["id"], report_id=report.id),
        headers={**operator_headers, "Idempotency-Key": "missing-evidence"},
        json={"finding_ids": [entry["finding_id"]]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "evidence_not_bound"
    assert calls == []
    with Session(engine) as session:
        assert (
            session.exec(
                select(AiGovernanceDraft).where(
                    AiGovernanceDraft.project_id == uuid.UUID(str(project["id"]))
                )
            ).all()
            == []
        )


@pytest.mark.parametrize("launch_mode", ("missing-session", "response-loss"))
def test_request_reconciles_an_accepted_session_before_returning(
    launch_mode: str,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, report = _publish_report_with_unobserved_asset(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    operator_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["operator"],
    )
    detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-reports/{report.id}",
        headers=operator_headers,
    ).json()
    selected_id = next(
        entry["finding_id"]
        for entry in detail["canonical_content"]["evidence_plan"]["entries"]
        if entry["finding_type"] == "UNOBSERVED_ASSET"
    )
    _configure_qualified_model(session=db, monkeypatch=monkeypatch)
    accepted: dict[str, str] = {}
    start_calls: list[str] = []
    get_calls: list[str] = []

    def start_draft(
        _client: object, *, client_request_id: str, draft_id: str
    ) -> AgentComposeRunStart:
        start_calls.append(client_request_id)
        run_id = AgentComposeClient().expected_ai_governance_draft_run_id(
            client_request_id
        )
        accepted.update(
            run_id=run_id,
            session_id=hashlib.sha256(draft_id.encode()).hexdigest(),
        )
        if launch_mode == "response-loss":
            raise AgentComposeBoundaryError("agent_compose_unavailable")
        return AgentComposeRunStart(
            run_id=run_id,
            started=True,
            status="RUN_STATUS_PENDING",
            session_id=None,
        )

    def get_run(_client: object, run_id: str) -> AgentComposeRunStart:
        get_calls.append(run_id)
        assert run_id == accepted["run_id"]
        return AgentComposeRunStart(
            run_id=run_id,
            started=False,
            status="RUN_STATUS_PENDING",
            session_id=accepted["session_id"],
        )

    monkeypatch.setattr(AgentComposeClient, "start_ai_governance_draft", start_draft)
    monkeypatch.setattr(AgentComposeClient, "get_run", get_run)
    response = client.post(
        _draft_url(project_id=project["id"], report_id=report.id),
        headers={**operator_headers, "Idempotency-Key": f"{launch_mode}-draft"},
        json={"finding_ids": [selected_id]},
    )

    assert response.status_code == 202, response.text
    assert response.json()["agent_compose_run_id"] == accepted["run_id"]
    assert response.json()["session_id"] == accepted["session_id"]
    assert len(start_calls) == 1
    assert get_calls == [accepted["run_id"]]


def test_pending_session_replay_recovers_without_another_start(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, report = _publish_report_with_unobserved_asset(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    operator_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["operator"],
    )
    detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-reports/{report.id}",
        headers=operator_headers,
    ).json()
    selected_id = next(
        entry["finding_id"]
        for entry in detail["canonical_content"]["evidence_plan"]["entries"]
        if entry["finding_type"] == "UNOBSERVED_ASSET"
    )
    _configure_qualified_model(session=db, monkeypatch=monkeypatch)
    accepted: dict[str, str] = {}
    start_calls: list[str] = []
    session_visible = False

    def start_draft(
        _client: object, *, client_request_id: str, draft_id: str
    ) -> AgentComposeRunStart:
        start_calls.append(client_request_id)
        run_id = AgentComposeClient().expected_ai_governance_draft_run_id(
            client_request_id
        )
        accepted.update(
            run_id=run_id,
            session_id=hashlib.sha256(draft_id.encode()).hexdigest(),
        )
        return AgentComposeRunStart(
            run_id=run_id,
            started=True,
            status="RUN_STATUS_PENDING",
            session_id=None,
        )

    def get_run(_client: object, run_id: str) -> AgentComposeRunStart:
        return AgentComposeRunStart(
            run_id=run_id,
            started=False,
            status="RUN_STATUS_PENDING",
            session_id=accepted["session_id"] if session_visible else None,
        )

    monkeypatch.setattr(AgentComposeClient, "start_ai_governance_draft", start_draft)
    monkeypatch.setattr(AgentComposeClient, "get_run", get_run)
    url = _draft_url(project_id=project["id"], report_id=report.id)
    headers = {**operator_headers, "Idempotency-Key": "pending-session"}
    first = client.post(url, headers=headers, json={"finding_ids": [selected_id]})
    assert first.status_code == 503
    assert first.json()["detail"]["code"] == "agent_compose_session_pending"
    with Session(engine) as session:
        draft = session.exec(
            select(AiGovernanceDraft).where(
                AiGovernanceDraft.project_id == uuid.UUID(str(project["id"]))
            )
        ).one()
        assert draft.status == "GENERATING"
        assert draft.agent_compose_run_id == accepted["run_id"]
        assert draft.session_id is None

    session_visible = True
    replay = client.post(url, headers=headers, json={"finding_ids": [selected_id]})
    assert replay.status_code == 200, replay.text
    assert replay.json()["agent_compose_run_id"] == accepted["run_id"]
    assert replay.json()["session_id"] == accepted["session_id"]
    assert len(start_calls) == 1


def test_unknown_run_status_remains_recoverable_without_a_failure_audit_event(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, report = _publish_report_with_unobserved_asset(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    operator_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["operator"],
    )
    detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-reports/{report.id}",
        headers=operator_headers,
    ).json()
    selected_id = next(
        entry["finding_id"]
        for entry in detail["canonical_content"]["evidence_plan"]["entries"]
        if entry["finding_type"] == "UNOBSERVED_ASSET"
    )
    _configure_qualified_model(session=db, monkeypatch=monkeypatch)
    start_calls: list[str] = []
    recovered_session_id: str | None = None

    def start_draft(
        _client: object, *, client_request_id: str, draft_id: str
    ) -> AgentComposeRunStart:
        nonlocal recovered_session_id
        start_calls.append(client_request_id)
        recovered_session_id = hashlib.sha256(draft_id.encode()).hexdigest()
        return AgentComposeRunStart(
            run_id=AgentComposeClient().expected_ai_governance_draft_run_id(
                client_request_id
            ),
            started=True,
            status="RUN_STATUS_UNSPECIFIED",
            session_id=recovered_session_id,
        )

    def get_run(_client: object, run_id: str) -> AgentComposeRunStart:
        assert recovered_session_id is not None
        return AgentComposeRunStart(
            run_id=run_id,
            started=False,
            status="RUN_STATUS_PENDING",
            session_id=recovered_session_id,
        )

    monkeypatch.setattr(AgentComposeClient, "start_ai_governance_draft", start_draft)
    monkeypatch.setattr(AgentComposeClient, "get_run", get_run)
    url = _draft_url(project_id=project["id"], report_id=report.id)
    headers = {**operator_headers, "Idempotency-Key": "unknown-run-status"}

    first = client.post(url, headers=headers, json={"finding_ids": [selected_id]})
    assert first.status_code == 503
    assert first.json()["detail"]["code"] == "agent_compose_run_status_unknown"
    with Session(engine) as session:
        draft = session.exec(
            select(AiGovernanceDraft).where(
                AiGovernanceDraft.project_id == uuid.UUID(str(project["id"]))
            )
        ).one()
        assert draft.status == "GENERATING"
        assert draft.agent_compose_run_id == (
            AgentComposeClient().expected_ai_governance_draft_run_id(
                f"ai-governance-draft:{draft.id}"
            )
        )
        assert draft.session_id is None
        assert (
            session.exec(
                select(AuditEvent).where(
                    AuditEvent.action == "ai_governance_draft.generation_failed",
                    AuditEvent.target_id == draft.id,
                )
            ).all()
            == []
        )

    replay = client.post(url, headers=headers, json={"finding_ids": [selected_id]})
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "GENERATING"
    assert replay.json()["session_id"] == recovered_session_id
    assert len(start_calls) == 1


def test_bound_generating_draft_replays_after_agent_compose_naming_changes(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, report = _publish_report_with_unobserved_asset(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    operator_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["operator"],
    )
    detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-reports/{report.id}",
        headers=operator_headers,
    ).json()
    selected_id = next(
        entry["finding_id"]
        for entry in detail["canonical_content"]["evidence_plan"]["entries"]
        if entry["finding_type"] == "UNOBSERVED_ASSET"
    )
    _configure_qualified_model(session=db, monkeypatch=monkeypatch)
    bound_session_ids: list[str] = []
    start_calls: list[str] = []

    def start_draft(
        _client: object, *, client_request_id: str, draft_id: str
    ) -> AgentComposeRunStart:
        start_calls.append(client_request_id)
        session_id = hashlib.sha256(draft_id.encode()).hexdigest()
        bound_session_ids.append(session_id)
        return AgentComposeRunStart(
            run_id=AgentComposeClient().expected_ai_governance_draft_run_id(
                client_request_id
            ),
            started=True,
            status="RUN_STATUS_PENDING",
            session_id=session_id,
        )

    monkeypatch.setattr(AgentComposeClient, "start_ai_governance_draft", start_draft)
    url = _draft_url(project_id=project["id"], report_id=report.id)
    headers = {**operator_headers, "Idempotency-Key": "bound-reconciliation"}
    first = client.post(url, headers=headers, json={"finding_ids": [selected_id]})
    assert first.status_code == 202, first.text
    assert first.json()["session_id"] == bound_session_ids[0]

    get_calls: list[str] = []
    monkeypatch.setattr(
        AgentComposeClient,
        "get_run",
        lambda _client, run_id: get_calls.append(run_id),
    )
    monkeypatch.setattr(settings, "AGENT_COMPOSE_PROJECT_NAME", "renamed-project")
    monkeypatch.setattr(
        settings, "AI_GOVERNANCE_DRAFT_AGENT_NAME", "renamed-draft-agent"
    )
    replay = client.post(url, headers=headers, json={"finding_ids": [selected_id]})
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert replay.json()["session_id"] == bound_session_ids[0]
    assert len(start_calls) == 1
    assert get_calls == []


def test_pending_session_replay_rechecks_qualification_before_start(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, report = _publish_report_with_unobserved_asset(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    operator_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["operator"],
    )
    detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-reports/{report.id}",
        headers=operator_headers,
    ).json()
    selected_id = next(
        entry["finding_id"]
        for entry in detail["canonical_content"]["evidence_plan"]["entries"]
        if entry["finding_type"] == "UNOBSERVED_ASSET"
    )
    _configure_qualified_model(session=db, monkeypatch=monkeypatch)
    qualified = True
    start_calls: list[str] = []

    def is_qualified(**_kwargs: object) -> bool:
        return qualified

    def unavailable_start(
        _client: object, *, client_request_id: str, draft_id: str
    ) -> AgentComposeRunStart:
        del draft_id
        start_calls.append(client_request_id)
        raise AgentComposeBoundaryError("agent_compose_unavailable")

    monkeypatch.setattr(
        "app.api.routes.governance_reports.current_model_is_qualified",
        is_qualified,
    )
    monkeypatch.setattr(
        AgentComposeClient, "start_ai_governance_draft", unavailable_start
    )
    monkeypatch.setattr(AgentComposeClient, "get_run", lambda *_args: None)
    url = _draft_url(project_id=project["id"], report_id=report.id)
    headers = {**operator_headers, "Idempotency-Key": "qualification-replay"}

    first = client.post(url, headers=headers, json={"finding_ids": [selected_id]})
    assert first.status_code == 503
    assert first.json()["detail"]["code"] == "agent_compose_unavailable"
    assert len(start_calls) == 1

    qualified = False
    replay = client.post(url, headers=headers, json={"finding_ids": [selected_id]})
    assert replay.status_code == 409
    assert replay.json()["detail"]["code"] == "model_not_qualified"
    assert len(start_calls) == 1


def test_pending_session_replay_fails_a_draft_when_its_model_binding_drifts(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, report = _publish_report_with_unobserved_asset(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    operator_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["operator"],
    )
    detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-reports/{report.id}",
        headers=operator_headers,
    ).json()
    selected_id = next(
        entry["finding_id"]
        for entry in detail["canonical_content"]["evidence_plan"]["entries"]
        if entry["finding_type"] == "UNOBSERVED_ASSET"
    )
    _configure_qualified_model(session=db, monkeypatch=monkeypatch)
    start_calls: list[str] = []

    def unavailable_start(
        _client: object, *, client_request_id: str, draft_id: str
    ) -> AgentComposeRunStart:
        del draft_id
        start_calls.append(client_request_id)
        raise AgentComposeBoundaryError("agent_compose_unavailable")

    monkeypatch.setattr(
        AgentComposeClient, "start_ai_governance_draft", unavailable_start
    )
    monkeypatch.setattr(AgentComposeClient, "get_run", lambda *_args: None)
    url = _draft_url(project_id=project["id"], report_id=report.id)
    headers = {**operator_headers, "Idempotency-Key": "binding-drift-replay"}

    first = client.post(url, headers=headers, json={"finding_ids": [selected_id]})
    assert first.status_code == 503
    assert len(start_calls) == 1

    monkeypatch.setattr(settings, "MODEL_CONFIG_REVISION", "fixture-v2")
    replay = client.post(url, headers=headers, json={"finding_ids": [selected_id]})
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "FAILED"
    assert replay.json()["failure_code"] == "model_binding_changed"
    assert len(start_calls) == 1
    with Session(engine) as session:
        event = session.exec(
            select(AuditEvent).where(
                AuditEvent.action == "ai_governance_draft.generation_failed",
                AuditEvent.target_id == uuid.UUID(replay.json()["id"]),
            )
        ).one()
    assert event.after_data == {
        "status": "FAILED",
        "failure_code": "model_binding_changed",
    }


@pytest.mark.parametrize(
    ("run_status", "session_id"),
    (
        ("RUN_STATUS_FAILED", None),
        ("RUN_STATUS_FAILED", "with-session"),
        ("RUN_STATUS_SUCCEEDED", None),
        ("RUN_STATUS_SUCCEEDED", "with-session"),
    ),
)
def test_terminal_session_launch_converges_to_a_durable_state(
    run_status: str,
    session_id: str | None,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, report = _publish_report_with_unobserved_asset(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    operator_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["operator"],
    )
    detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-reports/{report.id}",
        headers=operator_headers,
    ).json()
    selected_id = next(
        entry["finding_id"]
        for entry in detail["canonical_content"]["evidence_plan"]["entries"]
        if entry["finding_type"] == "UNOBSERVED_ASSET"
    )
    _configure_qualified_model(session=db, monkeypatch=monkeypatch)
    start_calls: list[str] = []
    get_calls: list[str] = []

    def terminal_start(
        _client: object, *, client_request_id: str, draft_id: str
    ) -> AgentComposeRunStart:
        start_calls.append(client_request_id)
        returned_session_id = (
            hashlib.sha256(draft_id.encode()).hexdigest()
            if session_id is not None
            else None
        )
        return AgentComposeRunStart(
            run_id=AgentComposeClient().expected_ai_governance_draft_run_id(
                client_request_id
            ),
            started=True,
            status=run_status,
            session_id=returned_session_id,
        )

    def get_run(_client: object, run_id: str) -> None:
        get_calls.append(run_id)
        return None

    monkeypatch.setattr(AgentComposeClient, "start_ai_governance_draft", terminal_start)
    monkeypatch.setattr(AgentComposeClient, "get_run", get_run)
    url = _draft_url(project_id=project["id"], report_id=report.id)
    headers = {**operator_headers, "Idempotency-Key": "terminal-launch"}

    first = client.post(url, headers=headers, json={"finding_ids": [selected_id]})
    assert first.status_code == 202, first.text
    successful_bootstrap = (
        run_status == "RUN_STATUS_SUCCEEDED" and session_id is not None
    )
    assert first.json()["status"] == (
        "GENERATING" if successful_bootstrap else "FAILED"
    )
    assert first.json()["failure_code"] == (
        None if successful_bootstrap else "agent_compose_run_failed"
    )
    assert (first.json()["session_id"] is not None) is (session_id is not None)
    assert len(start_calls) == 1
    assert get_calls == []
    if not successful_bootstrap:
        with Session(engine) as session:
            failure_event = session.exec(
                select(AuditEvent).where(
                    AuditEvent.action == "ai_governance_draft.generation_failed",
                    AuditEvent.target_id == uuid.UUID(first.json()["id"]),
                )
            ).one()
        assert failure_event.actor_subject == "agent-compose-control-plane"
        assert failure_event.after_data == {
            "status": "FAILED",
            "failure_code": "agent_compose_run_failed",
        }

    replay = client.post(url, headers=headers, json={"finding_ids": [selected_id]})
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert len(start_calls) == 1
    assert get_calls == []


def test_failed_draft_blocks_an_explicit_new_attempt(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, report = _publish_report_with_unobserved_asset(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    operator_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["operator"],
    )
    detail_url = (
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-reports/{report.id}"
    )
    detail = client.get(detail_url, headers=operator_headers).json()
    selected_id = next(
        entry["finding_id"]
        for entry in detail["canonical_content"]["evidence_plan"]["entries"]
        if entry["finding_type"] == "UNOBSERVED_ASSET"
    )
    _configure_qualified_model(session=db, monkeypatch=monkeypatch)
    start_calls: list[str] = []

    def start_draft(
        _client: object, *, client_request_id: str, draft_id: str
    ) -> AgentComposeRunStart:
        start_calls.append(client_request_id)
        return AgentComposeRunStart(
            run_id=AgentComposeClient().expected_ai_governance_draft_run_id(
                client_request_id
            ),
            started=True,
            status="RUN_STATUS_PENDING",
            session_id=hashlib.sha256(draft_id.encode()).hexdigest(),
        )

    monkeypatch.setattr(AgentComposeClient, "start_ai_governance_draft", start_draft)
    url = _draft_url(project_id=project["id"], report_id=report.id)
    first = client.post(
        url,
        headers={**operator_headers, "Idempotency-Key": "failed-original"},
        json={"finding_ids": [selected_id]},
    )
    assert first.status_code == 202, first.text
    with Session(engine) as session:
        draft = session.get(AiGovernanceDraft, uuid.UUID(first.json()["id"]))
        assert draft is not None
        fail_draft(session=session, draft=draft, failure_code="provider_failed")

    persisted = client.get(detail_url, headers=operator_headers)
    assert persisted.status_code == 200
    assert persisted.json()["can_request_ai_governance_draft"] is False
    assert persisted.json()["ai_governance_drafts"][0]["status"] == "FAILED"

    new_attempt = client.post(
        url,
        headers={**operator_headers, "Idempotency-Key": "failed-new-attempt"},
        json={"finding_ids": [selected_id]},
    )
    assert new_attempt.status_code == 409
    assert new_attempt.json()["detail"]["code"] == (
        "draft_generation_after_failure_not_supported"
    )
    assert len(start_calls) == 1


def test_global_admin_can_request_ai_governance_draft(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, report = _publish_report_with_unobserved_asset(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-reports/{report.id}",
        headers=superuser_token_headers,
    ).json()
    selected_id = next(
        entry["finding_id"]
        for entry in detail["canonical_content"]["evidence_plan"]["entries"]
        if entry["finding_type"] == "UNOBSERVED_ASSET"
    )
    _configure_qualified_model(session=db, monkeypatch=monkeypatch)
    calls: list[tuple[str, str]] = []

    def start_draft(
        _client: object, *, client_request_id: str, draft_id: str
    ) -> AgentComposeRunStart:
        calls.append((client_request_id, draft_id))
        return AgentComposeRunStart(
            run_id=AgentComposeClient().expected_ai_governance_draft_run_id(
                client_request_id
            ),
            started=True,
            status="RUN_STATUS_PENDING",
            session_id=hashlib.sha256(draft_id.encode()).hexdigest(),
        )

    monkeypatch.setattr(AgentComposeClient, "start_ai_governance_draft", start_draft)
    response = client.post(
        _draft_url(project_id=project["id"], report_id=report.id),
        headers={**superuser_token_headers, "Idempotency-Key": "admin-draft"},
        json={"finding_ids": [selected_id]},
    )

    assert detail["can_request_ai_governance_draft"] is True
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "GENERATING"
    assert len(calls) == 1


def _create_reserved_pending_draft(
    *,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> tuple[uuid.UUID, str]:
    project, report = _publish_report_with_unobserved_asset(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    operator_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["operator"],
    )
    detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-reports/{report.id}",
        headers=operator_headers,
    ).json()
    selected_id = next(
        entry["finding_id"]
        for entry in detail["canonical_content"]["evidence_plan"]["entries"]
        if entry["finding_type"] == "UNOBSERVED_ASSET"
    )
    _configure_qualified_model(session=db, monkeypatch=monkeypatch)
    monkeypatch.setattr(
        AgentComposeClient,
        "start_ai_governance_draft",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AgentComposeBoundaryError("agent_compose_unavailable")
        ),
    )
    monkeypatch.setattr(AgentComposeClient, "get_run", lambda *_args: None)
    response = client.post(
        _draft_url(project_id=project["id"], report_id=report.id),
        headers={**operator_headers, "Idempotency-Key": "concurrent-same-key"},
        json={"finding_ids": [selected_id]},
    )
    assert response.status_code == 503
    with Session(engine) as session:
        draft = session.exec(
            select(AiGovernanceDraft).where(
                AiGovernanceDraft.project_id == uuid.UUID(str(project["id"])),
                AiGovernanceDraft.idempotency_key == "concurrent-same-key",
            )
        ).one()
        assert draft.status == "GENERATING"
        assert draft.agent_compose_run_id == (
            AgentComposeClient().expected_ai_governance_draft_run_id(
                f"ai-governance-draft:{draft.id}"
            )
        )
        assert draft.agent_compose_run_id is not None
        return draft.id, draft.agent_compose_run_id


def test_postgresql_concurrent_same_key_replay_returns_persisted_session_binding(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    draft_id, run_id = _create_reserved_pending_draft(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    session_id = "a" * 64
    loser_reserved_run = threading.Event()
    persisted = threading.Event()
    start = threading.Event()
    outcomes: list[AiGovernanceDraft] = []
    errors: list[BaseException] = []
    original_reserve = draft_service.reserve_draft_run_identity
    original_bind = draft_service.bind_draft_session

    def reserve(
        *, session: Session, draft: AiGovernanceDraft, agent_compose_run_id: str
    ) -> AiGovernanceDraft:
        result = original_reserve(
            session=session,
            draft=draft,
            agent_compose_run_id=agent_compose_run_id,
        )
        # reserve_draft_run_identity refreshes the result after its
        # commit.  End that implicit read transaction before coordinating the
        # replay threads: the loser must not wait while holding any database
        # transaction or Project lock.
        session.commit()
        if threading.current_thread().name == "replay-loser":
            loser_reserved_run.set()
            if not persisted.wait(timeout=5):
                raise AssertionError("winner did not persist the Session binding")
        elif not loser_reserved_run.wait(timeout=5):
            raise AssertionError("loser did not reserve the deterministic Run")
        return result

    def bind(
        *,
        session: Session,
        draft: AiGovernanceDraft,
        agent_compose_run_id: str,
        session_id: str,
    ) -> AiGovernanceDraft:
        result = original_bind(
            session=session,
            draft=draft,
            agent_compose_run_id=agent_compose_run_id,
            session_id=session_id,
        )
        persisted.set()
        return result

    def get_run(_client: object, observed_run_id: str) -> AgentComposeRunStart:
        assert observed_run_id == run_id
        assert threading.current_thread().name == "replay-winner"
        return AgentComposeRunStart(
            run_id=run_id,
            started=False,
            status="RUN_STATUS_PENDING",
            session_id=session_id,
        )

    monkeypatch.setattr(draft_service, "reserve_draft_run_identity", reserve)
    monkeypatch.setattr(draft_service, "bind_draft_session", bind)
    monkeypatch.setattr(AgentComposeClient, "get_run", get_run)
    monkeypatch.setattr(
        AgentComposeClient,
        "start_ai_governance_draft",
        lambda *_args, **_kwargs: pytest.fail("stale replay started a second Session"),
    )

    def replay() -> None:
        try:
            if not start.wait(timeout=5):
                raise AssertionError("replay threads were not started")
            with Session(engine) as session:
                draft = session.get(AiGovernanceDraft, draft_id)
                assert draft is not None
                outcomes.append(
                    governance_report_routes._launch_or_reconcile_draft_session(
                        session=session,
                        draft=draft,
                        launch_now=False,
                        authorize_start=lambda: object(),
                    )
                )
        except BaseException as error:
            errors.append(error)
        finally:
            # A failed winner must still release a waiting loser, so joins
            # below are bounded even when an assertion or database call fails.
            loser_reserved_run.set()
            persisted.set()

    winner = threading.Thread(target=replay, name="replay-winner")
    loser = threading.Thread(target=replay, name="replay-loser")
    winner.start()
    loser.start()
    start.set()
    winner.join(timeout=10)
    loser.join(timeout=10)

    assert not winner.is_alive()
    assert not loser.is_alive()
    assert errors == []
    assert [(item.agent_compose_run_id, item.session_id) for item in outcomes] == [
        (run_id, session_id),
        (run_id, session_id),
    ]


def test_postgresql_concurrent_same_key_replay_returns_persisted_terminal_failure(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    draft_id, run_id = _create_reserved_pending_draft(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    loser_reserved_run = threading.Event()
    persisted = threading.Event()
    start = threading.Event()
    outcomes: list[AiGovernanceDraft] = []
    errors: list[BaseException] = []
    original_reserve = draft_service.reserve_draft_run_identity
    original_fail = draft_service.fail_draft

    def reserve(
        *, session: Session, draft: AiGovernanceDraft, agent_compose_run_id: str
    ) -> AiGovernanceDraft:
        result = original_reserve(
            session=session,
            draft=draft,
            agent_compose_run_id=agent_compose_run_id,
        )
        # See the Session-binding race above: do not wait while the refresh
        # performed by reservation has an implicit transaction open.
        session.commit()
        if threading.current_thread().name == "replay-loser":
            loser_reserved_run.set()
            if not persisted.wait(timeout=5):
                raise AssertionError("winner did not persist the terminal failure")
        elif not loser_reserved_run.wait(timeout=5):
            raise AssertionError("loser did not reserve the deterministic Run")
        return result

    def fail(
        *,
        session: Session,
        draft: AiGovernanceDraft,
        failure_code: str,
        actor_subject: str = "ai-draft-runner",
        agent_compose_run_id: str | None = None,
        session_id: str | None = None,
    ) -> AiGovernanceDraft:
        result = original_fail(
            session=session,
            draft=draft,
            failure_code=failure_code,
            actor_subject=actor_subject,
            agent_compose_run_id=agent_compose_run_id,
            session_id=session_id,
        )
        persisted.set()
        return result

    def get_run(_client: object, observed_run_id: str) -> AgentComposeRunStart:
        assert observed_run_id == run_id
        assert threading.current_thread().name == "replay-winner"
        return AgentComposeRunStart(
            run_id=run_id,
            started=False,
            status="RUN_STATUS_FAILED",
        )

    monkeypatch.setattr(draft_service, "reserve_draft_run_identity", reserve)
    monkeypatch.setattr(draft_service, "fail_draft", fail)
    monkeypatch.setattr(AgentComposeClient, "get_run", get_run)
    monkeypatch.setattr(
        AgentComposeClient,
        "start_ai_governance_draft",
        lambda *_args, **_kwargs: pytest.fail("stale replay started a failed Run"),
    )

    def replay() -> None:
        try:
            if not start.wait(timeout=5):
                raise AssertionError("replay threads were not started")
            with Session(engine) as session:
                draft = session.get(AiGovernanceDraft, draft_id)
                assert draft is not None
                outcomes.append(
                    governance_report_routes._launch_or_reconcile_draft_session(
                        session=session,
                        draft=draft,
                        launch_now=False,
                        authorize_start=lambda: object(),
                    )
                )
        except BaseException as error:
            errors.append(error)
        finally:
            loser_reserved_run.set()
            persisted.set()

    winner = threading.Thread(target=replay, name="replay-winner")
    loser = threading.Thread(target=replay, name="replay-loser")
    winner.start()
    loser.start()
    start.set()
    winner.join(timeout=10)
    loser.join(timeout=10)

    assert not winner.is_alive()
    assert not loser.is_alive()
    assert errors == []
    assert [(item.status, item.failure_code) for item in outcomes] == [
        ("FAILED", "agent_compose_run_failed"),
        ("FAILED", "agent_compose_run_failed"),
    ]
