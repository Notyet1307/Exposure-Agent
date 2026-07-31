import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from app.core.config import settings
from app.domain.models import CustomerUploadProfile, Project
from app.main import app
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

EXPECTED_PROFILE_SUMMARY = {
    "version": 1,
    "required_headers": [
        "资产IP",
        "起始端口",
        "结束端口",
        "是否web界面",
        "web界面url",
    ],
    "warning_headers": [
        "服务类型",
        "资产负责人",
        "资产所属部门",
        "端口负责人",
        "部门",
    ],
    "optional_headers": ["序号"],
}


@contextmanager
def reject_customer_upload_profile_inserts(db: Session) -> Iterator[None]:
    db.execute(
        text(
            """
            CREATE FUNCTION fail_test_customer_upload_profile_insert()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'test customer upload profile failure';
            END;
            $$
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TRIGGER fail_test_customer_upload_profile_insert
            BEFORE INSERT ON customer_upload_profiles
            FOR EACH ROW EXECUTE FUNCTION fail_test_customer_upload_profile_insert()
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
                "DROP TRIGGER IF EXISTS fail_test_customer_upload_profile_insert "
                "ON customer_upload_profiles"
            )
        )
        db.execute(
            text("DROP FUNCTION IF EXISTS fail_test_customer_upload_profile_insert()")
        )
        db.commit()


def create_project(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> dict[str, object]:
    response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=superuser_token_headers,
        json={"name": f"Profile Project {uuid.uuid4()}"},
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def test_new_projects_expose_independent_default_profile_v1(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    first_project = create_project(client, superuser_token_headers)
    second_project = create_project(client, superuser_token_headers)

    first_response = client.get(
        f"{settings.API_V1_STR}/projects/{first_project['id']}/customer-upload-profile",
        headers=superuser_token_headers,
    )
    second_response = client.get(
        f"{settings.API_V1_STR}/projects/{second_project['id']}/customer-upload-profile",
        headers=superuser_token_headers,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    first_profile = first_response.json()
    second_profile = second_response.json()
    assert uuid.UUID(first_profile.pop("id"))
    assert uuid.UUID(second_profile.pop("id"))
    assert first_profile == EXPECTED_PROFILE_SUMMARY
    assert second_profile == EXPECTED_PROFILE_SUMMARY
    assert first_response.json()["id"] != second_response.json()["id"]


def test_profile_insert_failure_rolls_back_project_creation(
    db: Session, superuser_token_headers: dict[str, str]
) -> None:
    name = f"Profile Rollback {uuid.uuid4()}"
    profile_count_before = len(db.exec(select(CustomerUploadProfile)).all())

    with reject_customer_upload_profile_inserts(db):
        with TestClient(
            app,
            raise_server_exceptions=False,
            client=("127.0.0.1", 50020),
        ) as failure_client:
            response = failure_client.post(
                f"{settings.API_V1_STR}/projects/",
                headers=superuser_token_headers,
                json={"name": name},
            )
        assert response.status_code == 500

    db.expire_all()
    assert db.exec(select(Project).where(Project.name == name)).one_or_none() is None
    assert len(db.exec(select(CustomerUploadProfile)).all()) == profile_count_before


@pytest.mark.parametrize("role", ["viewer", "operator", "approver"])
def test_project_reader_can_read_archived_profile_but_not_another_project(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    role: str,
) -> None:
    allowed_project = create_project(client, superuser_token_headers)
    hidden_project = create_project(client, superuser_token_headers)
    email = random_email()
    password = random_lower_string()
    user_response = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=superuser_token_headers,
        json={"email": email, "password": password},
    )
    assert user_response.status_code == 200
    membership_response = client.post(
        f"{settings.API_V1_STR}/projects/{allowed_project['id']}/memberships/",
        headers=superuser_token_headers,
        json={"user_id": user_response.json()["id"], "roles": [role]},
    )
    assert membership_response.status_code == 201
    archive_response = client.post(
        f"{settings.API_V1_STR}/projects/{allowed_project['id']}/archive",
        headers=superuser_token_headers,
    )
    assert archive_response.status_code == 200
    user_headers = user_authentication_headers(
        client=client, email=email, password=password
    )

    allowed_response = client.get(
        f"{settings.API_V1_STR}/projects/{allowed_project['id']}/customer-upload-profile",
        headers=user_headers,
    )
    hidden_response = client.get(
        f"{settings.API_V1_STR}/projects/{hidden_project['id']}/customer-upload-profile",
        headers=user_headers,
    )

    assert allowed_response.status_code == 200
    assert allowed_response.json()["version"] == 1
    assert hidden_response.status_code == 404
