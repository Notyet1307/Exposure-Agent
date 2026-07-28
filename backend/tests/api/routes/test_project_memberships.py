import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app.core.config import settings
from app.core.db import engine
from app.core.time import get_datetime_utc
from app.domain.models import AuditEvent, Project, ProjectMembership
from app.main import app
from tests.utils.audit import reject_audit_inserts
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def create_project(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> dict[str, object]:
    response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=superuser_token_headers,
        json={"name": f"Membership Project {uuid.uuid4()}"},
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def create_ordinary_user(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> dict[str, object]:
    response = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=superuser_token_headers,
        json={"email": random_email(), "password": random_lower_string()},
    )
    assert response.status_code == 200
    return cast(dict[str, object], response.json())


def create_user_with_headers(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> tuple[dict[str, object], dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    response = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=superuser_token_headers,
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return response.json(), user_authentication_headers(
        client=client, email=email, password=password
    )


def grant_membership(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    project_id: object,
    user_id: object,
    roles: list[str],
) -> dict[str, object]:
    response = client.post(
        f"{settings.API_V1_STR}/projects/{project_id}/memberships/",
        headers=superuser_token_headers,
        json={"user_id": user_id, "roles": roles},
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def test_admin_grants_combined_roles_and_lists_membership_with_one_audit_event(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    project = create_project(client, superuser_token_headers)
    user = create_ordinary_user(client, superuser_token_headers)

    grant_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/",
        headers={**superuser_token_headers, "X-Real-IP": "203.0.113.18"},
        json={"user_id": user["id"], "roles": ["operator", "approver"]},
    )

    assert grant_response.status_code == 201
    membership = grant_response.json()
    assert membership["project_id"] == project["id"]
    assert membership["user_id"] == user["id"]
    assert membership["roles"] == ["operator", "approver"]
    assert membership["revoked_at"] is None

    list_response = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/",
        headers=superuser_token_headers,
    )
    assert list_response.status_code == 200
    assert list_response.json() == {"data": [membership], "count": 1}

    audit_response = client.get(
        f"{settings.API_V1_STR}/audit-events/", headers=superuser_token_headers
    )
    matching_events = [
        event
        for event in audit_response.json()["data"]
        if event["target_id"] == membership["id"]
    ]
    assert len(matching_events) == 1
    assert matching_events[0]["action"] == "project_membership.granted"
    assert matching_events[0]["target_type"] == "project_membership"
    assert matching_events[0]["before_data"] is None
    assert matching_events[0]["after_data"] == {
        "user_id": user["id"],
        "roles": ["operator", "approver"],
        "status": "active",
    }
    assert matching_events[0]["ip_address"] == "203.0.113.18"


@pytest.mark.parametrize("role", ["viewer", "operator", "approver"])
def test_project_roles_read_only_their_active_membership_projects(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    role: str,
) -> None:
    allowed_project = create_project(client, superuser_token_headers)
    hidden_project = create_project(client, superuser_token_headers)
    user, user_headers = create_user_with_headers(client, superuser_token_headers)
    grant_membership(
        client,
        superuser_token_headers,
        allowed_project["id"],
        user["id"],
        [role],
    )

    list_response = client.get(f"{settings.API_V1_STR}/projects/", headers=user_headers)
    allowed_response = client.get(
        f"{settings.API_V1_STR}/projects/{allowed_project['id']}",
        headers=user_headers,
    )
    hidden_response = client.get(
        f"{settings.API_V1_STR}/projects/{hidden_project['id']}",
        headers=user_headers,
    )

    assert list_response.status_code == 200
    assert list_response.json() == {"data": [allowed_project], "count": 1}
    assert allowed_response.status_code == 200
    assert allowed_response.json() == allowed_project
    assert hidden_response.status_code == 404


def test_admin_changes_revokes_and_explicitly_regrants_membership(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project = create_project(client, superuser_token_headers)
    user, user_headers = create_user_with_headers(client, superuser_token_headers)
    membership = grant_membership(
        client,
        superuser_token_headers,
        project["id"],
        user["id"],
        ["viewer"],
    )

    update_response = client.patch(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/{membership['id']}",
        headers=superuser_token_headers,
        json={"roles": ["operator", "approver"]},
    )
    assert update_response.status_code == 200
    assert update_response.json()["roles"] == ["operator", "approver"]

    revoke_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/{membership['id']}/revoke",
        headers=superuser_token_headers,
    )
    assert revoke_response.status_code == 200
    assert revoke_response.json()["roles"] == ["operator", "approver"]
    assert revoke_response.json()["revoked_at"] is not None
    assert (
        client.get(f"{settings.API_V1_STR}/projects/", headers=user_headers).json()[
            "count"
        ]
        == 0
    )
    assert (
        client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}", headers=user_headers
        ).status_code
        == 404
    )

    rejected_regrant = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/{membership['id']}/regrant",
        headers=superuser_token_headers,
        json={},
    )
    assert rejected_regrant.status_code == 422

    regrant_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/{membership['id']}/regrant",
        headers=superuser_token_headers,
        json={"roles": ["approver"]},
    )
    assert regrant_response.status_code == 200
    assert regrant_response.json()["roles"] == ["approver"]
    assert regrant_response.json()["revoked_at"] is None
    assert (
        client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}", headers=user_headers
        ).status_code
        == 200
    )

    audit_response = client.get(
        f"{settings.API_V1_STR}/audit-events/", headers=superuser_token_headers
    )
    membership_events = [
        event
        for event in reversed(audit_response.json()["data"])
        if event["target_id"] == membership["id"]
    ]
    assert [event["action"] for event in membership_events] == [
        "project_membership.granted",
        "project_membership.roles_changed",
        "project_membership.revoked",
        "project_membership.regranted",
    ]
    assert membership_events[1]["before_data"] == {
        "user_id": user["id"],
        "roles": ["viewer"],
        "status": "active",
    }
    assert membership_events[1]["after_data"] == {
        "user_id": user["id"],
        "roles": ["operator", "approver"],
        "status": "active",
    }
    assert membership_events[2]["before_data"]["status"] == "active"
    assert membership_events[2]["after_data"]["status"] == "revoked"
    assert membership_events[3]["before_data"] == {
        "user_id": user["id"],
        "roles": ["operator", "approver"],
        "status": "revoked",
    }
    assert membership_events[3]["after_data"] == {
        "user_id": user["id"],
        "roles": ["approver"],
        "status": "active",
    }


@pytest.mark.parametrize(
    "roles",
    [[], ["owner"], ["viewer", "viewer"]],
    ids=["empty", "unknown", "duplicate"],
)
def test_membership_api_rejects_invalid_role_sets(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    roles: list[str],
) -> None:
    project = create_project(client, superuser_token_headers)
    user = create_ordinary_user(client, superuser_token_headers)

    response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/",
        headers=superuser_token_headers,
        json={"user_id": user["id"], "roles": roles},
    )

    assert response.status_code == 422
    list_response = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/",
        headers=superuser_token_headers,
    )
    assert list_response.json() == {"data": [], "count": 0}


def test_project_membership_is_unique_and_cannot_target_global_admin(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project = create_project(client, superuser_token_headers)
    user = create_ordinary_user(client, superuser_token_headers)
    membership = grant_membership(
        client,
        superuser_token_headers,
        project["id"],
        user["id"],
        ["viewer"],
    )

    duplicate_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/",
        headers=superuser_token_headers,
        json={"user_id": user["id"], "roles": ["operator"]},
    )
    admin_response = client.get(
        f"{settings.API_V1_STR}/users/me", headers=superuser_token_headers
    )
    admin_membership_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/",
        headers=superuser_token_headers,
        json={"user_id": admin_response.json()["id"], "roles": ["viewer"]},
    )

    assert duplicate_response.status_code == 409
    assert admin_membership_response.status_code == 409
    list_response = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/",
        headers=superuser_token_headers,
    )
    assert list_response.json() == {"data": [membership], "count": 1}


def test_archived_project_remains_readable_but_blocks_membership_changes(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project = create_project(client, superuser_token_headers)
    active_user, active_headers = create_user_with_headers(
        client, superuser_token_headers
    )
    active_membership = grant_membership(
        client,
        superuser_token_headers,
        project["id"],
        active_user["id"],
        ["viewer"],
    )
    revoked_user = create_ordinary_user(client, superuser_token_headers)
    revoked_membership = grant_membership(
        client,
        superuser_token_headers,
        project["id"],
        revoked_user["id"],
        ["operator"],
    )
    revoke_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/{revoked_membership['id']}/revoke",
        headers=superuser_token_headers,
    )
    assert revoke_response.status_code == 200
    new_user = create_ordinary_user(client, superuser_token_headers)
    archive_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/archive",
        headers=superuser_token_headers,
    )
    assert archive_response.status_code == 200

    grant_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/",
        headers=superuser_token_headers,
        json={"user_id": new_user["id"], "roles": ["viewer"]},
    )
    update_response = client.patch(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/{active_membership['id']}",
        headers=superuser_token_headers,
        json={"roles": ["approver"]},
    )
    revoke_active_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/{active_membership['id']}/revoke",
        headers=superuser_token_headers,
    )
    regrant_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/{revoked_membership['id']}/regrant",
        headers=superuser_token_headers,
        json={"roles": ["approver"]},
    )

    assert grant_response.status_code == 409
    assert update_response.status_code == 409
    assert revoke_active_response.status_code == 409
    assert regrant_response.status_code == 409
    member_read_response = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}", headers=active_headers
    )
    assert member_read_response.status_code == 200
    assert member_read_response.json()["archived_at"] is not None
    list_response = client.get(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/",
        headers=superuser_token_headers,
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 2


def test_account_reactivation_restores_only_still_active_memberships(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project = create_project(client, superuser_token_headers)
    active_user, active_headers = create_user_with_headers(
        client, superuser_token_headers
    )
    revoked_user, revoked_headers = create_user_with_headers(
        client, superuser_token_headers
    )
    grant_membership(
        client,
        superuser_token_headers,
        project["id"],
        active_user["id"],
        ["viewer"],
    )
    revoked_membership = grant_membership(
        client,
        superuser_token_headers,
        project["id"],
        revoked_user["id"],
        ["viewer"],
    )
    revoke_response = client.post(
        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/{revoked_membership['id']}/revoke",
        headers=superuser_token_headers,
    )
    assert revoke_response.status_code == 200

    for user in (active_user, revoked_user):
        deactivate_response = client.patch(
            f"{settings.API_V1_STR}/users/{user['id']}",
            headers=superuser_token_headers,
            json={"is_active": False},
        )
        assert deactivate_response.status_code == 200
    assert (
        client.get(
            f"{settings.API_V1_STR}/projects/", headers=active_headers
        ).status_code
        == 400
    )
    assert (
        client.get(
            f"{settings.API_V1_STR}/projects/", headers=revoked_headers
        ).status_code
        == 400
    )

    for user in (active_user, revoked_user):
        reactivate_response = client.patch(
            f"{settings.API_V1_STR}/users/{user['id']}",
            headers=superuser_token_headers,
            json={"is_active": True},
        )
        assert reactivate_response.status_code == 200

    assert (
        client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}", headers=active_headers
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"{settings.API_V1_STR}/projects/{project['id']}", headers=revoked_headers
        ).status_code
        == 404
    )


def test_membership_change_waits_for_concurrent_archive_and_is_rejected(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project = create_project(client, superuser_token_headers)
    user = create_ordinary_user(client, superuser_token_headers)
    membership = grant_membership(
        client,
        superuser_token_headers,
        project["id"],
        user["id"],
        ["viewer"],
    )
    project_id = uuid.UUID(str(project["id"]))

    with Session(engine) as archive_session:
        locked_project = archive_session.exec(
            select(Project).where(Project.id == project_id).with_for_update()
        ).one()
        locked_project.archived_at = get_datetime_utc()
        archive_session.add(locked_project)
        archive_session.flush()

        def change_roles() -> int:
            with TestClient(app, client=("127.0.0.1", 50014)) as request_client:
                return int(
                    request_client.patch(
                        f"{settings.API_V1_STR}/projects/{project['id']}/memberships/{membership['id']}",
                        headers=superuser_token_headers,
                        json={"roles": ["operator"]},
                    ).status_code
                )

        with ThreadPoolExecutor(max_workers=1) as executor:
            response_future = executor.submit(change_roles)
            with pytest.raises(TimeoutError):
                response_future.result(timeout=0.2)
            archive_session.commit()
            assert response_future.result(timeout=5) == 409


def test_audit_failure_rolls_back_every_membership_change(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    project = create_project(client, superuser_token_headers)
    user = create_ordinary_user(client, superuser_token_headers)
    membership_path = f"{settings.API_V1_STR}/projects/{project['id']}/memberships"

    audit_count = db.exec(select(func.count()).select_from(AuditEvent)).one()
    with reject_audit_inserts(db):
        with TestClient(
            app, raise_server_exceptions=False, client=("127.0.0.1", 50010)
        ) as failure_client:
            grant_response = failure_client.post(
                f"{membership_path}/",
                headers=superuser_token_headers,
                json={"user_id": user["id"], "roles": ["viewer"]},
            )
        assert grant_response.status_code == 500
    db.expire_all()
    assert (
        db.exec(
            select(ProjectMembership).where(
                ProjectMembership.project_id == uuid.UUID(str(project["id"])),
                ProjectMembership.user_id == uuid.UUID(str(user["id"])),
            )
        ).one_or_none()
        is None
    )
    assert db.exec(select(func.count()).select_from(AuditEvent)).one() == audit_count

    membership = grant_membership(
        client,
        superuser_token_headers,
        project["id"],
        user["id"],
        ["viewer"],
    )
    membership_id = uuid.UUID(str(membership["id"]))

    audit_count = db.exec(select(func.count()).select_from(AuditEvent)).one()
    with reject_audit_inserts(db):
        with TestClient(
            app, raise_server_exceptions=False, client=("127.0.0.1", 50011)
        ) as failure_client:
            update_response = failure_client.patch(
                f"{membership_path}/{membership['id']}",
                headers=superuser_token_headers,
                json={"roles": ["operator"]},
            )
        assert update_response.status_code == 500
    db.expire_all()
    persisted_membership = db.get(ProjectMembership, membership_id)
    assert persisted_membership is not None
    assert persisted_membership.roles == ["viewer"]
    assert db.exec(select(func.count()).select_from(AuditEvent)).one() == audit_count

    with reject_audit_inserts(db):
        with TestClient(
            app, raise_server_exceptions=False, client=("127.0.0.1", 50012)
        ) as failure_client:
            revoke_response = failure_client.post(
                f"{membership_path}/{membership['id']}/revoke",
                headers=superuser_token_headers,
            )
        assert revoke_response.status_code == 500
    db.expire_all()
    persisted_membership = db.get(ProjectMembership, membership_id)
    assert persisted_membership is not None
    assert persisted_membership.revoked_at is None
    assert db.exec(select(func.count()).select_from(AuditEvent)).one() == audit_count

    successful_revoke = client.post(
        f"{membership_path}/{membership['id']}/revoke",
        headers=superuser_token_headers,
    )
    assert successful_revoke.status_code == 200
    revoked_at = successful_revoke.json()["revoked_at"]
    audit_count = db.exec(select(func.count()).select_from(AuditEvent)).one()

    with reject_audit_inserts(db):
        with TestClient(
            app, raise_server_exceptions=False, client=("127.0.0.1", 50013)
        ) as failure_client:
            regrant_response = failure_client.post(
                f"{membership_path}/{membership['id']}/regrant",
                headers=superuser_token_headers,
                json={"roles": ["approver"]},
            )
        assert regrant_response.status_code == 500
    db.expire_all()
    persisted_membership = db.get(ProjectMembership, membership_id)
    assert persisted_membership is not None
    assert persisted_membership.roles == ["viewer"]
    assert persisted_membership.revoked_at is not None
    assert persisted_membership.revoked_at == datetime.fromisoformat(revoked_at)
    assert db.exec(select(func.count()).select_from(AuditEvent)).one() == audit_count
