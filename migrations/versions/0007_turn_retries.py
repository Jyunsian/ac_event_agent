"""Retry lineage keeps original failed/cancelled turns intact."""
from alembic import op
revision='0007'
down_revision='0006'
branch_labels=None
depends_on=None


def upgrade():
    op.execute('''ALTER TABLE agent_turns ADD COLUMN retry_of_turn_id uuid UNIQUE REFERENCES agent_turns(id);
      ALTER TABLE agent_turns ADD CONSTRAINT retry_not_self CHECK(retry_of_turn_id IS NULL OR retry_of_turn_id<>id);''')


def downgrade():
    raise RuntimeError('Destructive downgrade disabled')
