import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlalchemy import event, update
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.domain.cloudatlas_sources import OctobusCloudAtlasClient
from app.domain.governance_runs import RunnerInputs
from app.domain.models import GovernanceReport, GovernanceRun
from app.governance_runner import main as run_governance_runner
from app.integrations.agent_compose import (
    AgentComposeClient,
    AgentComposeRunStart,
    AgentComposeSession,
    AgentComposeSessionObservation,
)
from tests.api.routes.test_governance_runs import (
    _create_member,
    _create_project,
    _mock_cloudatlas,
    _prepare_ready_project,
    _runner_environment,
    _trigger_stage5_run,
)


def _reports_url(project_id: object) -> str:
    return f"{settings.API_V1_STR}/projects/{project_id}/governance-reports"


def _configure_runner(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(
        settings, "CLOUDATLAS_CAPSET_TOKEN", SecretStr("fixture-capset-token")
    )
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "test-runner-v1")
    build_version_path = tmp_path / "runner-build-version"
    build_version_path.write_text("test-runner-v1\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build_version_path))
    _mock_cloudatlas(monkeypatch)


def _prepare_rerun(
    *,
    client: TestClient,
    headers: dict[str, str],
    monkeypatch: MonkeyPatch,
    project_id: object,
    run_id: object,
    trigger_id: str,
) -> dict[str, str]:
    captured_environment: dict[str, str] = {}

    def start(
        _client: object,
        *,
        client_request_id: str,
        environment: dict[str, str],
        session_id: str | None = None,
    ) -> AgentComposeRunStart:
        del client_request_id, session_id
        captured_environment.update(environment)
        return AgentComposeRunStart(
            run_id=hashlib.sha256(trigger_id.encode()).hexdigest(),
            started=True,
            status="RUN_STATUS_PENDING",
        )

    monkeypatch.setattr(AgentComposeClient, "start_governance_run", start)
    monkeypatch.setattr(
        AgentComposeClient,
        "get_session",
        lambda _client, requested_id: AgentComposeSession(
            session_id=requested_id,
            observation=AgentComposeSessionObservation.TERMINAL,
        ),
    )
    response = client.post(
        f"{settings.API_V1_STR}/projects/{project_id}/governance-runs/{run_id}/rerun",
        headers={**headers, "Idempotency-Key": trigger_id},
    )
    assert response.status_code == 202, response.text
    captured_environment["SANDBOX_ID"] = hashlib.sha256(
        f"{trigger_id}-session".encode()
    ).hexdigest()
    return captured_environment


def _start_rerun(
    *,
    client: TestClient,
    headers: dict[str, str],
    monkeypatch: MonkeyPatch,
    project_id: object,
    run_id: object,
    trigger_id: str,
) -> None:
    environment = _prepare_rerun(
        client=client,
        headers=headers,
        monkeypatch=monkeypatch,
        project_id=project_id,
        run_id=run_id,
        trigger_id=trigger_id,
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    assert run_governance_runner() == 0


def test_report_list_uses_bounded_stable_cursor_pagination(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _configure_runner(tmp_path, monkeypatch)
    project = _create_project(client, superuser_token_headers)
    _prepare_ready_project(
        client=client, headers=superuser_token_headers, project=project
    )
    tied_completion = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

    _trigger_stage5_run(
        client=client,
        headers=superuser_token_headers,
        monkeypatch=monkeypatch,
        project=project,
        trigger_id="report-page-1",
    )
    assert run_governance_runner() == 0
    latest_run_id = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]["id"]
    for index in (2, 3):
        _start_rerun(
            client=client,
            headers=superuser_token_headers,
            monkeypatch=monkeypatch,
            project_id=project["id"],
            run_id=latest_run_id,
            trigger_id=f"report-page-{index}",
        )
        latest_run_id = client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
            headers=superuser_token_headers,
        ).json()["data"][0]["id"]

    with Session(engine) as session:
        session.connection().exec_driver_sql(
            "SET LOCAL session_replication_role = replica"
        )
        session.exec(
            update(GovernanceRun)
            .where(col(GovernanceRun.project_id) == uuid.UUID(str(project["id"])))
            .values(completed_at=tied_completion)
        )
        session.commit()

    with Session(engine) as session:
        expected_ids = sorted(
            (
                report.id
                for report in session.exec(
                    select(GovernanceReport).where(
                        GovernanceReport.project_id == uuid.UUID(str(project["id"]))
                    )
                ).all()
            ),
            reverse=True,
        )

    first = client.get(
        _reports_url(project["id"]),
        headers=superuser_token_headers,
        params={"limit": 2},
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert first_payload["count"] == 3
    assert first_payload["page_size"] == 2
    assert [uuid.UUID(item["id"]) for item in first_payload["data"]] == expected_ids[:2]
    assert first_payload["next_cursor"] is not None
    assert first_payload["compatible"] is True
    assert first_payload["compatibility_code"] is None

    second = client.get(
        _reports_url(project["id"]),
        headers=superuser_token_headers,
        params={"limit": 2, "cursor": first_payload["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert [uuid.UUID(item["id"]) for item in second_payload["data"]] == expected_ids[
        2:
    ]
    assert second_payload["next_cursor"] is None
    assert set(first_payload["data"][0]) == {
        "id",
        "governance_run_id",
        "run_completed_at",
        "report_contract_version",
        "generation_mode",
        "html_sha256",
        "csv_sha256",
        "created_at",
    }

    oversized = client.get(
        _reports_url(project["id"]),
        headers=superuser_token_headers,
        params={"limit": 51},
    )
    assert oversized.status_code == 422
    invalid_cursor = client.get(
        _reports_url(project["id"]),
        headers=superuser_token_headers,
        params={"cursor": "not-a-report-cursor"},
    )
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json()["detail"]["code"] == "report_cursor_invalid"


def test_report_list_is_consistent_when_publication_commits_during_the_read(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _configure_runner(tmp_path, monkeypatch)
    project = _create_project(client, superuser_token_headers)
    _prepare_ready_project(
        client=client, headers=superuser_token_headers, project=project
    )
    _trigger_stage5_run(
        client=client,
        headers=superuser_token_headers,
        monkeypatch=monkeypatch,
        project=project,
        trigger_id="report-consistent-baseline",
    )
    assert run_governance_runner() == 0
    baseline = client.get(
        _reports_url(project["id"]), headers=superuser_token_headers
    ).json()
    baseline_report = baseline["data"][0]
    environment = _prepare_rerun(
        client=client,
        headers=superuser_token_headers,
        monkeypatch=monkeypatch,
        project_id=project["id"],
        run_id=baseline_report["governance_run_id"],
        trigger_id="report-published-during-list",
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    publication_results: list[int] = []
    publication_started = False

    def publish_after_report_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal publication_started
        if publication_started or "governance_reports" not in statement:
            return
        publication_started = True
        publication_results.append(run_governance_runner())

    event.listen(engine, "after_cursor_execute", publish_after_report_statement)
    try:
        response = client.get(
            _reports_url(project["id"]), headers=superuser_token_headers
        )
    finally:
        event.remove(engine, "after_cursor_execute", publish_after_report_statement)

    assert response.status_code == 200, response.text
    assert publication_results == [0]
    payload = response.json()
    assert payload["count"] == payload["page_size"] == len(payload["data"]) == 1
    assert payload["data"] == baseline["data"]
    assert payload["compatible"] is True
    assert payload["latest_completed_run_id"] == baseline_report["governance_run_id"]
    assert payload["latest_completed_run_at"] == baseline_report["run_completed_at"]

    after_publication = client.get(
        _reports_url(project["id"]), headers=superuser_token_headers
    )
    assert after_publication.status_code == 200, after_publication.text
    assert after_publication.json()["count"] == 2
    assert after_publication.json()["latest_completed_run_id"] != baseline_report[
        "governance_run_id"
    ]


def test_report_detail_is_project_scoped_bounded_and_readable_by_all_read_roles(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _configure_runner(tmp_path, monkeypatch)
    project = _create_project(client, superuser_token_headers)
    _prepare_ready_project(
        client=client, headers=superuser_token_headers, project=project
    )
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _client, _source, *, capset_token, page, size: {
            "items": [
                {"id": "fixture-other", "ip": "192.0.2.20", "status": "valid"}
            ],
            "page": page,
            "size": size,
            "total": 1,
        },
    )
    _trigger_stage5_run(
        client=client,
        headers=superuser_token_headers,
        monkeypatch=monkeypatch,
        project=project,
        trigger_id="report-read-detail",
    )
    assert run_governance_runner() == 0
    report = client.get(
        _reports_url(project["id"]), headers=superuser_token_headers
    ).json()["data"][0]
    detail_url = f"{_reports_url(project['id'])}/{report['id']}"
    role_headers = [
        _create_member(
            client,
            superuser_token_headers,
            project_id=project["id"],
            roles=[role],
        )
        for role in ("viewer", "operator", "approver")
    ]
    archive = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/archive",
        headers=superuser_token_headers,
    )
    assert archive.status_code == 200

    for headers in (*role_headers, superuser_token_headers):
        list_response = client.get(_reports_url(project["id"]), headers=headers)
        assert list_response.status_code == 200, list_response.text
        assert [item["id"] for item in list_response.json()["data"]] == [
            report["id"]
        ]
        response = client.get(detail_url, headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["id"] == report["id"]
        assert payload["report_contract_version"] == "deterministic-report-v1"
        assert payload["generation_mode"] == "DETERMINISTIC_TEMPLATE"
        assert (
            payload["canonical_content"]["report"]["report_identity"][
                "governance_run_id"
            ]
            == report["governance_run_id"]
        )
        assert payload["html_sha256"] == report["html_sha256"]
        assert payload["csv_sha256"] == report["csv_sha256"]
        assert payload["evidence_max_entries"] == 50
        assert payload["evidence_count"] == len(payload["evidence"]) == 2
        assert len(payload["evidence"]) <= 50
        assert all(
            set(reference) == {"id", "governance_run_id", "fact_type", "fact_id"}
            for reference in payload["evidence"]
        )
        assert not {
            "storage_key",
            "filesystem_path",
            "html_artifact_id",
            "csv_artifact_id",
            "source_snapshot",
            "observation",
        } & set(payload)

    other_project = _create_project(client, superuser_token_headers)
    cross_project = client.get(
        f"{_reports_url(other_project['id'])}/{report['id']}",
        headers=superuser_token_headers,
    )
    assert cross_project.status_code == 404


def test_stage4_only_project_requires_a_new_stage5_rerun(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _configure_runner(tmp_path, monkeypatch)
    project = _create_project(client, superuser_token_headers)
    upload, source = _prepare_ready_project(
        client=client, headers=superuser_token_headers, project=project
    )
    environment = _runner_environment(
        project=project,
        upload=upload,
        source=source,
        trigger_id="stage4-only-report-read",
        session_seed="stage4-only-report-read-session",
    )
    inputs = RunnerInputs.from_environment(environment)
    assert inputs.report_contract_version is None
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    assert run_governance_runner() == 0

    run_payload = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/governance-runs",
        headers=superuser_token_headers,
    ).json()["data"][0]
    response = client.get(_reports_url(project["id"]), headers=superuser_token_headers)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "data": [],
        "count": 0,
        "page_size": 0,
        "next_cursor": None,
        "compatible": False,
        "compatibility_code": "stage5_rerun_required",
        "latest_completed_run_id": run_payload["id"],
        "latest_completed_run_at": run_payload["completed_at"],
    }
