import json
import uuid
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlmodel import Session

from app.core.config import settings
from app.domain import governance_runs as runner
from app.domain.cloudatlas_sources import OctobusCloudAtlasClient
from app.domain.ip_consistency import IP_PROCESSING_CONTRACT_VERSION
from app.domain.ip_source_comparison import (
    IPSourceComparisonError,
    read_ip_source_comparison,
)
from app.domain.models import (
    Artifact,
    Finding,
    FindingOccurrence,
    FindingTransition,
    GovernanceReport,
    GovernanceRun,
    NetFlowDataset,
    Project,
    Resource,
    RunStep,
)
from app.domain.report_candidate_facts import (
    generate_run_report_candidate,
    read_report_candidate_facts,
)
from app.domain.report_candidates import (
    REPORT_V2_CONTRACT_VERSION,
    ReportCandidate,
    ReportCandidateError,
    generate_report_candidate,
    validate_report_candidate,
)
from app.domain.report_core import REPORT_CONTRACT_VERSION
from tests.api.routes import test_governance_runs as run_fixtures
from tests.api.routes.test_governance_report_reads import _configure_runner
from tests.api.routes.test_netflow_datasets import _upload

HEADER = b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"


def _scope(run: GovernanceRun) -> dict[str, uuid.UUID]:
    return {"tenant_id": run.tenant_id, "project_id": run.project_id, "run_id": run.id}


def _insert_run(
    *,
    session: Session,
    project: Project,
    report_contract_version: str = REPORT_V2_CONTRACT_VERSION,
    processing_contract_version: str = IP_PROCESSING_CONTRACT_VERSION,
    input_contract_version: str | None = "governance-run-input-v1",
    status: str = "RUNNING",
) -> GovernanceRun:
    # Test-only construction: the first INSERT already contains the final pin.
    pinned = replace(
        runner.require_trigger_readiness(session=session, project=project),
        report_contract_version=report_contract_version,
        processing_contract_version=processing_contract_version,
        input_contract_version=input_contract_version,
    )
    run = GovernanceRun(
        **asdict(pinned),
        input_hash=pinned.input_hash() if input_contract_version is not None else None,
        trigger_id=f"v2-adapter-{uuid.uuid4()}",
        session_id=uuid.uuid4().hex,
        requested_by="v2-adapter-fixture",
        status=status,
    )
    session.add(run)
    session.flush()
    return run


def _prepare_v2_run(
    *,
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    mode: str = "absent",
    report_contract_version: str = REPORT_V2_CONTRACT_VERSION,
    cloudatlas_ips: tuple[str, ...] | None = None,
) -> GovernanceRun:
    """Real fixed facts through CHECK_FINDINGS with a test-only direct Run insert."""
    _configure_runner(tmp_path, monkeypatch)
    if cloudatlas_ips is not None:
        items = [
            {"id": f"asset-{index}", "ip": ip, "status": "valid"}
            for index, ip in enumerate(cloudatlas_ips)
        ]
        monkeypatch.setattr(
            OctobusCloudAtlasClient,
            "list_ip_assets_page",
            lambda _client, _source, *, capset_token, page, size: {
                "items": items[(page - 1) * size : page * size],
                "page": page,
                "size": size,
                "total": len(items),
            },
        )
    project_data = run_fixtures._create_project(client, headers)
    run_fixtures._prepare_ready_project(
        client=client, headers=headers, project=project_data
    )
    if mode != "absent":
        assert mode in {"empty", "active"}
        content = HEADER
        if mode == "active":
            content += b"192.0.2.10,198.51.100.20,6,443,53000\n"
        response = _upload(client, headers, project_data["id"], content)
        assert response.status_code == 201, response.text
        dataset_id = response.json()["id"]
        response = client.post(
            f"{settings.API_V1_STR}/projects/{project_data['id']}/netflow-datasets/{dataset_id}/select",
            headers=headers,
        )
        assert response.status_code == 200, response.text
    project = db.get(Project, uuid.UUID(str(project_data["id"])))
    assert project is not None
    db.refresh(project)
    run = _insert_run(
        session=db, project=project, report_contract_version=report_contract_version
    )
    db.commit()
    runner._load_customer_snapshot(session=db, run=run, request_ip=None)
    runner._pull_cloudatlas_snapshot(session=db, run=run, request_ip=None)
    runner._load_netflow_snapshot(session=db, run=run, request_ip=None)
    runner._normalize_ip_observations(session=db, run=run, request_ip=None)
    runner._resolve_ip_observations(session=db, run=run, request_ip=None)
    runner._check_ip_findings(session=db, run=run, request_ip=None)
    db.add(
        RunStep(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            governance_run_id=run.id,
            step_code="BUILD_REPORT",
            input_hash=run.input_hash,
        )
    )
    db.commit()
    db.refresh(run)
    return run


def _flush_report(
    *, session: Session, run: GovernanceRun, candidate: ReportCandidate
) -> GovernanceReport:
    """Metadata only, in the caller's transaction, before lifecycle publication."""
    artifacts = []
    for extension, media_type, content, content_hash in (
        ("html", "text/html", candidate.rendered.html, candidate.rendered.html_sha256),
        ("csv", "text/csv", candidate.rendered.csv, candidate.rendered.csv_sha256),
    ):
        artifact = Artifact(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            governance_run_id=run.id,
            storage_key=f"reports/{uuid.uuid4()}.{extension}",
            media_type=media_type,
            byte_size=len(content),
            sha256=content_hash,
        )
        session.add(artifact)
        artifacts.append(artifact)
    session.flush()
    report = GovernanceReport(
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        governance_run_id=run.id,
        report_contract_version=candidate.report_contract_version,
        canonical_content=json.loads(candidate.rendered.canonical_json),
        html_artifact_id=artifacts[0].id,
        html_sha256=artifacts[0].sha256,
        csv_artifact_id=artifacts[1].id,
        csv_sha256=artifacts[1].sha256,
    )
    session.add(report)
    session.flush()
    return report


@pytest.mark.parametrize("mode", ["absent", "empty", "active"])
@pytest.mark.parametrize(
    "version", [REPORT_CONTRACT_VERSION, REPORT_V2_CONTRACT_VERSION]
)
def test_fixed_run_can_rebuild_candidate_after_report_flush(
    mode: str,
    version: str,
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
        mode=mode,
        report_contract_version=version,
    )
    facts = read_report_candidate_facts(session=db, **_scope(run))
    candidate = generate_report_candidate(facts, REPORT_V2_CONTRACT_VERSION)
    assert (
        generate_run_report_candidate(
            session=db,
            **_scope(run),
            report_contract_version=REPORT_V2_CONTRACT_VERSION,
        )
        == candidate
    )
    assert runner.pinned_inputs_for_run(run).input_hash() == run.input_hash
    assert run.report_contract_version == version
    assert facts.comparison.results[0].netflow_status == (
        "ACTIVE" if mode == "active" else "UNKNOWN"
    )
    assert (facts.netflow_snapshot is None) == (mode == "absent")
    with db.begin_nested() as transaction:
        stored_candidate = generate_report_candidate(facts, version)
        _flush_report(session=db, run=run, candidate=stored_candidate)
        db.expire_all()
        assert read_report_candidate_facts(session=db, **_scope(run)) == facts
        assert not db.new and not db.dirty and not db.deleted
        with pytest.raises(IPSourceComparisonError, match="run_not_published"):
            read_ip_source_comparison(session=db, **_scope(run))
        transaction.rollback()


def test_fixed_v2_resource_cutoff_and_selection_ignore_unrelated_late_inputs(
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
        mode="active",
    )
    facts = read_report_candidate_facts(session=db, **_scope(run))
    with db.begin_nested() as transaction:
        project = db.get(Project, run.project_id)
        assert project is not None
        project.current_netflow_dataset_id = None
        db.add(project)
        db.add(
            Resource(
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                resource_type="IP",
                canonical_key="198.51.100.20",
            )
        )
        db.flush()
        db.expire_all()
        assert read_report_candidate_facts(session=db, **_scope(run)) == facts
        transaction.rollback()


@pytest.mark.parametrize("drift_after_capture", [False, True])
def test_fresh_v2_read_observes_late_governance_history_and_candidate_time(
    drift_after_capture: bool,
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
    )
    captured = read_report_candidate_facts(session=db, **_scope(run))
    candidate = generate_report_candidate(captured, REPORT_V2_CONTRACT_VERSION)
    with db.begin_nested() as transaction:
        project = db.get(Project, run.project_id)
        assert project is not None
        history = _insert_run(session=db, project=project, status="FAILED_PROCESSING")
        resource = Resource(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            resource_type="IP",
            canonical_key="203.0.113.90",
        )
        db.add(resource)
        db.flush()
        finding = Finding(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            resource_id=resource.id,
            finding_type="UNOBSERVED_ASSET",
            dedupe_key=f"UNOBSERVED_ASSET:{resource.canonical_key}",
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
        history.completed_at = captured.governance.completed_at + timedelta(
            days=1 if drift_after_capture else -1
        )
        db.add(history)
        db.flush()
        db.expire_all()
        fresh = read_report_candidate_facts(session=db, **_scope(run))
        assert fresh.comparison == captured.comparison
        assert fresh.governance != captured.governance
        assert (
            fresh.governance.completed_at > captured.governance.completed_at
        ) == drift_after_capture
        assert generate_report_candidate(fresh, REPORT_V2_CONTRACT_VERSION) != candidate
        with pytest.raises(ReportCandidateError, match="report_candidate_invalid"):
            validate_report_candidate(fresh, candidate)
        transaction.rollback()


@pytest.mark.parametrize(
    "input_version,processing_version,report_version",
    [
        (None, IP_PROCESSING_CONTRACT_VERSION, REPORT_V2_CONTRACT_VERSION),
        (
            "governance-run-input-v1",
            "unsupported-processing",
            REPORT_V2_CONTRACT_VERSION,
        ),
        (
            "governance-run-input-v1",
            IP_PROCESSING_CONTRACT_VERSION,
            "unsupported-report",
        ),
    ],
)
def test_new_run_unsupported_pins_keep_adapter_error_contract(
    input_version: str | None,
    processing_version: str,
    report_version: str,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    valid = _prepare_v2_run(
        client=client,
        headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    with db.begin_nested() as transaction:
        project = db.get(Project, valid.project_id)
        assert project is not None
        invalid = _insert_run(
            session=db,
            project=project,
            status="FAILED_PROCESSING",
            input_contract_version=input_version,
            processing_contract_version=processing_version,
            report_contract_version=report_version,
        )
        with pytest.raises(
            ReportCandidateError, match="comparison_contract_unsupported"
        ):
            read_report_candidate_facts(session=db, **_scope(invalid))
        transaction.rollback()


def test_v2_fresh_read_reopens_fixed_netflow_input_and_preserves_io_errors(
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
        mode="active",
    )
    captured = read_report_candidate_facts(session=db, **_scope(run))
    dataset = db.get(NetFlowDataset, run.netflow_dataset_id)
    assert dataset is not None
    artifact = db.get(Artifact, dataset.raw_artifact_id)
    assert artifact is not None
    path = runner._artifact_path(artifact)
    original = path.read_bytes()
    path.chmod(0o640)
    try:
        path.write_bytes(HEADER)
        with pytest.raises(ReportCandidateError, match="report_facts_invalid"):
            read_report_candidate_facts(session=db, **_scope(run))
    finally:
        path.write_bytes(original)
        path.chmod(0o440)
    assert read_report_candidate_facts(session=db, **_scope(run)) == captured

    unavailable_path = path.with_suffix(".unavailable")
    path.rename(unavailable_path)
    try:
        with pytest.raises(runner.GovernanceRunExecutionError) as failure:
            read_report_candidate_facts(session=db, **_scope(run))
        assert failure.value.code == "netflow_artifact_unavailable"
    finally:
        unavailable_path.rename(path)
