"""Seal normalized shards once so refilters can prune columns without full hashing."""
from alembic import op

revision = "nf3040000003"
down_revision = "nf3040000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE netflow_bulk_shards ADD COLUMN sealed_inode BIGINT, ADD COLUMN sealed_mtime_ns BIGINT, ADD COLUMN sealed_ctime_ns BIGINT;
ALTER TABLE netflow_bulk_shards ADD CONSTRAINT ck_bulk_shard_seal CHECK ((sealed_inode IS NULL AND sealed_mtime_ns IS NULL AND sealed_ctime_ns IS NULL) OR (sealed_inode IS NOT NULL AND sealed_mtime_ns IS NOT NULL AND sealed_ctime_ns IS NOT NULL));
CREATE OR REPLACE FUNCTION guard_bulk_checkpoint() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' OR OLD.sealed_inode IS NOT NULL OR NEW.sealed_inode IS NULL OR
    (to_jsonb(NEW)-'sealed_inode'-'sealed_mtime_ns'-'sealed_ctime_ns') IS DISTINCT FROM (to_jsonb(OLD)-'sealed_inode'-'sealed_mtime_ns'-'sealed_ctime_ns') THEN
      RAISE EXCEPTION 'committed bulk shard is immutable except its first seal';
  END IF;
  RETURN NEW;
END $$;
    """)


def downgrade() -> None:
    raise RuntimeError("Keep sealed normalization evidence; disable admission for rollback")
