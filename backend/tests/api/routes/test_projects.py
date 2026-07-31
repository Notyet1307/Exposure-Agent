import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import ProgrammingError
from sqlmodel import Session, func, select

from app.core.config import settings
from app.domain.models import AuditEvent, Project
from app.main import app
from tests.utils.audit import reject_audit_inserts


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
    assert event["created_at"]
    assert event["updated_at"]


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


def test_admin_can_archive_project_idempotently_and_still_read_it(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    name = f"Archive Me {uuid.uuid4()}"
    create_response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=superuser_token_headers,
        json={"name": name},
    )
    assert create_response.status_code == 201
    active_project = create_response.json()
    assert active_project["archived_at"] is None

    archive_response = client.post(
        f"{settings.API_V1_STR}/projects/{active_project['id']}/archive",
        headers=superuser_token_headers,
    )

    assert archive_response.status_code == 200
    archived_project = archive_response.json()
    assert archived_project["id"] == active_project["id"]
    assert archived_project["name"] == name
    assert archived_project["created_at"] == active_project["created_at"]
    assert archived_project["archived_at"] is not None

    read_response = client.get(
        f"{settings.API_V1_STR}/projects/{active_project['id']}",
        headers=superuser_token_headers,
    )
    assert read_response.status_code == 200
    assert read_response.json() == archived_project

    repeated_response = client.post(
        f"{settings.API_V1_STR}/projects/{active_project['id']}/archive",
        headers=superuser_token_headers,
    )
    assert repeated_response.status_code == 200
    assert repeated_response.json() == archived_project

    audit_response = client.get(
        f"{settings.API_V1_STR}/audit-events/", headers=superuser_token_headers
    )
    project_events = [
        event
        for event in audit_response.json()["data"]
        if event["target_id"] == active_project["id"]
    ]
    assert [event["action"] for event in project_events] == [
        "project.archived",
        "project.created",
    ]
    archive_event = project_events[0]
    assert archive_event["before_data"] == {"name": name, "archived_at": None}
    assert archive_event["after_data"]["name"] == name
    assert datetime.fromisoformat(
        archive_event["after_data"]["archived_at"]
    ) == datetime.fromisoformat(archived_project["archived_at"])


def test_archived_project_rejects_rename_without_emitting_audit_event(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    original_name = f"Frozen {uuid.uuid4()}"
    create_response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=superuser_token_headers,
        json={"name": original_name},
    )
    project_id = create_response.json()["id"]
    archive_response = client.post(
        f"{settings.API_V1_STR}/projects/{project_id}/archive",
        headers=superuser_token_headers,
    )
    assert archive_response.status_code == 200

    rename_response = client.patch(
        f"{settings.API_V1_STR}/projects/{project_id}",
        headers=superuser_token_headers,
        json={"name": "Forbidden rename"},
    )

    assert rename_response.status_code == 409
    assert rename_response.json() == {"detail": "Archived project is read-only"}
    read_response = client.get(
        f"{settings.API_V1_STR}/projects/{project_id}",
        headers=superuser_token_headers,
    )
    assert read_response.json()["name"] == original_name
    audit_response = client.get(
        f"{settings.API_V1_STR}/audit-events/", headers=superuser_token_headers
    )
    assert [
        event["action"]
        for event in audit_response.json()["data"]
        if event["target_id"] == project_id
    ] == ["project.archived", "project.created"]


def test_admin_can_reactivate_project_idempotently_and_then_rename_it(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    name = f"Recover Me {uuid.uuid4()}"
    create_response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=superuser_token_headers,
        json={"name": name},
    )
    active_project = create_response.json()
    archive_response = client.post(
        f"{settings.API_V1_STR}/projects/{active_project['id']}/archive",
        headers=superuser_token_headers,
    )
    archived_project = archive_response.json()

    reactivate_response = client.post(
        f"{settings.API_V1_STR}/projects/{active_project['id']}/reactivate",
        headers=superuser_token_headers,
    )

    assert reactivate_response.status_code == 200
    reactivated_project = reactivate_response.json()
    assert reactivated_project["id"] == active_project["id"]
    assert reactivated_project["name"] == name
    assert reactivated_project["created_at"] == active_project["created_at"]
    assert reactivated_project["archived_at"] is None

    repeated_response = client.post(
        f"{settings.API_V1_STR}/projects/{active_project['id']}/reactivate",
        headers=superuser_token_headers,
    )
    assert repeated_response.status_code == 200
    assert repeated_response.json() == reactivated_project

    audit_response = client.get(
        f"{settings.API_V1_STR}/audit-events/", headers=superuser_token_headers
    )
    project_events = [
        event
        for event in audit_response.json()["data"]
        if event["target_id"] == active_project["id"]
    ]
    assert [event["action"] for event in project_events] == [
        "project.reactivated",
        "project.archived",
        "project.created",
    ]
    reactivation_event = project_events[0]
    assert reactivation_event["before_data"]["name"] == name
    assert datetime.fromisoformat(
        reactivation_event["before_data"]["archived_at"]
    ) == datetime.fromisoformat(archived_project["archived_at"])
    assert reactivation_event["after_data"] == {"name": name, "archived_at": None}

    rename_response = client.patch(
        f"{settings.API_V1_STR}/projects/{active_project['id']}",
        headers=superuser_token_headers,
        json={"name": "Recovered project"},
    )
    assert rename_response.status_code == 200
    assert rename_response.json()["name"] == "Recovered project"


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


def test_ordinary_user_sees_no_unassigned_projects_or_raw_audit_events(
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
    archive_response = client.post(
        f"{settings.API_V1_STR}/projects/{project_id}/archive",
        headers=normal_user_token_headers,
    )
    reactivate_response = client.post(
        f"{settings.API_V1_STR}/projects/{project_id}/reactivate",
        headers=normal_user_token_headers,
    )
    audit_response = client.get(
        f"{settings.API_V1_STR}/audit-events/", headers=normal_user_token_headers
    )

    assert list_response.status_code == 200
    assert list_response.json() == {"data": [], "count": 0}
    assert read_response.status_code == 404
    assert archive_response.status_code == 403
    assert reactivate_response.status_code == 403
    assert audit_response.status_code == 403


def test_audit_insert_failure_rolls_back_project_creation(
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    name = f"Rolled Back {uuid.uuid4()}"
    audit_count_before = db.exec(select(func.count()).select_from(AuditEvent)).one()

    with reject_audit_inserts(db):
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


def test_audit_insert_failure_rolls_back_project_archive(
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    with TestClient(app, client=("127.0.0.1", 50004)) as setup_client:
        create_response = setup_client.post(
            f"{settings.API_V1_STR}/projects/",
            headers=superuser_token_headers,
            json={"name": f"Archive Rollback {uuid.uuid4()}"},
        )
    project_id = uuid.UUID(create_response.json()["id"])
    audit_count_before = db.exec(select(func.count()).select_from(AuditEvent)).one()

    with reject_audit_inserts(db):
        with TestClient(
            app,
            raise_server_exceptions=False,
            client=("127.0.0.1", 50005),
        ) as failure_client:
            response = failure_client.post(
                f"{settings.API_V1_STR}/projects/{project_id}/archive",
                headers=superuser_token_headers,
            )
        assert response.status_code == 500

    db.expire_all()
    project = db.get(Project, project_id)
    assert project is not None
    assert project.archived_at is None
    audit_count_after = db.exec(select(func.count()).select_from(AuditEvent)).one()
    assert audit_count_after == audit_count_before


def test_audit_insert_failure_rolls_back_project_reactivation(
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    with TestClient(app, client=("127.0.0.1", 50006)) as setup_client:
        create_response = setup_client.post(
            f"{settings.API_V1_STR}/projects/",
            headers=superuser_token_headers,
            json={"name": f"Reactivate Rollback {uuid.uuid4()}"},
        )
        project_id = uuid.UUID(create_response.json()["id"])
        archive_response = setup_client.post(
            f"{settings.API_V1_STR}/projects/{project_id}/archive",
            headers=superuser_token_headers,
        )
    archived_at = datetime.fromisoformat(archive_response.json()["archived_at"])
    audit_count_before = db.exec(select(func.count()).select_from(AuditEvent)).one()

    with reject_audit_inserts(db):
        with TestClient(
            app,
            raise_server_exceptions=False,
            client=("127.0.0.1", 50007),
        ) as failure_client:
            response = failure_client.post(
                f"{settings.API_V1_STR}/projects/{project_id}/reactivate",
                headers=superuser_token_headers,
            )
        assert response.status_code == 500

    db.expire_all()
    project = db.get(Project, project_id)
    assert project is not None
    assert project.archived_at == archived_at
    audit_count_after = db.exec(select(func.count()).select_from(AuditEvent)).one()
    assert audit_count_after == audit_count_before


def test_audit_insert_failure_rolls_back_project_rename(
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    original_name = f"Original Rollback {uuid.uuid4()}"
    with TestClient(app, client=("127.0.0.1", 50002)) as setup_client:
        create_response = setup_client.post(
            f"{settings.API_V1_STR}/projects/",
            headers=superuser_token_headers,
            json={"name": original_name},
        )
    assert create_response.status_code == 201
    project_id = uuid.UUID(create_response.json()["id"])
    audit_count_before = db.exec(select(func.count()).select_from(AuditEvent)).one()

    with reject_audit_inserts(db):
        with TestClient(
            app,
            raise_server_exceptions=False,
            client=("127.0.0.1", 50003),
        ) as failure_client:
            response = failure_client.patch(
                f"{settings.API_V1_STR}/projects/{project_id}",
                headers=superuser_token_headers,
                json={"name": "This must roll back"},
            )

        assert response.status_code == 500

    db.expire_all()
    project = db.get(Project, project_id)
    assert project is not None
    assert project.name == original_name
    audit_count_after = db.exec(select(func.count()).select_from(AuditEvent)).one()
    assert audit_count_after == audit_count_before


def test_audit_events_cannot_be_modified_after_insertion(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    create_response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=superuser_token_headers,
        json={"name": f"Immutable Audit {uuid.uuid4()}"},
    )
    assert create_response.status_code == 201
    project_id = uuid.UUID(create_response.json()["id"])
    audit_event = db.exec(
        select(AuditEvent).where(AuditEvent.project_id == project_id)
    ).one()

    audit_event.action = "tampered"
    db.add(audit_event)
    try:
        with pytest.raises(ProgrammingError, match="audit_events is append-only"):
            db.commit()
    finally:
        db.rollback()


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
    assert set(
        paths[
            f"{settings.API_V1_STR}/projects/{{project_id}}/customer-upload-profile"
        ]
    ) == {"get"}
    customer_uploads_path = (
        f"{settings.API_V1_STR}/projects/{{project_id}}/customer-uploads"
    )
    assert set(paths[customer_uploads_path]) == {"get", "post"}
    upload_file_schema = paths[customer_uploads_path]["post"]["requestBody"][
        "content"
    ]["multipart/form-data"]["schema"]["properties"]["file"]
    assert upload_file_schema["type"] == "string"
    assert upload_file_schema["format"] == "binary"
    select_upload_path = f"{customer_uploads_path}/{{upload_id}}/select"
    assert set(paths[select_upload_path]) == {"post"}
    assert set(paths[f"{settings.API_V1_STR}/projects/{{project_id}}/archive"]) == {
        "post"
    }
    assert set(paths[f"{settings.API_V1_STR}/projects/{{project_id}}/reactivate"]) == {
        "post"
    }
    assert not any(
        "delete" in path_operations
        for path, path_operations in paths.items()
        if path.startswith(f"{settings.API_V1_STR}/projects")
    )
    membership_path = f"{settings.API_V1_STR}/projects/{{project_id}}/memberships"
    assert set(paths[f"{membership_path}/"]) == {"get", "post"}
    assert set(paths[f"{membership_path}/{{membership_id}}"]) == {"patch"}
    assert set(paths[f"{membership_path}/{{membership_id}}/revoke"]) == {"post"}
    assert set(paths[f"{membership_path}/{{membership_id}}/regrant"]) == {"post"}
    assert not any(
        "delete" in path_operations
        for path, path_operations in paths.items()
        if "/memberships" in path
    )
    assert response.json()["components"]["schemas"]["ProjectRole"]["enum"] == [
        "viewer",
        "operator",
        "approver",
    ]
    assert set(paths[f"{settings.API_V1_STR}/audit-events/"]) == {"get"}
    assert not any("tenant" in path for path in paths)
