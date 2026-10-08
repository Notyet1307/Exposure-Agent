"""Real HTTP/processor setup; only the external control plane is simulated."""

import uuid
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlmodel import Session

from app.core.config import settings
from app.domain.models import Project
from app.domain.netflow_models import NetFlowAnalysis
from app.domain.netflow_processing import execute_analysis
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
    AgentComposeRunStart,
    AgentComposeSession,
    AgentComposeSessionObservation,
)
from app.models import User
from tests.api.routes.test_netflow_datasets import _project, _upload

NAMESPACE = "synthetic-nf273"
CSV = (
    Path(__file__).parents[1] / "fixtures/netflow_processing/source_position_sample.csv"
)


class ControlPlane:
    def __init__(self, monkeypatch: MonkeyPatch) -> None:
        self.runs: dict[str, AgentComposeRunStart] = {}
        self.observations: dict[str, AgentComposeSessionObservation] = {}
        self.starts: list[str] = []
        self.lose_start_response = False
        self.session_reads = 0
        self.lose_publication_observation = False

        def start(
            client: AgentComposeClient, *, client_request_id: str, analysis_id: str
        ) -> AgentComposeRunStart:
            run_id = client.expected_netflow_analysis_run_id(client_request_id)
            session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, run_id))
            run = AgentComposeRunStart(
                run_id=run_id,
                started=True,
                status="RUNNING",
                session_id=session_id,
                project_id=client.project_id,
                agent_name="netflow-processor",
            )
            self.starts.append(analysis_id)
            self.runs[run_id] = run
            self.observations[session_id] = AgentComposeSessionObservation.RUNNING
            if self.lose_start_response:
                raise AgentComposeBoundaryError(
                    "agent_compose_response_contract_failed"
                )
            return run

        def get_run(
            _client: AgentComposeClient, run_id: str
        ) -> AgentComposeRunStart | None:
            return self.runs.get(run_id)

        def get_session(
            _client: AgentComposeClient, session_id: str
        ) -> AgentComposeSession:
            self.session_reads += 1
            observation = self.observations.get(
                session_id, AgentComposeSessionObservation.UNKNOWN
            )
            if self.lose_publication_observation and self.session_reads >= 2:
                observation = AgentComposeSessionObservation.UNKNOWN
            return AgentComposeSession(session_id=session_id, observation=observation)

        monkeypatch.setattr(AgentComposeClient, "start_netflow_analysis", start)
        monkeypatch.setattr(AgentComposeClient, "get_run", get_run)
        monkeypatch.setattr(AgentComposeClient, "get_session", get_session)

    def observe(
        self, row: NetFlowAnalysis, state: AgentComposeSessionObservation
    ) -> None:
        session_id = self.runs[row.agent_run_id].session_id
        assert session_id is not None
        self.lose_publication_observation = False
        self.observations[session_id] = state


def context_request(
    parent: str | None = None,
    *,
    state: str = "CONFIRMED",
    collection_scope: str | None = None,
) -> dict[str, Any]:
    return {
        "expected_parent_id": parent,
        "network_namespace": NAMESPACE,
        "state": state,
        "collection_scope": collection_scope,
        "collection_scope_evidence": "Synthetic fixed collector scope."
        if collection_scope
        else None,
        "endpoint_selection": "declared_source",
        "source_position_evidence": "Public synthetic fixture: SRC is local, DST external.",
        "nat_context": "none",
        "nat_evidence": "Public synthetic unconverted endpoints.",
        "observation_point": {"id": "synthetic-nf273", "view": "UNKNOWN"},
        "sampling": {"mode": "unknown", "rate": None},
    }


def prepared_dataset(
    client: TestClient,
    db: Session,
    headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    raw_text: str | None = None,
) -> dict[str, Any]:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "NETFLOW_ALLOW_TEST_FIXTURES", True)
    monkeypatch.setattr(settings, "GOVERNANCE_RUNNER_BUILD_VERSION", "synthetic-nf273")
    control = ControlPlane(monkeypatch)
    created = _project(client, headers)
    project_id = str(created["id"])
    uploaded = _upload(
        client,
        headers,
        project_id,
        CSV.read_bytes() if raw_text is None else raw_text.encode(),
    )
    assert uploaded.status_code == 201, uploaded.text
    dataset_id = uploaded.json()["id"]
    root = f"{settings.API_V1_STR}/projects/{project_id}"
    dataset_url = f"{root}/netflow-datasets/{dataset_id}"
    context = client.post(
        dataset_url + "/processing-contexts",
        headers=headers | {"Idempotency-Key": "context"},
        json=context_request(),
    )
    assert context.status_code == 201, context.text
    me = client.get(f"{settings.API_V1_STR}/users/me", headers=headers)
    assert me.status_code == 200, me.text
    project = db.get(Project, uuid.UUID(project_id))
    actor = db.get(User, uuid.UUID(me.json()["id"]))
    assert project is not None and actor is not None
    db.commit()
    return {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "context_revision_id": context.json()["context_revision_id"],
        "namespace": NAMESPACE,
        "project": project,
        "actor": actor,
        "control": control,
        "dataset_url": dataset_url,
        "root": root,
        "headers": headers,
    }


def reserve(
    client: TestClient,
    setup: dict[str, Any],
    *,
    key: str = "analysis",
    retry: str | None = None,
) -> dict[str, Any]:
    body = {"context_revision_id": setup["context_revision_id"]}
    if retry is not None:
        body["retry_of_analysis_id"] = retry
    response = client.post(
        setup["dataset_url"] + "/analyses",
        headers=setup["headers"] | {"Idempotency-Key": key},
        json=body,
    )
    assert response.status_code == 202, response.text
    value: dict[str, Any] = response.json()
    return value


def execute(db: Session, setup: dict[str, Any], analysis_id: str) -> NetFlowAnalysis:
    db.expire_all()
    row = db.get(NetFlowAnalysis, uuid.UUID(analysis_id))
    assert row is not None
    run = setup["control"].runs[row.agent_run_id]
    assert run.session_id is not None
    execute_analysis(db, row.id, row.agent_run_id, run.session_id)
    db.refresh(row)
    db.commit()
    return row


def published_analysis(
    client: TestClient,
    db: Session,
    headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    raw_text: str | None = None,
) -> dict[str, Any]:
    setup = prepared_dataset(
        client, db, headers, tmp_path, monkeypatch, raw_text=raw_text
    )
    queued = reserve(client, setup)
    execute(db, setup, queued["analysis_id"])
    response = client.get(
        f"{setup['root']}/netflow-analyses/{queued['analysis_id']}", headers=headers
    )
    assert response.status_code == 200, response.text
    analysis = response.json()
    assert analysis["status"] in ("SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"), analysis
    assert (
        analysis["pipeline_complete"] and analysis["feedback_revision_id"] is not None
    )
    return setup | {
        "analysis_id": analysis["analysis_id"],
        "feedback_revision_id": analysis["feedback_revision_id"],
        "analysis": analysis,
    }
