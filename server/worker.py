"""Compute subprocess supervised by a lease-heartbeating parent; only trusted handlers are injected."""
import argparse
import errno
import json
import multiprocessing as mp
import os
import re
import signal
import threading
import time
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from server.db import Repository, database_engine
from server.jobs import JobQueue, LeaseLost
from server.resources import Limits,ResourceLimitError,RESOURCE_EXIT_CODES
from server.worker_health import pulse

MAX_RESULT_BYTES = 256 * 1024


class TaskFailure(Exception):
    def __init__(self, code, retryable=False):
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
            raise ValueError("Invalid safe error code")
        self.code, self.retryable = code, retryable
        super().__init__(code)


def baseline_handler(payload):
    from server.pipeline import baseline_from_environment
    from server.analysis.ingest import IngestError
    from server.storage import StorageError
    if not os.environ.get("DATABASE_URL"):
        raise TaskFailure("DATABASE_NOT_CONFIGURED")
    try:
        return baseline_from_environment(payload)
    except StorageError as error:
        raise TaskFailure(error.code, error.retryable) from None
    except IngestError as error:
        raise TaskFailure(str(error)) from None
    except ResourceLimitError as error:
        raise TaskFailure(str(error)) from None


def _compute(handler, payload, output, expected_parent):
    def watch_parent():
        while True:
            if os.getppid() != expected_parent:
                os._exit(70)  # Parent SIGKILL must not leave expensive orphan computation running.
            time.sleep(.1)
    threading.Thread(target=watch_parent, daemon=True).start()
    try:
        result = handler(payload)
        if not isinstance(result, dict):
            raise TaskFailure("INVALID_WORKER_RESULT")
        encoded = json.dumps({"ok": True, "result": result}, allow_nan=False).encode()
        if len(encoded) > MAX_RESULT_BYTES:
            raise TaskFailure("WORKER_RESULT_TOO_LARGE")
    except TaskFailure as error:
        encoded = json.dumps({"ok": False, "code": error.code, "retryable": error.retryable}).encode()
    except MemoryError:
        encoded = b'{"ok":false,"code":"MEMORY_LIMIT","retryable":false}'
    except OSError as error:
        code = 'DISK_FULL' if error.errno in (errno.ENOSPC, errno.EDQUOT) else 'COMPUTE_IO_ERROR'
        encoded = json.dumps({'ok':False,'code':code,'retryable':False}).encode()
    except BaseException:
        # Do not serialize raw exception text: it may include source log content, paths or credentials.
        encoded = b'{"ok":false,"code":"COMPUTE_FAILED","retryable":false}'
    try:
        output.send_bytes(encoded)
    finally:
        output.close()


class Worker:
    def __init__(self, engine, handler=baseline_handler, *, worker_id=None,
                 lease_seconds=90, heartbeat_seconds=15, task_timeout=None):
        if task_timeout is None:task_timeout=Limits.from_environment().timeout_seconds
        if not 0 < heartbeat_seconds < lease_seconds / 2 or task_timeout <= 0:
            raise ValueError("Heartbeat must be positive and less than half the lease; timeout must be positive")
        self.engine, self.handler = engine, handler
        self.repo = Repository(engine)
        self.queue = JobQueue(engine, lease_seconds)
        self.worker_id = worker_id or str(uuid4())
        self.heartbeat_seconds, self.task_timeout = heartbeat_seconds, task_timeout
        self.stopping = threading.Event()
        self.child = None

    def stop(self, *_):
        self.stopping.set()

    def run_once(self):
        lease = self.queue.claim(self.worker_id)
        pulse()  # Successful DB contact, including an idle queue.
        if lease is None:
            return False
        child = receiver = sender = None
        try:
            with self.engine.connect() as c:
                run = self.repo.get_run(c, lease.run_id)
                payload = {"run_id": str(lease.run_id), "dataset_id": str(run["dataset_id"]),
                           "job_id": str(lease.job_id), "worker_id": lease.worker_id,
                           "attempt_id": str(lease.attempt_id), "fence": lease.fence,
                           "stage": lease.stage, "config": run["config"]}
            context = mp.get_context("spawn")
            receiver, sender = context.Pipe(duplex=False)
            child = context.Process(target=_compute, args=(self.handler, payload, sender, os.getpid()), daemon=True)
            self.child = child
            child.start()
            sender.close()
            deadline, next_heartbeat = time.monotonic()+self.task_timeout, time.monotonic()
            message = None
            while not self.stopping.is_set():
                now = time.monotonic()
                if now >= deadline:
                    raise TaskFailure("TASK_TIMEOUT")
                if now >= next_heartbeat:
                    self.queue.heartbeat(lease)
                    pulse()
                    next_heartbeat = now+self.heartbeat_seconds
                if receiver.poll(min(.05, self.heartbeat_seconds)):
                    try:
                        message = json.loads(receiver.recv_bytes(MAX_RESULT_BYTES))
                    except (EOFError, OSError, ValueError):
                        child.join(timeout=.2)
                        raise TaskFailure(RESOURCE_EXIT_CODES.get(child.exitcode,"INVALID_WORKER_RESULT")) from None
                    break
                if not child.is_alive():
                    raise TaskFailure(RESOURCE_EXIT_CODES.get(child.exitcode,"COMPUTE_PROCESS_EXITED"))
            if self.stopping.is_set():
                raise TaskFailure("WORKER_SHUTDOWN", retryable=True)
            if not isinstance(message, dict):
                raise TaskFailure("INVALID_WORKER_RESULT")
            if not message.get("ok"):
                raise TaskFailure(message.get("code", "INVALID_WORKER_RESULT"), message.get("retryable", False))
            result = message["result"]
            def publish(c):
                published = {}
                for artifact in result.get("artifacts", []):
                    row = self.repo.add_artifact(c, lease.run_id, lease.attempt_id, **artifact)
                    published.setdefault(artifact["kind"], []).append(row)
                if result.get("report_kind"):
                    if result["report_kind"] != "report_json" or any(
                            len(published.get(kind, [])) != 1 for kind in ("report_json", "report_html", "report_csv")):
                        raise TaskFailure("INCOMPLETE_REPORT_EXPORTS")
                    self.repo.add_report(c, lease.run_id, published["report_json"][0]["id"])
                c.execute(text("UPDATE runs SET progress=CAST(:result AS jsonb) WHERE id=:id"),
                          {"id": lease.run_id, "result": json.dumps(result.get("summary", {}), allow_nan=False)})
            self.queue.finish(lease, publish)
        except TaskFailure as error:
            try:
                self.queue.fail(lease, error.code, retryable=error.retryable)
            except (LeaseLost, SQLAlchemyError):
                pass  # Lost DB/ownership: leave recovery to the durable lease, not an in-memory state.
        except (LeaseLost, SQLAlchemyError):
            pass
        except Exception:
            try:
                self.queue.fail(lease, "WORKER_INTERNAL_ERROR")
            except (LeaseLost, SQLAlchemyError):
                pass
        finally:
            if child is not None and child.pid is not None:
                if child.is_alive():
                    child.terminate()
                child.join(timeout=2)
                if child.is_alive():
                    child.kill()
                    child.join(timeout=2)
                child.close()
            self.child = None
            if receiver:
                receiver.close()
            if sender:
                sender.close()
        return True

    def run_forever(self, poll_seconds=1):
        while not self.stopping.is_set():
            try:
                had_work = self.run_once()
            except SQLAlchemyError:
                had_work = False
            if not had_work:
                self.stopping.wait(poll_seconds)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    engine = database_engine()
    worker = Worker(engine)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, worker.stop)
    try:
        worker.run_once() if args.once else worker.run_forever()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
