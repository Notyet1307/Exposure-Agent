import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app import crud
from app.core.config import Settings, parse_cors, settings
from app.core.security import verify_password
from app.domain.models import AuditEvent
from app.main import app
from app.models import User, UserCreate
from tests.utils.audit import reject_audit_inserts
from tests.utils.user import create_random_user
from tests.utils.utils import random_email, random_lower_string


def test_get_users_superuser_me(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(f"{settings.API_V1_STR}/users/me", headers=superuser_token_headers)
    current_user = r.json()
    assert current_user
    assert current_user["is_active"] is True
    assert current_user["is_superuser"]
    assert current_user["email"] == settings.FIRST_SUPERUSER


def test_get_users_normal_user_me(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.get(f"{settings.API_V1_STR}/users/me", headers=normal_user_token_headers)
    current_user = r.json()
    assert current_user
    assert current_user["is_active"] is True
    assert current_user["is_superuser"] is False
    assert current_user["email"] == settings.EMAIL_TEST_USER


def test_create_user_new_email(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    data = {"email": username, "password": password}
    r = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=superuser_token_headers,
        json=data,
    )
    assert 200 <= r.status_code < 300
    created_user = r.json()
    user = crud.get_user_by_email(session=db, email=username)
    assert user
    assert user.email == created_user["email"]


def test_get_existing_user_as_superuser(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)
    user_id = user.id
    r = client.get(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=superuser_token_headers,
    )
    assert 200 <= r.status_code < 300
    api_user = r.json()
    existing_user = crud.get_user_by_email(session=db, email=username)
    assert existing_user
    assert existing_user.email == api_user["email"]


def test_get_non_existing_user_as_superuser(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/users/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
    assert r.json() == {"detail": "User not found"}


def test_get_existing_user_current_user(client: TestClient, db: Session) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)
    user_id = user.id

    login_data = {
        "username": username,
        "password": password,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}

    r = client.get(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=headers,
    )
    assert 200 <= r.status_code < 300
    api_user = r.json()
    existing_user = crud.get_user_by_email(session=db, email=username)
    assert existing_user
    assert existing_user.email == api_user["email"]


def test_get_existing_user_permissions_error(
    db: Session,
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    user = create_random_user(db)

    r = client.get(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403
    assert r.json() == {"detail": "The user doesn't have enough privileges"}


def test_get_non_existing_user_permissions_error(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    user_id = uuid.uuid4()

    r = client.get(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403
    assert r.json() == {"detail": "The user doesn't have enough privileges"}


def test_create_user_existing_username(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    # username = email
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    crud.create_user(session=db, user_create=user_in)
    data = {"email": username, "password": password}
    r = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=superuser_token_headers,
        json=data,
    )
    created_user = r.json()
    assert r.status_code == 400
    assert "_id" not in created_user


def test_create_user_by_normal_user(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    username = random_email()
    password = random_lower_string()
    data = {"email": username, "password": password}
    r = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 403


def test_retrieve_users(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    crud.create_user(session=db, user_create=user_in)

    username2 = random_email()
    password2 = random_lower_string()
    user_in2 = UserCreate(email=username2, password=password2)
    crud.create_user(session=db, user_create=user_in2)

    r = client.get(f"{settings.API_V1_STR}/users/", headers=superuser_token_headers)
    all_users = r.json()

    assert len(all_users["data"]) > 1
    assert "count" in all_users
    for item in all_users["data"]:
        assert "email" in item


def test_update_user_me(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    full_name = "Updated Name"
    email = random_email()
    data = {"full_name": full_name, "email": email}
    r = client.patch(
        f"{settings.API_V1_STR}/users/me",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 200
    updated_user = r.json()
    assert updated_user["email"] == email
    assert updated_user["full_name"] == full_name

    user_query = select(User).where(User.email == email)
    user_db = db.exec(user_query).first()
    assert user_db
    assert user_db.email == email
    assert user_db.full_name == full_name


def test_update_password_me(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    new_password = random_lower_string()
    data = {
        "current_password": settings.FIRST_SUPERUSER_PASSWORD,
        "new_password": new_password,
    }
    r = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 200
    updated_user = r.json()
    assert updated_user["message"] == "Password updated successfully"

    user_query = select(User).where(User.email == settings.FIRST_SUPERUSER)
    user_db = db.exec(user_query).first()
    assert user_db
    assert user_db.email == settings.FIRST_SUPERUSER
    verified, _ = verify_password(new_password, user_db.hashed_password)
    assert verified

    # Revert to the old password to keep consistency in test
    old_data = {
        "current_password": new_password,
        "new_password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers=superuser_token_headers,
        json=old_data,
    )
    db.refresh(user_db)

    assert r.status_code == 200
    verified, _ = verify_password(
        settings.FIRST_SUPERUSER_PASSWORD, user_db.hashed_password
    )
    assert verified


def test_update_password_me_incorrect_password(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    new_password = random_lower_string()
    data = {"current_password": new_password, "new_password": new_password}
    r = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 400
    updated_user = r.json()
    assert updated_user["detail"] == "Incorrect password"


def test_update_user_me_email_exists(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)

    data = {"email": user.email}
    r = client.patch(
        f"{settings.API_V1_STR}/users/me",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "User with this email already exists"


def test_update_password_me_same_password_error(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {
        "current_password": settings.FIRST_SUPERUSER_PASSWORD,
        "new_password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 400
    updated_user = r.json()
    assert (
        updated_user["detail"] == "New password cannot be the same as the current one"
    )


def test_update_user(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)

    data = {"full_name": "Updated_full_name"}
    r = client.patch(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 200
    updated_user = r.json()

    assert updated_user["full_name"] == "Updated_full_name"

    user_query = select(User).where(User.email == username)
    user_db = db.exec(user_query).first()
    db.refresh(user_db)
    assert user_db
    assert user_db.full_name == "Updated_full_name"


def test_admin_user_update_emits_sanitized_audit_event(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user = create_random_user(db)
    original_email = str(user.email)
    new_email = random_email()
    new_password = random_lower_string()

    update_response = client.patch(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers=superuser_token_headers,
        json={"full_name": "Audited User", "password": new_password},
    )

    assert update_response.status_code == 200
    mixed_update_response = client.patch(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers=superuser_token_headers,
        json={"email": new_email, "is_active": False},
    )
    assert mixed_update_response.status_code == 200

    audit_response = client.get(
        f"{settings.API_V1_STR}/audit-events/", headers=superuser_token_headers
    )
    user_events = [
        event
        for event in reversed(audit_response.json()["data"])
        if event["target_id"] == str(user.id)
    ]
    assert [event["action"] for event in user_events] == [
        "user.updated",
        "user.deactivated",
    ]
    update_event, mixed_event = user_events
    assert update_event["before_data"] == {
        "email": original_email,
        "full_name": None,
        "is_active": True,
        "password_changed": False,
    }
    assert update_event["after_data"] == {
        "email": original_email,
        "full_name": "Audited User",
        "is_active": True,
        "password_changed": True,
    }
    assert mixed_event["before_data"] == {
        "email": original_email,
        "full_name": "Audited User",
        "is_active": True,
    }
    assert mixed_event["after_data"] == {
        "email": new_email,
        "full_name": "Audited User",
        "is_active": False,
    }
    assert new_password not in str(user_events)
    assert "hashed_password" not in str(user_events)


def test_admin_deactivates_and_reactivates_user_with_audit_history(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    user = create_random_user(db)
    actor_response = client.get(
        f"{settings.API_V1_STR}/users/me", headers=superuser_token_headers
    )
    assert actor_response.status_code == 200

    deactivate_response = client.patch(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers={**superuser_token_headers, "X-Real-IP": "203.0.113.29"},
        json={"is_active": False},
    )
    reactivate_response = client.patch(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers={**superuser_token_headers, "X-Real-IP": "203.0.113.30"},
        json={"is_active": True},
    )

    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["is_active"] is False
    assert reactivate_response.status_code == 200
    assert reactivate_response.json()["is_active"] is True
    audit_response = client.get(
        f"{settings.API_V1_STR}/audit-events/", headers=superuser_token_headers
    )
    assert audit_response.status_code == 200
    user_events = [
        event
        for event in reversed(audit_response.json()["data"])
        if event["target_id"] == str(user.id)
    ]
    assert [event["action"] for event in user_events] == [
        "user.deactivated",
        "user.reactivated",
    ]
    assert all(event["project_id"] is None for event in user_events)
    assert all(
        event["actor_subject"] == actor_response.json()["id"] for event in user_events
    )
    assert all(event["actor_type"] == "user" for event in user_events)
    assert all(event["target_type"] == "user" for event in user_events)
    assert user_events[0]["before_data"] == {
        "email": user.email,
        "full_name": None,
        "is_active": True,
    }
    assert user_events[0]["after_data"] == {
        "email": user.email,
        "full_name": None,
        "is_active": False,
    }
    assert user_events[0]["ip_address"] == "203.0.113.29"
    assert user_events[1]["before_data"] == {
        "email": user.email,
        "full_name": None,
        "is_active": False,
    }
    assert user_events[1]["after_data"] == {
        "email": user.email,
        "full_name": None,
        "is_active": True,
    }
    assert user_events[1]["ip_address"] == "203.0.113.30"


def test_user_deactivation_rolls_back_when_audit_insert_fails(
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    user = create_random_user(db)
    audit_count = db.exec(select(func.count()).select_from(AuditEvent)).one()

    with reject_audit_inserts(db):
        with TestClient(
            app, raise_server_exceptions=False, client=("127.0.0.1", 50031)
        ) as failure_client:
            response = failure_client.patch(
                f"{settings.API_V1_STR}/users/{user.id}",
                headers=superuser_token_headers,
                json={"is_active": False},
            )
        assert response.status_code == 500

    db.expire_all()
    persisted_user = db.get(User, user.id)
    assert persisted_user is not None
    assert persisted_user.is_active is True
    assert db.exec(select(func.count()).select_from(AuditEvent)).one() == audit_count


def test_update_user_not_exists(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {"full_name": "Updated_full_name"}
    r = client.patch(
        f"{settings.API_V1_STR}/users/{uuid.uuid4()}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "The user with this id does not exist in the system"


def test_update_user_email_exists(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)

    username2 = random_email()
    password2 = random_lower_string()
    user_in2 = UserCreate(email=username2, password=password2)
    user2 = crud.create_user(session=db, user_create=user_in2)

    data = {"email": user2.email}
    r = client.patch(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "User with this email already exists"


def test_configuration_parses_cors_and_rejects_default_secrets() -> None:
    assert parse_cors(["https://example.com"]) == ["https://example.com"]
    with pytest.raises(ValueError, match="unsupported"):
        parse_cors({"unsupported": "origin"})

    settings_for_deployment = Settings.model_construct(ENVIRONMENT="production")
    with pytest.raises(ValueError, match="for security"):
        settings_for_deployment._check_default_secret("SECRET_KEY", "changethis")


@pytest.mark.parametrize(
    ("field_name", "default_value"),
    [
        ("SECRET_KEY", "not-for-production-issue4-secret"),
        ("POSTGRES_PASSWORD", "not-for-production-issue4-postgres"),
        ("FIRST_SUPERUSER", "admin@example.com"),
        ("FIRST_SUPERUSER_PASSWORD", "not-for-production-issue4-admin"),
    ],
)
def test_configuration_rejects_repository_defaults_in_production(
    field_name: str, default_value: str
) -> None:
    settings_for_deployment = Settings.model_construct(
        ENVIRONMENT="production",
        SECRET_KEY="a-secure-secret",
        POSTGRES_PASSWORD="a-secure-password",
        FIRST_SUPERUSER="administrator@example.com",
        FIRST_SUPERUSER_PASSWORD="a-secure-admin-password",
    )
    setattr(settings_for_deployment, field_name, default_value)

    with pytest.raises(ValueError, match="for security"):
        settings_for_deployment._enforce_non_default_secrets()
