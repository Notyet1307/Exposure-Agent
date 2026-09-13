"""Management contracts; actual Pi/proxy execution has a separate acceptance path."""

import secrets
import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import SecretStr
from sqlalchemy import text
from sqlmodel import Session, delete, select

from app.api.routes import model_connections as routes
from app.core.config import settings
from app.core.db import engine
from app.domain import model_connections as service
from app.domain.models import (
    DEPLOYMENT_TENANT_ID,
    AuditEvent,
    ModelConnectionLease,
    ModelConnectionOperation,
    ModelConnectionSecret,
    ModelConnectionState,
    ModelConnectionVersion,
)
from app.integrations import model_connection_runtime as runtime

BASE = settings.API_V1_STR + "/model-connections"


@pytest.fixture(autouse=True)
def model_environment(
    db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[None]:
    def clean() -> None:
        db.rollback()
        db.execute(text("TRUNCATE ai_governance_drafts, audit_events CASCADE"))
        for model in [
            ModelConnectionLease,
            ModelConnectionOperation,
            ModelConnectionState,
            ModelConnectionVersion,
            ModelConnectionSecret,
        ]:
            db.exec(delete(model))
        db.commit()
        db.expire_all()

    clean()
    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    (keys / "v1.key").write_bytes(secrets.token_bytes(32))
    (keys / "v1.key").chmod(0o600)
    monkeypatch.setattr(settings, "MODEL_CONNECTION_KEY_DIRECTORY", keys)
    monkeypatch.setattr(settings, "MODEL_CONNECTION_KEY_ID", "v1")
    monkeypatch.setattr(settings, "RUNNER_BUILD_VERSION", "connection-test")
    monkeypatch.setattr(settings, "AGENT_COMPOSE_RUNTIME_VERSION", "runtime-test")
    monkeypatch.setattr(settings, "MODEL_API_KEY", SecretStr(""))
    monkeypatch.setattr(runtime, "start_validation", lambda _: None)
    monkeypatch.setattr(runtime, "reconcile_validation", lambda _: None)
    monkeypatch.setattr(
        runtime, "ensure_project", lambda *_, **__: {"spec_hash": "sha256:test"}
    )
    monkeypatch.setattr(routes, "_legacy_drained", lambda: None)
    yield
    clean()


def generation(client: TestClient, headers: dict[str, str]) -> int:
    value = client.get(BASE, headers=headers).json()["generation"]
    assert isinstance(value, int)
    return value


def save(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str = "A",
    key: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Response:
    body = payload or {
        "name": name,
        "endpoint": "http://127.0.0.1:9999/v1",
        "protocol": "chat_completions",
        "model_identity": "fixture-model",
        "api_key": "synthetic-provider-key-not-returned",
        "expected_generation": generation(client, headers),
    }
    return cast(
        Response,
        client.post(
            BASE,
            headers={**headers, "Idempotency-Key": key or str(uuid.uuid4())},
            json=body,
        ),
    )


def act(
    client: TestClient,
    headers: dict[str, str],
    connection: str,
    action: str,
    *,
    key: str | None = None,
    expected: int | None = None,
) -> Response:
    return cast(
        Response,
        client.post(
            f"{BASE}/{connection}/{action}",
            headers={**headers, "Idempotency-Key": key or str(uuid.uuid4())},
            json={
                "expected_generation": generation(client, headers)
                if expected is None
                else expected
            },
        ),
    )


def complete(op_id: str) -> None:
    with Session(engine) as session:
        op = session.get(ModelConnectionOperation, uuid.UUID(op_id))
        assert op and op.agent_run_id
        version = session.get(ModelConnectionVersion, op.connection_id)
        assert version
        op.session_id = "c" * 64
        version.runtime_spec_hash = "sha256:test"
        version.runtime_project_id = runtime.client_for_version(version).project_id
        version.runtime_project_revision = "1"
        version.runtime_agents = {role: role for role in runtime.ROLES}
        session.add(op)
        session.add(version)
        session.commit()
        evidence = dict.fromkeys(
            ["qualification", "investigation", "analysis_report", "runtime"], "PASS"
        )
        evidence.update(
            fingerprint=version.fingerprint,
            operation_id=str(op.id),
            agent_run_id=op.agent_run_id,
            session_id=op.session_id,
            runtime_spec_hash=version.runtime_spec_hash,
        )
        service.finish_validation(session, op.id, evidence)


def validated(client: TestClient, headers: dict[str, str], name: str = "A") -> str:
    response = save(client, headers, name=name)
    assert response.status_code == 201, response.text
    connection = response.json()["operation"]["connection_id"]
    op = act(client, headers, connection, "validate")
    assert op.status_code == 200, op.text
    complete(op.json()["operation"]["id"])
    return str(connection)


def test_admin_only_and_secret_never_returns(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    assert client.get(BASE).status_code in {401, 403}
    assert client.get(BASE, headers=normal_user_token_headers).status_code == 403
    assert (
        client.get(BASE + "/status", headers=normal_user_token_headers).status_code
        == 200
    )
    assert (
        save(
            client,
            normal_user_token_headers,
            payload={
                "name": "x",
                "endpoint": "http://127.0.0.1/v1",
                "protocol": "chat_completions",
                "model_identity": "m",
                "api_key": "secret",
                "expected_generation": 0,
            },
        ).status_code
        == 403
    )
    response = save(client, superuser_token_headers)
    assert response.status_code == 201, response.text
    assert "synthetic-provider-key-not-returned" not in response.text
    assert "ciphertext" not in response.text and "secret_id" not in response.text
    db.expire_all()
    version = db.exec(select(ModelConnectionVersion)).one()
    secret = db.get(ModelConnectionSecret, version.secret_id)
    assert secret and b"synthetic-provider-key-not-returned" not in secret.ciphertext
    assert service.provider_key(db, version) == "synthetic-provider-key-not-returned"
    events = db.exec(select(AuditEvent).where(AuditEvent.target_id == version.id)).all()
    assert len(events) == 1 and "synthetic-provider-key-not-returned" not in repr(
        events[0].after_data
    )
    invalid = client.post(
        BASE,
        headers={**superuser_token_headers, "Idempotency-Key": "invalid"},
        json={"api_key": "must-not-leak"},
    )
    assert invalid.status_code == 422 and "must-not-leak" not in invalid.text
    for action in ["validate", "activate", "revoke", "discard"]:
        assert (
            act(
                client, normal_user_token_headers, str(version.id), action, expected=1
            ).status_code
            == 403
        )


def test_save_replay_conflict_and_atomicity(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = superuser_token_headers
    body = {
        "name": "  A  ",
        "endpoint": "http://127.0.0.1:9999/v1",
        "protocol": "chat_completions",
        "model_identity": "fixture-model",
        "api_key": "key-a",
        "expected_generation": 0,
    }
    first = save(client, h, key="same-intent", payload=body)
    assert first.status_code == 201
    replay = save(client, h, key="same-intent", payload={**body, "name": "A"})
    assert replay.status_code == 200
    assert first.json()["operation"]["id"] == replay.json()["operation"]["id"]
    conflict = save(client, h, key="same-intent", payload={**body, "api_key": "key-b"})
    assert (
        conflict.status_code == 409
        and conflict.json()["detail"]["code"] == "model_connection_intent_conflict"
    )
    db.expire_all()
    assert len(db.exec(select(ModelConnectionVersion)).all()) == 1
    assert save(client, h).json()["detail"]["code"] == "model_connection_pending_exists"
    assert (
        act(client, h, first.json()["operation"]["connection_id"], "activate").json()[
            "detail"
        ]["code"]
        == "model_not_qualified"
    )
    act(client, h, first.json()["operation"]["connection_id"], "discard")
    monkeypatch.setattr(settings, "MODEL_CONNECTION_KEY_DIRECTORY", None)
    denied = save(client, h)
    assert denied.status_code == 409
    db.expire_all()
    assert len(db.exec(select(ModelConnectionVersion)).all()) == 1
    assert len(db.exec(select(ModelConnectionSecret)).all()) == 1


def test_concurrent_save_has_one_version(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    body = {
        "name": "Concurrent",
        "endpoint": "http://127.0.0.1:9999/v1",
        "protocol": "chat_completions",
        "model_identity": "fixture-model",
        "api_key": "parallel-key",
        "expected_generation": 0,
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda _: save(
                    client, superuser_token_headers, key="parallel", payload=body
                ),
                range(2),
            )
        )
    assert sorted(r.status_code for r in responses) == [200, 201]
    assert len({r.json()["operation"]["connection_id"] for r in responses}) == 1
    db.expire_all()
    assert len(db.exec(select(ModelConnectionSecret)).all()) == 1
    assert len(db.exec(select(ModelConnectionOperation)).all()) == 1


def bound(
    session: Session, purpose: str, record: Any = None
) -> service.ConnectionBinding:
    result = service.binding_for_task(session, purpose, record)
    assert result is not None
    return result


def test_b_preserves_a_until_explicit_revoke(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    h = superuser_token_headers
    a = validated(client, h, "A")
    assert act(client, h, a, "activate").json()["operation"]["status"] == "SUCCEEDED"
    with Session(engine) as s:
        binding = service.binding_for_task(s, "investigation")
        assert binding
        old = SimpleNamespace(
            connection_version_id=uuid.UUID(a),
            config_fingerprint=binding.config_fingerprint,
            tenant_id=DEPLOYMENT_TENANT_ID,
        )
    b = validated(client, h, "B")
    assert act(client, h, b, "activate").json()["state"]["active_id"] == b
    with Session(engine) as s:
        assert bound(s, "investigation").connection_version_id == uuid.UUID(b)
        assert bound(s, "investigation", old).connection_version_id == uuid.UUID(a)
        assert (
            service.binding_for_task(
                s, "investigation", SimpleNamespace(connection_version_id=None)
            )
            is None
        )
    assert act(client, h, a, "revoke").json()["state"]["active_id"] == b
    with Session(engine) as s:
        with pytest.raises(
            service.ModelConnectionError, match="model_connection_revoked"
        ):
            service.binding_for_task(s, "investigation", old)
        assert bound(s, "analysis_report").connection_version_id == uuid.UUID(b)
    act(client, h, b, "revoke")
    state = client.get(BASE + "/status", headers=h).json()
    assert state["state"] == "disabled" and not state["ready"]
    with Session(engine) as s:
        with pytest.raises(
            service.ModelConnectionError, match="model_connection_disabled"
        ):
            service.binding_for_task(s, "investigation")


def test_unknown_get_observes_post_reuses_operation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = superuser_token_headers
    c = save(client, h).json()["operation"]["connection_id"]
    calls: list[uuid.UUID] = []

    def start_with_independent_transaction(op: uuid.UUID) -> None:
        # Real start_validation needs its own transaction before native Start.
        with Session(engine) as other:
            other.connection().execute(text("SET LOCAL lock_timeout = '500ms'"))
            service.state_for_write(other)
        calls.append(op)

    monkeypatch.setattr(runtime, "start_validation", start_with_independent_transaction)
    expected = generation(client, h)
    first = act(client, h, c, "validate", key="validation", expected=expected)
    opid = first.json()["operation"]["id"]
    with Session(engine) as s:
        op = s.get(ModelConnectionOperation, uuid.UUID(opid))
        assert op is not None
        op.status = "UNKNOWN"
        s.add(op)
        s.commit()
    for _ in range(2):
        assert client.get(BASE + "/operations/" + opid, headers=h).status_code == 200
    assert len(calls) == 1
    repeat = act(client, h, c, "validate", key="validation", expected=expected)
    assert repeat.json()["operation"]["id"] == opid and len(calls) == 2
    assert (
        act(client, h, c, "discard").json()["detail"]["code"] == "model_connection_busy"
    )


def test_activation_failure_and_stale_generation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = superuser_token_headers
    a = validated(client, h, "A")
    act(client, h, a, "activate")
    b = validated(client, h, "B")

    def conflict(*_args: Any, **_kwargs: Any) -> None:
        raise service.ModelConnectionError("model_connection_runtime_conflict")

    monkeypatch.setattr(runtime, "ensure_project", conflict)
    result = act(client, h, b, "activate").json()
    assert (
        result["operation"]["status"] == "FAILED" and result["state"]["active_id"] == a
    )
    stale = act(client, h, b, "discard", expected=0)
    assert (
        stale.status_code == 409
        and stale.json()["detail"]["code"] == "model_connection_generation_conflict"
    )


def proxy_context(
    client: TestClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> tuple[uuid.UUID, str, list[dict[str, Any]]]:
    from app.integrations.agent_compose import AgentComposeClient, AgentComposeRunStart

    connection = save(client, headers).json()["operation"]["connection_id"]
    operation_id = act(client, headers, connection, "validate").json()["operation"][
        "id"
    ]
    with Session(engine) as session:
        op = session.get(ModelConnectionOperation, uuid.UUID(operation_id))
        assert op and op.agent_run_id
        v = session.get(ModelConnectionVersion, uuid.UUID(connection))
        assert v
        v.runtime_project_id = runtime.client_for_version(v).project_id
        v.runtime_project_revision = "1"
        v.runtime_agents = dict.fromkeys(runtime.ROLES, "f" * 64)
        v.runtime_spec_hash = "sha256:test"
        op.session_id = "d" * 64
        op.status = "RUNNING"
        session.add(v)
        session.add(op)
        session.commit()
        lease = session.exec(
            select(ModelConnectionLease).where(
                ModelConnectionLease.task_id == op.id,
                ModelConnectionLease.purpose == "qualification",
            )
        ).one()
        lease_id, token = lease.id, service.lease_token(lease)
        run = AgentComposeRunStart(
            run_id=op.agent_run_id,
            started=False,
            status="RUN_STATUS_RUNNING",
            session_id=op.session_id,
            project_id=v.runtime_project_id,
            agent_name="model-connection-validator",
            project_revision="1",
            agent_id="f" * 64,
        )
    monkeypatch.setattr(AgentComposeClient, "get_run", lambda *_: run)
    calls: list[dict[str, Any]] = []

    class Provider:
        status_code = 200
        headers = {"Content-Type": "application/json"}

        def __init__(self, **kwargs: Any):
            assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False

        def __enter__(self) -> Provider:
            return self

        def __exit__(self, *_: Any) -> None:
            pass

        def stream(self, method: str, url: str, **kwargs: Any) -> Provider:
            assert (
                kwargs["headers"]["Authorization"]
                == "Bearer synthetic-provider-key-not-returned"
            )
            calls.append(
                {
                    "method": method,
                    "url": url,
                    "host": kwargs["headers"]["Host"],
                    "body": kwargs["content"],
                }
            )
            return self

        def iter_bytes(self) -> Generator[bytes]:
            yield b'{"ok":true}'

    monkeypatch.setattr(httpx, "Client", Provider)
    return lease_id, token, calls


def test_proxy_uses_backend_key_and_exhausts_scoped_lease(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease, token, calls = proxy_context(client, superuser_token_headers, monkeypatch)
    url = f"{BASE}/internal/{lease}/chat/completions"
    headers = {"Authorization": "Bearer " + token}
    result = client.post(
        url, headers=headers, json={"model": "fixture-model", "messages": []}
    )
    assert result.status_code == 200 and result.json() == {"ok": True}
    assert (
        len(calls) == 1
        and calls[0]["url"] == "http://127.0.0.1:9999/v1/chat/completions"
    )
    assert (
        client.post(url, headers=headers, json={"model": "fixture-model"}).status_code
        == 403
    )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "fault",
    [
        "token",
        "expired",
        "model",
        "suffix",
        "revoked",
        "task",
        "runtime_revision",
        "runtime_agent",
    ],
)
def test_proxy_rejects_fault_before_provider(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    from datetime import timedelta

    from app.core.time import get_datetime_utc
    from app.integrations.agent_compose import AgentComposeClient

    lease_id, token, calls = proxy_context(client, superuser_token_headers, monkeypatch)
    model = "fixture-model"
    suffix = "chat/completions"
    if fault == "token":
        token = "wrong"
    elif fault == "model":
        model = "wrong"
    elif fault == "suffix":
        suffix = "responses"
    elif fault.startswith("runtime_"):
        with Session(engine) as s:
            lease = s.get(ModelConnectionLease, lease_id)
            assert lease
            v = s.get(ModelConnectionVersion, lease.connection_id)
            assert v
            run = runtime.client_for_version(v).get_run(lease.agent_run_id)
            assert run
        if fault == "runtime_revision":
            run = replace(run, project_revision="2")
        else:
            run = replace(run, agent_id="0" * 64)
        monkeypatch.setattr(AgentComposeClient, "get_run", lambda *_: run)
    else:
        with Session(engine) as s:
            lease = s.get(ModelConnectionLease, lease_id)
            assert lease
            if fault == "expired":
                lease.expires_at = get_datetime_utc() - timedelta(seconds=1)
            elif fault == "task":
                lease.task_id = uuid.uuid4()
            else:
                v = s.get(ModelConnectionVersion, lease.connection_id)
                assert v
                v.revoked_at = get_datetime_utc()
                s.add(v)
            s.add(lease)
            s.commit()
    result = client.post(
        f"{BASE}/internal/{lease_id}/{suffix}",
        headers={"Authorization": "Bearer " + token},
        json={"model": model},
    )
    assert result.status_code == 403 and calls == []


def test_recover_by_key_is_actor_scoped_and_read_only(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = str(uuid.uuid4())
    response = save(client, superuser_token_headers, key=key)
    original = response.json()
    headers = {**superuser_token_headers, "Idempotency-Key": key}
    with Session(engine) as session:
        before = len(session.exec(select(AuditEvent)).all())

    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("read-only recovery crossed a write or Secret boundary")

    monkeypatch.setattr(runtime, "start_validation", forbidden)
    monkeypatch.setattr(runtime, "reconcile_validation", forbidden)
    monkeypatch.setattr(service, "state_for_write", forbidden)
    monkeypatch.setattr(service, "_open", forbidden)
    found = client.get(BASE + "/operations/recover/save", headers=headers)
    assert found.status_code == 200
    assert found.json() == original
    assert found.json()["operation"]["expected_generation"] == 0
    assert (
        client.get(BASE + "/operations/recover/adopt", headers=headers).status_code
        == 404
    )
    assert (
        client.get(
            BASE + "/operations/recover/save",
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        ).status_code
        == 404
    )
    assert (
        client.get(
            BASE + "/operations/recover/save",
            headers={**normal_user_token_headers, "Idempotency-Key": key},
        ).status_code
        == 403
    )
    from app.models import User

    other = client.get(
        settings.API_V1_STR + "/users/me", headers=normal_user_token_headers
    ).json()
    with Session(engine) as session:
        user = session.get(User, uuid.UUID(other["id"]))
        assert user
        user.is_superuser = True
        session.add(user)
        session.commit()
        try:
            assert (
                client.get(
                    BASE + "/operations/recover/save",
                    headers={**normal_user_token_headers, "Idempotency-Key": key},
                ).status_code
                == 404
            )
        finally:
            user.is_superuser = False
            session.add(user)
            session.commit()
        assert len(session.exec(select(AuditEvent)).all()) == before


def test_admin_state_includes_validation_layers_but_not_secrets(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    identity = validated(client, superuser_token_headers)
    response = client.get(BASE, headers=superuser_token_headers)
    version = next(v for v in response.json()["connections"] if v["id"] == identity)
    assert version["validation_status"] == "VALIDATED"
    assert version["validation_completed_at"] is not None
    assert all(
        version["validation_evidence"][layer] == "PASS"
        for layer in ["qualification", "investigation", "analysis_report", "runtime"]
    )
    assert "synthetic-provider-key-not-returned" not in response.text
