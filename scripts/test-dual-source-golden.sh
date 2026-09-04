#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
cd backend

# Permanent dual-source golden gate: the existing behavior tests are the oracle.
# This is not a fixed Run snapshot or Issue evidence. Node renames must preserve
# equivalent contract coverage and be updated here; missing nodes fail closed.
node_ids=(
  # ip-v1 facts and Runs / Assets / Findings reads
  tests/api/routes/test_governance_runs.py::test_runner_retries_transient_page_and_atomically_publishes_completed
  tests/domain/test_ip_consistency.py::test_processes_ordered_snapshots_without_collapsing_source_observations
  tests/api/routes/test_stage4_governance_results.py::test_stage4_run_publishes_ip_results_and_is_reentrant
  tests/api/routes/test_stage4_governance_results.py::test_stage4_finding_lifecycle_state_machine_is_exposed_by_public_api

  # report-v1 exact canonical JSON, HTML, and CSV bytes
  tests/domain/test_report_core.py::test_zero_finding_facts_produce_the_complete_canonical_core
  tests/domain/test_report_renderer.py::test_renderer_returns_complete_byte_stable_zero_finding_artifacts
  tests/domain/test_report_renderer.py::test_html_escapes_source_text_and_csv_is_exact_deduplicated_and_safe

  # Existing report and historical reads
  tests/api/routes/test_governance_report_reads.py::test_report_detail_is_project_scoped_bounded_and_readable_by_all_read_roles
  tests/api/routes/test_governance_report_reads.py::test_stage4_only_project_requires_a_new_stage5_rerun
  tests/api/routes/test_governance_report_downloads.py::test_report_csv_download_is_operator_admin_only_and_preserved_when_archived
  tests/migrations/test_schema_history.py::test_stage4_run_history_upgrades_without_report_backfill_or_new_steps

  # Retry, Rerun, and completed-run late mutation
  tests/api/routes/test_governance_runs.py::test_retry_resumes_the_same_session_and_reuses_successful_snapshot
  tests/api/routes/test_governance_runs.py::test_changed_input_requires_rerun_with_a_new_run_and_session
  tests/api/routes/test_governance_runs.py::test_completed_is_immutable_and_not_retryable
  tests/migrations/test_schema_history.py::test_stage4_scope_uniqueness_immutability_and_completed_run_guards
  tests/migrations/test_evidence_schema.py::test_completed_run_rejects_late_evidence_and_report_mutations
)

exec env \
  ALL_PROXY= HTTP_PROXY= HTTPS_PROXY= \
  all_proxy= http_proxy= https_proxy= \
  NO_PROXY=127.0.0.1,localhost,agent-compose \
  no_proxy=127.0.0.1,localhost,agent-compose \
  uv run pytest -q "${node_ids[@]}"
