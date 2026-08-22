import json
from typing import Any

import pytest

from app.domain.model_qualification import (
    FIXTURE_VERSION,
    ModelQualificationOutput,
    evaluate_qualification,
    model_binding,
    model_config_fingerprint,
)


def _passing_output() -> dict[str, Any]:
    return {
        "recommendations": [
            {
                "finding_id": f"fixture-finding-{number}",
                "action_code": action,
                "claims": [
                    {
                        "claim_id": f"fixture-claim-{number}",
                        "evidence_ids": [f"fixture-evidence-{number}"],
                    }
                ],
                "finding_modified": False,
            }
            for number, action in enumerate(
                (
                    "CONFIRM_ASSET_OWNER",
                    "ADD_AUTHENTICATED_SCAN",
                    "VERIFY_NETWORK_ROUTE",
                    "CONFIRM_SERVICE_EXPOSURE",
                ),
                start=1,
            )
        ],
        "unsupported_claims": [],
        "unauthorized_side_effects": [],
    }


def test_fixed_fixture_passes_only_when_every_quality_gate_holds() -> None:
    result = evaluate_qualification(
        ModelQualificationOutput.model_validate(_passing_output())
    )

    assert result.status == "PASS"
    assert result.fixture_version == FIXTURE_VERSION
    assert result.availability_numerator == 4
    assert result.availability_denominator == 4
    assert result.traceable_citations == result.total_citations == 4
    assert result.hallucination_count == 0
    assert result.finding_modification_count == 0
    assert result.unauthorized_side_effect_count == 0


def test_exactly_seventy_five_percent_availability_passes() -> None:
    output = _passing_output()
    output["recommendations"][0]["action_code"] = "TEXT_EDIT_REQUIRED"

    result = evaluate_qualification(ModelQualificationOutput.model_validate(output))

    assert result.status == "PASS"
    assert result.availability_numerator == 3
    assert result.availability_denominator == 4


@pytest.mark.parametrize(
    ("mutate", "failure_code"),
    [
        (
            lambda output: [
                output["recommendations"][index].update(
                    {"action_code": "CONFIRM_ASSET_OWNER"}
                )
                for index in (1, 2)
            ],
            "availability_below_threshold",
        ),
        (
            lambda output: output["recommendations"][0]["claims"][0].update(
                {"evidence_ids": ["unknown-evidence"]}
            ),
            "citation_traceability_failed",
        ),
        (
            lambda output: output["unsupported_claims"].append("invented"),
            "hallucination_detected",
        ),
        (
            lambda output: output["recommendations"][0].update(
                {"finding_modified": True}
            ),
            "finding_modification_detected",
        ),
        (
            lambda output: output["unauthorized_side_effects"].append("network"),
            "unauthorized_side_effect_detected",
        ),
    ],
)
def test_quality_gate_failures_fail_closed(mutate: object, failure_code: str) -> None:
    output = _passing_output()
    mutate(output)  # type: ignore[operator]

    result = evaluate_qualification(ModelQualificationOutput.model_validate(output))

    assert result.status == "FAIL"
    assert result.failure_code == failure_code


def test_config_fingerprint_is_deterministic_secret_free_and_drift_sensitive() -> None:
    first = model_config_fingerprint(
        endpoint="http://model.internal/v1",
        model_identity="customer-model",
        protocol="chat_completions",
        config_revision="v1",
    )
    same = model_config_fingerprint(
        endpoint="http://model.internal/v1/",
        model_identity="customer-model",
        protocol="chat_completions",
        config_revision="v1",
    )
    drifted = model_config_fingerprint(
        endpoint="http://model.internal/v1",
        model_identity="customer-model",
        protocol="chat_completions",
        config_revision="v2",
    )

    assert first == same
    assert first != drifted
    assert len(first) == 64
    assert "secret" not in json.dumps(first)


def test_external_provider_endpoints_are_rejected_without_fallback() -> None:
    with pytest.raises(ValueError, match="external_model_provider_forbidden"):
        model_binding(
            endpoint="https://api.openai.com/v1",
            model_identity="gpt",
            protocol="responses",
            config_revision="v1",
        )
