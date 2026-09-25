"""Persist bounded publication seals without reinterpreting historical tasks.

Revision ID: 9bc23d4e5f60
Revises: 8ab12c3d4e5f
"""

from alembic import op
import sqlalchemy as sa

revision = "9bc23d4e5f60"
down_revision = "8ab12c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("external_asset_versions", sa.Column("pages_read", sa.Integer()))
    op.add_column("external_asset_versions", sa.Column("stop_reason", sa.String(32)))
    op.drop_constraint("ck_external_sync_status", "external_syncs", type_="check")
    op.create_check_constraint(
        "ck_external_sync_status",
        "external_syncs",
        "status IN ('PENDING','RUNNING','UNKNOWN','SUCCEEDED','PARTIAL_SUCCEEDED','PARTIAL_FAILED','FAILED')",
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION guard_external_version() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE policy jsonb; capacity integer; quota integer;
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
          IF NEW.status = 'PUBLISHED' THEN
            IF NEW.expected_total IS NULL OR NEW.published_at IS NULL OR NEW.fetched_at IS NULL
               OR NEW.record_count <> (SELECT count(*) FROM external_asset_records WHERE version_id = NEW.id)
               OR (NEW.complete AND NEW.expected_total <> NEW.record_count) THEN
              RAISE EXCEPTION 'external publication is incomplete';
            END IF;
            SELECT request INTO policy FROM external_syncs WHERE id = NEW.sync_id;
            IF policy ? 'publication_mode' THEN
              IF policy->>'publication_mode' IS DISTINCT FROM 'bounded-v1' THEN
                RAISE EXCEPTION 'external publication mode is invalid';
              END IF;
              capacity := LEAST((policy->>'max_pages')::integer,
                               (policy->>'max_records')::integer / (policy->>'page_size')::integer);
              quota := CASE WHEN NEW.domain = 'ip' THEN (capacity + 1) / 2 ELSE capacity / 2 END;
              IF TG_OP <> 'UPDATE' OR OLD.status NOT IN ('RUNNING', 'UNKNOWN') OR
                 (NEW.pages_read, NEW.stop_reason, NEW.record_count, NEW.expected_total, NEW.complete)
                 IS DISTINCT FROM
                 (OLD.pages_read, OLD.stop_reason, OLD.record_count, OLD.expected_total, OLD.complete) OR
                 (capacity >= 2 AND NEW.pages_read BETWEEN 1 AND quota
                  AND NEW.record_count <= NEW.pages_read * (policy->>'page_size')::integer
                  AND ((NEW.complete AND NEW.stop_reason = 'source_complete')
                       OR (NOT NEW.complete AND NEW.stop_reason = 'batch_limit'
                           AND NEW.pages_read = quota
                           AND NEW.record_count > 0 AND NEW.record_count < NEW.expected_total))) IS NOT TRUE THEN
                RAISE EXCEPTION 'external publication has no valid batch seal';
              END IF;
            ELSIF NOT NEW.complete THEN
              RAISE EXCEPTION 'external publication is incomplete';
            END IF;
          END IF;
          RETURN NEW;
        END $$;
    """)


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM external_syncs WHERE request ? 'publication_mode')"
        )
    ):
        raise RuntimeError(
            "Cannot discard bounded publication semantics while tasks exist"
        )
    op.drop_constraint("ck_external_sync_status", "external_syncs", type_="check")
    op.create_check_constraint(
        "ck_external_sync_status",
        "external_syncs",
        "status IN ('PENDING','RUNNING','UNKNOWN','SUCCEEDED','PARTIAL_FAILED','FAILED')",
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION guard_external_version() RETURNS trigger LANGUAGE plpgsql AS $$
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
    """)
    op.drop_column("external_asset_versions", "stop_reason")
    op.drop_column("external_asset_versions", "pages_read")
