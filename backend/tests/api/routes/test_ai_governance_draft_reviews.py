import hashlib
import uuid
from pathlib import Path
from typing import Any, TypedDict

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.domain import ai_governance_drafts as draft_service
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
from tests.api.routes.test_governance_runs import _create_member


class _ReviewableDraft(TypedDict):
    id: str
    report_id: str
    finding_id: str
    model_output: dict[str, Any]


def _review_url(
    *, project_id: object, report_id: object, draft_id: object
) -> str:
    return (
        f"{settings.API_V1_STR}/projects/{project_id}/governance-reports/"
        f"{report_id}/ai-governance-drafts/{draft_id}/review"
    )


def _reviewable_draft_context(
    *,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> tuple[dict[str, object], dict[str, str], _ReviewableDraft]:
    project, report, operator_headers, selected_id, request_url = (
        _operator_draft_request_context(
            client=client,
            superuser_token_headers=superuser_token_headers,
            db=db,
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
        )
    )

    def start_draft(
        _client: AgentComposeClient, *, client_request_id: str, draft_id: str
    ) -> AgentComposeRunStart:
        return AgentComposeRunStart(
            run_id=AgentComposeClient().expected_ai_governance_draft_run_id(
                client_request_id
            ),
            started=True,
            status="RUN_STATUS_PENDING",
            session_id=hashlib.sha256(draft_id.encode()).hexdigest(),
        )

    monkeypatch.setattr(AgentComposeClient, "start_ai_governance_draft", start_draft)
    requested = client.post(
        request_url,
        headers={**operator_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"finding_ids": [selected_id]},
    )
    assert requested.status_code == 202, requested.text
    draft_id = uuid.UUID(requested.json()["id"])

    with Session(engine) as session:
        draft = session.get(AiGovernanceDraft, draft_id)
        assert draft is not None
        bindings = session.exec(
            select(AiGovernanceDraftFindingBinding).where(
                AiGovernanceDraftFindingBinding.draft_id == draft.id
            )
        ).all()
        output = AiDraftModelOutput.model_validate(
            {
                "report_sha256": draft.report_sha256,
                "summary": "Bounded interpretation of the deterministic report.",
                "recommendations": [
                    {
                        "finding_id": str(binding.finding_id),
                        "rescan_recommendation": "Verify the exposure.",
                        "pending_verifications": ["Confirm the system owner."],
                        "limitations": ["Based on the current report only."],
                        "claims": [
                            {
                                "claim_id": f"claim-{binding.finding_id}",
                                "evidence_ids": [str(binding.evidence_id)],
                            }
                        ],
                    }
                    for binding in bindings
                ],
            }
        )
        reviewable = draft_service.mark_draft_reviewable(
            session=session, draft=draft, model_output=output
        )
        model_output = reviewable.model_output
    assert model_output is not None
    return project, operator_headers, {
        "id": str(draft_id),
        "report_id": str(report.id),
        "finding_id": selected_id,
        "model_output": model_output,
    }


def test_operator_records_one_edited_review_without_mutating_model_output(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, operator_headers, draft = _reviewable_draft_context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    url = _review_url(
        project_id=project["id"], report_id=draft["report_id"], draft_id=draft["id"]
    )
    request_body = {
        "decision": "EDITED",
        "edited_output": {
            "findings": [
                {
                    "finding_id": draft["finding_id"],
                    "rescan_recommendation": "Verify with the owner.",
                    "pending_verifications": ["Confirm remediation timing."],
                    "limitations": ["No remediation evidence is available."],
                }
            ]
        },
    }

    reviewed = client.post(url, headers=operator_headers, json=request_body)

    assert reviewed.status_code == 200, reviewed.text
    body = reviewed.json()
    assert body["review_decision"] == "EDITED"
    assert body["model_output"] == draft["model_output"]
    assert body["operator_edited_output"] == request_body["edited_output"]
    assert body["finding_ids"] == [draft["finding_id"]]

    again = client.post(url, headers=operator_headers, json=request_body)
    assert again.status_code == 409
    assert again.json()["detail"] == "draft_already_reviewed"
    with Session(engine) as session:
        persisted = session.get(AiGovernanceDraft, uuid.UUID(draft["id"]))
        assert persisted is not None
        assert persisted.model_output == draft["model_output"]
        assert persisted.review_decision == "EDITED"
        events = session.exec(
            select(AuditEvent).where(
                AuditEvent.target_id == persisted.id,
                AuditEvent.action == "ai_governance_draft.reviewed",
            )
        ).all()
        assert len(events) == 1
        assert events[0].after_data == {"review_decision": "EDITED"}


def test_review_rejects_non_operator_and_wrong_draft_scope_before_mutation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project, operator_headers, draft = _reviewable_draft_context(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    viewer_headers = _create_member(
        client, superuser_token_headers, project_id=project["id"], roles=["viewer"]
    )
    url = _review_url(
        project_id=project["id"], report_id=draft["report_id"], draft_id=draft["id"]
    )

    denied = client.post(url, headers=viewer_headers, json={"decision": "ACCEPTED"})
    wrong_scope = client.post(
        _review_url(
            project_id=project["id"],
            report_id=uuid.uuid4(),
            draft_id=draft["id"],
        ),
        headers=operator_headers,
        json={"decision": "ACCEPTED"},
    )

    assert denied.status_code == 404
    assert wrong_scope.status_code == 404
    with Session(engine) as session:
        persisted = session.get(AiGovernanceDraft, uuid.UUID(draft["id"]))
        assert persisted is not None
        assert persisted.review_decision is None
