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


def _allow_session_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(AgentComposeClient, "get_run", lambda *_args, **_kwargs: None)

    def start(
        client: AgentComposeClient,
        *,
        client_request_id: str,
        draft_id: str,
    ) -> AgentComposeRunStart:
        assert client_request_id == f"ai-governance-draft:{draft_id}"
        return AgentComposeRunStart(
            run_id=client.expected_ai_governance_draft_run_id(client_request_id),
            started=True,
            status="RUN_STATUS_SUCCEEDED",
            session_id=hashlib.sha256(f"review:{draft_id}".encode()).hexdigest(),
        )

    monkeypatch.setattr(AgentComposeClient, "start_ai_governance_draft", start)


def _request_context(
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
    idempotency_key: str,
) -> tuple[uuid.UUID, dict[str, Any]]:
    response = client.post(
        f"{settings.API_V1_STR}/projects/{project_id}/governance-reports/"
        f"{report_id}/ai-governance-drafts",
        headers={**headers, "Idempotency-Key": idempotency_key},
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


@pytest.mark.parametrize("decision", ["ACCEPTED", "EDITED", "REJECTED"])
def test_operator_completes_exactly_one_terminal_review_without_mutating_model_output(
    decision: str,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _request_context(
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
        idempotency_key=f"rel003-oracle-review-{decision.lower()}",
    )
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

    endpoint = (
        f"{settings.API_V1_STR}/projects/{context['project_id']}/"
        f"governance-reports/{context['report_id']}/ai-governance-drafts/"
        f"{draft_id}/review"
    )
    reviewed = client.post(
        endpoint,
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

    second_review = client.post(
        endpoint,
        headers=context["operator_headers"],
        json=request_body,
    )
    assert second_review.status_code == 409, second_review.text
    assert second_review.json()["detail"] == "draft_already_reviewed"

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
        assert audit.target_type == "ai_governance_draft"


def test_review_rejects_fields_outside_the_editorial_contract(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _request_context(
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
        idempotency_key="rel003-oracle-review-invalid-edit",
    )
    response = client.post(
        f"{settings.API_V1_STR}/projects/{context['project_id']}/"
        f"governance-reports/{context['report_id']}/ai-governance-drafts/"
        f"{draft_id}/review",
        headers=context["operator_headers"],
        json={
            "decision": "EDITED",
            "edited_output": {
                "findings": [
                    {
                        "finding_id": str(context["finding_id"]),
                        "rescan_recommendation": "Allowed edit.",
                        "pending_verifications": [],
                        "limitations": [],
                        "evidence_ids": [
                            model_output["recommendations"][0]["claims"][0][
                                "evidence_ids"
                            ][0]
                        ],
                    }
                ]
            },
        },
    )
    assert response.status_code == 422, response.text
    with Session(engine) as session:
        unchanged = session.get(AiGovernanceDraft, draft_id)
        assert unchanged is not None
        assert unchanged.review_decision is None
