"""Adopt the approved DNS business-group object without rewriting history.

Revision ID: ce56f7081923
Revises: bd45e6f70812
"""

import sqlalchemy as sa
from alembic import op

revision = "ce56f7081923"
down_revision = "bd45e6f70812"
branch_labels = None
depends_on = None

_OLD = """          FOREACH key IN ARRAY ARRAY['domain','subdomain','rdtype','record','status','bu','created_at','updated_at','lastseen_at'] LOOP
            IF jsonb_typeof(fields->key) IS DISTINCT FROM 'string' THEN RETURN false; END IF;
          END LOOP;"""
_NEW = """          FOREACH key IN ARRAY ARRAY['domain','subdomain','rdtype','record','status','created_at','updated_at','lastseen_at'] LOOP
            IF jsonb_typeof(fields->key) IS DISTINCT FROM 'string' THEN RETURN false; END IF;
          END LOOP;
          IF jsonb_typeof(fields->'bu') IS DISTINCT FROM 'object'
             OR jsonb_typeof(fields->'bu'->'id') IS DISTINCT FROM 'string'
             OR (fields->'bu'->>'id') !~ '^-?(0|[1-9][0-9]*)$'
             OR length(fields->'bu'->>'id') > 100
             OR jsonb_typeof(fields->'bu'->'name') IS DISTINCT FROM 'string' THEN RETURN false; END IF;"""


def _replace_guard(before: str, after: str) -> None:
    definition = op.get_bind().scalar(
        sa.text(
            "SELECT pg_get_functiondef('valid_external_dns_fields(jsonb, text)'::regprocedure)"
        )
    )
    if not isinstance(definition, str) or definition.count(before) != 1:
        raise RuntimeError("Unexpected preceding DNS field guard")
    op.execute(definition.replace(before, after))


def upgrade() -> None:
    _replace_guard(_OLD, _NEW)


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("""
        SELECT EXISTS (
          SELECT 1 FROM external_asset_records r
          JOIN external_asset_versions v ON v.id = r.version_id
          WHERE v.domain = 'dns' AND jsonb_typeof(r.fields->'bu') = 'object'
        )
        """)
    ):
        raise RuntimeError("Cannot revert DNS bu contract while object records exist")
    _replace_guard(_NEW, _OLD)
