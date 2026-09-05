import hashlib
import uuid
from collections.abc import Callable

import pytest

from app.domain.governance_runs import (
    GovernanceRunExecutionError,
    PinnedTriggerInputs,
    RunnerInputs,
)


def _pinned(
    *,
    present: bool = False,
    report_contract_version: str | None = "deterministic-report-v1",
) -> PinnedTriggerInputs:
    dataset_id = uuid.UUID("55555555-5555-4555-8555-555555555555") if present else None
    return PinnedTriggerInputs(
        project_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        tenant_id=uuid.uuid4(),
        customer_upload_id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
        customer_upload_sha256="a" * 64,
        customer_upload_profile_id=uuid.UUID("33333333-3333-4333-8333-333333333333"),
        customer_upload_profile_version=1,
        source_instance_id=uuid.UUID("44444444-4444-4444-8444-444444444444"),
        cloudatlas_validated_fingerprint="b" * 64,
        cloudatlas_capset_id="cloudatlas-read",
        cloudatlas_method="cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets",
        package_sha256="c" * 64,
        descriptor_sha256="d" * 64,
        runner_build_version="runner-v1",
        processing_contract_version="ip-v1",
        report_contract_version=report_contract_version,
        input_contract_version="governance-run-input-v1",
        netflow_dataset_id=dataset_id,
        netflow_content_sha256="e" * 64 if present else None,
        netflow_dataset_contract_version="netflow-dataset-v1" if present else None,
    )

def test_absent_input_hash_matches_adr_vector() -> None:
    assert (
        _pinned(report_contract_version=None).input_hash()
        == "0dc5f48d13f4bd65e1b9592a094792c967ef854002b6f78333f30ad2a307b229"
    )


def test_present_pin_round_trips_through_runner_environment() -> None:
    pinned = _pinned(present=True, report_contract_version="deterministic-report-v1")
    environment = pinned.runner_environment(
        trigger_id="trigger",
        requested_by="operator",
        input_hash=pinned.input_hash(),
    )
    environment["SANDBOX_ID"] = hashlib.sha256(b"session").hexdigest()
    parsed = RunnerInputs.from_environment(environment)
    assert parsed.netflow_dataset_id == pinned.netflow_dataset_id
    assert parsed.netflow_content_sha256 == pinned.netflow_content_sha256
    assert parsed.netflow_dataset_contract_version == pinned.netflow_dataset_contract_version
    assert parsed.computed_input_hash() == pinned.input_hash()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda env: env.update({"GOVERNANCE_INPUT_HASH": "a" * 64}),
        lambda env: env.update({"GOVERNANCE_NETFLOW_CONTENT_SHA256": "e" * 64}),
    ],
)
def test_legacy_input_cannot_carry_v1_fields(
    mutate: Callable[[dict[str, str]], None],
) -> None:
    pinned = _pinned()
    environment = pinned.runner_environment(trigger_id="legacy", requested_by="operator")
    environment["SANDBOX_ID"] = hashlib.sha256(b"session").hexdigest()
    environment.pop("GOVERNANCE_INPUT_CONTRACT_VERSION", None)
    mutate(environment)
    with pytest.raises(GovernanceRunExecutionError, match="runner_input_invalid"):
        RunnerInputs.from_environment(environment)


def test_legacy_input_without_v1_fields_remains_valid() -> None:
    pinned = _pinned()
    environment = {
        key: value
        for key, value in pinned.runner_environment(
            trigger_id="legacy", requested_by="operator"
        ).items()
        if not key.startswith("GOVERNANCE_INPUT_")
        and not key.startswith("GOVERNANCE_NETFLOW_")
    }
    environment["SANDBOX_ID"] = hashlib.sha256(b"session").hexdigest()
    assert RunnerInputs.from_environment(environment).input_contract_version is None
