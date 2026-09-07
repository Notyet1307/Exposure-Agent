import hashlib
import json

import pytest
from sqlmodel import Session, col, delete, select, update

from app.core.db import engine
from app.domain import governance_runs as governance_run_service
from app.domain.models import (
    AuditEvent,
    GovernanceRun,
    NetFlowIPActivity,
    ObservationResourceLink,
    RunStep,
    SourceSnapshot,
)
from app.domain.report_candidate_facts import generate_run_report_candidate
from app.domain.report_candidates import ReportCandidateError
from tests.api.routes import test_ip_source_comparison as comparison_fixtures

comparison_run = comparison_fixtures.comparison_run


@pytest.mark.parametrize("damage", ["snapshot", "link", "activity", "normalization"])
def test_damaged_database_facts_never_produce_successful_candidate(
    comparison_run: GovernanceRun,
    damage: str,
) -> None:
    run = comparison_run
    with Session(engine) as session:
        session.connection().exec_driver_sql(
            "SET LOCAL session_replication_role = replica"
        )
        if damage == "snapshot":
            session.exec(
                update(SourceSnapshot)
                .where(
                    col(SourceSnapshot.governance_run_id) == run.id,
                    col(SourceSnapshot.source_type) == "CLOUDATLAS",
                )
                .values(content_sha256="0" * 64)
            )
        elif damage == "link":
            session.exec(
                delete(ObservationResourceLink).where(
                    col(ObservationResourceLink.governance_run_id) == run.id,
                )
            )
        elif damage == "activity":
            session.exec(
                update(NetFlowIPActivity)
                .where(
                    col(NetFlowIPActivity.governance_run_id) == run.id,
                )
                .values(flow_count=999)
            )
        else:
            session.exec(
                update(RunStep)
                .where(
                    col(RunStep.governance_run_id) == run.id,
                    col(RunStep.step_code) == "NORMALIZE",
                )
                .values(output_hash="0" * 64)
            )
        with pytest.raises(ReportCandidateError, match="report_facts_invalid"):
            generate_run_report_candidate(
                session=session,
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                run_id=run.id,
                report_contract_version="deterministic-report-v2",
            )
        session.rollback()


def test_published_candidate_is_never_recreated_when_both_files_are_missing(
    comparison_run: GovernanceRun,
) -> None:
    with Session(engine) as session:
        run = session.get(GovernanceRun, comparison_run.id)
        assert run is not None and run.status == "COMPLETED"
        paths = tuple(
            governance_run_service._candidate_storage_path(storage_key)
            for storage_key in governance_run_service._report_candidate_storage_keys(
                run.id
            )
        )
        for path in paths:
            path.unlink()

        with pytest.raises(
            governance_run_service.ReportCandidateStorageError,
            match="candidate_artifact_unavailable",
        ):
            governance_run_service._prepare_report_candidate(
                session=session, run=run, reuse_existing=True
            )
        assert not any(path.exists() for path in paths)
        session.rollback()


def test_historical_v1_rebuild_does_not_require_comparison_receipt(
    comparison_run: GovernanceRun,
) -> None:
    run = comparison_run
    scope = {"tenant_id": run.tenant_id, "project_id": run.project_id, "run_id": run.id}
    with Session(engine) as session:
        baseline = generate_run_report_candidate(
            session=session,
            **scope,
            report_contract_version="deterministic-report-v1",
        )
        session.connection().exec_driver_sql(
            "SET LOCAL session_replication_role = replica"
        )
        audit = session.exec(
            select(AuditEvent).where(
                col(AuditEvent.target_id) == run.id,
                col(AuditEvent.action) == "governance_run.published",
            )
        ).one()
        data = dict(audit.after_data or {})
        data.pop("netflow_activity")
        session.exec(
            update(AuditEvent)
            .where(col(AuditEvent.id) == audit.id)
            .values(after_data=data)
        )
        steps = {
            step.step_code: step
            for step in session.exec(
                select(RunStep).where(
                    col(RunStep.governance_run_id) == run.id,
                )
            ).all()
        }
        old_publish = {
            "processing_contract_version": run.processing_contract_version,
            "check_findings_output_hash": steps["CHECK_FINDINGS"].output_hash,
            "validated_report_output_hash": steps["VALIDATE_REPORT"].output_hash,
            "governance_report_id": data["governance_report_id"],
        }
        old_hash = hashlib.sha256(
            json.dumps(
                old_publish,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        session.exec(
            update(RunStep)
            .where(col(RunStep.id) == steps["PUBLISH"].id)
            .values(output_hash=old_hash)
        )
        session.expire_all()
        assert (
            generate_run_report_candidate(
                session=session,
                **scope,
                report_contract_version="deterministic-report-v1",
            )
            == baseline
        )
        with pytest.raises(
            ReportCandidateError, match="comparison_contract_unsupported"
        ):
            generate_run_report_candidate(
                session=session,
                **scope,
                report_contract_version="deterministic-report-v2",
            )
        session.rollback()
