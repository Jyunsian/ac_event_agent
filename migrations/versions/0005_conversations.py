"""Persistent ordered conversations, user messages and Agent turn queue."""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE conversations (
            id uuid PRIMARY KEY,
            baseline_run_id uuid NOT NULL REFERENCES runs(id),
            next_seq bigint NOT NULL DEFAULT 1 CHECK (next_seq > 0),
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX conversations_baseline ON conversations(baseline_run_id,created_at,id);
        CREATE TABLE agent_turns (
            id uuid PRIMARY KEY,
            conversation_id uuid NOT NULL REFERENCES conversations(id),
            ordinal bigint NOT NULL CHECK (ordinal > 0),
            selected_run_id uuid NOT NULL REFERENCES runs(id),
            selected_candidate_id text CHECK (length(selected_candidate_id) BETWEEN 1 AND 256),
            report_version integer NOT NULL CHECK (report_version > 0),
            status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
            error jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (conversation_id,ordinal),
            UNIQUE (id,conversation_id)
        );
        CREATE UNIQUE INDEX one_running_agent_turn ON agent_turns(conversation_id) WHERE status='running';
        CREATE INDEX agent_turn_fifo ON agent_turns(conversation_id,ordinal) WHERE status='queued';
        CREATE TABLE messages (
            id uuid PRIMARY KEY,
            conversation_id uuid NOT NULL REFERENCES conversations(id),
            turn_id uuid NOT NULL,
            seq bigint NOT NULL CHECK (seq > 0),
            role text NOT NULL CHECK (role IN ('user','assistant')),
            content text NOT NULL CHECK (length(content) BETWEEN 1 AND 20000),
            context jsonb NOT NULL CHECK (jsonb_typeof(context)='object'),
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (turn_id,conversation_id) REFERENCES agent_turns(id,conversation_id),
            UNIQUE (conversation_id,seq)
        );
        CREATE TABLE conversation_events (
            conversation_id uuid NOT NULL REFERENCES conversations(id),
            seq bigint NOT NULL CHECK (seq > 0),
            turn_id uuid NOT NULL,
            kind text NOT NULL,
            payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(conversation_id,seq),
            FOREIGN KEY (turn_id,conversation_id) REFERENCES agent_turns(id,conversation_id)
        );
        CREATE FUNCTION protect_conversation_record() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Conversation messages and events are immutable'; END $$;
        CREATE TRIGGER messages_immutable BEFORE UPDATE OR DELETE ON messages
            FOR EACH ROW EXECUTE FUNCTION protect_conversation_record();
        CREATE TRIGGER conversation_events_immutable BEFORE UPDATE OR DELETE ON conversation_events
            FOR EACH ROW EXECUTE FUNCTION protect_conversation_record();
    """)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled")
