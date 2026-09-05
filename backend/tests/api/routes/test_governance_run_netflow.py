import hashlib
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.core.config import settings
from app.domain.cloudatlas_sources import (
    CloudAtlasBoundaryError,
    OctobusCloudAtlasClient,
)
from app.domain.governance_runs import RunnerInputs
from app.domain.models import GovernanceRun, Project, SourceSnapshot
from app.governance_runner import main as run_governance_runner
from app.integrations.agent_compose import (
    AgentComposeClient,
    AgentComposeRunStart,
    AgentComposeSession,
    AgentComposeSessionObservation,
)
from tests.api.routes.test_governance_runs import (
    _create_project,
    _mock_cloudatlas,
    _prepare_ready_project,
)
from tests.api.routes.test_netflow_datasets import _csv, _upload


def test_present_dataset_is_reserved_then_pinned_at_runner_start(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)

    project = _create_project(client, superuser_token_headers)
    _prepare_ready_project(
        client=client, headers=superuser_token_headers, project=project
    )
    dataset_response = _upload(
        client, superuser_token_headers, project["id"], _csv("198.51.100.20")
    )
    assert dataset_response.status_code == 201, dataset_response.text
    dataset = dataset_response.json()
    selected = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/netflow-datasets/{dataset['id']}/select",
        headers=superuser_token_headers,
    )
    assert selected.status_code == 200, selected.text

    captured: dict[str, str] = {}

    def start(
        _client: object,
        *,
        client_request_id: str,
        environment: dict[str, str],
        session_id: str | None = None,
    ) -> AgentComposeRunStart:
        del _client, client_request_id, session_id
        captured.update(environment)
        return AgentComposeRunStart(
            run_id=hashlib.sha256(b"present-reservation").hexdigest(),
            started=True,
            status="RUN_STATUS_PENDING",
        )

    monkeypatch.setattr(AgentComposeClient, "start_governance_run", start)
    trigger = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers={**superuser_token_headers, "Idempotency-Key": "present-trigger"},
    )
    assert trigger.status_code == 202, trigger.text
    assert captured["GOVERNANCE_INPUT_CONTRACT_VERSION"] == "governance-run-input-v1"
    assert captured["GOVERNANCE_NETFLOW_DATASET_ID"] == dataset["id"]
    assert captured["GOVERNANCE_NETFLOW_CONTENT_SHA256"] == dataset["raw_sha256"]
    assert captured["GOVERNANCE_NETFLOW_DATASET_CONTRACT_VERSION"] == dataset[
        "dataset_contract_version"
    ]
    reserved_project = db.exec(
        select(Project).where(Project.id == uuid.UUID(str(project["id"])))
    ).one()
    assert reserved_project.governance_launch_input_hash == captured["GOVERNANCE_INPUT_HASH"]
    assert db.exec(
        select(GovernanceRun).where(GovernanceRun.project_id == uuid.UUID(str(project["id"])))
    ).first() is None

    captured["SANDBOX_ID"] = hashlib.sha256(b"present-session").hexdigest()
    for name, value in captured.items():
        monkeypatch.setenv(name, value)
    runtime_inputs = RunnerInputs.from_environment(captured)
    assert runtime_inputs.report_contract_version == "deterministic-report-v1"
    assert runtime_inputs.computed_input_hash() == captured["GOVERNANCE_INPUT_HASH"]
    assert run_governance_runner() == 0
    run = db.exec(
        select(GovernanceRun).where(
            GovernanceRun.project_id == uuid.UUID(str(project["id"])),
            GovernanceRun.trigger_id == "present-trigger",
        )
    ).one()
    assert run.input_contract_version == "governance-run-input-v1"
    assert run.input_hash == captured["GOVERNANCE_INPUT_HASH"]
    assert run.netflow_dataset_id == uuid.UUID(dataset["id"])
    assert run.netflow_content_sha256 == dataset["raw_sha256"]
    assert run.netflow_dataset_contract_version == dataset["dataset_contract_version"]
    original = (
        run.netflow_dataset_id,
        run.netflow_content_sha256,
        run.netflow_dataset_contract_version,
        run.input_hash,
    )
    second = _upload(
        client, superuser_token_headers, project["id"], _csv("198.51.100.23")
    )
    assert second.status_code == 201, second.text
    switched = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/netflow-datasets/{second.json()['id']}/select",
        headers=superuser_token_headers,
    )
    assert switched.status_code == 200, switched.text
    db.expire(run)
    db.refresh(run)
    assert (
        run.netflow_dataset_id,
        run.netflow_content_sha256,
        run.netflow_dataset_contract_version,
        run.input_hash,
    ) == original
    run.netflow_content_sha256 = "f" * 64
    db.add(run)
    with pytest.raises(SQLAlchemyError):
        db.commit()
    db.rollback()
    db.refresh(run)
    assert run.netflow_content_sha256 == original[1]


def test_dataset_selection_drift_before_runner_establishment_fails_closed(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    _prepare_ready_project(
        client=client, headers=superuser_token_headers, project=project
    )
    first = _upload(client, superuser_token_headers, project["id"], _csv("198.51.100.21"))
    second = _upload(client, superuser_token_headers, project["id"], _csv("198.51.100.22"))
    assert first.status_code == 201 and second.status_code == 201
    for dataset_id in (first.json()["id"],):
        assert client.post(
            f"{settings.API_V1_STR}/projects/{project['id']}/netflow-datasets/{dataset_id}/select",
            headers=superuser_token_headers,
        ).status_code == 200
    captured: dict[str, str] = {}

    def start(
        _client: object,
        *,
        client_request_id: str,
        environment: dict[str, str],
        session_id: str | None = None,
    ) -> AgentComposeRunStart:
        del _client, client_request_id, session_id
        captured.update(environment)
        return AgentComposeRunStart(
            run_id=hashlib.sha256(b"drift-reservation").hexdigest(),
            started=True,
            status="RUN_STATUS_PENDING",
        )

    monkeypatch.setattr(AgentComposeClient, "start_governance_run", start)
    trigger = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers={**superuser_token_headers, "Idempotency-Key": "drift-trigger"},
    )
    assert trigger.status_code == 202, trigger.text
    switched = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/netflow-datasets/{second.json()['id']}/select",
        headers=superuser_token_headers,
    )
    assert switched.status_code == 200, switched.text
    captured["SANDBOX_ID"] = hashlib.sha256(b"drift-session").hexdigest()
    for name, value in captured.items():
        monkeypatch.setenv(name, value)
    assert run_governance_runner() == 1
    assert db.exec(
        select(GovernanceRun).where(GovernanceRun.project_id == uuid.UUID(str(project["id"])))
    ).first() is None

def test_absent_input_keeps_report_v1_completion_without_netflow_facts(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    _prepare_ready_project(
        client=client, headers=superuser_token_headers, project=project
    )
    captured: dict[str, str] = {}

    def start(
        _client: object,
        *,
        client_request_id: str,
        environment: dict[str, str],
        session_id: str | None = None,
    ) -> AgentComposeRunStart:
        del _client, client_request_id, session_id
        captured.update(environment)
        return AgentComposeRunStart(
            run_id=hashlib.sha256(b"absent-report-v1").hexdigest(),
            started=True,
            status="RUN_STATUS_PENDING",
        )

    monkeypatch.setattr(AgentComposeClient, "start_governance_run", start)
    response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers={**superuser_token_headers, "Idempotency-Key": "absent-trigger"},
    )
    assert response.status_code == 202, response.text
    assert captured["GOVERNANCE_REPORT_CONTRACT_VERSION"] == "deterministic-report-v1"
    captured["SANDBOX_ID"] = hashlib.sha256(b"absent-session").hexdigest()
    for name, value in captured.items():
        monkeypatch.setenv(name, value)
    assert run_governance_runner() == 0
    run = db.exec(
        select(GovernanceRun).where(
            GovernanceRun.project_id == uuid.UUID(str(project["id"])),
            GovernanceRun.trigger_id == "absent-trigger",
        )
    ).one()
    assert run.status == "COMPLETED"
    assert run.report_contract_version == "deterministic-report-v1"
    snapshots = db.exec(
        select(SourceSnapshot).where(SourceSnapshot.governance_run_id == run.id)
    ).all()
    assert {snapshot.source_type for snapshot in snapshots} == {
        "CUSTOMER_UPLOAD",
        "CLOUDATLAS",
    }
    assert run.netflow_dataset_id is None

def test_retry_refuses_dataset_drift_and_rerun_uses_new_dataset_hash(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
) -> None:
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
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CloudAtlasBoundaryError("cloudatlas_upstream_failed")
        ),
    )
    project = _create_project(client, superuser_token_headers)
    _prepare_ready_project(
        client=client, headers=superuser_token_headers, project=project
    )
    first = _upload(client, superuser_token_headers, project["id"], _csv("198.51.100.30"))
    second = _upload(client, superuser_token_headers, project["id"], _csv("198.51.100.31"))
    assert first.status_code == 201 and second.status_code == 201
    select_url = f"{settings.API_V1_STR}/projects/{project['id']}/netflow-datasets"
    assert client.post(f"{select_url}/{first.json()['id']}/select", headers=superuser_token_headers).status_code == 200
    captured: dict[str, str] = {}

    def start(
        _client: object,
        *,
        client_request_id: str,
        environment: dict[str, str],
        session_id: str | None = None,
    ) -> AgentComposeRunStart:
        del _client, client_request_id, session_id
        captured.update(environment)
        return AgentComposeRunStart(
            run_id=hashlib.sha256(b"retry-drift").hexdigest(),
            started=True,
            status="RUN_STATUS_PENDING",
        )

    monkeypatch.setattr(AgentComposeClient, "start_governance_run", start)
    assert client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers={**superuser_token_headers, "Idempotency-Key": "retry-drift"},
    ).status_code == 202
    captured["SANDBOX_ID"] = hashlib.sha256(b"retry-drift-session").hexdigest()
    for name, value in captured.items():
        monkeypatch.setenv(name, value)
    assert run_governance_runner() == 1
    run = db.exec(
        select(GovernanceRun).where(
            GovernanceRun.project_id == uuid.UUID(str(project["id"])),
            GovernanceRun.trigger_id == "retry-drift",
        )
    ).one()
    original_hash = run.input_hash
    assert client.post(f"{select_url}/{second.json()['id']}/select", headers=superuser_token_headers).status_code == 200
    retry = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run.id}/retry",
        headers=superuser_token_headers,
    )
    assert retry.status_code == 409
    assert retry.json()["detail"]["code"] == "run_retry_netflow_input_changed"

    monkeypatch.setattr(
        AgentComposeClient,
        "get_session",
        lambda _client, _session_id: AgentComposeSession(
            session_id=str(_session_id), observation=AgentComposeSessionObservation.TERMINAL
        ),
    )
    rerun_capture: dict[str, str] = {}

    def rerun_start(
        _client: object,
        *,
        client_request_id: str,
        environment: dict[str, str],
        session_id: str | None = None,
    ) -> AgentComposeRunStart:
        del _client, client_request_id, session_id
        rerun_capture.update(environment)
        return AgentComposeRunStart(
            run_id=hashlib.sha256(b"rerun-drift").hexdigest(),
            started=True,
            status="RUN_STATUS_PENDING",
        )

    monkeypatch.setattr(AgentComposeClient, "start_governance_run", rerun_start)
    rerun = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run.id}/rerun",
        headers={**superuser_token_headers, "Idempotency-Key": "rerun-drift"},
    )
    assert rerun.status_code == 202, rerun.text
    assert rerun_capture["GOVERNANCE_NETFLOW_DATASET_ID"] == second.json()["id"]
    assert rerun_capture["GOVERNANCE_INPUT_HASH"] != original_hash
