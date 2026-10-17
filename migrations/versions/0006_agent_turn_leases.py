"""Agent queue leases are separate from computation run status."""
from alembic import op
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
      ALTER TABLE agent_turns ADD COLUMN fence bigint NOT NULL DEFAULT 0 CHECK(fence>=0),
        ADD COLUMN worker_id text, ADD COLUMN lease_until timestamptz,
        ADD COLUMN max_attempts integer NOT NULL DEFAULT 3 CHECK(max_attempts>0);
      CREATE TABLE agent_turn_attempts (
        turn_id uuid NOT NULL REFERENCES agent_turns(id), fence bigint NOT NULL CHECK(fence>0),
        worker_id text NOT NULL, started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        finished_at timestamptz, outcome text, PRIMARY KEY(turn_id,fence)
      );
    """)


def downgrade():
    raise RuntimeError('Destructive downgrade disabled')
