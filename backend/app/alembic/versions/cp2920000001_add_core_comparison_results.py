"""Add C/A publication identities and optional, independently bounded evidence.

Revision ID: cp2920000001
Revises: cb2920000001
"""

from alembic import op
import sqlalchemy as sa

revision = "cp2920000001"
down_revision = "cb2920000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE core_comparison_results (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    scope_key VARCHAR(64) NOT NULL,
    scope_confirmation_id UUID NOT NULL,
    purpose VARCHAR(16) NOT NULL,
    rule_version VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    error_code VARCHAR(100),
    published_at TIMESTAMP WITH TIME ZONE,
    selection JSONB NOT NULL,
    pins JSONB NOT NULL,
    input_sha256 VARCHAR(64) NOT NULL,
    customer_applied_at TIMESTAMP WITH TIME ZONE,
    created_by UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(project_id, tenant_id) REFERENCES projects (id, tenant_id) ON DELETE RESTRICT,
    FOREIGN KEY(scope_confirmation_id) REFERENCES source_correlation_revisions (id) ON DELETE RESTRICT,
    CONSTRAINT uq_core_result_scope UNIQUE (id, project_id, tenant_id),
    CONSTRAINT ck_core_result_purpose CHECK (purpose IN ('regular','custom')),
    CONSTRAINT ck_core_result_publication CHECK ((status = 'PUBLISHED' AND published_at IS NOT NULL AND error_code IS NULL) OR (status = 'FAILED' AND published_at IS NULL AND error_code IS NOT NULL)),
    CONSTRAINT ck_core_result_hashes CHECK (input_sha256 ~ '^[0-9a-f]{64}$' AND scope_key ~ '^[0-9a-f]{64}$'),
    FOREIGN KEY(created_by) REFERENCES "user" (id) ON DELETE RESTRICT
);
CREATE INDEX ix_core_comparison_results_project_id ON core_comparison_results (project_id);
CREATE INDEX ix_core_result_scope_published ON core_comparison_results (project_id, scope_key, published_at, id);
CREATE TABLE core_comparison_supplements (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    result_id UUID NOT NULL,
    parent_id UUID,
    revision INTEGER NOT NULL,
    analysis_id UUID,
    qualification_confirmation_id UUID,
    qualification_evidence VARCHAR(2048),
    valid_until TIMESTAMP WITH TIME ZONE,
    observation_window JSONB NOT NULL,
    created_by UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(result_id, project_id, tenant_id) REFERENCES core_comparison_results (id, project_id, tenant_id) ON DELETE RESTRICT,
    FOREIGN KEY(analysis_id, project_id, tenant_id) REFERENCES netflow_analyses (id, project_id, tenant_id) ON DELETE RESTRICT,
    CONSTRAINT uq_core_supplement_scope UNIQUE (id, result_id, project_id, tenant_id),
    FOREIGN KEY(parent_id, result_id, project_id, tenant_id) REFERENCES core_comparison_supplements (id, result_id, project_id, tenant_id) ON DELETE RESTRICT,
    FOREIGN KEY(qualification_confirmation_id) REFERENCES source_correlation_revisions (id) ON DELETE RESTRICT,
    CONSTRAINT uq_core_supplement_revision UNIQUE (result_id, revision),
    CONSTRAINT uq_core_supplement_successor UNIQUE (parent_id),
    CONSTRAINT ck_core_supplement_revision CHECK (revision > 0 AND ((parent_id IS NULL AND revision = 1) OR (parent_id IS NOT NULL AND revision > 1))),
    CONSTRAINT ck_core_supplement_binding CHECK ((analysis_id IS NULL AND valid_until IS NULL AND qualification_confirmation_id IS NULL AND qualification_evidence IS NULL) OR (analysis_id IS NOT NULL AND valid_until > created_at AND (qualification_confirmation_id IS NOT NULL OR coalesce(length(btrim(qualification_evidence)),0) > 0))),
    FOREIGN KEY(created_by) REFERENCES "user" (id) ON DELETE RESTRICT
);
CREATE INDEX ix_core_comparison_supplements_result_id ON core_comparison_supplements (result_id);
CREATE UNIQUE INDEX uq_core_supplement_root ON core_comparison_supplements (result_id) WHERE parent_id IS NULL;
    """)
    op.execute("""
    CREATE FUNCTION guard_core_comparison_identity() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE c source_correlation_revisions%ROWTYPE;
    BEGIN
      SELECT * INTO c FROM source_correlation_revisions WHERE id = NEW.scope_confirmation_id;
      IF NOT FOUND OR c.project_id != NEW.project_id OR c.tenant_id != NEW.tenant_id
         OR c.scope_state != 'CONFIRMED' OR c.selection->'netflow' IS DISTINCT FROM 'null'::jsonb
         OR (c.selection->'customer' IS NULL OR c.selection->'customer' = 'null'::jsonb) OR c.selection->'cloud'->>'kind' IS DISTINCT FROM 'external_versions'
         OR c.selection != NEW.selection OR c.pins != NEW.pins THEN
        RAISE EXCEPTION 'core comparison input scope mismatch';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER core_comparison_identity BEFORE INSERT ON core_comparison_results
      FOR EACH ROW EXECUTE FUNCTION guard_core_comparison_identity();
    CREATE FUNCTION guard_core_supplement_identity() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE r core_comparison_results%ROWTYPE; p core_comparison_supplements%ROWTYPE;
            a netflow_analyses%ROWTYPE; q source_correlation_revisions%ROWTYPE;
    BEGIN
      SELECT * INTO r FROM core_comparison_results WHERE id = NEW.result_id;
      IF NOT FOUND OR r.status != 'PUBLISHED' THEN RAISE EXCEPTION 'supplement needs published core'; END IF;
      IF NEW.parent_id IS NOT NULL THEN
        SELECT * INTO p FROM core_comparison_supplements WHERE id = NEW.parent_id;
        IF NOT FOUND OR NEW.revision != p.revision + 1 THEN RAISE EXCEPTION 'supplement parent mismatch'; END IF;
      END IF;
      IF NEW.analysis_id IS NOT NULL THEN
        SELECT * INTO a FROM netflow_analyses WHERE id = NEW.analysis_id;
        IF NOT FOUND OR a.status NOT IN ('SUCCEEDED','SUCCEEDED_WITH_WARNINGS')
          OR a.network_namespace IS DISTINCT FROM r.selection->>'network_namespace' THEN
          RAISE EXCEPTION 'supplement analysis scope mismatch';
        END IF;
      END IF;
      IF NEW.qualification_confirmation_id IS NOT NULL THEN
        SELECT * INTO q FROM source_correlation_revisions WHERE id = NEW.qualification_confirmation_id;
        IF NOT FOUND OR q.project_id != NEW.project_id OR q.tenant_id != NEW.tenant_id
          OR q.scope_state != 'CONFIRMED' OR q.selection->'netflow'->>'analysis_id' IS DISTINCT FROM NEW.analysis_id::text
          OR q.selection->'customer' IS DISTINCT FROM r.selection->'customer' OR q.selection->'cloud' IS DISTINCT FROM r.selection->'cloud'
          OR q.selection->>'network_namespace' IS DISTINCT FROM r.selection->>'network_namespace' THEN
          RAISE EXCEPTION 'supplement confirmation scope mismatch';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER core_supplement_identity BEFORE INSERT ON core_comparison_supplements
      FOR EACH ROW EXECUTE FUNCTION guard_core_supplement_identity();
    CREATE TRIGGER core_comparison_immutable BEFORE UPDATE OR DELETE ON core_comparison_results
      FOR EACH ROW EXECUTE FUNCTION guard_netflow_revision_mutation();
    CREATE TRIGGER core_supplement_immutable BEFORE UPDATE OR DELETE ON core_comparison_supplements
      FOR EACH ROW EXECUTE FUNCTION guard_netflow_revision_mutation();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM core_comparison_results) OR EXISTS(SELECT 1 FROM core_comparison_supplements)"
            )
        )
        .scalar()
    ):
        raise RuntimeError(
            "Cannot remove immutable core results or evidence bindings; use a forward migration"
        )
    op.drop_table("core_comparison_supplements")
    op.drop_table("core_comparison_results")
    op.execute("DROP FUNCTION guard_core_supplement_identity()")
    op.execute("DROP FUNCTION guard_core_comparison_identity()")
