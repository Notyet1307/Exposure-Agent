import hashlib
import io
import json
import uuid
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook  # type: ignore[import-untyped]
from pytest import MonkeyPatch
from sqlalchemy import event
from sqlmodel import Session, col, delete, select, update

from app.api.deps import get_db
from app.core.db import engine
from app.domain.cloudatlas_sources import OctobusCloudAtlasClient
from app.domain.governance_runs import pinned_inputs_for_run
from app.domain.ip_source_comparison import (
    IPSourceComparisonError,
    read_ip_source_comparison,
)
from app.domain.models import (
    AuditEvent,
    Finding,
    GovernanceReport,
    GovernanceRun,
    NetFlowIPActivity,
    Observation,
    ObservationResourceLink,
    Project,
    Resource,
    RunStep,
    SourceSnapshot,
)
from app.governance_runner import main as run_runner
from app.main import app
from tests.api.routes import test_governance_runs as run_fixtures
from tests.api.routes.test_governance_report_reads import (
    _configure_runner,
    _start_rerun,
)
from tests.api.routes.test_governance_run_netflow import _prepare_present_run

HEADER = b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _read(session: Session, run: GovernanceRun) -> Any:
    return read_ip_source_comparison(
        session=session,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        run_id=run.id,
    )


@pytest.fixture
def comparison_run(
    request: pytest.FixtureRequest,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
) -> GovernanceRun:
    mode = getattr(request, "param", "active")
    trigger_id = f"comparison-{uuid.uuid4()}"
    if mode == "absent":
        _configure_runner(tmp_path, monkeypatch)
        project = run_fixtures._create_project(client, superuser_token_headers)
        run_fixtures._prepare_ready_project(
            client=client, headers=superuser_token_headers, project=project
        )
        run_fixtures._trigger_stage5_run(
            client=client,
            headers=superuser_token_headers,
            monkeypatch=monkeypatch,
            project=project,
            trigger_id=trigger_id,
        )
    else:
        content = (
            HEADER
            if mode == "empty"
            else HEADER
            + (
                b"invalid,192.0.2.10,6,443,53000\n"
                if mode == "zero"
                else b"192.0.2.10,198.51.100.20,6,443,53000\n"
            )
        )
        project, _, _ = _prepare_present_run(
            client=client,
            headers=superuser_token_headers,
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            content=content,
            trigger_id=trigger_id,
        )
    assert run_runner() == 0
    return db.exec(
        select(GovernanceRun).where(
            col(GovernanceRun.project_id) == uuid.UUID(str(project["id"]))
        )
    ).one()


def test_all_combinations_are_scoped_ordered_read_only_and_historically_stable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
) -> None:
    def workbook() -> bytes:
        book = Workbook()
        sheet = book.active
        assert sheet is not None
        sheet.append(run_fixtures.REQUIRED_HEADERS)
        for ip in (
            "192.0.2.11",
            "::ffff:192.0.2.2",
            "192.0.2.10",
            "192.0.2.3",
            "192.0.2.2",
        ):
            sheet.append([ip, 443, 443, "是", "example.test"])
        output = io.BytesIO()
        book.save(output)
        book.close()
        return output.getvalue()

    monkeypatch.setattr(run_fixtures, "_workbook_bytes", workbook)
    project, _, _ = _prepare_present_run(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        content=HEADER
        + b"2001:db8::10,192.0.2.99,6,443,53000\n2001:db8::2,192.0.2.99,17,53,53000\n192.0.2.4,192.0.2.99,6,443,53000\n192.0.2.3,192.0.2.2,6,443,53000\n",
        trigger_id="comparison-seven",
    )
    cloud_ips = ("192.0.2.12", "192.0.2.2", "192.0.2.10", "192.0.2.4", "192.0.2.2")
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _client, _source, *, capset_token, page, size: {
            "items": [
                {"id": f"asset-{index}", "ip": ip, "status": "valid"}
                for index, ip in enumerate(cloud_ips)
            ],
            "page": page,
            "size": size,
            "total": len(cloud_ips),
        },
    )
    project_id = uuid.UUID(str(project["id"]))
    stored_project = db.get(Project, project_id)
    assert stored_project is not None
    for ip in ("2001:db8::2", "2001:db8::10", "2001:db8::1"):
        db.add(
            Resource(
                tenant_id=stored_project.tenant_id,
                project_id=project_id,
                resource_type="IP",
                canonical_key=ip,
            )
        )
    other = run_fixtures._create_project(client, superuser_token_headers)
    db.add(
        Resource(
            tenant_id=stored_project.tenant_id,
            project_id=uuid.UUID(str(other["id"])),
            resource_type="IP",
            canonical_key="192.0.2.99",
        )
    )
    db.commit()
    assert run_runner() == 0
    run = db.exec(
        select(GovernanceRun).where(col(GovernanceRun.project_id) == project_id)
    ).one()
    result = _read(db, run)
    assert [
        (item.canonical_ip, item.classification, item.netflow_status)
        for item in result.results
    ] == [
        ("192.0.2.2", "matched", "ACTIVE"),
        ("192.0.2.3", "customer_upload_only", "ACTIVE"),
        ("192.0.2.4", "cloudatlas_only", "ACTIVE"),
        ("192.0.2.10", "matched", "UNKNOWN"),
        ("192.0.2.11", "customer_upload_only", "UNKNOWN"),
        ("192.0.2.12", "cloudatlas_only", "UNKNOWN"),
        ("2001:db8::2", "neither_source_observed", "ACTIVE"),
        ("2001:db8::10", "neither_source_observed", "ACTIVE"),
    ]
    reasons = {
        "matched": "observed_in_both_sources",
        "customer_upload_only": "observed_in_customer_upload_only",
        "cloudatlas_only": "observed_in_cloudatlas_only",
        "neither_source_observed": "not_observed_in_either_source",
    }
    scope = result.model_dump(mode="json", exclude={"results", "output_hash"})
    for item in result.results:
        assert item.classification_reason == reasons[item.classification]
        assert item.netflow_reason == (
            "positive_activity_observed"
            if item.netflow_status == "ACTIVE"
            else "no_positive_activity_evidence"
        )
        assert item.content_hash == _hash(
            {**scope, **item.model_dump(mode="json", exclude={"content_hash"})}
        )
    assert result.output_hash == _hash(
        result.model_dump(mode="json", exclude={"output_hash"})
    )
    run_result_url = (
        f"/api/v1/projects/{project_id}/governance-runs/{run.id}"
    )
    baseline_comparison_response = client.get(
        f"{run_result_url}/ip-source-comparisons", headers=superuser_token_headers
    )
    baseline_sources_response = client.get(
        f"{run_result_url}/sources", headers=superuser_token_headers
    )
    assert baseline_comparison_response.status_code == 200
    assert baseline_sources_response.status_code == 200
    baseline_comparison_api = baseline_comparison_response.json()
    baseline_sources_api = baseline_sources_response.json()
    findings = db.exec(select(Finding).where(Finding.project_id == project_id)).all()
    assert len(findings) == 4
    baseline = result.model_dump(mode="json")
    for finding in findings:
        finding.status = "CLOSED"
        db.add(finding)
    stored_project.current_netflow_dataset_id = None
    db.add(stored_project)
    db.add(
        Resource(
            tenant_id=run.tenant_id,
            project_id=project_id,
            resource_type="IP",
            canonical_key="192.0.2.1",
        )
    )
    db.commit()

    queries: list[str] = []

    def trace(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _params: Any,
        _context: Any,
        _many: Any,
    ) -> None:
        queries.append(statement)

    def no_files(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("comparison must not open artifacts")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", no_files)
        event.listen(engine, "before_cursor_execute", trace)
        try:
            with Session(engine) as session:
                assert _read(session, run).model_dump(mode="json") == baseline
        finally:
            event.remove(engine, "before_cursor_execute", trace)
    assert queries and all(
        query.lstrip().upper().startswith("SELECT") for query in queries
    )
    assert not any("FROM findings" in query for query in queries)
    queries.clear()
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", no_files)
        event.listen(engine, "before_cursor_execute", trace)
        try:
            comparison_response = client.get(
                f"{run_result_url}/ip-source-comparisons",
                headers=superuser_token_headers,
            )
            sources_response = client.get(
                f"{run_result_url}/sources", headers=superuser_token_headers
            )
        finally:
            event.remove(engine, "before_cursor_execute", trace)
    assert comparison_response.status_code == sources_response.status_code == 200
    assert comparison_response.json() == baseline_comparison_api
    assert sources_response.json() == baseline_sources_api
    assert queries and all(
        query.lstrip().upper().startswith("SELECT") for query in queries
    )
    assert run_runner() == 0
    assert _read(db, run).model_dump(mode="json") == baseline


@pytest.mark.parametrize(
    "comparison_run", ["absent", "empty", "zero", "active"], indirect=True
)
def test_supported_input_states_and_rerun_identity(
    comparison_run: GovernanceRun,
    db: Session,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    run = comparison_run
    before = _read(db, run)
    assert len(before.results) == 1
    activity = db.exec(
        select(NetFlowIPActivity).where(
            col(NetFlowIPActivity.governance_run_id) == run.id
        )
    ).first()
    expected = (
        "positive_activity_observed"
        if activity
        else (
            "netflow_input_absent"
            if run.netflow_dataset_id is None
            else "no_positive_activity_evidence"
        )
    )
    assert before.results[0].netflow_reason == expected
    run_result_url = f"/api/v1/projects/{run.project_id}/governance-runs/{run.id}"
    comparison_response = client.get(
        f"{run_result_url}/ip-source-comparisons",
        headers=superuser_token_headers,
    )
    sources_response = client.get(
        f"{run_result_url}/sources", headers=superuser_token_headers
    )
    assert comparison_response.status_code == sources_response.status_code == 200
    assert comparison_response.json()["output_hash"] == before.output_hash
    netflow = sources_response.json()["sources"][2]
    snapshot = db.exec(
        select(SourceSnapshot).where(
            SourceSnapshot.governance_run_id == run.id,
            SourceSnapshot.source_type == "NETFLOW",
        )
    ).one_or_none()
    assert netflow["state"] == ("ABSENT" if snapshot is None else "PRESENT")
    assert netflow["record_count"] == (None if snapshot is None else snapshot.record_count)
    original_comparison_response = comparison_response.json()
    original_sources_response = sources_response.json()
    _start_rerun(
        client=client,
        headers=superuser_token_headers,
        monkeypatch=monkeypatch,
        project_id=str(run.project_id),
        run_id=str(run.id),
        trigger_id=f"comparison-rerun-{run.id}",
    )
    latest = db.exec(
        select(GovernanceRun).where(
            col(GovernanceRun.project_id) == run.project_id, GovernanceRun.id != run.id
        )
    ).one()
    after = _read(db, latest)
    assert before.output_hash != after.output_hash
    assert before.results[0].content_hash != after.results[0].content_hash
    assert before.results[0].model_dump(exclude={"content_hash"}) == after.results[
        0
    ].model_dump(exclude={"content_hash"})
    assert _read(db, run) == before
    assert (
        client.get(
            f"{run_result_url}/ip-source-comparisons",
            headers=superuser_token_headers,
        ).json()
        == original_comparison_response
    )
    assert (
        client.get(
            f"{run_result_url}/sources", headers=superuser_token_headers
        ).json()
        == original_sources_response
    )


@pytest.mark.parametrize(
    "comparison_run,damage,expected",
    [
        ("active", "missing_activity", "comparison_facts_invalid"),
        ("active", "activity_content", "comparison_facts_invalid"),
        ("active", "missing_observation", "comparison_facts_invalid"),
        ("active", "observation_content", "comparison_facts_invalid"),
        ("active", "missing_link", "comparison_facts_invalid"),
        ("active", "link_contract", "comparison_facts_invalid"),
        ("active", "missing_snapshot", "comparison_facts_invalid"),
        ("active", "cloudatlas_snapshot_hash", "comparison_facts_invalid"),
        ("active", "customer_load_hash", "comparison_facts_invalid"),
        ("active", "missing_receipt", "comparison_facts_invalid"),
        ("active", "malformed_receipt", "comparison_facts_invalid"),
        ("active", "receipt_contract", "comparison_facts_invalid"),
        ("active", "duplicate_publication", "comparison_facts_invalid"),
        ("active", "historical", "comparison_contract_unsupported"),
        ("active", "unmodeled", "comparison_contract_unsupported"),
        ("active", "failed", "run_not_published"),
        ("active", "incomplete", "run_not_published"),
        ("empty", "historical", "comparison_contract_unsupported"),
        ("empty", "missing_receipt", "comparison_facts_invalid"),
        ("empty", "malformed_receipt", "comparison_facts_invalid"),
    ],
    indirect=["comparison_run"],
)
def test_invalid_facts_never_become_unknown_or_empty(
    comparison_run: GovernanceRun,
    damage: str,
    expected: str,
) -> None:
    run = comparison_run
    with Session(engine) as session:
        session.connection().exec_driver_sql(
            "SET LOCAL session_replication_role = replica"
        )
        if damage == "missing_activity":
            session.exec(
                delete(NetFlowIPActivity).where(
                    col(NetFlowIPActivity.governance_run_id) == run.id
                )
            )
        elif damage == "activity_content":
            session.exec(
                update(NetFlowIPActivity)
                .where(col(NetFlowIPActivity.governance_run_id) == run.id)
                .values(flow_count=999)
            )
        elif damage == "missing_observation":
            session.exec(
                delete(Observation).where(col(Observation.governance_run_id) == run.id)
            )
        elif damage == "observation_content":
            session.exec(
                update(Observation)
                .where(col(Observation.governance_run_id) == run.id)
                .values(raw_ip="192.0.2.100")
            )
        elif damage == "missing_link":
            session.exec(
                delete(ObservationResourceLink).where(
                    col(ObservationResourceLink.governance_run_id) == run.id
                )
            )
        elif damage == "link_contract":
            session.exec(
                update(ObservationResourceLink)
                .where(col(ObservationResourceLink.governance_run_id) == run.id)
                .values(processing_contract_version="wrong")
            )
        elif damage == "missing_snapshot":
            session.exec(
                delete(SourceSnapshot).where(
                    col(SourceSnapshot.governance_run_id) == run.id,
                    col(SourceSnapshot.source_type) == "NETFLOW",
                )
            )
        elif damage == "cloudatlas_snapshot_hash":
            session.exec(
                update(SourceSnapshot)
                .where(
                    col(SourceSnapshot.governance_run_id) == run.id,
                    col(SourceSnapshot.source_type) == "CLOUDATLAS",
                )
                .values(content_sha256="0" * 64)
            )
        elif damage == "customer_load_hash":
            session.exec(
                update(RunStep)
                .where(
                    col(RunStep.governance_run_id) == run.id,
                    col(RunStep.step_code) == "LOAD_CUSTOMER",
                )
                .values(output_hash="0" * 64)
            )
        elif damage in {
            "historical",
            "missing_receipt",
            "malformed_receipt",
            "receipt_contract",
            "duplicate_publication",
        }:
            audit = session.exec(
                select(AuditEvent).where(
                    col(AuditEvent.target_id) == run.id,
                    col(AuditEvent.action) == "governance_run.published",
                )
            ).one()
            data = dict(audit.after_data or {})
            if damage == "duplicate_publication":
                session.add(AuditEvent(**audit.model_dump(exclude={"id"})))
                session.flush()
            else:
                if damage == "malformed_receipt":
                    data["netflow_activity"] = None
                elif damage == "receipt_contract":
                    receipt = dict(data["netflow_activity"])
                    receipt["contract_version"] = "netflow-ip-activity-v999"
                    data["netflow_activity"] = receipt
                else:
                    data.pop("netflow_activity")
                session.exec(
                    update(AuditEvent)
                    .where(col(AuditEvent.id) == audit.id)
                    .values(after_data=data)
                )
                if damage in {"historical", "malformed_receipt", "receipt_contract"}:
                    steps = {
                        step.step_code: step
                        for step in session.exec(
                            select(RunStep).where(
                                col(RunStep.governance_run_id) == run.id
                            )
                        ).all()
                    }
                    output = {
                        "processing_contract_version": run.processing_contract_version,
                        "check_findings_output_hash": steps[
                            "CHECK_FINDINGS"
                        ].output_hash,
                        "validated_report_output_hash": steps[
                            "VALIDATE_REPORT"
                        ].output_hash,
                        "governance_report_id": data["governance_report_id"],
                    }
                    if damage != "historical":
                        output["netflow_activity"] = data["netflow_activity"]
                    session.exec(
                        update(RunStep)
                        .where(col(RunStep.id) == steps["PUBLISH"].id)
                        .values(output_hash=_hash(output))
                    )
        elif damage == "unmodeled":
            session.exec(
                update(GovernanceRun)
                .where(col(GovernanceRun.id) == run.id)
                .values(
                    input_contract_version=None,
                    input_hash=None,
                    netflow_dataset_id=None,
                    netflow_content_sha256=None,
                    netflow_dataset_contract_version=None,
                )
            )
        elif damage == "failed":
            session.exec(
                update(GovernanceRun)
                .where(col(GovernanceRun.id) == run.id)
                .values(status="FAILED_PROCESSING", completed_at=None)
            )
        elif damage == "incomplete":
            session.exec(
                update(GovernanceRun)
                .where(col(GovernanceRun.id) == run.id)
                .values(completed_at=None)
            )
        session.expire_all()
        with pytest.raises(IPSourceComparisonError) as error:
            _read(session, run)
        assert error.value.code == expected
        session.rollback()


def test_scope_isolation_and_warning_success(
    comparison_run: GovernanceRun,
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    run = comparison_run
    with Session(engine) as session:
        for tenant, project, run_id in (
            (uuid.uuid4(), run.project_id, run.id),
            (run.tenant_id, uuid.uuid4(), run.id),
            (run.tenant_id, run.project_id, uuid.uuid4()),
        ):
            with pytest.raises(IPSourceComparisonError, match="run_not_found"):
                read_ip_source_comparison(
                    session=session, tenant_id=tenant, project_id=project, run_id=run_id
                )
        baseline = _read(session, run)
        session.connection().exec_driver_sql(
            "SET LOCAL session_replication_role = replica"
        )
        session.exec(
            update(GovernanceRun)
            .where(col(GovernanceRun.id) == run.id)
            .values(status="COMPLETED_WITH_WARNINGS")
        )
        session.flush()
        session.connection().exec_driver_sql(
            "SET LOCAL session_replication_role = origin"
        )
        session.expire_all()
        assert _read(session, run) == baseline

        def override_db() -> Generator[Session]:
            yield session

        previous = app.dependency_overrides.get(get_db)
        app.dependency_overrides[get_db] = override_db
        try:
            url = f"/api/v1/projects/{run.project_id}/governance-runs/{run.id}"
            sources = client.get(
                f"{url}/sources", headers=superuser_token_headers
            )
            comparisons = client.get(
                f"{url}/ip-source-comparisons", headers=superuser_token_headers
            )
            assert sources.status_code == comparisons.status_code == 200
            assert sources.json()["run_status"] == "COMPLETED_WITH_WARNINGS"
        finally:
            if previous is None:
                app.dependency_overrides.pop(get_db, None)
            else:
                app.dependency_overrides[get_db] = previous
            session.rollback()


@pytest.mark.parametrize("comparison_run", ["absent"], indirect=True)
def test_explicit_published_run_sources_distinguish_absent_netflow(
    comparison_run: GovernanceRun,
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.get(
        f"/api/v1/projects/{comparison_run.project_id}/governance-runs/"
        f"{comparison_run.id}/sources",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.keys() == {
        "project_id",
        "governance_run_id",
        "governance_report_id",
        "run_status",
        "completed_at",
        "input_contract_version",
        "processing_contract_version",
        "report_contract_version",
        "sources",
    }
    assert payload["project_id"] == str(comparison_run.project_id)
    assert payload["governance_run_id"] == str(comparison_run.id)
    assert payload["run_status"] == "COMPLETED"
    assert payload["input_contract_version"] == "governance-run-input-v1"
    assert payload["processing_contract_version"] == "ip-v1"
    assert payload["report_contract_version"] == "deterministic-report-v1"
    assert [source["source_type"] for source in payload["sources"]] == [
        "CUSTOMER_UPLOAD",
        "CLOUDATLAS",
        "NETFLOW",
    ]
    assert [source["state"] for source in payload["sources"]] == [
        "PRESENT",
        "PRESENT",
        "ABSENT",
    ]
    assert payload["sources"][2] == {
        "source_type": "NETFLOW",
        "state": "ABSENT",
        "snapshot_id": None,
        "input_id": None,
        "content_sha256": None,
        "schema_fingerprint": None,
        "method_fingerprint": None,
        "record_count": None,
        "valid_time_start_utc": None,
        "valid_time_end_utc": None,
    }
    forbidden = {"artifact_id", "storage_key", "raw_ip", "peer_ips", "protocols"}
    assert not any(forbidden & source.keys() for source in payload["sources"])


@pytest.mark.parametrize("comparison_run", ["active"], indirect=True)
def test_explicit_published_run_exposes_ip_source_comparison(
    comparison_run: GovernanceRun,
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.get(
        f"/api/v1/projects/{comparison_run.project_id}/governance-runs/"
        f"{comparison_run.id}/ip-source-comparisons",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.keys() == {
        "project_id",
        "governance_run_id",
        "governance_report_id",
        "report_contract_version",
        "contract_version",
        "output_hash",
        "data",
        "count",
        "page_size",
    }
    assert payload["project_id"] == str(comparison_run.project_id)
    assert payload["governance_run_id"] == str(comparison_run.id)
    assert payload["report_contract_version"] == "deterministic-report-v2"
    assert payload["contract_version"] == "ip-source-comparison/v1"
    assert payload["count"] == payload["page_size"] == len(payload["data"]) == 1
    assert payload["data"][0] == {
        "resource_id": payload["data"][0]["resource_id"],
        "canonical_ip": "192.0.2.10",
        "customer_upload_present": True,
        "cloudatlas_present": True,
        "netflow_status": "ACTIVE",
        "classification": "matched",
        "classification_reason": "observed_in_both_sources",
        "netflow_reason": "positive_activity_observed",
        "content_hash": payload["data"][0]["content_hash"],
    }


def test_ip_source_comparison_filters_before_stable_pagination(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
) -> None:
    def workbook() -> bytes:
        book = Workbook()
        sheet = book.active
        assert sheet is not None
        sheet.append(run_fixtures.REQUIRED_HEADERS)
        for ip in ("2001:db8::2", "192.0.2.10", "192.0.2.2"):
            sheet.append([ip, 443, 443, "是", "example.test"])
        output = io.BytesIO()
        book.save(output)
        book.close()
        return output.getvalue()

    monkeypatch.setattr(run_fixtures, "_workbook_bytes", workbook)
    project, _, _ = _prepare_present_run(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        content=HEADER + b"192.0.2.10,198.51.100.20,6,443,53000\n",
        trigger_id="comparison-api-pagination",
    )
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _client, _source, *, capset_token, page, size: {
            "items": [
                {"id": "asset-2", "ip": "192.0.2.2", "status": "valid"},
                {"id": "asset-10", "ip": "192.0.2.10", "status": "valid"},
                {"id": "asset-v6", "ip": "2001:db8::1", "status": "valid"},
            ],
            "page": page,
            "size": size,
            "total": 3,
        },
    )
    assert run_runner() == 0
    run = db.exec(
        select(GovernanceRun).where(
            col(GovernanceRun.project_id) == uuid.UUID(str(project["id"]))
        )
    ).one()
    url = (
        f"/api/v1/projects/{project['id']}/governance-runs/{run.id}/"
        "ip-source-comparisons"
    )

    first = client.get(
        url,
        headers=superuser_token_headers,
        params={"netflow_status": "UNKNOWN", "skip": 0, "limit": 2},
    )
    second = client.get(
        url,
        headers=superuser_token_headers,
        params={"netflow_status": "UNKNOWN", "skip": 2, "limit": 2},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["count"] == second.json()["count"] == 3
    assert first.json()["page_size"] == 2
    assert second.json()["page_size"] == 1
    assert [item["canonical_ip"] for item in first.json()["data"]] == [
        "192.0.2.2",
        "2001:db8::1",
    ]
    assert [item["canonical_ip"] for item in second.json()["data"]] == [
        "2001:db8::2"
    ]
    matched = client.get(
        url,
        headers=superuser_token_headers,
        params={"classification": "matched"},
    )
    assert matched.status_code == 200
    assert matched.json()["count"] == 2
    assert [item["canonical_ip"] for item in matched.json()["data"]] == [
        "192.0.2.2",
        "192.0.2.10",
    ]
    assert client.get(
        url,
        headers=superuser_token_headers,
        params={"classification": "invalid"},
    ).status_code == 422
    assert client.get(
        url,
        headers=superuser_token_headers,
        params={"netflow_status": "active"},
    ).status_code == 422


@pytest.mark.parametrize("comparison_run", ["empty"], indirect=True)
def test_run_result_reads_are_authorized_scoped_and_explicit(
    comparison_run: GovernanceRun,
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    urls = (
        f"/api/v1/projects/{comparison_run.project_id}/governance-runs/"
        f"{comparison_run.id}/sources",
        f"/api/v1/projects/{comparison_run.project_id}/governance-runs/"
        f"{comparison_run.id}/ip-source-comparisons",
    )
    role_headers = [
        run_fixtures._create_member(
            client,
            superuser_token_headers,
            project_id=str(comparison_run.project_id),
            roles=[role],
        )
        for role in ("viewer", "operator", "approver")
    ]
    unscoped = run_fixtures._create_member(
        client,
        superuser_token_headers,
        project_id=str(
            run_fixtures._create_project(client, superuser_token_headers)["id"]
        ),
        roles=["viewer"],
    )
    other_project = run_fixtures._create_project(client, superuser_token_headers)

    for url in urls:
        for headers in (*role_headers, superuser_token_headers):
            response = client.get(url, headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()["governance_run_id"] == str(comparison_run.id)
        assert client.get(url, headers=unscoped).status_code == 404
        cross_project_url = url.replace(
            str(comparison_run.project_id), str(other_project["id"]), 1
        )
        assert (
            client.get(cross_project_url, headers=superuser_token_headers).status_code
            == 404
        )


@pytest.mark.parametrize("comparison_run", ["active"], indirect=True)
@pytest.mark.parametrize(
    "damage,expected_status",
    [
        ("running", 404),
        ("failed", 404),
        ("incomplete", 404),
        ("unmodeled", 404),
        ("unsupported", 404),
        ("unsupported_report", 404),
        ("missing_receipt", 500),
        ("missing_report", 500),
        ("missing_snapshot", 500),
    ],
)
def test_run_result_reads_fail_closed(
    comparison_run: GovernanceRun,
    damage: str,
    expected_status: int,
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    run = comparison_run
    with Session(engine) as session:
        session.connection().exec_driver_sql(
            "SET LOCAL session_replication_role = replica"
        )
        if damage == "running":
            session.exec(
                update(GovernanceRun)
                .where(col(GovernanceRun.id) == run.id)
                .values(status="RUNNING", completed_at=None)
            )
        elif damage == "failed":
            session.exec(
                update(GovernanceRun)
                .where(col(GovernanceRun.id) == run.id)
                .values(status="FAILED_PROCESSING", completed_at=None)
            )
        elif damage == "incomplete":
            session.exec(
                update(GovernanceRun)
                .where(col(GovernanceRun.id) == run.id)
                .values(completed_at=None)
            )
        elif damage == "unmodeled":
            session.exec(
                update(GovernanceRun)
                .where(col(GovernanceRun.id) == run.id)
                .values(
                    input_contract_version=None,
                    input_hash=None,
                    netflow_dataset_id=None,
                    netflow_content_sha256=None,
                    netflow_dataset_contract_version=None,
                )
            )
        elif damage == "unsupported":
            session.exec(
                update(GovernanceRun)
                .where(col(GovernanceRun.id) == run.id)
                .values(processing_contract_version="ip-v99")
            )
        elif damage == "unsupported_report":
            session.exec(
                update(GovernanceRun)
                .where(col(GovernanceRun.id) == run.id)
                .values(report_contract_version="deterministic-report-v99")
            )
        elif damage == "missing_receipt":
            audit = session.exec(
                select(AuditEvent).where(
                    col(AuditEvent.target_id) == run.id,
                    col(AuditEvent.action) == "governance_run.published",
                )
            ).one()
            data = dict(audit.after_data or {})
            data.pop("netflow_activity", None)
            session.exec(
                update(AuditEvent)
                .where(col(AuditEvent.id) == audit.id)
                .values(after_data=data)
            )
        elif damage == "missing_report":
            from app.domain.models import GovernanceReport

            session.exec(
                delete(GovernanceReport).where(
                    col(GovernanceReport.governance_run_id) == run.id
                )
            )
        elif damage == "missing_snapshot":
            session.exec(
                delete(SourceSnapshot).where(
                    col(SourceSnapshot.governance_run_id) == run.id,
                    col(SourceSnapshot.source_type) == "NETFLOW",
                )
            )
        else:
            from app.domain.models import IPSourceComparisonFact

            session.exec(
                delete(IPSourceComparisonFact).where(
                    col(IPSourceComparisonFact.governance_run_id) == run.id
                )
            )
        session.flush()
        session.connection().exec_driver_sql(
            "SET LOCAL session_replication_role = origin"
        )

        def override_db() -> Generator[Session]:
            yield session

        previous = app.dependency_overrides.get(get_db)
        app.dependency_overrides[get_db] = override_db
        try:
            for suffix in ("sources", "ip-source-comparisons"):
                response = client.get(
                    f"/api/v1/projects/{run.project_id}/governance-runs/{run.id}/{suffix}",
                    headers=superuser_token_headers,
                )
                assert response.status_code == expected_status, response.text
                if expected_status == 500:
                    assert response.json() == {
                        "detail": "Run result integrity verification failed"
                    }
        finally:
            if previous is None:
                app.dependency_overrides.pop(get_db, None)
            else:
                app.dependency_overrides[get_db] = previous
            session.rollback()


@pytest.mark.parametrize("comparison_run", ["active"], indirect=True)
def test_historical_v1_without_activity_receipt_is_incompatible(
    comparison_run: GovernanceRun,
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    run = comparison_run
    with Session(engine) as session:
        session.connection().exec_driver_sql(
            "SET LOCAL session_replication_role = replica"
        )
        stored_run = session.get(GovernanceRun, run.id)
        assert stored_run is not None
        report = session.exec(
            select(GovernanceReport).where(
                GovernanceReport.governance_run_id == run.id
            )
        ).one()
        audit = session.exec(
            select(AuditEvent).where(
                AuditEvent.target_id == run.id,
                AuditEvent.action == "governance_run.published",
            )
        ).one()
        data = dict(audit.after_data or {})
        data.pop("netflow_activity", None)
        session.exec(
            update(GovernanceRun)
            .where(col(GovernanceRun.id) == run.id)
            .values(report_contract_version="deterministic-report-v1")
        )
        session.exec(
            update(GovernanceReport)
            .where(col(GovernanceReport.id) == report.id)
            .values(report_contract_version="deterministic-report-v1")
        )
        session.exec(
            update(AuditEvent)
            .where(col(AuditEvent.id) == audit.id)
            .values(after_data=data)
        )
        session.flush()
        session.refresh(stored_run)
        session.exec(
            update(GovernanceRun)
            .where(col(GovernanceRun.id) == run.id)
            .values(input_hash=pinned_inputs_for_run(stored_run).input_hash())
        )
        steps = {
            step.step_code: step
            for step in session.exec(
                select(RunStep).where(RunStep.governance_run_id == run.id)
            ).all()
        }
        session.exec(
            update(RunStep)
            .where(col(RunStep.id) == steps["PUBLISH"].id)
            .values(
                output_hash=_hash(
                    {
                        "processing_contract_version": stored_run.processing_contract_version,
                        "check_findings_output_hash": steps[
                            "CHECK_FINDINGS"
                        ].output_hash,
                        "validated_report_output_hash": steps[
                            "VALIDATE_REPORT"
                        ].output_hash,
                        "governance_report_id": str(report.id),
                    }
                )
            )
        )
        session.flush()
        session.connection().exec_driver_sql(
            "SET LOCAL session_replication_role = origin"
        )
        session.expire_all()

        def override_db() -> Generator[Session]:
            yield session

        previous = app.dependency_overrides.get(get_db)
        app.dependency_overrides[get_db] = override_db
        try:
            for suffix in ("sources", "ip-source-comparisons"):
                response = client.get(
                    f"/api/v1/projects/{run.project_id}/governance-runs/{run.id}/{suffix}",
                    headers=superuser_token_headers,
                )
                assert response.status_code == 404, response.text
        finally:
            if previous is None:
                app.dependency_overrides.pop(get_db, None)
            else:
                app.dependency_overrides[get_db] = previous
            session.rollback()


def test_openapi_exposes_explicit_run_result_contracts(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    document = response.json()
    run_path = "/api/v1/projects/{project_id}/governance-runs/{governance_run_id}"
    assert set(document["paths"][f"{run_path}/sources"]) == {"get"}
    comparison_operation = document["paths"][
        f"{run_path}/ip-source-comparisons"
    ]["get"]
    assert comparison_operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {
        "$ref": "#/components/schemas/IPSourceComparisonsPublic"
    }
    parameters = {
        parameter["name"]: parameter for parameter in comparison_operation["parameters"]
    }
    assert parameters["skip"]["schema"]["minimum"] == 0
    assert parameters["limit"]["schema"]["minimum"] == 1
    assert parameters["limit"]["schema"]["maximum"] == 100
    assert set(
        parameters["classification"]["schema"]["anyOf"][0]["enum"]
    ) == {
        "matched",
        "customer_upload_only",
        "cloudatlas_only",
        "neither_source_observed",
    }
    assert parameters["netflow_status"]["schema"]["anyOf"][0]["enum"] == [
        "ACTIVE",
        "UNKNOWN",
    ]
