"""Freeze same-App finding provenance with the new baseline run transaction."""
from alembic import op
revision='0015'
down_revision='0014'
branch_labels=None
depends_on=None


def upgrade():
    op.execute('''CREATE TABLE finding_rechecks (
      run_id uuid PRIMARY KEY REFERENCES runs(id),
      sources jsonb NOT NULL CHECK(jsonb_typeof(sources)='array' AND jsonb_array_length(sources) BETWEEN 1 AND 10),
      snapshot_sha256 text NOT NULL CHECK(snapshot_sha256 ~ '^[0-9a-f]{64}$'),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE FUNCTION guard_finding_recheck() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE source jsonb; app text; dataset uuid;
    BEGIN
      SELECT p.app_id,r.dataset_id INTO app,dataset FROM runs r JOIN datasets d ON d.id=r.dataset_id
        JOIN projects p ON p.id=d.project_id WHERE r.id=NEW.run_id AND r.kind='baseline' AND r.status='queued';
      IF NOT FOUND THEN RAISE EXCEPTION 'RECHECK_BASELINE_REQUIRED' USING ERRCODE='23514'; END IF;
      FOR source IN SELECT value FROM jsonb_array_elements(NEW.sources) LOOP
        IF NOT EXISTS(SELECT 1 FROM app_findings f WHERE f.id=(source->>'finding_id')::uuid
          AND f.app_id=app AND f.source_dataset_id<>dataset
          AND f.candidate_id=source->>'candidate_id' AND f.event_spec=source->'event_spec'
          AND f.report_sha256=source->>'report_sha256')
        THEN RAISE EXCEPTION 'RECHECK_FINDING_SOURCE_MISMATCH' USING ERRCODE='23514'; END IF;
      END LOOP;
      RETURN NEW;
    END $$;
    CREATE TRIGGER finding_recheck_source BEFORE INSERT ON finding_rechecks
      FOR EACH ROW EXECUTE FUNCTION guard_finding_recheck();
    CREATE TRIGGER finding_recheck_immutable BEFORE UPDATE OR DELETE ON finding_rechecks
      FOR EACH ROW EXECUTE FUNCTION protect_checkpoint();''')


def downgrade():raise RuntimeError('Destructive downgrade disabled')
