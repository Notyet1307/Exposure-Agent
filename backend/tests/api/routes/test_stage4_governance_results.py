import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlmodel import Session, func, select

from app.core.config import settings
from app.core.db import engine
from app.domain.cloudatlas_sources import OctobusCloudAtlasClient
from app.domain.models import (
    Finding,
    FindingOccurrence,
    FindingOccurrenceObservation,
    FindingOccurrenceSnapshot,
    FindingTransition,
    FindingTransitionObservation,
    FindingTransitionSnapshot,
    GovernanceRun,
    Observation,
    ObservationResourceLink,
    Resource,
    RunStep,
)
from app.governance_runner import main as run_governance_runner
from tests.api.routes.test_governance_runs import (
    _create_member,
    _create_project,
    _mock_cloudatlas,
    _prepare_ready_project,
    _runner_environment,
)


def test_stage4_run_publishes_ip_results_and_is_reentrant(
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
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _client, _source, *, capset_token, page, size: {
            "items": [
                {
                    "id": "fixture-cloud-only",
                    "ip": "203.0.113.5",
                    "status": "valid",
                }
            ],
            "page": page,
            "size": size,
            "total": 1,
        },
    )

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
        trigger_id="stage4-happy-path",
        session_seed="stage4-session",
    )
    environment["GOVERNANCE_PROCESSING_CONTRACT_VERSION"] = "ip-v1"
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert run_governance_runner() == 0
    assert run_governance_runner() == 0

    run_payload = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()
    run = run_payload["data"][0]
    assert run["processing_contract_version"] == "ip-v1"
    assert [step["step_code"] for step in run["steps"]] == [
        "LOAD_CUSTOMER",
        "PULL_CLOUDATLAS",
        "NORMALIZE",
        "RESOLVE",
        "CHECK_FINDINGS",
        "PUBLISH",
    ]
    assert all(step["status"] == "SUCCEEDED" for step in run["steps"])
    assert all(len(step["output_hash"] or "") == 64 for step in run["steps"])

    assets = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets",
        headers=superuser_token_headers,
    )
    assert assets.status_code == 200, assets.text
    assert assets.json()["compatible"] is True
    assert assets.json()["count"] == 2
    assert client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/assets",
        headers=superuser_token_headers,
    ).status_code == 404
    assert {
        (
            asset["canonical_ip"],
            asset["customer_observed"],
            asset["cloudatlas_observed"],
        )
        for asset in assets.json()["data"]
    } == {
        ("192.0.2.10", True, False),
        ("203.0.113.5", False, True),
    }
    asset_id = assets.json()["data"][0]["id"]
    asset_detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets/{asset_id}",
        headers=superuser_token_headers,
    )
    assert asset_detail.status_code == 200, asset_detail.text
    assert len(asset_detail.json()["observations"]) == 1

    findings = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/findings",
        headers=superuser_token_headers,
    )
    assert findings.status_code == 200, findings.text
    assert findings.json()["count"] == 2
    assert {item["finding_type"] for item in findings.json()["data"]} == {
        "UNREPORTED_ASSET",
        "UNOBSERVED_ASSET",
    }

    finding_id = findings.json()["data"][0]["id"]
    detail = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/findings/{finding_id}",
        headers=superuser_token_headers,
    )
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["occurrences"]) == 1
    assert len(detail.json()["transitions"]) == 1
    assert len(detail.json()["occurrences"][0]["source_snapshot_ids"]) == 2
    assert len(detail.json()["occurrences"][0]["source_snapshots"]) == 2
    assert len(detail.json()["transitions"][0]["source_snapshot_ids"]) == 2
    assert len(detail.json()["transitions"][0]["source_snapshots"]) == 2

    with Session(engine) as session:
        run_id = uuid.UUID(str(run["id"]))
        project_id = uuid.UUID(str(project["id"]))
        assert (
            session.exec(
                select(func.count())
                .select_from(GovernanceRun)
                .where(GovernanceRun.id == run_id)
            ).one()
            == 1
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(Observation)
                .where(Observation.governance_run_id == run_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(Resource)
                .where(Resource.project_id == project_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(ObservationResourceLink)
                .where(ObservationResourceLink.governance_run_id == run_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(Finding)
                .where(Finding.project_id == project_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(FindingOccurrence)
                .where(FindingOccurrence.governance_run_id == run_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(FindingTransition)
                .where(FindingTransition.governance_run_id == run_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(FindingOccurrenceObservation)
                .where(FindingOccurrenceObservation.governance_run_id == run_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(FindingOccurrenceSnapshot)
                .where(FindingOccurrenceSnapshot.governance_run_id == run_id)
            ).one()
            == 4
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(FindingTransitionObservation)
                .where(FindingTransitionObservation.governance_run_id == run_id)
            ).one()
            == 2
        )
        assert (
            session.exec(
                select(func.count())
                .select_from(FindingTransitionSnapshot)
                .where(FindingTransitionSnapshot.governance_run_id == run_id)
            ).one()
            == 4
        )
        assert session.exec(
            select(RunStep).where(RunStep.governance_run_id == run_id)
        ).all()
        assert (
            session.exec(
                select(GovernanceRun).where(
                    GovernanceRun.project_id == project_id,
                    GovernanceRun.trigger_id == "stage4-happy-path",
                )
            )
            .one()
            .processing_contract_version
            == "ip-v1"
        )


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {
            "items": [
                {"id": "fixture", "ip": "203.0.113.5", "status": "valid"}
            ],
            "page": 2,
            "size": 200,
            "total": 1,
        },
        {
            "items": [
                {"id": "fixture", "ip": "203.0.113.5", "status": "valid"}
            ],
            "page": 1,
            "size": 200,
            "total": 0,
        },
        {
            "items": [
                {"id": "fixture", "ip": "203.0.113.5", "status": "valid"}
            ],
            "page": 1,
            "total": 1,
        },
    ],
    ids=["page", "total", "envelope"],
)
def test_cloudatlas_pagination_contract_failure_does_not_create_snapshot(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    invalid_payload: dict[str, object],
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
        lambda *_args, **_kwargs: invalid_payload,
    )
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
        trigger_id="invalid-pagination-contract",
        session_seed=f"invalid-pagination-contract-{uuid.uuid4()}",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert run_governance_runner() == 1
    run = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    assert run["status"] == "FAILED_DATA"
    assert [step["step_code"] for step in run["steps"]] == [
        "LOAD_CUSTOMER",
        "PULL_CLOUDATLAS",
    ]
    assert [snapshot["source_type"] for snapshot in run["snapshots"]] == [
        "CUSTOMER_UPLOAD"
    ]
    cloudatlas_directory = tmp_path / "cloudatlas_snapshots"
    assert not cloudatlas_directory.exists() or not list(cloudatlas_directory.iterdir())



def test_complete_snapshot_record_error_is_non_retryable_without_partial_facts(
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
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda *_args, **_kwargs: {
            "items": [
                {"id": "fixture", "ip": "203.0.113.5", "status": "stale"}
            ],
            "page": 1,
            "size": 200,
            "total": 1,
        },
    )
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
        trigger_id="invalid-complete-record",
        session_seed="invalid-complete-record-session",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert run_governance_runner() == 1
    run = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    assert run["status"] == "FAILED_PROCESSING"
    assert run["session_recovery_code"].startswith("non_retryable:")
    assert [
        (step["step_code"], step["status"], step["error_code"])
        for step in run["steps"]
    ] == [
        ("LOAD_CUSTOMER", "SUCCEEDED", None),
        ("PULL_CLOUDATLAS", "SUCCEEDED", None),
        ("NORMALIZE", "FAILED", "normalize_contract_failed"),
    ]
    with Session(engine) as session:
        run_id = uuid.UUID(str(run["id"]))
        project_id = uuid.UUID(str(project["id"]))
        assert session.exec(
            select(func.count()).select_from(Observation).where(
                Observation.governance_run_id == run_id
            )
        ).one() == 0
        assert session.exec(
            select(func.count()).select_from(ObservationResourceLink).where(
                ObservationResourceLink.governance_run_id == run_id
            )
        ).one() == 0
        assert session.exec(
            select(func.count()).select_from(Resource).where(
                Resource.project_id == project_id
            )
        ).one() == 0
        assert session.exec(
            select(func.count()).select_from(Finding).where(
                Finding.project_id == project_id
            )
        ).one() == 0



def test_failed_run_preserves_previous_results_and_all_project_read_roles_can_trace(
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
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda *_args, **_kwargs: {
            "items": [
                {"id": "fixture", "ip": "203.0.113.5", "status": "valid"}
            ],
            "page": 1,
            "size": 200,
            "total": 1,
        },
    )
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client,
        headers=superuser_token_headers,
        project=project,
    )
    first_environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="published-before-failure",
        session_seed="published-before-failure-session",
    )
    for name, value in first_environment.items():
        monkeypatch.setenv(name, value)
    assert run_governance_runner() == 0
    first_run = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    previous_assets = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets",
        headers=superuser_token_headers,
    ).json()
    previous_findings = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/findings",
        headers=superuser_token_headers,
    ).json()
    finding_id = previous_findings["data"][0]["id"]

    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda *_args, **_kwargs: {
            "items": [
                {"id": "fixture", "ip": "203.0.113.5", "status": "stale"}
            ],
            "page": 1,
            "size": 200,
            "total": 1,
        },
    )
    second_environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="failed-after-publication",
        session_seed="failed-after-publication-session",
    )
    for name, value in second_environment.items():
        monkeypatch.setenv(name, value)
    assert run_governance_runner() == 1

    assets = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets",
        headers=superuser_token_headers,
    ).json()
    findings = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/findings",
        headers=superuser_token_headers,
    ).json()
    assert assets == previous_assets
    assert findings == previous_findings
    assert assets["latest_run_id"] == first_run["id"]
    assert findings["latest_run_id"] == first_run["id"]

    for role in ("viewer", "operator", "approver"):
        role_headers = _create_member(
            client,
            superuser_token_headers,
            project_id=project["id"],
            roles=[role],
        )
        role_assets = client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}/ip-assets",
            headers=role_headers,
        )
        role_findings = client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}/findings",
            headers=role_headers,
        )
        role_detail = client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}/findings/{finding_id}",
            headers=role_headers,
        )
        assert role_assets.status_code == 200
        assert role_findings.status_code == 200
        assert role_detail.status_code == 200
