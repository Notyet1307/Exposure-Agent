import hashlib
import io
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook  # type: ignore[import-untyped]
from pytest import MonkeyPatch
from sqlalchemy import text
from sqlmodel import Session, func, select

from app.core.config import settings
from app.domain.models import Artifact, AuditEvent, CustomerUpload
from app.main import app
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
        "can_upload": True,
    }
    artifacts = list((tmp_path / "customer_uploads").glob("*.xlsx"))
    assert len(artifacts) == 1
    assert artifacts[0].name != "customer.xlsx"
    assert artifacts[0].read_bytes() == content


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

    def upload() -> tuple[int, dict[str, object]]:
        with TestClient(app, client=("127.0.0.1", 50100)) as concurrent_client:
            response = concurrent_client.post(
                url,
                headers=superuser_token_headers,
                files={"file": ("concurrent.xlsx", content, XLSX_MEDIA_TYPE)},
            )
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: upload(), range(2)))

    assert sorted(status_code for status_code, _body in results) == [200, 201]
    assert results[0][1] == results[1][1]
    assert len(list((tmp_path / "customer_uploads").glob("*.xlsx"))) == 1


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
    assert list_response.json() == {"data": [], "count": 0, "can_upload": False}


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
    assert list_response.json() == {"data": [], "count": 0, "can_upload": False}


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


def test_validator_rejection_is_sanitized_and_compensated(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    project = _create_project(client, superuser_token_headers)
    content = _workbook_bytes(asset_ip="customer-secret.invalid")
    audit_count = db.exec(select(func.count()).select_from(AuditEvent)).one()

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
    assert db.exec(select(func.count()).select_from(AuditEvent)).one() == audit_count
    assert not list((tmp_path / "customer_uploads").glob("*"))


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
