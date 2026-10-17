"""Persist runtime identity, consumed model steps and public response checkpoints."""
from alembic import op
revision='0017'
down_revision='0016'
branch_labels=None
depends_on=None


def upgrade():
    op.execute('''CREATE TABLE agent_runtime_sessions (
      turn_id uuid PRIMARY KEY REFERENCES agent_turns(id),
      config jsonb NOT NULL CHECK(jsonb_typeof(config)='object'),
      config_sha256 text NOT NULL CHECK(config_sha256 ~ '^[0-9a-f]{64}$'),
      max_steps integer NOT NULL CHECK(max_steps BETWEEN 1 AND 20),
      deadline timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE TABLE agent_model_steps (
      turn_id uuid NOT NULL REFERENCES agent_runtime_sessions(turn_id),
      ordinal integer NOT NULL CHECK(ordinal BETWEEN 1 AND 20),
      request_id uuid NOT NULL, fence integer NOT NULL CHECK(fence>0),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY(turn_id,ordinal), UNIQUE(turn_id,request_id)
    );
    CREATE TABLE agent_step_results (
      turn_id uuid NOT NULL, ordinal integer NOT NULL,
      messages jsonb NOT NULL CHECK(jsonb_typeof(messages)='array'),
      usage jsonb NOT NULL CHECK(jsonb_typeof(usage)='object'),
      finish_reason text NOT NULL,
      snapshot_sha256 text NOT NULL CHECK(snapshot_sha256 ~ '^[0-9a-f]{64}$'),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY(turn_id,ordinal),
      FOREIGN KEY(turn_id,ordinal) REFERENCES agent_model_steps(turn_id,ordinal)
    );
    CREATE TRIGGER agent_runtime_sessions_immutable BEFORE UPDATE OR DELETE ON agent_runtime_sessions
      FOR EACH ROW EXECUTE FUNCTION protect_checkpoint();
    CREATE TRIGGER agent_model_steps_immutable BEFORE UPDATE OR DELETE ON agent_model_steps
      FOR EACH ROW EXECUTE FUNCTION protect_checkpoint();
    CREATE TRIGGER agent_step_results_immutable BEFORE UPDATE OR DELETE ON agent_step_results
      FOR EACH ROW EXECUTE FUNCTION protect_checkpoint();''')


def downgrade():raise RuntimeError('Destructive downgrade disabled')
