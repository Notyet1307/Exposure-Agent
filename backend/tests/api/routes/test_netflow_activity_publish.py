import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.domain import governance_runs as service
from app.domain.models import (
    Artifact,
    GovernanceRun,
    NetFlowDataset,
    NetFlowIPActivity,
    Project,
    Resource,
)
from app.governance_runner import main as run_runner
from tests.api.routes.test_governance_run_netflow import _prepare_present_run
from tests.api.routes.test_governance_runs import _create_project


def test_activity_publish_is_scoped_batched_atomic_and_retryable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
) -> None:
    historical_ips = [f"2001:db8::{index:x}" for index in range(1, 505)]
    content = (
        "IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
        "::ffff:192.0.2.10,198.51.100.20,6,53000,443\n"
        "198.51.100.20,192.0.2.10,6,443,53000\n"
        "192.0.2.10,192.0.2.10,1,0,2048\n"
        "203.0.113.9,198.51.100.20,6,443,443\n"
        + "".join(f"{ip},192.0.2.10,17,53,50000\n" for ip in historical_ips)
    ).encode()
    project, _, _ = _prepare_present_run(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        content=content,
        trigger_id="activity-publish",
    )
    project_id = uuid.UUID(str(project["id"]))
    stored_project = db.get(Project, project_id)
    assert stored_project is not None
    for ip in historical_ips:
        db.add(
            Resource(
                tenant_id=stored_project.tenant_id,
                project_id=project_id,
                resource_type="IP",
                canonical_key=ip,
            )
        )
    other = _create_project(client, superuser_token_headers)
    db.add(
        Resource(
            tenant_id=stored_project.tenant_id,
            project_id=uuid.UUID(str(other["id"])),
            resource_type="IP",
            canonical_key="203.0.113.9",
        )
    )
    db.commit()
    batches: list[int] = []
    draft_hashes: dict[uuid.UUID, str] = {}

    def trace_flush(session: Session, *_args: object) -> None:
        facts = [item for item in session.new if isinstance(item, NetFlowIPActivity)]
        if facts:
            batches.append(len(facts))
            draft_hashes.update({item.id: item.content_sha256 for item in facts})

    original = service._report_publication_records

    def fail_after_activity(**_kwargs: object) -> None:
        raise SQLAlchemyError("injected publish failure")

    event.listen(Session, "before_flush", trace_flush)
    try:
        monkeypatch.setattr(service, "_report_publication_records", fail_after_activity)
        assert run_runner() == 1
        run = db.exec(
            select(GovernanceRun).where(GovernanceRun.project_id == project_id)
        ).one()
        assert run.status == "FAILED_PROCESSING"
        assert (
            db.exec(
                select(NetFlowIPActivity).where(
                    NetFlowIPActivity.governance_run_id == run.id
                )
            ).all()
            == []
        )
        db.refresh(stored_project)
        assert stored_project.latest_completed_run_id is None
        assert batches == [500, 5]
        first_hashes = dict(draft_hashes)
        monkeypatch.setattr(service, "_report_publication_records", original)
        service.prepare_retry(
            session=db, run=run, actor_subject="test-admin", request_ip=None
        )
        assert run_runner() == 0
        db.refresh(run)
        assert run.status == "COMPLETED"
        facts = db.exec(
            select(NetFlowIPActivity).where(
                NetFlowIPActivity.governance_run_id == run.id
            )
        ).all()
        assert {item.id: item.content_sha256 for item in facts} == first_hashes
        assert batches == [500, 5, 500, 5]
        resources = db.exec(
            select(Resource).where(Resource.project_id == project_id)
        ).all()
        by_id = {item.id: str(item.canonical_key) for item in resources}
        assert set(by_id.values()) == {"192.0.2.10", *historical_ips}
        assert {by_id[item.resource_id] for item in facts} == set(by_id.values())
        current = next(
            item for item in facts if by_id[item.resource_id] == "192.0.2.10"
        )
        assert current.flow_count == 507
        assert current.protocols == [1, 6, 17]
        assert "192.0.2.10" not in {str(ip) for ip in current.peer_ips}
        assert "198.51.100.20" in {str(ip) for ip in current.peer_ips}
        assert run_runner() == 0
        assert batches == [500, 5, 500, 5]
        with pytest.raises(SQLAlchemyError), db.begin_nested():
            current.flow_count += 1
            db.flush()
    finally:
        event.remove(Session, "before_flush", trace_flush)


@pytest.mark.parametrize("timing", ["before_publish", "after_resolution"])
def test_normalized_drift_cannot_publish_activity(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    db: Session,
    timing: str,
) -> None:
    project, dataset, _ = _prepare_present_run(
        client=client,
        headers=superuser_token_headers,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        content=b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n192.0.2.10,198.51.100.20,6,443,53000\n",
        trigger_id=f"normalized-drift-{timing}",
    )
    stored = db.get(NetFlowDataset, uuid.UUID(str(dataset["id"])))
    assert stored is not None
    artifact = db.get(Artifact, stored.normalized_artifact_id)
    assert artifact is not None
    target = tmp_path / artifact.storage_key
    hook = (
        "_validate_report_candidate"
        if timing == "before_publish"
        else "_resolve_ip_observations"
    )
    original = getattr(service, hook)

    def tamper(**kwargs: object) -> None:
        original(**kwargs)
        target.chmod(0o640)
        target.write_bytes(target.read_bytes() + b"\n")

    monkeypatch.setattr(service, hook, tamper)
    assert run_runner() == 1
    run = db.exec(
        select(GovernanceRun).where(
            GovernanceRun.project_id == uuid.UUID(str(project["id"]))
        )
    ).one()
    assert run.status == "FAILED_DATA"
    assert (
        db.exec(
            select(NetFlowIPActivity).where(
                NetFlowIPActivity.governance_run_id == run.id
            )
        ).all()
        == []
    )
