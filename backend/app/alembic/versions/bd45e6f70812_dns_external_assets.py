"""Add DNS-only contracts while retaining the existing root/IP guards.

Revision ID: bd45e6f70812
Revises: ac34d5e6f701
"""

import sqlalchemy as sa
from alembic import op

revision = "bd45e6f70812"
down_revision = "ac34d5e6f701"
branch_labels = None
depends_on = None

# Exact, reversible edits to the preceding revision's functions. Fail rather than
# silently weakening a guard if its expected body is not present.
_GUARD_EDITS = (
    (
        "guard_external_record",
        "ELSIF NEW.ip IS NULL OR NEW.canonical_ip IS NULL THEN",
        """ELSIF record_domain = 'dns' THEN
            IF expiry <= CURRENT_TIMESTAMP OR NEW.ip IS NOT NULL OR NEW.canonical_ip IS NOT NULL
               OR NOT valid_external_dns_fields(NEW.fields, NEW.source_id) THEN
              RAISE EXCEPTION 'external DNS record is invalid';
            END IF;
          ELSIF NEW.ip IS NULL OR NEW.canonical_ip IS NULL THEN""",
    ),
    (
        "guard_external_version",
        "IF root_source AND NOT EXISTS (",
        """IF (NEW.domain = 'dns') IS DISTINCT FROM
             (SELECT s.capability_profile = 'dns-v1' FROM source_instances s WHERE s.id = NEW.source_id) THEN
            RAISE EXCEPTION 'external DNS version domain source mismatch';
          END IF;
          IF NEW.domain = 'dns' AND NOT EXISTS (
            SELECT 1 FROM external_syncs t JOIN source_instances s ON s.id = t.source_id
            WHERE t.id = NEW.sync_id AND s.id = NEW.source_id
              AND t.request->>'publication_mode' = 'dns-bounded-v1'
              AND t.request->>'flat' = '1' AND t.request->>'status' = 'valid' AND t.request->>'sort' = '-id'
              AND (NEW.space_id, NEW.instance_id, NEW.capset_id, NEW.fingerprint, NEW.retain_until)
                  IS NOT DISTINCT FROM (s.space_id, s.instance_id, s.capset_id, t.fingerprint, t.retain_until)
              AND NEW.filter = '{"flat":"1","status":"valid"}'::jsonb AND NEW.sort = '-id') THEN
            RAISE EXCEPTION 'external DNS version scope mismatch';
          END IF;
          IF root_source AND NOT EXISTS (""",
    ),
    (
        "guard_external_version",
        "IF root_source AND NEW.retain_until <= CURRENT_TIMESTAMP THEN",
        "IF (root_source OR NEW.domain = 'dns') AND NEW.retain_until <= CURRENT_TIMESTAMP THEN",
    ),
    (
        "guard_external_version",
        "CASE WHEN root_source THEN 'root-domain-bounded-v1' ELSE 'bounded-v1' END",
        "CASE WHEN root_source THEN 'root-domain-bounded-v1' WHEN NEW.domain = 'dns' THEN 'dns-bounded-v1' ELSE 'bounded-v1' END",
    ),
    (
        "guard_external_version",
        "CASE WHEN root_source THEN 1 ELSE 2 END",
        "CASE WHEN root_source OR NEW.domain = 'dns' THEN 1 ELSE 2 END",
    ),
    (
        "guard_external_version",
        "CASE WHEN root_source THEN capacity WHEN NEW.domain = 'ip'",
        "CASE WHEN root_source OR NEW.domain = 'dns' THEN capacity WHEN NEW.domain = 'ip'",
    ),
)


def _edit_guards(*, reverse: bool = False) -> None:
    for name, before, after in reversed(_GUARD_EDITS) if reverse else _GUARD_EDITS:
        if reverse:
            before, after = after, before
        definition = op.get_bind().scalar(
            sa.text("SELECT pg_get_functiondef(CAST(:name AS regproc))"), {"name": name}
        )
        if not isinstance(definition, str) or definition.count(before) != 1:
            raise RuntimeError(f"Unexpected preceding definition for {name}")
        op.execute(definition.replace(before, after))


def _constraints(*, dns: bool) -> None:
    for name, table, expression in (
        (
            "ck_source_instances_type",
            "source_instances",
            "source_type IN ('cloudatlas', 'cloudatlas_root_domains'"
            + (", 'cloudatlas_dns')" if dns else ")"),
        ),
        (
            "ck_source_instances_profile",
            "source_instances",
            "((source_type = 'cloudatlas' AND capability_profile IN ('legacy-ip-v1', 'assets-v1')) OR "
            "(source_type = 'cloudatlas_root_domains' AND capability_profile = 'root-domains-v1')"
            + (
                " OR (source_type = 'cloudatlas_dns' AND capability_profile = 'dns-v1')"
                if dns
                else ""
            )
            + ") AND (capability_profile = 'legacy-ip-v1' OR space_id IS NOT NULL)",
        ),
        (
            "ck_external_version_domain",
            "external_asset_versions",
            "domain IN ('ip','port','root_domain'" + (",'dns')" if dns else ")"),
        ),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, expression)


def upgrade() -> None:
    _constraints(dns=True)
    op.execute("""
        CREATE FUNCTION guard_external_dns_source() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF 'dns-v1' IN (NEW.capability_profile, OLD.capability_profile)
             AND (NEW.source_type, NEW.capability_profile) IS DISTINCT FROM (OLD.source_type, OLD.capability_profile) THEN
            RAISE EXCEPTION 'external DNS source contract is immutable';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER guard_external_dns_source BEFORE UPDATE ON source_instances
          FOR EACH ROW EXECUTE FUNCTION guard_external_dns_source();

        CREATE FUNCTION guard_external_dns_sync() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE profile text;
        BEGIN
          SELECT capability_profile INTO profile FROM source_instances WHERE id = NEW.source_id;
          IF (profile = 'dns-v1') IS DISTINCT FROM
             (COALESCE(NEW.request->>'publication_mode', '') = 'dns-bounded-v1') THEN
            RAISE EXCEPTION 'external DNS sync source contract mismatch';
          END IF;
          IF profile = 'dns-v1' AND ((NEW.request->>'flat', NEW.request->>'status', NEW.request->>'sort')
                                   IS DISTINCT FROM ('1', 'valid', '-id')) THEN
            RAISE EXCEPTION 'external DNS request scope mismatch';
          END IF;
          IF TG_OP = 'UPDATE' AND (OLD.request->>'publication_mode' = 'dns-bounded-v1' OR profile = 'dns-v1') AND
             (NEW.source_id, NEW.project_id, NEW.actor_id, NEW.idempotency_key, NEW.request_sha256,
              NEW.request, NEW.fingerprint, NEW.token_sha256, NEW.agent_run_id, NEW.agent_project_id, NEW.retain_until)
             IS DISTINCT FROM
             (OLD.source_id, OLD.project_id, OLD.actor_id, OLD.idempotency_key, OLD.request_sha256,
              OLD.request, OLD.fingerprint, OLD.token_sha256, OLD.agent_run_id, OLD.agent_project_id, OLD.retain_until) THEN
            RAISE EXCEPTION 'external DNS sync contract is immutable';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER guard_external_dns_sync BEFORE INSERT OR UPDATE ON external_syncs
          FOR EACH ROW EXECUTE FUNCTION guard_external_dns_sync();

        CREATE FUNCTION valid_external_dns_fields(fields jsonb, source_id text) RETURNS boolean
        LANGUAGE plpgsql IMMUTABLE AS $$
        DECLARE key text; item jsonb;
        BEGIN
          IF jsonb_typeof(fields) IS DISTINCT FROM 'object'
             OR jsonb_typeof(fields->'id') IS DISTINCT FROM 'string'
             OR fields->>'id' IS DISTINCT FROM source_id
             OR source_id !~ '^-?(0|[1-9][0-9]*)$' THEN RETURN false; END IF;
          FOREACH key IN ARRAY ARRAY['domain','subdomain','rdtype','record','status','bu','created_at','updated_at','lastseen_at'] LOOP
            IF jsonb_typeof(fields->key) IS DISTINCT FROM 'string' THEN RETURN false; END IF;
          END LOOP;
          IF jsonb_typeof(fields->'tags') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
          FOR item IN SELECT value FROM jsonb_array_elements(fields->'tags') LOOP
            IF jsonb_typeof(item) IS DISTINCT FROM 'object'
               OR jsonb_typeof(item->'pk') IS DISTINCT FROM 'string'
               OR (item->>'pk') !~ '^-?(0|[1-9][0-9]*)$' OR length(item->>'pk') > 100
               OR jsonb_typeof(item->'name') IS DISTINCT FROM 'string' THEN RETURN false; END IF;
          END LOOP;
          RETURN true;
        END $$;
    """)
    _edit_guards()


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("""
        SELECT EXISTS (SELECT 1 FROM source_instances WHERE capability_profile = 'dns-v1' OR source_type = 'cloudatlas_dns')
            OR EXISTS (SELECT 1 FROM external_syncs WHERE request->>'publication_mode' = 'dns-bounded-v1')
            OR EXISTS (SELECT 1 FROM external_asset_versions WHERE domain = 'dns')
            OR EXISTS (SELECT 1 FROM external_asset_heads WHERE domain = 'dns')
    """)
    ):
        raise RuntimeError(
            "Cannot discard DNS contracts while sources, tasks or data exist"
        )
    _edit_guards(reverse=True)
    op.execute("""
        DROP TRIGGER guard_external_dns_source ON source_instances;
        DROP TRIGGER guard_external_dns_sync ON external_syncs;
        DROP FUNCTION guard_external_dns_source();
        DROP FUNCTION guard_external_dns_sync();
        DROP FUNCTION valid_external_dns_fields(jsonb, text);
    """)
    _constraints(dns=False)
