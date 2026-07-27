import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.db import init_db
from app.models import User
from tests.utils.utils import random_email, random_lower_string


def login(
    client: TestClient, email: str, password: str
) -> tuple[int, dict[str, object]]:
    response = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": email, "password": password},
    )
    return response.status_code, response.json()


def test_admin_creates_active_ordinary_user_with_initial_password(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    email = random_email()
    password = random_lower_string()

    response = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=superuser_token_headers,
        json={"email": email, "password": password},
    )

    assert response.status_code == 200
    created_user = response.json()
    assert created_user["email"] == email
    assert created_user["is_active"] is True
    assert created_user["is_superuser"] is False

    status_code, token = login(client, email, password)
    assert status_code == 200
    assert token["access_token"]


def test_admin_can_reset_user_password(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    email = random_email()
    old_password = random_lower_string()
    new_password = random_lower_string()
    create_response = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=superuser_token_headers,
        json={"email": email, "password": old_password},
    )
    assert create_response.status_code == 200

    response = client.patch(
        f"{settings.API_V1_STR}/users/{create_response.json()['id']}",
        headers=superuser_token_headers,
        json={"password": new_password},
    )

    assert response.status_code == 200
    assert login(client, email, old_password)[0] == 400
    assert login(client, email, new_password)[0] == 200


def test_admin_deactivates_user_without_deleting_their_record(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    email = random_email()
    password = random_lower_string()
    create_response = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=superuser_token_headers,
        json={"email": email, "password": password},
    )
    assert create_response.status_code == 200
    user_id = create_response.json()["id"]

    response = client.patch(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=superuser_token_headers,
        json={"is_active": False},
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    user = db.get(User, user_id)
    assert user is not None
    assert user.email == email
    assert user.is_active is False
    status_code, login_response = login(client, email, password)
    assert status_code == 400
    assert login_response["detail"] == "Inactive user"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/users/signup"),
        ("POST", "/login/password-recovery/user@example.com"),
        ("POST", "/login/reset-password/"),
        ("DELETE", "/users/me"),
        ("DELETE", "/users/00000000-0000-0000-0000-000000000000"),
    ],
)
def test_removed_account_lifecycle_apis_are_not_routable(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, f"{settings.API_V1_STR}{path}")

    assert response.status_code in {404, 405}


def test_initial_superuser_bootstrap_is_idempotent(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = random_email()
    initial_password = random_lower_string()
    replacement_password = random_lower_string()
    monkeypatch.setattr(settings, "FIRST_SUPERUSER", email)
    monkeypatch.setattr(settings, "FIRST_SUPERUSER_PASSWORD", initial_password)

    init_db(db)
    user = crud.get_user_by_email(session=db, email=email)
    assert user is not None
    assert user.is_superuser is True

    original_hash = user.hashed_password
    monkeypatch.setattr(settings, "FIRST_SUPERUSER_PASSWORD", replacement_password)
    init_db(db)
    db.refresh(user)

    assert user.hashed_password == original_hash
