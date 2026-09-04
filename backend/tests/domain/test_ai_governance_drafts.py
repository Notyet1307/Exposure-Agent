import sys
import uuid
from dataclasses import fields
from inspect import signature
from typing import Any

import pytest

from app.domain.ai_governance_drafts import (
    AiDraftEditedOutput,
    AiDraftModelOutput,
    AiGovernanceDraftStateError,
    DraftFindingBinding,
    DraftRunnerHandoff,
    _is_failure_code,
    bind_draft_session,
    create_ai_governance_draft,
    fail_draft,
    mark_draft_reviewable,
    report_identity_hash,
    review_draft,
)
from app.domain.models import GovernanceReport


def _report(canonical_content: dict[str, Any]) -> GovernanceReport:
    return GovernanceReport(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        governance_run_id=uuid.uuid4(),
        report_contract_version="deterministic-report-v1",
        canonical_content=canonical_content,
        html_artifact_id=uuid.uuid4(),
        html_sha256="a" * 64,
        csv_artifact_id=uuid.uuid4(),
        csv_sha256="b" * 64,
    )


def _report_with_evidence_plan(entries: list[dict[str, Any]]) -> GovernanceReport:
    report = _report({"pending": True})
    report.canonical_content = {
        "schema_version": report.report_contract_version,
        "report": {
            "report_identity": {
                "governance_run_id": str(report.governance_run_id),
                "project_id": str(report.project_id),
                "report_contract_version": report.report_contract_version,
                "generation_mode": report.generation_mode,
            }
        },
        "evidence_plan": {
            "governance_run_id": str(report.governance_run_id),
            "report_contract_version": report.report_contract_version,
            "max_entries": 50,
            "entries": entries,
        },
    }
    return report


def _model_output(
    *,
    report_sha256: str,
    finding_ids: tuple[str, ...],
    evidence_by_finding: dict[str, tuple[str, ...]],
) -> AiDraftModelOutput:
    return AiDraftModelOutput.model_validate(
        {
            "report_sha256": report_sha256,
            "summary": "deterministic report interpretation",
            "recommendations": [
                {
                    "finding_id": finding_id,
                    "rescan_recommendation": "verify exposure",
                    "pending_verifications": ["owner is unknown"],
                    "limitations": ["single observation"],
                    "claims": [
                        {
                            "claim_id": f"claim-{finding_id}",
                            "evidence_ids": list(
                                evidence_by_finding.get(
                                    finding_id, (str(uuid.uuid4()),)
                                )
                            ),
                        }
                    ],
                }
                for finding_id in finding_ids
            ],
        }
    )


def _edited_output(finding_id: uuid.UUID) -> AiDraftEditedOutput:
    return AiDraftEditedOutput.model_validate(
        {
            "findings": [
                {
                    "finding_id": str(finding_id),
                    "rescan_recommendation": "edited text",
                    "pending_verifications": [],
                    "limitations": [],
                }
            ]
        }
    )


def test_report_identity_hash_is_stable_canonical_and_content_bound() -> None:
    report = _report({"report_identity": {"b": 1, "a": 2}})
    reordered = _report({"report_identity": {"a": 2, "b": 1}})
    changed = _report({"report_identity": {"a": 2, "b": 2}})

    digest = report_identity_hash(report)
    assert digest == report_identity_hash(reordered)
    assert digest != report_identity_hash(changed)
    assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")


def test_canonical_evidence_plan_requires_canonical_identity_values() -> None:
    from app.domain.ai_governance_drafts import _canonical_evidence_bindings

    finding_id = uuid.uuid4()
    fact_id = uuid.uuid4()
    report = _report_with_evidence_plan(
        [
            {
                "coverage": "OPEN_BACKLOG",
                "finding_id": str(finding_id),
                "finding_type": "UNOBSERVED_ASSET",
                "canonical_ip": "192.0.2.10",
                "transition_type": None,
                "evidence_reference": {
                    "governance_run_id": "pending",
                    "fact_type": "OBSERVATION",
                    "fact_id": str(fact_id),
                },
            }
        ]
    )
    entry = report.canonical_content["evidence_plan"]["entries"][0]
    entry["evidence_reference"]["governance_run_id"] = str(report.governance_run_id)

    bindings = _canonical_evidence_bindings(report)

    assert bindings[finding_id].fact_id == fact_id
    assert bindings[finding_id].canonical_ip == "192.0.2.10"

    entry["canonical_ip"] = "192.000.002.010"
    with pytest.raises(
        AiGovernanceDraftStateError,
        match="report_evidence_plan_invalid",
    ):
        _canonical_evidence_bindings(report)

    entry["canonical_ip"] = "192.0.2.10"
    entry["evidence_reference"]["governance_run_id"] = str(uuid.uuid4())
    with pytest.raises(
        AiGovernanceDraftStateError, match="report_evidence_plan_invalid"
    ):
        _canonical_evidence_bindings(report)


def test_runner_handoff_accepts_only_draft_and_session_identity() -> None:
    draft_id = uuid.uuid4()
    session_id = "c" * 64
    environment = {
        "AI_DRAFT_ID": str(draft_id),
        "AI_DRAFT_RUN_ID": "b" * 64,
        "SANDBOX_ID": session_id,
        "LLM_API_KEY": "secret-value",
        "PROMPT_TEXT": "complete prompt material",
        "EVIDENCE_PAYLOAD": "raw evidence payload",
    }

    handoff = DraftRunnerHandoff.from_environment(environment)

    assert handoff.draft_id == draft_id
    assert handoff.agent_compose_run_id == "b" * 64
    assert handoff.session_id == session_id
    assert {field.name for field in fields(DraftRunnerHandoff)} == {
        "draft_id",
        "agent_compose_run_id",
        "session_id",
    }


@pytest.mark.parametrize(
    "operation",
    (
        create_ai_governance_draft,
        bind_draft_session,
        mark_draft_reviewable,
        fail_draft,
        review_draft,
    ),
)
def test_draft_operations_do_not_accept_caller_audit_events(operation: Any) -> None:
    assert "audit_event" not in signature(operation).parameters


def test_failure_code_is_an_opaque_bounded_identifier() -> None:
    assert _is_failure_code("model_output_invalid")
    assert not _is_failure_code("Provider said: raw event payload")
    assert not _is_failure_code('{"provider_event":"secret"}')
    assert not _is_failure_code("a" * 101)


def test_runner_entry_rejects_all_command_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ai_draft_runner import main

    monkeypatch.setattr(sys, "argv", ["ai-draft-runner", "complete prompt material"])
    monkeypatch.setenv("AI_DRAFT_ID", str(uuid.uuid4()))
    monkeypatch.setenv("AI_DRAFT_RUN_ID", "b" * 64)
    monkeypatch.setenv("SANDBOX_ID", "c" * 64)

    assert main() == 1


def test_runner_terminal_stdout_contains_only_redacted_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    from app.ai_draft_runner import _terminal_output

    draft_id = uuid.uuid4()
    _terminal_output(
        draft_id=draft_id,
        status="FAILED",
        failure_code="model_binding_changed",
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload == {
        "draft_id": str(draft_id),
        "failure_code": "model_binding_changed",
        "status": "FAILED",
    }


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"AI_DRAFT_ID": "not-a-uuid", "SANDBOX_ID": "c" * 64},
        {"AI_DRAFT_ID": str(uuid.uuid4()), "SANDBOX_ID": "short"},
        {"AI_DRAFT_ID": str(uuid.uuid4()), "SANDBOX_ID": "z" * 64},
        {"AI_DRAFT_ID": "{" + str(uuid.uuid4()) + "}", "SANDBOX_ID": "c" * 64},
    ],
)
def test_runner_handoff_rejects_incomplete_or_malformed_identity(
    environment: dict[str, str],
) -> None:
    with pytest.raises(AiGovernanceDraftStateError, match="runner_handoff_invalid"):
        DraftRunnerHandoff.from_environment(environment)


def _selections(finding_ids: tuple[uuid.UUID, ...]) -> dict[uuid.UUID, uuid.UUID]:
    return {
        finding_id: uuid.uuid5(finding_id, "evidence-0") for finding_id in finding_ids
    }


def test_request_bindings_require_one_to_eight_unique_pairs() -> None:
    from app.domain.ai_governance_drafts import _validated_bindings

    valid = [DraftFindingBinding(uuid.uuid4(), uuid.uuid4()) for _ in range(8)]
    assert len(_validated_bindings(bindings=valid)) == 8

    duplicate_binding = DraftFindingBinding(uuid.uuid4(), uuid.uuid4())
    repeated_evidence = uuid.uuid4()
    invalid_bindings: tuple[list[DraftFindingBinding], ...] = (
        [],
        [DraftFindingBinding(uuid.uuid4(), uuid.uuid4()) for _ in range(9)],
        [duplicate_binding, duplicate_binding],
        [
            DraftFindingBinding(uuid.uuid4(), repeated_evidence),
            DraftFindingBinding(uuid.uuid4(), repeated_evidence),
        ],
    )
    for bindings in invalid_bindings:
        with pytest.raises(AiGovernanceDraftStateError, match="invalid_bindings"):
            _validated_bindings(bindings=bindings)


def test_model_output_validation_rejects_bound_input_violations() -> None:
    from app.domain.ai_governance_drafts import _validate_model_output

    finding_a = uuid.uuid4()
    finding_b = uuid.uuid4()
    selections = _selections((finding_a, finding_b))
    evidence_a = selections[finding_a]
    report_sha256 = "d" * 64

    valid = _model_output(
        report_sha256=report_sha256,
        finding_ids=(str(finding_a), str(finding_b)),
        evidence_by_finding={
            str(finding_a): (str(evidence_a),),
            str(finding_b): (str(selections[finding_b]),),
        },
    )
    _validate_model_output(
        model_output=valid, report_sha256=report_sha256, selections=selections
    )

    def assert_invalid(output: AiDraftModelOutput, code: str) -> None:
        with pytest.raises(AiGovernanceDraftStateError, match=code):
            _validate_model_output(
                model_output=output,
                report_sha256=report_sha256,
                selections=selections,
            )

    mutated = valid.model_copy(deep=True)
    mutated.recommendations[0].limitations.append("x" * 2001)
    assert_invalid(mutated, "model_output_invalid")
    structurally_mutated = valid.model_copy(deep=True)
    structurally_mutated.__dict__["recommendations"] = [object()]
    assert_invalid(structurally_mutated, "model_output_invalid")

    report_mismatch = valid.model_copy(deep=True)
    report_mismatch.report_sha256 = "e" * 64
    assert_invalid(report_mismatch, "report_mismatch")

    unknown_finding = valid.model_copy(deep=True)
    unknown_finding.recommendations[1].finding_id = str(uuid.uuid4())
    assert_invalid(unknown_finding, "finding_unknown")

    duplicate_finding = valid.model_copy(deep=True)
    duplicate_finding.recommendations[1].finding_id = str(finding_a)
    assert_invalid(duplicate_finding, "finding_unknown")

    partial = valid.model_copy(deep=True)
    partial.recommendations.pop()
    assert_invalid(partial, "finding_missing")

    out_of_bounds = valid.model_copy(deep=True)
    out_of_bounds.recommendations[1].claims[0].evidence_ids = [str(evidence_a)]
    assert_invalid(out_of_bounds, "evidence_out_of_bounds")

    duplicate_evidence = valid.model_copy(deep=True)
    duplicate_evidence.recommendations[0].claims[0].evidence_ids.append(str(evidence_a))
    assert_invalid(duplicate_evidence, "evidence_duplicate")

    missing_evidence = valid.model_copy(deep=True)
    missing_evidence.recommendations[0].claims[0].evidence_ids.clear()
    assert_invalid(missing_evidence, "evidence_missing")

    duplicate_claim = valid.model_copy(deep=True)
    duplicate_claim.recommendations[0].claims.append(
        duplicate_claim.recommendations[0].claims[0]
    )
    assert_invalid(duplicate_claim, "claim_duplicate")


def _valid_model_payload() -> dict[str, Any]:
    finding_id = str(uuid.uuid4())
    evidence_id = str(uuid.uuid4())
    return _model_output(
        report_sha256="f" * 64,
        finding_ids=(finding_id,),
        evidence_by_finding={finding_id: (evidence_id,)},
    ).model_dump()


@pytest.mark.parametrize(
    ("mutate", "error_fragments"),
    (
        (
            lambda payload: (
                payload.update(secret="model-secret"),
                payload["recommendations"][0]["claims"][0].update(
                    provider_event={"raw": "sensitive"}
                ),
            ),
            ("provider_event", "secret"),
        ),
        (lambda payload: payload.update(recommendations=[]), ()),
        (lambda payload: payload.update(summary="   "), ()),
        (lambda payload: payload.update(summary="x" * 4001), ()),
    ),
)
def test_model_output_schema_rejects_unbounded_or_sensitive_material(
    mutate: Any, error_fragments: tuple[str, ...]
) -> None:
    payload = _valid_model_payload()
    mutate(payload)
    with pytest.raises(ValueError) as error:
        AiDraftModelOutput.model_validate(payload)
    assert all(fragment in str(error.value) for fragment in error_fragments)


def test_edited_output_structure_is_validated() -> None:
    from app.domain.ai_governance_drafts import _validate_edited_output

    finding = uuid.uuid4()
    selections = {finding: uuid.uuid4()}
    valid = _edited_output(finding)
    _validate_edited_output(edited_output=valid, selections=selections)

    mutated = valid.model_copy(deep=True)
    mutated.findings[0].limitations.append("x" * 2001)
    with pytest.raises(AiGovernanceDraftStateError, match="edited_output_invalid"):
        _validate_edited_output(edited_output=mutated, selections=selections)
    structurally_mutated = valid.model_copy(deep=True)
    structurally_mutated.__dict__["findings"] = [object()]
    with pytest.raises(AiGovernanceDraftStateError, match="edited_output_invalid"):
        _validate_edited_output(
            edited_output=structurally_mutated, selections=selections
        )

    unknown = _edited_output(uuid.uuid4())
    with pytest.raises(AiGovernanceDraftStateError, match="finding_unknown"):
        _validate_edited_output(edited_output=unknown, selections=selections)


def test_edited_output_rejects_finding_fact_edits() -> None:
    payload = _edited_output(uuid.uuid4()).model_dump()
    payload["findings"][0]["fact_claims"] = "factual correction smuggled into an edit"
    with pytest.raises(ValueError):
        AiDraftEditedOutput.model_validate(payload)
