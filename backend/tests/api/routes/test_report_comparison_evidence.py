"""Isolated fixtures cover v2 publication binding and integrity edge cases."""

import hashlib
import json
import uuid
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import event
from sqlmodel import Session, col, delete, select, update

from app.core.config import settings
from app.core.db import engine
from app.domain import governance_runs as runner
from app.domain.comparison_evidence import ReportV2EvidenceBundle
from app.domain.models import (
    Artifact,
    AuditEvent,
    Evidence,
    Finding,
    FindingOccurrence,
    FindingOccurrenceObservation,
    FindingOccurrenceSnapshot,
    FindingTransition,
    FindingTransitionObservation,
    FindingTransitionSnapshot,
    GovernanceReport,
    GovernanceRun,
    IPSourceComparisonFact,
    NetFlowIPActivity,
    Observation,
    Project,
    Resource,
    RunStep,
    SourceSnapshot,
)
from app.domain.report_candidate_facts import read_report_candidate_facts
from app.domain.report_candidates import (
    REPORT_V2_CONTRACT_VERSION,
    FrozenReportCandidateFacts,
    ReportCandidate,
    generate_report_candidate,
    validate_report_candidate,
)
from app.domain.report_comparison_evidence import (
    ReportComparisonEvidenceError,
    bind_report_comparison_evidence,
    read_report_comparison_evidence,
)
from tests.api.routes.test_governance_runs import _create_member, _create_project
from tests.api.routes.test_report_candidate_v2_facts import (
    _flush_report,
    _insert_run,
    _prepare_v2_run,
    _scope,
)


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _bind(
    session: Session,
    run: GovernanceRun,
    report: GovernanceReport,
    facts: FrozenReportCandidateFacts,
    candidate: ReportCandidate,
) -> Any:
    return bind_report_comparison_evidence(
        session=session,
        **_scope(run),
        report_id=report.id,
        frozen_facts=facts,
        candidate=candidate,
    )


def _read(session: Session, run: GovernanceRun, report: GovernanceReport) -> Any:
    return read_report_comparison_evidence(
        session=session,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        report_id=report.id,
    )


def _publish_bound_report(
    *,
    session: Session,
    run: GovernanceRun,
    facts: FrozenReportCandidateFacts,
    candidate: ReportCandidate,
    report: GovernanceReport,
) -> None:
    """Finish isolated test publication AFTER comparison binding; no commit.

    The v2 validator is real. The production v1 dispatcher/validator is neither
    monkeypatched nor enabled for v2. Inputs and activity use existing readers.
    """
    validate_report_candidate(facts, candidate)
    assert read_report_candidate_facts(session=session, **_scope(run)) == facts
    assert report.canonical_content == json.loads(candidate.rendered.canonical_json)
    for artifact_id, body, digest in (
        (
            report.html_artifact_id,
            candidate.rendered.html,
            candidate.rendered.html_sha256,
        ),
        (report.csv_artifact_id, candidate.rendered.csv, candidate.rendered.csv_sha256),
    ):
        artifact = session.get(Artifact, artifact_id)
        assert artifact is not None
        assert (artifact.byte_size, artifact.sha256) == (len(body), digest)
        path = settings.ARTIFACT_ROOT / artifact.storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        assert path.read_bytes() == body
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest

    resources = {
        str(item.canonical_key): item
        for item in session.exec(
            select(Resource).where(Resource.project_id == run.project_id)
        ).all()
    }
    snapshots = session.exec(
        select(SourceSnapshot).where(
            SourceSnapshot.governance_run_id == run.id,
            col(SourceSnapshot.source_type).in_(("CUSTOMER_UPLOAD", "CLOUDATLAS")),
        )
    ).all()
    observations = session.exec(
        select(Observation).where(
            Observation.governance_run_id == run.id,
        )
    ).all()
    for lifecycle in facts.governance.finding_lifecycles:
        current_occurrence = any(
            item.run_id == str(run.id) for item in lifecycle.occurrences
        )
        current_transition = next(
            (item for item in lifecycle.transitions if item.run_id == str(run.id)), None
        )
        if not current_occurrence and current_transition is None:
            continue
        finding = session.get(Finding, uuid.UUID(lifecycle.finding_id))
        if finding is None:
            finding = Finding(
                id=uuid.UUID(lifecycle.finding_id),
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                resource_id=resources[lifecycle.canonical_ip].id,
                finding_type=lifecycle.finding_type,
                dedupe_key=f"{lifecycle.finding_type}:{lifecycle.canonical_ip}",
                status="OPEN",
                first_detected_at=facts.governance.completed_at,
                last_detected_at=facts.governance.completed_at,
            )
        if current_transition is not None:
            finding.status = (
                "CLOSED" if current_transition.transition_type == "CLOSED" else "OPEN"
            )
        session.add(finding)
        session.flush()
        relevant = [
            item
            for item in observations
            if str(item.canonical_ip) == lifecycle.canonical_ip
        ]
        if current_occurrence:
            occurrence = FindingOccurrence(
                id=uuid.UUID(
                    runner._report_candidate_uuid(
                        run,
                        "occurrence",
                        lifecycle.finding_type,
                        lifecycle.canonical_ip,
                    )
                ),
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                governance_run_id=run.id,
                finding_id=finding.id,
            )
            session.add(occurrence)
            session.flush()
            session.add_all(
                [
                    FindingOccurrenceObservation(
                        tenant_id=run.tenant_id,
                        project_id=run.project_id,
                        governance_run_id=run.id,
                        finding_occurrence_id=occurrence.id,
                        observation_id=item.id,
                    )
                    for item in relevant
                ]
            )
            session.add_all(
                [
                    FindingOccurrenceSnapshot(
                        tenant_id=run.tenant_id,
                        project_id=run.project_id,
                        governance_run_id=run.id,
                        finding_occurrence_id=occurrence.id,
                        source_snapshot_id=item.id,
                    )
                    for item in snapshots
                ]
            )
        if current_transition is not None:
            transition = FindingTransition(
                id=uuid.UUID(
                    runner._report_candidate_uuid(
                        run,
                        "transition",
                        lifecycle.finding_type,
                        lifecycle.canonical_ip,
                    )
                ),
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                governance_run_id=run.id,
                finding_id=finding.id,
                transition_type=current_transition.transition_type,
            )
            session.add(transition)
            session.flush()
            session.add_all(
                [
                    FindingTransitionObservation(
                        tenant_id=run.tenant_id,
                        project_id=run.project_id,
                        governance_run_id=run.id,
                        finding_transition_id=transition.id,
                        observation_id=item.id,
                    )
                    for item in relevant
                ]
            )
            session.add_all(
                [
                    FindingTransitionSnapshot(
                        tenant_id=run.tenant_id,
                        project_id=run.project_id,
                        governance_run_id=run.id,
                        finding_transition_id=transition.id,
                        source_snapshot_id=item.id,
                    )
                    for item in snapshots
                ]
            )
    session.flush()
    activity_receipt = runner._publish_netflow_activity(session=session, run=run)
    columns = {
        "SOURCE_SNAPSHOT": "source_snapshot_id",
        "OBSERVATION": "observation_id",
        "FINDING_OCCURRENCE": "finding_occurrence_id",
        "FINDING_TRANSITION": "finding_transition_id",
    }
    for index, entry in enumerate(candidate.evidence_plan.entries):
        reference = entry.evidence_reference
        session.add(
            Evidence(
                id=uuid.uuid5(
                    report.id, f"{index}:{reference.fact_type}:{reference.fact_id}"
                ),
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                governance_run_id=run.id,
                governance_report_id=report.id,
                **{columns[reference.fact_type]: uuid.UUID(reference.fact_id)},
            )
        )
    session.flush()
    build = session.exec(
        select(RunStep).where(
            RunStep.governance_run_id == run.id,
            RunStep.step_code == "BUILD_REPORT",
        )
    ).one()
    html = session.get(Artifact, report.html_artifact_id)
    csv = session.get(Artifact, report.csv_artifact_id)
    assert html is not None and csv is not None
    build.output_hash = _hash(
        {
            "report_contract_version": REPORT_V2_CONTRACT_VERSION,
            "canonical_json_sha256": candidate.rendered.canonical_json_sha256,
            "html_sha256": report.html_sha256,
            "csv_sha256": report.csv_sha256,
            "html_storage_key": html.storage_key,
            "csv_storage_key": csv.storage_key,
        }
    )
    build.status = "SUCCEEDED"
    build.completed_at = facts.governance.completed_at
    validation_hash = _hash(
        {
            "build_output_hash": build.output_hash,
            "canonical_json_sha256": candidate.rendered.canonical_json_sha256,
            "html_sha256": report.html_sha256,
            "csv_sha256": report.csv_sha256,
        }
    )
    check = session.exec(
        select(RunStep).where(
            RunStep.governance_run_id == run.id,
            RunStep.step_code == "CHECK_FINDINGS",
        )
    ).one()
    publication: dict[str, Any] = {
        "status": "COMPLETED",
        "governance_report_id": str(report.id),
        "report_generation_mode": report.generation_mode,
    }
    output: dict[str, Any] = {
        "processing_contract_version": run.processing_contract_version,
        "check_findings_output_hash": check.output_hash,
        "validated_report_output_hash": validation_hash,
        "governance_report_id": str(report.id),
    }
    if activity_receipt is not None:
        publication["netflow_activity"] = activity_receipt
        output["netflow_activity"] = activity_receipt
    for code, input_hash, output_hash in (
        ("VALIDATE_REPORT", build.output_hash, validation_hash),
        ("PUBLISH", validation_hash, _hash(output)),
    ):
        session.add(
            RunStep(
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                governance_run_id=run.id,
                step_code=code,
                status="SUCCEEDED",
                input_hash=input_hash,
                output_hash=output_hash,
                started_at=build.started_at,
                completed_at=facts.governance.completed_at,
            )
        )
    session.add(build)
    session.add(
        runner._audit_event(
            run=run,
            action="governance_run.published",
            target_type="governance_run",
            target_id=run.id,
            before_data={"status": "RUNNING"},
            after_data=publication,
            request_ip=None,
        )
    )
    session.flush()
    run.status = "COMPLETED"
    run.completed_at = facts.governance.completed_at
    session.add(run)
    session.flush()
    # Final read validates fully formed facts in this same transaction, without
    # reopening candidate inputs or reusing the pre-lifecycle binder.
    assert isinstance(candidate.evidence_plan, ReportV2EvidenceBundle)
    assert len(_read(session, run, report)) == len(
        candidate.evidence_plan.comparison_entries
    )


@pytest.fixture
def binding_run(
    request: pytest.FixtureRequest,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> GovernanceRun:
    return _prepare_v2_run(
        client=client,
        headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        mode=getattr(request, "param", "active"),
        cloudatlas_ips=("192.0.2.20",),
    )


def _prepare_binding(
    session: Session, run: GovernanceRun
) -> tuple[FrozenReportCandidateFacts, ReportCandidate, GovernanceReport]:
    session.exec(
        select(GovernanceRun).where(GovernanceRun.id == run.id).with_for_update()
    ).one()
    facts = read_report_candidate_facts(session=session, **_scope(run))
    candidate = generate_report_candidate(facts, REPORT_V2_CONTRACT_VERSION)
    return (
        facts,
        candidate,
        _flush_report(session=session, run=run, candidate=candidate),
    )


@pytest.mark.parametrize("binding_run", ["absent", "empty", "active"], indirect=True)
def test_bind_reenter_publish_and_read_are_real_scoped_facts(
    binding_run: GovernanceRun,
    db: Session,
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    run = binding_run
    facts, candidate, report = _prepare_binding(db, run)
    before = db.exec(select(AuditEvent.id).where(AuditEvent.target_id == run.id)).all()
    bindings = _bind(db, run, report, facts, candidate)
    assert bindings == _bind(db, run, report, facts, candidate)
    assert tuple(item.fact for item in bindings) == facts.comparison.results[:50]
    persisted = db.exec(
        select(IPSourceComparisonFact).where(
            IPSourceComparisonFact.governance_run_id == run.id
        )
    ).all()
    assert len(persisted) == len(facts.comparison.results)
    assert run.status == "RUNNING" and run.completed_at is None
    assert (
        db.exec(select(AuditEvent.id).where(AuditEvent.target_id == run.id)).all()
        == before
    )
    with pytest.raises(ReportComparisonEvidenceError, match="report_not_ready"):
        _read(db, run, report)
    _publish_bound_report(
        session=db, run=run, facts=facts, candidate=candidate, report=report
    )
    db.commit()
    assert _read(db, run, report) == bindings
    with pytest.raises(ReportComparisonEvidenceError, match="report_not_ready"):
        _bind(db, run, report, facts, candidate)
    response = client.get(
        f"{settings.API_V1_STR}/projects/{run.project_id}/governance-reports/{report.id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["evidence_max_entries"] == 100
    assert detail["evidence_count"] == len(bindings) + len(
        candidate.evidence_plan.entries
    )
    assert detail["can_request_ai_governance_draft"] is False
    assert all(
        set(item) == {"id", "governance_run_id", "fact_type", "fact_id"}
        for item in detail["evidence"]
    )
    assert {
        item["id"]
        for item in detail["evidence"]
        if item["fact_type"] == "IP_SOURCE_COMPARISON"
    } == {str(item.evidence_id) for item in bindings}


@pytest.mark.parametrize(
    "damage",
    ["missing_fact", "missing_evidence", "extra_fact", "wrong_index", "wrong_hash"],
)
def test_partial_reentry_fails_without_repairs(
    binding_run: GovernanceRun, db: Session, damage: str
) -> None:
    run = binding_run
    facts, candidate, report = _prepare_binding(db, run)
    bindings = _bind(db, run, report, facts, candidate)
    db.connection().exec_driver_sql("SET LOCAL session_replication_role = replica")
    first_fact = uuid.UUID(bindings[0].evidence_reference.fact_id)
    if damage == "missing_fact":
        db.exec(
            delete(IPSourceComparisonFact).where(
                col(IPSourceComparisonFact.id) == first_fact
            )
        )
    elif damage == "missing_evidence":
        db.exec(delete(Evidence).where(col(Evidence.id) == bindings[0].evidence_id))
    elif damage == "wrong_index":
        db.exec(
            update(Evidence)
            .where(col(Evidence.id) == bindings[0].evidence_id)
            .values(id=uuid.uuid4())
        )
    elif damage == "wrong_hash":
        db.exec(
            update(IPSourceComparisonFact)
            .where(col(IPSourceComparisonFact.id) == first_fact)
            .values(content_hash="f" * 64)
        )
    else:
        extra = db.get(IPSourceComparisonFact, first_fact)
        assert extra is not None
        values = extra.model_dump(exclude={"id", "canonical_ip", "resource_id"})
        db.add(
            IPSourceComparisonFact(
                **values,
                id=uuid.uuid4(),
                resource_id=uuid.uuid4(),
                canonical_ip="203.0.113.250",
            )
        )
        db.flush()
    db.expire_all()
    with pytest.raises(
        ReportComparisonEvidenceError, match="comparison_evidence_invalid"
    ):
        _bind(db, run, report, facts, candidate)
    db.rollback()


@pytest.mark.parametrize(
    "damage",
    [
        "missing_report",
        "wrong_run",
        "wrong_tenant",
        "candidate_bytes",
        "report_hash",
        "canonical",
        "comparison_contract",
        "staged_transition",
        "pending_transition",
        "pending_finding",
        "pending_activity",
    ],
)
def test_binding_preconditions_fail_closed(
    binding_run: GovernanceRun, db: Session, damage: str
) -> None:
    run = binding_run
    facts, candidate, report = _prepare_binding(db, run)
    code = "comparison_evidence_invalid"
    kwargs = _scope(run)
    if damage == "missing_report":
        report.id = uuid.uuid4()
        code = "report_not_found"
    elif damage == "wrong_run":
        kwargs["run_id"] = uuid.uuid4()
    elif damage == "wrong_tenant":
        kwargs["tenant_id"] = uuid.uuid4()
        code = "report_not_found"
    elif damage == "candidate_bytes":
        candidate = candidate.model_copy(
            update={"rendered": replace(candidate.rendered, html=b"corrupt")}
        )
    elif damage == "report_hash":
        db.connection().exec_driver_sql("SET LOCAL session_replication_role = replica")
        db.exec(
            update(GovernanceReport)
            .where(col(GovernanceReport.id) == report.id)
            .values(html_sha256="f" * 64)
        )
    elif damage == "canonical":
        db.exec(
            update(GovernanceReport)
            .where(col(GovernanceReport.id) == report.id)
            .values(canonical_content={"bad": "content"})
        )
    elif damage == "comparison_contract":
        db.connection().exec_driver_sql("SET LOCAL session_replication_role = replica")
        db.exec(
            update(GovernanceRun)
            .where(col(GovernanceRun.id) == run.id)
            .values(processing_contract_version="unsupported")
        )
        code = "comparison_contract_unsupported"
    else:
        code = "report_not_ready"
        resource = db.exec(
            select(Resource).where(Resource.project_id == run.project_id)
        ).first()
        assert resource is not None
        if damage == "pending_activity":
            db.add(
                NetFlowIPActivity(
                    tenant_id=run.tenant_id,
                    project_id=run.project_id,
                    governance_run_id=run.id,
                    resource_id=resource.id,
                )
            )
        elif damage == "pending_finding":
            db.add(
                Finding(
                    tenant_id=run.tenant_id,
                    project_id=run.project_id,
                    resource_id=resource.id,
                    finding_type="UNOBSERVED_ASSET",
                    dedupe_key="pending",
                    status="OPEN",
                )
            )
        else:
            finding = Finding(
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                resource_id=resource.id,
                finding_type="UNOBSERVED_ASSET",
                dedupe_key="staged",
                status="OPEN",
            )
            db.add(finding)
            db.flush()
            db.add(
                FindingTransition(
                    tenant_id=run.tenant_id,
                    project_id=run.project_id,
                    governance_run_id=run.id,
                    finding_id=finding.id,
                    transition_type="OPENED",
                )
            )
            if damage == "staged_transition":
                db.flush()
    with pytest.raises(ReportComparisonEvidenceError, match=code):
        bind_report_comparison_evidence(
            session=db,
            **kwargs,
            report_id=report.id,
            frozen_facts=facts,
            candidate=candidate,
        )
    db.rollback()


@pytest.mark.parametrize("fail_after", ["facts", "evidence"])
def test_outer_rollback_removes_both_groups(
    binding_run: GovernanceRun, db: Session, fail_after: str
) -> None:
    run = binding_run
    facts, candidate, report = _prepare_binding(db, run)
    run_id = run.id

    def fail_flush(session: Session, _context: Any) -> None:
        expected = IPSourceComparisonFact if fail_after == "facts" else Evidence
        if any(isinstance(item, expected) for item in session.new):
            raise RuntimeError("injected transaction failure")

    event.listen(db, "after_flush", fail_flush)
    try:
        with pytest.raises(RuntimeError, match="injected transaction failure"):
            _bind(db, run, report, facts, candidate)
    finally:
        event.remove(db, "after_flush", fail_flush)
        db.rollback()
    with Session(engine) as reader:
        assert not reader.exec(
            select(IPSourceComparisonFact).where(
                IPSourceComparisonFact.governance_run_id == run_id
            )
        ).all()
        assert not reader.exec(
            select(Evidence).where(Evidence.governance_run_id == run_id)
        ).all()
        current = reader.get(GovernanceRun, run_id)
        assert (
            current is not None
            and current.status == "RUNNING"
            and current.completed_at is None
        )


@pytest.mark.parametrize(
    "damage",
    [
        "missing_fact",
        "extra_fact",
        "receipt",
        "canonical",
        "governance_missing",
        "comparison_missing",
        "artifact_hash",
        "current_transition_changed",
    ],
)
def test_published_damage_is_not_partial_success(
    binding_run: GovernanceRun, db: Session, damage: str
) -> None:
    run = binding_run
    facts, candidate, report = _prepare_binding(db, run)
    bindings = _bind(db, run, report, facts, candidate)
    _publish_bound_report(
        session=db, run=run, facts=facts, candidate=candidate, report=report
    )
    db.connection().exec_driver_sql("SET LOCAL session_replication_role = replica")
    if damage == "missing_fact":
        db.exec(
            delete(IPSourceComparisonFact).where(
                col(IPSourceComparisonFact.id)
                == uuid.UUID(bindings[0].evidence_reference.fact_id)
            )
        )
    elif damage == "extra_fact":
        original = db.get(
            IPSourceComparisonFact, uuid.UUID(bindings[0].evidence_reference.fact_id)
        )
        assert original is not None
        db.add(
            IPSourceComparisonFact(
                **original.model_dump(exclude={"id", "canonical_ip", "resource_id"}),
                id=uuid.uuid4(),
                resource_id=uuid.uuid4(),
                canonical_ip="203.0.113.250",
            )
        )
        db.flush()
    elif damage == "receipt":
        db.exec(
            update(AuditEvent)
            .where(
                col(AuditEvent.target_id) == run.id,
                col(AuditEvent.action) == "governance_run.published",
            )
            .values(after_data={"governance_report_id": str(report.id)})
        )
    elif damage == "canonical":
        db.exec(
            update(GovernanceReport)
            .where(col(GovernanceReport.id) == report.id)
            .values(canonical_content={"bad": "content"})
        )
    elif damage == "artifact_hash":
        db.exec(
            update(Artifact)
            .where(col(Artifact.id) == report.html_artifact_id)
            .values(sha256="f" * 64)
        )
    elif damage == "current_transition_changed":
        entry = next(
            item
            for item in candidate.evidence_plan.entries
            if item.coverage == "CURRENT_RUN_TRANSITION"
            and item.evidence_reference.fact_type == "FINDING_TRANSITION"
        )
        assert entry.transition_type == "OPENED"
        db.exec(
            update(FindingTransition)
            .where(
                col(FindingTransition.id) == uuid.UUID(entry.evidence_reference.fact_id)
            )
            .values(transition_type="CLOSED")
        )
    else:
        condition = (
            col(Evidence.ip_source_comparison_fact_id).is_(None)
            if damage == "governance_missing"
            else col(Evidence.ip_source_comparison_fact_id).is_not(None)
        )
        db.exec(
            delete(Evidence).where(
                col(Evidence.governance_report_id) == report.id, condition
            )
        )
    with pytest.raises(
        ReportComparisonEvidenceError,
        match="comparison_evidence_invalid|comparison_contract_unsupported",
    ):
        _read(db, run, report)
    db.rollback()


@pytest.mark.parametrize("count", [50, 51, 100, 101])
def test_full_population_independent_budgets_and_unsampled_damage(
    count: int,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    run = _prepare_v2_run(
        client=client,
        headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        cloudatlas_ips=(
            "192.0.2.10",
            *(f"203.0.113.{index}" for index in range(1, count)),
        ),
    )
    facts, candidate, report = _prepare_binding(db, run)
    assert len(facts.comparison.results) == count
    bindings = _bind(db, run, report, facts, candidate)
    assert len(bindings) == 50
    assert len(candidate.evidence_plan.entries) == min(count - 1, 50)
    assert (
        len(
            db.exec(
                select(IPSourceComparisonFact).where(
                    IPSourceComparisonFact.governance_run_id == run.id
                )
            ).all()
        )
        == count
    )
    _publish_bound_report(
        session=db, run=run, facts=facts, candidate=candidate, report=report
    )
    db.commit()
    response = client.get(
        f"{settings.API_V1_STR}/projects/{run.project_id}/governance-reports/{report.id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["evidence_count"] == 50 + min(count - 1, 50)
    assert len(response.json()["evidence"]) == 50 + min(count - 1, 50)
    if count > 50:
        # Do not expire cached ORM identities: the reader must really re-read.
        last = db.exec(
            select(IPSourceComparisonFact).where(
                IPSourceComparisonFact.governance_run_id == run.id,
                IPSourceComparisonFact.canonical_ip
                == facts.comparison.results[-1].canonical_ip,
            )
        ).one()
        db.connection().exec_driver_sql("SET LOCAL session_replication_role = replica")
        db.connection().exec_driver_sql(
            "UPDATE ip_source_comparison_facts SET content_hash = %s WHERE id = %s",
            ("f" * 64, last.id),
        )
        with pytest.raises(
            ReportComparisonEvidenceError, match="comparison_evidence_invalid"
        ):
            _read(db, run, report)
        db.rollback()


def test_binding_rejects_late_history_but_ignores_unrelated_selection_and_resource(
    binding_run: GovernanceRun,
    db: Session,
) -> None:
    run = binding_run
    facts, candidate, report = _prepare_binding(db, run)
    project = db.get(Project, run.project_id)
    assert project is not None
    project.current_netflow_dataset_id = None
    db.add(project)
    resource = Resource(
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        resource_type="IP",
        canonical_key="203.0.113.90",
    )
    db.add(resource)
    db.flush()
    assert _bind(db, run, report, facts, candidate)
    history = _insert_run(session=db, project=project, status="FAILED_PROCESSING")
    finding = Finding(
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        resource_id=resource.id,
        finding_type="UNOBSERVED_ASSET",
        dedupe_key="UNOBSERVED_ASSET:203.0.113.90",
        status="OPEN",
    )
    db.add(finding)
    db.flush()
    db.add(
        FindingOccurrence(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            governance_run_id=history.id,
            finding_id=finding.id,
        )
    )
    db.add(
        FindingTransition(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            governance_run_id=history.id,
            finding_id=finding.id,
            transition_type="OPENED",
        )
    )
    db.flush()
    history.status = "COMPLETED"
    history.completed_at = facts.governance.completed_at + timedelta(days=1)
    db.add(history)
    db.flush()
    with pytest.raises(
        ReportComparisonEvidenceError, match="comparison_evidence_invalid"
    ):
        _bind(db, run, report, facts, candidate)
    db.rollback()


def test_fresh_binding_does_not_trust_cached_resource(
    binding_run: GovernanceRun, db: Session
) -> None:
    run = binding_run
    facts, candidate, report = _prepare_binding(db, run)
    resource = db.get(Resource, facts.comparison.results[0].resource_id)
    assert resource is not None
    db.connection().exec_driver_sql("SET LOCAL session_replication_role = replica")
    db.connection().exec_driver_sql(
        "UPDATE resources SET canonical_key = '203.0.113.88' WHERE id = %s",
        (resource.id,),
    )
    with pytest.raises(
        ReportComparisonEvidenceError, match="comparison_evidence_invalid"
    ):
        _bind(db, run, report, facts, candidate)
    db.rollback()


def test_v2_detail_permissions_archive_and_corruption(
    binding_run: GovernanceRun,
    db: Session,
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    run = binding_run
    facts, candidate, report = _prepare_binding(db, run)
    _bind(db, run, report, facts, candidate)
    _publish_bound_report(
        session=db, run=run, facts=facts, candidate=candidate, report=report
    )
    db.commit()
    url = f"{settings.API_V1_STR}/projects/{run.project_id}/governance-reports/{report.id}"
    roles = [
        _create_member(
            client,
            superuser_token_headers,
            project_id=str(run.project_id),
            roles=[role],
        )
        for role in ("viewer", "operator", "approver")
    ]
    assert (
        client.post(
            f"{settings.API_V1_STR}/projects/{run.project_id}/archive",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )
    for headers in (*roles, superuser_token_headers):
        response = client.get(url, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["can_request_ai_governance_draft"] is False
    other = _create_project(client, superuser_token_headers)
    assert (
        client.get(
            f"{settings.API_V1_STR}/projects/{other['id']}/governance-reports/{report.id}",
            headers=superuser_token_headers,
        ).status_code
        == 404
    )
    with pytest.raises(ReportComparisonEvidenceError, match="report_not_found"):
        read_report_comparison_evidence(
            session=db,
            tenant_id=uuid.uuid4(),
            project_id=run.project_id,
            report_id=report.id,
        )
    db.connection().exec_driver_sql("SET LOCAL session_replication_role = replica")
    db.exec(
        delete(Evidence).where(
            col(Evidence.governance_report_id) == report.id,
            col(Evidence.ip_source_comparison_fact_id).is_not(None),
        )
    )
    db.commit()
    response = client.get(url, headers=superuser_token_headers)
    assert response.status_code == 500
    assert response.json() == {"detail": "Report integrity verification failed"}


def test_v1_pin_cannot_bind_its_v2_memory_candidate(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    run = _prepare_v2_run(
        client=client,
        headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        report_contract_version="deterministic-report-v1",
    )
    facts = read_report_candidate_facts(session=db, **_scope(run))
    report = _flush_report(
        session=db,
        run=run,
        candidate=generate_report_candidate(facts, "deterministic-report-v1"),
    )
    candidate = generate_report_candidate(facts, REPORT_V2_CONTRACT_VERSION)
    with pytest.raises(
        ReportComparisonEvidenceError, match="report_contract_unsupported"
    ):
        _bind(db, run, report, facts, candidate)
    with pytest.raises(
        ReportComparisonEvidenceError, match="report_contract_unsupported"
    ):
        _read(db, run, report)
    db.rollback()


def test_published_resolution_reads_no_files_or_writes(
    binding_run: GovernanceRun,
    db: Session,
    monkeypatch: MonkeyPatch,
) -> None:
    run = binding_run
    facts, candidate, report = _prepare_binding(db, run)
    expected = _bind(db, run, report, facts, candidate)
    _publish_bound_report(
        session=db, run=run, facts=facts, candidate=candidate, report=report
    )

    def forbidden_file(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("published comparison resolution must not open Artifacts")

    monkeypatch.setattr(Path, "read_bytes", forbidden_file)

    def reject_write(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _many: Any,
    ) -> None:
        assert statement.lstrip().split()[0].upper() not in {
            "INSERT",
            "UPDATE",
            "DELETE",
        }, statement

    event.listen(engine, "before_cursor_execute", reject_write)
    try:
        assert _read(db, run, report) == expected
    finally:
        event.remove(engine, "before_cursor_execute", reject_write)
        db.rollback()
