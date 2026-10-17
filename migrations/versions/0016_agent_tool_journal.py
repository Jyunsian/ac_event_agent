"""Immutable tool intents and results survive Node process loss."""
from alembic import op
revision='0016'
down_revision='0015'
branch_labels=None
depends_on=None


def upgrade():
    op.execute('''CREATE TABLE agent_tool_calls (
      turn_id uuid NOT NULL REFERENCES agent_turns(id),
      tool_call_id text NOT NULL CHECK(length(tool_call_id) BETWEEN 1 AND 200),
      ordinal integer NOT NULL CHECK(ordinal BETWEEN 1 AND 100),
      tool_name text NOT NULL CHECK(length(tool_name) BETWEEN 1 AND 100),
      arguments jsonb NOT NULL CHECK(jsonb_typeof(arguments)='object'),
      input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[0-9a-f]{64}$'),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY(turn_id,tool_call_id), UNIQUE(turn_id,ordinal)
    );
    CREATE TABLE agent_tool_results (
      turn_id uuid NOT NULL, tool_call_id text NOT NULL,
      output jsonb NOT NULL CHECK(jsonb_typeof(output)='object'),
      output_sha256 text NOT NULL CHECK(output_sha256 ~ '^[0-9a-f]{64}$'),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY(turn_id,tool_call_id),
      FOREIGN KEY(turn_id,tool_call_id) REFERENCES agent_tool_calls(turn_id,tool_call_id)
    );
    CREATE TRIGGER agent_tool_calls_immutable BEFORE UPDATE OR DELETE ON agent_tool_calls
      FOR EACH ROW EXECUTE FUNCTION protect_checkpoint();
    CREATE TRIGGER agent_tool_results_immutable BEFORE UPDATE OR DELETE ON agent_tool_results
      FOR EACH ROW EXECUTE FUNCTION protect_checkpoint();''')


def downgrade():raise RuntimeError('Destructive downgrade disabled')
