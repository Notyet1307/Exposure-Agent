from sqlalchemy import text
from sqlmodel import Session


def test_netflow_schema_exposes_scoped_immutable_contract(db: Session) -> None:
    constraints = {
        row[0]
        for row in db.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid IN ('netflow_datasets'::regclass, 'projects'::regclass, "
                "'governance_runs'::regclass)"
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
