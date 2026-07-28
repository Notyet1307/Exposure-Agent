import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, func, select

from app.core.config import settings
from app.main import app
from app.models import AuditEvent, Project


def test_admin_can_create_and_read_project_without_source_configuration(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    name = f"Project {uuid.uuid4()}"

    create_response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=superuser_token_headers,
        json={"name": name},
    )

    assert create_response.status_code == 201
    created_project = create_response.json()
    assert created_project["name"] == name
    assert uuid.UUID(created_project["id"])

    read_response = client.get(
        f"{settings.API_V1_STR}/projects/{created_project['id']}",
        headers=superuser_token_headers,
    )
    assert read_response.status_code == 200
    assert read_response.json() == created_project


def test_project_creation_emits_one_sanitized_audit_event(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    actor_response = client.get(
        f"{settings.API_V1_STR}/users/me", headers=superuser_token_headers
    )
    assert actor_response.status_code == 200
    actor_id = actor_response.json()["id"]
    name = f"Audited Project {uuid.uuid4()}"

    create_response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers={**superuser_token_headers, "X-Real-IP": "203.0.113.7"},
        json={"name": name},
    )
    assert create_response.status_code == 201
    project = create_response.json()

    audit_response = client.get(
        f"{settings.API_V1_STR}/audit-events/", headers=superuser_token_headers
    )
    assert audit_response.status_code == 200
    matching_events = [
        event
        for event in audit_response.json()["data"]
        if event["target_id"] == project["id"]
    ]
    assert len(matching_events) == 1
    event = matching_events[0]
    assert event["tenant_id"] == project["tenant_id"]
    assert event["project_id"] == project["id"]
    assert event["actor_subject"] == actor_id
    assert event["actor_type"] == "user"
    assert event["action"] == "project.created"
    assert event["target_type"] == "project"
    assert event["before_data"] is None
    assert event["after_data"] == {"name": name}
    assert event["ip_address"] == "203.0.113.7"
    assert event["occurred_at"]


def test_admin_can_rename_project_with_immutable_id_and_one_audit_event(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    original_name = f"Original {uuid.uuid4()}"
    renamed_name = f"Renamed {uuid.uuid4()}"
    create_response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=superuser_token_headers,
        json={"name": original_name},
    )
    assert create_response.status_code == 201
    original_project = create_response.json()

    rename_response = client.patch(
        f"{settings.API_V1_STR}/projects/{original_project['id']}",
        headers=superuser_token_headers,
        json={"name": renamed_name},
    )

    assert rename_response.status_code == 200
    renamed_project = rename_response.json()
    assert renamed_project["id"] == original_project["id"]
    assert renamed_project["tenant_id"] == original_project["tenant_id"]
    assert renamed_project["created_at"] == original_project["created_at"]
    assert renamed_project["name"] == renamed_name

    audit_response = client.get(
        f"{settings.API_V1_STR}/audit-events/", headers=superuser_token_headers
    )
    assert audit_response.status_code == 200
    project_events = [
        event
        for event in audit_response.json()["data"]
        if event["target_id"] == original_project["id"]
    ]
    assert [event["action"] for event in project_events] == [
        "project.renamed",
        "project.created",
    ]
    rename_event = project_events[0]
    assert rename_event["before_data"] == {"name": original_name}
    assert rename_event["after_data"] == {"name": renamed_name}


def test_admin_can_list_multiple_independent_projects_with_the_same_name(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    shared_name = f"Shared Name {uuid.uuid4()}"
    created_ids = []
    for _ in range(2):
        create_response = client.post(
            f"{settings.API_V1_STR}/projects/",
            headers=superuser_token_headers,
            json={"name": shared_name},
        )
        assert create_response.status_code == 201
        created_ids.append(create_response.json()["id"])

    list_response = client.get(
        f"{settings.API_V1_STR}/projects/",
        headers=superuser_token_headers,
        params={"skip": 0, "limit": 100},
    )

    assert list_response.status_code == 200
    payload = list_response.json()
    matching_projects = [
        project for project in payload["data"] if project["name"] == shared_name
    ]
    assert {project["id"] for project in matching_projects} == set(created_ids)
    assert payload["count"] >= 2


def test_ordinary_user_cannot_discover_projects_or_read_raw_audit_events(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=superuser_token_headers,
        json={"name": f"Private Project {uuid.uuid4()}"},
    )
    assert create_response.status_code == 201
    project_id = create_response.json()["id"]

    list_response = client.get(
        f"{settings.API_V1_STR}/projects/", headers=normal_user_token_headers
    )
    read_response = client.get(
        f"{settings.API_V1_STR}/projects/{project_id}",
        headers=normal_user_token_headers,
    )
    audit_response = client.get(
        f"{settings.API_V1_STR}/audit-events/", headers=normal_user_token_headers
    )

    assert list_response.status_code == 403
    assert read_response.status_code == 403
    assert audit_response.status_code == 403


def test_audit_insert_failure_rolls_back_project_creation(
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    name = f"Rolled Back {uuid.uuid4()}"
    audit_count_before = db.exec(select(func.count()).select_from(AuditEvent)).one()
    db.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION fail_test_audit_insert()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'test audit failure';
            END;
            $$
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TRIGGER fail_test_audit_insert
            BEFORE INSERT ON audit_events
            FOR EACH ROW EXECUTE FUNCTION fail_test_audit_insert()
            """
        )
    )
    db.commit()

    try:
        with TestClient(
            app,
            raise_server_exceptions=False,
            client=("127.0.0.1", 50001),
        ) as failure_client:
            response = failure_client.post(
                f"{settings.API_V1_STR}/projects/",
                headers=superuser_token_headers,
                json={"name": name},
            )

        assert response.status_code == 500
        db.expire_all()
        assert db.exec(select(Project).where(Project.name == name)).first() is None
        audit_count_after = db.exec(select(func.count()).select_from(AuditEvent)).one()
        assert audit_count_after == audit_count_before
    finally:
        db.rollback()
        db.execute(
            text("DROP TRIGGER IF EXISTS fail_test_audit_insert ON audit_events")
        )
        db.execute(text("DROP FUNCTION IF EXISTS fail_test_audit_insert()"))
        db.commit()


def test_failed_project_rename_does_not_emit_success_event(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    missing_project_id = str(uuid.uuid4())

    rename_response = client.patch(
        f"{settings.API_V1_STR}/projects/{missing_project_id}",
        headers=superuser_token_headers,
        json={"name": "Still missing"},
    )
    audit_response = client.get(
        f"{settings.API_V1_STR}/audit-events/", headers=superuser_token_headers
    )

    assert rename_response.status_code == 404
    assert audit_response.status_code == 200
    assert all(
        event["target_id"] != missing_project_id
        for event in audit_response.json()["data"]
    )


def test_openapi_exposes_supported_project_and_read_only_audit_contracts(
    client: TestClient,
) -> None:
    response = client.get(f"{settings.API_V1_STR}/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert set(paths[f"{settings.API_V1_STR}/projects/"]) == {"get", "post"}
    assert set(paths[f"{settings.API_V1_STR}/projects/{{project_id}}"]) == {
        "get",
        "patch",
    }
    assert set(paths[f"{settings.API_V1_STR}/audit-events/"]) == {"get"}
    assert not any("tenant" in path for path in paths)
