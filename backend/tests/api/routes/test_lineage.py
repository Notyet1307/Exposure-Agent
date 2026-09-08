import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import event
from sqlmodel import Session, col, delete, select, update

from app.core.db import engine
from app.domain.cloudatlas_sources import OctobusCloudAtlasClient
from app.domain.models import (
    FindingOccurrenceObservation,
    FindingOccurrenceSnapshot,
    GovernanceReport,
    GovernanceRun,
    SourceSnapshot,
)
from app.governance_runner import main as run_runner
from tests.api.routes import test_governance_runs as run_fixtures
from tests.api.routes.test_finding_netflow_context import (
    _cloud_ips,
    _damaged_publication,
    _workbook,
)
from tests.api.routes.test_governance_report_reads import (
    _configure_runner,
    _prepare_rerun,
    _start_rerun,
)
from tests.api.routes.test_governance_run_netflow import _prepare_present_run
from tests.api.routes.test_ip_source_comparison import HEADER
from tests.api.routes.test_ip_source_comparison import comparison_run as comparison_run


@pytest.mark.parametrize("comparison_run", ["absent"], indirect=True)
def test_published_lineage_preserves_absent_source_and_report_scope(
    comparison_run: GovernanceRun,
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    url = (
        f"/api/v1/projects/{comparison_run.project_id}/governance-runs/"
        f"{comparison_run.id}"
    )
    response = client.get(f"{url}/lineage", headers=superuser_token_headers)
    assert response.status_code == 200, response.text
    graph = response.json()
    sources = client.get(f"{url}/sources", headers=superuser_token_headers).json()
    comparisons = client.get(
        f"{url}/ip-source-comparisons", headers=superuser_token_headers
    ).json()
    assert graph["governance_report_id"] == sources["governance_report_id"]
    assert graph["totals"]["comparison_count"] == comparisons["count"]
    assert graph["comparison_output_hash"] == comparisons["output_hash"]
    netflow = next(
        node
        for node in graph["nodes"]
        if node["kind"] == "SOURCE" and node["source_type"] == "NETFLOW"
    )
    assert netflow["state"] == "ABSENT"
    assert netflow["input_id"] is None
    assert not any(
        node["kind"] == "SNAPSHOT" and node["source_type"] == "NETFLOW"
        for node in graph["nodes"]
    )
    assert response.headers["cache-control"] == "private, no-store"


def _publish(
    client: TestClient,
    headers: dict[str, str],
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    ips: list[str],
    *,
    netflow: bool = True,
) -> str:
    monkeypatch.setattr(run_fixtures, "_workbook_bytes", lambda: _workbook(ips))
    trigger_id = f"lineage-{uuid.uuid4()}"
    if netflow:
        project, _, _ = _prepare_present_run(
            client=client,
            headers=headers,
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            content=HEADER,
            trigger_id=trigger_id,
        )
    else:
        _configure_runner(tmp_path, monkeypatch)
        project = run_fixtures._create_project(client, headers)
        run_fixtures._prepare_ready_project(
            client=client, headers=headers, project=project
        )
        run_fixtures._trigger_stage5_run(
            client=client,
            headers=headers,
            monkeypatch=monkeypatch,
            project=project,
            trigger_id=trigger_id,
        )
    _cloud_ips(monkeypatch, [])
    assert run_runner() == 0
    listing = client.get(
        f"/api/v1/projects/{project['id']}/findings", headers=headers
    ).json()
    return (
        f"/api/v1/projects/{project['id']}/governance-runs/{listing['latest_run_id']}"
    )


def _graph(client: TestClient, headers: dict[str, str], url: str, **params: Any) -> Any:
    response = client.get(f"{url}/lineage", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("netflow", [False, True])
@pytest.mark.parametrize("size", [20, 21])
def test_overview_is_bounded_and_omitted_resource_remains_traceable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    size: int,
    netflow: bool,
) -> None:
    ips = [f"192.0.2.{i}" for i in range(1, size - 1)] + ["2001:db8::2", "2001:db8::10"]
    url = _publish(
        client,
        superuser_token_headers,
        monkeypatch,
        tmp_path,
        list(reversed(ips)) + ["::ffff:192.0.2.1"],
        netflow=netflow,
    )
    graph = _graph(client, superuser_token_headers, url)
    assert graph["totals"] == {"comparison_count": size, "finding_event_count": size}
    assert graph["coverage"] == {
        "comparison_count": size,
        "finding_event_count": size,
        "comparison_returned": 20,
        "finding_returned": 20,
    }
    comparisons = [node for node in graph["nodes"] if node["kind"] == "COMPARISON"]
    assert [node["canonical_ip"] for node in comparisons] == ips[:20]
    assert (len(graph["nodes"]), len(graph["edges"])) == (
        (48, 87) if netflow else (47, 86)
    )
    keys = {node["key"] for node in graph["nodes"]}
    assert len(keys) == (48 if netflow else 47)
    assert all(edge["from"] in keys and edge["to"] in keys for edge in graph["edges"])
    assert len({edge["key"] for edge in graph["edges"]}) == (87 if netflow else 86)
    assert not any(
        edge["from"].startswith("comparison/") and edge["to"].startswith("finding/")
        for edge in graph["edges"]
    )
    assert ("comparison_limit" in graph["truncation_reasons"]) == (size == 21)
    assert ("finding_limit" in graph["truncation_reasons"]) == (size == 21)
    matrix = client.get(
        f"{url}/ip-source-comparisons", headers=superuser_token_headers
    ).json()
    selected = matrix["data"][-1]
    detail = _graph(
        client, superuser_token_headers, url, resource_id=selected["resource_id"]
    )
    assert detail["view"] == "RESOURCE"
    assert detail["totals"] == graph["totals"]
    assert detail["coverage"] == {
        "comparison_count": 1,
        "finding_event_count": 1,
        "comparison_returned": 1,
        "finding_returned": 1,
    }
    selected_comparison = next(n for n in detail["nodes"] if n["kind"] == "COMPARISON")
    assert {key: selected_comparison[key] for key in selected} == selected
    assert (selected_comparison["comparison_fact_id"] is not None) == netflow
    finding = next(n for n in detail["nodes"] if n["kind"] == "FINDING")
    assert finding["resource_id"] == selected["resource_id"]
    assert finding["transition_type"] == "OPENED"
    report = next(n for n in graph["nodes"] if n["kind"] == "REPORT")
    assert report["evidence"]["count"] == (2 * size if netflow else size)
    assert len(report["evidence"]["data"]) == 20
    assert report["evidence"]["truncated"] == (netflow or size == 21)
    assert report["summary"] == {
        "customer_observed_asset_count": size,
        "cloudatlas_observed_asset_count": 0,
        "matched_asset_count": 0,
        "current_run_finding_count": size,
        "current_run_transition_count": size,
        "open_backlog_count": size,
    }


@pytest.mark.parametrize(
    "missing", ["observation_links", "one_snapshot_link", "occurrence"]
)
def test_v1_missing_finding_basis_fails_closed(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    missing: str,
) -> None:
    url = _publish(
        client,
        superuser_token_headers,
        monkeypatch,
        tmp_path,
        ["192.0.2.10"],
        netflow=False,
    )
    baseline = _graph(client, superuser_token_headers, url)
    run_id = uuid.UUID(baseline["governance_run_id"])
    with _damaged_publication() as session:
        if missing == "observation_links":
            session.exec(
                delete(FindingOccurrenceObservation).where(
                    col(FindingOccurrenceObservation.governance_run_id) == run_id
                )
            )
        elif missing == "one_snapshot_link":
            snapshot_id = session.exec(
                select(SourceSnapshot.id).where(
                    SourceSnapshot.governance_run_id == run_id,
                    SourceSnapshot.source_type == "CLOUDATLAS",
                )
            ).one()
            session.exec(
                delete(FindingOccurrenceSnapshot).where(
                    col(FindingOccurrenceSnapshot.governance_run_id) == run_id,
                    col(FindingOccurrenceSnapshot.source_snapshot_id) == snapshot_id,
                )
            )
        else:
            from app.domain.models import FindingOccurrence

            for model in (
                FindingOccurrenceObservation,
                FindingOccurrenceSnapshot,
                FindingOccurrence,
            ):
                session.exec(
                    delete(model).where(col(model.governance_run_id) == run_id)
                )
        response = client.get(f"{url}/lineage", headers=superuser_token_headers)
        assert response.status_code == 500
        assert response.json() == {"detail": "Run result integrity verification failed"}
    assert _graph(client, superuser_token_headers, url) == baseline


@pytest.mark.parametrize("size", [20, 21])
def test_observation_references_are_bounded_without_collapsing_duplicate_records(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    size: int,
) -> None:
    url = _publish(
        client, superuser_token_headers, monkeypatch, tmp_path, ["192.0.2.10"] * size
    )
    graph = _graph(client, superuser_token_headers, url)
    assert graph["totals"] == {"comparison_count": 1, "finding_event_count": 1}
    refs = [
        node["observations"]
        for node in graph["nodes"]
        if node["kind"] in ("COMPARISON", "FINDING")
    ]
    assert len(refs) == 2
    assert refs[0] == refs[1]
    assert refs[0]["count"] == size
    assert len(refs[0]["data"]) == 20
    assert len({r["observation_id"] for r in refs[0]["data"]}) == 20
    assert graph["status"] == ("COMPLETE" if size == 20 else "PARTIAL")
    assert graph["truncation_reasons"] == (
        [] if size == 20 else ["observation_reference_limit"]
    )


@pytest.mark.parametrize("comparison_run", ["active", "empty", "zero"], indirect=True)
def test_present_netflow_does_not_invent_zero_activity_or_findings(
    comparison_run: GovernanceRun,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    request: pytest.FixtureRequest,
) -> None:
    url = f"/api/v1/projects/{comparison_run.project_id}/governance-runs/{comparison_run.id}"
    graph = _graph(client, superuser_token_headers, url)
    source = next(
        n
        for n in graph["nodes"]
        if n["kind"] == "SOURCE" and n["source_type"] == "NETFLOW"
    )
    snapshot = next(
        n
        for n in graph["nodes"]
        if n["kind"] == "SNAPSHOT" and n["source_type"] == "NETFLOW"
    )
    mode = request.node.callspec.params["comparison_run"]
    assert source["state"] == "PRESENT" and source["input_id"] is not None
    assert snapshot["record_count"] == (0 if mode == "empty" else 1)
    comparison = next(n for n in graph["nodes"] if n["kind"] == "COMPARISON")
    assert comparison["netflow_status"] == ("ACTIVE" if mode == "active" else "UNKNOWN")
    assert comparison["netflow_reason"] == (
        "positive_activity_observed"
        if mode == "active"
        else "no_positive_activity_evidence"
    )
    assert graph["totals"]["finding_event_count"] == 0
    assert not any(n["kind"] == "FINDING" for n in graph["nodes"])
    assert graph["status"] == "COMPLETE"


@pytest.mark.parametrize("comparison_run", ["absent"], indirect=True)
def test_lineage_authorization_scope_and_archived_reads(
    comparison_run: GovernanceRun,
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    run = comparison_run
    url = f"/api/v1/projects/{run.project_id}/governance-runs/{run.id}"
    baseline = _graph(client, superuser_token_headers, url)
    resource_id = next(
        n["resource_id"] for n in baseline["nodes"] if n["kind"] == "COMPARISON"
    )
    members = [
        run_fixtures._create_member(
            client,
            superuser_token_headers,
            project_id=str(run.project_id),
            roles=[role],
        )
        for role in ("viewer", "operator", "approver")
    ]
    other = run_fixtures._create_project(client, superuser_token_headers)
    outsider = run_fixtures._create_member(
        client, superuser_token_headers, project_id=str(other["id"]), roles=["viewer"]
    )
    for headers in members:
        assert _graph(client, headers, url) == baseline
        assert (
            _graph(client, headers, url, resource_id=resource_id)["resource_id"]
            == resource_id
        )
    assert client.get(f"{url}/lineage", headers=outsider).status_code == 404
    assert (
        client.get(
            f"{url}/lineage", headers=outsider, params={"resource_id": resource_id}
        ).status_code
        == 404
    )
    assert client.get(f"{url}/lineage").status_code == 401
    assert (
        client.get(
            f"{url}/lineage",
            headers=superuser_token_headers,
            params={"resource_id": str(uuid.uuid4())},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"{url}/lineage",
            headers=superuser_token_headers,
            params={"resource_id": "bad-uuid"},
        ).status_code
        == 422
    )
    cross_url = url.replace(str(run.project_id), str(other["id"]))
    assert (
        client.get(f"{cross_url}/lineage", headers=superuser_token_headers).status_code
        == 404
    )
    archived = client.post(
        f"/api/v1/projects/{run.project_id}/archive", headers=superuser_token_headers
    )
    assert archived.status_code == 200, archived.text
    assert _graph(client, members[0], url) == baseline


@pytest.mark.parametrize("netflow", [False, True])
def test_later_finding_close_and_reopen_do_not_rewrite_history(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    netflow: bool,
) -> None:
    headers = superuser_token_headers
    url = _publish(
        client, headers, monkeypatch, tmp_path, ["192.0.2.10"], netflow=netflow
    )
    original = _graph(client, headers, url)
    initial_finding = next(n for n in original["nodes"] if n["kind"] == "FINDING")
    latest_id = original["governance_run_id"]
    project_id = original["project_id"]
    for clouds, transition in ((["192.0.2.10"], "CLOSED"), ([], "REOPENED")):
        _cloud_ips(monkeypatch, clouds)
        _start_rerun(
            client=client,
            headers=headers,
            monkeypatch=monkeypatch,
            project_id=project_id,
            run_id=latest_id,
            trigger_id=f"lineage-history-{uuid.uuid4()}",
        )
        latest_id = client.get(
            f"/api/v1/projects/{project_id}/findings", headers=headers
        ).json()["latest_run_id"]
        new_graph = _graph(
            client,
            headers,
            f"/api/v1/projects/{project_id}/governance-runs/{latest_id}",
        )
        finding = next(n for n in new_graph["nodes"] if n["kind"] == "FINDING")
        assert finding["finding_id"] == initial_finding["finding_id"]
        assert finding["transition_type"] == transition
        assert (finding["occurrence_id"] is None) == (transition == "CLOSED")
        assert "status" not in finding and "updated_at" not in finding
        assert _graph(client, headers, url) == original


@pytest.mark.parametrize(
    "damage",
    [
        "missing_summary",
        "string_count",
        "negative_count",
        "wrong_identity",
        "wrong_snapshot",
        "missing_provenance",
        "missing_evidence_limit",
        "invalid_directions",
        "wrong_provenance_snapshot",
    ],
)
@pytest.mark.parametrize("comparison_run", ["absent"], indirect=True)
def test_v1_wire_damage_is_not_defaulted_or_exposed(
    comparison_run: GovernanceRun,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    damage: str,
) -> None:
    run = comparison_run
    url = f"/api/v1/projects/{run.project_id}/governance-runs/{run.id}"
    with _damaged_publication() as session:
        report = session.exec(
            select(GovernanceReport).where(GovernanceReport.governance_run_id == run.id)
        ).one()
        content = deepcopy(report.canonical_content)
        wire = content["report"]
        if damage == "missing_summary":
            del wire["ip_consistency_summary"]["matched_asset_count"]
        elif damage == "string_count":
            wire["ip_consistency_summary"]["matched_asset_count"] = "1"
        elif damage == "negative_count":
            wire["ip_consistency_summary"]["matched_asset_count"] = -1
        elif damage == "wrong_identity":
            wire["report_identity"]["project_id"] = str(uuid.uuid4())
        elif damage == "missing_provenance":
            del wire["provenance"]
        elif damage == "missing_evidence_limit":
            del wire["bounded_evidence_examples"]["max_selected_entries"]
        elif damage == "invalid_directions":
            wire["finding_type_directions_and_limitations"]["directions"] = "invalid"
        elif damage == "wrong_provenance_snapshot":
            wire["provenance"]["source_snapshot_ids"][0] = str(uuid.uuid4())
        else:
            wire["input_completeness"]["sources"][0]["source_snapshot_id"] = str(
                uuid.uuid4()
            )
        session.exec(
            update(GovernanceReport)
            .where(col(GovernanceReport.id) == report.id)
            .values(canonical_content=content)
        )
        response = client.get(f"{url}/lineage", headers=superuser_token_headers)
        assert response.status_code == 500
        assert response.json() == {"detail": "Run result integrity verification failed"}


@pytest.mark.parametrize("comparison_run", ["absent"], indirect=True)
def test_publish_during_read_does_not_enter_an_older_snapshot(
    comparison_run: GovernanceRun,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    run = comparison_run
    trigger_id = f"lineage-concurrent-{uuid.uuid4()}"
    environment = _prepare_rerun(
        client=client,
        headers=superuser_token_headers,
        monkeypatch=monkeypatch,
        project_id=run.project_id,
        run_id=run.id,
        trigger_id=trigger_id,
    )
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    loading, release = Event(), Event()
    original_read = OctobusCloudAtlasClient.list_ip_assets_page

    def paused_read(*args: Any, **kwargs: Any) -> Any:
        loading.set()
        assert release.wait(20)
        return original_read(*args, **kwargs)

    monkeypatch.setattr(OctobusCloudAtlasClient, "list_ip_assets_page", paused_read)
    with ThreadPoolExecutor(max_workers=1) as workers:
        publication = workers.submit(run_runner)
        try:
            assert loading.wait(20)
            with Session(engine) as session:
                pending_id = session.exec(
                    select(GovernanceRun.id).where(
                        GovernanceRun.project_id == run.project_id,
                        GovernanceRun.status == "RUNNING",
                    )
                ).one()
            url = f"/api/v1/projects/{run.project_id}/governance-runs/{pending_id}"
            published: list[int] = []
            started = False

            def publish_after_authorization(
                _conn: Any,
                _cursor: Any,
                statement: str,
                _params: Any,
                _context: Any,
                _many: Any,
            ) -> None:
                nonlocal started
                if not started and "FROM projects" in statement:
                    started = True
                    release.set()
                    published.append(publication.result(timeout=20))

            event.listen(engine, "after_cursor_execute", publish_after_authorization)
            try:
                response = client.get(f"{url}/lineage", headers=superuser_token_headers)
            finally:
                event.remove(
                    engine, "after_cursor_execute", publish_after_authorization
                )
            assert published == [0]
            assert response.status_code == 404
            assert _graph(client, superuser_token_headers, url)[
                "governance_run_id"
            ] == str(pending_id)
        finally:
            release.set()
            publication.result(timeout=20)


@pytest.mark.parametrize("comparison_run", ["active"], indirect=True)
def test_lineage_reads_are_database_only_and_read_only(
    comparison_run: GovernanceRun,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    run = comparison_run
    url = f"/api/v1/projects/{run.project_id}/governance-runs/{run.id}"
    baseline = _graph(client, superuser_token_headers, url)
    checked: list[tuple[str, str]] = []
    checking = False

    def observe_transaction(
        conn: Any, _cursor: Any, statement: str, _params: Any, _context: Any, _many: Any
    ) -> None:
        nonlocal checking
        assert statement.lstrip().upper().startswith(("SELECT", "SHOW"))
        if not checking:
            checking = True
            checked.append(
                (
                    conn.exec_driver_sql("SHOW transaction_read_only").scalar_one(),
                    conn.exec_driver_sql("SHOW transaction_isolation").scalar_one(),
                )
            )

    def forbidden_io(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Lineage cannot read artifacts or call external systems")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", forbidden_io)
        patch.setattr(OctobusCloudAtlasClient, "list_ip_assets_page", forbidden_io)
        event.listen(engine, "before_cursor_execute", observe_transaction)
        try:
            assert _graph(client, superuser_token_headers, url) == baseline
        finally:
            event.remove(engine, "before_cursor_execute", observe_transaction)
    assert checked == [("on", "repeatable read")]


@pytest.mark.parametrize("damage", ["omitted_finding_link", "omitted_evidence_target"])
def test_truncation_cannot_hide_corrupt_unreturned_facts(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    damage: str,
) -> None:
    from app.domain.models import Evidence, Finding, FindingOccurrence

    url = _publish(
        client,
        superuser_token_headers,
        monkeypatch,
        tmp_path,
        [f"192.0.2.{i}" for i in range(1, 22)],
        netflow=False,
    )
    baseline = _graph(client, superuser_token_headers, url)
    matrix = client.get(
        f"{url}/ip-source-comparisons", headers=superuser_token_headers
    ).json()
    selected = matrix["data"][0]["resource_id"]
    omitted = uuid.UUID(matrix["data"][-1]["resource_id"])
    with _damaged_publication() as session:
        if damage == "omitted_finding_link":
            occurrence_id = session.exec(
                select(FindingOccurrence.id)
                .join(Finding)
                .where(
                    FindingOccurrence.governance_run_id
                    == uuid.UUID(baseline["governance_run_id"]),
                    Finding.resource_id == omitted,
                )
            ).one()
            session.exec(
                update(FindingOccurrenceObservation)
                .where(
                    col(FindingOccurrenceObservation.finding_occurrence_id)
                    == occurrence_id
                )
                .values(observation_id=uuid.uuid4())
            )
        else:
            last_evidence = session.exec(
                select(Evidence)
                .where(
                    Evidence.governance_report_id
                    == uuid.UUID(baseline["governance_report_id"])
                )
                .order_by(col(Evidence.id).desc())
            ).first()
            assert last_evidence is not None
            returned_report = next(
                n for n in baseline["nodes"] if n["kind"] == "REPORT"
            )
            assert str(last_evidence.id) not in {
                e["id"] for e in returned_report["evidence"]["data"]
            }
            session.exec(
                update(Evidence)
                .where(col(Evidence.id) == last_evidence.id)
                .values(finding_transition_id=uuid.uuid4())
            )
        response = client.get(
            f"{url}/lineage",
            headers=superuser_token_headers,
            params={"resource_id": selected},
        )
        assert response.status_code == 500
        assert response.json() == {"detail": "Run result integrity verification failed"}


@pytest.mark.parametrize("comparison_run", ["absent"], indirect=True)
def test_empty_published_read_contract_retains_source_and_report_context(
    comparison_run: GovernanceRun,
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    from app.domain.models import Observation, ObservationResourceLink, RunStep
    from tests.api.routes.test_ip_source_comparison import _hash

    run = comparison_run
    # Exercise the persisted read-contract boundary directly: current uploads require a row.
    with _damaged_publication() as session:
        for model in (ObservationResourceLink, Observation):
            session.exec(delete(model).where(col(model.governance_run_id) == run.id))
        session.exec(
            update(SourceSnapshot)
            .where(col(SourceSnapshot.governance_run_id) == run.id)
            .values(record_count=0)
        )
        session.exec(
            update(RunStep)
            .where(
                col(RunStep.governance_run_id) == run.id,
                col(RunStep.step_code) == "NORMALIZE",
            )
            .values(
                output_hash=_hash(
                    {"processing_contract_version": "ip-v1", "observations": []}
                )
            )
        )
        report = session.exec(
            select(GovernanceReport).where(GovernanceReport.governance_run_id == run.id)
        ).one()
        content = deepcopy(report.canonical_content)
        for source in content["report"]["input_completeness"]["sources"]:
            source["record_count"] = 0
        for key in (
            "customer_observed_asset_count",
            "cloudatlas_observed_asset_count",
            "matched_asset_count",
        ):
            content["report"]["ip_consistency_summary"][key] = 0
        session.exec(
            update(GovernanceReport)
            .where(col(GovernanceReport.id) == report.id)
            .values(canonical_content=content)
        )
        graph = _graph(
            client,
            superuser_token_headers,
            f"/api/v1/projects/{run.project_id}/governance-runs/{run.id}",
        )
        assert graph["status"] == "EMPTY"
        assert graph["truncated"] is False and graph["truncation_reasons"] == []
        assert graph["totals"] == {"comparison_count": 0, "finding_event_count": 0}
        assert [n["kind"] for n in graph["nodes"]] == [
            "SOURCE",
            "SOURCE",
            "SOURCE",
            "SNAPSHOT",
            "SNAPSHOT",
            "PROCESS",
            "REPORT",
        ]
        report_node = graph["nodes"][-1]
        assert report_node["evidence"] == {"count": 0, "data": [], "truncated": False}


def test_openapi_requires_lineage_discriminators(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    schemas = response.json()["components"]["schemas"]
    graph = schemas["GovernanceRunLineagePublic"]
    assert "projection_version" in graph["required"]
    discriminator = graph["properties"]["nodes"]["items"]["discriminator"]
    assert discriminator["propertyName"] == "kind"
    for reference in discriminator["mapping"].values():
        node = schemas[reference.rsplit("/", 1)[-1]]
        assert "kind" in node["required"]
