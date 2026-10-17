"""Public hypotheses and previously delivered evidence, never private reasoning."""
from alembic import op
revision='0013'
down_revision='0012'
branch_labels=None
depends_on=None


def upgrade():
    op.execute('''CREATE TABLE exploration_round_notes (
      run_id uuid PRIMARY KEY REFERENCES exploration_rounds(run_id),
      hypothesis text CHECK(hypothesis IS NULL OR length(hypothesis) BETWEEN 1 AND 1000),
      based_on jsonb NOT NULL CHECK(jsonb_typeof(based_on)='array'),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    INSERT INTO exploration_round_notes(run_id,hypothesis,based_on)
      SELECT run_id,NULL,'[]'::jsonb FROM exploration_rounds;
    CREATE TRIGGER exploration_round_notes_immutable BEFORE UPDATE OR DELETE ON exploration_round_notes
      FOR EACH ROW EXECUTE FUNCTION protect_checkpoint();''')


def downgrade():raise RuntimeError('Destructive downgrade disabled')
