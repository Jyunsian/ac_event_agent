"""Immutable population identity and pre-evaluation validation reservations."""
from alembic import op
revision='0009'
down_revision='0008'
branch_labels=None
depends_on=None


def upgrade():
    op.execute("""
      CREATE TABLE validation_populations (
        dataset_id uuid PRIMARY KEY REFERENCES datasets(id),
        users_sha256 text NOT NULL CHECK(users_sha256 ~ '^[a-f0-9]{64}$'),
        user_count bigint NOT NULL CHECK(user_count>=0),
        registered_at timestamptz NOT NULL DEFAULT clock_timestamp()
      );
      CREATE TABLE validation_population_members (
        dataset_id uuid NOT NULL REFERENCES validation_populations(dataset_id),
        user_hash text NOT NULL CHECK(user_hash ~ '^[a-f0-9]{64}$'),
        PRIMARY KEY(dataset_id,user_hash)
      );
      CREATE INDEX validation_population_user ON validation_population_members(user_hash,dataset_id);
      CREATE TABLE validation_reservations (
        run_id uuid PRIMARY KEY,
        dataset_id uuid NOT NULL REFERENCES validation_populations(dataset_id),
        split_id text NOT NULL,
        frozen_sha256 text NOT NULL CHECK(frozen_sha256 ~ '^[a-f0-9]{64}$'),
        eligible boolean NOT NULL,
        reasons jsonb NOT NULL CHECK(jsonb_typeof(reasons)='array'),
        policy_version text NOT NULL DEFAULT '1.0',
        reserved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        FOREIGN KEY(run_id,dataset_id) REFERENCES runs(id,dataset_id)
      );
      CREATE TRIGGER validation_populations_immutable BEFORE UPDATE OR DELETE ON validation_populations FOR EACH ROW EXECUTE FUNCTION protect_conversation_record();
      CREATE TRIGGER validation_members_immutable BEFORE UPDATE OR DELETE ON validation_population_members FOR EACH ROW EXECUTE FUNCTION protect_conversation_record();
      CREATE TRIGGER validation_reservations_immutable BEFORE UPDATE OR DELETE ON validation_reservations FOR EACH ROW EXECUTE FUNCTION protect_conversation_record();
      CREATE FUNCTION guard_validation_label() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE reservation validation_reservations%ROWTYPE;
      BEGIN
        SELECT * INTO reservation FROM validation_reservations WHERE run_id=NEW.id;
        IF FOUND THEN
          IF NEW.split_id IS DISTINCT FROM reservation.split_id THEN
            RAISE EXCEPTION 'Reserved validation split is immutable';
          END IF;
          IF NOT reservation.eligible AND NEW.evidence_status <> 'exploratory' THEN
            RAISE EXCEPTION 'Exposed or overlapping data must remain exploratory';
          END IF;
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER validation_label_guard BEFORE UPDATE ON runs FOR EACH ROW EXECUTE FUNCTION guard_validation_label();
    """)


def downgrade():raise RuntimeError('Destructive downgrade disabled')
