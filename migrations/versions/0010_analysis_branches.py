"""Immutable branch provenance and tool-call identity."""
from alembic import op
revision='0010'
down_revision='0009'
branch_labels=None
depends_on=None


def upgrade():
    op.execute("""
      CREATE TABLE analysis_branches (
        run_id uuid PRIMARY KEY REFERENCES runs(id),
        source_turn_id uuid NOT NULL REFERENCES agent_turns(id),
        tool_call_id text NOT NULL CHECK(length(tool_call_id) BETWEEN 1 AND 200),
        parent_report_artifact_id uuid NOT NULL REFERENCES artifacts(id),
        parent_report_version integer NOT NULL CHECK(parent_report_version>0),
        parent_report_sha256 text NOT NULL CHECK(parent_report_sha256 ~ '^[a-f0-9]{64}$'),
        config_delta jsonb NOT NULL CHECK(jsonb_typeof(config_delta)='object'),
        cache_context jsonb NOT NULL CHECK(jsonb_typeof(cache_context)='object'),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        UNIQUE(source_turn_id,tool_call_id)
      );
      CREATE TRIGGER analysis_branches_immutable BEFORE UPDATE OR DELETE ON analysis_branches
        FOR EACH ROW EXECUTE FUNCTION protect_conversation_record();
      CREATE FUNCTION guard_branch_provenance() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE child runs%ROWTYPE; source agent_turns%ROWTYPE; artifact artifacts%ROWTYPE;
      BEGIN
        SELECT * INTO child FROM runs WHERE id=NEW.run_id;
        SELECT * INTO source FROM agent_turns WHERE id=NEW.source_turn_id;
        SELECT * INTO artifact FROM artifacts WHERE id=NEW.parent_report_artifact_id;
        IF child.kind <> 'followup' OR child.parent_run_id IS DISTINCT FROM source.selected_run_id
          OR artifact.run_id IS DISTINCT FROM child.parent_run_id OR artifact.kind <> 'report_json'
          OR artifact.sha256 IS DISTINCT FROM NEW.parent_report_sha256 THEN
          RAISE EXCEPTION 'Branch provenance mismatch';
        END IF;
        IF NOT EXISTS(SELECT 1 FROM report_versions WHERE run_id=child.parent_run_id
          AND version=NEW.parent_report_version AND artifact_id=NEW.parent_report_artifact_id) THEN
          RAISE EXCEPTION 'Branch report version mismatch';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER analysis_branch_guard BEFORE INSERT ON analysis_branches FOR EACH ROW EXECUTE FUNCTION guard_branch_provenance();
    """)


def downgrade():raise RuntimeError('Destructive downgrade disabled')
