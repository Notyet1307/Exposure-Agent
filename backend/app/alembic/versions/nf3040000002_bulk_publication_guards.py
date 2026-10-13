"""Protect bulk identity, completed checkpoints and published query projections."""
from alembic import op

revision = "nf3040000002"
down_revision = "nf3040000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE netflow_analyses ADD CONSTRAINT uq_nf_analysis_dataset_scope UNIQUE (id,dataset_id,project_id,tenant_id);
ALTER TABLE netflow_bulk_jobs ADD CONSTRAINT fk_bulk_analysis_dataset_scope FOREIGN KEY (analysis_id,dataset_id,project_id,tenant_id) REFERENCES netflow_analyses (id,dataset_id,project_id,tenant_id) ON DELETE RESTRICT;
CREATE FUNCTION guard_bulk_projection() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target uuid;
BEGIN
  target := CASE WHEN TG_OP = 'DELETE' THEN OLD.analysis_id ELSE NEW.analysis_id END;
  IF EXISTS (SELECT 1 FROM netflow_analyses WHERE id=target AND status IN ('SUCCEEDED','SUCCEEDED_WITH_WARNINGS')) THEN
    RAISE EXCEPTION 'published bulk projection is immutable';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bulk_object_immutable BEFORE INSERT OR UPDATE OR DELETE ON netflow_bulk_objects FOR EACH ROW EXECUTE FUNCTION guard_bulk_projection();
CREATE TRIGGER bulk_address_immutable BEFORE INSERT OR UPDATE OR DELETE ON netflow_bulk_addresses FOR EACH ROW EXECUTE FUNCTION guard_bulk_projection();
CREATE FUNCTION guard_bulk_checkpoint() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'committed bulk shard is immutable'; END $$;
CREATE TRIGGER bulk_shard_immutable BEFORE UPDATE OR DELETE ON netflow_bulk_shards FOR EACH ROW EXECUTE FUNCTION guard_bulk_checkpoint();
CREATE FUNCTION guard_bulk_dataset() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' OR (to_jsonb(NEW)-'complete'-'invalidated') IS DISTINCT FROM (to_jsonb(OLD)-'complete'-'invalidated') OR (OLD.complete AND NOT NEW.complete) OR (OLD.invalidated AND NOT NEW.invalidated) THEN
    RAISE EXCEPTION 'bulk input identity is immutable';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bulk_dataset_immutable BEFORE UPDATE OR DELETE ON netflow_bulk_datasets FOR EACH ROW EXECUTE FUNCTION guard_bulk_dataset();
CREATE FUNCTION guard_bulk_member() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' OR (OLD.complete AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD)) OR ROW(OLD.dataset_id,OLD.file_id,OLD.byte_size) IS DISTINCT FROM ROW(NEW.dataset_id,NEW.file_id,NEW.byte_size) THEN
    RAISE EXCEPTION 'completed bulk member is immutable';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bulk_member_immutable BEFORE UPDATE OR DELETE ON netflow_bulk_members FOR EACH ROW EXECUTE FUNCTION guard_bulk_member();
    """)


def downgrade() -> None:
    raise RuntimeError("Keep published bulk identities and evidence; disable admission for rollback")
