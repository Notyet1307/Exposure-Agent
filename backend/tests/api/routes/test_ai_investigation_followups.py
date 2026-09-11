"""Followups preserve scope, history, and failed-read citation boundaries."""

import hashlib
import json
import uuid
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.domain import ai_investigation_tools as tools
from app.domain import ai_investigations as service
from app.domain.models import AiInvestigation
from tests.api.routes.test_ai_investigations import (
    _output,
    _pending,
    _run,
)
from tests.api.routes.test_ai_investigations import (
    investigation_context as investigation_context,
)


def test_followup_timeout_is_independent_and_pinned(
    client: TestClient, investigation_context: Any, monkeypatch: MonkeyPatch
) -> None:
    url, headers, scope = investigation_context
    _pending(monkeypatch)
    monkeypatch.setattr(settings, "AI_INVESTIGATION_TIMEOUT_SECONDS", 120)
    monkeypatch.setattr(settings, "AI_INVESTIGATION_FOLLOWUP_TIMEOUT_SECONDS", 1200)
    parent = client.post(
        url, headers={**headers, "Idempotency-Key": "timeout-parent"}, json=scope
    )
    assert parent.status_code == 201
    parent_id = parent.json()["id"]

    def complete_parent(**kwargs: Any) -> dict[str, Any]:
        assert 0 < kwargs["timeout_seconds"] <= 120
        return _output(kwargs["tools"]["read_asset_facts"]({}))

    assert _run(monkeypatch, parent_id, complete_parent) == 0
    request_headers = {**headers, "Idempotency-Key": "timeout-child"}
    body = {"question": "Explain the fixed facts."}
    child_url = f"{url}/{parent_id}/followups"
    child = client.post(child_url, headers=request_headers, json=body)
    assert child.status_code == 201
    child_id = child.json()["id"]
    monkeypatch.setattr(settings, "AI_INVESTIGATION_FOLLOWUP_TIMEOUT_SECONDS", 300)
    replay = client.post(child_url, headers=request_headers, json=body)
    assert replay.status_code == 200 and replay.json()["id"] == child_id
    with Session(engine) as session:
        parent_record = session.get(AiInvestigation, uuid.UUID(parent_id))
        child_record = session.get(AiInvestigation, uuid.UUID(child_id))
        assert parent_record is not None and parent_record.timeout_seconds == 120
        assert child_record is not None and child_record.timeout_seconds == 1200

    def complete_child(**kwargs: Any) -> dict[str, Any]:
        assert 1100 < kwargs["timeout_seconds"] <= 1200
        return _output(kwargs["tools"]["read_asset_facts"]({}))

    assert _run(monkeypatch, child_id, complete_child) == 0


def test_followup_scope_replay_and_prior_result_survive_failed_query(
    client: TestClient, investigation_context: Any, monkeypatch: MonkeyPatch
) -> None:
    url, headers, scope = investigation_context
    starts = _pending(monkeypatch)
    parent = client.post(
        url, headers={**headers, "Idempotency-Key": "parent"}, json=scope
    )
    assert parent.status_code == 201, parent.text
    parent_id = parent.json()["id"]
    assert (
        _run(
            monkeypatch,
            parent_id,
            lambda **kw: _output(kw["tools"]["read_asset_facts"]({})),
        )
        == 0
    )
    original = client.get(f"{url}/{parent_id}", headers=headers).json()
    question = {"question": "Compare previous history with a fresh CloudAtlas query."}
    request_headers = {**headers, "Idempotency-Key": "followup"}
    followup_url = f"{url}/{parent_id}/followups"
    rejected = client.post(
        followup_url,
        headers=request_headers,
        json={**question, "run_id": str(uuid.uuid4())},
    )
    assert rejected.status_code == 422
    created = client.post(followup_url, headers=request_headers, json=question)
    assert created.status_code == 201, created.text
    child = created.json()
    assert {key: child[key] for key in scope} == scope
    assert child["parent_investigation_id"] == parent_id
    replay = client.post(followup_url, headers=request_headers, json=question)
    assert replay.status_code == 200 and replay.json()["id"] == child["id"]
    conflict = client.post(
        followup_url, headers=request_headers, json={"question": "Different question"}
    )
    assert conflict.status_code == 409

    def unavailable(**_kwargs: Any) -> dict[str, Any]:
        raise service.InvestigationError("cloudatlas_upstream_failed")

    monkeypatch.setattr(tools, "read_cloudatlas_asset", unavailable)

    def model(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["conversation"]["question"] == question["question"]
        assert (
            kwargs["conversation"]["previous_turns"][-1]["output"] == original["output"]
        )
        material = kwargs["tools"]["read_asset_facts"]({})
        failed = kwargs["tools"]["read_cloudatlas_asset"]({})
        assert failed["status"] == "FAILED" and failed["items"] == []
        output = _output(material)
        output["gaps"] = [
            "The live CloudAtlas query failed; no new observation was obtained."
        ]
        return output

    assert _run(monkeypatch, child["id"], model) == 0
    result = client.get(f"{url}/{child['id']}", headers=headers).json()
    assert result["status"] == "COMPLETED"
    assert result["tool_reads"][-1]["failure_code"] == "cloudatlas_upstream_failed"
    assert result["tool_reads"][-1]["items"] == []
    assert client.get(f"{url}/{parent_id}", headers=headers).json() == original
    assert starts == [parent_id, child["id"]]
    with Session(engine) as session:
        with pytest.raises(DBAPIError):
            session.connection().execute(
                text("UPDATE ai_investigations SET tool_reads = '[]' WHERE id = :id"),
                {"id": child["id"]},
            )
        session.rollback()


def test_failed_optional_read_cannot_support_a_fact(
    client: TestClient, investigation_context: Any, monkeypatch: MonkeyPatch
) -> None:
    url, headers, scope = investigation_context
    _pending(monkeypatch)
    created = client.post(
        url, headers={**headers, "Idempotency-Key": "failed-citation"}, json=scope
    )
    assert created.status_code == 201
    record_id = created.json()["id"]

    def unavailable(**_kwargs: Any) -> dict[str, Any]:
        raise service.InvestigationError("cloudatlas_upstream_failed")

    monkeypatch.setattr(tools, "read_cloudatlas_asset", unavailable)

    def model(**kwargs: Any) -> dict[str, Any]:
        material = kwargs["tools"]["read_asset_facts"]({})
        failed = kwargs["tools"]["read_cloudatlas_asset"]({})
        output = _output(material)
        output["facts"][0]["citation_ids"] = [failed["id"]]
        return output

    assert _run(monkeypatch, record_id, model) == 1
    result = client.get(f"{url}/{record_id}", headers=headers).json()
    assert result["failure_code"] == "model_citation_invalid"
    assert result["tool_reads"][-1]["status"] == "FAILED"
    assert result["output"] is None


def test_followup_turn_budget_and_incomplete_parent(
    client: TestClient, investigation_context: Any, monkeypatch: MonkeyPatch
) -> None:
    url, headers, scope = investigation_context
    _pending(monkeypatch)
    response = client.post(
        url, headers={**headers, "Idempotency-Key": "bounded-parent"}, json=scope
    )
    assert response.status_code == 201
    parent_id = response.json()["id"]
    blocked = client.post(
        f"{url}/{parent_id}/followups",
        headers={**headers, "Idempotency-Key": "unfinished"},
        json={"question": "Continue"},
    )
    assert blocked.status_code == 409
    for turn in range(8):
        assert (
            _run(
                monkeypatch,
                parent_id,
                lambda **kw: _output(kw["tools"]["read_asset_facts"]({})),
            )
            == 0
        )
        next_turn = client.post(
            f"{url}/{parent_id}/followups",
            headers={**headers, "Idempotency-Key": f"turn-{turn}"},
            json={"question": "What remains uncertain?"},
        )
        if turn == 7:
            assert next_turn.status_code == 409
            assert next_turn.json()["detail"]["code"] == "investigation_turn_limit"
        else:
            assert next_turn.status_code == 201, next_turn.text
            parent_id = next_turn.json()["id"]


@pytest.mark.parametrize("has_match", [False, True])
def test_followup_cannot_resend_revoked_prior_live_material(
    client: TestClient,
    investigation_context: Any,
    monkeypatch: MonkeyPatch,
    has_match: bool,
) -> None:
    url, headers, scope = investigation_context
    _pending(monkeypatch)
    created = client.post(
        url, headers={**headers, "Idempotency-Key": "prior-live"}, json=scope
    )
    assert created.status_code == 201
    record_id = created.json()["id"]
    content = {
        "schema": "ai-cloudatlas-asset/v1",
        "project_id": created.json()["project_id"],
        "resource_id": scope["resource_id"],
        "run_id": scope["run_id"],
        "base_published_at": created.json()["material"]["published_at"],
        "source": {
            "source_type": "CLOUDATLAS",
            "source_instance_id": str(uuid.uuid4()),
            "instance_id": "fixture",
            "capset_id": "readonly",
            "method": "cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets",
            "fingerprint": "a" * 64,
        },
        "canonical_ip": "192.0.2.10",
        "result": "FOUND" if has_match else "NO_DATA",
        "assets": [{"id": "one", "ip": "192.0.2.10", "status": "valid"}]
        if has_match
        else [],
    }
    supplemental = {
        **{key: value for key, value in content.items() if key != "assets"},
        "items": [{"citation_id": "live-synthetic", "fact": content}]
        if has_match
        else [],
    }
    monkeypatch.setattr(tools, "read_cloudatlas_asset", lambda **_: supplemental)

    def model(**kwargs: Any) -> dict[str, Any]:
        material = kwargs["tools"]["read_asset_facts"]({})
        kwargs["tools"]["read_cloudatlas_asset"]({})
        return _output(material)

    assert _run(monkeypatch, record_id, model) == 0
    with Session(engine) as session:
        record = session.get(AiInvestigation, uuid.UUID(record_id))
        assert record is not None
        binding = replace(
            service.require_model(session, record),
            endpoint="https://ai-api-gateway.app.baizhi.cloud/api/openai",
        )
        permission = {
            "project_id": str(record.project_id),
            **scope,
            "material_sha256": record.material_sha256,
            "sources": record.sources,
            "question_sha256s": [
                hashlib.sha256(b"Repeat what the prior live query showed.").hexdigest()
            ],
        }
    monkeypatch.setattr(service, "require_model", lambda *_: binding)
    monkeypatch.setattr(settings, "AI_INVESTIGATION_ALLOW_BAIZHI_TEST", True)
    monkeypatch.setattr(
        settings, "AI_INVESTIGATION_SYNTHETIC_MANIFEST", json.dumps([permission])
    )
    rejected = client.post(
        f"{url}/{record_id}/followups",
        headers={**headers, "Idempotency-Key": "revoked-context"},
        json={"question": "Repeat what the prior live query showed."},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "synthetic_material_denied"
    assert (
        client.get(f"{url}/{record_id}", headers=headers).json()["status"]
        == "COMPLETED"
    )


def test_public_followups_require_current_and_prior_question_approval(
    client: TestClient,
    investigation_context: Any,
    monkeypatch: MonkeyPatch,
) -> None:
    url, headers, scope = investigation_context
    starts = _pending(monkeypatch)
    initial = client.post(
        url, headers={**headers, "Idempotency-Key": "question-root"}, json=scope
    )
    initial_id = initial.json()["id"]

    def model(**kwargs: Any) -> dict[str, Any]:
        return _output(kwargs["tools"]["read_asset_facts"]({}))

    assert _run(monkeypatch, initial_id, model) == 0
    with Session(engine) as session:
        record = session.get(AiInvestigation, uuid.UUID(initial_id))
        assert record is not None
        binding = replace(
            service.require_model(session, record),
            endpoint="https://ai-api-gateway.app.baizhi.cloud/api/openai",
        )
        permission = {
            "project_id": str(record.project_id),
            **scope,
            "material_sha256": record.material_sha256,
            "sources": record.sources,
        }
    monkeypatch.setattr(service, "require_model", lambda *_: binding)
    monkeypatch.setattr(settings, "AI_INVESTIGATION_ALLOW_BAIZHI_TEST", True)
    monkeypatch.setattr(
        settings, "AI_INVESTIGATION_SYNTHETIC_MANIFEST", json.dumps([permission])
    )
    denied = client.post(
        f"{url}/{initial_id}/followups",
        headers={**headers, "Idempotency-Key": "unapproved-question"},
        json={"question": "Unapproved synthetic secret."},
    )
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "synthetic_material_denied"
    assert starts == [initial_id]
    question = "Compare with history."
    permission["question_sha256s"] = [hashlib.sha256(question.encode()).hexdigest()]
    monkeypatch.setattr(
        settings, "AI_INVESTIGATION_SYNTHETIC_MANIFEST", json.dumps([permission])
    )
    approved = client.post(
        f"{url}/{initial_id}/followups",
        headers={**headers, "Idempotency-Key": "approved-question"},
        json={"question": f"  {question}  "},
    )
    assert approved.status_code == 201, approved.text
    approved_id = approved.json()["id"]
    assert approved.json()["question"] == question
    assert _run(monkeypatch, approved_id, model) == 0
    next_question = "What remains uncertain?"
    permission["question_sha256s"] = [
        hashlib.sha256(next_question.encode()).hexdigest()
    ]
    monkeypatch.setattr(
        settings, "AI_INVESTIGATION_SYNTHETIC_MANIFEST", json.dumps([permission])
    )
    revoked = client.post(
        f"{url}/{approved_id}/followups",
        headers={**headers, "Idempotency-Key": "revoked-question-context"},
        json={"question": next_question},
    )
    assert revoked.status_code == 409
    assert revoked.json()["detail"]["code"] == "synthetic_material_denied"
    assert starts == [initial_id, approved_id]
    assert (
        client.get(f"{url}/{approved_id}", headers=headers).json()["status"]
        == "COMPLETED"
    )
