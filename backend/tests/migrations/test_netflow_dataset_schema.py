from sqlalchemy import CheckConstraint, text
from sqlmodel import Session

from app.domain.models import RunStep, SourceSnapshot


def test_netflow_schema_exposes_scoped_immutable_contract(db: Session) -> None:
    constraints = {
        row[0]
        for row in db.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid IN ('netflow_datasets'::regclass, 'projects'::regclass, "
                "'governance_runs'::regclass, 'source_snapshots'::regclass, "
                "'run_steps'::regclass)"
            )
        ).all()
    }
    assert {
        "uq_netflow_datasets_idempotency",
        "fk_netflow_datasets_raw_artifact_scope_hash",
        "fk_netflow_datasets_normalized_artifact_scope_hash",
        "ck_netflow_datasets_distinct_artifacts",
        "ck_netflow_datasets_count_sum",
        "ck_netflow_datasets_hash_format",
        "ck_netflow_datasets_contract_nonblank",
        "ck_netflow_datasets_counts_nonnegative",
        "ck_netflow_datasets_encoding",
        "fk_projects_current_netflow_dataset",
        "fk_governance_runs_netflow_dataset_scope",
        "fk_governance_runs_netflow_content_scope",
        "fk_source_snapshots_netflow_dataset_scope",
        "ck_source_snapshots_type",
        "ck_source_snapshots_source_reference",
        "ck_run_steps_code",
    } <= constraints
    assert (
        db.execute(
            text(
                "SELECT 1 FROM pg_trigger "
                "WHERE tgrelid = 'netflow_datasets'::regclass "
                "AND tgname = 'netflow_datasets_immutable'"
            )
        ).scalar_one()
        == 1
    )
    assert (
        db.execute(
            text(
                "SELECT 1 FROM pg_indexes WHERE tablename = 'projects' "
                "AND indexname = 'ix_projects_current_netflow_dataset_id'"
            )
        ).scalar_one()
        == 1
    )
    definitions = {
        row[0]: row[1]
        for row in db.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname IN ('ck_source_snapshots_type', "
                "'ck_source_snapshots_source_reference', 'ck_run_steps_code')"
            )
        ).all()
    }
    assert "NETFLOW" in definitions["ck_source_snapshots_type"]
    assert "netflow_dataset_id" in definitions["ck_source_snapshots_source_reference"]
    assert "valid_time_start_utc" in definitions["ck_source_snapshots_source_reference"]
    assert "valid_time_end_utc" in definitions["ck_source_snapshots_source_reference"]
    assert "LOAD_NETFLOW" in definitions["ck_run_steps_code"]
    model_definitions = {
        constraint.name: str(constraint.sqltext)
        for table in (RunStep.__table__, SourceSnapshot.__table__)  # type: ignore[attr-defined]
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "LOAD_NETFLOW" in model_definitions["ck_run_steps_code"]
    assert "NETFLOW" in model_definitions["ck_source_snapshots_type"]
    assert (
        "netflow_dataset_id"
        in model_definitions["ck_source_snapshots_source_reference"]
    )
