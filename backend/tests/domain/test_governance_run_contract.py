from app.domain.models import GovernanceRun, RunStepCode


def test_stage5_report_run_contract_values_are_stable() -> None:
    assert RunStepCode.BUILD_REPORT.value == "BUILD_REPORT"
    assert RunStepCode.VALIDATE_REPORT.value == "VALIDATE_REPORT"
    assert GovernanceRun.model_fields["report_contract_version"].default is None
