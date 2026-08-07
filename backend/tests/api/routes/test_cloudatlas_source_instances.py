import hashlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any, cast

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import text
from sqlmodel import Session, col, func, select

from app.core.config import settings
from app.domain.models import AuditEvent, SourceInstance
from app.main import app
from tests.utils.audit import reject_audit_inserts
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string

SERVICE_ID = "cloudatlas-read"
METHOD = "cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets"
PACKAGE_SHA256 = "1d487b2773d0dc2457d5c552d5a5d9cd34b4e7c732f9a810cf0115cdab3f069c"
DESCRIPTOR_SHA256 = "3fada7cb00f3bca132c28d316ea61158522a1a07d3e80a83f9e68010d1a588e0"
CAPSET_TOKEN = "fixture-capset-token"


class _OctobusState:
    def __init__(self) -> None:
        self.instance_id = "cloudatlas-fixture"
        self.capset_id = "cloudatlas-readonly"
        self.package_sha256 = PACKAGE_SHA256
        self.descriptor_sha256 = DESCRIPTOR_SHA256
        self.config_sha256 = "1" * 64
        self.secret_sha256 = "2" * 64
        self.binding_instance_id = self.instance_id
        self.include_all_methods = False
        self.selected_method = METHOD
        self.token_hash = hashlib.sha256(CAPSET_TOKEN.encode()).hexdigest()
        self.connect_status = 200
        self.connect_error = "cloudatlas_authentication_failed"
        self.missing_path: str | None = None
        self.requests: list[dict[str, Any]] = []

    def response(self, path: str) -> dict[str, Any] | None:
        if path == self.missing_path:
            return None
        admin = "/admin/v1"
        if path == f"{admin}/services/{SERVICE_ID}":
            return {
                "ID": SERVICE_ID,
                "PackageSHA256": self.package_sha256,
                "PackageVersion": "",
                "DescriptorSHA256": self.descriptor_sha256,
            }
        if path == f"{admin}/instances/{self.instance_id}":
            return {
                "ID": self.instance_id,
                "ServiceID": SERVICE_ID,
                "ConfigSHA256": self.config_sha256,
                "SecretSHA256": self.secret_sha256,
            }
        if path == f"{admin}/capsets/{self.capset_id}":
            return {"ID": self.capset_id, "Enabled": True}
        if path == f"{admin}/capsets/{self.capset_id}/instances":
            return {
                "instances": [
                    {
                        "ServiceID": SERVICE_ID,
                        "InstanceID": self.binding_instance_id,
                        "Enabled": True,
                        "IncludeAllMethods": self.include_all_methods,
                    }
                ]
            }
        if path == f"{admin}/capsets/{self.capset_id}/methods":
            return {
                "methods": [
                    {"MethodFullName": self.selected_method, "Enabled": True}
                ]
            }
        if path == f"{admin}/capsets/{self.capset_id}/tokens":
            return {
                "tokens": [
                    {
                        "ID": "fixture-token",
                        "TokenHash": self.token_hash,
                    }
                ]
            }
        return None

    def fingerprint(self) -> str:
        material = {
            "schema": "exposure-agent.cloudatlas-source-fingerprint.v1",
            "service": {
                "id": SERVICE_ID,
                "package_sha256": PACKAGE_SHA256,
                "package_version": "",
                "descriptor_sha256": DESCRIPTOR_SHA256,
            },
            "instance": {
                "id": self.instance_id,
                "service_id": SERVICE_ID,
                "config_sha256": self.config_sha256,
                "secret_sha256": self.secret_sha256,
            },
            "capset": {
                "id": self.capset_id,
                "enabled": True,
                "token_bindings": [
                    {
                        "id": "fixture-token",
                        "token_hash": hashlib.sha256(
                            CAPSET_TOKEN.encode()
                        ).hexdigest(),
                    }
                ],
                "instances": [
                    {
                        "service_id": SERVICE_ID,
                        "instance_id": self.instance_id,
                        "enabled": True,
                        "include_all_methods": False,
                    }
                ],
                "methods": [{"name": METHOD, "enabled": True}],
            },
            "selected_method": METHOD,
        }
        encoded = json.dumps(
            material, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@contextmanager
def _octobus_server() -> Iterator[tuple[str, _OctobusState]]:
    state = _OctobusState()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            state.requests.append({"method": "GET", "path": self.path})
            payload = state.response(self.path)
            if payload is None:
                self.send_error(404)
                return
            self._json_response(200, payload)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            state.requests.append(
                {
                    "method": "POST",
                    "path": self.path,
                    "authorization": self.headers.get("authorization"),
                    "body": body,
                }
            )
            expected_path = (
                f"/capsets/{state.capset_id}/connect/{state.instance_id}/{METHOD}"
            )
            if self.path != expected_path:
                self.send_error(404)
                return
            if self.headers.get("authorization") != f"Bearer {CAPSET_TOKEN}":
                self._json_response(401, {"code": "unauthenticated"})
                return
            if state.connect_status != 200:
                self._json_response(
                    state.connect_status,
                    {"code": "upstream_error", "message": state.connect_error},
                )
                return
            self._json_response(
                200,
                {
                    "items": [
                        {
                            "id": "fixture-asset-1",
                            "ip": "192.0.2.10",
                            "status": "valid",
                        }
                    ],
                    "page": 1,
                    "size": 1,
                    "total": 1,
                },
            )

        def _json_response(self, status_code: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload).encode()
            self.send_response(status_code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format: str, *args: object) -> None:
            del args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = cast(tuple[str, int], server.server_address)
        yield f"http://{host}:{port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _create_project(
    client: TestClient, headers: dict[str, str], *, name: str = "CloudAtlas Project"
) -> dict[str, Any]:
    response = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=headers,
        json={"name": f"{name} {uuid.uuid4()}"},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


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


def _assert_source_audit_actions(
    client: TestClient,
    admin_headers: dict[str, str],
    *,
    source_id: str,
    expected: list[str],
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/audit-events/",
        headers=admin_headers,
    )
    assert response.status_code == 200
    actions = [
        event["action"]
        for event in response.json()["data"]
        if event["target_id"] == source_id
    ][::-1]
    assert actions == expected


def test_admin_configures_validates_and_enables_cloudatlas_source(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project = _create_project(client, superuser_token_headers)
    with _octobus_server() as (base_url, octobus):
        monkeypatch.setattr(settings, "OCTOBUS_URL", base_url, raising=False)
        collection_url = (
            f"{settings.API_V1_STR}/projects/{project['id']}"
            "/cloudatlas-source-instances"
        )

        create_response = client.post(
            collection_url,
            headers=superuser_token_headers,
            json={
                "instance_id": octobus.instance_id,
                "capset_id": octobus.capset_id,
            },
        )

        assert create_response.status_code == 201, create_response.text
        created = create_response.json()
        assert created == {
            "id": created["id"],
            "source_type": "cloudatlas",
            "instance_id": octobus.instance_id,
            "capset_id": octobus.capset_id,
            "enabled": False,
            "validation_status": "not_validated",
            "fingerprint_summary": None,
            "created_at": created["created_at"],
            "updated_at": created["updated_at"],
        }
        assert CAPSET_TOKEN not in create_response.text

        validate_response = client.post(
            f"{collection_url}/{created['id']}/validate",
            headers=superuser_token_headers,
            json={"capset_token": CAPSET_TOKEN},
        )

        assert validate_response.status_code == 200, validate_response.text
        validated = validate_response.json()
        assert validated["validation_status"] == "validated"
        assert validated["fingerprint_summary"] == octobus.fingerprint()[:12]
        assert CAPSET_TOKEN not in validate_response.text
        connect_requests = [
            request for request in octobus.requests if request["method"] == "POST"
        ]
        assert connect_requests == [
            {
                "method": "POST",
                "path": (
                    f"/capsets/{octobus.capset_id}/connect/"
                    f"{octobus.instance_id}/{METHOD}"
                ),
                "authorization": f"Bearer {CAPSET_TOKEN}",
                "body": {"status": "valid", "page": 1, "size": 1},
            }
        ]

        enable_response = client.post(
            f"{collection_url}/{created['id']}/enable",
            headers=superuser_token_headers,
        )

        assert enable_response.status_code == 200, enable_response.text
        assert enable_response.json()["enabled"] is True

    source_row = db.execute(
        text(
            "SELECT validated_fingerprint, validation_error_code "
            "FROM source_instances WHERE id = :source_id"
        ),
        {"source_id": uuid.UUID(created["id"])},
    ).one()
    assert source_row == (octobus.fingerprint(), None)
    audit_events = db.exec(
        select(AuditEvent)
        .where(AuditEvent.target_id == uuid.UUID(created["id"]))
        .order_by(col(AuditEvent.occurred_at))
    ).all()
    assert [event.action for event in audit_events] == [
        "source_instance.created",
        "source_instance.validated",
        "source_instance.enabled",
    ]
    serialized_audits = json.dumps(
        [
            {"before": event.before_data, "after": event.after_data}
            for event in audit_events
        ]
    )
    assert CAPSET_TOKEN not in serialized_audits
    assert "TokenHash" not in serialized_audits


def test_repeated_state_operations_are_audited(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project = _create_project(client, superuser_token_headers)
    with _octobus_server() as (base_url, octobus):
        monkeypatch.setattr(settings, "OCTOBUS_URL", base_url)
        collection_url = (
            f"{settings.API_V1_STR}/projects/{project['id']}"
            "/cloudatlas-source-instances"
        )
        source = client.post(
            collection_url,
            headers=superuser_token_headers,
            json={
                "instance_id": octobus.instance_id,
                "capset_id": octobus.capset_id,
            },
        ).json()
        source_url = f"{collection_url}/{source['id']}"
        assert client.post(
            f"{source_url}/validate",
            headers=superuser_token_headers,
            json={"capset_token": CAPSET_TOKEN},
        ).status_code == 200

        for action in ("enable", "enable", "disable", "disable"):
            assert client.post(
                f"{source_url}/{action}", headers=superuser_token_headers
            ).status_code == 200

    actions = db.exec(
        select(AuditEvent.action)
        .where(AuditEvent.target_id == uuid.UUID(source["id"]))
        .order_by(col(AuditEvent.occurred_at))
    ).all()
    assert actions == [
        "source_instance.created",
        "source_instance.validated",
        "source_instance.enabled",
        "source_instance.enabled",
        "source_instance.disabled",
        "source_instance.disabled",
    ]


def test_project_roles_only_receive_safe_summaries_for_their_own_project(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project = _create_project(client, superuser_token_headers)
    other_project = _create_project(client, superuser_token_headers)
    collection_url = (
        f"{settings.API_V1_STR}/projects/{project['id']}"
        "/cloudatlas-source-instances"
    )
    source = client.post(
        collection_url,
        headers=superuser_token_headers,
        json={"instance_id": "safe-instance", "capset_id": "safe-capset"},
    ).json()
    member_headers = [
        _create_member(
            client,
            superuser_token_headers,
            project_id=project["id"],
            roles=[role],
        )
        for role in ("operator", "viewer", "approver")
    ]

    read_responses = [
        client.get(collection_url, headers=headers) for headers in member_headers
    ]
    write_responses = [
        client.post(
            collection_url,
            headers=headers,
            json={"instance_id": "forbidden", "capset_id": "forbidden"},
        )
        for headers in member_headers
    ]
    cross_project_responses = [
        client.get(
            f"{settings.API_V1_STR}/projects/{other_project['id']}"
            "/cloudatlas-source-instances",
            headers=headers,
        )
        for headers in member_headers
    ]

    assert [response.status_code for response in read_responses] == [200, 200, 200]
    for response in read_responses:
        assert response.json() == {
            "data": [source],
            "count": 1,
            "can_manage": False,
        }
        assert set(response.json()["data"][0]) == {
            "id",
            "source_type",
            "instance_id",
            "capset_id",
            "enabled",
            "validation_status",
            "fingerprint_summary",
            "created_at",
            "updated_at",
        }
    assert [response.status_code for response in write_responses] == [403, 403, 403]
    assert [response.status_code for response in cross_project_responses] == [
        404,
        404,
        404,
    ]


def test_project_role_read_persists_drift_invalidation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project = _create_project(client, superuser_token_headers)
    viewer_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=project["id"],
        roles=["viewer"],
    )
    with _octobus_server() as (base_url, octobus):
        monkeypatch.setattr(settings, "OCTOBUS_URL", base_url)
        collection_url = (
            f"{settings.API_V1_STR}/projects/{project['id']}"
            "/cloudatlas-source-instances"
        )
        source = client.post(
            collection_url,
            headers=superuser_token_headers,
            json={
                "instance_id": octobus.instance_id,
                "capset_id": octobus.capset_id,
            },
        ).json()
        source_url = f"{collection_url}/{source['id']}"
        assert client.post(
            f"{source_url}/validate",
            headers=superuser_token_headers,
            json={"capset_token": CAPSET_TOKEN},
        ).status_code == 200

        octobus.secret_sha256 = "3" * 64
        drifted_response = client.get(collection_url, headers=viewer_headers)
        octobus.secret_sha256 = "2" * 64
        restored_response = client.get(collection_url, headers=viewer_headers)

    assert drifted_response.status_code == 200
    assert drifted_response.json()["data"][0]["validation_status"] == "invalid"
    assert restored_response.status_code == 200
    assert restored_response.json()["data"][0]["validation_status"] == "invalid"
    _assert_source_audit_actions(
        client,
        superuser_token_headers,
        source_id=source["id"],
        expected=[
            "source_instance.created",
            "source_instance.validated",
            "source_instance.validation_invalidated",
        ],
    )


def test_archived_project_read_persists_drift_invalidation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project = _create_project(client, superuser_token_headers)
    with _octobus_server() as (base_url, octobus):
        monkeypatch.setattr(settings, "OCTOBUS_URL", base_url)
        collection_url = (
            f"{settings.API_V1_STR}/projects/{project['id']}"
            "/cloudatlas-source-instances"
        )
        source = client.post(
            collection_url,
            headers=superuser_token_headers,
            json={
                "instance_id": octobus.instance_id,
                "capset_id": octobus.capset_id,
            },
        ).json()
        source_url = f"{collection_url}/{source['id']}"
        assert client.post(
            f"{source_url}/validate",
            headers=superuser_token_headers,
            json={"capset_token": CAPSET_TOKEN},
        ).status_code == 200
        assert client.post(
            f"{settings.API_V1_STR}/projects/{project['id']}/archive",
            headers=superuser_token_headers,
        ).status_code == 200

        octobus.secret_sha256 = "3" * 64
        drifted_response = client.get(
            collection_url, headers=superuser_token_headers
        )
        octobus.secret_sha256 = "2" * 64
        restored_response = client.get(
            collection_url, headers=superuser_token_headers
        )

    assert drifted_response.status_code == 200
    assert drifted_response.json()["data"][0]["validation_status"] == "invalid"
    assert drifted_response.json()["can_manage"] is False
    assert restored_response.status_code == 200
    assert restored_response.json()["data"][0]["validation_status"] == "invalid"
    _assert_source_audit_actions(
        client,
        superuser_token_headers,
        source_id=source["id"],
        expected=[
            "source_instance.created",
            "source_instance.validated",
            "source_instance.validation_invalidated",
        ],
    )


def test_fingerprint_drift_and_binding_changes_invalidate_validation(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project = _create_project(client, superuser_token_headers)
    with _octobus_server() as (base_url, octobus):
        monkeypatch.setattr(settings, "OCTOBUS_URL", base_url)
        collection_url = (
            f"{settings.API_V1_STR}/projects/{project['id']}"
            "/cloudatlas-source-instances"
        )
        source = client.post(
            collection_url,
            headers=superuser_token_headers,
            json={
                "instance_id": octobus.instance_id,
                "capset_id": octobus.capset_id,
            },
        ).json()
        source_url = f"{collection_url}/{source['id']}"
        assert client.post(
            f"{source_url}/validate",
            headers=superuser_token_headers,
            json={"capset_token": CAPSET_TOKEN},
        ).status_code == 200

        octobus.secret_sha256 = "3" * 64
        drifted_response = client.get(
            collection_url, headers=superuser_token_headers
        )
        enable_response = client.post(
            f"{source_url}/enable", headers=superuser_token_headers
        )

        assert drifted_response.status_code == 200
        assert drifted_response.json()["data"][0]["validation_status"] == "invalid"
        assert enable_response.status_code == 409
        assert enable_response.json()["detail"]["code"] == (
            "cloudatlas_validation_required"
        )

        update_response = client.patch(
            source_url,
            headers=superuser_token_headers,
            json={"instance_id": "replacement", "capset_id": "replacement-readonly"},
        )

    assert update_response.status_code == 200
    assert update_response.json()["validation_status"] == "not_validated"
    assert update_response.json()["fingerprint_summary"] is None
    source_row = db.execute(
        text(
            "SELECT instance_id, capset_id, enabled, validated_fingerprint, "
            "validated_at FROM source_instances WHERE id = :source_id"
        ),
        {"source_id": uuid.UUID(source["id"])},
    ).one()
    assert source_row == (
        "replacement",
        "replacement-readonly",
        False,
        None,
        None,
    )
    actions = db.exec(
        select(AuditEvent.action)
        .where(AuditEvent.target_id == uuid.UUID(source["id"]))
        .order_by(col(AuditEvent.occurred_at))
    ).all()
    assert actions == [
        "source_instance.created",
        "source_instance.validated",
        "source_instance.validation_invalidated",
        "source_instance.configured",
    ]
    invalidation_actor = db.exec(
        select(AuditEvent.actor_type, AuditEvent.actor_subject).where(
            AuditEvent.target_id == uuid.UUID(source["id"]),
            AuditEvent.action == "source_instance.validation_invalidated",
        )
    ).one()
    assert invalidation_actor == ("system", "octobus-control-plane")


def test_deleted_control_plane_material_requires_fresh_validation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project = _create_project(client, superuser_token_headers)
    with _octobus_server() as (base_url, octobus):
        monkeypatch.setattr(settings, "OCTOBUS_URL", base_url)
        collection_url = (
            f"{settings.API_V1_STR}/projects/{project['id']}"
            "/cloudatlas-source-instances"
        )
        source = client.post(
            collection_url,
            headers=superuser_token_headers,
            json={
                "instance_id": octobus.instance_id,
                "capset_id": octobus.capset_id,
            },
        ).json()
        source_url = f"{collection_url}/{source['id']}"
        assert client.post(
            f"{source_url}/validate",
            headers=superuser_token_headers,
            json={"capset_token": CAPSET_TOKEN},
        ).status_code == 200

        octobus.missing_path = f"/admin/v1/instances/{octobus.instance_id}"
        missing_response = client.get(
            collection_url, headers=superuser_token_headers
        )
        octobus.missing_path = None
        restored_response = client.get(
            collection_url, headers=superuser_token_headers
        )
        revalidated_response = client.post(
            f"{source_url}/validate",
            headers=superuser_token_headers,
            json={"capset_token": CAPSET_TOKEN},
        )

    assert missing_response.status_code == 200
    assert missing_response.json()["data"][0]["validation_status"] == "invalid"
    assert restored_response.status_code == 200
    assert restored_response.json()["data"][0]["validation_status"] == "invalid"
    assert revalidated_response.status_code == 200
    assert revalidated_response.json()["validation_status"] == "validated"


def test_control_plane_outage_does_not_claim_configuration_drift(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project = _create_project(client, superuser_token_headers)
    with _octobus_server() as (base_url, octobus):
        monkeypatch.setattr(settings, "OCTOBUS_URL", base_url)
        collection_url = (
            f"{settings.API_V1_STR}/projects/{project['id']}"
            "/cloudatlas-source-instances"
        )
        source = client.post(
            collection_url,
            headers=superuser_token_headers,
            json={
                "instance_id": octobus.instance_id,
                "capset_id": octobus.capset_id,
            },
        ).json()
        assert client.post(
            f"{collection_url}/{source['id']}/validate",
            headers=superuser_token_headers,
            json={"capset_token": CAPSET_TOKEN},
        ).status_code == 200

    outage_response = client.get(
        collection_url, headers=superuser_token_headers
    )

    assert outage_response.status_code == 200
    assert outage_response.json()["data"][0]["validation_status"] == "unavailable"
    db.expire_all()
    source_row = db.execute(
        text(
            "SELECT validated_fingerprint, validation_error_code "
            "FROM source_instances WHERE id = :source_id"
        ),
        {"source_id": uuid.UUID(source["id"])},
    ).one()
    assert source_row == (octobus.fingerprint(), None)


def test_every_constrained_material_change_invalidates_the_fingerprint(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project = _create_project(client, superuser_token_headers)
    with _octobus_server() as (base_url, octobus):
        monkeypatch.setattr(settings, "OCTOBUS_URL", base_url)
        collection_url = (
            f"{settings.API_V1_STR}/projects/{project['id']}"
            "/cloudatlas-source-instances"
        )
        source = client.post(
            collection_url,
            headers=superuser_token_headers,
            json={
                "instance_id": octobus.instance_id,
                "capset_id": octobus.capset_id,
            },
        ).json()
        assert client.post(
            f"{collection_url}/{source['id']}/validate",
            headers=superuser_token_headers,
            json={"capset_token": CAPSET_TOKEN},
        ).status_code == 200

        changes: list[tuple[str, object]] = [
            ("binding_instance_id", "different-instance"),
            ("config_sha256", "4" * 64),
            ("secret_sha256", "5" * 64),
            ("token_hash", "6" * 64),
            ("include_all_methods", True),
            ("selected_method", "cloudatlas.read.v1.OtherService/OtherMethod"),
            ("package_sha256", "7" * 64),
            ("descriptor_sha256", "8" * 64),
        ]
        for attribute, changed_value in changes:
            original_value = getattr(octobus, attribute)
            setattr(octobus, attribute, changed_value)
            changed_response = client.get(
                collection_url, headers=superuser_token_headers
            )
            assert changed_response.status_code == 200
            assert changed_response.json()["data"][0]["validation_status"] == (
                "invalid"
            )
            setattr(octobus, attribute, original_value)
            restored_response = client.get(
                collection_url, headers=superuser_token_headers
            )
            assert restored_response.status_code == 200
            assert restored_response.json()["data"][0]["validation_status"] == (
                "invalid"
            )
            assert client.post(
                f"{collection_url}/{source['id']}/validate",
                headers=superuser_token_headers,
                json={"capset_token": CAPSET_TOKEN},
            ).status_code == 200


def test_failed_validation_is_safe_audited_and_not_enableable(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project = _create_project(client, superuser_token_headers)
    with _octobus_server() as (base_url, octobus):
        monkeypatch.setattr(settings, "OCTOBUS_URL", base_url)
        octobus.connect_status = 401
        collection_url = (
            f"{settings.API_V1_STR}/projects/{project['id']}"
            "/cloudatlas-source-instances"
        )
        source = client.post(
            collection_url,
            headers=superuser_token_headers,
            json={
                "instance_id": octobus.instance_id,
                "capset_id": octobus.capset_id,
            },
        ).json()
        source_url = f"{collection_url}/{source['id']}"

        validation_response = client.post(
            f"{source_url}/validate",
            headers=superuser_token_headers,
            json={"capset_token": CAPSET_TOKEN},
        )
        enable_response = client.post(
            f"{source_url}/enable", headers=superuser_token_headers
        )

    assert validation_response.status_code == 401
    assert validation_response.json()["detail"] == {
        "code": "cloudatlas_authentication_failed",
        "message": "CloudAtlas authentication failed.",
    }
    assert CAPSET_TOKEN not in validation_response.text
    assert "192.0.2.10" not in validation_response.text
    assert enable_response.status_code == 409
    source_row = db.execute(
        text(
            "SELECT enabled, validated_fingerprint, validation_error_code "
            "FROM source_instances WHERE id = :source_id"
        ),
        {"source_id": uuid.UUID(source["id"])},
    ).one()
    assert source_row == (False, None, "cloudatlas_authentication_failed")
    actions = db.exec(
        select(AuditEvent.action)
        .where(AuditEvent.target_id == uuid.UUID(source["id"]))
        .order_by(col(AuditEvent.occurred_at))
    ).all()
    assert actions == [
        "source_instance.created",
        "source_instance.validation_failed",
    ]


def test_invalid_capset_token_length_is_not_echoed(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    project = _create_project(client, superuser_token_headers)
    collection_url = (
        f"{settings.API_V1_STR}/projects/{project['id']}"
        "/cloudatlas-source-instances"
    )
    source = client.post(
        collection_url,
        headers=superuser_token_headers,
        json={"instance_id": "safe-instance", "capset_id": "safe-capset"},
    ).json()
    secret_marker = "TOKEN-MUST-NOT-LEAK"
    oversized_token = secret_marker + "x" * 4096

    response = client.post(
        f"{collection_url}/{source['id']}/validate",
        headers=superuser_token_headers,
        json={"capset_token": oversized_token},
    )

    assert response.status_code == 422
    assert secret_marker not in response.text
    assert oversized_token not in response.text


def test_wrong_capset_token_is_not_a_cloudatlas_authentication_failure(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project = _create_project(client, superuser_token_headers)
    with _octobus_server() as (base_url, octobus):
        monkeypatch.setattr(settings, "OCTOBUS_URL", base_url)
        collection_url = (
            f"{settings.API_V1_STR}/projects/{project['id']}"
            "/cloudatlas-source-instances"
        )
        source = client.post(
            collection_url,
            headers=superuser_token_headers,
            json={
                "instance_id": octobus.instance_id,
                "capset_id": octobus.capset_id,
            },
        ).json()

        validation_response = client.post(
            f"{collection_url}/{source['id']}/validate",
            headers=superuser_token_headers,
            json={"capset_token": "wrong-capset-token"},
        )

    assert validation_response.status_code == 401
    assert validation_response.json()["detail"] == {
        "code": "octobus_authentication_failed",
        "message": "OctoBus authentication failed.",
    }
    assert "wrong-capset-token" not in validation_response.text
    source_row = db.execute(
        text(
            "SELECT validated_fingerprint, validation_error_code "
            "FROM source_instances WHERE id = :source_id"
        ),
        {"source_id": uuid.UUID(source["id"])},
    ).one()
    assert source_row == (None, "octobus_authentication_failed")


def test_database_constraint_rejects_a_second_enabled_cloudatlas_source(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project = _create_project(client, superuser_token_headers)
    with _octobus_server() as (base_url, octobus):
        monkeypatch.setattr(settings, "OCTOBUS_URL", base_url)
        collection_url = (
            f"{settings.API_V1_STR}/projects/{project['id']}"
            "/cloudatlas-source-instances"
        )
        source_ids = []
        for _index in range(2):
            source = client.post(
                collection_url,
                headers=superuser_token_headers,
                json={
                    "instance_id": octobus.instance_id,
                    "capset_id": octobus.capset_id,
                },
            ).json()
            source_ids.append(source["id"])
            assert client.post(
                f"{collection_url}/{source['id']}/validate",
                headers=superuser_token_headers,
                json={"capset_token": CAPSET_TOKEN},
            ).status_code == 200

        first_enable = client.post(
            f"{collection_url}/{source_ids[0]}/enable",
            headers=superuser_token_headers,
        )
        second_enable = client.post(
            f"{collection_url}/{source_ids[1]}/enable",
            headers=superuser_token_headers,
        )

    assert first_enable.status_code == 200
    assert second_enable.status_code == 409
    assert second_enable.json()["detail"]["code"] == "cloudatlas_source_conflict"
    enabled_count = db.execute(
        text(
            "SELECT count(*) FROM source_instances "
            "WHERE project_id = :project_id AND enabled"
        ),
        {"project_id": uuid.UUID(project["id"])},
    ).scalar_one()
    assert enabled_count == 1
    second_actions = db.exec(
        select(AuditEvent.action)
        .where(AuditEvent.target_id == uuid.UUID(source_ids[1]))
        .order_by(col(AuditEvent.occurred_at))
    ).all()
    assert second_actions == [
        "source_instance.created",
        "source_instance.validated",
    ]


def test_validation_state_rolls_back_when_audit_insert_fails(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project = _create_project(client, superuser_token_headers)
    with _octobus_server() as (base_url, octobus):
        monkeypatch.setattr(settings, "OCTOBUS_URL", base_url)
        collection_url = (
            f"{settings.API_V1_STR}/projects/{project['id']}"
            "/cloudatlas-source-instances"
        )
        source = client.post(
            collection_url,
            headers=superuser_token_headers,
            json={
                "instance_id": octobus.instance_id,
                "capset_id": octobus.capset_id,
            },
        ).json()

        with reject_audit_inserts(db):
            with TestClient(
                app,
                raise_server_exceptions=False,
                client=("127.0.0.1", 50110),
            ) as failure_client:
                response = failure_client.post(
                    f"{collection_url}/{source['id']}/validate",
                    headers=superuser_token_headers,
                    json={"capset_token": CAPSET_TOKEN},
                )

    assert response.status_code == 500
    db.expire_all()
    source_row = db.execute(
        text(
            "SELECT validated_fingerprint, validated_at, validation_error_code "
            "FROM source_instances WHERE id = :source_id"
        ),
        {"source_id": uuid.UUID(source["id"])},
    ).one()
    assert source_row == (None, None, None)


def test_every_source_mutation_rolls_back_when_its_audit_insert_fails(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    project = _create_project(client, superuser_token_headers)
    project_id = uuid.UUID(project["id"])
    collection_url = (
        f"{settings.API_V1_STR}/projects/{project['id']}"
        "/cloudatlas-source-instances"
    )

    def request_with_rejected_audit(
        method: str, url: str, *, json_body: dict[str, str] | None = None
    ) -> int:
        with reject_audit_inserts(db):
            with TestClient(
                app,
                raise_server_exceptions=False,
                client=("127.0.0.1", 50111),
            ) as failure_client:
                response = failure_client.request(
                    method,
                    url,
                    headers=superuser_token_headers,
                    json=json_body,
                )
        return int(response.status_code)

    create_body = {
        "instance_id": "cloudatlas-fixture",
        "capset_id": "cloudatlas-readonly",
    }
    assert request_with_rejected_audit(
        "POST", collection_url, json_body=create_body
    ) == 500
    db.expire_all()
    assert db.exec(
        select(func.count())
        .select_from(SourceInstance)
        .where(SourceInstance.project_id == project_id)
    ).one() == 0

    with _octobus_server() as (base_url, _octobus):
        monkeypatch.setattr(settings, "OCTOBUS_URL", base_url)
        source = client.post(
            collection_url,
            headers=superuser_token_headers,
            json=create_body,
        ).json()
        source_url = f"{collection_url}/{source['id']}"
        assert client.post(
            f"{source_url}/validate",
            headers=superuser_token_headers,
            json={"capset_token": CAPSET_TOKEN},
        ).status_code == 200

        assert request_with_rejected_audit("POST", f"{source_url}/enable") == 500
        db.expire_all()
        source_record = db.get(SourceInstance, uuid.UUID(source["id"]))
        assert source_record is not None
        assert source_record.enabled is False

        assert client.post(
            f"{source_url}/enable", headers=superuser_token_headers
        ).status_code == 200
        assert request_with_rejected_audit("POST", f"{source_url}/disable") == 500
        db.expire_all()
        source_record = db.get(SourceInstance, uuid.UUID(source["id"]))
        assert source_record is not None
        assert source_record.enabled is True

        assert client.post(
            f"{source_url}/disable", headers=superuser_token_headers
        ).status_code == 200
        assert request_with_rejected_audit(
            "PATCH",
            source_url,
            json_body={
                "instance_id": "replacement",
                "capset_id": "replacement-readonly",
            },
        ) == 500

    db.expire_all()
    source_record = db.get(SourceInstance, uuid.UUID(source["id"]))
    assert source_record is not None
    assert (
        source_record.instance_id,
        source_record.capset_id,
        source_record.enabled,
        source_record.validated_fingerprint is not None,
    ) == (
        "cloudatlas-fixture",
        "cloudatlas-readonly",
        False,
        True,
    )
    actions = db.exec(
        select(AuditEvent.action)
        .where(AuditEvent.target_id == source_record.id)
        .order_by(col(AuditEvent.occurred_at))
    ).all()
    assert actions == [
        "source_instance.created",
        "source_instance.validated",
        "source_instance.enabled",
        "source_instance.disabled",
    ]
