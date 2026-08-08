"""Add Stage 4 IP governance facts and database guards.

Revision ID: d3e4f5a6b7c8
Revises: c1d2e3f4a5b6
Create Date: 2026-08-12 00:00:00.000000

"""

from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d3e4f5a6b7c8"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def _scope_fk(
    local_columns: Iterable[str],
    remote_table: str,
    remote_columns: Iterable[str],
    *,
    name: str,
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        list(local_columns),
        [f"{remote_table}.{column}" for column in remote_columns],
        name=name,
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.add_column(
        "governance_runs",
        sa.Column(
            "processing_contract_version",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_governance_runs_processing_contract_version",
        "governance_runs",
        "processing_contract_version IS NULL OR "
        "btrim(processing_contract_version) <> ''",
    )

    op.drop_constraint("ck_run_steps_code", "run_steps", type_="check")
    op.create_check_constraint(
        "ck_run_steps_code",
        "run_steps",
        "step_code IN ('LOAD_CUSTOMER', 'PULL_CLOUDATLAS', 'NORMALIZE', "
        "'RESOLVE', 'CHECK_FINDINGS', 'PUBLISH')",
    )

    # Composite uniques are the parent keys used by every scoped child FK below.
    op.create_unique_constraint(
        "uq_source_snapshots_scope",
        "source_snapshots",
        ["id", "governance_run_id", "project_id", "tenant_id"],
    )
    op.create_unique_constraint(
        "uq_source_snapshots_scope_type",
        "source_snapshots",
        ["id", "governance_run_id", "project_id", "tenant_id", "source_type"],
    )

    op.create_table(
        "resources",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("resource_type", sa.String(length=30), nullable=False),
        sa.Column("canonical_key", postgresql.INET(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("resource_type = 'IP'", name="ck_resources_type"),
        sa.CheckConstraint(
            "masklen(canonical_key) = CASE WHEN family(canonical_key) = 4 "
            "THEN 32 ELSE 128 END",
            name="ck_resources_canonical_ip_host",
        ),
        _scope_fk(
            ["project_id", "tenant_id"],
            "projects",
            ["id", "tenant_id"],
            name="fk_resources_project_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "tenant_id", name="uq_resources_scope"),
        sa.UniqueConstraint(
            "project_id",
            "resource_type",
            "canonical_key",
            name="uq_resources_project_type_key",
        ),
    )
    op.create_index("ix_resources_tenant_id", "resources", ["tenant_id"])
    op.create_index("ix_resources_project_id", "resources", ["project_id"])

    op.create_table(
        "observations",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("governance_run_id", _uuid(), nullable=False),
        sa.Column("source_snapshot_id", _uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_record_key", sa.String(length=255), nullable=False),
        sa.Column("raw_ip", sa.String(length=255), nullable=False),
        sa.Column("canonical_ip", postgresql.INET(), nullable=False),
        sa.Column("cloudatlas_asset_id", sa.String(length=255), nullable=True),
        sa.Column("cloudatlas_status", sa.String(length=30), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "source_type IN ('CUSTOMER_UPLOAD', 'CLOUDATLAS')",
            name="ck_observations_source_type",
        ),
        sa.CheckConstraint(
            "btrim(source_record_key) <> ''",
            name="ck_observations_source_record_key",
        ),
        sa.CheckConstraint("btrim(raw_ip) <> ''", name="ck_observations_raw_ip"),
        sa.CheckConstraint(
            "masklen(canonical_ip) = CASE WHEN family(canonical_ip) = 4 "
            "THEN 32 ELSE 128 END",
            name="ck_observations_canonical_ip_host",
        ),
        sa.CheckConstraint(
            "(source_type = 'CUSTOMER_UPLOAD' AND cloudatlas_asset_id IS NULL "
            "AND cloudatlas_status IS NULL) OR "
            "(source_type = 'CLOUDATLAS' AND cloudatlas_asset_id IS NOT NULL "
            "AND cloudatlas_status IS NOT NULL "
            "AND btrim(cloudatlas_asset_id) <> '' "
            "AND btrim(cloudatlas_status) <> '')",
            name="ck_observations_cloudatlas_fields",
        ),
        _scope_fk(
            ["governance_run_id", "project_id", "tenant_id"],
            "governance_runs",
            ["id", "project_id", "tenant_id"],
            name="fk_observations_governance_run_scope",
        ),
        _scope_fk(
            [
                "source_snapshot_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
                "source_type",
            ],
            "source_snapshots",
            ["id", "governance_run_id", "project_id", "tenant_id", "source_type"],
            name="fk_observations_source_snapshot_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            name="uq_observations_scope",
        ),
        sa.UniqueConstraint(
            "source_snapshot_id",
            "source_record_key",
            name="uq_observations_snapshot_record",
        ),
    )
    for column in (
        "tenant_id",
        "project_id",
        "governance_run_id",
        "source_snapshot_id",
        "canonical_ip",
    ):
        op.create_index(f"ix_observations_{column}", "observations", [column])
    op.create_index(
        "ix_observations_run_snapshot",
        "observations",
        ["governance_run_id", "source_snapshot_id"],
    )

    op.create_table(
        "observation_resource_links",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("governance_run_id", _uuid(), nullable=False),
        sa.Column("observation_id", _uuid(), nullable=False),
        sa.Column("resource_id", _uuid(), nullable=False),
        sa.Column("processing_contract_version", sa.String(length=100), nullable=False),
        *_timestamps(),
        _scope_fk(
            ["governance_run_id", "project_id", "tenant_id"],
            "governance_runs",
            ["id", "project_id", "tenant_id"],
            name="fk_observation_resource_links_run_scope",
        ),
        _scope_fk(
            ["observation_id", "governance_run_id", "project_id", "tenant_id"],
            "observations",
            ["id", "governance_run_id", "project_id", "tenant_id"],
            name="fk_observation_resource_links_observation_scope",
        ),
        _scope_fk(
            ["resource_id", "project_id", "tenant_id"],
            "resources",
            ["id", "project_id", "tenant_id"],
            name="fk_observation_resource_links_resource_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            name="uq_observation_resource_links_scope",
        ),
        sa.UniqueConstraint(
            "observation_id", name="uq_observation_resource_links_observation"
        ),
        sa.CheckConstraint(
            "btrim(processing_contract_version) <> ''",
            name="ck_observation_resource_links_processing_contract_version",
        ),
    )
    for column in (
        "tenant_id",
        "project_id",
        "governance_run_id",
        "observation_id",
        "resource_id",
    ):
        op.create_index(
            f"ix_observation_resource_links_{column}",
            "observation_resource_links",
            [column],
        )

    op.create_table(
        "findings",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("resource_id", _uuid(), nullable=False),
        sa.Column("finding_type", sa.String(length=50), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "finding_type IN ('UNREPORTED_ASSET', 'UNOBSERVED_ASSET')",
            name="ck_findings_type",
        ),
        sa.CheckConstraint("status IN ('OPEN', 'CLOSED')", name="ck_findings_status"),
        sa.CheckConstraint("btrim(dedupe_key) <> ''", name="ck_findings_dedupe_key"),
        _scope_fk(
            ["project_id", "tenant_id"],
            "projects",
            ["id", "tenant_id"],
            name="fk_findings_project_scope",
        ),
        _scope_fk(
            ["resource_id", "project_id", "tenant_id"],
            "resources",
            ["id", "project_id", "tenant_id"],
            name="fk_findings_resource_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "tenant_id", name="uq_findings_scope"),
        sa.UniqueConstraint(
            "project_id", "dedupe_key", name="uq_findings_project_dedupe"
        ),
        sa.UniqueConstraint(
            "project_id",
            "finding_type",
            "resource_id",
            name="uq_findings_project_type_resource",
        ),
    )
    for column in ("tenant_id", "project_id", "resource_id", "finding_type", "status"):
        op.create_index(f"ix_findings_{column}", "findings", [column])

    op.create_table(
        "finding_occurrences",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("finding_id", _uuid(), nullable=False),
        sa.Column("governance_run_id", _uuid(), nullable=False),
        *_timestamps(),
        _scope_fk(
            ["finding_id", "project_id", "tenant_id"],
            "findings",
            ["id", "project_id", "tenant_id"],
            name="fk_finding_occurrences_finding_scope",
        ),
        _scope_fk(
            ["governance_run_id", "project_id", "tenant_id"],
            "governance_runs",
            ["id", "project_id", "tenant_id"],
            name="fk_finding_occurrences_run_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            name="uq_finding_occurrences_scope",
        ),
        sa.UniqueConstraint(
            "finding_id",
            "governance_run_id",
            name="uq_finding_occurrences_finding_run",
        ),
    )
    for column in ("tenant_id", "project_id", "finding_id", "governance_run_id"):
        op.create_index(
            f"ix_finding_occurrences_{column}", "finding_occurrences", [column]
        )

    op.create_table(
        "finding_transitions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("finding_id", _uuid(), nullable=False),
        sa.Column("governance_run_id", _uuid(), nullable=False),
        sa.Column("transition_type", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "transition_type IN ('OPENED', 'CLOSED', 'REOPENED')",
            name="ck_finding_transitions_type",
        ),
        _scope_fk(
            ["finding_id", "project_id", "tenant_id"],
            "findings",
            ["id", "project_id", "tenant_id"],
            name="fk_finding_transitions_finding_scope",
        ),
        _scope_fk(
            ["governance_run_id", "project_id", "tenant_id"],
            "governance_runs",
            ["id", "project_id", "tenant_id"],
            name="fk_finding_transitions_run_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "governance_run_id",
            "project_id",
            "tenant_id",
            name="uq_finding_transitions_scope",
        ),
        sa.UniqueConstraint(
            "finding_id",
            "governance_run_id",
            name="uq_finding_transitions_finding_run",
        ),
    )
    for column in ("tenant_id", "project_id", "finding_id", "governance_run_id"):
        op.create_index(
            f"ix_finding_transitions_{column}", "finding_transitions", [column]
        )

    _create_occurrence_reference_tables()
    _create_transition_reference_tables()
    _create_stage4_triggers()


def _create_occurrence_reference_tables() -> None:
    op.create_table(
        "finding_occurrence_observations",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("governance_run_id", _uuid(), nullable=False),
        sa.Column("finding_occurrence_id", _uuid(), nullable=False),
        sa.Column("observation_id", _uuid(), nullable=False),
        *_timestamps(),
        _scope_fk(
            [
                "finding_occurrence_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
            ],
            "finding_occurrences",
            ["id", "governance_run_id", "project_id", "tenant_id"],
            name="fk_finding_occurrence_observations_occurrence_scope",
        ),
        _scope_fk(
            ["observation_id", "governance_run_id", "project_id", "tenant_id"],
            "observations",
            ["id", "governance_run_id", "project_id", "tenant_id"],
            name="fk_finding_occurrence_observations_observation_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "finding_occurrence_id",
            "observation_id",
            name="uq_finding_occurrence_observations_pair",
        ),
    )
    for column in (
        "tenant_id",
        "project_id",
        "governance_run_id",
        "finding_occurrence_id",
        "observation_id",
    ):
        op.create_index(
            f"ix_finding_occurrence_observations_{column}",
            "finding_occurrence_observations",
            [column],
        )

    op.create_table(
        "finding_occurrence_snapshots",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("governance_run_id", _uuid(), nullable=False),
        sa.Column("finding_occurrence_id", _uuid(), nullable=False),
        sa.Column("source_snapshot_id", _uuid(), nullable=False),
        *_timestamps(),
        _scope_fk(
            [
                "finding_occurrence_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
            ],
            "finding_occurrences",
            ["id", "governance_run_id", "project_id", "tenant_id"],
            name="fk_finding_occurrence_snapshots_occurrence_scope",
        ),
        _scope_fk(
            ["source_snapshot_id", "governance_run_id", "project_id", "tenant_id"],
            "source_snapshots",
            ["id", "governance_run_id", "project_id", "tenant_id"],
            name="fk_finding_occurrence_snapshots_snapshot_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "finding_occurrence_id",
            "source_snapshot_id",
            name="uq_finding_occurrence_snapshots_pair",
        ),
    )
    for column in (
        "tenant_id",
        "project_id",
        "governance_run_id",
        "finding_occurrence_id",
        "source_snapshot_id",
    ):
        op.create_index(
            f"ix_finding_occurrence_snapshots_{column}",
            "finding_occurrence_snapshots",
            [column],
        )


def _create_transition_reference_tables() -> None:
    op.create_table(
        "finding_transition_observations",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("governance_run_id", _uuid(), nullable=False),
        sa.Column("finding_transition_id", _uuid(), nullable=False),
        sa.Column("observation_id", _uuid(), nullable=False),
        *_timestamps(),
        _scope_fk(
            [
                "finding_transition_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
            ],
            "finding_transitions",
            ["id", "governance_run_id", "project_id", "tenant_id"],
            name="fk_finding_transition_observations_transition_scope",
        ),
        _scope_fk(
            ["observation_id", "governance_run_id", "project_id", "tenant_id"],
            "observations",
            ["id", "governance_run_id", "project_id", "tenant_id"],
            name="fk_finding_transition_observations_observation_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "finding_transition_id",
            "observation_id",
            name="uq_finding_transition_observations_pair",
        ),
    )
    for column in (
        "tenant_id",
        "project_id",
        "governance_run_id",
        "finding_transition_id",
        "observation_id",
    ):
        op.create_index(
            f"ix_finding_transition_observations_{column}",
            "finding_transition_observations",
            [column],
        )

    op.create_table(
        "finding_transition_snapshots",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("governance_run_id", _uuid(), nullable=False),
        sa.Column("finding_transition_id", _uuid(), nullable=False),
        sa.Column("source_snapshot_id", _uuid(), nullable=False),
        *_timestamps(),
        _scope_fk(
            [
                "finding_transition_id",
                "governance_run_id",
                "project_id",
                "tenant_id",
            ],
            "finding_transitions",
            ["id", "governance_run_id", "project_id", "tenant_id"],
            name="fk_finding_transition_snapshots_transition_scope",
        ),
        _scope_fk(
            ["source_snapshot_id", "governance_run_id", "project_id", "tenant_id"],
            "source_snapshots",
            ["id", "governance_run_id", "project_id", "tenant_id"],
            name="fk_finding_transition_snapshots_snapshot_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "finding_transition_id",
            "source_snapshot_id",
            name="uq_finding_transition_snapshots_pair",
        ),
    )
    for column in (
        "tenant_id",
        "project_id",
        "governance_run_id",
        "finding_transition_id",
        "source_snapshot_id",
    ):
        op.create_index(
            f"ix_finding_transition_snapshots_{column}",
            "finding_transition_snapshots",
            [column],
        )


def _create_stage4_triggers() -> None:
    # Preserve the Stage 3 trigger's behavior while pinning the new version too.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_governance_run_facts()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status = 'COMPLETED' THEN
                RAISE EXCEPTION 'completed governance_runs are immutable';
            END IF;
            IF ROW(
                NEW.tenant_id, NEW.project_id, NEW.trigger_id, NEW.session_id,
                NEW.requested_by, NEW.customer_upload_id,
                NEW.customer_upload_sha256, NEW.customer_upload_profile_id,
                NEW.customer_upload_profile_version, NEW.source_instance_id,
                NEW.cloudatlas_validated_fingerprint, NEW.cloudatlas_capset_id,
                NEW.cloudatlas_method, NEW.package_sha256,
                NEW.descriptor_sha256, NEW.runner_build_version,
                NEW.processing_contract_version, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.tenant_id, OLD.project_id, OLD.trigger_id, OLD.session_id,
                OLD.requested_by, OLD.customer_upload_id,
                OLD.customer_upload_sha256, OLD.customer_upload_profile_id,
                OLD.customer_upload_profile_version, OLD.source_instance_id,
                OLD.cloudatlas_validated_fingerprint, OLD.cloudatlas_capset_id,
                OLD.cloudatlas_method, OLD.package_sha256,
                OLD.descriptor_sha256, OLD.runner_build_version,
                OLD.processing_contract_version, OLD.created_at
            ) THEN
                RAISE EXCEPTION 'governance_run pinned facts are immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION reject_completed_run_child_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            run_status text;
        BEGIN
            SELECT status INTO run_status
            FROM governance_runs
            WHERE id = NEW.governance_run_id;
            IF run_status LIKE 'COMPLETED%' THEN
                RAISE EXCEPTION
                    'completed governance_runs cannot receive % records', TG_TABLE_NAME;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table_name in (
        "source_snapshots",
        "observations",
        "observation_resource_links",
        "finding_occurrences",
        "finding_transitions",
        "finding_occurrence_observations",
        "finding_occurrence_snapshots",
        "finding_transition_observations",
        "finding_transition_snapshots",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_reject_completed_insert
            BEFORE INSERT ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_completed_run_child_insert()
            """
        )

    op.execute(
        """
        CREATE FUNCTION require_stage4_processing_contract()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            run_version varchar(100);
        BEGIN
            SELECT processing_contract_version INTO run_version
            FROM governance_runs
            WHERE id = NEW.governance_run_id;
            IF run_version IS NULL THEN
                RAISE EXCEPTION
                    'Stage 4 facts require a processing_contract_version';
            END IF;
            IF TG_TABLE_NAME = 'observation_resource_links'
               AND (to_jsonb(NEW)->>'processing_contract_version') <> run_version THEN
                RAISE EXCEPTION
                    'processing_contract_version does not match governance_run';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table_name in (
        "observations",
        "observation_resource_links",
        "finding_occurrences",
        "finding_transitions",
        "finding_occurrence_observations",
        "finding_occurrence_snapshots",
        "finding_transition_observations",
        "finding_transition_snapshots",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_require_processing_contract
            BEFORE INSERT ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION require_stage4_processing_contract()
            """
        )

    op.execute(
        """
        CREATE FUNCTION reject_stage4_fact_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION '% records are immutable', TG_TABLE_NAME;
        END;
        $$
        """
    )
    for table_name in (
        "resources",
        "observations",
        "observation_resource_links",
        "finding_occurrences",
        "finding_transitions",
        "finding_occurrence_observations",
        "finding_occurrence_snapshots",
        "finding_transition_observations",
        "finding_transition_snapshots",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_stage4_fact_mutation()
            """
        )

    op.execute(
        """
        CREATE FUNCTION protect_finding_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'findings are immutable';
            END IF;
            IF ROW(
                NEW.tenant_id, NEW.project_id, NEW.resource_id,
                NEW.finding_type, NEW.dedupe_key, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.tenant_id, OLD.project_id, OLD.resource_id,
                OLD.finding_type, OLD.dedupe_key, OLD.created_at
            ) THEN
                RAISE EXCEPTION 'finding identity is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER findings_protect_identity
        BEFORE UPDATE OR DELETE ON findings
        FOR EACH ROW EXECUTE FUNCTION protect_finding_identity()
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_finding_source_snapshot_refs()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            occurrence_id uuid;
            transition_id uuid;
            snapshot_count integer;
            customer_snapshot_count integer;
            cloudatlas_snapshot_count integer;
        BEGIN
            IF TG_TABLE_NAME = 'finding_occurrences' THEN
                occurrence_id := NEW.id;
                transition_id := NULL;
            ELSIF TG_TABLE_NAME = 'finding_occurrence_snapshots' THEN
                occurrence_id := NEW.finding_occurrence_id;
                transition_id := NULL;
            ELSIF TG_TABLE_NAME = 'finding_transitions' THEN
                occurrence_id := NULL;
                transition_id := NEW.id;
            ELSE
                occurrence_id := NULL;
                transition_id := NEW.finding_transition_id;
            END IF;

            IF occurrence_id IS NOT NULL THEN
                SELECT count(*),
                       count(*) FILTER (WHERE ss.source_type = 'CUSTOMER_UPLOAD'),
                       count(*) FILTER (WHERE ss.source_type = 'CLOUDATLAS')
                INTO snapshot_count, customer_snapshot_count, cloudatlas_snapshot_count
                FROM finding_occurrence_snapshots fos
                JOIN source_snapshots ss ON ss.id = fos.source_snapshot_id
                WHERE fos.finding_occurrence_id = occurrence_id;
            ELSE
                SELECT count(*),
                       count(*) FILTER (WHERE ss.source_type = 'CUSTOMER_UPLOAD'),
                       count(*) FILTER (WHERE ss.source_type = 'CLOUDATLAS')
                INTO snapshot_count, customer_snapshot_count, cloudatlas_snapshot_count
                FROM finding_transition_snapshots fts
                JOIN source_snapshots ss ON ss.id = fts.source_snapshot_id
                WHERE fts.finding_transition_id = transition_id;
            END IF;

            IF snapshot_count <> 2
               OR customer_snapshot_count <> 1
               OR cloudatlas_snapshot_count <> 1 THEN
                IF occurrence_id IS NOT NULL THEN
                    RAISE EXCEPTION
                        'FindingOccurrence must reference exactly one customer and one CloudAtlas snapshot';
                ELSE
                    RAISE EXCEPTION
                        'FindingTransition must reference exactly one customer and one CloudAtlas snapshot';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table_name in (
        "finding_occurrences",
        "finding_occurrence_snapshots",
        "finding_transitions",
        "finding_transition_snapshots",
    ):
        op.execute(
            f"""
            CREATE CONSTRAINT TRIGGER {table_name}_require_two_snapshots
            AFTER INSERT OR UPDATE ON {table_name}
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION enforce_finding_source_snapshot_refs()
            """
        )


def _drop_stage4_triggers() -> None:
    for table_name in (
        "source_snapshots",
        "observations",
        "observation_resource_links",
        "finding_occurrences",
        "finding_transitions",
        "finding_occurrence_observations",
        "finding_occurrence_snapshots",
        "finding_transition_observations",
        "finding_transition_snapshots",
    ):
        op.execute(f"DROP TRIGGER {table_name}_reject_completed_insert ON {table_name}")
        if table_name != "source_snapshots":
            op.execute(
                f"DROP TRIGGER {table_name}_require_processing_contract ON {table_name}"
            )
            op.execute(f"DROP TRIGGER {table_name}_immutable ON {table_name}")
    for table_name in (
        "finding_occurrences",
        "finding_occurrence_snapshots",
        "finding_transitions",
        "finding_transition_snapshots",
    ):
        op.execute(f"DROP TRIGGER {table_name}_require_two_snapshots ON {table_name}")
    op.execute("DROP TRIGGER resources_immutable ON resources")
    op.execute("DROP TRIGGER findings_protect_identity ON findings")
    op.execute("DROP FUNCTION enforce_finding_source_snapshot_refs()")
    op.execute("DROP FUNCTION protect_finding_identity()")
    op.execute("DROP FUNCTION reject_stage4_fact_mutation()")
    op.execute("DROP FUNCTION require_stage4_processing_contract()")
    op.execute("DROP FUNCTION reject_completed_run_child_insert()")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_governance_run_facts()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status = 'COMPLETED' THEN
                RAISE EXCEPTION 'completed governance_runs are immutable';
            END IF;
            IF ROW(
                NEW.tenant_id, NEW.project_id, NEW.trigger_id, NEW.session_id,
                NEW.requested_by, NEW.customer_upload_id,
                NEW.customer_upload_sha256, NEW.customer_upload_profile_id,
                NEW.customer_upload_profile_version, NEW.source_instance_id,
                NEW.cloudatlas_validated_fingerprint, NEW.cloudatlas_capset_id,
                NEW.cloudatlas_method, NEW.package_sha256,
                NEW.descriptor_sha256, NEW.runner_build_version, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.tenant_id, OLD.project_id, OLD.trigger_id, OLD.session_id,
                OLD.requested_by, OLD.customer_upload_id,
                OLD.customer_upload_sha256, OLD.customer_upload_profile_id,
                OLD.customer_upload_profile_version, OLD.source_instance_id,
                OLD.cloudatlas_validated_fingerprint, OLD.cloudatlas_capset_id,
                OLD.cloudatlas_method, OLD.package_sha256,
                OLD.descriptor_sha256, OLD.runner_build_version, OLD.created_at
            ) THEN
                RAISE EXCEPTION 'governance_run pinned facts are immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )


def downgrade() -> None:
    _drop_stage4_triggers()

    for table_name in (
        "finding_transition_snapshots",
        "finding_transition_observations",
        "finding_occurrence_snapshots",
        "finding_occurrence_observations",
        "finding_transitions",
        "finding_occurrences",
        "findings",
        "observation_resource_links",
        "observations",
        "resources",
    ):
        op.drop_table(table_name)

    op.drop_constraint(
        "uq_source_snapshots_scope_type", "source_snapshots", type_="unique"
    )
    op.drop_constraint("uq_source_snapshots_scope", "source_snapshots", type_="unique")
    op.drop_constraint("ck_run_steps_code", "run_steps", type_="check")
    op.create_check_constraint(
        "ck_run_steps_code",
        "run_steps",
        "step_code IN ('LOAD_CUSTOMER', 'PULL_CLOUDATLAS', 'PUBLISH')",
    )
    op.drop_constraint(
        "ck_governance_runs_processing_contract_version",
        "governance_runs",
        type_="check",
    )
    op.drop_column("governance_runs", "processing_contract_version")
