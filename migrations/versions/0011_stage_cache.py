"""Content-keyed immutable references to committed stage checkpoints."""
from alembic import op
revision='0011'
down_revision='0010'
branch_labels=None
depends_on=None


def upgrade():
    op.execute("""
      CREATE TABLE analysis_stage_cache (
        cache_key text PRIMARY KEY CHECK(cache_key ~ '^[a-f0-9]{64}$'),
        identity jsonb NOT NULL,
        source_run_id uuid NOT NULL,
        stage text NOT NULL,
        stage_version text NOT NULL,
        input_sha256 text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        FOREIGN KEY(source_run_id,stage,stage_version,input_sha256)
          REFERENCES stage_checkpoints(run_id,stage,stage_version,input_sha256)
      );
      CREATE TRIGGER analysis_stage_cache_immutable BEFORE UPDATE OR DELETE ON analysis_stage_cache
        FOR EACH ROW EXECUTE FUNCTION protect_checkpoint();
    """)


def downgrade():raise RuntimeError('Destructive downgrade disabled')
