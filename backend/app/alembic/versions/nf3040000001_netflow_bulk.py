"""Add versioned NetFlow bulk metadata and query projections.

Revision: nf3040000001; only additive tables and widening counts.
"""
from alembic import op

revision = "nf3040000001"
down_revision = "ai2980000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""

CREATE TABLE netflow_bulk_datasets (
	dataset_id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	source_id VARCHAR(64) NOT NULL,
	ready_id VARCHAR(64) NOT NULL,
	manifest JSONB NOT NULL,
	normalizer VARCHAR(64) NOT NULL,
	complete BOOLEAN NOT NULL,
	invalidated BOOLEAN NOT NULL,
	PRIMARY KEY (dataset_id),
	FOREIGN KEY(dataset_id, project_id, tenant_id) REFERENCES netflow_datasets (id, project_id, tenant_id) ON DELETE RESTRICT,
	CONSTRAINT uq_bulk_ready UNIQUE (tenant_id, project_id, source_id, ready_id)
)

;
CREATE INDEX ix_netflow_bulk_datasets_project_id ON netflow_bulk_datasets (project_id);

CREATE TABLE netflow_bulk_members (
	dataset_id UUID NOT NULL,
	file_id VARCHAR(64) NOT NULL,
	complete BOOLEAN NOT NULL,
	raw_count BIGINT NOT NULL,
	invalid_count BIGINT NOT NULL,
	byte_size BIGINT NOT NULL,
	shard_count INTEGER NOT NULL,
	PRIMARY KEY (dataset_id, file_id),
	FOREIGN KEY(dataset_id) REFERENCES netflow_bulk_datasets (dataset_id) ON DELETE RESTRICT
)

;

CREATE TABLE netflow_bulk_shards (
	dataset_id UUID NOT NULL,
	file_id VARCHAR(64) NOT NULL,
	ordinal INTEGER NOT NULL,
	storage_key VARCHAR(1024) NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	size BIGINT NOT NULL,
	first_row BIGINT NOT NULL,
	last_row BIGINT NOT NULL,
	rows BIGINT NOT NULL,
	invalid BIGINT NOT NULL,
	PRIMARY KEY (dataset_id, file_id, ordinal),
	FOREIGN KEY(dataset_id, file_id) REFERENCES netflow_bulk_members (dataset_id, file_id) ON DELETE RESTRICT,
	CONSTRAINT ck_bulk_shard_counts CHECK (first_row > 0 AND last_row >= first_row AND rows = last_row-first_row+1 AND invalid >= 0 AND invalid <= rows)
)

;

CREATE TABLE netflow_bulk_jobs (
	analysis_id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	dataset_id UUID NOT NULL,
	fence INTEGER NOT NULL,
	lease_until TIMESTAMP WITH TIME ZONE,
	heartbeat_at TIMESTAMP WITH TIME ZONE,
	cancel_requested BOOLEAN NOT NULL,
	invalidated BOOLEAN NOT NULL,
	phase VARCHAR(32) NOT NULL,
	selection JSONB NOT NULL,
	metrics JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (analysis_id),
	FOREIGN KEY(analysis_id, project_id, tenant_id) REFERENCES netflow_analyses (id, project_id, tenant_id) ON DELETE RESTRICT,
	CONSTRAINT ck_bulk_fence CHECK (fence >= 0),
	FOREIGN KEY(dataset_id) REFERENCES netflow_bulk_datasets (dataset_id) ON DELETE RESTRICT
)

;
CREATE INDEX ix_bulk_lease ON netflow_bulk_jobs (lease_until);
CREATE INDEX ix_netflow_bulk_jobs_dataset_id ON netflow_bulk_jobs (dataset_id);

CREATE TABLE netflow_bulk_objects (
	analysis_id UUID NOT NULL,
	object_key VARCHAR(64) NOT NULL,
	ip VARCHAR(45) NOT NULL,
	family INTEGER NOT NULL,
	ip_sort VARCHAR(32) NOT NULL,
	protocol INTEGER NOT NULL,
	port INTEGER,
	record_count BIGINT NOT NULL,
	start_us BIGINT,
	end_us BIGINT,
	PRIMARY KEY (analysis_id, object_key),
	CONSTRAINT ck_bulk_object_count CHECK (record_count >= 0 AND family IN (4,6)),
	FOREIGN KEY(analysis_id) REFERENCES netflow_bulk_jobs (analysis_id) ON DELETE RESTRICT
)

;
CREATE INDEX ix_bulk_object_filter ON netflow_bulk_objects (analysis_id, ip, protocol, port);
CREATE INDEX ix_bulk_object_page ON netflow_bulk_objects (analysis_id, family, ip_sort, object_key);

CREATE TABLE netflow_bulk_addresses (
	analysis_id UUID NOT NULL,
	ip VARCHAR(45) NOT NULL,
	family INTEGER NOT NULL,
	ip_sort VARCHAR(32) NOT NULL,
	observation_count BIGINT NOT NULL,
	record_count BIGINT NOT NULL,
	PRIMARY KEY (analysis_id, ip),
	FOREIGN KEY(analysis_id) REFERENCES netflow_bulk_jobs (analysis_id) ON DELETE RESTRICT
)

;
CREATE INDEX ix_bulk_address_page ON netflow_bulk_addresses (analysis_id, family, ip_sort);
""")
    for column in ("byte_size", "raw_record_count", "activity_valid_record_count", "isolated_record_count", "duplicate_group_count", "duplicate_record_count"):
        op.execute(f"ALTER TABLE netflow_datasets ALTER COLUMN {column} TYPE BIGINT")


def downgrade() -> None:
    raise RuntimeError("Bulk evidence is retained; roll back application with bulk disabled, not by deleting shared history")
