"""Immutable, fenced baseline stage checkpoints backed by object storage."""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE stage_checkpoints (
            run_id uuid NOT NULL REFERENCES runs(id),
            stage text NOT NULL CHECK (stage ~ '^[a-z][a-z0-9_]{0,63}$'),
            stage_version text NOT NULL,
            input_sha256 text NOT NULL CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
            attempt_id uuid NOT NULL,
            fence bigint NOT NULL CHECK (fence > 0),
            manifest jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (run_id, stage, stage_version, input_sha256),
            FOREIGN KEY (attempt_id, run_id) REFERENCES job_attempts(id, run_id)
        );
        CREATE FUNCTION protect_checkpoint() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Stage checkpoints are immutable'; END $$;
        CREATE TRIGGER checkpoint_guard BEFORE UPDATE OR DELETE ON stage_checkpoints
            FOR EACH ROW EXECUTE FUNCTION protect_checkpoint();
    """)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled")
