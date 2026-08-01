import hashlib
import io
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient
from openpyxl import Workbook  # type: ignore[import-untyped]
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlmodel import Session, func, select

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
    AuditEvent,
    GovernanceRun,
    GovernanceRunStatus,
    Project,
)
from app.governance_runner import main as run_governance_runner

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


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(REQUIRED_HEADERS)
    worksheet.append(["192.0.2.10", 443, 443, "是", "example.test"])
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
