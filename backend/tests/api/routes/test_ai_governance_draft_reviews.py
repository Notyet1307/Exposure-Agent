from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import app.domain.ai_governance_drafts as draft_service
from app.core.config import settings
from app.core.db import engine
from app.domain.ai_governance_drafts import AiDraftModelOutput
from app.domain.models import (
    AiGovernanceDraft,
    AiGovernanceDraftFindingBinding,
    AuditEvent,
)
from app.integrations.agent_compose import AgentComposeClient, AgentComposeRunStart
from tests.api.routes.test_ai_governance_draft_requests import (
    _operator_draft_request_context,
)
from tests.api.routes.test_governance_runs import _create_member, _create_project


def _allow_session_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(AgentComposeClient, "get_run", lambda *_args, **_kwargs: None)

    def start(
        client: AgentComposeClient,
        *,
        client_request_id: str,
        draft_id: str,
    ) -> AgentComposeRunStart:
        return AgentComposeRunStart(
            run_id=client.expected_ai_governance_draft_run_id(client_request_id),
            started=True,
            status="RUN_STATUS_SUCCEEDED",
            session_id=hashlib.sha256(f"review:{draft_id}".encode()).hexdigest(),
        )

    monkeypatch.setattr(AgentComposeClient, "start_ai_governance_draft", start)


def _context(
    *,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    project, report, operator_headers, finding_id, _url = (
        _operator_draft_request_context(
            client=client,
            superuser_token_headers=superuser_token_headers,
            db=db,
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
        )
    )
    return {
        "project_id": uuid.UUID(str(project["id"])),
        "report_id": report.id,
        "operator_headers": operator_headers,
        "finding_id": uuid.UUID(finding_id),
    }


def _reviewable_draft(
    *,
    client: TestClient,
    headers: dict[str, str],
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    finding_id: uuid.UUID,
) -> tuple[uuid.UUID, dict[str, Any]]:
    _key = f"review-route-{uuid.uuid4()}"
    response = client.post(
        f"{settings.API_V1_STR}/projects/{project_id}/governance-reports/"
        f"{report_id}/ai-governance-drafts",
        headers={**headers, "Idempotency-Key": _key},
        json={"finding_ids": [str(finding_id)]},
    )
    assert response.status_code == 202, response.text
    draft_id = uuid.UUID(response.json()["id"])
    with Session(engine) as session:
        draft = session.get(AiGovernanceDraft, draft_id)
        assert draft is not None
        binding = session.exec(
            select(AiGovernanceDraftFindingBinding).where(
                AiGovernanceDraftFindingBinding.draft_id == draft_id
            )
        ).one()
        model_output = {
            "report_sha256": draft.report_sha256,
            "summary": "Immutable model-authored summary.",
            "recommendations": [
                {
                    "finding_id": str(binding.finding_id),
                    "rescan_recommendation": "Verify the selected asset.",
                    "pending_verifications": ["Confirm ownership."],
                    "limitations": ["One bounded observation."],
                    "claims": [
                        {
                            "claim_id": "claim-reviewable",
                            "evidence_ids": [str(binding.evidence_id)],
                        }
                    ],
                }
            ],
        }
        draft_service.mark_draft_reviewable(
            session=session,
            draft=draft,
            model_output=AiDraftModelOutput.model_validate(model_output),
        )
    return draft_id, model_output


def _review_endpoint(context: dict[str, Any], draft_id: uuid.UUID) -> str:
    return (
        f"{settings.API_V1_STR}/projects/{context['project_id']}/"
        f"governance-reports/{context['report_id']}/ai-governance-drafts/"
        f"{draft_id}/review"
    )


def _detail_endpoint(context: dict[str, Any], draft_id: uuid.UUID) -> str:
    return _review_endpoint(context, draft_id).removesuffix("/review")


@pytest.mark.parametrize("decision", ["ACCEPTED", "EDITED", "REJECTED"])
def test_operator_reads_and_records_exactly_one_terminal_review(
    decision: str,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    _allow_session_start(monkeypatch)
    draft_id, original_model_output = _reviewable_draft(
        client=client,
        headers=context["operator_headers"],
        project_id=context["project_id"],
        report_id=context["report_id"],
        finding_id=context["finding_id"],
    )

    detail = client.get(
        _detail_endpoint(context, draft_id),
        headers=context["operator_headers"],
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["model_output"] == original_model_output
    assert detail.json()["review_decision"] is None

    edited_output = {
        "findings": [
            {
                "finding_id": str(context["finding_id"]),
                "rescan_recommendation": "Operator-edited recommendation.",
                "pending_verifications": ["Operator verification."],
                "limitations": ["Operator limitation."],
            }
        ]
    }
    request_body: dict[str, Any] = {"decision": decision}
    if decision == "EDITED":
        request_body["edited_output"] = edited_output

    reviewed = client.post(
        _review_endpoint(context, draft_id),
        headers=context["operator_headers"],
        json=request_body,
    )
    assert reviewed.status_code == 200, reviewed.text
    payload = reviewed.json()
    assert payload["review_decision"] == decision
    assert payload["model_output"] == original_model_output
    assert payload["operator_edited_output"] == (
        edited_output if decision == "EDITED" else None
    )
    assert payload["reviewed_at"] is not None

    second = client.post(
        _review_endpoint(context, draft_id),
        headers=context["operator_headers"],
        json=request_body,
    )
    assert second.status_code == 409, second.text
    assert second.json()["detail"] == "draft_already_reviewed"

    with Session(engine) as session:
        persisted = session.get(AiGovernanceDraft, draft_id)
        assert persisted is not None
        assert persisted.model_output == original_model_output
        audit = session.exec(
            select(AuditEvent).where(
                AuditEvent.action == "ai_governance_draft.reviewed",
                AuditEvent.target_id == draft_id,
            )
        ).one()
        assert audit.after_data == {"review_decision": decision}


def test_review_contract_rejects_field_escalation_and_wrong_scope(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    _allow_session_start(monkeypatch)
    draft_id, model_output = _reviewable_draft(
        client=client,
        headers=context["operator_headers"],
        project_id=context["project_id"],
        report_id=context["report_id"],
        finding_id=context["finding_id"],
    )
    endpoint = _review_endpoint(context, draft_id)

    invalid_bodies = [
        {"decision": "EDITED"},
        {
            "decision": "ACCEPTED",
            "edited_output": {
                "findings": [
                    {
                        "finding_id": str(context["finding_id"]),
                        "rescan_recommendation": "Not allowed for ACCEPTED.",
                        "pending_verifications": [],
                        "limitations": [],
                    }
                ]
            },
        },
        {
            "decision": "EDITED",
            "edited_output": {
                "findings": [
                    {
                        "finding_id": str(context["finding_id"]),
                        "rescan_recommendation": "Allowed editorial text.",
                        "pending_verifications": [],
                        "limitations": [],
                        "evidence_ids": model_output["recommendations"][0]["claims"][
                            0
                        ]["evidence_ids"],
                    }
                ]
            },
        },
    ]
    for body in invalid_bodies:
        invalid = client.post(
            endpoint,
            headers=context["operator_headers"],
            json=body,
        )
        assert invalid.status_code == 422, invalid.text

    wrong_report = client.post(
        endpoint.replace(str(context["report_id"]), str(uuid.uuid4())),
        headers=context["operator_headers"],
        json={"decision": "ACCEPTED"},
    )
    assert wrong_report.status_code == 404

    viewer_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=context["project_id"],
        roles=["viewer"],
    )
    approver_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=context["project_id"],
        roles=["approver"],
    )
    other_project = _create_project(client, superuser_token_headers)
    nonmember_headers = _create_member(
        client,
        superuser_token_headers,
        project_id=other_project["id"],
        roles=["operator"],
    )
    for restricted_headers in (
        viewer_headers,
        approver_headers,
        nonmember_headers,
    ):
        denied_read = client.get(
            _detail_endpoint(context, draft_id), headers=restricted_headers
        )
        denied_review = client.post(
            endpoint,
            headers=restricted_headers,
            json={"decision": "ACCEPTED"},
        )
        assert denied_read.status_code == 404
        assert denied_review.status_code == 404

    with Session(engine) as session:
        unchanged = session.get(AiGovernanceDraft, draft_id)
        assert unchanged is not None
        assert unchanged.review_decision is None


def test_global_admin_can_review_but_archived_project_is_read_only(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    _allow_session_start(monkeypatch)
    admin_draft_id, _ = _reviewable_draft(
        client=client,
        headers=context["operator_headers"],
        project_id=context["project_id"],
        report_id=context["report_id"],
        finding_id=context["finding_id"],
    )
    reviewed = client.post(
        _review_endpoint(context, admin_draft_id),
        headers=superuser_token_headers,
        json={"decision": "REJECTED"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review_decision"] == "REJECTED"

    archived_context = _context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    _allow_session_start(monkeypatch)
    archived_draft_id, _ = _reviewable_draft(
        client=client,
        headers=archived_context["operator_headers"],
        project_id=archived_context["project_id"],
        report_id=archived_context["report_id"],
        finding_id=archived_context["finding_id"],
    )
    archived = client.post(
        f"{settings.API_V1_STR}/projects/{archived_context['project_id']}/archive",
        headers=superuser_token_headers,
    )
    assert archived.status_code == 200, archived.text

    denied = client.post(
        _review_endpoint(archived_context, archived_draft_id),
        headers=archived_context["operator_headers"],
        json={"decision": "ACCEPTED"},
    )
    assert denied.status_code == 409
    assert denied.json()["detail"] == "Archived project is read-only"
