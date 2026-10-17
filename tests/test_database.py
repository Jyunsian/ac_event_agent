"""Real PostgreSQL tests. Missing runtime is a failure, never silently skipped."""
import os
import subprocess
import sys
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import insert, select, text, update, func
from sqlalchemy.exc import DBAPIError, IntegrityError

from scripts.local_postgres import LocalPostgres
from server.db import Repository, database_engine, fingerprint


@pytest.fixture(scope="module")
def database():
    with LocalPostgres() as pg:
        env = {**os.environ, "DATABASE_URL": pg.url}
        migration = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                                   env=env, capture_output=True, text=True, timeout=45)
        assert migration.returncode == 0, migration.stderr
        engine = database_engine(pg.url)
        repo = Repository(engine)
        print(f"\nPostgreSQL test evidence retained: {pg.root}")
        yield pg, engine, repo
        engine.dispose()


def seed(connection, repo):
    project = repo.create_project(connection, "synthetic", "Synthetic DB test")
    dataset = repo.create_dataset(connection, project["id"])
    repo.seal_dataset(connection, dataset["id"],
                      [{"key": "synthetic/users.csv", "sha256": "a"*64}], {}, {"synthetic": True})
    run = repo.create_run(connection, dataset["id"], {"window_hours": [1, 24]}, str(uuid4()))
    return dataset, run


def test_migrate_restart_and_read_back(database):
    pg, engine, repo = database
    with engine.begin() as connection:
        dataset, run = seed(connection, repo)
        assert connection.execute(text("select version()")).scalar().startswith("PostgreSQL")
        assert connection.execute(text("select version_num from alembic_version")).scalar() == \
            ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    engine.dispose()
    pg.restart()
    with engine.connect() as connection:
        saved = repo.get_run(connection, run["id"])
        assert saved["dataset_id"] == dataset["id"]
        assert saved["config"] == {"window_hours": [1, 24]}
        assert saved["config_hash"] == fingerprint(saved["config"])
        assert connection.execute(select(func.count()).select_from(repo.tables["jobs"]).where(
            repo.tables["jobs"].c.run_id == run["id"])).scalar() == 1


def test_immutable_dataset_and_run_inputs(database):
    _, engine, repo = database
    with engine.begin() as c:
        dataset, run = seed(c, repo)
    for table_name, identity, values in [
        ("datasets", dataset["id"], {"mapping": {"bad": "replacement"}}),
        ("datasets", dataset["id"], {"fingerprint": "b"*64}),
        ("runs", run["id"], {"config": {"window_hours": [72]}}),
        ("runs", run["id"], {"config_hash": "b"*64}),
        ("runs", run["id"], {"calculation_version": "changed"}),
    ]:
        table = repo.tables[table_name]
        with pytest.raises(DBAPIError), engine.begin() as c:
            c.execute(update(table).where(table.c.id == identity).values(**values))
    with engine.connect() as c:
        assert repo.get_run(c, run["id"])["config"] == {"window_hours": [1, 24]}


def test_parent_and_dataset_guards(database):
    _, engine, repo = database
    with engine.begin() as c:
        dataset, run = seed(c, repo)
        other_dataset, other_run = seed(c, repo)
        branch = repo.create_run(c, dataset["id"], {"window_hours": [72]}, str(uuid4()), run["id"])
        assert branch["root_run_id"] == run["id"] and branch["evidence_status"] == "exploratory"
        unsealed = repo.create_dataset(c, other_dataset["project_id"])
    with pytest.raises(ValueError), engine.begin() as c:
        repo.create_run(c, other_dataset["id"], {}, str(uuid4()), run["id"])
    # Bypass repository to prove the database rejects cross-dataset lineage too.
    with pytest.raises(IntegrityError), engine.begin() as c:
        c.execute(insert(repo.tables["runs"]).values(
            id=uuid4(), dataset_id=other_dataset["id"], kind="followup",
            parent_run_id=run["id"], root_run_id=run["id"], config={},
            config_hash=fingerprint({}), calculation_version="1", evidence_status="exploratory",
            idempotency_key=str(uuid4())))
    with pytest.raises(DBAPIError), engine.begin() as c:
        repo.create_run(c, unsealed["id"], {}, str(uuid4()))
    with pytest.raises(IntegrityError), engine.begin() as c:
        c.execute(update(repo.tables["runs"]).where(repo.tables["runs"].c.id == branch["id"])
                  .values(evidence_status="historically_validated"))


def test_artifact_report_relations_and_immutability(database):
    _, engine, repo = database
    with engine.begin() as c:
        _, run = seed(c, repo)
        _, other_run = seed(c, repo)
        jobs = repo.tables["jobs"]
        job = c.execute(select(jobs).where(jobs.c.run_id == run["id"])).mappings().one()
        attempt_id = uuid4()
        c.execute(insert(repo.tables["job_attempts"]).values(
            id=attempt_id, job_id=job["id"], run_id=run["id"], attempt_number=1, fence=1))
        artifact = repo.add_artifact(c, run["id"], attempt_id, "report", f"runs/{run['id']}/report.json", "a"*64, 10)
        report = repo.add_report(c, run["id"], artifact["id"])
    with pytest.raises(IntegrityError), engine.begin() as c:
        repo.add_artifact(c, other_run["id"], attempt_id, "report", "wrong/report", "b"*64, 10)
    with pytest.raises(IntegrityError), engine.begin() as c:
        repo.add_report(c, other_run["id"], artifact["id"])
    for table_name, identity in [("artifacts", artifact["id"]), ("report_versions", report["id"])]:
        table = repo.tables[table_name]
        with pytest.raises(DBAPIError), engine.begin() as c:
            c.execute(update(table).where(table.c.id == identity).values(run_id=other_run["id"]))


def test_rollback_has_no_partial_run_or_job(database):
    _, engine, repo = database
    with engine.begin() as c:
        dataset, _ = seed(c, repo)
    key = str(uuid4())
    with pytest.raises(RuntimeError), engine.begin() as c:
        failed_run = repo.create_run(c, dataset["id"], {}, key)
        raise RuntimeError("synthetic failure after run and job insertion")
    with engine.connect() as c:
        for name in ("runs", "jobs"):
            table = repo.tables[name]
            column = table.c.id if name == "runs" else table.c.run_id
            assert c.execute(select(func.count()).select_from(table).where(
                column == failed_run["id"])).scalar() == 0


def test_database_configuration_rejects_substitutes():
    with pytest.raises(ValueError):
        database_engine("sqlite://")
