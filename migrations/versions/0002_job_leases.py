"""Lease limits, retry timing and attempt completion state."""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""
        ALTER TABLE jobs ADD COLUMN max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0);
        ALTER TABLE jobs ADD COLUMN available_at timestamptz NOT NULL DEFAULT now();
        ALTER TABLE job_attempts ADD COLUMN outcome text
            CHECK (outcome IN ('succeeded','failed','cancelled','expired'));
        ALTER TABLE runs ADD COLUMN request_hash text CHECK (request_hash ~ '^[0-9a-f]{64}$');
        CREATE FUNCTION protect_request_hash() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.request_hash IS DISTINCT FROM OLD.request_hash THEN
                RAISE EXCEPTION 'Request identity is immutable';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER request_hash_guard BEFORE UPDATE ON runs
            FOR EACH ROW EXECUTE FUNCTION protect_request_hash();
    """)

def downgrade():
    raise RuntimeError("Destructive downgrade disabled")
