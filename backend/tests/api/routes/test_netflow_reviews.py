"""Consumer regressions using real component artifacts, not fabricated task states."""

import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.time import get_datetime_utc
from app.domain.models import ProjectMembership
from app.domain.netflow_models import NetFlowContextRevision
from tests.api.routes.test_netflow_datasets import _member, _project
from tests.utils.netflow_processing import published_analysis


@pytest.fixture
def review_analysis(client: TestClient, db: Session, superuser_token_headers: dict[str, str],
                    tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    raw = "IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
    raw += "".join(f"192.0.2.{index},198.51.100.{peer},6,443,53000\n"
                   for index in range(1, 31) for peer in (1, 2))
    raw += "192.0.2.1,198.51.100.1,6,443,53000\n" * 25
    raw += "192.0.2.1,192.0.2.1,17,53,53\n"
    value = published_analysis(client, db, superuser_token_headers, tmp_path, monkeypatch, raw_text=raw)
    value["root"] = f"/api/v1/projects/{value['project_id']}/netflow-analyses/{value['analysis_id']}"
    value["headers"] = superuser_token_headers
    return value


def _get(client: TestClient, fixture: dict[str, Any], suffix: str, **params: Any) -> dict[str, Any]:
    response = client.get(fixture["root"] + suffix, headers=fixture["headers"], params=params)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    return response.json()


def _post(client: TestClient, fixture: dict[str, Any], parent: str, responses: list[dict[str, Any]],
          *, key: str | None = None, status: int = 201, headers: dict[str, str] | None = None) -> dict[str, Any]:
    response = client.post(fixture["root"] + "/feedback",
                           headers={**(headers or fixture["headers"]), "Idempotency-Key": key or str(uuid.uuid4())},
                           json={"expected_parent_id": parent, "responses": responses})
    assert response.status_code == status, response.text
    return response.json()


def _response(task: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    return {"task_id": task["task_id"], "provided_by": "Unauthenticated provider declaration",
            "submitted_at": "2000-01-01T00:00:00Z", "answers": answers, "note_checks": []}


SERVICE = {"responsible_unit": "Synthetic business", "supporting_evidence": ["synthetic:config"],
           "business_role": "service_provider", "actual_service": "Synthetic HTTPS", "business_purpose": "Test only",
           "external_access_need": "not_required", "access_control": "Synthetic deny"}
EXPORT = {"responsible_unit": "Synthetic collector", "supporting_evidence": ["synthetic:export"],
          "sampling": {"mode": "unsampled", "rate": 1}, "input_timezone": "UTC",
          "counter_semantics": "Unscaled", "export_selection": "All synthetic rows",
          "observation_view": "INTERNAL", "direction_semantics": "Declared source",
          "tcp_flags_semantics": "Bit union"}


def test_frozen_dependency_pagination_replacement_and_actor(
    client: TestClient, review_analysis: dict[str, Any],
) -> None:
    f = review_analysis
    original = _get(client, f, "/feedback")
    initial = original["feedback_revision_id"]
    assert initial == f["feedback_revision_id"]
    assert original["system_generated"] and original["authenticated_actor_id"] is None
    tasks = _get(client, f, "/review-tasks", limit=100)
    services = [item for item in tasks["data"] if item["task"]["task_kind"] == "service"]
    assert len(services) == 30
    export = next(item for item in tasks["data"] if item["task"]["task_kind"] == "export")
    assert all(item["material_status"] == "AWAITING_FEEDBACK" for item in tasks["data"])
    first = _post(client, f, initial, [_response(item, SERVICE) for item in services])
    fixed = first["feedback_revision_id"]
    page1 = _get(client, f, "/review-tasks", feedback_revision_id=fixed,
                 material_status="AWAITING_DEPENDENCY_MATERIAL", limit=25)
    assert page1["count"] == 30 and len(page1["data"]) == 25
    corrected = _post(client, f, fixed, [_response(export, EXPORT)])
    page2 = _get(client, f, "/review-tasks", feedback_revision_id=fixed,
                 material_status="AWAITING_DEPENDENCY_MATERIAL", skip=25, limit=25)
    assert page2["feedback_revision_id"] == fixed and page2["count"] == 30
    old_ids = [item["task_id"] for item in page1["data"] + page2["data"]]
    assert old_ids == sorted(item["task_id"] for item in services)
    newer = _get(client, f, "/review-tasks", feedback_revision_id=corrected["feedback_revision_id"],
                 task_kind="service", material_status="FIELDS_COMPLETE_PENDING_REVIEW", limit=100)
    assert newer["count"] == 30
    detail = _get(client, f, "/review-tasks/" + quote(services[0]["task_id"], safe=""),
                  feedback_revision_id=fixed)
    assert detail["material"]["material_status"] == "AWAITING_DEPENDENCY_MATERIAL"
    assert detail["dependencies"][0]["material_status"] == "AWAITING_FEEDBACK"
    assert "actual_service" in detail["material"]["answer_schema"]["properties"]
    actor = newer["data"][0]["authenticated_author"]
    assert actor["actor_id"] == str(f["actor"].id)
    assert actor["feedback_revision_id"] == fixed
    assert actor["submitted_at"] != "2000-01-01T00:00:00Z"
    assert newer["data"][0]["provider_claim"]["provided_by"] == "Unauthenticated provider declaration"
    assert all(item["review_required"] and not item["task_closed"] and not item["facts_changed"]
               for item in newer["data"])
    empty = _post(client, f, corrected["feedback_revision_id"], [_response(services[0], {})])
    changed = _get(client, f, "/review-tasks/" + quote(services[0]["task_id"], safe=""),
                   feedback_revision_id=empty["feedback_revision_id"])["material"]
    assert changed["declared_answers"] == {} and changed["material_status"] == "MATERIAL_INCOMPLETE"
    untouched = _get(client, f, "/review-tasks/" + quote(services[1]["task_id"], safe=""),
                     feedback_revision_id=empty["feedback_revision_id"])["material"]
    assert untouched["declared_answers"] == SERVICE
    assert untouched["authenticated_author"]["feedback_revision_id"] == fixed
    invalid = _post(client, f, empty["feedback_revision_id"], [_response(export, {**EXPORT, "input_timezone": "Invalid/Zone"})])
    invalid_task = _get(client, f, "/review-tasks/" + quote(export["task_id"], safe=""),
                        feedback_revision_id=invalid["feedback_revision_id"])["material"]
    assert invalid_task["material_status"] == "INVALID_MATERIAL"
    assert not invalid_task["task_closed"] and not invalid_task["facts_changed"]
    assert _get(client, f, "/feedback", feedback_revision_id=initial) == original


def test_feedback_idempotency_parent_scope_and_patch_validation(
    client: TestClient, review_analysis: dict[str, Any], db: Session,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = review_analysis
    parent = f["feedback_revision_id"]
    task = _get(client, f, "/review-tasks")["data"][0]
    patch = [_response(task, {})]
    saved = _post(client, f, parent, patch, key="fixed-request")
    assert _post(client, f, parent, patch, key="fixed-request") == saved
    recovered = _get(client, f, "/feedback/operations/fixed-request")
    assert recovered == saved
    assert _post(client, f, parent, [], key="fixed-request", status=409)["detail"]["code"] == "netflow_key_conflict"
    assert _post(client, f, parent, patch, status=409)["detail"]["code"] == "netflow_revision_conflict"
    _post(client, f, str(uuid.uuid4()), patch, status=404)
    _post(client, f, saved["feedback_revision_id"], patch * 2, status=422)
    _post(client, f, saved["feedback_revision_id"], [_response(task, {"foreign_kind_field": True})], status=422)
    for suffix in ("/feedback", "/review-tasks", "/review-tasks/" + quote(task["task_id"], safe="")):
        response = client.get(f["root"] + suffix, headers=f["headers"],
                              params={"feedback_revision_id": str(uuid.uuid4())})
        assert response.status_code == 404
    other = _project(client, f["headers"])
    assert client.get(f"/api/v1/projects/{other['id']}/netflow-analyses/{f['analysis_id']}/feedback",
                      headers=f["headers"]).status_code == 404
    viewer = _member(client, f["headers"], f["project_id"], ["viewer"])
    assert client.get(f["root"] + "/feedback/operations/fixed-request", headers=viewer).status_code == 404
    assert _get(client, f, "/feedback")["feedback_revision_id"] == saved["feedback_revision_id"]
    second = published_analysis(client, db, f["headers"], tmp_path, monkeypatch)
    for suffix in ("/feedback", "/review-tasks"):
        response = client.get(f["root"] + suffix, headers=f["headers"],
                              params={"feedback_revision_id": second["feedback_revision_id"]})
        assert response.status_code == 404
    _post(client, f, second["feedback_revision_id"], patch, status=404)


def test_peers_evidence_exact_filters_counts_and_source_separation(
    client: TestClient, review_analysis: dict[str, Any],
) -> None:
    f = review_analysis
    peers = _get(client, f, "/peers", limit=1)
    assert peers["count"] == peers["total_peers"] == 3
    assert peers["total_peer_records"] == 86
    exact = _get(client, f, "/peers", ip="::ffff:198.51.100.1", protocol=6, peer_port=53000)
    assert exact["count"] == 1 and exact["data"][0]["source_record_count"] == 55
    assert not exact["data"][0]["is_local_candidate"]
    assert _get(client, f, "/peers", ip="198.51.100.1", protocol=17)["count"] == 0
    assert _get(client, f, "/peers", ip="198.51.100.1", peer_port=443)["count"] == 0
    peer_key = exact["data"][0]["peer_key"]
    evidence = _get(client, f, "/evidence", peer_key=peer_key, limit=1)
    assert evidence["side"] == "peer" and evidence["source_record_count"] == 55
    assert evidence["count"] == evidence["retained_count"]
    assert evidence["retained_count"] + evidence["omitted_count"] == 55
    assert evidence["omitted_count"] > 0 and len(evidence["data"]) == 1
    assert evidence["data"][0]["peer_key"] == peer_key and evidence["object_key"] is None
    assert len(evidence["input_sha256"]) == len(evidence["artifact_sha256"]) == 64
    source = _get(client, f, "/review-tasks", task_kind="service", limit=100)["data"]
    source_task = next(item for item in source if item["task"]["target"]["ip"] == "192.0.2.1")
    local = _get(client, f, "/evidence", object_key=source_task["task"]["object_key"])
    assert local["side"] == "source" and local["source_record_count"] == 27
    assert local["retained_count"] + local["omitted_count"] == 27
    for params in ({"peer_key": peer_key, "path": "/etc/passwd"}, {"url": "http://localhost"},
                   {"peer_key": peer_key, "offset": 0}, {"peer_key": peer_key, "object_key": source_task["task"]["object_key"]}):
        assert client.get(f["root"] + "/evidence", headers=f["headers"], params=params).status_code == 422
    assert client.get(f["root"] + "/peers", headers=f["headers"], params={"ip": "fe80::1%en0"}).status_code == 422


def test_roles_archive_and_current_context_revocation(
    client: TestClient, db: Session, review_analysis: dict[str, Any],
) -> None:
    f = review_analysis
    for role in ("viewer", "approver"):
        headers = _member(client, f["headers"], f["project_id"], [role])
        assert client.get(f["root"] + "/feedback", headers=headers).status_code == 200
        _post(client, f, f["feedback_revision_id"], [], status=403, headers=headers)
    operator = _member(client, f["headers"], f["project_id"], ["operator"])
    saved = _post(client, f, f["feedback_revision_id"], [], headers=operator)
    assert saved["authenticated_actor_id"] != str(f["actor"].id)
    membership = db.exec(select(ProjectMembership).where(
        ProjectMembership.project_id == uuid.UUID(f["project_id"]),
        ProjectMembership.user_id == uuid.UUID(saved["authenticated_actor_id"]))).one()
    membership.revoked_at = get_datetime_utc()
    db.add(membership)
    db.commit()
    for suffix in ("/feedback", "/review-tasks", "/peers"):
        assert client.get(f["root"] + suffix, headers=operator).status_code == 404
    project = f["project"]
    project.archived_at = get_datetime_utc()
    db.add(project)
    db.commit()
    assert client.get(f["root"] + "/feedback", headers=f["headers"]).status_code == 200
    response = client.post(f["root"] + "/feedback", headers={**f["headers"], "Idempotency-Key": "archived"},
                           json={"expected_parent_id": saved["feedback_revision_id"], "responses": []})
    assert response.status_code in (403, 409)
    project.archived_at = None
    db.add(project)
    context = db.get(NetFlowContextRevision, uuid.UUID(f["context_revision_id"]))
    assert context is not None
    revoked = NetFlowContextRevision(
        tenant_id=context.tenant_id, project_id=context.project_id, dataset_id=context.dataset_id,
        parent_id=context.id, revision=context.revision + 1, network_namespace=context.network_namespace,
        state="REVOKED", raw_sha256=context.raw_sha256, normalized_sha256=context.normalized_sha256,
        payload=context.payload, created_by=f["actor"].id, operation_key=str(uuid.uuid4()), request_sha256="b" * 64)
    db.add(revoked)
    db.commit()
    for suffix in ("/feedback", "/review-tasks", "/peers"):
        response = client.get(f["root"] + suffix, headers=f["headers"])
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "netflow_context_revoked"
