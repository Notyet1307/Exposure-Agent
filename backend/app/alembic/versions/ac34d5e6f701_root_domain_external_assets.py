"""Add isolated root-domain publication without rewriting historical asset contracts.

Revision ID: ac34d5e6f701
Revises: 9bc23d4e5f60
"""

import sqlalchemy as sa
from alembic import op

revision = "ac34d5e6f701"
down_revision = "9bc23d4e5f60"
branch_labels = None
depends_on = None


# Keep the preceding seal policy verbatim for a lossless downgrade.
_LEGACY_VERSION_GUARD = """
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
"""

_LEGACY_RECORD_GUARD = """
CREATE OR REPLACE FUNCTION guard_external_record() RETURNS trigger LANGUAGE plpgsql AS $$
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
"""


def upgrade() -> None:
    op.drop_constraint("ck_source_instances_type", "source_instances", type_="check")
    op.create_check_constraint(
        "ck_source_instances_type",
        "source_instances",
        "source_type IN ('cloudatlas', 'cloudatlas_root_domains')",
    )
    op.drop_constraint("ck_source_instances_profile", "source_instances", type_="check")
    op.create_check_constraint(
        "ck_source_instances_profile",
        "source_instances",
        "((source_type = 'cloudatlas' AND capability_profile IN ('legacy-ip-v1', 'assets-v1')) OR "
        "(source_type = 'cloudatlas_root_domains' AND capability_profile = 'root-domains-v1')) AND "
        "(capability_profile = 'legacy-ip-v1' OR space_id IS NOT NULL)",
    )
    for table in ("external_asset_versions", "external_asset_heads"):
        op.alter_column(
            table, "domain", type_=sa.String(20), existing_type=sa.String(10)
        )
    op.drop_constraint(
        "ck_external_version_domain", "external_asset_versions", type_="check"
    )
    op.create_check_constraint(
        "ck_external_version_domain",
        "external_asset_versions",
        "domain IN ('ip','port','root_domain')",
    )
    for column in ("ip", "canonical_ip"):
        op.alter_column(
            "external_asset_records", column, nullable=True, existing_type=sa.String(45)
        )
    op.execute("""
        CREATE FUNCTION guard_external_root_source() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF (NEW.source_type, NEW.capability_profile) IS DISTINCT FROM (OLD.source_type, OLD.capability_profile)
             AND ('root-domains-v1' IN (NEW.capability_profile, OLD.capability_profile)) THEN
            RAISE EXCEPTION 'external root source contract is immutable';
          END IF;
          IF EXISTS (SELECT 1 FROM external_syncs WHERE source_id = OLD.id)
             AND (NEW.instance_id, NEW.capset_id, NEW.space_id, NEW.capability_profile, NEW.source_type, NEW.project_id, NEW.tenant_id)
             IS DISTINCT FROM (OLD.instance_id, OLD.capset_id, OLD.space_id, OLD.capability_profile, OLD.source_type, OLD.project_id, OLD.tenant_id) THEN
            RAISE EXCEPTION 'external source binding is immutable';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER guard_external_root_source BEFORE UPDATE ON source_instances
          FOR EACH ROW EXECUTE FUNCTION guard_external_root_source();

        CREATE FUNCTION guard_external_root_sync() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE profile text;
        BEGIN
          SELECT capability_profile INTO profile FROM source_instances WHERE id = NEW.source_id;
          IF (profile = 'root-domains-v1') IS DISTINCT FROM
             (COALESCE(NEW.request->>'publication_mode', '') = 'root-domain-bounded-v1') THEN
            RAISE EXCEPTION 'external sync source contract mismatch';
          END IF;
          IF TG_OP = 'UPDATE' AND (OLD.request->>'publication_mode' = 'root-domain-bounded-v1'
                                  OR profile = 'root-domains-v1') AND
             (NEW.source_id, NEW.project_id, NEW.actor_id, NEW.idempotency_key, NEW.request_sha256,
              NEW.request, NEW.fingerprint, NEW.token_sha256, NEW.agent_run_id, NEW.agent_project_id, NEW.retain_until)
             IS DISTINCT FROM
             (OLD.source_id, OLD.project_id, OLD.actor_id, OLD.idempotency_key, OLD.request_sha256,
              OLD.request, OLD.fingerprint, OLD.token_sha256, OLD.agent_run_id, OLD.agent_project_id, OLD.retain_until) THEN
            RAISE EXCEPTION 'external root sync contract is immutable';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER guard_external_root_sync BEFORE INSERT OR UPDATE ON external_syncs
          FOR EACH ROW EXECUTE FUNCTION guard_external_root_sync();

        CREATE FUNCTION valid_external_root_fields(fields jsonb, source_id text) RETURNS boolean
        LANGUAGE plpgsql IMMUTABLE AS $$
        DECLARE key text; item jsonb;
        BEGIN
          IF jsonb_typeof(fields) IS DISTINCT FROM 'object'
             OR jsonb_typeof(fields->'id') IS DISTINCT FROM 'string'
             OR fields->>'id' IS DISTINCT FROM source_id
             OR source_id !~ '^-?(0|[1-9][0-9]*)$' THEN RETURN false; END IF;
          FOREACH key IN ARRAY ARRAY['root_domain','status','created_at','updated_at','lastseen_at'] LOOP
            IF jsonb_typeof(fields->key) IS DISTINCT FROM 'string' THEN RETURN false; END IF;
          END LOOP;
          IF btrim(fields->>'root_domain') = '' OR btrim(fields->>'status') = '' THEN RETURN false; END IF;
          FOREACH key IN ARRAY ARRAY['icp_date','icp_num','icp_official_name','whois_registrant','whois_email','whois_expiration_time'] LOOP
            IF NOT fields ? key OR jsonb_typeof(fields->key) NOT IN ('null','string') THEN RETURN false; END IF;
          END LOOP;
          IF jsonb_typeof(fields->'valid_subdomain') IS DISTINCT FROM 'number'
             OR (fields->>'valid_subdomain') !~ '^-?[0-9]+$'
             OR abs((fields->>'valid_subdomain')::numeric) > 9007199254740991
             OR jsonb_typeof(fields->'sources') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
          FOR item IN SELECT value FROM jsonb_array_elements(fields->'sources') LOOP
            IF jsonb_typeof(item) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
            FOREACH key IN ARRAY ARRAY['source','reason','factor'] LOOP
              IF jsonb_typeof(item->key) IS DISTINCT FROM 'string' THEN RETURN false; END IF;
            END LOOP;
          END LOOP;
          RETURN true;
        END $$;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION guard_external_record() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE version_status text; expiry timestamptz; record_domain text;
        BEGIN
          IF TG_OP = 'UPDATE' THEN RAISE EXCEPTION 'external record is immutable'; END IF;
          IF TG_OP = 'DELETE' THEN
            SELECT retain_until INTO expiry FROM external_asset_versions WHERE id = OLD.version_id FOR SHARE;
            IF expiry > CURRENT_TIMESTAMP THEN RAISE EXCEPTION 'external record retention has not expired'; END IF;
            RETURN OLD;
          END IF;
          SELECT status, retain_until, domain INTO version_status, expiry, record_domain
            FROM external_asset_versions WHERE id = NEW.version_id FOR SHARE;
          IF version_status IS DISTINCT FROM 'RUNNING' THEN RAISE EXCEPTION 'external version is not staging'; END IF;
          IF record_domain = 'root_domain' THEN
            IF expiry <= CURRENT_TIMESTAMP OR NEW.ip IS NOT NULL OR NEW.canonical_ip IS NOT NULL
               OR NOT valid_external_root_fields(NEW.fields, NEW.source_id) THEN
              RAISE EXCEPTION 'external root record is invalid';
            END IF;
          ELSIF NEW.ip IS NULL OR NEW.canonical_ip IS NULL THEN
            RAISE EXCEPTION 'external IP record requires an address';
          END IF;
          RETURN NEW;
        END $$;
    """)
    # Extend the existing trusted seal, retaining its prior-state and persisted-value checks.
    guard = (
        _LEGACY_VERSION_GUARD.replace(
            "DECLARE policy jsonb; capacity integer; quota integer;",
            "DECLARE policy jsonb; capacity integer; quota integer; minimum integer; root_source boolean;",
        )
        .replace(
            "  IF NEW.status = 'PUBLISHED' THEN",
            """  SELECT s.capability_profile = 'root-domains-v1' INTO root_source
            FROM source_instances s WHERE s.id = NEW.source_id;
          IF (NEW.domain = 'root_domain') IS DISTINCT FROM root_source THEN
            RAISE EXCEPTION 'external version domain source mismatch';
          END IF;
          IF root_source AND NOT EXISTS (
            SELECT 1 FROM external_syncs t JOIN source_instances s ON s.id = t.source_id
            WHERE t.id = NEW.sync_id AND s.id = NEW.source_id
              AND t.request->>'publication_mode' = 'root-domain-bounded-v1'
              AND (NEW.space_id, NEW.instance_id, NEW.capset_id, NEW.fingerprint, NEW.retain_until)
                  IS NOT DISTINCT FROM (s.space_id, s.instance_id, s.capset_id, t.fingerprint, t.retain_until)
              AND NEW.filter = '{"status":"valid"}'::jsonb AND NEW.sort = '-id') THEN
            RAISE EXCEPTION 'external root version scope mismatch';
          END IF;
          IF NEW.status = 'PUBLISHED' THEN
            IF root_source AND NEW.retain_until <= CURRENT_TIMESTAMP THEN
              RAISE EXCEPTION 'external root publication has expired';
            END IF;""",
        )
        .replace(
            "      IF policy->>'publication_mode' IS DISTINCT FROM 'bounded-v1' THEN",
            "      IF policy->>'publication_mode' IS DISTINCT FROM\n"
            "         (CASE WHEN root_source THEN 'root-domain-bounded-v1' ELSE 'bounded-v1' END) THEN",
        )
        .replace(
            "      quota := CASE WHEN NEW.domain = 'ip' THEN (capacity + 1) / 2 ELSE capacity / 2 END;",
            "      minimum := CASE WHEN root_source THEN 1 ELSE 2 END;\n"
            "      quota := CASE WHEN root_source THEN capacity WHEN NEW.domain = 'ip' THEN (capacity + 1) / 2 ELSE capacity / 2 END;",
        )
        .replace("(capacity >= 2 AND", "(capacity >= minimum AND")
    )
    op.execute(guard)


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("""
        SELECT EXISTS (SELECT 1 FROM source_instances WHERE capability_profile = 'root-domains-v1'
                       OR source_type = 'cloudatlas_root_domains')
            OR EXISTS (SELECT 1 FROM external_syncs WHERE request->>'publication_mode' = 'root-domain-bounded-v1')
            OR EXISTS (SELECT 1 FROM external_asset_versions WHERE domain = 'root_domain')
            OR EXISTS (SELECT 1 FROM external_asset_heads WHERE domain = 'root_domain')
            OR EXISTS (SELECT 1 FROM external_asset_records WHERE ip IS NULL OR canonical_ip IS NULL)
    """)
    ):
        raise RuntimeError(
            "Cannot discard root-domain contracts while sources, tasks or data exist"
        )
    op.execute(_LEGACY_VERSION_GUARD)
    op.execute(_LEGACY_RECORD_GUARD)
    op.execute("""
        DROP TRIGGER guard_external_root_source ON source_instances;
        DROP TRIGGER guard_external_root_sync ON external_syncs;
        DROP FUNCTION guard_external_root_source();
        DROP FUNCTION guard_external_root_sync();
        DROP FUNCTION valid_external_root_fields(jsonb, text);
    """)
    for column in ("ip", "canonical_ip"):
        op.alter_column(
            "external_asset_records",
            column,
            nullable=False,
            existing_type=sa.String(45),
        )
    op.drop_constraint(
        "ck_external_version_domain", "external_asset_versions", type_="check"
    )
    op.create_check_constraint(
        "ck_external_version_domain",
        "external_asset_versions",
        "domain IN ('ip','port')",
    )
    for table in ("external_asset_heads", "external_asset_versions"):
        op.alter_column(
            table, "domain", type_=sa.String(10), existing_type=sa.String(20)
        )
    op.drop_constraint("ck_source_instances_profile", "source_instances", type_="check")
    op.create_check_constraint(
        "ck_source_instances_profile",
        "source_instances",
        "capability_profile IN ('legacy-ip-v1', 'assets-v1') AND (capability_profile != 'assets-v1' OR space_id IS NOT NULL)",
    )
    op.drop_constraint("ck_source_instances_type", "source_instances", type_="check")
    op.create_check_constraint(
        "ck_source_instances_type", "source_instances", "source_type = 'cloudatlas'"
    )
