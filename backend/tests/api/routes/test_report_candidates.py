import hashlib
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import event
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.domain import governance_runs as runner
from app.domain.cloudatlas_sources import OctobusCloudAtlasClient
from app.domain.ip_source_comparison import read_ip_source_comparison
from app.domain.models import (
    Artifact,
    Finding,
    GovernanceReport,
    GovernanceRun,
    Project,
    Resource,
    SourceSnapshot,
)
from app.domain.report_candidate_facts import (
    generate_run_report_candidate,
    read_report_candidate_facts,
)
from app.domain.report_candidates import (
    FrozenReportCandidateFacts,
    ReportCandidateError,
    ReportV2,
    generate_report_candidate,
    validate_report_candidate,
)
from app.governance_runner import main as run_runner
from tests.api.routes import test_governance_runs as run_fixtures
from tests.api.routes import test_ip_source_comparison as comparison_fixtures
from tests.api.routes.test_governance_report_reads import (
    _configure_runner,
    _start_rerun,
)
from tests.api.routes.test_governance_run_netflow import _prepare_present_run

HEADER = comparison_fixtures.HEADER
comparison_run = comparison_fixtures.comparison_run


def _scope(run: GovernanceRun) -> dict[str, uuid.UUID]:
    return {"tenant_id": run.tenant_id, "project_id": run.project_id, "run_id": run.id}


@pytest.mark.parametrize("comparison_run", ["absent", "empty", "active"], indirect=True)
def test_published_candidate_is_read_only_rebuildable_and_keeps_v1_files(
    comparison_run: GovernanceRun,
    db: Session,
) -> None:
    run = comparison_run
    report = db.exec(
        select(GovernanceReport).where(GovernanceReport.governance_run_id == run.id)
    ).one()
    v1_content = report.canonical_content
    snapshots = db.exec(
        select(SourceSnapshot).where(SourceSnapshot.governance_run_id == run.id)
    ).all()
    artifacts = db.exec(
        select(Artifact).where(
            col(Artifact.id).in_((report.html_artifact_id, report.csv_artifact_id))
        )
    ).all()
    artifact_before = {
        artifact.id: (
            runner._artifact_path(artifact).read_bytes(),
            runner._artifact_path(artifact).stat().st_mode,
        )
        for artifact in artifacts
    }
    facts = read_report_candidate_facts(session=db, **_scope(run))
    assert facts.comparison == read_ip_source_comparison(session=db, **_scope(run))
    candidate = generate_report_candidate(facts, "deterministic-report-v2")
    assert isinstance(candidate.report, ReportV2)
    validate_report_candidate(facts, candidate)
    assert (
        generate_run_report_candidate(
            session=db, **_scope(run), report_contract_version="deterministic-report-v2"
        )
        == candidate
    )
    assert len(candidate.report.input_completeness.sources) == len(snapshots)
    rows = candidate.report.ip_source_comparison.results
    assert len(rows) == 1
    expected = (
        ("UNKNOWN", "netflow_input_absent")
        if run.netflow_dataset_id is None
        else ("ACTIVE", "positive_activity_observed")
        if facts.comparison.results[0].netflow_status == "ACTIVE"
        else ("UNKNOWN", "no_positive_activity_evidence")
    )
    assert (rows[0].netflow_status, rows[0].netflow_reason) == expected
    if facts.netflow_snapshot is not None:
        assert (
            candidate.report.input_capabilities.netflow.positive_activity_resource_count
            == int(expected[0] == "ACTIVE")
        )
    assert candidate.report.input_capabilities.netflow.coverage == "UNKNOWN"
    assert run.report_contract_version == "deterministic-report-v1"
    assert report.canonical_content == v1_content
    for artifact in artifacts:
        path = runner._artifact_path(artifact)
        assert (path.read_bytes(), path.stat().st_mode) == artifact_before[artifact.id]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact.sha256
    assert candidate.rendered.csv.count(b"\r\n") == len(rows) + 1
    assert not db.new and not db.dirty and not db.deleted

    def reject_writes(
        _connection: object, _cursor: object, statement: str, *_args: object
    ) -> None:
        assert statement.lstrip().split(maxsplit=1)[0].upper() not in {
            "INSERT",
            "UPDATE",
            "DELETE",
        }

    event.listen(engine, "before_cursor_execute", reject_writes)
    try:
        assert read_report_candidate_facts(session=db, **_scope(run)) == facts
        rebuilt_v1 = generate_report_candidate(facts, "deterministic-report-v1")
        assert json.loads(rebuilt_v1.rendered.canonical_json) == v1_content
        assert rebuilt_v1.rendered.html_sha256 == report.html_sha256
        assert rebuilt_v1.rendered.csv_sha256 == report.csv_sha256
        # Explicit scoped failures do not leak a different Project or tenant.
        for scope in (
            {**_scope(run), "tenant_id": uuid.uuid4()},
            {**_scope(run), "project_id": uuid.uuid4()},
            {**_scope(run), "run_id": uuid.uuid4()},
        ):
            with pytest.raises(ReportCandidateError, match="report_facts_invalid"):
                read_report_candidate_facts(session=db, **scope)
        # Detached bundles rebuild after the read transaction is gone.
        roundtripped = FrozenReportCandidateFacts.model_validate_json(
            facts.model_dump_json()
        )
        assert (
            generate_report_candidate(roundtripped, "deterministic-report-v2")
            == candidate
        )
    finally:
        event.remove(engine, "before_cursor_execute", reject_writes)


@pytest.mark.parametrize("mode", ["absent", "empty", "active", "self"])
def test_prepublication_candidate_matches_published_reader_and_never_touches_files(
    mode: str,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    trigger_id = f"candidate-{uuid.uuid4()}"
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
            else HEADER + b"192.0.2.10,198.51.100.20,6,443,53000\n"
        )
        if mode == "self":
            content = HEADER + b"192.0.2.10,192.0.2.10,6,443,443\n"
        project, _, _ = _prepare_present_run(
            client=client,
            headers=superuser_token_headers,
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            content=content,
            trigger_id=trigger_id,
        )
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _client, _source, *, capset_token, page, size: {
            "items": [{"id": "asset-20", "ip": "192.0.2.20", "status": "valid"}],
            "page": page,
            "size": size,
            "total": 1,
        },
    )
    captured: list[FrozenReportCandidateFacts] = []
    prepare_v1 = runner._prepare_report_candidate

    def prepare_and_capture(
        *, session: Session, run: GovernanceRun
    ) -> runner.ReportCandidate:
        assert run.completed_at is None
        assert (
            session.exec(
                select(GovernanceReport.id).where(
                    GovernanceReport.governance_run_id == run.id
                )
            ).first()
            is None
        )
        v1_candidate = prepare_v1(session=session, run=run)
        before = {
            key: (
                (settings.ARTIFACT_ROOT / key).read_bytes(),
                (settings.ARTIFACT_ROOT / key).stat().st_mode,
            )
            for key in (v1_candidate.html_storage_key, v1_candidate.csv_storage_key)
        }
        facts = read_report_candidate_facts(session=session, **_scope(run))
        if mode == "active":
            with session.begin_nested() as later_resource:
                session.add(
                    Resource(
                        tenant_id=run.tenant_id,
                        project_id=run.project_id,
                        resource_type="IP",
                        canonical_key="198.51.100.20",
                    )
                )
                session.flush()
                assert (
                    read_report_candidate_facts(session=session, **_scope(run)) == facts
                )
                later_resource.rollback()
        candidate = generate_report_candidate(facts, "deterministic-report-v2")
        validate_report_candidate(facts, candidate)
        assert candidate.report.ip_consistency_summary.current_run_finding_count == 2
        assert len(candidate.evidence_plan.entries) == 2
        assert candidate.report.current_run_lifecycle_changes.total == 2
        assert all(
            entry.evidence_reference.fact_type == "FINDING_TRANSITION"
            for entry in candidate.evidence_plan.entries
        )
        for key, value in before.items():
            path = settings.ARTIFACT_ROOT / key
            assert (path.read_bytes(), path.stat().st_mode) == value
        captured.append(facts)
        return v1_candidate

    monkeypatch.setattr(runner, "_prepare_report_candidate", prepare_and_capture)
    assert run_runner() == 0
    monkeypatch.setattr(runner, "_prepare_report_candidate", prepare_v1)
    run = db.exec(
        select(GovernanceRun).where(
            GovernanceRun.project_id == uuid.UUID(str(project["id"]))
        )
    ).one()
    assert run.status == "COMPLETED"
    assert run.report_contract_version == "deterministic-report-v1"
    facts = captured[0]
    assert facts.comparison == read_ip_source_comparison(session=db, **_scope(run))
    candidate = generate_report_candidate(facts, "deterministic-report-v2")
    rebuilt = generate_run_report_candidate(
        session=db, **_scope(run), report_contract_version="deterministic-report-v2"
    )
    assert rebuilt == candidate
    old_input_hash = run.input_hash
    old_report = db.exec(
        select(GovernanceReport).where(GovernanceReport.governance_run_id == run.id)
    ).one()
    old_content = old_report.canonical_content
    old_artifact_hashes = (old_report.html_sha256, old_report.csv_sha256)
    assert candidate.evidence_plan.entries
    assert all(
        entry.evidence_reference.fact_type
        in {
            "SOURCE_SNAPSHOT",
            "OBSERVATION",
            "FINDING_OCCURRENCE",
            "FINDING_TRANSITION",
        }
        for entry in candidate.evidence_plan.entries
    )

    # A later Run closes the current unobserved Finding. Old candidate remains as-of.
    monkeypatch.setattr(
        OctobusCloudAtlasClient,
        "list_ip_assets_page",
        lambda _client, _source, *, capset_token, page, size: {
            "items": [
                {"id": "asset-10", "ip": "192.0.2.10", "status": "valid"},
                {"id": "asset-20", "ip": "192.0.2.20", "status": "valid"},
            ],
            "page": page,
            "size": size,
            "total": 2,
        },
    )
    _start_rerun(
        client=client,
        headers=superuser_token_headers,
        monkeypatch=monkeypatch,
        project_id=project["id"],
        run_id=run.id,
        trigger_id=f"candidate-rerun-{run.id}",
    )
    db.expire_all()
    stored_project = db.get(Project, run.project_id)
    assert stored_project is not None
    stored_project.current_netflow_dataset_id = None
    db.add(stored_project)
    db.add(
        Resource(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            resource_type="IP",
            canonical_key="203.0.113.100",
        )
    )
    db.commit()
    changed_findings = db.exec(
        select(Finding).where(
            Finding.project_id == run.project_id, Finding.status == "CLOSED"
        )
    ).all()
    assert changed_findings
    assert generate_report_candidate(facts, "deterministic-report-v2") == candidate
    assert (
        generate_run_report_candidate(
            session=db, **_scope(run), report_contract_version="deterministic-report-v2"
        )
        == candidate
    )
    db.refresh(old_report)
    db.refresh(run)
    assert run.input_hash == old_input_hash
    assert old_report.canonical_content == old_content
    assert (old_report.html_sha256, old_report.csv_sha256) == old_artifact_hashes
