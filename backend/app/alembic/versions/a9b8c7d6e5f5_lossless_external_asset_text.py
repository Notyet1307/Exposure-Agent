"""Preserve CloudAtlas JSON strings containing a NUL without SQL JSONB decoding.

Revision ID: a9b8c7d6e5f5
Revises: df67a8192a34
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a9b8c7d6e5f5"
down_revision = "df67a8192a34"
branch_labels = None
depends_on = None


_ROOT_OLD = "OR NOT valid_external_root_fields(NEW.fields, NEW.source_id)"
_ROOT_NEW = """OR NOT valid_lossless_external_root_record(
                 NEW.fields, NEW.source_id, NEW.root_domain_segments, NEW.status_segments
               )"""
_DNS_OLD = "OR NOT valid_external_dns_fields(NEW.fields, NEW.source_id)"
_DNS_NEW = """OR NOT valid_lossless_external_dns_record(
                 NEW.fields, NEW.source_id, NEW.subdomain_segments, NEW.status_segments
               )"""


_LOSSLESS_HELPERS = r"""
    -- A non-consuming lookbehind handles adjacent escapes and preserves every
    -- pair of literal backslashes. No per-character PL/pgSQL copying is needed.
    CREATE FUNCTION external_asset_json_has_nul(document json)
    RETURNS boolean LANGUAGE sql IMMUTABLE STRICT AS $$
      SELECT document::text ~ $rx$(?<!\\)((?:\\\\)*)\\u0000$rx$
    $$;

    CREATE FUNCTION external_asset_json_nul_copy(document json, replacement integer)
    RETURNS jsonb LANGUAGE sql IMMUTABLE STRICT AS $$
      SELECT regexp_replace(
        document::text,
        $rx$(?<!\\)((?:\\\\)*)\\u0000$rx$,
        $replacement$\1\\u$replacement$ || lpad(to_hex(replacement), 4, '0'),
        'g'
      )::jsonb
    $$;

    CREATE FUNCTION external_asset_projection_matches(
      first_value text, second_value text, segments text[]
    ) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
      SELECT CASE WHEN first_value IS NULL AND second_value IS NULL
                  THEN segments IS NULL
                  ELSE COALESCE(
                    array_ndims(segments) = 1
                    AND array_lower(segments, 1) = 1
                    AND cardinality(segments) > 0
                    AND array_position(segments, NULL) IS NULL
                    AND array_to_string(segments, chr(1)) = first_value
                    AND array_to_string(segments, chr(2)) = second_value,
                    false)
             END
    $$;

    CREATE FUNCTION checked_external_asset_projection(
      first_value jsonb, second_value jsonb, segments text[]
    ) RETURNS text[] LANGUAGE plpgsql IMMUTABLE AS $$
    DECLARE first_text text; second_text text;
    BEGIN
      IF jsonb_typeof(first_value) = 'string' THEN
        first_text := first_value #>> '{}';
        second_text := second_value #>> '{}';
        -- Legacy direct inserts need no knowledge of the derived columns.
        -- New NUL-bearing names require their lossless split from the writer.
        IF segments IS NULL AND first_text IS NOT DISTINCT FROM second_text THEN
          segments := ARRAY[first_text];
        END IF;
      END IF;
      IF NOT external_asset_projection_matches(first_text, second_text, segments) THEN
        RAISE EXCEPTION 'External asset text projection mismatch';
      END IF;
      RETURN segments;
    END $$;

    CREATE FUNCTION project_external_asset_text() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE first_copy jsonb; second_copy jsonb;
    BEGIN
      IF external_asset_json_has_nul(NEW.fields) THEN
        first_copy := external_asset_json_nul_copy(NEW.fields, 1);
        second_copy := external_asset_json_nul_copy(NEW.fields, 2);
      ELSE
        first_copy := NEW.fields::jsonb;
        second_copy := first_copy;
      END IF;
      IF jsonb_typeof(first_copy) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'External asset fields must be an object';
      END IF;
      NEW.root_domain_segments := checked_external_asset_projection(
        first_copy->'root_domain', second_copy->'root_domain', NEW.root_domain_segments);
      NEW.subdomain_segments := checked_external_asset_projection(
        first_copy->'subdomain', second_copy->'subdomain', NEW.subdomain_segments);
      NEW.status_segments := checked_external_asset_projection(
        first_copy->'status', second_copy->'status', NEW.status_segments);
      RETURN NEW;
    END $$;

    CREATE TRIGGER aa_project_external_asset_text
      BEFORE INSERT OR UPDATE ON external_asset_records
      FOR EACH ROW EXECUTE FUNCTION project_external_asset_text();

    CREATE FUNCTION valid_lossless_external_root_record(
      document json, source_id text, root_segments text[], status_segments text[]
    ) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
      WITH first_copy AS (SELECT external_asset_json_nul_copy(document, 1) AS fields),
           second_copy AS (SELECT external_asset_json_nul_copy(document, 2) AS fields)
      SELECT COALESCE(
        valid_external_root_fields(first_copy.fields, source_id)
        AND valid_external_root_fields(second_copy.fields, source_id)
        AND external_asset_projection_matches(
          first_copy.fields->>'root_domain', second_copy.fields->>'root_domain', root_segments)
        AND external_asset_projection_matches(
          first_copy.fields->>'status', second_copy.fields->>'status', status_segments),
        false)
      FROM first_copy, second_copy
    $$;

    CREATE FUNCTION valid_lossless_external_dns_record(
      document json, source_id text, subdomain_segments text[], status_segments text[]
    ) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
      WITH first_copy AS (SELECT external_asset_json_nul_copy(document, 1) AS fields),
           second_copy AS (SELECT external_asset_json_nul_copy(document, 2) AS fields)
      SELECT COALESCE(
        valid_external_dns_fields(first_copy.fields, source_id)
        AND valid_external_dns_fields(second_copy.fields, source_id)
        AND external_asset_projection_matches(
          first_copy.fields->>'subdomain', second_copy.fields->>'subdomain', subdomain_segments)
        AND external_asset_projection_matches(
          first_copy.fields->>'status', second_copy.fields->>'status', status_segments),
        false)
      FROM first_copy, second_copy
    $$;
"""


def _replace_record_guard(*, reverse: bool) -> None:
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_functiondef('guard_external_record'::regproc)")
    )
    if not isinstance(definition, str):
        raise RuntimeError("External record guard is missing")
    edits = ((_ROOT_OLD, _ROOT_NEW), (_DNS_OLD, _DNS_NEW))
    for before, after in edits:
        if reverse:
            before, after = after, before
        if definition.count(before) != 1:
            raise RuntimeError("Unexpected external record guard definition")
        definition = definition.replace(before, after)
    op.execute(definition)


def upgrade() -> None:
    for column in (
        "root_domain_segments",
        "subdomain_segments",
        "status_segments",
    ):
        op.add_column(
            "external_asset_records",
            sa.Column(column, postgresql.ARRAY(sa.Text()), nullable=True),
        )

    # Existing JSONB values cannot contain a NUL. Backfill before changing the
    # type, because JSONB extraction itself would be unsafe after the change.
    # ALTER TABLE holds an exclusive lock until this migration commits.
    # Suspend only the immutable-record trigger for this derived-column
    # backfill; preserve every unrelated trigger and its original mode.
    trigger_mode = op.get_bind().scalar(
        sa.text(
            "SELECT tgenabled FROM pg_trigger "
            "WHERE tgrelid = 'external_asset_records'::regclass "
            "AND tgname = 'guard_external_record'"
        )
    )
    if trigger_mode not in ("O", "A", "R"):
        raise RuntimeError("Expected an enabled external record guard")
    op.execute(
        "ALTER TABLE external_asset_records DISABLE TRIGGER guard_external_record"
    )
    op.execute("""
        UPDATE external_asset_records
        SET root_domain_segments = CASE WHEN jsonb_typeof(fields->'root_domain') = 'string'
                                        THEN ARRAY[fields->>'root_domain'] END,
            subdomain_segments = CASE WHEN jsonb_typeof(fields->'subdomain') = 'string'
                                      THEN ARRAY[fields->>'subdomain'] END,
            status_segments = CASE WHEN jsonb_typeof(fields->'status') = 'string'
                                   THEN ARRAY[fields->>'status'] END
    """)
    enabled = {"O": "ENABLE", "A": "ENABLE ALWAYS", "R": "ENABLE REPLICA"}[trigger_mode]
    op.execute(
        f"ALTER TABLE external_asset_records {enabled} TRIGGER guard_external_record"
    )
    op.alter_column(
        "external_asset_records",
        "fields",
        type_=sa.JSON(),
        existing_type=postgresql.JSONB(),
        postgresql_using="fields::text::json",
    )
    op.execute(r"""
        CREATE FUNCTION external_asset_segments_icontains(segments text[], query_segments text[])
        RETURNS boolean LANGUAGE sql IMMUTABLE STRICT AS $$
          WITH escaped AS (
            SELECT ordinality, replace(replace(replace(value, E'\\', E'\\\\'), '%', E'\\%'), '_', E'\\_') AS value
            FROM unnest(query_segments) WITH ORDINALITY AS query_value(value, ordinality)
          )
          SELECT CASE
            WHEN cardinality(query_segments) = 1 THEN EXISTS (
              SELECT 1 FROM unnest(segments) AS segment
              WHERE segment ILIKE '%' || (SELECT value FROM escaped WHERE ordinality = 1) || '%' ESCAPE E'\\'
            )
            ELSE EXISTS (
              SELECT 1 FROM generate_subscripts(segments, 1) AS start_at
              WHERE start_at + cardinality(query_segments) - 1 <= cardinality(segments)
                AND segments[start_at] ILIKE '%' || (SELECT value FROM escaped WHERE ordinality = 1) ESCAPE E'\\'
                AND segments[start_at + cardinality(query_segments) - 1]
                    ILIKE (SELECT value FROM escaped WHERE ordinality = cardinality(query_segments)) || '%' ESCAPE E'\\'
                AND NOT EXISTS (
                  SELECT 1 FROM escaped
                  WHERE ordinality > 1 AND ordinality < cardinality(query_segments)
                    AND segments[start_at + ordinality - 1] NOT ILIKE value ESCAPE E'\\'
                )
            )
          END
        $$;
    """)
    op.execute(_LOSSLESS_HELPERS)
    _replace_record_guard(reverse=False)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM external_asset_records WHERE external_asset_json_has_nul(fields))"
        )
    ):
        raise RuntimeError(
            "Cannot convert lossless external asset JSON containing NUL to JSONB"
        )
    _replace_record_guard(reverse=True)
    op.execute("DROP TRIGGER aa_project_external_asset_text ON external_asset_records")
    op.execute("DROP FUNCTION project_external_asset_text()")
    op.alter_column(
        "external_asset_records",
        "fields",
        type_=postgresql.JSONB(),
        existing_type=sa.JSON(),
        postgresql_using="fields::text::jsonb",
    )
    op.execute("DROP FUNCTION external_asset_segments_icontains(text[], text[])")
    op.execute(
        "DROP FUNCTION valid_lossless_external_dns_record(json, text, text[], text[])"
    )
    op.execute(
        "DROP FUNCTION valid_lossless_external_root_record(json, text, text[], text[])"
    )
    op.execute("DROP FUNCTION checked_external_asset_projection(jsonb, jsonb, text[])")
    op.execute("DROP FUNCTION external_asset_projection_matches(text, text, text[])")
    op.execute("DROP FUNCTION external_asset_json_nul_copy(json, integer)")
    op.execute("DROP FUNCTION external_asset_json_has_nul(json)")
    for column in (
        "status_segments",
        "subdomain_segments",
        "root_domain_segments",
    ):
        op.drop_column("external_asset_records", column)
