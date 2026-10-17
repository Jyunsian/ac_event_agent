import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from scripts.local_postgres import LocalPostgres
from server.api.main import idempotency_conflict_handler
from server.db import IdempotencyConflict, Repository, database_engine
from server.jobs import JobQueue, LeaseLost


@pytest.fixture
def jobdb():
    with LocalPostgres() as pg:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True,
                       env={**os.environ, "DATABASE_URL": pg.url}, capture_output=True, timeout=30)
        engine = database_engine(pg.url)
        repo = Repository(engine)
        with engine.begin() as c:
            project = repo.create_project(c, "synthetic", "Job test")
            dataset = repo.create_dataset(c, project["id"])
            repo.seal_dataset(c, dataset["id"], [{"synthetic": True}], {}, {})
        yield engine, repo, dataset["id"]
        engine.dispose()


def submit(jobdb, key=None, config=None):
    engine, repo, dataset = jobdb
    with engine.begin() as c:
        return repo.create_run(c, dataset, config or {"synthetic": True}, key or str(uuid4()))


def test_concurrent_claim_short_transaction_and_heartbeat(jobdb):
    engine, _, _ = jobdb
    run = submit(jobdb)
    queue = JobQueue(engine, lease_seconds=2)
    barrier = threading.Barrier(2)
    def claim(worker):
        barrier.wait()
        return queue.claim(worker)
    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(claim, ["worker-a", "worker-b"]))
    winners = [lease for lease in leases if lease]
    assert len(winners) == 1
    lease = winners[0]
    assert lease.run_id == run["id"]
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='idle in transaction'")).scalar() == 0
    queue.heartbeat(lease)
    queue.finish(lease)
    with pytest.raises(LeaseLost):
        queue.finish(lease)


def test_expiry_reclaim_fencing_and_atomic_publication(jobdb):
    engine, _, _ = jobdb
    run = submit(jobdb)
    queue = JobQueue(engine, lease_seconds=.15)
    old = queue.claim("old-worker")
    time.sleep(.2)
    replacement = queue.claim("replacement")
    assert replacement.job_id == old.job_id and replacement.fence > old.fence
    for action in (queue.heartbeat, queue.finish):
        with pytest.raises(LeaseLost):
            action(old)
    # A publication error rolls back both metadata and terminal state.
    def broken(c):
        c.execute(text("UPDATE runs SET progress=jsonb_build_object('synthetic',true) WHERE id=:id"), {"id": run["id"]})
        raise RuntimeError("synthetic publication failure")
    with pytest.raises(RuntimeError):
        queue.finish(replacement, broken)
    with engine.connect() as c:
        saved = c.execute(text("SELECT status,progress FROM runs WHERE id=:id"), {"id": run["id"]}).mappings().one()
        assert saved["status"] == "running" and saved["progress"] == {}
    queue.finish(replacement)


def test_cancellation_and_retry_limit(jobdb):
    engine, _, _ = jobdb
    submit(jobdb)
    queue = JobQueue(engine)
    lease = queue.claim("worker")
    assert queue.cancel(lease.job_id) == "cancelled"
    assert queue.cancel(lease.job_id) == "cancelled"
    with pytest.raises(LeaseLost):
        queue.finish(lease)
    run = submit(jobdb)
    for attempt in range(1, 4):
        retry = queue.claim("retry-worker")
        assert retry.run_id == run["id"]
        queue.fail(retry, "SYNTHETIC_TRANSIENT", retryable=True, retry_delay=0)
    assert queue.claim("retry-worker") is None
    with engine.connect() as c:
        job = c.execute(text("SELECT status,attempt_number FROM jobs WHERE run_id=:id"), {"id": run["id"]}).mappings().one()
        assert job == {"status": "failed", "attempt_number": 3}


def test_expired_final_attempt_becomes_terminal(jobdb):
    engine, _, _ = jobdb
    run = submit(jobdb)
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET max_attempts=1 WHERE run_id=:id"), {"id": run["id"]})
    queue = JobQueue(engine, lease_seconds=.1)
    queue.claim("dying-worker")
    time.sleep(.15)
    assert queue.claim("replacement") is None
    with engine.connect() as c:
        assert c.execute(text("SELECT status FROM runs WHERE id=:id"), {"id": run["id"]}).scalar() == "failed"


def test_idempotency_concurrent_and_http_conflict(jobdb):
    engine, repo, dataset = jobdb
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(lambda _: submit(jobdb, key), range(4)))
    assert len({run["id"] for run in runs}) == 1
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM jobs")).scalar() == 1
    test_app = FastAPI()
    test_app.add_exception_handler(IdempotencyConflict, idempotency_conflict_handler)
    @test_app.post("/submit")
    def post(config: dict):
        with engine.begin() as c:
            return {"run_id": str(repo.create_run(c, dataset, config, key)["id"])}
    with TestClient(test_app) as client:
        same = client.post("/submit", json={"synthetic": True})
        conflict = client.post("/submit", json={"synthetic": False})
    assert same.status_code == 200
    assert conflict.status_code == 409 and conflict.json()["error_code"] == "IDEMPOTENCY_CONFLICT"
