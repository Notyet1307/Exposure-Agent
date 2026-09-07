import hashlib
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.api.routes import governance_reports as report_routes
from app.core.config import settings
from app.core.db import engine
from app.domain import governance_runs as governance_run_service
from app.domain.cloudatlas_sources import (
    CloudAtlasBoundaryError,
    OctobusCloudAtlasClient,
)
from app.domain.governance_runs import RunnerInputs
from app.domain.models import (
    Artifact,
    AuditEvent,
    Evidence,
    Finding,
    GovernanceReport,
    GovernanceRun,
    IPSourceComparisonFact,
    NetFlowDataset,
    NetFlowIPActivity,
    Observation,
    Project,
    RunStep,
    RunStepCode,
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
    assert runtime_inputs.report_contract_version == "deterministic-report-v2"
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
    assert stored_dataset.warnings
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
    assert report.report_contract_version == "deterministic-report-v2"
    assert [
        source["source_type"]
        for source in report.canonical_content["report"]["input_completeness"][
            "sources"
        ]
    ] == ["CUSTOMER_UPLOAD", "CLOUDATLAS", "NETFLOW"]
    comparison_rows = report.canonical_content["report"]["ip_source_comparison"][
        "results"
    ]
    comparison_facts = db.exec(
        select(IPSourceComparisonFact).where(
            IPSourceComparisonFact.governance_run_id == run.id
        )
    ).all()
    assert len(comparison_facts) == len(comparison_rows)
    comparison_evidence = [
        item
        for item in db.exec(
            select(Evidence).where(Evidence.governance_run_id == run.id)
        ).all()
        if item.ip_source_comparison_fact_id is not None
    ]
    assert len(comparison_evidence) == len(
        report.canonical_content["evidence_plan"]["comparison_entries"]
    )
    report_url = (
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-reports/{report.id}"
    )
    detail = client.get(report_url, headers=superuser_token_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_request_ai_governance_draft"] is False
    finding_id = uuid.uuid4()

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("v2 must be rejected before model or Session launch")

    monkeypatch.setattr(report_routes, "_require_current_model_binding", forbidden)
    monkeypatch.setattr(report_routes, "_launch_or_reconcile_draft_session", forbidden)
    draft = client.post(
        f"{report_url}/ai-governance-drafts",
        headers={**superuser_token_headers, "Idempotency-Key": "production-v2-deny"},
        json={"finding_ids": [str(finding_id)]},
    )
    assert draft.status_code == 409, draft.text
    assert draft.json()["detail"]["code"] == "draft_report_contract_unsupported"

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
    report = db.exec(
        select(GovernanceReport).where(GovernanceReport.governance_run_id == run.id)
    ).one()
    assert report.report_contract_version == "deterministic-report-v1"
    assert (
        db.exec(
            select(IPSourceComparisonFact).where(
                IPSourceComparisonFact.governance_run_id == run.id
            )
        ).all()
        == []
    )
    assert all(
        item.ip_source_comparison_fact_id is None
        for item in db.exec(
            select(Evidence).where(Evidence.governance_run_id == run.id)
        ).all()
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
    report = db.exec(
        select(GovernanceReport).where(GovernanceReport.governance_run_id == run.id)
    ).one()
    assert report.report_contract_version == "deterministic-report-v2"
    rows = report.canonical_content["report"]["ip_source_comparison"]["results"]
    assert rows
    assert {(row["netflow_status"], row["netflow_reason"]) for row in rows} == {
        ("UNKNOWN", "no_positive_activity_evidence")
    }
    assert len(
        db.exec(
            select(IPSourceComparisonFact).where(
                IPSourceComparisonFact.governance_run_id == run.id
            )
        ).all()
    ) == len(rows)


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


def test_stale_publish_reentry_converges_after_other_session_commits(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    publish_run = governance_run_service._publish_run
    validate_report = governance_run_service._validate_report_candidate
    monkeypatch.setattr(
        governance_run_service,
        "_validate_report_candidate",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        governance_run_service,
        "_publish_run",
        lambda **_kwargs: None,
    )
    project, _, captured = _prepare_present_run(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        content=_csv("198.51.100.43"),
        trigger_id="stale-publish-reentry",
    )
    assert run_governance_runner() == 0
    monkeypatch.setattr(
        governance_run_service, "_validate_report_candidate", validate_report
    )
    monkeypatch.setattr(governance_run_service, "_publish_run", publish_run)
    project_id = uuid.UUID(str(project["id"]))
    runner_inputs = RunnerInputs.from_environment(captured)

    with (
        Session(engine) as orchestration_session,
        Session(engine, expire_on_commit=False) as stale_session,
    ):
        orchestration_run = orchestration_session.exec(
            select(GovernanceRun).where(GovernanceRun.project_id == project_id)
        ).one()
        assert orchestration_run.status == "RUNNING"
        stale_run = stale_session.exec(
            select(GovernanceRun).where(GovernanceRun.project_id == project_id)
        ).one()
        run_id = stale_run.id
        stale_candidate = governance_run_service._prepare_report_candidate(
            session=stale_session, run=stale_run, reuse_existing=True
        )
        stale_validate, created = governance_run_service._begin_step(
            session=stale_session,
            run=stale_run,
            step_code=RunStepCode.VALIDATE_REPORT,
            input_hash=stale_candidate.build_output_hash,
            request_ip=None,
        )
        assert created and stale_validate.status == "RUNNING"
        stale_session.commit()
        stale_session.refresh(stale_run)

        with Session(engine) as publisher:
            fresh_run = publisher.get(GovernanceRun, run_id)
            assert fresh_run is not None
            fresh_candidate = governance_run_service._prepare_report_candidate(
                session=publisher, run=fresh_run, reuse_existing=True
            )
            governance_run_service._validate_report_candidate(
                session=publisher,
                run=fresh_run,
                candidate=fresh_candidate,
                request_ip=None,
            )
            _, publish_input_hash = governance_run_service._stage4_publish_input(
                session=publisher, run=fresh_run
            )
            _, created = governance_run_service._begin_step(
                session=publisher,
                run=fresh_run,
                step_code=RunStepCode.PUBLISH,
                input_hash=publish_input_hash,
                request_ip=None,
            )
            assert created
            stale_publish = stale_session.exec(
                select(RunStep).where(
                    RunStep.governance_run_id == run_id,
                    RunStep.step_code == RunStepCode.PUBLISH.value,
                )
            ).one()
            assert stale_publish.status == "RUNNING"
            governance_run_service._publish_run(
                session=publisher,
                run=fresh_run,
                request_ip=None,
                report_candidate=fresh_candidate,
            )

        assert stale_run.status == "RUNNING"
        assert stale_validate.status == "RUNNING"
        assert stale_publish.status == "RUNNING"
        governance_run_service._publish_run(
            session=stale_session,
            run=stale_run,
            request_ip=None,
            report_candidate=stale_candidate,
        )
        assert orchestration_run.status == "RUNNING"
        replayed = governance_run_service.execute_governance_run(
            session=orchestration_session, inputs=runner_inputs
        )
        assert replayed.status == "COMPLETED"

    with Session(engine) as session:
        run = session.get(GovernanceRun, run_id)
        assert run is not None and run.status == "COMPLETED"
        assert (
            len(
                session.exec(
                    select(GovernanceReport).where(
                        GovernanceReport.governance_run_id == run.id
                    )
                ).all()
            )
            == 1
        )
        assert (
            len(
                session.exec(
                    select(AuditEvent).where(
                        AuditEvent.target_id == run.id,
                        AuditEvent.action == "governance_run.published",
                    )
                ).all()
            )
            == 1
        )
        publish_step = session.exec(
            select(RunStep).where(
                RunStep.governance_run_id == run.id,
                RunStep.step_code == "PUBLISH",
            )
        ).one()
        assert (publish_step.status, publish_step.attempt) == ("SUCCEEDED", 1)


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
    bind_comparison = governance_run_service._bind_report_comparison

    def fail_publish(*args: object, **kwargs: object) -> None:
        bind_comparison(*args, **kwargs)  # type: ignore[arg-type]
        raise SQLAlchemyError()

    monkeypatch.setattr(governance_run_service, "_bind_report_comparison", fail_publish)
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
    candidate_paths = [
        settings.ARTIFACT_ROOT / storage_key
        for storage_key in governance_run_service._report_candidate_storage_keys(run.id)
    ]
    retained_candidates = [
        (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
        for path in candidate_paths
    ]
    assert (
        db.exec(
            select(IPSourceComparisonFact).where(
                IPSourceComparisonFact.governance_run_id == run.id
            )
        ).all()
        == []
    )
    assert (
        db.exec(
            select(GovernanceReport).where(GovernanceReport.governance_run_id == run.id)
        ).all()
        == []
    )
    assert [
        artifact
        for artifact in db.exec(
            select(Artifact).where(Artifact.governance_run_id == run.id)
        ).all()
        if artifact.media_type in {"text/html", "text/csv"}
    ] == []
    assert (
        db.exec(select(Evidence).where(Evidence.governance_run_id == run.id)).all()
        == []
    )
    assert (
        db.exec(
            select(NetFlowIPActivity).where(
                NetFlowIPActivity.governance_run_id == run.id
            )
        ).all()
        == []
    )
    assert (
        db.exec(select(Finding).where(Finding.project_id == run.project_id)).all() == []
    )
    failed_project = db.get(Project, run.project_id)
    assert failed_project is not None
    assert failed_project.latest_completed_run_id is None
    monkeypatch.setattr(
        governance_run_service,
        "_bind_report_comparison",
        bind_comparison,
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
    assert [
        (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
        for path in candidate_paths
    ] == retained_candidates
    assert db.exec(
        select(IPSourceComparisonFact).where(
            IPSourceComparisonFact.governance_run_id == run.id
        )
    ).all()
    assert (
        governance_run_service.governance_run_public(
            session=db, run=run
        ).reused_snapshot_count
        == 3
    )
