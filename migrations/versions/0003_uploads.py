"""Durable multipart upload identities and request responses."""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""
        CREATE TABLE uploads (
            id uuid PRIMARY KEY,
            dataset_id uuid NOT NULL REFERENCES datasets(id),
            role text NOT NULL CHECK (role IN ('users','events')),
            filename text NOT NULL CHECK (length(filename) BETWEEN 1 AND 255),
            format text NOT NULL CHECK (format IN ('csv','parquet')),
            expected_size bigint NOT NULL CHECK (expected_size > 0),
            expected_sha256 text NOT NULL CHECK (expected_sha256 ~ '^[0-9a-f]{64}$'),
            part_size bigint NOT NULL CHECK (part_size >= 5242880 AND part_size <= 5368709120),
            part_count integer NOT NULL CHECK (part_count BETWEEN 1 AND 10000),
            object_key text NOT NULL UNIQUE,
            multipart_id text,
            status text NOT NULL DEFAULT 'uploading'
                CHECK (status IN ('uploading','completed','failed','aborted')),
            verified_manifest jsonb,
            error_code text,
            created_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz,
            CHECK (part_count = ceil(expected_size::numeric / part_size)::integer),
            CHECK (status <> 'completed' OR (verified_manifest IS NOT NULL AND completed_at IS NOT NULL))
        );
        CREATE INDEX uploads_dataset ON uploads(dataset_id, created_at);
        CREATE TABLE api_requests (
            scope text NOT NULL,
            key text NOT NULL,
            request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
            response jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(scope, key)
        );
        CREATE FUNCTION protect_upload() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE sealed timestamptz;
        BEGIN
            IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Upload history cannot be deleted'; END IF;
            SELECT sealed_at INTO sealed FROM datasets WHERE id=NEW.dataset_id FOR UPDATE;
            IF sealed IS NOT NULL THEN RAISE EXCEPTION 'Dataset is sealed'; END IF;
            IF TG_OP = 'UPDATE' THEN
                IF OLD.status IN ('completed','aborted') AND NEW IS DISTINCT FROM OLD THEN
                    RAISE EXCEPTION 'Completed upload is immutable';
                END IF;
                IF (NEW.id,NEW.dataset_id,NEW.role,NEW.filename,NEW.format,NEW.expected_size,
                    NEW.expected_sha256,NEW.part_size,NEW.part_count,NEW.object_key,NEW.created_at)
                    IS DISTINCT FROM
                   (OLD.id,OLD.dataset_id,OLD.role,OLD.filename,OLD.format,OLD.expected_size,
                    OLD.expected_sha256,OLD.part_size,OLD.part_count,OLD.object_key,OLD.created_at) THEN
                    RAISE EXCEPTION 'Upload identity is immutable';
                END IF;
                IF OLD.multipart_id IS NOT NULL AND NEW.multipart_id IS DISTINCT FROM OLD.multipart_id THEN
                    RAISE EXCEPTION 'Multipart identity is immutable';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER upload_guard BEFORE INSERT OR UPDATE OR DELETE ON uploads
            FOR EACH ROW EXECUTE FUNCTION protect_upload();
    """)

def downgrade():
    raise RuntimeError("Destructive downgrade disabled")
