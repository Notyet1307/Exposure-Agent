import asyncio
import hashlib
import io
import logging
import os
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier, Lock
from typing import NoReturn, cast

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook  # type: ignore[import-untyped]
from pytest import LogCaptureFixture, MonkeyPatch
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, func, select
from starlette.requests import Request
from starlette.types import Message, Scope

from app.core.config import settings
from app.core.db import engine
from app.domain import customer_uploads as customer_upload_service
from app.domain.models import (
    Artifact,
    AuditEvent,
    CustomerUpload,
    GovernanceRun,
    Project,
    SourceInstance,
    SourceSnapshot,
)
from app.main import app
from tests.utils.audit import reject_audit_inserts
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

REQUIRED_HEADERS = ["资产IP", "起始端口", "结束端口", "是否web界面", "web界面url"]
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _workbook_bytes(*, asset_ip: str = "192.0.2.10", formula: bool = False) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(REQUIRED_HEADERS)
    worksheet.append(
        [asset_ip, 443, 443, "是", "=HYPERLINK(\"https://example.test\")" if formula else "example.test"]
    )
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _create_project(
    client: TestClient, headers: dict[str, str], *, name: str | None = None
) -> dict[str, object]:
    response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=headers,
        json={"name": name or f"Upload Project {uuid.uuid4()}"},
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def _create_member(
    client: TestClient,
    admin_headers: dict[str, str],
    *,
    project_id: object,
    roles: list[str],
) -> dict[str, str]:
    email = random_email()
    password = random_lower_string()
    user_response = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=admin_headers,
        json={"email": email, "password": password},
    )
    assert user_response.status_code == 200
    membership_response = client.post(
        f"{settings.API_V1_STR}/projects/{project_id}/memberships/",
        headers=admin_headers,
        json={"user_id": user_response.json()["id"], "roles": roles},
    )
    assert membership_response.status_code == 201
    return user_authentication_headers(client=client, email=email, password=password)


@contextmanager
def _reject_customer_upload_inserts(db: Session) -> Iterator[None]:
    db.execute(
        text(
            """
            CREATE FUNCTION fail_test_customer_upload_insert()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'test customer upload insert failure';
            END;
            $$
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TRIGGER fail_test_customer_upload_insert
            BEFORE INSERT ON customer_uploads
            FOR EACH ROW EXECUTE FUNCTION fail_test_customer_upload_insert()
            """
        )
    )
    db.commit()
    try:
        yield
    finally:
        db.rollback()
        db.execute(
            text(
                "DROP TRIGGER IF EXISTS fail_test_customer_upload_insert "
                "ON customer_uploads"
            )
        )
        db.execute(text("DROP FUNCTION IF EXISTS fail_test_customer_upload_insert()"))
        db.commit()


@contextmanager
def _synchronize_first_customer_upload_reads() -> Iterator[None]:
    barrier = Barrier(2)
    counter_lock = Lock()
    read_count = 0

    def synchronize_customer_upload_select(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal read_count
        if not (
            statement.lstrip().startswith("SELECT")
            and "FROM customer_uploads" in statement
        ):
            return
        with counter_lock:
            read_count += 1
            should_wait = read_count <= 2
        if should_wait:
            barrier.wait(timeout=5)

    event.listen(engine, "before_cursor_execute", synchronize_customer_upload_select)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_customer_upload_select)


@contextmanager
def _reject_customer_upload_reads() -> Iterator[None]:
    def reject_customer_upload_select(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if (
            statement.lstrip().startswith("SELECT")
            and "FROM customer_uploads" in statement
        ):
            raise SQLAlchemyError("test customer upload read failure")

    event.listen(engine, "before_cursor_execute", reject_customer_upload_select)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", reject_customer_upload_select)


def test_admin_can_accept_and_list_an_immutable_customer_upload(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    content = _workbook_bytes()

    create_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", content, XLSX_MEDIA_TYPE)},
    )

    assert create_response.status_code == 201, create_response.text
    upload = create_response.json()
    assert set(upload) == {
        "id",
        "display_filename",
        "raw_sha256",
        "record_count",
        "profile_id",
        "profile_version",
        "warnings",
        "created_at",
    }
    assert uuid.UUID(upload["id"])
    assert upload["display_filename"] == "customer.xlsx"
    assert upload["raw_sha256"] == hashlib.sha256(content).hexdigest()
    assert upload["record_count"] == 1
    assert uuid.UUID(upload["profile_id"])
    assert upload["profile_version"] == 1
    assert upload["warnings"] == [
        {"code": "missing_responsibility_value", "field": field, "count": 1}
        for field in [
            "service_type",
            "asset_owner",
            "asset_department",
            "port_owner",
            "department",
        ]
    ]
    assert upload["created_at"]
    assert "artifact" not in upload
    assert str(tmp_path) not in create_response.text

    list_response = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=superuser_token_headers,
    )
    assert list_response.status_code == 200
    assert list_response.json() == {
        "data": [upload],
        "count": 1,
        "current_customer_upload_id": None,
        "can_upload": True,
        "can_select": True,
    }
    artifacts = list((tmp_path / "customer_uploads").glob("*.xlsx"))
    assert len(artifacts) == 1
    assert artifacts[0].name != "customer.xlsx"
    assert artifacts[0].read_bytes() == content


def test_admin_selects_current_upload_and_list_reports_selection(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    uploads_url = (
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads"
    )
    upload_response = client.post(
        uploads_url,
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    )
    assert upload_response.status_code == 201
    upload = upload_response.json()

    initial_list_response = client.get(
        uploads_url, headers=superuser_token_headers
    )
    assert initial_list_response.status_code == 200
    assert initial_list_response.json()["current_customer_upload_id"] is None
    assert initial_list_response.json()["can_select"] is True

    select_response = client.post(
        f"{uploads_url}/{upload['id']}/select",
        headers=superuser_token_headers,
    )

    assert select_response.status_code == 200
    assert select_response.json() == upload
    selected_list_response = client.get(
        uploads_url, headers=superuser_token_headers
    )
    assert selected_list_response.status_code == 200
    assert (
        selected_list_response.json()["current_customer_upload_id"] == upload["id"]
    )
    db.expire_all()
    audit_event = db.exec(
        select(AuditEvent).where(
            AuditEvent.project_id == uuid.UUID(str(project["id"])),
            AuditEvent.action == "customer_upload.selected",
        )
    ).one()
    assert audit_event.target_type == "customer_upload"
    assert audit_event.target_id == uuid.UUID(upload["id"])
    assert audit_event.before_data == {"current_customer_upload_id": None}
    assert audit_event.after_data == {"current_customer_upload_id": upload["id"]}


def test_operator_can_select_but_viewer_and_approver_cannot(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    uploads_url = (
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads"
    )
    upload_response = client.post(
        uploads_url,
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    )
    upload_id = upload_response.json()["id"]
    operator_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["operator"],
    )
    read_only_headers = [
        _create_member(
            client,
            superuser_token_headers,
            project_id=project["id"],
            roles=[role],
        )
        for role in ("viewer", "approver")
    ]

    select_url = f"{uploads_url}/{upload_id}/select"
    operator_response = client.post(select_url, headers=operator_headers)
    read_only_responses = [
        client.post(select_url, headers=headers) for headers in read_only_headers
    ]

    assert operator_response.status_code == 200
    assert [response.status_code for response in read_only_responses] == [404, 404]
    operator_list_response = client.get(uploads_url, headers=operator_headers)
    assert operator_list_response.status_code == 200
    assert operator_list_response.json()["can_select"] is True
    db.expire_all()
    project_record = db.get(Project, uuid.UUID(str(project["id"])))
    assert project_record is not None
    assert project_record.current_customer_upload_id == uuid.UUID(upload_id)
    assert db.exec(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.project_id == project_record.id,
            AuditEvent.action == "customer_upload.selected",
        )
    ).one() == 1


def test_cross_project_missing_and_archived_selection_do_not_change_pointer(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    other_project = _create_project(client, superuser_token_headers)
    uploads_url = (
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads"
    )
    own_upload = client.post(
        uploads_url,
        headers=superuser_token_headers,
        files={"file": ("own.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    ).json()
    other_upload = client.post(
        f"{settings.API_V1_STR}/projects/{other_project['id']}/customer-uploads",
        headers=superuser_token_headers,
        files={
            "file": (
                "other.xlsx",
                _workbook_bytes(asset_ip="192.0.2.20"),
                XLSX_MEDIA_TYPE,
            )
        },
    ).json()
    assert client.post(
        f"{uploads_url}/{own_upload['id']}/select",
        headers=superuser_token_headers,
    ).status_code == 200

    cross_project_response = client.post(
        f"{uploads_url}/{other_upload['id']}/select",
        headers=superuser_token_headers,
    )
    missing_response = client.post(
        f"{uploads_url}/{uuid.uuid4()}/select",
        headers=superuser_token_headers,
    )
    archive_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/archive",
        headers=superuser_token_headers,
    )
    archived_response = client.post(
        f"{uploads_url}/{own_upload['id']}/select",
        headers=superuser_token_headers,
    )

    assert cross_project_response.status_code == 404
    assert missing_response.status_code == 404
    assert archive_response.status_code == 200
    assert archived_response.status_code == 409
    db.expire_all()
    project_record = db.get(Project, uuid.UUID(str(project["id"])))
    assert project_record is not None
    assert project_record.current_customer_upload_id == uuid.UUID(own_upload["id"])
    assert db.exec(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.project_id == project_record.id,
            AuditEvent.action == "customer_upload.selected",
        )
    ).one() == 1


def test_repeated_selection_is_idempotent_without_duplicate_audit(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    uploads_url = (
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads"
    )
    upload = client.post(
        uploads_url,
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    ).json()
    select_url = f"{uploads_url}/{upload['id']}/select"

    first_response = client.post(select_url, headers=superuser_token_headers)
    repeated_response = client.post(select_url, headers=superuser_token_headers)

    assert first_response.status_code == 200
    assert repeated_response.status_code == 200
    assert repeated_response.json() == first_response.json()
    db.expire_all()
    assert db.exec(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.project_id == uuid.UUID(str(project["id"])),
            AuditEvent.action == "customer_upload.selected",
        )
    ).one() == 1


def test_selection_rolls_back_when_audit_insert_fails(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    uploads_url = (
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads"
    )
    upload = client.post(
        uploads_url,
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    ).json()
    audit_count = db.exec(select(func.count()).select_from(AuditEvent)).one()

    with reject_audit_inserts(db):
        with TestClient(
            app,
            raise_server_exceptions=False,
            client=("127.0.0.1", 50102),
        ) as failure_client:
            response = failure_client.post(
                f"{uploads_url}/{upload['id']}/select",
                headers=superuser_token_headers,
            )
        assert response.status_code == 500

    db.expire_all()
    project_record = db.get(Project, uuid.UUID(str(project["id"])))
    assert project_record is not None
    assert project_record.current_customer_upload_id is None
    assert db.exec(select(func.count()).select_from(AuditEvent)).one() == audit_count


def test_repeated_upload_returns_existing_record_without_duplicate_side_effects(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    content = _workbook_bytes()
    url = f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads"

    first_response = client.post(
        url,
        headers=superuser_token_headers,
        files={"file": ("first.xlsx", content, XLSX_MEDIA_TYPE)},
    )
    repeated_response = client.post(
        url,
        headers=superuser_token_headers,
        files={"file": ("second.xlsx", content, XLSX_MEDIA_TYPE)},
    )

    assert first_response.status_code == 201
    assert repeated_response.status_code == 200
    assert repeated_response.json() == first_response.json()
    db.expire_all()
    project_id = uuid.UUID(str(project["id"]))
    assert db.exec(
        select(func.count())
        .select_from(CustomerUpload)
        .where(CustomerUpload.project_id == project_id)
    ).one() == 1
    assert db.exec(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.project_id == project_id,
            AuditEvent.action == "customer_upload.accepted",
        )
    ).one() == 1
    assert len(list((tmp_path / "customer_uploads").glob("*.xlsx"))) == 1


def test_concurrent_uploads_are_idempotent(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    content = _workbook_bytes()
    url = f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads"

    def upload(concurrent_client: TestClient) -> tuple[int, dict[str, object]]:
        response = concurrent_client.post(
            url,
            headers=superuser_token_headers,
            files={"file": ("concurrent.xlsx", content, XLSX_MEDIA_TYPE)},
        )
        return response.status_code, response.json()

    with (
        TestClient(app, client=("127.0.0.1", 50100)) as first_client,
        TestClient(app, client=("127.0.0.1", 50101)) as second_client,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        results = list(executor.map(upload, (first_client, second_client)))

    assert sorted(status_code for status_code, _body in results) == [200, 201]
    assert results[0][1] == results[1][1]
    assert len(list((tmp_path / "customer_uploads").glob("*.xlsx"))) == 1


def test_forced_concurrent_acceptance_returns_the_winner(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    project_data = _create_project(client, superuser_token_headers)
    project_id = uuid.UUID(str(project_data["id"]))
    content = _workbook_bytes()
    upload_directory = tmp_path / "customer_uploads"
    upload_directory.mkdir()

    def accept(index: int) -> tuple[uuid.UUID, bool]:
        temporary_path = upload_directory / f".{index}.tmp.xlsx"
        temporary_path.write_bytes(content)
        streamed_upload = customer_upload_service.StreamedCustomerUpload(
            temporary_path=temporary_path,
            display_filename="concurrent.xlsx",
            byte_size=len(content),
            raw_sha256=hashlib.sha256(content).hexdigest(),
        )
        with Session(engine) as session:
            project = session.get(Project, project_id)
            assert project is not None
            upload, created = customer_upload_service.accept_customer_upload(
                session=session,
                project=project,
                streamed_upload=streamed_upload,
                artifact_root=tmp_path,
                actor_subject=str(uuid.uuid4()),
                ip_address="127.0.0.1",
            )
            return upload.id, created

    with (
        _synchronize_first_customer_upload_reads(),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        results = list(executor.map(accept, range(2)))

    assert sorted(created for _upload_id, created in results) == [False, True]
    assert results[0][0] == results[1][0]
    assert len(list(upload_directory.glob("*.xlsx"))) == 1
    assert not list(upload_directory.glob("*.tmp.xlsx"))


@pytest.mark.parametrize("role", ["viewer", "approver"])
def test_non_operator_cannot_upload_but_can_list_with_can_upload_false(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    role: str,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    member_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=[role],
    )

    upload_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=member_headers,
        files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    )
    list_response = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=member_headers,
    )

    assert upload_response.status_code == 404
    assert list_response.status_code == 200
    assert list_response.json() == {
        "data": [],
        "count": 0,
        "current_customer_upload_id": None,
        "can_upload": False,
        "can_select": False,
    }


def test_operator_can_upload_only_to_own_active_project(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    allowed_project = _create_project(client, superuser_token_headers)
    hidden_project = _create_project(client, superuser_token_headers)
    operator_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=allowed_project["id"],
        roles=["operator"],
    )
    content = _workbook_bytes()

    allowed_response = client.post(
        f"{settings.API_V1_STR}/projects/{allowed_project['id']}/customer-uploads",
        headers=operator_headers,
        files={"file": ("customer.xlsx", content, XLSX_MEDIA_TYPE)},
    )
    hidden_response = client.post(
        f"{settings.API_V1_STR}/projects/{hidden_project['id']}/customer-uploads",
        headers=operator_headers,
        files={"file": ("customer.xlsx", content, XLSX_MEDIA_TYPE)},
    )

    assert allowed_response.status_code == 201
    assert hidden_response.status_code == 404


def test_archived_project_is_readable_but_cannot_accept_uploads(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    archive_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/archive",
        headers=superuser_token_headers,
    )
    assert archive_response.status_code == 200

    upload_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    )
    list_response = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=superuser_token_headers,
    )

    assert upload_response.status_code == 409
    assert list_response.status_code == 200
    assert list_response.json() == {
        "data": [],
        "count": 0,
        "current_customer_upload_id": None,
        "can_upload": False,
        "can_select": False,
    }


@pytest.mark.parametrize(
    ("filename", "content", "expected_status", "expected_code"),
    [
        ("customer.csv", b"not,xlsx", 415, "unsupported_workbook_type"),
        ("customer.xlsx", b"not an xlsx", 415, "unsupported_workbook_type"),
        (
            "customer.xlsx",
            b"x" * (20 * 1024 * 1024 + 1),
            413,
            "upload_too_large",
        ),
    ],
)
def test_upload_transport_rejections_are_stable_and_leave_no_records(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    filename: str,
    content: bytes,
    expected_status: int,
    expected_code: str,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    project_id = uuid.UUID(str(project["id"]))
    audit_count = db.exec(select(func.count()).select_from(AuditEvent)).one()

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=superuser_token_headers,
        files={"file": (filename, content, "application/octet-stream")},
    )

    assert response.status_code == expected_status
    assert response.json()["detail"] == {
        "code": expected_code,
        "message": {
            "unsupported_workbook_type": "Only XLSX workbooks are supported.",
            "upload_too_large": "The upload exceeds the allowed size.",
        }[expected_code],
    }
    assert filename not in response.text
    assert str(tmp_path) not in response.text
    db.expire_all()
    assert db.exec(
        select(func.count())
        .select_from(CustomerUpload)
        .where(CustomerUpload.project_id == project_id)
    ).one() == 0
    assert db.exec(select(func.count()).select_from(AuditEvent)).one() == audit_count
    assert not list((tmp_path / "customer_uploads").glob("*"))


def test_valid_upload_streams_without_framework_spooling(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)

    def reject_framework_spooling(
        *_args: object, **_kwargs: object
    ) -> NoReturn:
        raise AssertionError("framework upload spool must not be used")

    monkeypatch.setattr(
        "starlette.formparsers.SpooledTemporaryFile", reject_framework_spooling
    )
    response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    )

    assert response.status_code == 201
    assert len(list((tmp_path / "customer_uploads").glob("*.xlsx"))) == 1


def test_incomplete_multipart_upload_is_stable_and_removes_temporary_file(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    boundary = b"customer-upload-boundary"
    body = (
        b"--"
        + boundary
        + b'\r\nContent-Disposition: form-data; name="file"; '
        + b'filename="customer.xlsx"\r\n'
        + f"Content-Type: {XLSX_MEDIA_TYPE}\r\n\r\n".encode()
        + _workbook_bytes()
    )

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers={
            **superuser_token_headers,
            "Content-Type": f"multipart/form-data; boundary={boundary.decode()}",
        },
        content=body,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "incomplete_upload",
        "message": "The upload was incomplete.",
    }
    assert not list((tmp_path / "customer_uploads").glob("*"))


def test_overlong_multipart_boundary_is_stable_and_removes_temporary_file(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    boundary = "b" * 257

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers={
            **superuser_token_headers,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        content=b"",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "incomplete_upload",
        "message": "The upload was incomplete.",
    }
    assert not list((tmp_path / "customer_uploads").glob("*"))


def test_oversized_non_file_multipart_content_is_rejected(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    boundary = b"customer-upload-boundary"
    body = (
        b"--"
        + boundary
        + b'\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n'
        + b"x" * (20 * 1024 * 1024 + 64 * 1024)
        + b"\r\n--"
        + boundary
        + b"--\r\n"
    )

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers={
            **superuser_token_headers,
            "Content-Type": f"multipart/form-data; boundary={boundary.decode()}",
        },
        content=body,
    )

    assert response.status_code == 413
    assert response.json()["detail"] == {
        "code": "upload_too_large",
        "message": "The upload exceeds the allowed size.",
    }
    assert not list((tmp_path / "customer_uploads").glob("*"))


def test_cancelled_multipart_stream_removes_temporary_file(tmp_path: Path) -> None:
    boundary = b"customer-upload-boundary"
    first_chunk = (
        b"--"
        + boundary
        + b'\r\nContent-Disposition: form-data; name="file"; '
        + b'filename="customer.xlsx"\r\n'
        + f"Content-Type: {XLSX_MEDIA_TYPE}\r\n\r\n".encode()
        + b"partial workbook bytes"
    )
    messages: list[Message] = [
        {"type": "http.request", "body": first_chunk, "more_body": True}
    ]

    async def receive() -> Message:
        if messages:
            return messages.pop()
        raise asyncio.CancelledError

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "headers": [
            (
                b"content-type",
                b"multipart/form-data; boundary=" + boundary,
            )
        ],
    }
    request = Request(scope, receive)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            customer_upload_service.stream_customer_upload_request(
                request=request,
                artifact_root=tmp_path,
            )
        )

    assert not list((tmp_path / "customer_uploads").glob("*"))


def test_validator_rejection_is_sanitized_and_compensated(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    content = _workbook_bytes(asset_ip="customer-secret.invalid")
    audit_count = db.exec(select(func.count()).select_from(AuditEvent)).one()

    with caplog.at_level(logging.INFO, logger="app.api.routes.projects"):
        response = client.post(
            f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
            headers=superuser_token_headers,
            files={"file": ("customer-secret.xlsx", content, XLSX_MEDIA_TYPE)},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "invalid_required_value",
        "message": "The workbook contains an invalid required value.",
        "field": "asset_ip",
        "row": 2,
    }
    assert "customer-secret" not in response.text
    assert str(tmp_path) not in response.text
    rejection_records = [
        record
        for record in caplog.records
        if record.message == "Customer upload rejected"
    ]
    assert len(rejection_records) == 1
    assert rejection_records[0].__dict__["upload_error_code"] == "invalid_required_value"
    assert rejection_records[0].__dict__["project_id"] == str(project["id"])
    assert "customer-secret" not in caplog.text
    assert str(tmp_path) not in caplog.text
    assert db.exec(select(func.count()).select_from(AuditEvent)).one() == audit_count
    assert not list((tmp_path / "customer_uploads").glob("*"))


def test_validator_rejection_cleanup_failure_returns_storage_error(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)

    def reject_unlink(_path: Path, *, missing_ok: bool = False) -> None:
        del missing_ok
        raise OSError("test cleanup failure")

    monkeypatch.setattr(Path, "unlink", reject_unlink)
    response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=superuser_token_headers,
        files={
            "file": (
                "customer.xlsx",
                _workbook_bytes(asset_ip="invalid.example"),
                XLSX_MEDIA_TYPE,
            )
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "upload_storage_failed",
        "message": "The upload could not be stored.",
    }


def test_active_content_maps_to_unsupported_workbook_feature(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=superuser_token_headers,
        files={
            "file": (
                "customer.xlsx",
                _workbook_bytes(formula=True),
                XLSX_MEDIA_TYPE,
            )
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_workbook_feature"
    assert not list((tmp_path / "customer_uploads").glob("*"))


def test_storage_failure_returns_stable_error_without_database_side_effects(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "not-a-directory"
    artifact_root.write_text("occupied")
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", artifact_root)
    project = _create_project(client, superuser_token_headers)
    artifact_count = db.exec(select(func.count()).select_from(Artifact)).one()

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "upload_storage_failed",
        "message": "The upload could not be stored.",
    }
    assert db.exec(select(func.count()).select_from(Artifact)).one() == artifact_count


def test_transaction_failure_removes_promoted_artifact_and_rolls_back_audit(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    artifact_count = db.exec(select(func.count()).select_from(Artifact)).one()
    audit_count = db.exec(select(func.count()).select_from(AuditEvent)).one()

    with _reject_customer_upload_inserts(db):
        response = client.post(
            f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
            headers=superuser_token_headers,
            files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
        )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "upload_storage_failed"
    db.expire_all()
    assert db.exec(select(func.count()).select_from(Artifact)).one() == artifact_count
    assert db.exec(select(func.count()).select_from(AuditEvent)).one() == audit_count
    assert not list((tmp_path / "customer_uploads").glob("*"))


def test_accepted_upload_does_not_depend_on_a_post_commit_refresh(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    project_id = uuid.UUID(str(project["id"]))

    def reject_refresh(*_args: object, **_kwargs: object) -> NoReturn:
        raise SQLAlchemyError("test post-commit refresh failure")

    monkeypatch.setattr(Session, "refresh", reject_refresh)
    response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    )

    assert response.status_code == 201
    assert response.json()["display_filename"] == "customer.xlsx"
    db.expire_all()
    assert db.exec(
        select(func.count())
        .select_from(CustomerUpload)
        .where(CustomerUpload.project_id == project_id)
    ).one() == 1
    assert len(list((tmp_path / "customer_uploads").glob("*.xlsx"))) == 1


def test_deduplication_read_failure_removes_temporary_upload(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    artifact_count = db.exec(select(func.count()).select_from(Artifact)).one()
    audit_count = db.exec(select(func.count()).select_from(AuditEvent)).one()

    with _reject_customer_upload_reads():
        response = client.post(
            f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads",
            headers=superuser_token_headers,
            files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
        )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "upload_storage_failed"
    db.expire_all()
    assert db.exec(select(func.count()).select_from(Artifact)).one() == artifact_count
    assert db.exec(select(func.count()).select_from(AuditEvent)).one() == audit_count
    assert not list((tmp_path / "customer_uploads").glob("*"))


def test_deduplication_cleanup_failure_returns_storage_error(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    content = _workbook_bytes()
    url = f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads"
    first_response = client.post(
        url,
        headers=superuser_token_headers,
        files={"file": ("first.xlsx", content, XLSX_MEDIA_TYPE)},
    )
    assert first_response.status_code == 201

    original_unlink = Path.unlink

    def reject_temporary_unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path.name.startswith("."):
            raise OSError("test cleanup failure")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", reject_temporary_unlink)
    repeated_response = client.post(
        url,
        headers=superuser_token_headers,
        files={"file": ("second.xlsx", content, XLSX_MEDIA_TYPE)},
    )

    assert repeated_response.status_code == 500
    assert repeated_response.json()["detail"] == {
        "code": "upload_storage_failed",
        "message": "The upload could not be stored.",
    }


def _create_governance_reference(
    db: Session,
    *,
    project_id: uuid.UUID,
    run_upload: CustomerUpload,
    snapshot_upload: CustomerUpload | None = None,
) -> None:
    project = db.get(Project, project_id)
    assert project is not None
    source = SourceInstance(
        tenant_id=project.tenant_id,
        project_id=project.id,
        instance_id=f"reference-{uuid.uuid4()}",
        capset_id="reference-capset",
    )
    run = GovernanceRun(
        tenant_id=project.tenant_id,
        project_id=project.id,
        trigger_id=f"reference-{uuid.uuid4()}",
        session_id=str(uuid.uuid4()),
        requested_by="test",
        status="FAILED_PROCESSING",
        customer_upload_id=run_upload.id,
        customer_upload_sha256=run_upload.raw_sha256,
        customer_upload_profile_id=run_upload.profile_id,
        customer_upload_profile_version=run_upload.profile_version,
        source_instance_id=source.id,
        cloudatlas_validated_fingerprint="a" * 64,
        cloudatlas_capset_id=source.capset_id,
        cloudatlas_method="reference-method",
        package_sha256="b" * 64,
        descriptor_sha256="c" * 64,
        runner_build_version="reference-runner",
    )
    db.add(source)
    db.flush()
    db.add(run)
    if snapshot_upload is not None:
        db.add(
            SourceSnapshot(
                tenant_id=project.tenant_id,
                project_id=project.id,
                governance_run_id=run.id,
                source_type="CUSTOMER_UPLOAD",
                customer_upload_id=snapshot_upload.id,
                artifact_id=snapshot_upload.artifact_id,
                content_sha256=snapshot_upload.raw_sha256,
                schema_fingerprint="d" * 64,
                record_count=snapshot_upload.record_count,
            )
        )
    db.commit()


def test_global_admin_can_delete_unused_upload_and_reupload_gets_new_ids(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    content = _workbook_bytes()
    uploads_url = f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads"
    upload_response = client.post(
        uploads_url,
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", content, XLSX_MEDIA_TYPE)},
    )
    assert upload_response.status_code == 201
    upload = upload_response.json()
    upload_id = uuid.UUID(upload["id"])
    db.expire_all()
    stored_upload = db.get(CustomerUpload, upload_id)
    assert stored_upload is not None
    stored_artifact = db.get(Artifact, stored_upload.artifact_id)
    assert stored_artifact is not None
    artifact_id = stored_artifact.id
    artifact_path = tmp_path / stored_artifact.storage_key
    assert artifact_path.read_bytes() == content

    delete_response = client.delete(
        f"{uploads_url}/{upload_id}", headers=superuser_token_headers
    )

    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert not artifact_path.exists()
    db.expire_all()
    assert db.get(CustomerUpload, upload_id) is None
    assert db.get(Artifact, artifact_id) is None
    delete_events = db.exec(
        select(AuditEvent).where(
            AuditEvent.project_id == uuid.UUID(str(project["id"])),
            AuditEvent.action == "customer_upload.deleted",
        )
    ).all()
    assert len(delete_events) == 1
    assert delete_events[0].target_id == upload_id
    assert delete_events[0].before_data == {
        "profile_id": upload["profile_id"],
        "profile_version": 1,
        "record_count": 1,
        "warning_count": 5,
    }
    assert delete_events[0].after_data is None

    repeated_delete = client.delete(
        f"{uploads_url}/{upload_id}", headers=superuser_token_headers
    )
    assert repeated_delete.status_code == 404

    replacement_response = client.post(
        uploads_url,
        headers=superuser_token_headers,
        files={"file": ("replacement.xlsx", content, XLSX_MEDIA_TYPE)},
    )
    assert replacement_response.status_code == 201
    replacement = replacement_response.json()
    assert replacement["id"] != upload["id"]
    db.expire_all()
    replacement_record = db.get(CustomerUpload, uuid.UUID(replacement["id"]))
    assert replacement_record is not None
    assert replacement_record.artifact_id != artifact_id
    assert (tmp_path / f"customer_uploads/{replacement_record.artifact_id}.xlsx").exists()


def test_only_global_admin_can_delete_customer_uploads_across_project_roles(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    target_project = _create_project(client, superuser_token_headers)
    other_project = _create_project(client, superuser_token_headers)
    uploads_url = (
        f"{settings.API_V1_STR}/projects/{target_project['id']}/customer-uploads"
    )
    upload_response = client.post(
        uploads_url,
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    )
    assert upload_response.status_code == 201
    upload_id = upload_response.json()["id"]

    role_headers = [
        _create_member(
            client,
            superuser_token_headers,
            project_id=target_project["id"],
            roles=[role],
        )
        for role in ("operator", "viewer", "approver")
    ]
    cross_project_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=other_project["id"],
        roles=["operator"],
    )

    responses = [
        client.delete(f"{uploads_url}/{upload_id}", headers=headers)
        for headers in [*role_headers, cross_project_headers]
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]


def test_archived_project_allows_global_admin_to_delete_unused_upload(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    uploads_url = f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads"
    upload_response = client.post(
        uploads_url,
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    )
    assert upload_response.status_code == 201
    upload_id = upload_response.json()["id"]
    assert (
        client.post(
            f"{settings.API_V1_STR}/projects/{project['id']}/archive",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )

    delete_response = client.delete(
        f"{uploads_url}/{upload_id}", headers=superuser_token_headers
    )

    assert delete_response.status_code == 204


@pytest.mark.parametrize("reference_kind", ["current", "run", "snapshot"])
def test_referenced_customer_upload_cannot_be_deleted(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    reference_kind: str,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    uploads_url = f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads"
    upload_response = client.post(
        uploads_url,
        headers=superuser_token_headers,
        files={"file": ("target.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    )
    assert upload_response.status_code == 201
    target_upload = upload_response.json()
    target_id = uuid.UUID(target_upload["id"])
    if reference_kind == "current":
        assert client.post(
            f"{uploads_url}/{target_id}/select",
            headers=superuser_token_headers,
        ).status_code == 200
    else:
        db.expire_all()
        target_record = db.get(CustomerUpload, target_id)
        assert target_record is not None
        if reference_kind == "run":
            _create_governance_reference(
                db,
                project_id=uuid.UUID(str(project["id"])),
                run_upload=target_record,
            )
        else:
            other_response = client.post(
                uploads_url,
                headers=superuser_token_headers,
                files={
                    "file": (
                        "other.xlsx",
                        _workbook_bytes(asset_ip="192.0.2.20"),
                        XLSX_MEDIA_TYPE,
                    )
                },
            )
            assert other_response.status_code == 201
            other_record = db.get(
                CustomerUpload, uuid.UUID(other_response.json()["id"])
            )
            assert other_record is not None
            _create_governance_reference(
                db,
                project_id=uuid.UUID(str(project["id"])),
                run_upload=other_record,
                snapshot_upload=target_record,
            )

    response = client.delete(
        f"{uploads_url}/{target_id}", headers=superuser_token_headers
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "customer_upload_in_use"
    db.expire_all()
    assert db.get(CustomerUpload, target_id) is not None


def test_delete_storage_failure_keeps_original_artifact_and_metadata(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    uploads_url = f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads"
    content = _workbook_bytes()
    upload = client.post(
        uploads_url,
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", content, XLSX_MEDIA_TYPE)},
    ).json()
    db.expire_all()
    stored_upload = db.get(CustomerUpload, uuid.UUID(upload["id"]))
    assert stored_upload is not None
    artifact = db.get(Artifact, stored_upload.artifact_id)
    assert artifact is not None
    original_path = tmp_path / artifact.storage_key
    original_replace = os.replace

    def reject_isolation(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        if Path(destination).name.endswith(".deleting"):
            raise OSError("test isolation failure")
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", reject_isolation)
    response = client.delete(
        f"{uploads_url}/{upload['id']}", headers=superuser_token_headers
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "customer_upload_delete_failed"
    assert original_path.read_bytes() == content
    db.expire_all()
    assert db.get(CustomerUpload, uuid.UUID(upload["id"])) is not None
    assert db.get(Artifact, artifact.id) is not None
    assert not list((tmp_path / "customer_uploads").glob("*.deleting"))


def test_delete_transaction_failure_restores_isolated_artifact(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    uploads_url = f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads"
    content = _workbook_bytes()
    upload = client.post(
        uploads_url,
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", content, XLSX_MEDIA_TYPE)},
    ).json()
    db.expire_all()
    stored_upload = db.get(CustomerUpload, uuid.UUID(upload["id"]))
    assert stored_upload is not None
    artifact = db.get(Artifact, stored_upload.artifact_id)
    assert artifact is not None
    original_path = tmp_path / artifact.storage_key

    with reject_audit_inserts(db):
        response = client.delete(
            f"{uploads_url}/{upload['id']}", headers=superuser_token_headers
        )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "customer_upload_delete_failed"
    assert original_path.read_bytes() == content
    assert not list((tmp_path / "customer_uploads").glob("*.deleting"))
    db.expire_all()
    assert db.get(CustomerUpload, uuid.UUID(upload["id"])) is not None
    assert db.get(Artifact, artifact.id) is not None


def test_final_physical_cleanup_failure_is_explicit_and_not_product_accessible(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    uploads_url = f"{settings.API_V1_STR}/projects/{project['id']}/customer-uploads"
    upload = client.post(
        uploads_url,
        headers=superuser_token_headers,
        files={"file": ("customer.xlsx", _workbook_bytes(), XLSX_MEDIA_TYPE)},
    ).json()
    db.expire_all()
    stored_upload = db.get(CustomerUpload, uuid.UUID(upload["id"]))
    assert stored_upload is not None
    artifact = db.get(Artifact, stored_upload.artifact_id)
    assert artifact is not None
    artifact_id = artifact.id
    original_path = tmp_path / artifact.storage_key
    original_unlink = Path.unlink

    def reject_isolated_unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path.name.endswith(".deleting"):
            raise OSError("test physical cleanup failure")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", reject_isolated_unlink)
    response = client.delete(
        f"{uploads_url}/{upload['id']}", headers=superuser_token_headers
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "customer_upload_delete_failed"
    assert not original_path.exists()
    assert list((tmp_path / "customer_uploads").glob("*.deleting"))
    db.expire_all()
    assert db.get(CustomerUpload, uuid.UUID(upload["id"])) is None
    assert db.get(Artifact, artifact_id) is None
    assert (
        client.delete(
            f"{uploads_url}/{upload['id']}", headers=superuser_token_headers
        ).status_code
        == 404
    )
