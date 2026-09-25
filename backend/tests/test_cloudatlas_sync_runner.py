import hashlib
import sys
import uuid
from collections.abc import Generator
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app import cloudatlas_sync_runner as runner
from app.core.config import settings
from app.core.db import engine
from app.core.time import get_datetime_utc
from app.domain import external_assets as service
from app.domain.cloudatlas_sources import CloudAtlasFingerprint
from app.domain.external_asset_models import (
    ExternalAssetHead,
    ExternalAssetRecord,
    ExternalAssetVersion,
    ExternalSync,
    ExternalSyncCreate,
)
from app.domain.models import ProjectCreate, SourceInstance
from app.domain.projects import create_project
from app.integrations.agent_compose import (
    AgentComposeClient,
    AgentComposeRunStart,
    AgentComposeSession,
    AgentComposeSessionObservation,
)
from app.integrations.cloudatlas_assets import OctobusCloudAtlasAssetsClient
from app.models import User


@pytest.fixture
def worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[SimpleNamespace]:
    build = tmp_path / "runner-build-version"
    build.write_text("synthetic-build\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_BUILD_VERSION_PATH", str(build))
    monkeypatch.setattr(settings, "GOVERNANCE_RUNNER_BUILD_VERSION", "synthetic-build")
    monkeypatch.setattr(sys, "argv", ["cloudatlas-sync"])
    token = "synthetic-worker-secret"
    monkeypatch.setattr(settings, "CLOUDATLAS_ASSETS_CAPSET_TOKEN", SecretStr(token))

    def no_transport(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("Unexpected external transport in dedicated worker test")

    monkeypatch.setattr(OctobusCloudAtlasAssetsClient, "_request_json", no_transport)
    monkeypatch.setattr(AgentComposeClient, "get_run", no_transport)
    monkeypatch.setattr(AgentComposeClient, "get_session", no_transport)
    monkeypatch.setattr(
        OctobusCloudAtlasAssetsClient,
        "validate_credentials",
        lambda *_args, **_kwargs: CloudAtlasFingerprint("a" * 64),
    )
    with engine.connect() as connection:
        transaction = connection.begin()
        monkeypatch.setattr(
            runner,
            "Session",
            lambda _engine: Session(
                connection, join_transaction_mode="create_savepoint"
            ),
        )
        try:
            with Session(
                connection,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            ) as session:
                actor = session.exec(
                    select(User).where(User.email == settings.FIRST_SUPERUSER)
                ).one()
                state = SimpleNamespace(
                    session=session, actor=actor, token=token, build=build
                )
                yield state
        finally:
            transaction.rollback()


def _reserve(worker: SimpleNamespace) -> tuple[ExternalSync, SourceInstance]:
    session = worker.session
    project = create_project(
        session=session,
        project_in=ProjectCreate(name=f"worker-{uuid.uuid4()}"),
        actor_subject=str(worker.actor.id),
        ip_address=None,
    )
    source = SourceInstance(
        project_id=project.id,
        instance_id="synthetic-assets",
        capset_id="synthetic-capset",
        capability_profile="assets-v1",
        space_id="7",
        enabled=True,
        validated_fingerprint="a" * 64,
        assets_token_sha256=hashlib.sha256(worker.token.encode()).hexdigest(),
    )
    session.add(source)
    session.commit()
    sync, _ = service.reserve_sync(
        session,
        source,
        worker.actor,
        ExternalSyncCreate(
            page_size=1,
            max_pages=2,
            max_records=2,
            max_response_bytes=4096,
            timeout_seconds=60,
            retain_until=get_datetime_utc() + timedelta(hours=1),
        ),
        str(uuid.uuid4()),
    )
    sync.session_id = hashlib.sha256(sync.id.bytes).hexdigest()
    session.add(sync)
    session.commit()
    return sync, source


def _identity(monkeypatch: pytest.MonkeyPatch, sync: ExternalSync) -> None:
    monkeypatch.setenv("EXTERNAL_SYNC_ID", str(sync.id))
    monkeypatch.setenv("EXTERNAL_SYNC_RUN_ID", sync.agent_run_id)
    assert sync.session_id is not None
    monkeypatch.setenv("SANDBOX_ID", sync.session_id)


@pytest.mark.parametrize(
    "invalid",
    ["sync-id", "run-id", "session-id", "build-mismatch", "build-missing", "arguments"],
)
def test_worker_rejects_untrusted_deployment_before_mutating_reservation(
    worker: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    sync, _ = _reserve(worker)
    _identity(monkeypatch, sync)
    if invalid == "sync-id":
        monkeypatch.setenv("EXTERNAL_SYNC_ID", "not-a-uuid")
    elif invalid == "run-id":
        monkeypatch.setenv("EXTERNAL_SYNC_RUN_ID", "A" * 64)
    elif invalid == "session-id":
        monkeypatch.delenv("SANDBOX_ID")
    elif invalid == "build-mismatch":
        worker.build.write_text("another-build", encoding="utf-8")
    elif invalid == "build-missing":
        worker.build.unlink()
    else:
        monkeypatch.setattr(sys, "argv", ["cloudatlas-sync", "--untrusted"])

    assert runner.main() == 1
    worker.session.refresh(sync)
    assert (sync.status, sync.started_at, sync.pages_read, sync.error_code) == (
        "PENDING",
        None,
        0,
        None,
    )
    assert (
        worker.session.exec(
            select(ExternalAssetHead).where(
                ExternalAssetHead.source_id == sync.source_id
            )
        ).all()
        == []
    )


def test_worker_entrypoint_publishes_real_versions_and_does_not_replay_source_calls(
    worker: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    sync, source = _reserve(worker)
    _identity(monkeypatch, sync)
    session_id = sync.session_id
    assert session_id is not None
    monkeypatch.setattr(
        AgentComposeClient,
        "get_run",
        lambda *_args: AgentComposeRunStart(
            run_id=sync.agent_run_id,
            session_id=sync.session_id,
            project_id=sync.agent_project_id,
            agent_name="cloudatlas-sync",
            started=True,
            status="running",
        ),
    )
    monkeypatch.setattr(
        AgentComposeClient,
        "get_session",
        lambda *_args: AgentComposeSession(
            session_id=session_id, observation=AgentComposeSessionObservation.RUNNING
        ),
    )
    calls: list[str] = []

    def page(_self: Any, _source: SourceInstance, **options: Any) -> dict[str, Any]:
        calls.append(options["domain"])
        row: dict[str, Any] = {"id": "9007199254740993", "ip": "2001:0db8::1"}
        row.update({"status": "valid"} if options["domain"] == "ip" else {"port": 443})
        return {"page": 1, "size": 1, "total": 1, "space_id": "7", "items": [row]}

    monkeypatch.setattr(OctobusCloudAtlasAssetsClient, "list_page", page)
    assert runner.main() == 0
    worker.session.refresh(sync)
    assert (sync.status, sync.pages_read, sync.records_read) == ("SUCCEEDED", 2, 2)
    versions = worker.session.exec(
        select(ExternalAssetVersion).where(ExternalAssetVersion.sync_id == sync.id)
    ).all()
    assert {version.domain for version in versions} == {"ip", "port"}
    for version in versions:
        assert (version.status, version.complete, version.record_count) == (
            "PUBLISHED",
            True,
            1,
        )
        head = worker.session.get(ExternalAssetHead, (source.id, version.domain))
        assert head is not None and head.version_id == version.id
        record = worker.session.exec(
            select(ExternalAssetRecord).where(
                ExternalAssetRecord.version_id == version.id
            )
        ).one()
        assert (record.source_id, record.canonical_ip) == (
            "9007199254740993",
            "2001:db8::1",
        )
    worker.session.commit()
    assert runner.main() == 0
    assert calls == ["ip", "port"]


@pytest.mark.parametrize("settled_domain", ["PUBLISHED", "FAILED"])
def test_interruption_marks_only_matching_unfinished_work_unknown_without_leaking(
    worker: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settled_domain: str,
) -> None:
    sync, _ = _reserve(worker)
    unrelated, _ = _reserve(worker)
    versions = worker.session.exec(
        select(ExternalAssetVersion)
        .where(ExternalAssetVersion.sync_id == sync.id)
        .order_by(ExternalAssetVersion.domain)
    ).all()
    unrelated_versions = worker.session.exec(
        select(ExternalAssetVersion).where(ExternalAssetVersion.sync_id == unrelated.id)
    ).all()
    unrelated_before = unrelated.model_dump()
    unrelated_versions_before = [version.model_dump() for version in unrelated_versions]
    versions[0].status = "RUNNING" if settled_domain == "PUBLISHED" else settled_domain
    versions[0].error_code = "existing-error" if settled_domain == "FAILED" else None
    if settled_domain == "PUBLISHED":
        versions[0].complete = True
        versions[0].expected_total = 0
        versions[0].fetched_at = get_datetime_utc()
        versions[0].pages_read = 1
        versions[0].stop_reason = "source_complete"
        worker.session.add(versions[0])
        worker.session.commit()
        versions[0].status = "PUBLISHED"
        versions[0].published_at = get_datetime_utc()
    worker.session.add(versions[0])
    worker.session.commit()
    preserved = versions[0].model_dump()
    _identity(monkeypatch, sync)

    def interrupted(*_args: Any) -> None:
        raise RuntimeError(f"source response and credential: {worker.token}")

    monkeypatch.setattr(service, "execute_sync", interrupted)
    assert runner.main() == 1
    worker.session.refresh(sync)
    for version in versions:
        worker.session.refresh(version)
    worker.session.refresh(unrelated)
    for version in unrelated_versions:
        worker.session.refresh(version)
    assert (sync.status, sync.error_code) == ("UNKNOWN", "external_execution_unknown")
    assert versions[0].model_dump() == preserved
    assert (versions[1].status, versions[1].error_code) == (
        "UNKNOWN",
        "external_execution_unknown",
    )
    assert unrelated.model_dump() == unrelated_before
    assert [
        version.model_dump() for version in unrelated_versions
    ] == unrelated_versions_before
    assert sync.completed_at is None
    output = capsys.readouterr()
    assert worker.token not in output.out + output.err
    assert "source response" not in output.out + output.err
    assert worker.token not in str(sync.model_dump()) + str(versions[1].model_dump())


@pytest.mark.parametrize(
    "identity", ["other-run", "other-session", "completed", "missing"]
)
def test_interruption_cannot_rewrite_an_unowned_or_completed_task(
    worker: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, identity: str
) -> None:
    sync, _ = _reserve(worker)
    if identity == "completed":
        sync.status = "FAILED"
        sync.error_code = "external_record_budget"
        sync.completed_at = get_datetime_utc()
        worker.session.add(sync)
        worker.session.commit()
    _identity(monkeypatch, sync)
    if identity == "other-run":
        monkeypatch.setenv("EXTERNAL_SYNC_RUN_ID", "b" * 64)
    elif identity == "other-session":
        monkeypatch.setenv("SANDBOX_ID", "c" * 64)
    elif identity == "missing":
        monkeypatch.setenv("EXTERNAL_SYNC_ID", str(uuid.uuid4()))
    before = sync.model_dump()
    versions = worker.session.exec(
        select(ExternalAssetVersion).where(ExternalAssetVersion.sync_id == sync.id)
    ).all()
    before_versions = [version.model_dump() for version in versions]
    worker.session.commit()

    def interrupted(*_args: Any) -> None:
        raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(service, "execute_sync", interrupted)
    assert runner.main() == 1
    worker.session.refresh(sync)
    for version in versions:
        worker.session.refresh(version)
    assert sync.model_dump() == before
    assert [version.model_dump() for version in versions] == before_versions


def test_maintenance_rejects_invalid_missing_and_legacy_sources_without_deleting(
    worker: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    expired_clock = get_datetime_utc() - timedelta(hours=2)
    with monkeypatch.context() as clock:
        clock.setattr(service, "get_datetime_utc", lambda: expired_clock)
        clock.setattr(sys.modules[__name__], "get_datetime_utc", lambda: expired_clock)
        sync, source = _reserve(worker)
    legacy = SourceInstance(
        project_id=source.project_id,
        instance_id="synthetic-legacy",
        capset_id="synthetic-legacy-capset",
        capability_profile="legacy-ip-v1",
        enabled=False,
    )
    worker.session.add(legacy)
    version = worker.session.exec(
        select(ExternalAssetVersion).where(
            ExternalAssetVersion.sync_id == sync.id, ExternalAssetVersion.domain == "ip"
        )
    ).one()
    version.status = "RUNNING"
    worker.session.add(version)
    worker.session.flush()
    record = ExternalAssetRecord(
        version_id=version.id,
        source_id="1",
        ip="192.0.2.1",
        canonical_ip="192.0.2.1",
        fields={"id": "1", "ip": "192.0.2.1"},
    )
    worker.session.add(record)
    worker.session.commit()
    for source_id in ("invalid", str(uuid.uuid4()), str(legacy.id)):
        monkeypatch.setattr(
            sys,
            "argv",
            ["cloudatlas-sync", "--purge-expired", "--source-id", source_id],
        )
        assert runner.main() == 1
    worker.session.expire_all()
    assert worker.session.get(ExternalAssetRecord, record.id) is not None


def test_interruption_with_unavailable_recovery_database_stays_redacted_and_reserved(
    worker: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sync, _ = _reserve(worker)
    _identity(monkeypatch, sync)
    before = sync.model_dump()
    attempts = 0

    def session_unavailable_on_recovery(_engine: Any) -> Session:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise SQLAlchemyError(f"database credential: {worker.token}")
        return Session(
            worker.session.get_bind(), join_transaction_mode="create_savepoint"
        )

    def interrupted(*_args: Any) -> None:
        raise RuntimeError(f"source credential: {worker.token}")

    monkeypatch.setattr(runner, "Session", session_unavailable_on_recovery)
    monkeypatch.setattr(service, "execute_sync", interrupted)
    assert runner.main() == 1
    worker.session.refresh(sync)
    assert sync.model_dump() == before
    output = capsys.readouterr()
    assert worker.token not in output.out + output.err
    assert "credential" not in output.out + output.err
