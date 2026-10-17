"""Append-only dataset/split disclosure ledger, independent of conversation."""
from alembic import op

revision='0008'
down_revision='0007'
branch_labels=None
depends_on=None


def upgrade():
    op.execute("""
      CREATE TABLE validation_exposures (
        dataset_id uuid NOT NULL REFERENCES datasets(id),
        split_id text NOT NULL CHECK (length(split_id)>0),
        source_run_id uuid NOT NULL,
        report_artifact_id uuid NOT NULL REFERENCES artifacts(id),
        report_version integer NOT NULL CHECK (report_version>0),
        report_sha256 text NOT NULL CHECK (report_sha256 ~ '^[a-f0-9]{64}$'),
        channel text NOT NULL CHECK (channel IN ('report_export','agent_tool','run_summary')),
        exposed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY(dataset_id,split_id),
        FOREIGN KEY(source_run_id,dataset_id) REFERENCES runs(id,dataset_id)
      );
      CREATE TRIGGER validation_exposures_immutable BEFORE UPDATE OR DELETE ON validation_exposures
        FOR EACH ROW EXECUTE FUNCTION protect_conversation_record();
    """)


def downgrade():
    raise RuntimeError('Destructive downgrade disabled')
