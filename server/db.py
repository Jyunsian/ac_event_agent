"""PostgreSQL repository. Transactions belong to the caller, never hidden commits."""
import hashlib
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import MetaData, create_engine, insert, select, update


def database_engine(url=None):
    url = url or os.environ.get("DATABASE_URL")
    if not url or not url.startswith("postgresql+psycopg://"):
        raise ValueError("DATABASE_URL must use postgresql+psycopg")
    return create_engine(url, pool_pre_ping=True, hide_parameters=True)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                      allow_nan=False).encode()).hexdigest()


class IdempotencyConflict(Exception):
    status_code = 409
    code = "IDEMPOTENCY_CONFLICT"

    def __init__(self):
        super().__init__("The idempotency key was already used with different inputs")


class Repository:
    def __init__(self, engine):
        self.engine = engine
        self.metadata = MetaData()
        self.metadata.reflect(engine)
        self.tables = self.metadata.tables

    def create_project(self, connection, app_id, name, customer_label=None):
        table = self.tables["projects"]
        return connection.execute(insert(table).values(
            id=uuid4(), app_id=app_id, name=name, customer_label=customer_label
        ).returning(table)).mappings().one()

    def create_dataset(self, connection, project_id):
        table = self.tables["datasets"]
        return connection.execute(insert(table).values(
            id=uuid4(), project_id=project_id).returning(table)).mappings().one()

    def seal_dataset(self, connection, dataset_id, manifest, mapping, export_metadata):
        if not manifest:
            raise ValueError("Cannot seal an empty manifest")
        table = self.tables["datasets"]
        values = dict(manifest=manifest, mapping=mapping, export_metadata=export_metadata)
        return connection.execute(update(table).where(table.c.id == dataset_id).values(
            **values, fingerprint=fingerprint(values), status="ready",
            sealed_at=datetime.now(timezone.utc)).returning(table)).mappings().one()

    def create_run(self, connection, dataset_id, config, idempotency_key,
                   parent_run_id=None, calculation_version="1.0"):
        table = self.tables["runs"]
        request_hash = fingerprint({"dataset_id": str(dataset_id), "config": config,
                                    "parent_run_id": str(parent_run_id) if parent_run_id else None,
                                    "calculation_version": calculation_version})
        # Serialize the same request key only, not every run submission. Lock is transaction-scoped.
        from sqlalchemy import text
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                           {"key": idempotency_key})
        existing = connection.execute(select(table).where(
            table.c.idempotency_key == idempotency_key)).mappings().one_or_none()
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise IdempotencyConflict()
            return existing
        run_id = uuid4()
        root_id = run_id
        if parent_run_id is not None:
            parent = connection.execute(select(table).where(
                table.c.id == parent_run_id)).mappings().one()
            if parent["dataset_id"] != dataset_id:
                raise ValueError("Parent must reference the same dataset version")
            root_id = parent["root_run_id"]
        run = connection.execute(insert(table).values(
            id=run_id, dataset_id=dataset_id, config=config, config_hash=fingerprint(config),
            kind="followup" if parent_run_id else "baseline", parent_run_id=parent_run_id,
            root_run_id=root_id, evidence_status="exploratory" if parent_run_id else "pending",
            calculation_version=calculation_version, idempotency_key=idempotency_key,
            request_hash=request_hash
        ).returning(table)).mappings().one()
        connection.execute(insert(self.tables["jobs"]).values(id=uuid4(), run_id=run_id))
        return run

    def get_run(self, connection, run_id):
        table = self.tables["runs"]
        return connection.execute(select(table).where(table.c.id == run_id)).mappings().one()

    def add_artifact(self, connection, run_id, attempt_id, kind, object_key, sha256, size_bytes):
        table = self.tables["artifacts"]
        return connection.execute(insert(table).values(
            id=uuid4(), run_id=run_id, attempt_id=attempt_id, kind=kind,
            object_key=object_key, sha256=sha256, size_bytes=size_bytes
        ).returning(table)).mappings().one()

    def add_report(self, connection, run_id, artifact_id, version=1):
        table = self.tables["report_versions"]
        return connection.execute(insert(table).values(
            id=uuid4(), run_id=run_id, artifact_id=artifact_id, version=version
        ).returning(table)).mappings().one()
