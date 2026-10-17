"""Immutable same-App observations with report provenance, not model training."""
from alembic import op
revision='0014'
down_revision='0013'
branch_labels=None
depends_on=None


def upgrade():
    op.execute('''CREATE TABLE app_findings (
      id uuid PRIMARY KEY,
      app_id text NOT NULL CHECK(length(app_id)>0),
      source_run_id uuid NOT NULL REFERENCES runs(id),
      source_dataset_id uuid NOT NULL REFERENCES datasets(id),
      report_version integer NOT NULL CHECK(report_version>0),
      report_artifact_id uuid NOT NULL REFERENCES artifacts(id),
      report_sha256 text NOT NULL CHECK(report_sha256 ~ '^[0-9a-f]{64}$'),
      candidate_id text NOT NULL CHECK(length(candidate_id) BETWEEN 1 AND 256),
      event_spec jsonb NOT NULL CHECK(jsonb_typeof(event_spec)='object'),
      hypothesis text NOT NULL CHECK(length(hypothesis) BETWEEN 1 AND 1000),
      limitations jsonb NOT NULL CHECK(jsonb_typeof(limitations)='array'),
      counterexamples jsonb NOT NULL CHECK(jsonb_typeof(counterexamples)='array'),
      outcome text NOT NULL CHECK(outcome IN ('observation','supported','contradicted','inconclusive')),
      previous_finding_id uuid REFERENCES app_findings(id),
      source_turn_id uuid NOT NULL REFERENCES agent_turns(id),
      tool_call_id text NOT NULL CHECK(length(tool_call_id) BETWEEN 1 AND 200),
      payload_hash text NOT NULL CHECK(payload_hash ~ '^[0-9a-f]{64}$'),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      UNIQUE(source_turn_id,tool_call_id),
      UNIQUE(app_id,source_run_id,report_version,candidate_id,payload_hash),
      CHECK((outcome='observation')=(previous_finding_id IS NULL))
    );
    CREATE INDEX app_findings_read ON app_findings(app_id,created_at DESC,id DESC);
    CREATE FUNCTION guard_app_finding() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE prior app_findings;
    BEGIN
      IF NOT EXISTS(SELECT 1 FROM runs r JOIN datasets d ON d.id=r.dataset_id
          JOIN projects p ON p.id=d.project_id
          JOIN report_versions v ON v.run_id=r.id
          JOIN artifacts a ON a.id=v.artifact_id AND a.run_id=r.id
          JOIN agent_turns t ON t.id=NEW.source_turn_id
          JOIN runs selected ON selected.id=t.selected_run_id
          WHERE r.id=NEW.source_run_id AND r.status='succeeded'
          AND d.id=NEW.source_dataset_id AND p.app_id=NEW.app_id
          AND v.version=NEW.report_version AND a.id=NEW.report_artifact_id
          AND a.kind='report_json' AND a.sha256=NEW.report_sha256
          AND selected.root_run_id=r.root_run_id)
      THEN RAISE EXCEPTION 'FINDING_PROVENANCE_MISMATCH' USING ERRCODE='23514'; END IF;
      IF NEW.previous_finding_id IS NOT NULL THEN
        SELECT * INTO prior FROM app_findings WHERE id=NEW.previous_finding_id;
        IF NOT FOUND OR prior.app_id<>NEW.app_id OR prior.source_dataset_id=NEW.source_dataset_id
           OR prior.event_spec<>NEW.event_spec
        THEN RAISE EXCEPTION 'FINDING_RECHECK_MISMATCH' USING ERRCODE='23514'; END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER app_findings_source BEFORE INSERT ON app_findings
      FOR EACH ROW EXECUTE FUNCTION guard_app_finding();
    CREATE TRIGGER app_findings_immutable BEFORE UPDATE OR DELETE ON app_findings
      FOR EACH ROW EXECUTE FUNCTION protect_checkpoint();''')


def downgrade():raise RuntimeError('Destructive downgrade disabled')
