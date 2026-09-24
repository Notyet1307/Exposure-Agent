"""Independent CloudAtlas asset read model; preserve all legacy source constraints.

Revision ID: 8ab12c3d4e5f
Revises: 7fa01c2d3e4f
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "8ab12c3d4e5f"
down_revision = "7fa01c2d3e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_instances",
        sa.Column(
            "capability_profile",
            sa.String(30),
            nullable=False,
            server_default="legacy-ip-v1",
        ),
    )
    op.add_column("source_instances", sa.Column("space_id", sa.String(255)))
    op.add_column(
        "source_instances",
        sa.Column(
            "data_access_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column("source_instances", sa.Column("assets_token_sha256", sa.String(64)))
    op.create_check_constraint(
        "ck_source_instances_profile",
        "source_instances",
        "capability_profile IN ('legacy-ip-v1', 'assets-v1') AND (capability_profile != 'assets-v1' OR space_id IS NOT NULL)",
    )
    op.create_table(
        "external_syncs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("user.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("request", postgresql.JSONB(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("token_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("agent_run_id", sa.String(64), nullable=False, unique=True),
        sa.Column("agent_project_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("pages_read", sa.Integer(), nullable=False),
        sa.Column("records_read", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id", "project_id"],
            ["source_instances.id", "source_instances.project_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "actor_id",
            "project_id",
            "source_id",
            "idempotency_key",
            name="uq_external_sync_intent",
        ),
        sa.UniqueConstraint("id", "source_id", name="uq_external_sync_source"),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','UNKNOWN','SUCCEEDED','PARTIAL_FAILED','FAILED')",
            name="ck_external_sync_status",
        ),
    )
    op.create_index("ix_external_syncs_source_id", "external_syncs", ["source_id"])
    op.create_index(
        "uq_external_sync_unfinished",
        "external_syncs",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING','RUNNING','UNKNOWN')"),
    )
    op.create_table(
        "external_asset_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sync_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("domain", sa.String(10), nullable=False),
        sa.Column("space_id", sa.String(255), nullable=False),
        sa.Column("instance_id", sa.String(255), nullable=False),
        sa.Column("capset_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("expected_total", sa.Integer()),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("filter", postgresql.JSONB(), nullable=False),
        sa.Column("sort", sa.String(10), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.ForeignKeyConstraint(
            ["sync_id", "source_id"],
            ["external_syncs.id", "external_syncs.source_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("sync_id", "domain", name="uq_external_version_domain"),
        sa.UniqueConstraint(
            "id", "source_id", "domain", name="uq_external_version_scope"
        ),
        sa.CheckConstraint(
            "domain IN ('ip','port')", name="ck_external_version_domain"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','PUBLISHED','FAILED','UNKNOWN')",
            name="ck_external_version_status",
        ),
    )
    op.create_index(
        "ix_external_asset_versions_source_id", "external_asset_versions", ["source_id"]
    )
    op.create_table(
        "external_asset_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("external_asset_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("ip", sa.String(45), nullable=False),
        sa.Column("canonical_ip", sa.String(45), nullable=False),
        sa.Column("fields", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "version_id", "source_id", name="uq_external_record_identity"
        ),
    )
    op.create_index(
        "ix_external_asset_records_version_id", "external_asset_records", ["version_id"]
    )
    op.create_index(
        "ix_external_asset_records_canonical_ip",
        "external_asset_records",
        ["canonical_ip"],
    )
    op.create_table(
        "external_asset_heads",
        sa.Column("source_id", sa.Uuid(), primary_key=True),
        sa.Column("domain", sa.String(10), primary_key=True),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id", "source_id", "domain"],
            [
                "external_asset_versions.id",
                "external_asset_versions.source_id",
                "external_asset_versions.domain",
            ],
            ondelete="RESTRICT",
        ),
    )
    op.execute("""
        CREATE FUNCTION guard_external_source_binding() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF (NEW.instance_id, NEW.capset_id, NEW.space_id, NEW.capability_profile, NEW.project_id, NEW.tenant_id)
             IS DISTINCT FROM (OLD.instance_id, OLD.capset_id, OLD.space_id, OLD.capability_profile, OLD.project_id, OLD.tenant_id)
             AND EXISTS (SELECT 1 FROM external_asset_versions WHERE source_id = OLD.id) THEN
            RAISE EXCEPTION 'external source binding is immutable';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER guard_external_source_binding BEFORE UPDATE ON source_instances
          FOR EACH ROW EXECUTE FUNCTION guard_external_source_binding();
        CREATE FUNCTION guard_external_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND OLD.status = 'PUBLISHED') THEN
            RAISE EXCEPTION 'external version is immutable';
          END IF;
          IF TG_OP = 'UPDATE' AND
             (NEW.source_id, NEW.sync_id, NEW.domain, NEW.space_id, NEW.instance_id, NEW.capset_id,
              NEW.filter, NEW.sort, NEW.fingerprint, NEW.retain_until)
             IS DISTINCT FROM
             (OLD.source_id, OLD.sync_id, OLD.domain, OLD.space_id, OLD.instance_id, OLD.capset_id,
              OLD.filter, OLD.sort, OLD.fingerprint, OLD.retain_until) THEN
            RAISE EXCEPTION 'external version scope is immutable';
          END IF;
          IF NEW.status = 'PUBLISHED' AND (NOT NEW.complete OR NEW.expected_total IS DISTINCT FROM NEW.record_count
             OR NEW.published_at IS NULL OR NEW.fetched_at IS NULL
             OR NEW.record_count <> (SELECT count(*) FROM external_asset_records WHERE version_id = NEW.id)) THEN
            RAISE EXCEPTION 'external publication is incomplete';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER guard_external_version BEFORE INSERT OR UPDATE OR DELETE ON external_asset_versions
          FOR EACH ROW EXECUTE FUNCTION guard_external_version();
        CREATE FUNCTION guard_external_record() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE version_status text; expiry timestamptz;
        BEGIN
          IF TG_OP = 'UPDATE' THEN RAISE EXCEPTION 'external record is immutable'; END IF;
          IF TG_OP = 'DELETE' THEN
            SELECT retain_until INTO expiry FROM external_asset_versions WHERE id = OLD.version_id FOR SHARE;
            IF expiry > CURRENT_TIMESTAMP THEN RAISE EXCEPTION 'external record retention has not expired'; END IF;
            RETURN OLD;
          END IF;
          SELECT status INTO version_status FROM external_asset_versions WHERE id = NEW.version_id FOR SHARE;
          IF version_status IS DISTINCT FROM 'RUNNING' THEN RAISE EXCEPTION 'external version is not staging'; END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER guard_external_record BEFORE INSERT OR UPDATE OR DELETE ON external_asset_records
          FOR EACH ROW EXECUTE FUNCTION guard_external_record();
        CREATE FUNCTION guard_external_head() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM external_asset_versions
             WHERE id = NEW.version_id AND source_id = NEW.source_id AND domain = NEW.domain AND status = 'PUBLISHED') THEN
            RAISE EXCEPTION 'external head must reference published version';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER guard_external_head BEFORE INSERT OR UPDATE ON external_asset_heads
          FOR EACH ROW EXECUTE FUNCTION guard_external_head();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER guard_external_source_binding ON source_instances")
    op.drop_table("external_asset_heads")
    op.drop_table("external_asset_records")
    op.drop_table("external_asset_versions")
    op.drop_table("external_syncs")
    op.execute(
        "DROP FUNCTION guard_external_head(); DROP FUNCTION guard_external_record(); DROP FUNCTION guard_external_version(); DROP FUNCTION guard_external_source_binding();"
    )
    op.drop_constraint("ck_source_instances_profile", "source_instances", type_="check")
    for name in (
        "assets_token_sha256",
        "data_access_enabled",
        "space_id",
        "capability_profile",
    ):
        op.drop_column("source_instances", name)
