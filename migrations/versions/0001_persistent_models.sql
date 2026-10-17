CREATE TABLE projects (
    id uuid PRIMARY KEY,
    app_id text NOT NULL CHECK (length(app_id) > 0),
    name text NOT NULL CHECK (length(name) > 0),
    customer_label text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE datasets (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id),
    status text NOT NULL DEFAULT 'uploading'
        CHECK (status IN ('uploading','ready','failed')),
    manifest jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(manifest) = 'array'),
    mapping jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(mapping) = 'object'),
    export_metadata jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(export_metadata) = 'object'),
    fingerprint text CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    schema_version text NOT NULL DEFAULT '1.0',
    sealed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, project_id),
    CHECK (status <> 'ready' OR (sealed_at IS NOT NULL AND fingerprint IS NOT NULL)),
    CHECK (sealed_at IS NULL OR fingerprint IS NOT NULL)
);

CREATE TABLE runs (
    id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES datasets(id),
    kind text NOT NULL CHECK (kind IN ('baseline','followup')),
    parent_run_id uuid,
    root_run_id uuid NOT NULL,
    config jsonb NOT NULL CHECK (jsonb_typeof(config) = 'object'),
    config_hash text NOT NULL CHECK (config_hash ~ '^[0-9a-f]{64}$'),
    calculation_version text NOT NULL,
    split_id text,
    evidence_status text NOT NULL DEFAULT 'pending'
        CHECK (evidence_status IN ('pending','exploratory','insufficient_data','historically_validated')),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    progress jsonb NOT NULL DEFAULT '{}',
    error jsonb,
    idempotency_key text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, dataset_id),
    FOREIGN KEY (parent_run_id, dataset_id) REFERENCES runs(id, dataset_id),
    FOREIGN KEY (root_run_id, dataset_id) REFERENCES runs(id, dataset_id),
    CHECK ((kind = 'baseline' AND parent_run_id IS NULL AND root_run_id = id)
        OR (kind = 'followup' AND parent_run_id IS NOT NULL AND parent_run_id <> id
            AND root_run_id <> id AND evidence_status = 'exploratory'))
);

CREATE TABLE jobs (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES runs(id),
    queue text NOT NULL DEFAULT 'compute' CHECK (queue IN ('compute','agent')),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    stage text NOT NULL DEFAULT 'initial',
    attempt_number integer NOT NULL DEFAULT 0 CHECK (attempt_number >= 0),
    fence bigint NOT NULL DEFAULT 0 CHECK (fence >= 0),
    lease_until timestamptz,
    worker_id text,
    cancel_requested boolean NOT NULL DEFAULT false,
    error jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, run_id)
);
CREATE INDEX jobs_claim ON jobs(queue, status, created_at);

CREATE TABLE job_attempts (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL,
    run_id uuid NOT NULL,
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    fence bigint NOT NULL CHECK (fence > 0),
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    error jsonb,
    FOREIGN KEY (job_id, run_id) REFERENCES jobs(id, run_id),
    UNIQUE (job_id, attempt_number),
    UNIQUE (job_id, fence),
    UNIQUE (id, run_id)
);

CREATE TABLE artifacts (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES runs(id),
    attempt_id uuid NOT NULL,
    kind text NOT NULL,
    object_key text NOT NULL UNIQUE
        CHECK (object_key ~ '^[a-zA-Z0-9][a-zA-Z0-9_./-]*$' AND object_key NOT LIKE '%..%'),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    schema_version text NOT NULL DEFAULT '1.0',
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (attempt_id, run_id) REFERENCES job_attempts(id, run_id),
    UNIQUE (id, run_id)
);

CREATE TABLE report_versions (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES runs(id),
    artifact_id uuid NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    narrative_status text NOT NULL DEFAULT 'not_requested'
        CHECK (narrative_status IN ('not_requested','pending','succeeded','failed')),
    model_info jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (artifact_id, run_id) REFERENCES artifacts(id, run_id),
    UNIQUE (run_id, version)
);

CREATE FUNCTION protect_dataset() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Dataset deletion requires explicit retention workflow';
    END IF;
    IF OLD.sealed_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'Sealed dataset is immutable';
    END IF;
    IF (NEW.id, NEW.project_id, NEW.created_at) IS DISTINCT FROM
       (OLD.id, OLD.project_id, OLD.created_at) THEN
        RAISE EXCEPTION 'Dataset identity is immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER dataset_guard BEFORE UPDATE OR DELETE ON datasets
    FOR EACH ROW EXECUTE FUNCTION protect_dataset();

CREATE FUNCTION protect_run() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_root uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Run history is immutable';
    END IF;
    IF TG_OP = 'UPDATE' AND
       (NEW.id, NEW.dataset_id, NEW.kind, NEW.parent_run_id, NEW.root_run_id,
        NEW.config, NEW.config_hash, NEW.calculation_version, NEW.idempotency_key, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.dataset_id, OLD.kind, OLD.parent_run_id, OLD.root_run_id,
        OLD.config, OLD.config_hash, OLD.calculation_version, OLD.idempotency_key, OLD.created_at) THEN
        RAISE EXCEPTION 'Run inputs are immutable; create a branch';
    END IF;
    IF TG_OP = 'INSERT' THEN
        PERFORM 1 FROM datasets WHERE id = NEW.dataset_id AND status = 'ready' AND sealed_at IS NOT NULL;
        IF NOT FOUND THEN RAISE EXCEPTION 'Run requires sealed ready dataset'; END IF;
        IF NEW.kind = 'followup' THEN
            SELECT root_run_id INTO parent_root FROM runs WHERE id = NEW.parent_run_id;
            IF parent_root IS NULL OR parent_root <> NEW.root_run_id THEN
                RAISE EXCEPTION 'Invalid run lineage';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER run_guard BEFORE INSERT OR UPDATE OR DELETE ON runs
    FOR EACH ROW EXECUTE FUNCTION protect_run();

CREATE FUNCTION immutable_record() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Published record is immutable';
END $$;
CREATE TRIGGER artifact_guard BEFORE UPDATE OR DELETE ON artifacts
    FOR EACH ROW EXECUTE FUNCTION immutable_record();
CREATE TRIGGER report_guard BEFORE UPDATE OR DELETE ON report_versions
    FOR EACH ROW EXECUTE FUNCTION immutable_record();
