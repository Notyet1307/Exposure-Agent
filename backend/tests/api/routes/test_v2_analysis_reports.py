import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.core.time import get_datetime_utc
from app.domain import comparison_results as comparisons
from app.domain import v2_analysis_reports as v2
from app.domain.models import (
    AnalysisReport,
    AnalysisReportRevisionRecord,
    GovernanceRun,
)
from tests.api.routes.test_ai_governance_draft_requests import (
    _configure_qualified_model,
)
from tests.api.routes.test_analysis_reports import _pending, _run
from tests.api.routes.test_core_comparisons import _create_core, _post, _setup_core
from tests.api.routes.test_governance_runs import _create_member
from tests.api.routes.test_netflow_datasets import _upload
from tests.utils.netflow_processing import (
    ControlPlane,
    context_request,
    execute,
    reserve,
)


def proposal(material: dict[str, Any]) -> dict[str, Any]:
    base = material["items"][0]["citation_id"]
    sample = material["samples"][0] if material["samples"] else None
    sections = (
        v2.ADDRESS_SECTIONS
        if material["subject"]["address_key"]
        else v2.REPORT_SECTIONS
    )
    result_id = material["subject"]["result_id"]
    return {
        "contract_version": v2.OUTPUT_VERSION,
        "text": {
            "summary": ["facts", "check"],
            "sections": [
                {
                    "id": section,
                    "claim_ids": [
                        "facts"
                        if section in ("conclusion", "appendix", "known_facts")
                        else "check"
                    ],
                }
                for section in sections
            ],
            "claims": [
                {
                    "id": "facts",
                    "type": "fact",
                    "fact_refs": [f"fact:{result_id}:counts"],
                    "evidence_refs": [base],
                },
                {
                    "id": "check",
                    "type": "action",
                    "text": "请优先核对登记资料与采集范围，补充可比的来源依据。",
                    "fact_refs": [],
                    "evidence_refs": [base],
                },
            ],
            "priority_cases": []
            if sample is None
            else [
                {
                    "address_key": sample["address_key"],
                    "why_review": "所选资料中的登记与观测记录需要核对。",
                    "next_check": "请补充该地址的登记依据和采集范围说明。",
                    "evidence_refs": sample["evidence_refs"],
                }
            ],
            "limitations": [],
        },
    }


@pytest.fixture
def context(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    core = _setup_core(client, db, superuser_token_headers, tmp_path, monkeypatch)
    result = _create_core(client, core)
    _configure_qualified_model(session=db, monkeypatch=monkeypatch)
    return {
        **core,
        "result": result,
        "url": core["root"] + "/analysis-reports/v2",
        "body": {
            "result_id": result["id"],
            "supplement_binding_id": None,
            "language": "zh",
            "audience": "management",
        },
    }


def generate(
    client: TestClient,
    context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    key: str,
) -> dict[str, Any]:
    created = client.post(
        context["url"],
        headers=context["headers"] | {"Idempotency-Key": key},
        json=context["body"],
    )
    assert created.status_code == 201, created.text
    report = created.json()
    assert (
        _run(
            monkeypatch,
            report["id"],
            lambda **kwargs: proposal(kwargs["tools"]["read_report_material"]({})),
        )
        == 0
    )
    response = client.get(
        context["url"] + "/" + report["id"], headers=context["headers"]
    )
    assert response.status_code == 200, response.text
    completed: dict[str, Any] = response.json()
    assert completed["status"] == "DRAFT" and completed["readable"], completed[
        "failure_code"
    ]
    assert completed["text"] is not None and completed["material"] is not None
    return completed


def test_v2_no_run_generation_edit_confirm_and_immutable_revisions(
    client: TestClient,
    db: Session,
    context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starts = _pending(monkeypatch)
    report = generate(client, context, monkeypatch, "v2-full")
    assert report["status"] == "DRAFT" and report["readable"]
    assert report["material"]["summary"]["total_addresses"] == 3
    assert report["supplement_binding_id"] is None
    assert (
        db.exec(
            select(GovernanceRun).where(
                GovernanceRun.project_id == context["project"].id
            )
        ).all()
        == []
    )
    replay = client.post(
        context["url"],
        headers=context["headers"] | {"Idempotency-Key": "v2-full"},
        json=context["body"],
    )
    assert replay.status_code == 200 and replay.json()["id"] == report["id"]
    assert starts == [report["id"]]
    url = context["url"] + "/" + report["id"]
    edit = client.patch(
        url,
        headers=context["headers"],
        json={
            "expected_revision": 1,
            "edits": {"check": "先核对登记责任人与采集范围，补充书面依据。"},
        },
    )
    assert edit.status_code == 200, edit.text
    edited = edit.json()
    assert edited["original_output"] == report["original_output"]
    assert edited["text"]["claims"][0] == report["text"]["claims"][0]
    assert (
        client.patch(
            url,
            headers=context["headers"],
            json={"expected_revision": 1, "edits": {"check": "覆盖另一个人的修改。"}},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            url,
            headers=context["headers"],
            json={"expected_revision": 2, "edits": {"facts": "修改权威统计。"}},
        ).status_code
        == 409
    )
    confirmed = client.post(
        url + "/confirm", headers=context["headers"], json={"expected_revision": 2}
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "CONFIRMED"
    assert (
        client.patch(
            url,
            headers=context["headers"],
            json={"expected_revision": 3, "edits": {"check": "修改确认版。"}},
        ).status_code
        == 409
    )
    history = client.get(url + "/revisions", headers=context["headers"])
    assert history.status_code == 200
    assert [item["revision"] for item in history.json()] == [3, 2, 1]
    assert history.json()[-1]["text"] == report["text"]
    with Session(engine) as session:
        saved = session.exec(
            select(AnalysisReportRevisionRecord).where(
                AnalysisReportRevisionRecord.report_id == uuid.UUID(report["id"])
            )
        ).first()
        assert saved
        with pytest.raises(DBAPIError):
            session.execute(
                text(
                    "UPDATE analysis_report_revisions SET text = '{}'::jsonb WHERE id=:id"
                ),
                {"id": saved.id},
            )
            session.commit()
        session.rollback()


def test_v2_acl_strict_binding_and_unknown_operation_replay(
    client: TestClient,
    db: Session,
    context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    superuser_token_headers: dict[str, str],
) -> None:
    starts = _pending(monkeypatch)
    viewer = _create_member(
        client,
        superuser_token_headers,
        project_id=str(context["project"].id),
        roles=["viewer"],
    )
    response = client.post(
        context["url"],
        headers=viewer | {"Idempotency-Key": "viewer-v2"},
        json=context["body"],
    )
    assert response.status_code == 404
    params = context["body"]
    state = client.get(
        context["url"] + "/readiness",
        headers=viewer,
        params={key: value for key, value in params.items() if value is not None},
    )
    assert state.json()["state"] == "NO_PERMISSION"
    no_binding = {
        key: value
        for key, value in context["body"].items()
        if key != "supplement_binding_id"
    }
    assert (
        client.post(
            context["url"],
            headers=context["headers"] | {"Idempotency-Key": "missing-binding"},
            json=no_binding,
        ).status_code
        == 422
    )
    created = client.post(
        context["url"],
        headers=context["headers"] | {"Idempotency-Key": "unknown-v2"},
        json=context["body"],
    )
    assert created.status_code == 201, created.text
    report = created.json()
    receipt = client.get(
        context["url"] + "/operations/unknown-v2", headers=context["headers"]
    )
    assert receipt.status_code == 200 and receipt.json()["id"] == report["id"]
    assert starts == [report["id"]]
    different = {**context["body"], "language": "en"}
    assert (
        client.post(
            context["url"],
            headers=context["headers"] | {"Idempotency-Key": "unknown-v2"},
            json=different,
        ).status_code
        == 409
    )
    assert (
        client.get(
            context["root"] + "/analysis-reports/" + report["id"],
            headers=context["headers"],
        ).status_code
        == 404
    )
    forged = {**context["body"], "result_id": str(uuid.uuid4())}
    assert (
        client.post(
            context["url"],
            headers=context["headers"] | {"Idempotency-Key": "forged-result"},
            json=forged,
        ).status_code
        == 409
    )
    record = db.get(AnalysisReport, uuid.UUID(report["id"]))
    assert record is not None and record.run_id is None


def test_bound_supplement_expiry_masks_all_report_consumers(
    client: TestClient,
    db: Session,
    context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "NETFLOW_ALLOW_TEST_FIXTURES", True)
    monkeypatch.setattr(settings, "GOVERNANCE_RUNNER_BUILD_VERSION", "synthetic-core")
    control = ControlPlane(monkeypatch)
    raw = b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n192.0.2.20,203.0.113.1,6,50000,443\n"
    upload = _upload(client, context["headers"], str(context["project"].id), raw)
    assert upload.status_code == 201
    dataset_url = context["root"] + "/netflow-datasets/" + upload.json()["id"]
    current = _post(
        client,
        dataset_url + "/processing-contexts",
        context["headers"],
        context_request(network_namespace="synthetic-core"),
        "report-nf-context",
    )
    setup = {
        "dataset_url": dataset_url,
        "context_revision_id": current["context_revision_id"],
        "headers": context["headers"],
        "control": control,
    }
    queued = reserve(client, setup, key="v2-report-nf")
    execute(db, setup, queued["analysis_id"])
    deadline = get_datetime_utc() + timedelta(minutes=5)
    binding = _post(
        client,
        context["root"]
        + "/comparison-results/"
        + context["result"]["id"]
        + "/supplements",
        context["headers"],
        {
            "analysis_id": queued["analysis_id"],
            "valid_until": deadline.isoformat(),
            "scope_evidence": "Synthetic same-space evidence.",
            "expected_binding_id": None,
        },
        "report-binding",
    )
    _pending(monkeypatch)
    context["body"]["supplement_binding_id"] = binding["id"]
    report = generate(client, context, monkeypatch, "with-supplement")
    old_hash = report["material_sha256"]
    monkeypatch.setattr(
        comparisons, "get_datetime_utc", lambda: deadline + timedelta(seconds=1)
    )
    url = context["url"] + "/" + report["id"]
    unavailable = client.get(url, headers=context["headers"])
    assert unavailable.status_code == 200
    value = unavailable.json()
    assert not value["readable"]
    assert (
        value["text"] is None
        and value["original_output"] is None
        and value["material"] is None
    )
    assert value["material_sha256"] == old_hash
    assert (
        client.patch(
            url,
            headers=context["headers"],
            json={"expected_revision": 1, "edits": {"check": "使用过期资料。"}},
        ).status_code
        == 410
    )
    assert (
        client.post(
            url + "/confirm", headers=context["headers"], json={"expected_revision": 1}
        ).status_code
        == 410
    )
    assert client.get(url + "/revisions", headers=context["headers"]).status_code == 410
    listing = client.get(
        context["url"],
        headers=context["headers"],
        params={
            "result_id": context["result"]["id"],
            "supplement_binding_id": binding["id"],
        },
    )
    assert listing.status_code == 200 and listing.json()["data"][0]["material"] is None
    core = client.get(
        context["root"] + "/comparison-results/" + context["result"]["id"] + "/summary",
        headers=context["headers"],
    )
    assert core.status_code == 200 and core.json()["total_addresses"] == 3
