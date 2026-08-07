import hashlib
import io
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import cast

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook  # type: ignore[import-untyped]
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlmodel import Session, col, func, select

from app.core.config import settings
from app.core.db import engine
from app.domain.cloudatlas_sources import (
    CloudAtlasBoundaryError,
    CloudAtlasFingerprint,
    OctobusCloudAtlasClient,
)
from app.domain.governance_runs import (
    GovernanceRunExecutionError,
    RunnerInputs,
    establish_governance_run,
)
from app.domain.models import (
    Artifact,
    AuditEvent,
    CustomerUpload,
    GovernanceRun,
    GovernanceRunStatus,
    Project,
    RunStep,
    SourceInstance,
    SourceSnapshot,
)
from app.governance_runner import main as run_governance_runner
from app.integrations.agent_compose import (
    AgentComposeBoundaryError,
    AgentComposeClient,
    AgentComposeRunStart,
    AgentComposeSession,
    AgentComposeSessionObservation,
)
from tests.utils.audit import (
    reject_audit_inserts,
    reject_publish_audit_inserts,
    reject_source_snapshot_inserts,
)
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

REQUIRED_HEADERS = ["资产IP", "起始端口", "结束端口", "是否web界面", "web界面url"]
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
VALIDATED_FINGERPRINT = "1" * 64


def _create_project(
    client: TestClient, headers: dict[str, str], *, name: str | None = None
) -> dict[str, object]:
    response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=headers,
        json={"name": name or f"Governance Run Project {uuid.uuid4()}"},
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def _create_member(
    client: TestClient,
    admin_headers: dict[str, str],
    *,
    project_id: object,
    roles: list[str],
) -> dict[str, str]:
    email = random_email()
    password = random_lower_string()
    user_response = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=admin_headers,
        json={"email": email, "password": password},
    )
    assert user_response.status_code == 200
    membership_response = client.post(
        f"{settings.API_V1_STR}/projects/{project_id}/memberships/",
        headers=admin_headers,
        json={"user_id": user_response.json()["id"], "roles": roles},
    )
    assert membership_response.status_code == 201
    return user_authentication_headers(client=client, email=email, password=password)


def _workbook_bytes(ip_address: str = "192.0.2.10") -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(REQUIRED_HEADERS)
    worksheet.append([ip_address, 443, 443, "是", "example.test"])
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _prepare_ready_project(
    *,
    client: TestClient,
    headers: dict[str, str],
    project: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    upload_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=headers,
        files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    )
    assert upload_response.status_code == 201, upload_response.text
    upload = cast(dict[str, object], upload_response.json())
    select_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads/{upload['id']}/select",
        headers=headers,
    )
    assert select_response.status_code == 200, select_response.text

    source_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/cloudatlas-source-instances",
        headers=headers,
        json={"instance_id": "cloudatlas-fixture", "capset_id": "cloudatlas-readonly"},
    )
    assert source_response.status_code == 201, source_response.text
    source = cast(dict[str, object], source_response.json())
    validation_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/cloudatlas-source-instances/{source['id']}/validate",
        headers=headers,
        json={"capset_token": "fixture-capset-token"},
    )
    assert validation_response.status_code == 200, validation_response.text
    enable_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/cloudatlas-source-instances/{source['id']}/enable",
        headers=headers,
    )
    assert enable_response.status_code == 200, enable_response.text
    return upload, source


def _runner_environment(
    *,
    project: dict[str, object],
    upload: dict[str, object],
    source: dict[str, object],
    trigger_id: str,
    session_seed: str,
) -> dict[str, str]:
    return {
        "GOVERNANCE_PROJECT_ID": str(project["id"]),
        "GOVERNANCE_TRIGGER_ID": trigger_id,
        "GOVERNANCE_REQUESTED_BY": str(uuid.uuid4()),
        "GOVERNANCE_REQUEST_IP": "192.0.2.50",
        "GOVERNANCE_CUSTOMER_UPLOAD_ID": str(upload["id"]),
        "GOVERNANCE_CUSTOMER_UPLOAD_SHA256": str(upload["raw_sha256"]),
        "GOVERNANCE_CUSTOMER_PROFILE_ID": str(upload["profile_id"]),
        "GOVERNANCE_CUSTOMER_PROFILE_VERSION": str(upload["profile_version"]),
        "GOVERNANCE_SOURCE_INSTANCE_ID": str(source["id"]),
        "GOVERNANCE_CLOUDATLAS_FINGERPRINT": VALIDATED_FINGERPRINT,
        "GOVERNANCE_CLOUDATLAS_CAPSET_ID": "cloudatlas-readonly",
        "GOVERNANCE_CLOUDATLAS_METHOD": (
            "cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets"
        ),
        "GOVERNANCE_PACKAGE_SHA256": (
            "882a197f630497f00307be613f7c361a32dad156092726e35b2ce9855c0617e9"
        ),
        "GOVERNANCE_DESCRIPTOR_SHA256": (
            "3fada7cb00f3bca132c28d316ea61158522a1a07d3e80a83f9e68010d1a588e0"
        ),
        "GOVERNANCE_RUNNER_BUILD_VERSION": "test-runner-v1",
        "SANDBOX_ID": hashlib.sha256(session_seed.encode()).hexdigest(),
    }


def _mock_cloudatlas(monkeypatch: MonkeyPatch) -> None:
    fingerprint = CloudAtlasFingerprint(VALIDATED_FINGERPRINT)
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "current_fingerprint",
        lambda _client, _source: fingerprint,
    )
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "validate_read",
        lambda _client, _source, *, capset_token: fingerprint,
    )
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _client, _source, *, capset_token, page, size: {
            "items": [
                {"id": "fixture-asset-1", "ip": "192.0.2.10", "status": "valid"}
            ],
            "page": page,
            "size": size,
            "total": 1,
        },
    )


def test_terminal_launch_without_business_run_is_reconciled_by_mutation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    control_run_id = "c" * 64
    with Session(engine) as session:
        stored_project = session.get(Project, uuid.UUID(str(project["id"])))
        assert stored_project is not None
        stored_project.governance_launch_trigger_id = "stale-launch"
        stored_project.governance_launch_control_run_id = control_run_id
        stored_project.governance_launch_input_hash = "e" * 64
        session.add(stored_project)
        session.commit()

    get_run_calls: list[str] = []
    control_status = "RUN_STATUS_RUNNING"

    def get_run(_client: object, requested_id: str) -> AgentComposeRunStart:
        get_run_calls.append(requested_id)
        return AgentComposeRunStart(
            run_id=requested_id,
            started=False,
            status=control_status,
            session_id=None,
        )

    monkeypatch.setattr(AgentComposeClient, "get_run", get_run)
    monkeypatch.setattr(
        AgentComposeClient,
        "start_governance_run",
        lambda _client, **_kwargs: AgentComposeRunStart(
            run_id="d" * 64,
            started=True,
            status="RUN_STATUS_PENDING",
        ),
    )

    blocked_view = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    )
    assert blocked_view.status_code == 200, blocked_view.text
    blocked_payload = blocked_view.json()
    assert blocked_payload["data"] == []
    assert blocked_payload["can_trigger"] is False
    assert blocked_payload["launch_blocking_code"] == "run_launch_in_progress"

    control_status = "RUN_STATUS_FAILED"
    view = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    )
    assert view.status_code == 200, view.text
    payload = view.json()
    assert payload["data"] == []
    assert payload["count"] == 0
    assert payload["can_trigger"] is False
    assert payload["launch_blocking_code"] == "run_launch_in_progress"
    assert get_run_calls == []

    trigger = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers={**superuser_token_headers, "Idempotency-Key": "fresh-trigger"},
    )
    assert trigger.status_code == 202, trigger.text
    assert trigger.json()["accepted"] is True
    assert get_run_calls == [control_run_id]

    with Session(engine) as session:
        stored_project = session.get(Project, uuid.UUID(str(project["id"])))
        assert stored_project is not None
        assert stored_project.governance_launch_trigger_id == "fresh-trigger"
        convergence = session.exec(
            select(AuditEvent).where(
                AuditEvent.project_id == stored_project.id,
                AuditEvent.action == "governance_run.launch_terminal_converged",
            )
        ).one()
        assert convergence.after_data == {
            "reason": "control_run_terminated_before_session"
        }


def test_trigger_rejects_missing_current_customer_upload_before_creating_a_run(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project = _create_project(client, superuser_token_headers)

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers={**superuser_token_headers, "Idempotency-Key": "missing-upload"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "run_customer_upload_not_ready",
            "message": "Select a validated CustomerUpload before triggering a Run.",
        }
    }


def test_runner_creates_two_snapshots_and_atomically_publishes_completed(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
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
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    runner_environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="happy-path",
        session_seed="governance-session",
    )
    session_id = runner_environment["SANDBOX_ID"]
    for name, value in runner_environment.items():
        monkeypatch.setenv(name, value)

    assert run_governance_runner() == 0

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] == 1
    run = payload["data"][0]
    assert run["trigger_id"] == "happy-path"
    assert run["session_id"] == session_id
    assert run["status"] == "COMPLETED"
    assert [step["step_code"] for step in run["steps"]] == [
        "LOAD_CUSTOMER",
        "PULL_CLOUDATLAS",
        "PUBLISH",
    ]
    assert [step["status"] for step in run["steps"]] == [
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
    ]
    assert {
        (snapshot["source_type"], snapshot["record_count"])
        for snapshot in run["snapshots"]
    } == {("CUSTOMER_UPLOAD", 1), ("CLOUDATLAS", 1)}
    assert all(len(snapshot["content_sha256"]) == 64 for snapshot in run["snapshots"])
    assert not any(name in os.environ for name in ("CLOUDATLAS_TOKEN", "OCTOBUS_TOKEN"))

    audit_before = client.get(
        f"{settings.API_V1_STR}/audit-events/", headers=superuser_token_headers
    ).json()["data"]
    idempotent_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers={**superuser_token_headers, "Idempotency-Key": "happy-path"},
    )
    assert idempotent_response.status_code == 200
    assert idempotent_response.json()["governance_run_id"] == run["id"]
    assert idempotent_response.json()["accepted"] is False
    audit_after = client.get(
        f"{settings.API_V1_STR}/audit-events/", headers=superuser_token_headers
    ).json()["data"]
    assert sum(
        event["action"] == "governance_run.triggered" for event in audit_after
    ) == sum(event["action"] == "governance_run.triggered" for event in audit_before)


def test_cloudatlas_failure_stops_before_publish_without_a_completed_result(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
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
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )

    def fail_cloudatlas_page(
        _client: object,
        _source: object,
        *,
        capset_token: str,
        page: int,
        size: int,
    ) -> dict[str, object]:
        del capset_token, page, size
        raise CloudAtlasBoundaryError("cloudatlas_upstream_failed")

    monkeypatch.setattr(
        OctobusCloudAtlasClient, "list_ip_assets_page", fail_cloudatlas_page
    )
    runner_environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="cloudatlas-failure",
        session_seed="cloudatlas-failure-session",
    )
    for name, value in runner_environment.items():
        monkeypatch.setenv(name, value)

    assert run_governance_runner() == 1

    payload = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()
    run = payload["data"][0]
    assert run["status"] == "FAILED_DATA"
    assert [(step["step_code"], step["status"]) for step in run["steps"]] == [
        ("LOAD_CUSTOMER", "SUCCEEDED"),
        ("PULL_CLOUDATLAS", "FAILED"),
    ]
    assert [snapshot["source_type"] for snapshot in run["snapshots"]] == [
        "CUSTOMER_UPLOAD"
    ]
    with Session(engine) as session:
        stored_project = session.get(Project, uuid.UUID(str(project["id"])))
        assert stored_project is not None
        assert stored_project.latest_completed_run_id is None
    cloudatlas_directory = tmp_path / "cloudatlas_snapshots"
    assert not cloudatlas_directory.exists() or not list(cloudatlas_directory.iterdir())

    monkeypatch.setattr(
        "app.api.routes.governance_runs.AgentComposeClient.get_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.UNKNOWN,
        ),
    )
    retry_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run['id']}/retry",
        headers=superuser_token_headers,
    )
    rerun_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run['id']}/rerun",
        headers={**superuser_token_headers, "Idempotency-Key": "unknown-rerun"},
    )
    new_trigger_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers={**superuser_token_headers, "Idempotency-Key": "unknown-new-run"},
    )
    assert retry_response.status_code == 409
    assert rerun_response.status_code == 409
    assert new_trigger_response.status_code == 409
    assert {
        retry_response.json()["detail"]["code"],
        rerun_response.json()["detail"]["code"],
        new_trigger_response.json()["detail"]["code"],
    } == {"run_session_state_unknown"}
    with Session(engine) as session:
        assert session.exec(
            select(func.count())
            .select_from(GovernanceRun)
            .where(GovernanceRun.project_id == uuid.UUID(str(project["id"])))
        ).one() == 1
        rejection_events = session.exec(
            select(AuditEvent).where(
                AuditEvent.project_id == uuid.UUID(str(project["id"])),
                col(AuditEvent.action).in_(
                    (
                        "governance_run.retry_rejected",
                        "governance_run.rerun_rejected",
                        "governance_run.new_trigger_rejected",
                    )
                ),
            )
        ).all()
        assert len(rejection_events) == 3
        assert {
            cast(dict[str, object], event.after_data)["reason"]
            for event in rejection_events
        } == {"run_session_state_unknown"}
        assert "cloudatlas_upstream_failed" not in str(
            [event.after_data for event in rejection_events]
        )

    monkeypatch.setattr(
        "app.api.routes.governance_runs.AgentComposeClient.get_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.RUNNING,
        ),
    )
    running_responses = (
        client.post(
            f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run['id']}/retry",
            headers=superuser_token_headers,
        ),
        client.post(
            f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run['id']}/rerun",
            headers={
                **superuser_token_headers,
                "Idempotency-Key": "running-rerun",
            },
        ),
        client.post(
            f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
            headers={
                **superuser_token_headers,
                "Idempotency-Key": "running-new-run",
            },
        ),
    )
    assert {response.status_code for response in running_responses} == {409}
    assert {
        response.json()["detail"]["code"] for response in running_responses
    } == {"run_session_still_running"}
    with Session(engine) as session:
        assert session.exec(
            select(func.count())
            .select_from(GovernanceRun)
            .where(GovernanceRun.project_id == uuid.UUID(str(project["id"])))
        ).one() == 1
        rejection_events = session.exec(
            select(AuditEvent).where(
                AuditEvent.project_id == uuid.UUID(str(project["id"])),
                col(AuditEvent.action).in_(
                    (
                        "governance_run.retry_rejected",
                        "governance_run.rerun_rejected",
                        "governance_run.new_trigger_rejected",
                    )
                ),
            )
        ).all()
        assert len(rejection_events) == 6
        assert {
            cast(dict[str, object], event.after_data)["reason"]
            for event in rejection_events
        } == {"run_session_state_unknown", "run_session_still_running"}


@pytest.mark.parametrize(
    "failure_code",
    [
        "customer_artifact_read_failed",
        "cloudatlas_authentication_failed",
        "cloudatlas_authorization_failed",
        "cloudatlas_connectivity_failed",
        "cloudatlas_upstream_failed",
        "cloudatlas_response_contract_failed",
    ],
)
def test_each_source_boundary_failure_is_failed_data(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    failure_code: str,
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
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id=failure_code,
        session_seed=f"{failure_code}-session",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    customer_failure = failure_code == "customer_artifact_read_failed"
    if customer_failure:
        with Session(engine) as session:
            stored_upload = session.get(
                CustomerUpload, uuid.UUID(str(upload["id"]))
            )
            assert stored_upload is not None
            artifact = session.get(Artifact, stored_upload.artifact_id)
            assert artifact is not None
            (tmp_path / artifact.storage_key).unlink()
    else:
        monkeypatch.setattr(
            OctobusCloudAtlasClient,
            "list_ip_assets_page",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                CloudAtlasBoundaryError(failure_code)
            ),
        )

    assert run_governance_runner() == 1

    run = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    assert run["status"] == "FAILED_DATA"
    assert [
        (step["step_code"], step["status"], step["error_code"])
        for step in run["steps"]
    ] == (
        [("LOAD_CUSTOMER", "FAILED", "customer_snapshot_failed")]
        if customer_failure
        else [
            ("LOAD_CUSTOMER", "SUCCEEDED", None),
            ("PULL_CLOUDATLAS", "FAILED", "cloudatlas_snapshot_failed"),
        ]
    )
    assert [snapshot["source_type"] for snapshot in run["snapshots"]] == (
        [] if customer_failure else ["CUSTOMER_UPLOAD"]
    )
    with Session(engine) as session:
        stored_project = session.get(Project, uuid.UUID(str(project["id"])))
        assert stored_project is not None
        assert stored_project.latest_completed_run_id is None


def test_source_snapshot_persistence_failure_is_failed_processing(
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
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="source-snapshot-persistence-failure",
        session_seed="source-snapshot-persistence-failure-session",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with reject_source_snapshot_inserts(db):
        assert run_governance_runner() == 1

    run = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    assert run["status"] == "FAILED_PROCESSING"
    assert [
        (step["step_code"], step["status"], step["error_code"])
        for step in run["steps"]
    ] == [
        ("LOAD_CUSTOMER", "FAILED", "customer_snapshot_processing_failed")
    ]
    assert run["snapshots"] == []
    with Session(engine) as session:
        stored_project = session.get(Project, uuid.UUID(str(project["id"])))
        assert stored_project is not None
        assert stored_project.latest_completed_run_id is None


def test_artifact_persistence_failure_is_failed_processing(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
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
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="artifact-failure",
        session_seed="artifact-failure-session",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        "app.domain.governance_runs.os.replace",
        lambda _source, _destination: (_ for _ in ()).throw(OSError("disk full")),
    )

    assert run_governance_runner() == 1

    run = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    assert run["status"] == "FAILED_PROCESSING"
    assert [(step["step_code"], step["status"]) for step in run["steps"]] == [
        ("LOAD_CUSTOMER", "SUCCEEDED"),
        ("PULL_CLOUDATLAS", "FAILED"),
    ]
    assert [snapshot["source_type"] for snapshot in run["snapshots"]] == [
        "CUSTOMER_UPLOAD"
    ]
    with Session(engine) as session:
        stored_project = session.get(Project, uuid.UUID(str(project["id"])))
        assert stored_project is not None
        assert stored_project.latest_completed_run_id is None


def test_retry_recovers_when_the_session_stops_before_runner_reentry(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
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
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="retry-before-first-step",
        session_seed="retry-before-first-step-session",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    inputs = RunnerInputs.from_environment(environment)
    with Session(engine) as session:
        run = establish_governance_run(session=session, inputs=inputs)
        run_id = run.id

    session_id = environment["SANDBOX_ID"]
    session_observation = AgentComposeSessionObservation.TERMINAL

    def get_session(
        _client: object, requested_id: str
    ) -> AgentComposeSession:
        return AgentComposeSession(
            session_id=requested_id,
            observation=session_observation,
        )

    monkeypatch.setattr(AgentComposeClient, "get_session", get_session)
    monkeypatch.setattr(
        AgentComposeClient,
        "resume_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.RUNNING,
        ),
    )
    control_status = "RUN_STATUS_FAILED"
    control_error: str | None = None
    control_session_id = session_id
    started_requests: list[str] = []

    def get_run(
        _client: object, requested_id: str
    ) -> AgentComposeRunStart:
        if control_error is not None:
            raise AgentComposeBoundaryError(control_error)
        return AgentComposeRunStart(
            run_id=requested_id,
            started=False,
            status=control_status,
            session_id=control_session_id,
        )

    def start_run(
        _client: object,
        *,
        client_request_id: str,
        environment: dict[str, str],
        session_id: str | None = None,
    ) -> AgentComposeRunStart:
        del environment
        assert session_id == inputs.session_id
        started_requests.append(client_request_id)
        return AgentComposeRunStart(
            run_id=hashlib.sha256(client_request_id.encode()).hexdigest(),
            started=True,
            status="RUN_STATUS_PENDING",
            session_id=session_id,
        )

    monkeypatch.setattr(AgentComposeClient, "get_run", get_run)
    monkeypatch.setattr(AgentComposeClient, "start_governance_run", start_run)

    first_retry = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run_id}/retry",
        headers=superuser_token_headers,
    )
    assert first_retry.status_code == 202, first_retry.text
    assert started_requests[-1].endswith(":retry:1")

    prepared_view = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    )
    assert prepared_view.status_code == 200, prepared_view.text
    prepared_run = prepared_view.json()["data"][0]
    assert prepared_run["status"] == "RUNNING"
    assert prepared_run["can_retry"] is True
    assert prepared_run["can_rerun"] is False
    assert prepared_run["blocking_code"] is None

    control_error = "agent_compose_unavailable"
    unavailable_retry = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run_id}/retry",
        headers=superuser_token_headers,
    )
    assert unavailable_retry.status_code == 503, unavailable_retry.text
    assert unavailable_retry.json()["detail"]["code"] == control_error
    with Session(engine) as session:
        rejection = session.exec(
            select(AuditEvent).where(
                AuditEvent.target_id == run_id,
                AuditEvent.action == "governance_run.retry_rejected",
            )
        ).one()
        assert rejection.after_data == {"reason": control_error}
    control_error = None

    control_session_id = hashlib.sha256(b"wrong-session").hexdigest()
    mismatched_retry = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run_id}/retry",
        headers=superuser_token_headers,
    )
    assert mismatched_retry.status_code == 503, mismatched_retry.text
    assert mismatched_retry.json()["detail"]["code"] == (
        "agent_compose_response_contract_failed"
    )
    with Session(engine) as session:
        rejection_reasons = {
            cast(dict[str, object], event.after_data)["reason"]
            for event in session.exec(
                select(AuditEvent).where(
                    AuditEvent.target_id == run_id,
                    AuditEvent.action == "governance_run.retry_rejected",
                )
            ).all()
        }
        assert rejection_reasons == {
            "agent_compose_unavailable",
            "agent_compose_response_contract_failed",
        }
    control_session_id = session_id

    second_retry = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run_id}/retry",
        headers=superuser_token_headers,
    )
    assert second_retry.status_code == 202, second_retry.text
    assert started_requests[-1].endswith(":retry:2")

    with Session(engine) as session:
        stored = session.get(GovernanceRun, run_id)
        assert stored is not None
        stored.session_recovery_code = None
        session.add(stored)
        session.commit()
    retry_after_terminal = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run_id}/retry",
        headers=superuser_token_headers,
    )
    assert retry_after_terminal.status_code == 202, retry_after_terminal.text
    assert started_requests[-1].endswith(":retry:3")

    with Session(engine) as session:
        stored = session.get(GovernanceRun, run_id)
        assert stored is not None
        stored.session_recovery_code = None
        session.add(stored)
        session.commit()
    session_observation = AgentComposeSessionObservation.RUNNING
    control_status = "RUN_STATUS_RUNNING"
    duplicate_retry = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run_id}/retry",
        headers=superuser_token_headers,
    )
    assert duplicate_retry.status_code == 200, duplicate_retry.text
    assert duplicate_retry.json()["code"] == "run_retry_in_progress"
    assert duplicate_retry.json()["agent_compose_status"] == "RETRY_IN_PROGRESS"
    with Session(engine) as session:
        stored = session.get(GovernanceRun, run_id)
        assert stored is not None
        assert stored.session_recovery_code is None
        step = session.exec(
            select(RunStep).where(RunStep.governance_run_id == run_id)
        ).one()
        assert (step.step_code, step.status, step.attempt) == (
            "LOAD_CUSTOMER",
            "RUNNING",
            3,
        )

    assert run_governance_runner() == 0
    with Session(engine) as session:
        completed = session.get(GovernanceRun, run_id)
        assert completed is not None
        assert completed.status == GovernanceRunStatus.COMPLETED.value
        assert completed.session_recovery_code is None


@pytest.mark.parametrize(
    ("completed_codes", "next_code"),
    [
        (("LOAD_CUSTOMER",), "PULL_CLOUDATLAS"),
        (("LOAD_CUSTOMER", "PULL_CLOUDATLAS"), "PUBLISH"),
    ],
)
def test_retry_starts_the_first_step_missing_after_session_termination(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    completed_codes: tuple[str, ...],
    next_code: str,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    inputs = RunnerInputs.from_environment(
        _runner_environment(
            project=project,
            upload=upload,
            source=source,
            trigger_id=f"resume-before-{next_code.lower()}",
            session_seed=f"resume-before-{next_code.lower()}-session",
        )
    )
    with Session(engine) as session:
        run = establish_governance_run(session=session, inputs=inputs)
        for index, step_code in enumerate(completed_codes, start=1):
            session.add(
                RunStep(
                    tenant_id=run.tenant_id,
                    project_id=run.project_id,
                    governance_run_id=run.id,
                    step_code=step_code,
                    status="SUCCEEDED",
                    input_hash=f"{index}" * 64,
                    output_hash=f"{index + 2}" * 64,
                )
            )
        if next_code == "PUBLISH":
            stored_upload = session.get(
                CustomerUpload, uuid.UUID(str(upload["id"]))
            )
            assert stored_upload is not None
            cloudatlas_artifact = Artifact(
                tenant_id=run.tenant_id,
                storage_key=f"tests/{run.id}/cloudatlas.json",
                media_type="application/json",
                byte_size=2,
                sha256="5" * 64,
            )
            session.add(cloudatlas_artifact)
            session.flush()
            session.add_all(
                (
                    SourceSnapshot(
                        tenant_id=run.tenant_id,
                        project_id=run.project_id,
                        governance_run_id=run.id,
                        source_type="CUSTOMER_UPLOAD",
                        customer_upload_id=run.customer_upload_id,
                        artifact_id=stored_upload.artifact_id,
                        content_sha256=run.customer_upload_sha256,
                        schema_fingerprint="6" * 64,
                        record_count=1,
                    ),
                    SourceSnapshot(
                        tenant_id=run.tenant_id,
                        project_id=run.project_id,
                        governance_run_id=run.id,
                        source_type="CLOUDATLAS",
                        source_instance_id=run.source_instance_id,
                        artifact_id=cloudatlas_artifact.id,
                        content_sha256=cloudatlas_artifact.sha256,
                        schema_fingerprint="7" * 64,
                        method_fingerprint=run.cloudatlas_validated_fingerprint,
                        record_count=1,
                    ),
                )
            )
        session.commit()
        run_id = run.id
        session_id = run.session_id

    monkeypatch.setattr(
        AgentComposeClient,
        "get_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.TERMINAL,
        ),
    )
    monkeypatch.setattr(
        AgentComposeClient,
        "resume_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.RUNNING,
        ),
    )
    monkeypatch.setattr(
        AgentComposeClient,
        "start_governance_run",
        lambda _client, **_kwargs: AgentComposeRunStart(
            run_id="8" * 64,
            started=True,
            status="RUN_STATUS_PENDING",
            session_id=session_id,
        ),
    )

    retry = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run_id}/retry",
        headers=superuser_token_headers,
    )

    assert retry.status_code == 202, retry.text
    assert retry.json()["session_id"] == session_id
    recovered = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    assert [
        (step["step_code"], step["status"], step["attempt"])
        for step in recovered["steps"]
    ] == [
        *((step_code, "SUCCEEDED", 1) for step_code in completed_codes),
        (next_code, "RUNNING", 1),
    ]
    assert recovered["reused_snapshot_count"] == (
        2 if next_code == "PUBLISH" else 0
    )
    with Session(engine) as session:
        started = session.exec(
            select(AuditEvent).where(
                AuditEvent.project_id == uuid.UUID(str(project["id"])),
                AuditEvent.action == "run_step.started",
            )
        ).one()
        assert cast(dict[str, object], started.after_data)["step_code"] == next_code


def test_retry_is_blocked_by_an_outstanding_rerun_launch(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    inputs = RunnerInputs.from_environment(
        _runner_environment(
            project=project,
            upload=upload,
            source=source,
            trigger_id="retry-reservation-original",
            session_seed="retry-reservation-session",
        )
    )
    with Session(engine) as session:
        run = establish_governance_run(session=session, inputs=inputs)
        run.status = GovernanceRunStatus.FAILED_PROCESSING.value
        session.add(run)
        session.add(
            RunStep(
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                governance_run_id=run.id,
                step_code="LOAD_CUSTOMER",
                status="FAILED",
                input_hash=run.customer_upload_sha256,
                error_code="session_terminated",
            )
        )
        stored_project = session.get(Project, run.project_id)
        assert stored_project is not None
        stored_project.governance_launch_trigger_id = "outstanding-rerun"
        stored_project.governance_launch_control_run_id = "f" * 64
        stored_project.governance_launch_input_hash = "e" * 64
        session.add(stored_project)
        session.commit()
        run_id = run.id

    monkeypatch.setattr(
        AgentComposeClient,
        "get_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.TERMINAL,
        ),
    )
    blocked_view = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    )
    assert blocked_view.status_code == 200, blocked_view.text
    blocked_run = blocked_view.json()["data"][0]
    assert blocked_run["can_retry"] is False
    assert blocked_run["can_rerun"] is False
    assert blocked_run["blocking_code"] == "run_launch_in_progress"

    control_status = "RUN_STATUS_PENDING"
    control_error: str | None = "agent_compose_unavailable"

    def get_run(
        _client: object, requested_id: str
    ) -> AgentComposeRunStart:
        if control_error is not None:
            raise AgentComposeBoundaryError(control_error)
        return AgentComposeRunStart(
            run_id=requested_id,
            started=False,
            status=control_status,
            session_id=None,
        )

    monkeypatch.setattr(AgentComposeClient, "get_run", get_run)
    monkeypatch.setattr(
        AgentComposeClient,
        "get_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.TERMINAL,
        ),
    )
    started = False

    def start_run(*_args: object, **_kwargs: object) -> AgentComposeRunStart:
        nonlocal started
        started = True
        return AgentComposeRunStart(
            run_id="d" * 64, started=True, status="RUN_STATUS_PENDING"
        )

    monkeypatch.setattr(AgentComposeClient, "start_governance_run", start_run)
    unavailable_rerun = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run_id}/rerun",
        headers={
            **superuser_token_headers,
            "Idempotency-Key": "candidate-rerun",
        },
    )
    assert unavailable_rerun.status_code == 409, unavailable_rerun.text
    assert unavailable_rerun.json()["detail"]["code"] == "run_launch_in_progress"

    control_error = None
    response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run_id}/retry",
        headers=superuser_token_headers,
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "run_launch_in_progress"
    assert started is False
    with Session(engine) as session:
        rejection = session.exec(
            select(AuditEvent).where(
                AuditEvent.target_id == run_id,
                AuditEvent.action == "governance_run.retry_rejected",
            )
        ).one()
        assert rejection.after_data == {"reason": "run_launch_in_progress"}

    control_status = "RUN_STATUS_FAILED"
    terminal_rerun = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run_id}/rerun",
        headers={
            **superuser_token_headers,
            "Idempotency-Key": "outstanding-rerun",
        },
    )
    assert terminal_rerun.status_code == 409, terminal_rerun.text
    assert terminal_rerun.json()["detail"]["code"] == (
        "run_launch_terminal_use_new_trigger"
    )
    assert started is False
    with Session(engine) as session:
        rerun_rejections = session.exec(
            select(AuditEvent).where(
                AuditEvent.target_id == run_id,
                AuditEvent.action == "governance_run.rerun_rejected",
            )
        ).all()
        assert {
            cast(dict[str, object], event.after_data)["reason"]
            for event in rerun_rejections
        } == {
            "run_launch_in_progress",
            "run_launch_terminal_use_new_trigger",
        }


def test_retry_resumes_the_same_session_and_reuses_successful_snapshot(
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
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    runner_environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="retry-cloudatlas",
        session_seed="retry-cloudatlas-session",
    )
    for name, value in runner_environment.items():
        monkeypatch.setenv(name, value)

    calls = 0

    def fail_first_page(
        _client: object,
        _source: object,
        *,
        capset_token: str,
        page: int,
        size: int,
    ) -> dict[str, object]:
        nonlocal calls
        del capset_token
        calls += 1
        if calls == 1:
            raise CloudAtlasBoundaryError("cloudatlas_upstream_failed")
        return {
            "items": [
                {"id": "fixture-asset-1", "ip": "192.0.2.10", "status": "valid"}
            ],
            "page": page,
            "size": size,
            "total": 1,
        }

    monkeypatch.setattr(
        OctobusCloudAtlasClient, "list_ip_assets_page", fail_first_page
    )
    assert run_governance_runner() == 1
    failed = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    customer_snapshot_id = next(
        snapshot["id"]
        for snapshot in failed["snapshots"]
        if snapshot["source_type"] == "CUSTOMER_UPLOAD"
    )
    session_id = runner_environment["SANDBOX_ID"]
    monkeypatch.setattr(
        "app.api.routes.governance_runs.AgentComposeClient.get_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.TERMINAL,
        ),
    )
    resume_entered = Event()
    release_resume = Event()

    def resume_session(
        _client: object, requested_id: str
    ) -> AgentComposeSession:
        resume_entered.set()
        assert release_resume.wait(timeout=5)
        return AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.RUNNING,
        )

    monkeypatch.setattr(
        "app.api.routes.governance_runs.AgentComposeClient.resume_session",
        resume_session,
    )
    monkeypatch.setattr(
        "app.api.routes.governance_runs.AgentComposeClient.start_governance_run",
        lambda _client, **_kwargs: AgentComposeRunStart(
            run_id="d" * 64,
            started=True,
            status="RUN_STATUS_RUNNING",
            session_id=session_id,
        ),
    )
    monkeypatch.setattr(
        "app.api.routes.governance_runs.AgentComposeClient.get_run",
        lambda _client, requested_id: AgentComposeRunStart(
            run_id=requested_id,
            started=False,
            status="RUN_STATUS_RUNNING",
            session_id=session_id,
        ),
    )

    with reject_audit_inserts(db), pytest.raises(ProgrammingError):
        client.post(
            f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{failed['id']}/retry",
            headers=superuser_token_headers,
        )
    rolled_back = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    assert rolled_back["status"] == "FAILED_DATA"
    assert {
        step["step_code"]: step["attempt"] for step in rolled_back["steps"]
    } == {"LOAD_CUSTOMER": 1, "PULL_CLOUDATLAS": 1}

    with ThreadPoolExecutor(max_workers=2) as executor:
        retry_future = executor.submit(
            client.post,
            f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{failed['id']}/retry",
            headers=superuser_token_headers,
        )
        assert resume_entered.wait(timeout=5)
        concurrent_rerun = client.post(
            f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{failed['id']}/rerun",
            headers={
                **superuser_token_headers,
                "Idempotency-Key": "retry-race-rerun",
            },
        )
        assert concurrent_rerun.status_code == 409
        assert concurrent_rerun.json()["detail"]["code"] == "run_retry_in_progress"
        release_resume.set()
        retry_response = retry_future.result(timeout=5)
    assert retry_response.status_code == 202, retry_response.text
    assert retry_response.json()["governance_run_id"] == failed["id"]
    assert retry_response.json()["session_id"] == session_id

    duplicate_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{failed['id']}/retry",
        headers=superuser_token_headers,
    )
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["accepted"] is False

    assert run_governance_runner() == 0
    completed = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    assert completed["status"] == "COMPLETED"
    assert completed["session_id"] == session_id
    assert next(
        snapshot["id"]
        for snapshot in completed["snapshots"]
        if snapshot["source_type"] == "CUSTOMER_UPLOAD"
    ) == customer_snapshot_id
    assert {
        step["step_code"]: step["attempt"] for step in completed["steps"]
    } == {"LOAD_CUSTOMER": 1, "PULL_CLOUDATLAS": 2, "PUBLISH": 1}
    assert completed["reused_snapshot_count"] == 1


def test_retry_is_blocked_when_the_cloudatlas_run_credential_is_missing(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    inputs = RunnerInputs.from_environment(
        _runner_environment(
            project=project,
            upload=upload,
            source=source,
            trigger_id="retry-missing-credential",
            session_seed="retry-missing-credential-session",
        )
    )
    with Session(engine) as session:
        run = establish_governance_run(session=session, inputs=inputs)
        run.status = GovernanceRunStatus.FAILED_DATA.value
        session.add(
            RunStep(
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                governance_run_id=run.id,
                step_code="PULL_CLOUDATLAS",
                status="FAILED",
                input_hash=run.cloudatlas_validated_fingerprint,
                error_code="cloudatlas_snapshot_failed",
            )
        )
        session.commit()
        run_id = run.id

    monkeypatch.setattr(
        AgentComposeClient,
        "get_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.TERMINAL,
        ),
    )
    monkeypatch.setattr(settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr(""))

    view = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    )
    assert view.status_code == 200, view.text
    run_view = view.json()["data"][0]
    assert run_view["can_retry"] is False
    assert run_view["blocking_code"] == "run_cloudatlas_credential_not_ready"

    retry = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run_id}/retry",
        headers=superuser_token_headers,
    )
    assert retry.status_code == 409, retry.text
    assert retry.json()["detail"]["code"] == "run_cloudatlas_credential_not_ready"


def test_retry_requires_fresh_cloudatlas_validation_after_material_drift(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    inputs = RunnerInputs.from_environment(
        _runner_environment(
            project=project,
            upload=upload,
            source=source,
            trigger_id="retry-invalidated-source",
            session_seed="retry-invalidated-source-session",
        )
    )
    with Session(engine) as session:
        run = establish_governance_run(session=session, inputs=inputs)
        run.status = GovernanceRunStatus.FAILED_DATA.value
        stored_source = session.get(SourceInstance, uuid.UUID(str(source["id"])))
        assert stored_source is not None
        stored_source.validation_error_code = "cloudatlas_material_changed"
        session.add(stored_source)
        session.add(
            RunStep(
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                governance_run_id=run.id,
                step_code="PULL_CLOUDATLAS",
                status="FAILED",
                input_hash=run.cloudatlas_validated_fingerprint,
                error_code="cloudatlas_snapshot_failed",
            )
        )
        session.commit()
        run_id = run.id

    monkeypatch.setattr(
        AgentComposeClient,
        "get_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.TERMINAL,
        ),
    )
    view = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    )
    assert view.status_code == 200, view.text
    run_view = view.json()["data"][0]
    assert run_view["can_retry"] is False
    assert run_view["blocking_code"] == "run_cloudatlas_source_not_ready"

    retry = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run_id}/retry",
        headers=superuser_token_headers,
    )
    assert retry.status_code == 409, retry.text
    assert retry.json()["detail"]["code"] == "run_cloudatlas_source_not_ready"


def test_unrecoverable_retry_requires_an_explicit_rerun(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
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
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="unrecoverable-original",
        session_seed="unrecoverable-original-session",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CloudAtlasBoundaryError("cloudatlas_upstream_failed")
        ),
    )
    assert run_governance_runner() == 1
    original = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    monkeypatch.setattr(
        AgentComposeClient,
        "get_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.TERMINAL,
        ),
    )
    monkeypatch.setattr(
        AgentComposeClient,
        "resume_session",
        lambda *_args: (_ for _ in ()).throw(
            AgentComposeBoundaryError("agent_compose_session_not_recoverable")
        ),
    )

    retry_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{original['id']}/retry",
        headers=superuser_token_headers,
    )

    assert retry_response.status_code == 409
    assert retry_response.json()["detail"]["code"] == "run_session_not_recoverable"
    recovery_view = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    )
    assert recovery_view.status_code == 200
    recovery_run = recovery_view.json()["data"][0]
    assert recovery_run["can_retry"] is False
    assert recovery_run["can_rerun"] is True
    assert recovery_run["blocking_code"] == "run_session_not_recoverable"
    monkeypatch.setattr(
        AgentComposeClient,
        "get_session",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("known unrecoverable Retry must not query the Session")
        ),
    )
    repeated_retry = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{original['id']}/retry",
        headers=superuser_token_headers,
    )
    assert repeated_retry.status_code == 409, repeated_retry.text
    assert repeated_retry.json()["detail"]["code"] == (
        "run_session_not_recoverable"
    )

    monkeypatch.setattr(
        AgentComposeClient,
        "get_session",
        lambda *_args: (_ for _ in ()).throw(
            AgentComposeBoundaryError("agent_compose_unavailable")
        ),
    )
    captured_environment: dict[str, str] = {}
    rerun_start_error = True

    def start_rerun(
        _client: object,
        *,
        client_request_id: str,
        environment: dict[str, str],
        session_id: str | None = None,
    ) -> AgentComposeRunStart:
        nonlocal rerun_start_error
        assert client_request_id.endswith(":unrecoverable-rerun")
        assert session_id is None
        captured_environment.update(environment)
        if rerun_start_error:
            rerun_start_error = False
            raise AgentComposeBoundaryError("agent_compose_unavailable")
        return AgentComposeRunStart(
            run_id="9" * 64, started=True, status="RUN_STATUS_PENDING"
        )

    monkeypatch.setattr(AgentComposeClient, "start_governance_run", start_rerun)
    rerun_headers = {
        **superuser_token_headers,
        "Idempotency-Key": "unrecoverable-rerun",
    }
    failed_rerun = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{original['id']}/rerun",
        headers=rerun_headers,
    )
    assert failed_rerun.status_code == 503
    assert failed_rerun.json()["detail"]["code"] == "agent_compose_unavailable"
    with Session(engine) as session:
        rerun_rejection = session.exec(
            select(AuditEvent).where(
                AuditEvent.target_id == uuid.UUID(str(original["id"])),
                AuditEvent.action == "governance_run.rerun_rejected",
            )
        ).one()
        assert rerun_rejection.after_data == {
            "reason": "agent_compose_unavailable"
        }

    rerun_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{original['id']}/rerun",
        headers=rerun_headers,
    )

    assert rerun_response.status_code == 202, rerun_response.text
    assert captured_environment["GOVERNANCE_TRIGGER_ID"] == "unrecoverable-rerun"
    with Session(engine) as session:
        stored = session.get(GovernanceRun, uuid.UUID(str(original["id"])))
        assert stored is not None
        assert stored.status == GovernanceRunStatus.FAILED_PROCESSING.value
        assert stored.session_recovery_code == "run_session_not_recoverable"
        retry_rejections = session.exec(
            select(AuditEvent).where(
                AuditEvent.target_id == stored.id,
                AuditEvent.action == "governance_run.retry_rejected",
            )
        ).all()
        assert len(retry_rejections) == 2
        assert {
            cast(dict[str, object], event.after_data)["reason"]
            for event in retry_rejections
        } == {"run_session_not_recoverable"}


def test_changed_input_requires_rerun_with_a_new_run_and_session(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
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
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    original_environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="rerun-original",
        session_seed="rerun-original-session",
    )
    for name, value in original_environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CloudAtlasBoundaryError("cloudatlas_upstream_failed")
        ),
    )
    assert run_governance_runner() == 1
    original = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    with Session(engine) as session:
        stored_original = session.get(
            GovernanceRun, uuid.UUID(str(original["id"]))
        )
        assert stored_original is not None
        stored_original.status = GovernanceRunStatus.RUNNING.value
        session.add(stored_original)
        session.commit()

    upload_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=superuser_token_headers,
        files={
            "file": (
                "customer-new.xlsx",
                _workbook_bytes("198.51.100.20"),
                XLSX_MEDIA_TYPE,
            )
        },
    )
    assert upload_response.status_code == 201
    new_upload = upload_response.json()
    assert client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads/{new_upload['id']}/select",
        headers=superuser_token_headers,
    ).status_code == 200
    monkeypatch.setattr(
        "app.api.routes.governance_runs.AgentComposeClient.get_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.TERMINAL,
        ),
    )

    retry_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{original['id']}/retry",
        headers=superuser_token_headers,
    )
    assert retry_response.status_code == 409
    assert retry_response.json()["detail"]["code"] == (
        "run_retry_customer_input_changed"
    )

    captured_environment: dict[str, str] = {}

    def start_rerun(
        _client: object,
        *,
        client_request_id: str,
        environment: dict[str, str],
        session_id: str | None = None,
    ) -> AgentComposeRunStart:
        assert client_request_id.endswith(":rerun-new")
        assert session_id is None
        captured_environment.update(environment)
        return AgentComposeRunStart(
            run_id="e" * 64, started=True, status="RUNNING"
        )

    monkeypatch.setattr(
        "app.api.routes.governance_runs.AgentComposeClient.start_governance_run",
        start_rerun,
    )
    rerun_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{original['id']}/rerun",
        headers={**superuser_token_headers, "Idempotency-Key": "rerun-new"},
    )
    assert rerun_response.status_code == 202, rerun_response.text
    assert captured_environment["GOVERNANCE_CUSTOMER_UPLOAD_ID"] == new_upload["id"]
    assert captured_environment["GOVERNANCE_TRIGGER_ID"] == "rerun-new"

    _mock_cloudatlas(monkeypatch)
    for name, value in captured_environment.items():
        monkeypatch.setenv(name, value)
    new_session_id = hashlib.sha256(b"rerun-new-session").hexdigest()
    monkeypatch.setenv("SANDBOX_ID", new_session_id)
    assert run_governance_runner() == 0

    runs = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"]
    assert len(runs) == 2
    assert runs[0]["status"] == "COMPLETED"
    assert runs[0]["trigger_id"] == "rerun-new"
    assert runs[0]["session_id"] == new_session_id
    assert runs[1]["id"] == original["id"]
    assert runs[1]["status"] == "FAILED_PROCESSING"

    duplicate_rerun = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{original['id']}/rerun",
        headers={**superuser_token_headers, "Idempotency-Key": "rerun-new"},
    )
    assert duplicate_rerun.status_code == 200, duplicate_rerun.text
    assert duplicate_rerun.json()["governance_run_id"] == runs[0]["id"]

    conflicting_trigger = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{original['id']}/rerun",
        headers={
            **superuser_token_headers,
            "Idempotency-Key": original["trigger_id"],
        },
    )
    assert conflicting_trigger.status_code == 409, conflicting_trigger.text
    assert conflicting_trigger.json()["detail"]["code"] == (
        "run_rerun_trigger_conflict"
    )

    historical_retry = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{original['id']}/retry",
        headers=superuser_token_headers,
    )
    assert historical_retry.status_code == 409
    assert historical_retry.json()["detail"]["code"] == (
        "run_retry_newer_run_exists"
    )
    historical_rerun = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{original['id']}/rerun",
        headers={
            **superuser_token_headers,
            "Idempotency-Key": "historical-rerun-blocked",
        },
    )
    assert historical_rerun.status_code == 409
    assert historical_rerun.json()["detail"]["code"] == (
        "run_rerun_newer_run_exists"
    )


def test_postgresql_serializes_same_trigger_and_rejects_a_second_active_run(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    shared = RunnerInputs.from_environment(
        _runner_environment(
            project=project,
            upload=upload,
            source=source,
            trigger_id="same-trigger",
            session_seed="same-session",
        )
    )

    def establish(inputs: RunnerInputs) -> tuple[str, str]:
        try:
            with Session(engine) as session:
                run = establish_governance_run(session=session, inputs=inputs)
                return "ok", str(run.id)
        except GovernanceRunExecutionError as error:
            return "error", error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        same_results = list(executor.map(establish, (shared, shared)))
    assert same_results[0] == same_results[1]
    with Session(engine) as session:
        project_id = uuid.UUID(str(project["id"]))
        assert session.exec(
            select(func.count())
            .select_from(GovernanceRun)
            .where(GovernanceRun.project_id == project_id)
        ).one() == 1
        assert session.exec(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.project_id == project_id,
                AuditEvent.action == "governance_run.triggered",
            )
        ).one() == 1
        active = session.exec(
            select(GovernanceRun).where(GovernanceRun.project_id == project_id)
        ).one()
        active.status = GovernanceRunStatus.FAILED_DATA.value
        session.add(active)
        session.commit()

    first = RunnerInputs.from_environment(
        _runner_environment(
            project=project,
            upload=upload,
            source=source,
            trigger_id="different-trigger-a",
            session_seed="different-session-a",
        )
    )
    second = RunnerInputs.from_environment(
        _runner_environment(
            project=project,
            upload=upload,
            source=source,
            trigger_id="different-trigger-b",
            session_seed="different-session-b",
        )
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        different_results = list(executor.map(establish, (first, second)))
    assert sorted(result[0] for result in different_results) == ["error", "ok"]
    assert {
        result[1] for result in different_results if result[0] == "error"
    } == {"runner_project_has_active_run"}


def test_concurrent_initial_triggers_reserve_only_one_runner_launch(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    started: list[str] = []

    def start_run(
        _client: object,
        *,
        client_request_id: str,
        environment: dict[str, str],
        session_id: str | None = None,
    ) -> AgentComposeRunStart:
        del environment, session_id
        started.append(client_request_id)
        return AgentComposeRunStart(
            run_id=hashlib.sha256(client_request_id.encode()).hexdigest(),
            started=True,
            status="RUNNING",
        )

    monkeypatch.setattr(
        "app.api.routes.governance_runs.AgentComposeClient.start_governance_run",
        start_run,
    )
    url = f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs"

    def trigger(trigger_id: str) -> int:
        return cast(
            int,
            client.post(
                url,
                headers={**superuser_token_headers, "Idempotency-Key": trigger_id},
            ).status_code,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(trigger, ("concurrent-a", "concurrent-b")))

    assert sorted(statuses) == [202, 409]
    assert len(started) == 1
    with Session(engine) as session:
        assert session.exec(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.project_id == uuid.UUID(str(project["id"])),
                AuditEvent.action == "governance_run.trigger_requested",
            )
        ).one() == 1
        rejected = session.exec(
            select(AuditEvent).where(
                AuditEvent.project_id == uuid.UUID(str(project["id"])),
                AuditEvent.action == "governance_run.new_trigger_rejected",
            )
        ).one()
        assert rejected.target_type == "project"
        assert rejected.target_id == uuid.UUID(str(project["id"]))
        assert rejected.after_data == {"reason": "run_launch_in_progress"}
        stored_project = session.get(Project, uuid.UUID(str(project["id"])))
        assert stored_project is not None
        assert stored_project.governance_launch_trigger_id in {
            "concurrent-a",
            "concurrent-b",
        }
        reserved_trigger = stored_project.governance_launch_trigger_id
        assert reserved_trigger is not None
        assert session.exec(
            select(func.count())
            .select_from(GovernanceRun)
            .where(GovernanceRun.project_id == stored_project.id)
        ).one() == 0
        control_run_id = stored_project.governance_launch_control_run_id
        assert control_run_id is not None

    monkeypatch.setattr(
        AgentComposeClient,
        "get_run",
        lambda _client, requested_id: AgentComposeRunStart(
            run_id=requested_id,
            started=False,
            status="RUN_STATUS_FAILED",
            session_id=None,
        ),
    )
    terminal_trigger = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers={
            **superuser_token_headers,
            "Idempotency-Key": reserved_trigger,
        },
    )
    assert terminal_trigger.status_code == 409, terminal_trigger.text
    assert terminal_trigger.json()["detail"]["code"] == (
        "run_launch_terminal_use_new_trigger"
    )
    with Session(engine) as session:
        terminal_rejection = session.exec(
            select(AuditEvent)
            .where(
                AuditEvent.project_id == uuid.UUID(str(project["id"])),
                AuditEvent.action == "governance_run.new_trigger_rejected",
            )
            .order_by(col(AuditEvent.created_at).desc())
        ).first()
        assert terminal_rejection is not None
        assert terminal_rejection.target_type == "project"
        assert terminal_rejection.target_id == uuid.UUID(str(project["id"]))
        assert terminal_rejection.after_data == {
            "reason": "run_launch_terminal_use_new_trigger"
        }

    archive_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/archive",
        headers=superuser_token_headers,
    )
    assert archive_response.status_code == 200, archive_response.text
    with Session(engine) as session:
        stored_project = session.get(Project, uuid.UUID(str(project["id"])))
        assert stored_project is not None
        assert stored_project.governance_launch_trigger_id is None
        assert stored_project.archived_at is not None
        convergence = session.exec(
            select(AuditEvent).where(
                AuditEvent.project_id == stored_project.id,
                AuditEvent.action == "governance_run.launch_terminal_converged",
            )
        ).one()
        assert convergence.after_data == {
            "reason": "control_run_terminated_before_session"
        }


def test_trigger_requires_operator_or_global_admin_but_never_viewer_or_approver(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project = _create_project(client, superuser_token_headers)
    run_url = (
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs"
    )
    for role in ("viewer", "approver"):
        member_headers = _create_member(
            client,
            superuser_token_headers,
            project_id=project["id"],
            roles=[role],
        )
        trigger_response = client.post(
            run_url,
            headers={**member_headers, "Idempotency-Key": f"{role}-trigger"},
        )
        assert trigger_response.status_code == 404, trigger_response.text
        read_response = client.get(run_url, headers=member_headers)
        assert read_response.status_code == 200, read_response.text
        assert read_response.json()["can_trigger"] is False
        assert read_response.json()["data"] == []
        recovery_id = uuid.uuid4()
        retry_response = client.post(
            f"{run_url}/{recovery_id}/retry",
            headers=member_headers,
        )
        rerun_response = client.post(
            f"{run_url}/{recovery_id}/rerun",
            headers={**member_headers, "Idempotency-Key": f"{role}-rerun"},
        )
        assert retry_response.status_code == 404
        assert rerun_response.status_code == 404

    outside_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["operator"],
    )
    outside_project = _create_project(
        client, superuser_token_headers, name="Outside Governance Project"
    )
    outside_headers["Idempotency-Key"] = "cross-project-trigger"
    cross_response = client.post(
        f"{settings.API_V1_STR}/projects/{outside_project['id']}/governance-runs",
        headers=outside_headers,
    )
    assert cross_response.status_code == 404, cross_response.text


def test_trigger_rejects_each_missing_source_readiness_before_creating_a_run(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    run_url = f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs"
    trigger_headers = {**superuser_token_headers, "Idempotency-Key": "not-ready"}

    upload_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    )
    assert upload_response.status_code == 201
    upload = upload_response.json()
    client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads/{upload['id']}/select",
        headers=superuser_token_headers,
    )

    # Current upload exists but no enabled CloudAtlas source yet.
    not_ready = client.post(run_url, headers=trigger_headers)
    assert not_ready.status_code == 409
    assert not_ready.json()["detail"]["code"] == "run_cloudatlas_source_not_ready"

    source_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/cloudatlas-source-instances",
        headers=superuser_token_headers,
        json={"instance_id": "cloudatlas-fixture", "capset_id": "cloudatlas-readonly"},
    )
    source = source_response.json()

    # Source exists but not validated.
    not_ready = client.post(run_url, headers=trigger_headers)
    assert not_ready.status_code == 409
    assert not_ready.json()["detail"]["code"] == "run_cloudatlas_source_not_ready"

    # Source validated but not enabled.
    validation_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/cloudatlas-source-instances/{source['id']}/validate",
        headers=superuser_token_headers,
        json={"capset_token": "fixture-capset-token"},
    )
    assert validation_response.status_code == 200
    not_ready = client.post(run_url, headers=trigger_headers)
    assert not_ready.status_code == 409
    assert not_ready.json()["detail"]["code"] == "run_cloudatlas_source_not_ready"

    # Enabled but the deployment Run credential is missing.
    enable_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/cloudatlas-source-instances/{source['id']}/enable",
        headers=superuser_token_headers,
    )
    assert enable_response.status_code == 200
    monkeypatch.setattr(settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr(""))
    not_ready = client.post(run_url, headers=trigger_headers)
    assert not_ready.status_code == 409
    assert not_ready.json()["detail"]["code"] == "run_cloudatlas_credential_not_ready"

    with Session(engine) as session:
        assert (
            session.exec(
                select(func.count())
                .select_from(GovernanceRun)
                .where(GovernanceRun.project_id == uuid.UUID(str(project["id"])))
            ).one()
            == 0
        )
        rejection_events = session.exec(
            select(AuditEvent).where(
                AuditEvent.project_id == uuid.UUID(str(project["id"])),
                AuditEvent.action == "governance_run.trigger_rejected",
            )
        ).all()
        assert len(rejection_events) == 4
        assert {
            cast(dict[str, object], event.after_data)["reason"]
            for event in rejection_events
        } == {
            "run_cloudatlas_source_not_ready",
            "run_cloudatlas_credential_not_ready",
        }


def test_trigger_blocks_archived_project_without_creating_a_run(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    archive_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/archive",
        headers=superuser_token_headers,
    )
    assert archive_response.status_code == 200
    trigger_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers={**superuser_token_headers, "Idempotency-Key": "archived-project"},
    )
    assert trigger_response.status_code == 409
    assert "Archived project is read-only" in trigger_response.text
    with Session(engine) as session:
        assert (
            session.exec(
                select(func.count())
                .select_from(GovernanceRun)
                .where(GovernanceRun.project_id == uuid.UUID(str(project["id"])))
            ).one()
            == 0
        )


def test_active_run_blocks_project_archive_until_run_finishes(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    inputs = RunnerInputs.from_environment(
        _runner_environment(
            project=project,
            upload=upload,
            source=source,
            trigger_id="archive-active",
            session_seed="archive-active-session",
        )
    )
    with Session(engine) as session:
        run = establish_governance_run(session=session, inputs=inputs)
        assert run.status == GovernanceRunStatus.RUNNING.value

    trigger_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers={
            **superuser_token_headers,
            "Idempotency-Key": "active-run-trigger",
        },
    )
    assert trigger_response.status_code == 409
    assert trigger_response.json()["detail"] == {
        "code": "run_already_active",
        "message": "This Project already has an active GovernanceRun.",
    }
    with Session(engine) as session:
        rejection = session.exec(
            select(AuditEvent).where(
                AuditEvent.target_id == run.id,
                AuditEvent.action == "governance_run.new_trigger_rejected",
            )
        ).one()
        assert rejection.after_data == {"reason": "run_already_active"}

    archive_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/archive",
        headers=superuser_token_headers,
    )
    assert archive_response.status_code == 409
    assert archive_response.json()["detail"]["code"] == (
        "project_has_active_governance_run"
    )

    with Session(engine) as session:
        stored = session.get(GovernanceRun, run.id)
        assert stored is not None
        stored.status = GovernanceRunStatus.FAILED_DATA.value
        session.add(stored)
        session.commit()
    archive_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/archive",
        headers=superuser_token_headers,
    )
    assert archive_response.status_code == 200


def test_completed_is_immutable_and_not_retryable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    inputs = RunnerInputs.from_environment(
        _runner_environment(
            project=project,
            upload=upload,
            source=source,
            trigger_id="completed-with-warnings",
            session_seed="completed-with-warnings-session",
        )
    )
    with Session(engine) as session:
        run = establish_governance_run(session=session, inputs=inputs)
        run.status = GovernanceRunStatus.COMPLETED.value
        run.completed_at = run.updated_at
        run_id = run.id
        session.add(run)
        session.commit()

    response = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert response.json()["can_trigger"] is True
    assert response.json()["data"][0]["can_retry"] is False
    retry_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run_id}/retry",
        headers=superuser_token_headers,
    )
    assert retry_response.status_code == 409
    assert retry_response.json()["detail"]["code"] == "run_retry_completed"

    with Session(engine) as session:
        stored = session.get(GovernanceRun, run_id)
        assert stored is not None
        stored.status = GovernanceRunStatus.FAILED_PROCESSING.value
        session.add(stored)
        with pytest.raises(ProgrammingError):
            session.commit()
        session.rollback()


def test_referenced_customer_upload_and_artifact_cannot_be_deleted(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    inputs = RunnerInputs.from_environment(
        _runner_environment(
            project=project,
            upload=upload,
            source=source,
            trigger_id="delete-protection",
            session_seed="delete-protection-session",
        )
    )
    with Session(engine) as session:
        run = establish_governance_run(session=session, inputs=inputs)
        upload_id = uuid.UUID(str(upload["id"]))
        artifact_id = session.exec(
            select(CustomerUpload).where(CustomerUpload.id == upload_id)
        ).one().artifact_id
        with pytest.raises(IntegrityError):
            session.delete(session.get(CustomerUpload, upload_id))
            session.commit()
        session.rollback()
        with pytest.raises(IntegrityError):
            session.delete(session.get(Artifact, artifact_id))
            session.commit()
        session.rollback()
        assert session.get(CustomerUpload, upload_id) is not None
        assert session.get(Artifact, artifact_id) is not None
        assert session.get(GovernanceRun, run.id) is not None


def test_failed_run_history_stays_readable_and_snapshots_unrewritable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
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
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    runner_environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="failed-history",
        session_seed="failed-history-session",
    )
    for name, value in runner_environment.items():
        monkeypatch.setenv(name, value)
    assert run_governance_runner() == 0

    payload = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()
    run = payload["data"][0]
    assert run["status"] == "COMPLETED"
    with Session(engine) as session:
        snapshot = session.exec(
            select(SourceSnapshot).where(
                SourceSnapshot.governance_run_id
                == uuid.UUID(str(run["id"]))
            )
        ).first()
        assert snapshot is not None
        snapshot.record_count = 999
        session.add(snapshot)
        with pytest.raises(ProgrammingError):
            session.commit()
        session.rollback()


def test_publish_audit_insert_failure_rolls_back_completion(
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
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    runner_environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="audit-atomic",
        session_seed="audit-atomic-session",
    )
    for name, value in runner_environment.items():
        monkeypatch.setenv(name, value)

    # The publish transaction must roll back COMPLETED and the latest pointer
    # when its audit insert fails; the earlier steps remain committed.
    with reject_publish_audit_inserts(db):
        assert run_governance_runner() == 1

    payload = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()
    run = payload["data"][0]
    assert run["status"] == "FAILED_PROCESSING"
    assert not any(
        step["status"] == "SUCCEEDED" and step["step_code"] == "PUBLISH"
        for step in run["steps"]
    )
    with Session(engine) as session:
        stored_project = session.get(Project, uuid.UUID(str(project["id"])))
        assert stored_project is not None
        assert stored_project.latest_completed_run_id is None

    snapshot_ids = {snapshot["id"] for snapshot in run["snapshots"]}
    session_id = runner_environment["SANDBOX_ID"]
    monkeypatch.setattr(
        "app.api.routes.governance_runs.AgentComposeClient.get_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.TERMINAL,
        ),
    )
    monkeypatch.setattr(
        "app.api.routes.governance_runs.AgentComposeClient.resume_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.RUNNING,
        ),
    )
    monkeypatch.setattr(
        "app.api.routes.governance_runs.AgentComposeClient.start_governance_run",
        lambda _client, **_kwargs: AgentComposeRunStart(
            run_id="f" * 64,
            started=True,
            status="RUNNING",
            session_id=session_id,
        ),
    )
    retry_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs/{run['id']}/retry",
        headers=superuser_token_headers,
    )
    assert retry_response.status_code == 202
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("PUBLISH Retry must not re-read CloudAtlas")
        ),
    )
    assert run_governance_runner() == 0

    completed = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    assert completed["status"] == "COMPLETED"
    assert completed["session_id"] == session_id
    assert {snapshot["id"] for snapshot in completed["snapshots"]} == snapshot_ids
    assert {
        step["step_code"]: step["attempt"] for step in completed["steps"]
    } == {"LOAD_CUSTOMER": 1, "PULL_CLOUDATLAS": 1, "PUBLISH": 2}
    with Session(engine) as session:
        stored_project = session.get(Project, uuid.UUID(str(project["id"])))
        assert stored_project is not None
        assert str(stored_project.latest_completed_run_id) == completed["id"]


def test_two_projects_run_independently_in_parallel(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    _mock_cloudatlas(monkeypatch)
    project_a = _create_project(client, superuser_token_headers)
    project_b = _create_project(client, superuser_token_headers)
    upload_a, source_a = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project_a,
    )
    upload_b, source_b = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project_b,
    )
    inputs_a = RunnerInputs.from_environment(
        _runner_environment(
            project=project_a,
            upload=upload_a,
            source=source_a,
            trigger_id="parallel-a",
            session_seed="parallel-session-a",
        )
    )
    inputs_b = RunnerInputs.from_environment(
        _runner_environment(
            project=project_b,
            upload=upload_b,
            source=source_b,
            trigger_id="parallel-b",
            session_seed="parallel-session-b",
        )
    )

    def establish(inputs: RunnerInputs) -> str:
        with Session(engine) as session:
            run = establish_governance_run(session=session, inputs=inputs)
            return str(run.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(establish, (inputs_a, inputs_b)))
    assert results[0] != results[1]
    with Session(engine) as session:
        assert (
            session.exec(
                select(func.count())
                .select_from(GovernanceRun)
                .where(GovernanceRun.project_id == uuid.UUID(str(project_a["id"])))
            ).one()
            == 1
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(GovernanceRun)
                .where(GovernanceRun.project_id == uuid.UUID(str(project_b["id"])))
            ).one()
            == 1
        )


def test_runner_rejects_changed_pinned_inputs_without_a_completed_result(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
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
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    runner_environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="input-pinning",
        session_seed="input-pinning-session",
    )

    # The Runner must refuse to run when the pinned CloudAtlas fingerprint no
    # longer matches what OctoBus currently reports. Because the run is only
    # established after the Runner verifies the pinned inputs, no business Run
    # row may exist at all.
    runner_environment["GOVERNANCE_CLOUDATLAS_FINGERPRINT"] = "2" * 64
    for name, value in runner_environment.items():
        monkeypatch.setenv(name, value)
    assert run_governance_runner() == 1

    with Session(engine) as session:
        assert (
            session.exec(
                select(func.count())
                .select_from(GovernanceRun)
                .where(GovernanceRun.project_id == uuid.UUID(str(project["id"])))
            ).one()
            == 0
        )
        stored_project = session.get(Project, uuid.UUID(str(project["id"])))
        assert stored_project is not None
        assert stored_project.latest_completed_run_id is None


def test_runner_revalidates_retry_prepared_inputs_before_reentry(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="retry-revalidation",
        session_seed="retry-revalidation-session",
    )
    inputs = RunnerInputs.from_environment(environment)
    with Session(engine) as session:
        run = establish_governance_run(session=session, inputs=inputs)
        run.status = GovernanceRunStatus.RUNNING.value
        run.session_recovery_code = "retry_prepared"
        session.add(run)
        stored_project = session.get(Project, run.project_id)
        assert stored_project is not None
        stored_project.current_customer_upload_id = None
        session.add(stored_project)
        session.commit()
        run_id = run.id

    with Session(engine) as session:
        with pytest.raises(
            GovernanceRunExecutionError, match="runner_customer_input_changed"
        ):
            establish_governance_run(session=session, inputs=inputs)

    with Session(engine) as session:
        stored_run = session.get(GovernanceRun, run_id)
        assert stored_run is not None
        assert stored_run.status == GovernanceRunStatus.RUNNING.value
        assert stored_run.session_recovery_code == "retry_prepared"


def test_runner_requires_the_cloudatlas_run_credential_before_establishing(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    monkeypatch.setattr(settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr(""))
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="missing-run-credential",
        session_seed="missing-run-credential-session",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert run_governance_runner() == 1
    with Session(engine) as session:
        assert session.exec(
            select(func.count())
            .select_from(GovernanceRun)
            .where(GovernanceRun.project_id == uuid.UUID(str(project["id"])))
        ).one() == 0
