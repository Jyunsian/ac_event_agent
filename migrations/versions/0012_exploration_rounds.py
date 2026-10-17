"""Durable bounded exploration rounds and immutable finalization."""
from alembic import op
revision='0012'
down_revision='0011'
branch_labels=None
depends_on=None


def upgrade():
    op.execute('''
      CREATE TABLE exploration_budgets (
        turn_id uuid PRIMARY KEY REFERENCES agent_turns(id),
        max_rounds integer NOT NULL CHECK(max_rounds BETWEEN 1 AND 20),
        max_candidates integer NOT NULL CHECK(max_candidates BETWEEN 1 AND 40000),
        deadline timestamptz NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp()
      );
      CREATE TABLE exploration_rounds (
        run_id uuid PRIMARY KEY REFERENCES analysis_branches(run_id),
        turn_id uuid NOT NULL REFERENCES exploration_budgets(turn_id),
        ordinal integer NOT NULL CHECK(ordinal>0),
        reserved_candidates integer NOT NULL CHECK(reserved_candidates BETWEEN 1 AND 2000),
        parameters jsonb NOT NULL CHECK(jsonb_typeof(parameters)='object'),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        UNIQUE(turn_id,ordinal)
      );
      CREATE TABLE exploration_finalizations (
        turn_id uuid PRIMARY KEY REFERENCES exploration_budgets(turn_id),
        run_id uuid NOT NULL REFERENCES exploration_rounds(run_id),
        report_artifact_id uuid NOT NULL REFERENCES artifacts(id),
        report_version integer NOT NULL CHECK(report_version>0),
        report_sha256 text NOT NULL CHECK(report_sha256 ~ '^[a-f0-9]{64}$'),
        candidate_ids jsonb NOT NULL CHECK(jsonb_typeof(candidate_ids)='array'),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp()
      );
      CREATE TRIGGER exploration_budgets_immutable BEFORE UPDATE OR DELETE ON exploration_budgets
        FOR EACH ROW EXECUTE FUNCTION protect_checkpoint();
      CREATE TRIGGER exploration_rounds_immutable BEFORE UPDATE OR DELETE ON exploration_rounds
        FOR EACH ROW EXECUTE FUNCTION protect_checkpoint();
      CREATE TRIGGER exploration_finalizations_immutable BEFORE UPDATE OR DELETE ON exploration_finalizations
        FOR EACH ROW EXECUTE FUNCTION protect_checkpoint();
      CREATE FUNCTION guard_exploration_finalization() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NOT EXISTS(SELECT 1 FROM exploration_rounds r JOIN report_versions v ON v.run_id=r.run_id
          JOIN artifacts a ON a.id=v.artifact_id WHERE r.turn_id=NEW.turn_id AND r.run_id=NEW.run_id
          AND v.version=NEW.report_version AND a.id=NEW.report_artifact_id AND a.sha256=NEW.report_sha256)
        THEN RAISE EXCEPTION 'FINALIZATION_PROVENANCE_MISMATCH'; END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER exploration_finalization_guard BEFORE INSERT ON exploration_finalizations
        FOR EACH ROW EXECUTE FUNCTION guard_exploration_finalization();
      INSERT INTO exploration_budgets(turn_id,max_rounds,max_candidates,deadline,created_at)
        SELECT DISTINCT t.id,4,(p.config->>'max_candidates')::integer*4,t.created_at+interval '600 seconds',t.created_at
        FROM analysis_branches b JOIN agent_turns t ON t.id=b.source_turn_id JOIN runs p ON p.id=t.selected_run_id;
      INSERT INTO exploration_rounds(run_id,turn_id,ordinal,reserved_candidates,parameters,created_at)
        SELECT b.run_id,b.source_turn_id,row_number() OVER(PARTITION BY b.source_turn_id ORDER BY b.created_at,b.run_id),
          (r.config->>'max_candidates')::integer,r.config,b.created_at
        FROM analysis_branches b JOIN runs r ON r.id=b.run_id;
    ''')


def downgrade():raise RuntimeError('Destructive downgrade disabled')
