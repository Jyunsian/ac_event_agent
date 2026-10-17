import hashlib
import multiprocessing as mp
import os
import time
from pathlib import Path

import pytest
from sqlalchemy import text

from server.db import database_engine
from server.jobs import JobQueue, Lease, LeaseLost
from server.worker import Worker
from tests.test_jobs import jobdb, submit


def synthetic_compute(payload):
    """Real bounded CPU work. Delay and PID markers are synthetic fault-injection controls only."""
    config = payload["config"]
    marker = Path(config["marker_dir"])/str(payload["fence"])
    marker.write_text(str(os.getpid()))
    deadline = time.monotonic()+config.get("duration", 0)
    digest = b"synthetic"
    rounds = 0
    while time.monotonic() < deadline:
        for _ in range(1000):
            digest = hashlib.sha256(digest).digest()
        rounds += 1000
    return {"summary": {"synthetic": True, "rounds": rounds, "digest": digest.hex()}}


def synthetic_incomplete_report(payload):
    return {"report_kind": "report_json", "artifacts": [{"kind": "report_json",
        "object_key": "synthetic/incomplete.json", "sha256": "a"*64, "size_bytes": 2}]}


def test_incomplete_report_transaction_rolls_back(jobdb):
    engine, _, _ = jobdb
    run = submit(jobdb)
    assert Worker(engine, synthetic_incomplete_report).run_once()
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM artifacts WHERE run_id=:id"), {"id": run["id"]}).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM report_versions WHERE run_id=:id"), {"id": run["id"]}).scalar_one() == 0
        assert c.execute(text("SELECT status FROM runs WHERE id=:id"), {"id": run["id"]}).scalar_one() == "failed"


def run_worker(url, seconds=2, timeout=30, ready=None):
    engine = database_engine(url)
    try:
        worker = Worker(engine, synthetic_compute, lease_seconds=seconds,
                        heartbeat_seconds=.15, task_timeout=timeout)
        if ready:
            ready.wait(10)
        worker.run_once()
    finally:
        engine.dispose()


def eventually(check, timeout=10):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError("Expected state was not observed within deadline")


def read_job(engine):
    with engine.connect() as c:
        return dict(c.execute(text("SELECT * FROM jobs")).mappings().one())


def process_running(pid):
    import subprocess
    result = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return result.returncode == 0 and result.stdout.strip() and not result.stdout.strip().startswith("Z")


def stop_exact(process):
    if process.is_alive():
        process.terminate()
    process.join(5)
    if process.is_alive():
        process.kill()
        process.join(5)


def test_two_real_workers_and_heartbeat(jobdb, tmp_path):
    engine, _, _ = jobdb
    run = submit(jobdb, config={"synthetic": True, "marker_dir": str(tmp_path), "duration": 2.5})
    context = mp.get_context("spawn")
    barrier = context.Barrier(2)
    workers = [context.Process(target=run_worker, args=(str(engine.url), 2, 15, barrier)) for _ in range(2)]
    try:
        for process in workers:
            process.start()
        eventually(lambda: (tmp_path/"1").exists())
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='idle in transaction'")).scalar() == 0
        for process in workers:
            process.join(15)
            assert process.exitcode == 0
        assert read_job(engine)["status"] == "succeeded"
        assert read_job(engine)["attempt_number"] == 1
        assert len(list(tmp_path.iterdir())) == 1
        with engine.connect() as c:
            result = c.execute(text("SELECT progress FROM runs WHERE id=:id"), {"id": run["id"]}).scalar()
            assert result["synthetic"] and result["rounds"] > 0 and len(result["digest"]) == 64
    finally:
        for process in workers:
            stop_exact(process)


def test_sigkill_parent_orphan_exit_and_replacement(jobdb, tmp_path):
    engine, _, _ = jobdb
    submit(jobdb, config={"synthetic": True, "marker_dir": str(tmp_path), "duration": 3})
    context = mp.get_context("spawn")
    original = context.Process(target=run_worker, args=(str(engine.url),))
    replacement = None
    try:
        original.start()
        eventually(lambda: (tmp_path/"1").exists())
        child_pid = int((tmp_path/"1").read_text())
        previous = read_job(engine)
        with engine.connect() as c:
            attempt_id = c.execute(text("SELECT id FROM job_attempts WHERE job_id=:id"), {"id": previous["id"]}).scalar()
        old_lease = Lease(previous["id"], previous["run_id"], attempt_id, previous["fence"], previous["worker_id"], previous["stage"])
        original.kill()
        original.join(5)
        assert original.exitcode != 0
        eventually(lambda: not process_running(child_pid))
        eventually(lambda: expired(engine))
        replacement = context.Process(target=run_worker, args=(str(engine.url),))
        replacement.start()
        eventually(lambda: (tmp_path/"2").exists())
        with pytest.raises(LeaseLost):
            JobQueue(engine).finish(old_lease)
        replacement.join(15)
        assert replacement.exitcode == 0
        assert read_job(engine)["status"] == "succeeded" and read_job(engine)["attempt_number"] == 2
    finally:
        stop_exact(original)
        if replacement:
            stop_exact(replacement)


def expired(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT lease_until < clock_timestamp() FROM jobs")).scalar()


def test_cancel_terminates_compute(jobdb, tmp_path):
    engine, _, _ = jobdb
    submit(jobdb, config={"synthetic": True, "marker_dir": str(tmp_path), "duration": 30})
    process = mp.get_context("spawn").Process(target=run_worker, args=(str(engine.url),))
    try:
        process.start()
        eventually(lambda: (tmp_path/"1").exists())
        child_pid = int((tmp_path/"1").read_text())
        JobQueue(engine).cancel(read_job(engine)["id"])
        process.join(10)
        assert process.exitcode == 0
        eventually(lambda: not process_running(child_pid))
        assert read_job(engine)["status"] == "cancelled"
    finally:
        stop_exact(process)


def test_missing_pipeline_database_configuration_is_honest_failure(jobdb, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    engine, _, _ = jobdb
    submit(jobdb)
    Worker(engine).run_once()
    job = read_job(engine)
    assert job["status"] == "failed"
    assert job["error"]["code"] == "DATABASE_NOT_CONFIGURED"


def sensitive_failure(payload):
    raise RuntimeError("synthetic-secret-do-not-persist")


def resource_watchdog_exit(payload):
    os._exit(73)


def test_resource_watchdog_exit_is_persisted_without_report(jobdb):
    engine,_,_=jobdb
    submit(jobdb)
    assert Worker(engine,resource_watchdog_exit).run_once()
    job=read_job(engine)
    assert job['status']=='failed' and job['error']=={'code':'WORKDIR_LIMIT'}
    assert not Worker(engine).run_once()


def test_compute_error_is_sanitized(jobdb):
    engine, _, _ = jobdb
    submit(jobdb)
    Worker(engine, sensitive_failure).run_once()
    job = read_job(engine)
    assert job["status"] == "failed" and job["error"] == {"code": "COMPUTE_FAILED"}


def test_timeout_stops_child_without_retry(jobdb, tmp_path):
    engine, _, _ = jobdb
    submit(jobdb, config={"synthetic": True, "marker_dir": str(tmp_path), "duration": 30})
    Worker(engine, synthetic_compute, lease_seconds=2, heartbeat_seconds=.15, task_timeout=1.5).run_once()
    job = read_job(engine)
    assert job["status"] == "failed" and job["error"] == {"code": "TASK_TIMEOUT"}
    if (tmp_path/"1").exists():
        assert not process_running(int((tmp_path/"1").read_text()))
