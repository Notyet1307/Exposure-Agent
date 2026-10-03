"""Add the fourteen fixed structured CloudAtlas domains without changing old rows.

Revision ID: ca2810000001
Revises: a9b8c7d6e5f5
"""

import json
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ca2810000001"
down_revision = "a9b8c7d6e5f5"
branch_labels = None
depends_on = None

SEARCH_FIELDS = [
    "cn_name",
    "confidence",
    "cpe",
    "hostname",
    "md5_value",
    "mmh3_value",
    "name",
    "path",
    "product_name",
    "render_title",
    "sha256",
    "subdomain",
    "target",
    "title",
    "type",
    "uri",
    "url",
    "vendor",
    "version",
]

NEW_DOMAINS = [
    "subdomain",
    "cert",
    "openport",
    "web",
    "dir",
    "appfinger",
    "crawler",
    "seed_enterprise",
    "seed_keyword",
    "seed_domain",
    "seed_email",
    "seed_cert",
    "seed_icon",
    "seed_title",
]

NEW_PROFILES = [
    "subdomain-v1",
    "cert-v1",
    "openport-v1",
    "web-v1",
    "dir-v1",
    "appfinger-v1",
    "crawler-v1",
    "seed-enterprise-v1",
    "seed-keyword-v1",
    "seed-domain-v1",
    "seed-email-v1",
    "seed-cert-v1",
    "seed-icon-v1",
    "seed-title-v1",
]

OLD_TYPES = "source_type IN ('cloudatlas', 'cloudatlas_root_domains', 'cloudatlas_dns')"

NEW_TYPES = "source_type IN ('cloudatlas', 'cloudatlas_root_domains', 'cloudatlas_dns','cloudatlas_subdomain','cloudatlas_cert','cloudatlas_openport','cloudatlas_web','cloudatlas_dir','cloudatlas_appfinger','cloudatlas_crawler','cloudatlas_seed_enterprise','cloudatlas_seed_keyword','cloudatlas_seed_domain','cloudatlas_seed_email','cloudatlas_seed_cert','cloudatlas_seed_icon','cloudatlas_seed_title')"

OLD_PROFILES = "((source_type = 'cloudatlas' AND capability_profile IN ('legacy-ip-v1', 'assets-v1')) OR (source_type = 'cloudatlas_root_domains' AND capability_profile = 'root-domains-v1') OR (source_type = 'cloudatlas_dns' AND capability_profile = 'dns-v1')) AND (capability_profile = 'legacy-ip-v1' OR space_id IS NOT NULL)"

NEW_PROFILE_RULE = "((source_type = 'cloudatlas' AND capability_profile IN ('legacy-ip-v1', 'assets-v1')) OR (source_type = 'cloudatlas_root_domains' AND capability_profile = 'root-domains-v1') OR (source_type = 'cloudatlas_dns' AND capability_profile = 'dns-v1') OR (source_type='cloudatlas_subdomain' AND capability_profile='subdomain-v1') OR (source_type='cloudatlas_cert' AND capability_profile='cert-v1') OR (source_type='cloudatlas_openport' AND capability_profile='openport-v1') OR (source_type='cloudatlas_web' AND capability_profile='web-v1') OR (source_type='cloudatlas_dir' AND capability_profile='dir-v1') OR (source_type='cloudatlas_appfinger' AND capability_profile='appfinger-v1') OR (source_type='cloudatlas_crawler' AND capability_profile='crawler-v1') OR (source_type='cloudatlas_seed_enterprise' AND capability_profile='seed-enterprise-v1') OR (source_type='cloudatlas_seed_keyword' AND capability_profile='seed-keyword-v1') OR (source_type='cloudatlas_seed_domain' AND capability_profile='seed-domain-v1') OR (source_type='cloudatlas_seed_email' AND capability_profile='seed-email-v1') OR (source_type='cloudatlas_seed_cert' AND capability_profile='seed-cert-v1') OR (source_type='cloudatlas_seed_icon' AND capability_profile='seed-icon-v1') OR (source_type='cloudatlas_seed_title' AND capability_profile='seed-title-v1')) AND (capability_profile = 'legacy-ip-v1' OR space_id IS NOT NULL)"

HELPERS = r"""

CREATE FUNCTION external_structured_domain(profile text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE profile
 WHEN 'subdomain-v1' THEN 'subdomain'
 WHEN 'cert-v1' THEN 'cert'
 WHEN 'openport-v1' THEN 'openport'
 WHEN 'web-v1' THEN 'web'
 WHEN 'dir-v1' THEN 'dir'
 WHEN 'appfinger-v1' THEN 'appfinger'
 WHEN 'crawler-v1' THEN 'crawler'
 WHEN 'seed-enterprise-v1' THEN 'seed_enterprise'
 WHEN 'seed-keyword-v1' THEN 'seed_keyword'
 WHEN 'seed-domain-v1' THEN 'seed_domain'
 WHEN 'seed-email-v1' THEN 'seed_email'
 WHEN 'seed-cert-v1' THEN 'seed_cert'
 WHEN 'seed-icon-v1' THEN 'seed_icon'
 WHEN 'seed-title-v1' THEN 'seed_title'
 ELSE NULL END
$$;
CREATE FUNCTION external_structured_filters(domain_name text) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE domain_name
 WHEN 'subdomain' THEN '{"status":"valid"}'::jsonb
 WHEN 'cert' THEN '{"status":"valid"}'::jsonb
 WHEN 'openport' THEN '{}'::jsonb
 WHEN 'web' THEN '{"status":"valid"}'::jsonb
 WHEN 'dir' THEN '{"status":"valid","flat":"1"}'::jsonb
 WHEN 'appfinger' THEN '{"status":"valid"}'::jsonb
 WHEN 'crawler' THEN '{"status":"valid"}'::jsonb
 WHEN 'seed_enterprise' THEN '{"enable":"true"}'::jsonb
 WHEN 'seed_keyword' THEN '{"enable":"true"}'::jsonb
 WHEN 'seed_domain' THEN '{"enable":"true"}'::jsonb
 WHEN 'seed_email' THEN '{"enable":"true"}'::jsonb
 WHEN 'seed_cert' THEN '{"enable":"true"}'::jsonb
 WHEN 'seed_icon' THEN '{"enable":"true"}'::jsonb
 WHEN 'seed_title' THEN '{"enable":"true"}'::jsonb
 ELSE NULL END
$$;
CREATE FUNCTION valid_external_structured_fields(fields jsonb, domain_name text, source_id text)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT COALESCE(fields->>'id'=source_id AND CASE domain_name
 WHEN 'subdomain' THEN CASE WHEN jsonb_typeof(fields)='object' THEN fields ?& ARRAY['id','subdomain','source_name','reason','status','created_at','lastseen_at']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(fields) AS key0(value) WHERE NOT (key0.value=ANY(ARRAY['created_at','id','lastseen_at','reason','source_name','status','subdomain']::text[]))) AND (NOT (fields ? 'created_at') OR COALESCE(((jsonb_typeof((fields->'created_at'))='string')),false)) AND (NOT (fields ? 'id') OR COALESCE(((jsonb_typeof((fields->'id'))='string' AND ((fields->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((fields->'id') #>> '{}')<=100)),false)) AND (NOT (fields ? 'lastseen_at') OR COALESCE(((jsonb_typeof((fields->'lastseen_at'))='string')),false)) AND (NOT (fields ? 'reason') OR COALESCE(((jsonb_typeof((fields->'reason'))='string')),false)) AND (NOT (fields ? 'source_name') OR COALESCE(((jsonb_typeof((fields->'source_name'))='string')),false)) AND (NOT (fields ? 'status') OR COALESCE(((jsonb_typeof((fields->'status'))='string')),false)) AND (NOT (fields ? 'subdomain') OR COALESCE(((jsonb_typeof((fields->'subdomain'))='string')),false)) ELSE false END
 WHEN 'cert' THEN CASE WHEN jsonb_typeof(fields)='object' THEN fields ?& ARRAY['id','sha256','start_date','end_date','cn_name','o_name','ou_name','email_name','subject','issuer','serial_number','sha1','md5','trusted','sources','status','created_at','updated_at','lastseen_at']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(fields) AS key1(value) WHERE NOT (key1.value=ANY(ARRAY['cn_name','created_at','email_name','end_date','id','issuer','lastseen_at','md5','o_name','ou_name','serial_number','sha1','sha256','sources','start_date','status','subject','trusted','updated_at']::text[]))) AND (NOT (fields ? 'cn_name') OR COALESCE(((jsonb_typeof((fields->'cn_name'))='string')),false)) AND (NOT (fields ? 'created_at') OR COALESCE(((jsonb_typeof((fields->'created_at'))='string')),false)) AND (NOT (fields ? 'email_name') OR COALESCE(((jsonb_typeof((fields->'email_name'))='string')),false)) AND (NOT (fields ? 'end_date') OR COALESCE(((jsonb_typeof((fields->'end_date'))='string')),false)) AND (NOT (fields ? 'id') OR COALESCE(((jsonb_typeof((fields->'id'))='string' AND ((fields->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((fields->'id') #>> '{}')<=100)),false)) AND (NOT (fields ? 'issuer') OR COALESCE(((jsonb_typeof((fields->'issuer'))='string')),false)) AND (NOT (fields ? 'lastseen_at') OR COALESCE(((jsonb_typeof((fields->'lastseen_at'))='string')),false)) AND (NOT (fields ? 'md5') OR COALESCE(((jsonb_typeof((fields->'md5'))='string')),false)) AND (NOT (fields ? 'o_name') OR COALESCE(((jsonb_typeof((fields->'o_name'))='string')),false)) AND (NOT (fields ? 'ou_name') OR COALESCE(((jsonb_typeof((fields->'ou_name'))='string')),false)) AND (NOT (fields ? 'serial_number') OR COALESCE(((jsonb_typeof((fields->'serial_number'))='string')),false)) AND (NOT (fields ? 'sha1') OR COALESCE(((jsonb_typeof((fields->'sha1'))='string')),false)) AND (NOT (fields ? 'sha256') OR COALESCE(((jsonb_typeof((fields->'sha256'))='string')),false)) AND (NOT (fields ? 'sources') OR COALESCE((CASE WHEN jsonb_typeof((fields->'sources'))='array' THEN NOT EXISTS(SELECT 1 FROM jsonb_array_elements((fields->'sources')) AS element2(value) WHERE NOT COALESCE((CASE WHEN jsonb_typeof(element2.value)='object' THEN element2.value ?& ARRAY['source','reason','factor']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(element2.value) AS key3(value) WHERE NOT (key3.value=ANY(ARRAY['factor','reason','source']::text[]))) AND (NOT (element2.value ? 'factor') OR COALESCE(((jsonb_typeof((element2.value->'factor'))='string')),false)) AND (NOT (element2.value ? 'reason') OR COALESCE(((jsonb_typeof((element2.value->'reason'))='string')),false)) AND (NOT (element2.value ? 'source') OR COALESCE(((jsonb_typeof((element2.value->'source'))='string')),false)) ELSE false END),false)) ELSE false END),false)) AND (NOT (fields ? 'start_date') OR COALESCE(((jsonb_typeof((fields->'start_date'))='string')),false)) AND (NOT (fields ? 'status') OR COALESCE(((jsonb_typeof((fields->'status'))='string')),false)) AND (NOT (fields ? 'subject') OR COALESCE(((jsonb_typeof((fields->'subject'))='string')),false)) AND (NOT (fields ? 'trusted') OR COALESCE(((jsonb_typeof((fields->'trusted'))='boolean')),false)) AND (NOT (fields ? 'updated_at') OR COALESCE(((jsonb_typeof((fields->'updated_at'))='string')),false)) ELSE false END
 WHEN 'openport' THEN CASE WHEN jsonb_typeof(fields)='object' THEN fields ?& ARRAY['id','ip','port','protocol','created_at','updated_at','lastseen_at']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(fields) AS key4(value) WHERE NOT (key4.value=ANY(ARRAY['created_at','id','ip','lastseen_at','port','protocol','updated_at']::text[]))) AND (NOT (fields ? 'created_at') OR COALESCE(((jsonb_typeof((fields->'created_at'))='string')),false)) AND (NOT (fields ? 'id') OR COALESCE(((jsonb_typeof((fields->'id'))='string' AND ((fields->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((fields->'id') #>> '{}')<=100)),false)) AND (NOT (fields ? 'ip') OR COALESCE(((jsonb_typeof((fields->'ip'))='string')),false)) AND (NOT (fields ? 'lastseen_at') OR COALESCE(((jsonb_typeof((fields->'lastseen_at'))='string')),false)) AND (NOT (fields ? 'port') OR COALESCE((CASE WHEN jsonb_typeof((fields->'port'))='number' THEN mod(((fields->'port') #>> '{}')::numeric,1)=0 AND abs(((fields->'port') #>> '{}')::numeric)<=9007199254740991 ELSE false END),false)) AND (NOT (fields ? 'protocol') OR COALESCE(((jsonb_typeof((fields->'protocol'))='string')),false)) AND (NOT (fields ? 'updated_at') OR COALESCE(((jsonb_typeof((fields->'updated_at'))='string')),false)) ELSE false END
 WHEN 'web' THEN CASE WHEN jsonb_typeof(fields)='object' THEN fields ?& ARRAY['id','created_at','netloc','hostname','entity','tags','ip','updated_at','port','lastseen_at','bu','url','status','scheme']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(fields) AS key5(value) WHERE NOT (key5.value=ANY(ARRAY['bu','created_at','entity','hostname','id','ip','lastseen_at','netloc','port','scheme','status','tags','updated_at','url']::text[]))) AND (NOT (fields ? 'bu') OR COALESCE((CASE WHEN jsonb_typeof((fields->'bu'))='object' THEN (fields->'bu') ?& ARRAY['id','name']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys((fields->'bu')) AS key6(value) WHERE NOT (key6.value=ANY(ARRAY['id','name']::text[]))) AND (NOT ((fields->'bu') ? 'id') OR COALESCE(((jsonb_typeof(((fields->'bu')->'id'))='string' AND (((fields->'bu')->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length(((fields->'bu')->'id') #>> '{}')<=100)),false)) AND (NOT ((fields->'bu') ? 'name') OR COALESCE(((jsonb_typeof(((fields->'bu')->'name'))='string')),false)) ELSE false END),false)) AND (NOT (fields ? 'created_at') OR COALESCE(((jsonb_typeof((fields->'created_at'))='string')),false)) AND (NOT (fields ? 'entity') OR COALESCE(((jsonb_typeof((fields->'entity'))='string')),false)) AND (NOT (fields ? 'hostname') OR COALESCE(((jsonb_typeof((fields->'hostname'))='string')),false)) AND (NOT (fields ? 'id') OR COALESCE(((jsonb_typeof((fields->'id'))='string' AND ((fields->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((fields->'id') #>> '{}')<=100)),false)) AND (NOT (fields ? 'ip') OR COALESCE(((jsonb_typeof((fields->'ip'))='string')),false)) AND (NOT (fields ? 'lastseen_at') OR COALESCE(((jsonb_typeof((fields->'lastseen_at'))='string')),false)) AND (NOT (fields ? 'netloc') OR COALESCE(((jsonb_typeof((fields->'netloc'))='string')),false)) AND (NOT (fields ? 'port') OR COALESCE((CASE WHEN jsonb_typeof((fields->'port'))='number' THEN mod(((fields->'port') #>> '{}')::numeric,1)=0 AND abs(((fields->'port') #>> '{}')::numeric)<=9007199254740991 ELSE false END),false)) AND (NOT (fields ? 'scheme') OR COALESCE(((jsonb_typeof((fields->'scheme'))='string')),false)) AND (NOT (fields ? 'status') OR COALESCE(((jsonb_typeof((fields->'status'))='string')),false)) AND (NOT (fields ? 'tags') OR COALESCE((CASE WHEN jsonb_typeof((fields->'tags'))='array' THEN NOT EXISTS(SELECT 1 FROM jsonb_array_elements((fields->'tags')) AS element7(value) WHERE NOT COALESCE((CASE WHEN jsonb_typeof(element7.value)='object' THEN element7.value ?& ARRAY['pk','name']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(element7.value) AS key8(value) WHERE NOT (key8.value=ANY(ARRAY['name','pk']::text[]))) AND (NOT (element7.value ? 'name') OR COALESCE(((jsonb_typeof((element7.value->'name'))='string')),false)) AND (NOT (element7.value ? 'pk') OR COALESCE(((jsonb_typeof((element7.value->'pk'))='string' AND ((element7.value->'pk') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((element7.value->'pk') #>> '{}')<=100)),false)) ELSE false END),false)) ELSE false END),false)) AND (NOT (fields ? 'updated_at') OR COALESCE(((jsonb_typeof((fields->'updated_at'))='string')),false)) AND (NOT (fields ? 'url') OR COALESCE(((jsonb_typeof((fields->'url'))='string')),false)) ELSE false END
 WHEN 'dir' THEN CASE WHEN jsonb_typeof(fields)='object' THEN fields ?& ARRAY['id','status','scheme','netloc','hostname','port','ip','ip_info','url','bu','tags','apps','path','level','status_code','title','render_title','server','x_powered_by','screenshot_link','location','content_type','content_lines','content_words','content_length','body_md5_hash','icon_url','icon_mmh3_hash','icon_md5_hash','isadmin','created_at','updated_at','lastseen_at']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(fields) AS key9(value) WHERE NOT (key9.value=ANY(ARRAY['apps','body_md5_hash','bu','content_length','content_lines','content_type','content_words','created_at','hostname','icon_md5_hash','icon_mmh3_hash','icon_url','id','ip','ip_info','isadmin','lastseen_at','level','location','netloc','path','port','render_title','scheme','screenshot_link','server','status','status_code','tags','title','updated_at','url','x_powered_by']::text[]))) AND (NOT (fields ? 'apps') OR COALESCE((CASE WHEN jsonb_typeof((fields->'apps'))='array' THEN NOT EXISTS(SELECT 1 FROM jsonb_array_elements((fields->'apps')) AS element10(value) WHERE NOT COALESCE((CASE WHEN jsonb_typeof(element10.value)='object' THEN element10.value ?& ARRAY['product_uuid','vendor_uuid','product_name','vendor_name','cpe','version','created_at','updated_at','lastseen_at']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(element10.value) AS key11(value) WHERE NOT (key11.value=ANY(ARRAY['cpe','created_at','lastseen_at','product_name','product_uuid','updated_at','vendor_name','vendor_uuid','version']::text[]))) AND (NOT (element10.value ? 'cpe') OR COALESCE(((jsonb_typeof((element10.value->'cpe'))='string')),false)) AND (NOT (element10.value ? 'created_at') OR COALESCE(((jsonb_typeof((element10.value->'created_at'))='string')),false)) AND (NOT (element10.value ? 'lastseen_at') OR COALESCE(((jsonb_typeof((element10.value->'lastseen_at'))='string')),false)) AND (NOT (element10.value ? 'product_name') OR COALESCE(((jsonb_typeof((element10.value->'product_name'))='string')),false)) AND (NOT (element10.value ? 'product_uuid') OR COALESCE(((jsonb_typeof((element10.value->'product_uuid'))='string')),false)) AND (NOT (element10.value ? 'updated_at') OR COALESCE(((jsonb_typeof((element10.value->'updated_at'))='string')),false)) AND (NOT (element10.value ? 'vendor_name') OR COALESCE(((jsonb_typeof((element10.value->'vendor_name'))='string')),false)) AND (NOT (element10.value ? 'vendor_uuid') OR COALESCE(((jsonb_typeof((element10.value->'vendor_uuid'))='string')),false)) AND (NOT (element10.value ? 'version') OR COALESCE(((jsonb_typeof((element10.value->'version'))='string')),false)) ELSE false END),false)) ELSE false END),false)) AND (NOT (fields ? 'body_md5_hash') OR COALESCE(((jsonb_typeof((fields->'body_md5_hash'))='string')),false)) AND (NOT (fields ? 'bu') OR COALESCE((CASE WHEN jsonb_typeof((fields->'bu'))='object' THEN (fields->'bu') ?& ARRAY['id','name']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys((fields->'bu')) AS key12(value) WHERE NOT (key12.value=ANY(ARRAY['id','name']::text[]))) AND (NOT ((fields->'bu') ? 'id') OR COALESCE(((jsonb_typeof(((fields->'bu')->'id'))='string' AND (((fields->'bu')->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length(((fields->'bu')->'id') #>> '{}')<=100)),false)) AND (NOT ((fields->'bu') ? 'name') OR COALESCE(((jsonb_typeof(((fields->'bu')->'name'))='string')),false)) ELSE false END),false)) AND (NOT (fields ? 'content_length') OR COALESCE((CASE WHEN jsonb_typeof((fields->'content_length'))='number' THEN mod(((fields->'content_length') #>> '{}')::numeric,1)=0 AND abs(((fields->'content_length') #>> '{}')::numeric)<=9007199254740991 ELSE false END),false)) AND (NOT (fields ? 'content_lines') OR COALESCE((CASE WHEN jsonb_typeof((fields->'content_lines'))='number' THEN mod(((fields->'content_lines') #>> '{}')::numeric,1)=0 AND abs(((fields->'content_lines') #>> '{}')::numeric)<=9007199254740991 ELSE false END),false)) AND (NOT (fields ? 'content_type') OR COALESCE(((jsonb_typeof((fields->'content_type'))='string')),false)) AND (NOT (fields ? 'content_words') OR COALESCE((CASE WHEN jsonb_typeof((fields->'content_words'))='number' THEN mod(((fields->'content_words') #>> '{}')::numeric,1)=0 AND abs(((fields->'content_words') #>> '{}')::numeric)<=9007199254740991 ELSE false END),false)) AND (NOT (fields ? 'created_at') OR COALESCE(((jsonb_typeof((fields->'created_at'))='string')),false)) AND (NOT (fields ? 'hostname') OR COALESCE(((jsonb_typeof((fields->'hostname'))='string')),false)) AND (NOT (fields ? 'icon_md5_hash') OR COALESCE(((jsonb_typeof((fields->'icon_md5_hash'))='null' OR ((jsonb_typeof((fields->'icon_md5_hash'))='string')))),false)) AND (NOT (fields ? 'icon_mmh3_hash') OR COALESCE(((jsonb_typeof((fields->'icon_mmh3_hash'))='null' OR ((jsonb_typeof((fields->'icon_mmh3_hash'))='string')))),false)) AND (NOT (fields ? 'icon_url') OR COALESCE(((jsonb_typeof((fields->'icon_url'))='null' OR ((jsonb_typeof((fields->'icon_url'))='string')))),false)) AND (NOT (fields ? 'id') OR COALESCE(((jsonb_typeof((fields->'id'))='string' AND ((fields->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((fields->'id') #>> '{}')<=100)),false)) AND (NOT (fields ? 'ip') OR COALESCE(((jsonb_typeof((fields->'ip'))='string')),false)) AND (NOT (fields ? 'ip_info') OR COALESCE((CASE WHEN jsonb_typeof((fields->'ip_info'))='object' THEN (fields->'ip_info') ?& ARRAY[]::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys((fields->'ip_info')) AS key13(value) WHERE NOT (key13.value=ANY(ARRAY['as_name','as_num','city','country','ip','location','provider','province','subnet','version']::text[]))) AND (NOT ((fields->'ip_info') ? 'as_name') OR COALESCE(((jsonb_typeof(((fields->'ip_info')->'as_name'))='string')),false)) AND (NOT ((fields->'ip_info') ? 'as_num') OR COALESCE(((jsonb_typeof(((fields->'ip_info')->'as_num'))='string')),false)) AND (NOT ((fields->'ip_info') ? 'city') OR COALESCE(((jsonb_typeof(((fields->'ip_info')->'city'))='string')),false)) AND (NOT ((fields->'ip_info') ? 'country') OR COALESCE(((jsonb_typeof(((fields->'ip_info')->'country'))='string')),false)) AND (NOT ((fields->'ip_info') ? 'ip') OR COALESCE(((jsonb_typeof(((fields->'ip_info')->'ip'))='string')),false)) AND (NOT ((fields->'ip_info') ? 'location') OR COALESCE(((jsonb_typeof(((fields->'ip_info')->'location'))='string')),false)) AND (NOT ((fields->'ip_info') ? 'provider') OR COALESCE(((jsonb_typeof(((fields->'ip_info')->'provider'))='string')),false)) AND (NOT ((fields->'ip_info') ? 'province') OR COALESCE(((jsonb_typeof(((fields->'ip_info')->'province'))='string')),false)) AND (NOT ((fields->'ip_info') ? 'subnet') OR COALESCE(((jsonb_typeof(((fields->'ip_info')->'subnet'))='null' OR ((jsonb_typeof(((fields->'ip_info')->'subnet'))='string')))),false)) AND (NOT ((fields->'ip_info') ? 'version') OR COALESCE((CASE WHEN jsonb_typeof(((fields->'ip_info')->'version'))='number' THEN mod((((fields->'ip_info')->'version') #>> '{}')::numeric,1)=0 AND abs((((fields->'ip_info')->'version') #>> '{}')::numeric)<=9007199254740991 ELSE false END),false)) ELSE false END),false)) AND (NOT (fields ? 'isadmin') OR COALESCE(((jsonb_typeof((fields->'isadmin'))='boolean')),false)) AND (NOT (fields ? 'lastseen_at') OR COALESCE(((jsonb_typeof((fields->'lastseen_at'))='string')),false)) AND (NOT (fields ? 'level') OR COALESCE((CASE WHEN jsonb_typeof((fields->'level'))='number' THEN mod(((fields->'level') #>> '{}')::numeric,1)=0 AND abs(((fields->'level') #>> '{}')::numeric)<=9007199254740991 ELSE false END),false)) AND (NOT (fields ? 'location') OR COALESCE(((jsonb_typeof((fields->'location'))='string')),false)) AND (NOT (fields ? 'netloc') OR COALESCE(((jsonb_typeof((fields->'netloc'))='string')),false)) AND (NOT (fields ? 'path') OR COALESCE(((jsonb_typeof((fields->'path'))='string')),false)) AND (NOT (fields ? 'port') OR COALESCE((CASE WHEN jsonb_typeof((fields->'port'))='number' THEN mod(((fields->'port') #>> '{}')::numeric,1)=0 AND abs(((fields->'port') #>> '{}')::numeric)<=9007199254740991 ELSE false END),false)) AND (NOT (fields ? 'render_title') OR COALESCE(((jsonb_typeof((fields->'render_title'))='null' OR ((jsonb_typeof((fields->'render_title'))='string')))),false)) AND (NOT (fields ? 'scheme') OR COALESCE(((jsonb_typeof((fields->'scheme'))='string')),false)) AND (NOT (fields ? 'screenshot_link') OR COALESCE(((jsonb_typeof((fields->'screenshot_link'))='null' OR ((jsonb_typeof((fields->'screenshot_link'))='string')))),false)) AND (NOT (fields ? 'server') OR COALESCE(((jsonb_typeof((fields->'server'))='null' OR ((jsonb_typeof((fields->'server'))='string')))),false)) AND (NOT (fields ? 'status') OR COALESCE(((jsonb_typeof((fields->'status'))='string')),false)) AND (NOT (fields ? 'status_code') OR COALESCE((CASE WHEN jsonb_typeof((fields->'status_code'))='number' THEN mod(((fields->'status_code') #>> '{}')::numeric,1)=0 AND abs(((fields->'status_code') #>> '{}')::numeric)<=9007199254740991 ELSE false END),false)) AND (NOT (fields ? 'tags') OR COALESCE((CASE WHEN jsonb_typeof((fields->'tags'))='array' THEN NOT EXISTS(SELECT 1 FROM jsonb_array_elements((fields->'tags')) AS element14(value) WHERE NOT COALESCE((CASE WHEN jsonb_typeof(element14.value)='object' THEN element14.value ?& ARRAY['pk','name']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(element14.value) AS key15(value) WHERE NOT (key15.value=ANY(ARRAY['name','pk']::text[]))) AND (NOT (element14.value ? 'name') OR COALESCE(((jsonb_typeof((element14.value->'name'))='string')),false)) AND (NOT (element14.value ? 'pk') OR COALESCE(((jsonb_typeof((element14.value->'pk'))='string' AND ((element14.value->'pk') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((element14.value->'pk') #>> '{}')<=100)),false)) ELSE false END),false)) ELSE false END),false)) AND (NOT (fields ? 'title') OR COALESCE(((jsonb_typeof((fields->'title'))='string')),false)) AND (NOT (fields ? 'updated_at') OR COALESCE(((jsonb_typeof((fields->'updated_at'))='string')),false)) AND (NOT (fields ? 'url') OR COALESCE(((jsonb_typeof((fields->'url'))='string')),false)) AND (NOT (fields ? 'x_powered_by') OR COALESCE(((jsonb_typeof((fields->'x_powered_by'))='null' OR ((jsonb_typeof((fields->'x_powered_by'))='string')))),false)) ELSE false END
 WHEN 'appfinger' THEN CASE WHEN jsonb_typeof(fields)='object' THEN fields ?& ARRAY['id','url','scheme','hostname','netloc','path','port','product_name','product_uuid','vendor','vendor_uuid','version','cpe','bu','tags','status','created_at','updated_at','lastseen_at']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(fields) AS key16(value) WHERE NOT (key16.value=ANY(ARRAY['bu','cpe','created_at','hostname','id','lastseen_at','netloc','path','port','product_name','product_uuid','scheme','status','tags','updated_at','url','vendor','vendor_uuid','version']::text[]))) AND (NOT (fields ? 'bu') OR COALESCE((CASE WHEN jsonb_typeof((fields->'bu'))='object' THEN (fields->'bu') ?& ARRAY['id','name']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys((fields->'bu')) AS key17(value) WHERE NOT (key17.value=ANY(ARRAY['id','name']::text[]))) AND (NOT ((fields->'bu') ? 'id') OR COALESCE(((jsonb_typeof(((fields->'bu')->'id'))='string' AND (((fields->'bu')->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length(((fields->'bu')->'id') #>> '{}')<=100)),false)) AND (NOT ((fields->'bu') ? 'name') OR COALESCE(((jsonb_typeof(((fields->'bu')->'name'))='string')),false)) ELSE false END),false)) AND (NOT (fields ? 'cpe') OR COALESCE(((jsonb_typeof((fields->'cpe'))='string')),false)) AND (NOT (fields ? 'created_at') OR COALESCE(((jsonb_typeof((fields->'created_at'))='string')),false)) AND (NOT (fields ? 'hostname') OR COALESCE(((jsonb_typeof((fields->'hostname'))='string')),false)) AND (NOT (fields ? 'id') OR COALESCE(((jsonb_typeof((fields->'id'))='string' AND ((fields->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((fields->'id') #>> '{}')<=100)),false)) AND (NOT (fields ? 'lastseen_at') OR COALESCE(((jsonb_typeof((fields->'lastseen_at'))='string')),false)) AND (NOT (fields ? 'netloc') OR COALESCE(((jsonb_typeof((fields->'netloc'))='string')),false)) AND (NOT (fields ? 'path') OR COALESCE(((jsonb_typeof((fields->'path'))='string')),false)) AND (NOT (fields ? 'port') OR COALESCE((CASE WHEN jsonb_typeof((fields->'port'))='number' THEN mod(((fields->'port') #>> '{}')::numeric,1)=0 AND abs(((fields->'port') #>> '{}')::numeric)<=9007199254740991 ELSE false END),false)) AND (NOT (fields ? 'product_name') OR COALESCE(((jsonb_typeof((fields->'product_name'))='string')),false)) AND (NOT (fields ? 'product_uuid') OR COALESCE(((jsonb_typeof((fields->'product_uuid'))='string')),false)) AND (NOT (fields ? 'scheme') OR COALESCE(((jsonb_typeof((fields->'scheme'))='string')),false)) AND (NOT (fields ? 'status') OR COALESCE(((jsonb_typeof((fields->'status'))='string')),false)) AND (NOT (fields ? 'tags') OR COALESCE((CASE WHEN jsonb_typeof((fields->'tags'))='array' THEN NOT EXISTS(SELECT 1 FROM jsonb_array_elements((fields->'tags')) AS element18(value) WHERE NOT COALESCE((CASE WHEN jsonb_typeof(element18.value)='object' THEN element18.value ?& ARRAY['pk','name']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(element18.value) AS key19(value) WHERE NOT (key19.value=ANY(ARRAY['name','pk']::text[]))) AND (NOT (element18.value ? 'name') OR COALESCE(((jsonb_typeof((element18.value->'name'))='string')),false)) AND (NOT (element18.value ? 'pk') OR COALESCE(((jsonb_typeof((element18.value->'pk'))='string' AND ((element18.value->'pk') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((element18.value->'pk') #>> '{}')<=100)),false)) ELSE false END),false)) ELSE false END),false)) AND (NOT (fields ? 'updated_at') OR COALESCE(((jsonb_typeof((fields->'updated_at'))='string')),false)) AND (NOT (fields ? 'url') OR COALESCE(((jsonb_typeof((fields->'url'))='string')),false)) AND (NOT (fields ? 'vendor') OR COALESCE(((jsonb_typeof((fields->'vendor'))='string')),false)) AND (NOT (fields ? 'vendor_uuid') OR COALESCE(((jsonb_typeof((fields->'vendor_uuid'))='string')),false)) AND (NOT (fields ? 'version') OR COALESCE(((jsonb_typeof((fields->'version'))='string')),false)) ELSE false END
 WHEN 'crawler' THEN CASE WHEN jsonb_typeof(fields)='object' THEN fields ?& ARRAY['id']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(fields) AS key20(value) WHERE NOT (key20.value=ANY(ARRAY['created_at','hostname','id','lastseen_at','method','path','request_type','source','status','target','updated_at','uri']::text[]))) AND (NOT (fields ? 'created_at') OR COALESCE(((jsonb_typeof((fields->'created_at'))='string')),false)) AND (NOT (fields ? 'hostname') OR COALESCE(((jsonb_typeof((fields->'hostname'))='string')),false)) AND (NOT (fields ? 'id') OR COALESCE(((jsonb_typeof((fields->'id'))='string' AND ((fields->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((fields->'id') #>> '{}')<=100)),false)) AND (NOT (fields ? 'lastseen_at') OR COALESCE(((jsonb_typeof((fields->'lastseen_at'))='string')),false)) AND (NOT (fields ? 'method') OR COALESCE(((jsonb_typeof((fields->'method'))='string')),false)) AND (NOT (fields ? 'path') OR COALESCE(((jsonb_typeof((fields->'path'))='string')),false)) AND (NOT (fields ? 'request_type') OR COALESCE(((jsonb_typeof((fields->'request_type'))='string')),false)) AND (NOT (fields ? 'source') OR COALESCE(((jsonb_typeof((fields->'source'))='string')),false)) AND (NOT (fields ? 'status') OR COALESCE(((jsonb_typeof((fields->'status'))='string')),false)) AND (NOT (fields ? 'target') OR COALESCE(((jsonb_typeof((fields->'target'))='string')),false)) AND (NOT (fields ? 'updated_at') OR COALESCE(((jsonb_typeof((fields->'updated_at'))='string')),false)) AND (NOT (fields ? 'uri') OR COALESCE(((jsonb_typeof((fields->'uri'))='string')),false)) ELSE false END
 WHEN 'seed_enterprise' THEN CASE WHEN jsonb_typeof(fields)='object' THEN fields ?& ARRAY['id','confidence','name','created_at','updated_at','equity','investment_path','is_history','enable']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(fields) AS key21(value) WHERE NOT (key21.value=ANY(ARRAY['confidence','created_at','enable','equity','id','investment_path','is_history','name','updated_at']::text[]))) AND (NOT (fields ? 'confidence') OR COALESCE(((jsonb_typeof((fields->'confidence'))='string' AND ((fields->'confidence') #>> '{}')=ANY(ARRAY['60','100']::text[]))),false)) AND (NOT (fields ? 'created_at') OR COALESCE(((jsonb_typeof((fields->'created_at'))='string')),false)) AND (NOT (fields ? 'enable') OR COALESCE(((jsonb_typeof((fields->'enable'))='boolean')),false)) AND (NOT (fields ? 'equity') OR COALESCE((CASE WHEN jsonb_typeof((fields->'equity'))='number' THEN mod(((fields->'equity') #>> '{}')::numeric,1)=0 AND abs(((fields->'equity') #>> '{}')::numeric)<=9007199254740991 ELSE false END),false)) AND (NOT (fields ? 'id') OR COALESCE(((jsonb_typeof((fields->'id'))='string' AND ((fields->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((fields->'id') #>> '{}')<=100)),false)) AND (NOT (fields ? 'investment_path') OR COALESCE(((jsonb_typeof((fields->'investment_path'))='string')),false)) AND (NOT (fields ? 'is_history') OR COALESCE(((jsonb_typeof((fields->'is_history'))='boolean')),false)) AND (NOT (fields ? 'name') OR COALESCE(((jsonb_typeof((fields->'name'))='string')),false)) AND (NOT (fields ? 'updated_at') OR COALESCE(((jsonb_typeof((fields->'updated_at'))='string')),false)) ELSE false END
 WHEN 'seed_keyword' THEN CASE WHEN jsonb_typeof(fields)='object' THEN fields ?& ARRAY['id']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(fields) AS key22(value) WHERE NOT (key22.value=ANY(ARRAY['confidence','created_at','enable','id','name','type','updated_at']::text[]))) AND (NOT (fields ? 'confidence') OR COALESCE(((jsonb_typeof((fields->'confidence'))='string' AND ((fields->'confidence') #>> '{}')=ANY(ARRAY['60','100']::text[]))),false)) AND (NOT (fields ? 'created_at') OR COALESCE(((jsonb_typeof((fields->'created_at'))='string')),false)) AND (NOT (fields ? 'enable') OR COALESCE(((jsonb_typeof((fields->'enable'))='boolean')),false)) AND (NOT (fields ? 'id') OR COALESCE(((jsonb_typeof((fields->'id'))='string' AND ((fields->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((fields->'id') #>> '{}')<=100)),false)) AND (NOT (fields ? 'name') OR COALESCE(((jsonb_typeof((fields->'name'))='string')),false)) AND (NOT (fields ? 'type') OR COALESCE(((jsonb_typeof((fields->'type'))='string' AND ((fields->'type') #>> '{}')=ANY(ARRAY['品牌标识','业务系统']::text[]))),false)) AND (NOT (fields ? 'updated_at') OR COALESCE(((jsonb_typeof((fields->'updated_at'))='string')),false)) ELSE false END
 WHEN 'seed_domain' THEN CASE WHEN jsonb_typeof(fields)='object' THEN fields ?& ARRAY['id']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(fields) AS key23(value) WHERE NOT (key23.value=ANY(ARRAY['confidence','created_at','enable','id','name','type','updated_at']::text[]))) AND (NOT (fields ? 'confidence') OR COALESCE(((jsonb_typeof((fields->'confidence'))='string')),false)) AND (NOT (fields ? 'created_at') OR COALESCE(((jsonb_typeof((fields->'created_at'))='string')),false)) AND (NOT (fields ? 'enable') OR COALESCE(((jsonb_typeof((fields->'enable'))='boolean')),false)) AND (NOT (fields ? 'id') OR COALESCE(((jsonb_typeof((fields->'id'))='string' AND ((fields->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((fields->'id') #>> '{}')<=100)),false)) AND (NOT (fields ? 'name') OR COALESCE(((jsonb_typeof((fields->'name'))='string')),false)) AND (NOT (fields ? 'type') OR COALESCE(((jsonb_typeof((fields->'type'))='string' AND ((fields->'type') #>> '{}')=ANY(ARRAY['NS','MX','注册邮箱']::text[]))),false)) AND (NOT (fields ? 'updated_at') OR COALESCE(((jsonb_typeof((fields->'updated_at'))='string')),false)) ELSE false END
 WHEN 'seed_email' THEN CASE WHEN jsonb_typeof(fields)='object' THEN fields ?& ARRAY['id']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(fields) AS key24(value) WHERE NOT (key24.value=ANY(ARRAY['confidence','created_at','enable','id','name','updated_at']::text[]))) AND (NOT (fields ? 'confidence') OR COALESCE(((jsonb_typeof((fields->'confidence'))='string' AND ((fields->'confidence') #>> '{}')=ANY(ARRAY['60','100']::text[]))),false)) AND (NOT (fields ? 'created_at') OR COALESCE(((jsonb_typeof((fields->'created_at'))='string')),false)) AND (NOT (fields ? 'enable') OR COALESCE(((jsonb_typeof((fields->'enable'))='boolean')),false)) AND (NOT (fields ? 'id') OR COALESCE(((jsonb_typeof((fields->'id'))='string' AND ((fields->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((fields->'id') #>> '{}')<=100)),false)) AND (NOT (fields ? 'name') OR COALESCE(((jsonb_typeof((fields->'name'))='string')),false)) AND (NOT (fields ? 'updated_at') OR COALESCE(((jsonb_typeof((fields->'updated_at'))='string')),false)) ELSE false END
 WHEN 'seed_cert' THEN CASE WHEN jsonb_typeof(fields)='object' THEN fields ?& ARRAY['id']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(fields) AS key25(value) WHERE NOT (key25.value=ANY(ARRAY['confidence','created_at','enable','id','name','type','updated_at']::text[]))) AND (NOT (fields ? 'confidence') OR COALESCE(((jsonb_typeof((fields->'confidence'))='string')),false)) AND (NOT (fields ? 'created_at') OR COALESCE(((jsonb_typeof((fields->'created_at'))='string')),false)) AND (NOT (fields ? 'enable') OR COALESCE(((jsonb_typeof((fields->'enable'))='boolean')),false)) AND (NOT (fields ? 'id') OR COALESCE(((jsonb_typeof((fields->'id'))='string' AND ((fields->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((fields->'id') #>> '{}')<=100)),false)) AND (NOT (fields ? 'name') OR COALESCE(((jsonb_typeof((fields->'name'))='string')),false)) AND (NOT (fields ? 'type') OR COALESCE(((jsonb_typeof((fields->'type'))='string' AND ((fields->'type') #>> '{}')=ANY(ARRAY['O','OU']::text[]))),false)) AND (NOT (fields ? 'updated_at') OR COALESCE(((jsonb_typeof((fields->'updated_at'))='string')),false)) ELSE false END
 WHEN 'seed_icon' THEN CASE WHEN jsonb_typeof(fields)='object' THEN fields ?& ARRAY['id']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(fields) AS key26(value) WHERE NOT (key26.value=ANY(ARRAY['confidence','created_at','enable','icon_url','id','md5_value','mmh3_value','updated_at']::text[]))) AND (NOT (fields ? 'confidence') OR COALESCE(((jsonb_typeof((fields->'confidence'))='string')),false)) AND (NOT (fields ? 'created_at') OR COALESCE(((jsonb_typeof((fields->'created_at'))='string')),false)) AND (NOT (fields ? 'enable') OR COALESCE(((jsonb_typeof((fields->'enable'))='boolean')),false)) AND (NOT (fields ? 'icon_url') OR COALESCE(((jsonb_typeof((fields->'icon_url'))='null' OR ((jsonb_typeof((fields->'icon_url'))='string')))),false)) AND (NOT (fields ? 'id') OR COALESCE(((jsonb_typeof((fields->'id'))='string' AND ((fields->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((fields->'id') #>> '{}')<=100)),false)) AND (NOT (fields ? 'md5_value') OR COALESCE(((jsonb_typeof((fields->'md5_value'))='null' OR ((jsonb_typeof((fields->'md5_value'))='string')))),false)) AND (NOT (fields ? 'mmh3_value') OR COALESCE(((jsonb_typeof((fields->'mmh3_value'))='null' OR ((jsonb_typeof((fields->'mmh3_value'))='string')))),false)) AND (NOT (fields ? 'updated_at') OR COALESCE(((jsonb_typeof((fields->'updated_at'))='string')),false)) ELSE false END
 WHEN 'seed_title' THEN CASE WHEN jsonb_typeof(fields)='object' THEN fields ?& ARRAY['id']::text[] AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(fields) AS key27(value) WHERE NOT (key27.value=ANY(ARRAY['confidence','created_at','enable','id','name','type','updated_at']::text[]))) AND (NOT (fields ? 'confidence') OR COALESCE(((jsonb_typeof((fields->'confidence'))='string')),false)) AND (NOT (fields ? 'created_at') OR COALESCE(((jsonb_typeof((fields->'created_at'))='string')),false)) AND (NOT (fields ? 'enable') OR COALESCE(((jsonb_typeof((fields->'enable'))='boolean')),false)) AND (NOT (fields ? 'id') OR COALESCE(((jsonb_typeof((fields->'id'))='string' AND ((fields->'id') #>> '{}') ~ '^-?(0|[1-9][0-9]*)$' AND length((fields->'id') #>> '{}')<=100)),false)) AND (NOT (fields ? 'name') OR COALESCE(((jsonb_typeof((fields->'name'))='string')),false)) AND (NOT (fields ? 'type') OR COALESCE(((jsonb_typeof((fields->'type'))='string' AND ((fields->'type') #>> '{}')=ANY(ARRAY['full','like']::text[]))),false)) AND (NOT (fields ? 'updated_at') OR COALESCE(((jsonb_typeof((fields->'updated_at'))='string')),false)) ELSE false END
 ELSE false END,false)
$$;
CREATE FUNCTION valid_lossless_external_structured_record(document json, domain_name text, source_id text)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT valid_external_structured_fields(external_asset_json_nul_copy(document,1),domain_name,source_id)
    AND valid_external_structured_fields(external_asset_json_nul_copy(document,2),domain_name,source_id)
$$;
CREATE FUNCTION external_asset_search_segments(document jsonb, field_name text)
RETURNS text[] LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT CASE WHEN jsonb_typeof(document->field_name)='array'
             THEN ARRAY(SELECT jsonb_array_elements_text(document->field_name)) END
$$;
CREATE FUNCTION project_external_asset_search() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE first_copy jsonb; second_copy jsonb; key text; segments text[]; expected_enable boolean;
BEGIN
 first_copy := external_asset_json_nul_copy(NEW.fields,1);
 second_copy := external_asset_json_nul_copy(NEW.fields,2);
 IF jsonb_typeof(NEW.search_fields) IS DISTINCT FROM 'object' THEN
   RAISE EXCEPTION 'External search projection must be an object';
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_object_keys(NEW.search_fields) AS k WHERE NOT k=ANY(ARRAY['cn_name','confidence','cpe','hostname','md5_value','mmh3_value','name','path','product_name','render_title','sha256','subdomain','target','title','type','uri','url','vendor','version']::text[])) THEN
   RAISE EXCEPTION 'Unexpected external search projection';
 END IF;
 FOREACH key IN ARRAY ARRAY['cn_name','confidence','cpe','hostname','md5_value','mmh3_value','name','path','product_name','render_title','sha256','subdomain','target','title','type','uri','url','vendor','version']::text[] LOOP
   IF jsonb_typeof(first_copy->key)='string' THEN
     IF NOT (NEW.search_fields ? key) AND first_copy->key IS NOT DISTINCT FROM second_copy->key THEN
       NEW.search_fields := NEW.search_fields || jsonb_build_object(key,jsonb_build_array(first_copy->key));
     END IF;
     IF jsonb_typeof(NEW.search_fields->key) IS DISTINCT FROM 'array' THEN
       RAISE EXCEPTION 'External search projection mismatch';
     END IF;
     IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.search_fields->key) AS x WHERE jsonb_typeof(x) IS DISTINCT FROM 'string') THEN
       RAISE EXCEPTION 'External search projection mismatch';
     END IF;
     segments := external_asset_search_segments(NEW.search_fields,key);
     IF NOT external_asset_projection_matches(first_copy->>key,second_copy->>key,segments) THEN
       RAISE EXCEPTION 'External search projection mismatch';
     END IF;
   ELSIF NEW.search_fields ? key THEN
     RAISE EXCEPTION 'External search projection mismatch';
   END IF;
 END LOOP;
 expected_enable := CASE WHEN jsonb_typeof(first_copy->'enable')='boolean' THEN (first_copy->>'enable')::boolean END;
 IF NEW.enable_value IS NULL THEN NEW.enable_value := expected_enable; END IF;
 IF NEW.enable_value IS DISTINCT FROM expected_enable THEN RAISE EXCEPTION 'External enabled projection mismatch'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ab_project_external_asset_search BEFORE INSERT OR UPDATE ON external_asset_records
 FOR EACH ROW EXECUTE FUNCTION project_external_asset_search();
"""

SOURCE_SYNC_GUARDS = r"""
CREATE FUNCTION guard_external_structured_source() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (external_structured_domain(OLD.capability_profile) IS NOT NULL OR external_structured_domain(NEW.capability_profile) IS NOT NULL)
    AND (NEW.source_type,NEW.capability_profile) IS DISTINCT FROM (OLD.source_type,OLD.capability_profile) THEN
   RAISE EXCEPTION 'External structured source contract is immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_external_structured_source BEFORE UPDATE ON source_instances
 FOR EACH ROW EXECUTE FUNCTION guard_external_structured_source();
CREATE FUNCTION guard_external_structured_sync() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE profile text; domain_name text;
BEGIN
 SELECT capability_profile INTO profile FROM source_instances WHERE id=NEW.source_id;
 domain_name := external_structured_domain(profile);
 IF (domain_name IS NOT NULL) IS DISTINCT FROM (COALESCE(NEW.request->>'publication_mode','')='structured-bounded-v1') THEN
   RAISE EXCEPTION 'External structured sync source mismatch';
 END IF;
 IF domain_name IS NOT NULL AND (
   (NEW.request->>'domain',NEW.request->>'capability_profile',NEW.request->>'sort') IS DISTINCT FROM (domain_name,profile,'-id')
   OR NEW.request->'filters' IS DISTINCT FROM external_structured_filters(domain_name)) THEN
   RAISE EXCEPTION 'External structured request scope mismatch';
 END IF;
 IF TG_OP='UPDATE' AND (domain_name IS NOT NULL OR OLD.request->>'publication_mode'='structured-bounded-v1') AND
   (NEW.source_id,NEW.project_id,NEW.actor_id,NEW.idempotency_key,NEW.request_sha256,NEW.request,NEW.fingerprint,NEW.token_sha256,NEW.agent_run_id,NEW.agent_project_id,NEW.retain_until)
   IS DISTINCT FROM
   (OLD.source_id,OLD.project_id,OLD.actor_id,OLD.idempotency_key,OLD.request_sha256,OLD.request,OLD.fingerprint,OLD.token_sha256,OLD.agent_run_id,OLD.agent_project_id,OLD.retain_until) THEN
   RAISE EXCEPTION 'External structured sync contract is immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_external_structured_sync BEFORE INSERT OR UPDATE ON external_syncs
 FOR EACH ROW EXECUTE FUNCTION guard_external_structured_sync();
"""

VERSION_RULES = r"""

          IF NEW.domain IN ('subdomain','cert','openport','web','dir','appfinger','crawler','seed_enterprise','seed_keyword','seed_domain','seed_email','seed_cert','seed_icon','seed_title') OR
             (SELECT external_structured_domain(s.capability_profile) FROM source_instances s WHERE s.id=NEW.source_id) IS NOT NULL THEN
            IF NOT EXISTS (
              SELECT 1 FROM external_syncs t JOIN source_instances s ON s.id=t.source_id
              WHERE t.id=NEW.sync_id AND s.id=NEW.source_id
                AND NEW.domain=external_structured_domain(s.capability_profile)
                AND t.request->>'publication_mode'='structured-bounded-v1'
                AND t.request->>'domain'=NEW.domain AND t.request->>'capability_profile'=s.capability_profile
                AND t.request->>'sort'='-id' AND t.request->'filters'=external_structured_filters(NEW.domain)
                AND (NEW.space_id,NEW.instance_id,NEW.capset_id,NEW.fingerprint,NEW.retain_until)
                    IS NOT DISTINCT FROM (s.space_id,s.instance_id,s.capset_id,t.fingerprint,t.retain_until)
                AND NEW.filter=external_structured_filters(NEW.domain) AND NEW.sort='-id'
            ) THEN RAISE EXCEPTION 'External structured version scope mismatch'; END IF;
            IF NEW.status='PUBLISHED' AND (NEW.omitted_field_count IS NULL OR NEW.omitted_field_count < 0
               OR NEW.omitted_field_count > NEW.pages_read::bigint * (SELECT (request->>'max_response_bytes')::bigint FROM external_syncs WHERE id=NEW.sync_id)) THEN
              RAISE EXCEPTION 'External structured field coverage metadata is invalid';
            END IF;
          END IF;
"""

RECORD_RULES = r"""
          ELSIF record_domain IN ('subdomain','cert','openport','web','dir','appfinger','crawler','seed_enterprise','seed_keyword','seed_domain','seed_email','seed_cert','seed_icon','seed_title') THEN
            IF expiry <= CURRENT_TIMESTAMP OR NOT valid_lossless_external_structured_record(NEW.fields,record_domain,NEW.source_id) THEN
              RAISE EXCEPTION 'External structured record is invalid';
            END IF;
            IF record_domain='openport' THEN
              IF NEW.ip IS NULL OR NEW.canonical_ip IS NULL OR NEW.ip IS DISTINCT FROM external_asset_json_nul_copy(NEW.fields,1)->>'ip'
                 OR position('%' in NEW.ip)>0 OR position('/' in NEW.ip)>0
                 OR NEW.ip::inet IS DISTINCT FROM NEW.canonical_ip::inet
                 OR (external_asset_json_nul_copy(NEW.fields,1)->>'port')::numeric NOT BETWEEN 0 AND 65535 THEN
                RAISE EXCEPTION 'External open port address is invalid';
              END IF;
            ELSIF NEW.ip IS NOT NULL OR NEW.canonical_ip IS NOT NULL THEN
              RAISE EXCEPTION 'External structured record does not have an IP identity';
            END IF;
"""


def _patch(name, changes, reverse=False):
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_functiondef(CAST(:name AS regproc))"), {"name": name}
    )
    if not isinstance(definition, str):
        raise RuntimeError("Missing external guard")
    for old, new in changes:
        if reverse:
            old, new = new, old
        if old not in definition:
            raise RuntimeError("Unexpected external guard definition")
        definition = definition.replace(old, new)
    op.execute(definition)


def _guards(reverse=False):
    domains = ",".join(repr(x) for x in NEW_DOMAINS)
    _patch(
        "guard_external_version",
        [
            (
                "          IF NEW.status = 'PUBLISHED' THEN",
                VERSION_RULES + "          IF NEW.status = 'PUBLISHED' THEN",
            ),
            (
                "root_source OR NEW.domain = 'dns'",
                "root_source OR NEW.domain = 'dns' OR NEW.domain IN (" + domains + ")",
            ),
            (
                "WHEN NEW.domain = 'dns' THEN 'dns-bounded-v1' ELSE",
                "WHEN NEW.domain = 'dns' THEN 'dns-bounded-v1' WHEN NEW.domain IN ("
                + domains
                + ") THEN 'structured-bounded-v1' ELSE",
            ),
        ],
        reverse,
    )
    _patch(
        "guard_external_version",
        [
            (
                "(NEW.pages_read, NEW.stop_reason, NEW.record_count, NEW.expected_total, NEW.complete)",
                "(NEW.pages_read, NEW.stop_reason, NEW.record_count, NEW.expected_total, NEW.complete, NEW.omitted_field_count)",
            ),
            (
                "(OLD.pages_read, OLD.stop_reason, OLD.record_count, OLD.expected_total, OLD.complete)",
                "(OLD.pages_read, OLD.stop_reason, OLD.record_count, OLD.expected_total, OLD.complete, OLD.omitted_field_count)",
            ),
        ],
        reverse,
    )
    _patch(
        "guard_external_record",
        [
            (
                "          ELSIF NEW.ip IS NULL OR NEW.canonical_ip IS NULL THEN",
                RECORD_RULES
                + "          ELSIF NEW.ip IS NULL OR NEW.canonical_ip IS NULL THEN",
            )
        ],
        reverse,
    )


def _constraints(new):
    op.drop_constraint("ck_source_instances_type", "source_instances", type_="check")
    op.create_check_constraint(
        "ck_source_instances_type", "source_instances", NEW_TYPES if new else OLD_TYPES
    )
    op.drop_constraint("ck_source_instances_profile", "source_instances", type_="check")
    op.create_check_constraint(
        "ck_source_instances_profile",
        "source_instances",
        NEW_PROFILE_RULE if new else OLD_PROFILES,
    )
    op.drop_constraint(
        "ck_external_version_domain", "external_asset_versions", type_="check"
    )
    domains = ["ip", "port", "root_domain", "dns"] + (NEW_DOMAINS if new else [])
    op.create_check_constraint(
        "ck_external_version_domain",
        "external_asset_versions",
        "domain IN (" + ",".join(repr(x) for x in domains) + ")",
    )


def upgrade():
    op.add_column(
        "external_asset_versions",
        sa.Column("omitted_field_count", sa.BigInteger(), nullable=True),
    )
    op.create_check_constraint(
        "ck_external_version_omitted_fields",
        "external_asset_versions",
        "omitted_field_count IS NULL OR omitted_field_count >= 0",
    )
    op.add_column(
        "external_asset_records",
        sa.Column(
            "search_fields",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "external_asset_records", sa.Column("enable_value", sa.Boolean(), nullable=True)
    )
    connection = op.get_bind()
    mode = connection.scalar(
        sa.text(
            "SELECT tgenabled FROM pg_trigger WHERE tgrelid='external_asset_records'::regclass AND tgname='guard_external_record'"
        )
    )
    if mode not in ("O", "A", "R"):
        raise RuntimeError("Expected enabled immutable record guard")
    # ALTER holds an exclusive lock. Decode only in Python so true NUL remains
    # intact; old JSON text and the three old projections are never rewritten.
    op.execute(
        "ALTER TABLE external_asset_records DISABLE TRIGGER guard_external_record"
    )
    cursor = connection.execute(sa.text("SELECT id,fields FROM external_asset_records"))
    while rows := cursor.fetchmany(500):
        values = []
        for identity, fields in rows:
            values.append(
                {
                    "id": identity,
                    "search": json.dumps(
                        {
                            k: fields[k].split(chr(0))
                            for k in SEARCH_FIELDS
                            if isinstance(fields.get(k), str)
                        },
                        ensure_ascii=True,
                    ),
                    "enabled": fields.get("enable")
                    if type(fields.get("enable")) is bool
                    else None,
                }
            )
        connection.execute(
            sa.text(
                "UPDATE external_asset_records SET search_fields=CAST(:search AS jsonb),enable_value=:enabled WHERE id=:id"
            ),
            values,
        )
    enabled = {"O": "ENABLE", "A": "ENABLE ALWAYS", "R": "ENABLE REPLICA"}[mode]
    op.execute(
        f"ALTER TABLE external_asset_records {enabled} TRIGGER guard_external_record"
    )
    _constraints(True)
    op.execute(HELPERS)
    op.execute(SOURCE_SYNC_GUARDS)
    _guards()


def downgrade():
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM source_instances WHERE capability_profile=ANY(:profiles))"
        ),
        {"profiles": NEW_PROFILES},
    ) or connection.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM external_asset_versions WHERE domain=ANY(:domains))"
        ),
        {"domains": NEW_DOMAINS},
    ):
        raise RuntimeError(
            "Cannot downgrade while structured source or version history exists"
        )
    _guards(True)
    op.execute("DROP TRIGGER guard_external_structured_source ON source_instances")
    op.execute("DROP TRIGGER guard_external_structured_sync ON external_syncs")
    op.execute("DROP FUNCTION guard_external_structured_source()")
    op.execute("DROP FUNCTION guard_external_structured_sync()")
    op.execute(
        "DROP TRIGGER ab_project_external_asset_search ON external_asset_records"
    )
    op.execute("DROP FUNCTION project_external_asset_search()")
    op.execute("DROP FUNCTION external_asset_search_segments(jsonb,text)")
    op.execute(
        "DROP FUNCTION valid_lossless_external_structured_record(json,text,text)"
    )
    op.execute("DROP FUNCTION valid_external_structured_fields(jsonb,text,text)")
    op.execute("DROP FUNCTION external_structured_filters(text)")
    op.execute("DROP FUNCTION external_structured_domain(text)")
    op.drop_constraint(
        "ck_external_version_omitted_fields", "external_asset_versions", type_="check"
    )
    op.drop_column("external_asset_versions", "omitted_field_count")
    _constraints(False)
    op.drop_column("external_asset_records", "enable_value")
    op.drop_column("external_asset_records", "search_fields")
