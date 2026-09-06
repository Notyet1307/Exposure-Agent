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
from app.domain import governance_runs as governance_run_service
from app.domain.cloudatlas_sources import (
    CloudAtlasBoundaryError,
    OctobusCloudAtlasClient,
)
from app.domain.governance_runs import RunnerInputs
from app.domain.models import (
    Artifact,
    Evidence,
    Finding,
    GovernanceReport,
    GovernanceRun,
    NetFlowDataset,
    NetFlowIPActivity,
    Observation,
    Project,
    RunStep,
    SourceSnapshot,
)
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


def _prepare_present_run(
    *,
    client: TestClient,
    headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    content: bytes,
    trigger_id: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, str]]:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, headers)
    _prepare_ready_project(client=client, headers=headers, project=project)
    dataset_response = _upload(client, headers, project["id"], content)
    assert dataset_response.status_code == 201, dataset_response.text
    dataset = dataset_response.json()
    assert (
        client.post(
            f"{settings.API_V1_STR}/projects/{project['id']}/netflow-datasets/{dataset['id']}/select",
            headers=headers,
        ).status_code
        == 200
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
            run_id=hashlib.sha256(trigger_id.encode()).hexdigest(),
            started=True,
            status="RUN_STATUS_PENDING",
        )

    monkeypatch.setattr(AgentComposeClient, "start_governance_run", start)
    response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers={**headers, "Idempotency-Key": trigger_id},
    )
    assert response.status_code == 202, response.text
    captured["SANDBOX_ID"] = hashlib.sha256(
        f"{trigger_id}:session".encode()
    ).hexdigest()
    for name, value in captured.items():
        monkeypatch.setenv(name, value)
    return project, dataset, captured


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
        client,
        superuser_token_headers,
        project["id"],
        (
            b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT,start_time,end_time\n"
            b"198.51.100.20,192.0.2.10,6,53000,443,,2026-09-01 08:00:00\n"
            b"198.51.100.21,192.0.2.11,6,53001,443,2026-09-02 08:00:00,\n"
        ),
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
    assert (
        captured["GOVERNANCE_NETFLOW_DATASET_CONTRACT_VERSION"]
        == dataset["dataset_contract_version"]
    )
    reserved_project = db.exec(
        select(Project).where(Project.id == uuid.UUID(str(project["id"])))
    ).one()
    assert (
        reserved_project.governance_launch_input_hash
        == captured["GOVERNANCE_INPUT_HASH"]
    )
    assert (
        db.exec(
            select(GovernanceRun).where(
                GovernanceRun.project_id == uuid.UUID(str(project["id"]))
            )
        ).first()
        is None
    )

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
    assert run.status == "COMPLETED"
    stored_dataset = db.get(NetFlowDataset, uuid.UUID(dataset["id"]))
    assert stored_dataset is not None
    assert stored_dataset.valid_time_start_utc is not None
    assert stored_dataset.valid_time_end_utc is not None
    assert stored_dataset.valid_time_end_utc < stored_dataset.valid_time_start_utc
    netflow_snapshot = db.exec(
        select(SourceSnapshot).where(
            SourceSnapshot.governance_run_id == run.id,
            SourceSnapshot.source_type == "NETFLOW",
        )
    ).one()
    assert netflow_snapshot.netflow_dataset_id == stored_dataset.id
    assert netflow_snapshot.customer_upload_id is None
    assert netflow_snapshot.source_instance_id is None
    assert netflow_snapshot.method_fingerprint is None
    assert netflow_snapshot.artifact_id == stored_dataset.raw_artifact_id
    assert netflow_snapshot.content_sha256 == stored_dataset.raw_sha256
    assert netflow_snapshot.schema_fingerprint == stored_dataset.schema_fingerprint
    assert netflow_snapshot.record_count == stored_dataset.raw_record_count
    assert netflow_snapshot.valid_time_start_utc == stored_dataset.valid_time_start_utc
    assert netflow_snapshot.valid_time_end_utc == stored_dataset.valid_time_end_utc
    assert (
        db.exec(
            select(RunStep).where(
                RunStep.governance_run_id == run.id,
                RunStep.step_code == "LOAD_NETFLOW",
            )
        )
        .one()
        .status
        == "SUCCEEDED"
    )
    assert {
        snapshot.source_type
        for snapshot in db.exec(
            select(SourceSnapshot).where(SourceSnapshot.governance_run_id == run.id)
        ).all()
    } == {"CUSTOMER_UPLOAD", "CLOUDATLAS", "NETFLOW"}
    assert {
        observation.source_type
        for observation in db.exec(
            select(Observation).where(Observation.governance_run_id == run.id)
        ).all()
    } == {"CUSTOMER_UPLOAD", "CLOUDATLAS"}
    report = db.exec(
        select(GovernanceReport).where(GovernanceReport.governance_run_id == run.id)
    ).one()
    assert [
        source["source_type"]
        for source in report.canonical_content["report"]["input_completeness"][
            "sources"
        ]
    ] == ["CUSTOMER_UPLOAD", "CLOUDATLAS"]
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
    first = _upload(
        client, superuser_token_headers, project["id"], _csv("198.51.100.21")
    )
    second = _upload(
        client, superuser_token_headers, project["id"], _csv("198.51.100.22")
    )
    assert first.status_code == 201 and second.status_code == 201
    for dataset_id in (first.json()["id"],):
        assert (
            client.post(
                f"{settings.API_V1_STR}/projects/{project['id']}/netflow-datasets/{dataset_id}/select",
                headers=superuser_token_headers,
            ).status_code
            == 200
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
    assert (
        db.exec(
            select(GovernanceRun).where(
                GovernanceRun.project_id == uuid.UUID(str(project["id"]))
            )
        ).first()
        is None
    )


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
    assert (
        db.exec(
            select(RunStep).where(
                RunStep.governance_run_id == run.id,
                RunStep.step_code == "LOAD_NETFLOW",
            )
        ).one_or_none()
        is None
    )
    assert run.netflow_dataset_id is None
    assert (
        db.exec(
            select(NetFlowIPActivity).where(
                NetFlowIPActivity.governance_run_id == run.id
            )
        ).all()
        == []
    )


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
    first = _upload(
        client, superuser_token_headers, project["id"], _csv("198.51.100.30")
    )
    second = _upload(
        client, superuser_token_headers, project["id"], _csv("198.51.100.31")
    )
    assert first.status_code == 201 and second.status_code == 201
    select_url = f"{settings.API_V1_STR}/projects/{project['id']}/netflow-datasets"
    assert (
        client.post(
            f"{select_url}/{first.json()['id']}/select", headers=superuser_token_headers
        ).status_code
        == 200
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
            run_id=hashlib.sha256(b"retry-drift").hexdigest(),
            started=True,
            status="RUN_STATUS_PENDING",
        )

    monkeypatch.setattr(AgentComposeClient, "start_governance_run", start)
    assert (
        client.post(
            f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
            headers={**superuser_token_headers, "Idempotency-Key": "retry-drift"},
        ).status_code
        == 202
    )
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
    assert (
        client.post(
            f"{select_url}/{second.json()['id']}/select",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )
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
            session_id=str(_session_id),
            observation=AgentComposeSessionObservation.TERMINAL,
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


@pytest.mark.parametrize(
    ("content", "expected_record_count"),
    [
        (
            b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n",
            0,
        ),
        (
            b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
            b"invalid,192.0.2.10,6,53000,443\n",
            1,
        ),
    ],
)
def test_present_zero_activity_dataset_still_completes_with_snapshot(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
    content: bytes,
    expected_record_count: int,
) -> None:
    project, dataset, _ = _prepare_present_run(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        content=content,
        trigger_id=f"zero-netflow-{expected_record_count}",
    )
    assert run_governance_runner() == 0
    run = db.exec(
        select(GovernanceRun).where(
            GovernanceRun.project_id == uuid.UUID(str(project["id"]))
        )
    ).one()
    assert run.status == "COMPLETED"
    snapshot = db.exec(
        select(SourceSnapshot).where(
            SourceSnapshot.governance_run_id == run.id,
            SourceSnapshot.source_type == "NETFLOW",
        )
    ).one()
    assert snapshot.netflow_dataset_id == uuid.UUID(str(dataset["id"]))
    assert snapshot.record_count == expected_record_count
    assert (
        db.exec(
            select(NetFlowIPActivity).where(
                NetFlowIPActivity.governance_run_id == run.id
            )
        ).all()
        == []
    )


def test_netflow_artifact_drift_before_load_fails_data_without_publish(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
) -> None:
    project, dataset, _ = _prepare_present_run(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        content=_csv("198.51.100.40"),
        trigger_id="netflow-drift-before-load",
    )
    stored_dataset = db.get(NetFlowDataset, uuid.UUID(str(dataset["id"])))
    assert stored_dataset is not None
    artifact = db.get(Artifact, stored_dataset.raw_artifact_id)
    assert artifact is not None
    artifact_path = tmp_path / artifact.storage_key
    artifact_path.chmod(0o640)
    artifact_path.write_bytes(artifact_path.read_bytes() + b"\n")

    assert run_governance_runner() == 1
    run = db.exec(
        select(GovernanceRun).where(
            GovernanceRun.project_id == uuid.UUID(str(project["id"]))
        )
    ).one()
    assert run.status == "FAILED_DATA"
    assert (
        db.exec(
            select(RunStep).where(
                RunStep.governance_run_id == run.id,
                RunStep.step_code == "LOAD_NETFLOW",
            )
        )
        .one()
        .error_code
        == "netflow_snapshot_failed"
    )
    assert (
        db.exec(
            select(SourceSnapshot).where(
                SourceSnapshot.governance_run_id == run.id,
                SourceSnapshot.source_type == "NETFLOW",
            )
        ).one_or_none()
        is None
    )
    assert (
        db.exec(
            select(GovernanceReport).where(GovernanceReport.governance_run_id == run.id)
        ).one_or_none()
        is None
    )
    stored_project = db.get(Project, uuid.UUID(str(project["id"])))
    assert stored_project is not None
    db.refresh(stored_project)
    assert stored_project.latest_completed_run_id is None


def test_netflow_artifact_drift_before_publish_fails_data_without_partial_publish(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
) -> None:
    project, dataset, _ = _prepare_present_run(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        content=_csv("198.51.100.41"),
        trigger_id="netflow-drift-before-publish",
    )
    stored_dataset = db.get(NetFlowDataset, uuid.UUID(str(dataset["id"])))
    assert stored_dataset is not None
    artifact = db.get(Artifact, stored_dataset.raw_artifact_id)
    assert artifact is not None
    artifact_path = tmp_path / artifact.storage_key
    validate_report = governance_run_service._validate_report_candidate

    def validate_then_tamper(*args: object, **kwargs: object) -> None:
        validate_report(*args, **kwargs)  # type: ignore[arg-type]
        artifact_path.chmod(0o640)
        artifact_path.write_bytes(artifact_path.read_bytes() + b"\n")

    monkeypatch.setattr(
        governance_run_service, "_validate_report_candidate", validate_then_tamper
    )
    assert run_governance_runner() == 1
    run = db.exec(
        select(GovernanceRun).where(
            GovernanceRun.project_id == uuid.UUID(str(project["id"]))
        )
    ).one()
    assert run.status == "FAILED_DATA"
    assert (
        db.exec(
            select(SourceSnapshot).where(
                SourceSnapshot.governance_run_id == run.id,
                SourceSnapshot.source_type == "NETFLOW",
            )
        )
        .one()
        .content_sha256
        == stored_dataset.raw_sha256
    )
    assert (
        db.exec(
            select(RunStep).where(
                RunStep.governance_run_id == run.id,
                RunStep.step_code == "PUBLISH",
            )
        )
        .one()
        .error_code
        == "netflow_snapshot_failed"
    )
    assert (
        db.exec(
            select(GovernanceReport).where(GovernanceReport.governance_run_id == run.id)
        ).one_or_none()
        is None
    )
    assert (
        db.exec(select(Evidence).where(Evidence.governance_run_id == run.id)).all()
        == []
    )
    assert (
        db.exec(select(Finding).where(Finding.project_id == run.project_id)).all() == []
    )
    stored_project = db.get(Project, uuid.UUID(str(project["id"])))
    assert stored_project is not None
    assert stored_project.latest_completed_run_id is None


def test_retry_reuses_all_three_source_snapshots(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
) -> None:
    project, _, _ = _prepare_present_run(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        content=_csv("198.51.100.42"),
        trigger_id="netflow-publish-retry",
    )
    report_publication_records = governance_run_service._report_publication_records

    def fail_publish(*_args: object, **_kwargs: object) -> None:
        raise SQLAlchemyError()

    monkeypatch.setattr(
        governance_run_service, "_report_publication_records", fail_publish
    )
    assert run_governance_runner() == 1
    run = db.exec(
        select(GovernanceRun).where(
            GovernanceRun.project_id == uuid.UUID(str(project["id"]))
        )
    ).one()
    assert run.status == "FAILED_PROCESSING"
    failed_publish = db.exec(
        select(RunStep).where(
            RunStep.governance_run_id == run.id,
            RunStep.step_code == "PUBLISH",
        )
    ).one()
    failed_input_hash = failed_publish.input_hash
    monkeypatch.setattr(
        governance_run_service,
        "_report_publication_records",
        report_publication_records,
    )

    retried_step = governance_run_service.prepare_retry(
        session=db,
        run=run,
        actor_subject="test-admin",
        request_ip=None,
    )
    assert retried_step.step_code == "PUBLISH"
    assert retried_step.attempt == 2
    assert retried_step.input_hash == failed_input_hash
    assert (
        governance_run_service.governance_run_public(
            session=db, run=run
        ).reused_snapshot_count
        == 3
    )
    assert run_governance_runner() == 0
    db.refresh(run)
    assert run.status == "COMPLETED"
    assert (
        governance_run_service.governance_run_public(
            session=db, run=run
        ).reused_snapshot_count
        == 3
    )
