import hashlib
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.domain.models import Artifact, AuditEvent, GovernanceReport
from app.governance_runner import main as run_governance_runner
from tests.api.routes.test_governance_runs import (
    _create_member,
    _create_project,
    _mock_cloudatlas,
    _prepare_ready_project,
    _trigger_stage5_run,
)
from tests.utils.audit import reject_audit_inserts


def _publish_report(
    *,
    client: TestClient,
    admin_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> tuple[dict[str, object], GovernanceReport, Artifact, bytes]:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)
    project = _create_project(client, admin_headers)
    _prepare_ready_project(client=client, headers=admin_headers, project=project)
    _trigger_stage5_run(
        client=client,
        headers=admin_headers,
        monkeypatch=monkeypatch,
        project=project,
        trigger_id=f"report-download-{uuid.uuid4()}",
    )
    assert run_governance_runner() == 0

    with Session(engine) as session:
        report = session.exec(
            select(GovernanceReport).where(
                GovernanceReport.project_id == uuid.UUID(str(project["id"]))
            )
        ).one()
        artifact = session.exec(
            select(Artifact).where(Artifact.id == report.csv_artifact_id)
        ).one()
        session.expunge(report)
        session.expunge(artifact)
    csv_bytes = (tmp_path / artifact.storage_key).read_bytes()
    return project, report, artifact, csv_bytes


def _download_url(*, project_id: object, report_id: uuid.UUID) -> str:
    return (
        f"{settings.API_V1_STR}/projects/{project_id}/"
        f"governance-reports/{report_id}/csv"
    )


def test_report_csv_download_is_operator_admin_only_and_preserved_when_archived(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, report, artifact, csv_bytes = _publish_report(
        client=client,
        admin_headers=superuser_token_headers,
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
    approver_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["approver"],
    )
    archive = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/archive",
        headers=superuser_token_headers,
    )
    assert archive.status_code == 200

    url = _download_url(project_id=project["id"], report_id=report.id)
    viewer_response = client.get(url, headers=viewer_headers)
    approver_response = client.get(url, headers=approver_headers)
    operator_response = client.get(url, headers=operator_headers)
    admin_response = client.get(url, headers=superuser_token_headers)

    assert viewer_response.status_code == 404
    assert approver_response.status_code == 404
    expected_filename = (
        f'attachment; filename="governance-report-{report.id}-'
        f'run-{report.governance_run_id}.csv"'
    )
    for response in (operator_response, admin_response):
        assert response.status_code == 200
        assert response.content == csv_bytes
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert response.headers["content-disposition"] == expected_filename
        assert response.headers["content-length"] == str(len(csv_bytes))

    actor_ids = {
        client.get(
            f"{settings.API_V1_STR}/users/me", headers=headers
        ).json()["id"]
        for headers in (operator_headers, superuser_token_headers)
    }
    with Session(engine) as session:
        events = session.exec(
            select(AuditEvent).where(
                AuditEvent.project_id == uuid.UUID(str(project["id"])),
                AuditEvent.action == "governance_report.csv_download_started",
            )
        ).all()
    assert len(events) == 2
    assert {event.actor_subject for event in events} == actor_ids
    for event in events:
        assert event.actor_type == "user"
        assert event.target_type == "governance_report"
        assert event.target_id == report.id
        assert event.before_data is None
        assert event.after_data == {"artifact_sha256": artifact.sha256}
        assert event.ip_address is None
        assert event.occurred_at is not None


def test_report_csv_download_preflights_artifact_and_hash_before_audit(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, report, artifact, csv_bytes = _publish_report(
        client=client,
        admin_headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    url = _download_url(project_id=project["id"], report_id=report.id)
    artifact_path = tmp_path / artifact.storage_key
    artifact_path.chmod(0o640)
    tampered = b"X" + csv_bytes[1:]
    assert len(tampered) == len(csv_bytes)
    artifact_path.write_bytes(tampered)

    hash_response = client.get(url, headers=superuser_token_headers)

    assert hash_response.status_code == 500
    assert csv_bytes not in hash_response.content
    artifact_path.unlink()
    missing_response = client.get(url, headers=superuser_token_headers)
    assert missing_response.status_code == 500
    assert csv_bytes not in missing_response.content
    with Session(engine) as session:
        assert session.exec(
            select(AuditEvent).where(
                AuditEvent.project_id == uuid.UUID(str(project["id"])),
                AuditEvent.action == "governance_report.csv_download_started",
            )
        ).all() == []


def test_report_csv_download_commits_audit_before_streaming(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, report, _artifact, csv_bytes = _publish_report(
        client=client,
        admin_headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    url = _download_url(project_id=project["id"], report_id=report.id)
    with Session(engine) as session, reject_audit_inserts(session):
        failed_response = client.get(url, headers=superuser_token_headers)

    assert failed_response.status_code == 500
    assert csv_bytes not in failed_response.content
    with Session(engine) as session:
        assert session.exec(
            select(AuditEvent).where(
                AuditEvent.project_id == uuid.UUID(str(project["id"])),
                AuditEvent.action == "governance_report.csv_download_started",
            )
        ).all() == []

    successful_response = client.get(url, headers=superuser_token_headers)
    assert successful_response.status_code == 200
    assert successful_response.content == csv_bytes
    assert hashlib.sha256(successful_response.content).hexdigest() == report.csv_sha256

    with Session(engine) as session:
        events = session.exec(
            select(AuditEvent).where(
                AuditEvent.project_id == uuid.UUID(str(project["id"])),
                AuditEvent.action == "governance_report.csv_download_started",
            )
        ).all()
    assert len(events) == 1
