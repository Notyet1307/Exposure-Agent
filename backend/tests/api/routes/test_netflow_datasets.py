import hashlib
import stat
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from app.core.config import settings
from app.domain.models import (
    Artifact,
    AuditEvent,
    GovernanceRun,
    NetFlowDataset,
    Project,
    RunStep,
    SourceSnapshot,
)
from app.main import app
from tests.utils.audit import reject_audit_inserts
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _project(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=headers,
        json={"name": f"NetFlow {uuid.uuid4()}"},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def _member(
    client: TestClient, admin: dict[str, str], project_id: object, roles: list[str]
) -> dict[str, str]:
    email, password = random_email(), random_lower_string()
    user = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=admin,
        json={"email": email, "password": password},
    )
    assert user.status_code == 200
    membership = client.post(
        f"{settings.API_V1_STR}/projects/{project_id}/memberships/",
        headers=admin,
        json={"user_id": user.json()["id"], "roles": roles},
    )
    assert membership.status_code == 201
    return user_authentication_headers(client=client, email=email, password=password)


def _csv() -> bytes:
    return (
        b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
        b"198.51.100.20,192.0.2.10,6,53000,443\n"
    )


def _upload(
    client: TestClient,
    headers: dict[str, str],
    project_id: object,
    content: bytes,
    filename: str = "flows.csv",
) -> Any:
    return client.post(
        f"{settings.API_V1_STR}/projects/{project_id}/netflow-datasets",
        headers=headers,
        files={"file": (filename, content, "text/csv")},
    )


def test_netflow_post_is_idempotent_scoped_and_does_not_select_or_create_run(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    content = _csv()
    first_project = _project(client, superuser_token_headers)
    third_project = _project(client, superuser_token_headers)
    second_project = _project(client, superuser_token_headers)
    before = db.exec(
        select(Project).where(Project.id == uuid.UUID(str(first_project["id"])))
    ).one()
    first = _upload(client, superuser_token_headers, first_project["id"], content)
    assert first.status_code == 201, first.text
    replay = _upload(client, superuser_token_headers, first_project["id"], content)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first.json()["id"]
    other = _upload(client, superuser_token_headers, second_project["id"], content)
    assert other.status_code == 201, other.text
    assert other.json()["id"] != first.json()["id"]
    project_ids = {
        uuid.UUID(str(first_project["id"])),
        uuid.UUID(str(second_project["id"])),
    }
    datasets = db.exec(
        select(NetFlowDataset).where(col(NetFlowDataset.project_id).in_(project_ids))
    ).all()
    assert len(datasets) == 2
    for payload in (first.json(), other.json()):
        dataset = db.exec(
            select(NetFlowDataset).where(NetFlowDataset.id == uuid.UUID(payload["id"]))
        ).one()
        artifacts = db.exec(
            select(Artifact).where(Artifact.project_id == dataset.project_id)
        ).all()
        by_hash = {artifact.sha256: artifact for artifact in artifacts}
        raw_artifact = by_hash[dataset.raw_sha256]
        normalized_artifact = by_hash[dataset.normalized_sha256]
        for artifact in (raw_artifact, normalized_artifact):
            artifact_path = tmp_path / artifact.storage_key
            assert artifact.project_id == dataset.project_id
            assert artifact_path.is_file()
            assert stat.S_IMODE(artifact_path.stat().st_mode) == 0o440
            assert artifact.byte_size == artifact_path.stat().st_size
            assert (
                hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                == artifact.sha256
            )
        assert raw_artifact.id != normalized_artifact.id
    first_dataset = db.exec(
        select(NetFlowDataset).where(NetFlowDataset.id == uuid.UUID(first.json()["id"]))
    ).one()
    first_raw = db.get(Artifact, first_dataset.raw_artifact_id)
    assert first_raw is not None
    first_dataset.display_filename = "changed.csv"
    with pytest.raises(SQLAlchemyError):
        db.commit()
    db.rollback()
    first_raw = db.get(Artifact, first_dataset.raw_artifact_id)
    assert first_raw is not None
    db.delete(first_raw)
    with pytest.raises(SQLAlchemyError):
        db.commit()
    db.rollback()
    first_normalized = db.get(Artifact, first_dataset.normalized_artifact_id)
    assert first_normalized is not None
    db.delete(first_normalized)
    with pytest.raises(SQLAlchemyError):
        db.commit()
    db.rollback()
    duplicate = NetFlowDataset(**first_dataset.model_dump())
    duplicate.id = uuid.uuid4()
    db.add(duplicate)
    with pytest.raises(SQLAlchemyError):
        db.commit()
    db.rollback()
    cross_scope = NetFlowDataset(**first_dataset.model_dump())
    cross_scope.id = uuid.uuid4()
    cross_scope.project_id = uuid.UUID(str(third_project["id"]))
    db.add(cross_scope)
    with pytest.raises(SQLAlchemyError):
        db.commit()
    db.rollback()
    source_artifacts = db.exec(
        select(Artifact).where(Artifact.project_id == first_dataset.project_id)
    ).all()
    constraint_artifacts: list[Artifact] = []
    for source, digest in zip(source_artifacts, ("b" * 64, "c" * 64), strict=True):
        artifact = Artifact(**source.model_dump())
        artifact.id = uuid.uuid4()
        artifact.project_id = uuid.UUID(str(third_project["id"]))
        artifact.storage_key = f"constraint/{artifact.id}"
        artifact.sha256 = digest
        constraint_artifacts.append(artifact)
        db.add(artifact)
    db.commit()
    invalid_counts = NetFlowDataset(**first_dataset.model_dump())
    invalid_counts.id = uuid.uuid4()
    invalid_counts.project_id = uuid.UUID(str(third_project["id"]))
    invalid_counts.raw_artifact_id = constraint_artifacts[0].id
    invalid_counts.normalized_artifact_id = constraint_artifacts[1].id
    invalid_counts.raw_sha256 = constraint_artifacts[0].sha256
    invalid_counts.normalized_sha256 = constraint_artifacts[1].sha256
    invalid_counts.raw_record_count = -1
    invalid_counts.activity_valid_record_count = -1
    invalid_counts.isolated_record_count = 0
    db.add(invalid_counts)
    with pytest.raises(SQLAlchemyError):
        db.commit()
    db.rollback()
    hash_mismatch = NetFlowDataset(**invalid_counts.model_dump())
    hash_mismatch.id = uuid.uuid4()
    hash_mismatch.raw_record_count = 1
    hash_mismatch.activity_valid_record_count = 1
    hash_mismatch.raw_sha256 = "d" * 64
    db.add(hash_mismatch)
    with pytest.raises(SQLAlchemyError):
        db.commit()
    db.rollback()
    invalid_encoding = NetFlowDataset(**hash_mismatch.model_dump())
    invalid_encoding.id = uuid.uuid4()
    invalid_encoding.raw_sha256 = constraint_artifacts[0].sha256
    invalid_encoding.encoding = "latin-1"
    db.add(invalid_encoding)
    with pytest.raises(SQLAlchemyError):
        db.commit()
    db.rollback()
    inconsistent_counts = NetFlowDataset(**invalid_encoding.model_dump())
    inconsistent_counts.id = uuid.uuid4()
    inconsistent_counts.encoding = "utf-8-sig"
    inconsistent_counts.raw_record_count = 2
    inconsistent_counts.activity_valid_record_count = 1
    inconsistent_counts.isolated_record_count = 0
    db.add(inconsistent_counts)
    with pytest.raises(SQLAlchemyError):
        db.commit()
    db.rollback()
    accepted_events = db.exec(
        select(AuditEvent).where(AuditEvent.action == "netflow_dataset.accepted")
    ).all()
    assert len(accepted_events) == 2
    assert set(cast(dict[str, Any], accepted_events[0].after_data)) == {
        "dataset_contract_version",
        "raw_sha256",
        "normalized_sha256",
        "raw_record_count",
        "activity_valid_record_count",
        "isolated_record_count",
        "warning_count",
    }
    assert all(
        b"198.51.100.20" not in str(event.after_data).encode()
        for event in accepted_events
    )
    assert not db.exec(
        select(GovernanceRun).where(col(GovernanceRun.project_id).in_(project_ids))
    ).all()
    assert not db.exec(
        select(RunStep).where(col(RunStep.project_id).in_(project_ids))
    ).all()
    assert not db.exec(
        select(SourceSnapshot).where(col(SourceSnapshot.project_id).in_(project_ids))
    ).all()
    after = db.exec(select(Project).where(Project.id == before.id)).one()
    assert after.current_customer_upload_id == before.current_customer_upload_id
    assert not db.exec(
        select(AuditEvent).where(AuditEvent.action == "governance_run.created")
    ).all()
    assert first.json()["raw_sha256"] == hashlib.sha256(content).hexdigest()
    assert (
        b"198.51.100.20"
        not in str(
            db.exec(
                select(AuditEvent).where(
                    AuditEvent.target_id == uuid.UUID(first.json()["id"])
                )
            ).all()
        ).encode()
    )


def test_netflow_post_returns_stable_sanitized_boundary_errors(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "NETFLOW_MAX_BYTES", 64)
    project = _project(client, superuser_token_headers)
    project_id = uuid.UUID(str(project["id"]))
    cases = [
        (b"", "netflow_missing_header", "flows.csv"),
        (b"x", "netflow_unsupported_type", "flows.xlsx"),
        (b"x" * 65, "netflow_too_large", "flows.csv"),
    ]
    for content, code, filename in cases:
        response = _upload(
            client, superuser_token_headers, project["id"], content, filename
        )
        assert response.status_code in {400, 413, 415, 422}
        assert response.json()["detail"]["code"] == code
        if content:
            assert content[:8] not in response.content
        assert str(tmp_path) not in response.text
        assert not db.exec(
            select(NetFlowDataset).where(NetFlowDataset.project_id == project_id)
        ).all()
        assert not db.exec(
            select(Artifact).where(Artifact.project_id == project_id)
        ).all()
        assert not db.exec(
            select(AuditEvent).where(
                AuditEvent.project_id == project_id,
                AuditEvent.action == "netflow_dataset.accepted",
            )
        ).all()
        assert not list((tmp_path / "netflow_datasets").glob("*"))


def test_netflow_post_supports_txt_and_rejects_incomplete_or_multiple_parts(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _project(client, superuser_token_headers)
    txt = _upload(client, superuser_token_headers, project["id"], _csv(), "flows.TXT")
    assert txt.status_code == 201, txt.text
    rejection_project = _project(client, superuser_token_headers)
    rejection_root = tmp_path / "rejected"
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", rejection_root)
    url = f"{settings.API_V1_STR}/projects/{rejection_project['id']}/netflow-datasets"
    incomplete = client.post(
        url, headers=superuser_token_headers, data={"not_file": "x"}
    )
    assert incomplete.status_code == 400
    assert incomplete.json()["detail"]["code"] == "netflow_incomplete_upload"
    multiple = client.post(
        url,
        headers=superuser_token_headers,
        files=[
            ("file", ("one.csv", _csv(), "text/csv")),
            ("file", ("two.csv", _csv(), "text/csv")),
        ],
    )
    assert multiple.status_code == 400
    assert multiple.json()["detail"]["code"] == "netflow_incomplete_upload"
    rejection_project_id = uuid.UUID(str(rejection_project["id"]))
    assert not db.exec(
        select(NetFlowDataset).where(NetFlowDataset.project_id == rejection_project_id)
    ).all()
    assert not db.exec(
        select(Artifact).where(Artifact.project_id == rejection_project_id)
    ).all()
    assert not db.exec(
        select(AuditEvent).where(
            AuditEvent.project_id == rejection_project_id,
            AuditEvent.action == "netflow_dataset.accepted",
        )
    ).all()
    assert not list((rejection_root / "netflow_datasets").glob("*"))


def test_netflow_post_concurrent_replay_has_one_winner(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _project(client, superuser_token_headers)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda _: _upload(
                    client, superuser_token_headers, project["id"], _csv()
                ),
                range(2),
            )
        )
    assert {response.status_code for response in responses} == {200, 201}
    project_id = uuid.UUID(str(project["id"]))
    assert (
        len(
            db.exec(
                select(NetFlowDataset).where(NetFlowDataset.project_id == project_id)
            ).all()
        )
        == 1
    )
    assert (
        len(db.exec(select(Artifact).where(Artifact.project_id == project_id)).all())
        == 2
    )
    assert (
        len(
            db.exec(
                select(AuditEvent).where(
                    AuditEvent.project_id == project_id,
                    AuditEvent.action == "netflow_dataset.accepted",
                )
            ).all()
        )
        == 1
    )
    assert len(list((tmp_path / "netflow_datasets").iterdir())) == 2


def test_netflow_post_rejects_archived_project_without_side_effect(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _project(client, superuser_token_headers)
    archive = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/archive",
        headers=superuser_token_headers,
    )
    assert archive.status_code == 200, archive.text
    response = _upload(client, superuser_token_headers, project["id"], _csv())
    assert response.status_code == 409
    assert response.json()["detail"] == "Archived project is read-only"
    assert not db.exec(
        select(NetFlowDataset).where(
            NetFlowDataset.project_id == uuid.UUID(str(project["id"]))
        )
    ).all()


def test_netflow_upload_is_operator_only_and_project_scoped(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    own = _project(client, superuser_token_headers)
    other = _project(client, superuser_token_headers)
    operator = _member(client, superuser_token_headers, own["id"], ["operator"])
    viewer = _member(client, superuser_token_headers, own["id"], ["viewer"])
    allowed = _upload(client, operator, own["id"], _csv())
    denied_role = _upload(client, viewer, own["id"], _csv())
    denied_scope = _upload(client, operator, other["id"], _csv())
    assert allowed.status_code == 201
    assert denied_role.status_code == 404
    assert denied_scope.status_code == 404
    assert not db.exec(
        select(NetFlowDataset).where(
            NetFlowDataset.project_id == uuid.UUID(str(other["id"]))
        )
    ).all()


def test_netflow_audit_failure_compensates_database_and_files(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _project(client, superuser_token_headers)
    project_id = uuid.UUID(str(project["id"]))
    with reject_audit_inserts(db):
        with TestClient(app, raise_server_exceptions=False) as failure_client:
            response = _upload(
                failure_client, superuser_token_headers, project["id"], _csv()
            )
        assert response.status_code == 500
        assert response.json()["detail"]["code"] == "netflow_storage_failed"
    assert not db.exec(
        select(NetFlowDataset).where(NetFlowDataset.project_id == project_id)
    ).all()
    assert not db.exec(select(Artifact).where(Artifact.project_id == project_id)).all()
    assert not db.exec(
        select(AuditEvent).where(
            AuditEvent.project_id == project_id,
            AuditEvent.action == "netflow_dataset.accepted",
        )
    ).all()
    assert not list((tmp_path / "netflow_datasets").glob("*"))
