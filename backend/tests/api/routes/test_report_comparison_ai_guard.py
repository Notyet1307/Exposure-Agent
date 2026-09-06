import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlmodel import Session, col, select, update

from app.core.config import settings
from app.domain import ai_governance_drafts as drafts
from app.domain.models import (
    AiGovernanceDraft,
    AiGovernanceDraftFindingBinding,
    Evidence,
    GovernanceRun,
)
from app.integrations.agent_compose import AgentComposeClient
from tests.api.routes.test_ai_governance_draft_requests import (
    _create_reserved_pending_draft,
)
from tests.api.routes.test_report_comparison_evidence import (
    _bind,
    _prepare_binding,
    _publish_bound_report,
    binding_run,
)
from tests.domain.test_ai_governance_drafts import _report_with_evidence_plan

__all__ = ["binding_run"]


@pytest.mark.parametrize("mixed", [False, True])
def test_ai_target_parser_and_runner_reference_explicitly_reject_fifth_column(
    mixed: bool,
) -> None:
    item = Evidence(
        tenant_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        governance_run_id=uuid.uuid4(),
        governance_report_id=uuid.uuid4(),
        ip_source_comparison_fact_id=uuid.uuid4(),
        finding_transition_id=uuid.uuid4() if mixed else None,
    )
    for loader in (drafts._evidence_target, drafts._evidence_reference):
        with pytest.raises(
            drafts.AiGovernanceDraftStateError, match="evidence_not_bound"
        ):
            loader(item)


def test_v1_canonical_parser_does_not_gain_comparison_target() -> None:
    report = _report_with_evidence_plan([])
    report.canonical_content["evidence_plan"]["entries"] = [
        {
            "coverage": "CURRENT_RUN_TRANSITION",
            "finding_id": str(uuid.uuid4()),
            "finding_type": "UNOBSERVED_ASSET",
            "canonical_ip": "192.0.2.1",
            "transition_type": "OPENED",
            "evidence_reference": {
                "governance_run_id": str(report.governance_run_id),
                "fact_type": "IP_SOURCE_COMPARISON",
                "fact_id": str(uuid.uuid4()),
            },
        }
    ]
    with pytest.raises(
        drafts.AiGovernanceDraftStateError, match="report_evidence_plan_invalid"
    ):
        drafts._canonical_evidence_bindings(report)


def test_legal_v2_post_and_repeated_request_stop_before_evidence_or_session(
    binding_run: GovernanceRun,
    db: Session,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    run = binding_run
    facts, candidate, report = _prepare_binding(db, run)
    _bind(db, run, report, facts, candidate)
    _publish_bound_report(
        session=db, run=run, facts=facts, candidate=candidate, report=report
    )
    db.commit()

    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("v2 must stop before Evidence parsing, model or Session")

    monkeypatch.setattr(drafts, "_canonical_evidence_bindings", forbidden)
    monkeypatch.setattr(AgentComposeClient, "start_ai_governance_draft", forbidden)
    monkeypatch.setattr(AgentComposeClient, "get_run", forbidden)
    url = f"{settings.API_V1_STR}/projects/{run.project_id}/governance-reports/{report.id}/ai-governance-drafts"
    finding_id = next(
        item.finding_id
        for item in facts.governance.finding_lifecycles
        if item.finding_type == "UNOBSERVED_ASSET"
    )
    for _ in range(2):
        response = client.post(
            url,
            headers={
                **superuser_token_headers,
                "Idempotency-Key": "comparison-ai-rejected",
            },
            json={"finding_ids": [finding_id]},
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "draft_report_contract_unsupported"
    assert not db.exec(
        select(AiGovernanceDraft).where(
            AiGovernanceDraft.governance_report_id == report.id
        )
    ).all()


def test_v1_persisted_binding_and_real_runner_reload_reject_comparison_target(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    draft_id, run_id = _create_reserved_pending_draft(
        client=client,
        superuser_token_headers=superuser_token_headers,
        db=db,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    draft = db.get(AiGovernanceDraft, draft_id)
    assert draft is not None
    session_id = uuid.uuid4().hex + uuid.uuid4().hex
    drafts.bind_draft_session(
        session=db, draft=draft, agent_compose_run_id=run_id, session_id=session_id
    )
    baseline = drafts.load_draft_runner_inputs(
        session=db, draft_id=draft_id, session_id=session_id
    )
    assert baseline.findings
    selection = db.exec(
        select(AiGovernanceDraftFindingBinding).where(
            AiGovernanceDraftFindingBinding.draft_id == draft_id,
        )
    ).first()
    assert selection is not None
    db.connection().exec_driver_sql("SET LOCAL session_replication_role = replica")
    db.exec(
        update(Evidence)
        .where(col(Evidence.id) == selection.evidence_id)
        .values(
            source_snapshot_id=None,
            observation_id=None,
            finding_occurrence_id=None,
            finding_transition_id=None,
            ip_source_comparison_fact_id=uuid.uuid4(),
        )
    )
    db.expire_all()
    with pytest.raises(drafts.AiGovernanceDraftStateError, match="evidence_not_bound"):
        drafts.load_draft_runner_inputs(
            session=db, draft_id=draft_id, session_id=session_id
        )
    db.rollback()
