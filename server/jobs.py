"""Short PostgreSQL transactions for at-least-once jobs with fenced lease ownership."""
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import text


class LeaseLost(Exception):
    pass


@dataclass(frozen=True)
class Lease:
    job_id: UUID
    run_id: UUID
    attempt_id: UUID
    fence: int
    worker_id: str
    stage: str


class JobQueue:
    def __init__(self, engine, lease_seconds=90):
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.engine, self.lease_seconds = engine, lease_seconds

    def claim(self, worker_id, queue="compute"):
        if queue not in ("compute", "agent") or not worker_id:
            raise ValueError("Invalid queue or worker")
        with self.engine.begin() as c:
            # Exhausted expired jobs are terminalized as part of claiming, never stranded running.
            exhausted = c.execute(text("""
                SELECT id, run_id FROM jobs WHERE queue=:queue AND status='running'
                    AND lease_until <= clock_timestamp() AND attempt_number >= max_attempts
                FOR UPDATE SKIP LOCKED
            """), {"queue": queue}).mappings().all()
            for job in exhausted:
                self._terminal(c, job["id"], job["run_id"], "failed", "RETRY_LIMIT")
            job = c.execute(text("""
                SELECT * FROM jobs WHERE queue=:queue AND cancel_requested=false
                  AND attempt_number < max_attempts AND available_at <= clock_timestamp()
                  AND (status='queued' OR (status='running' AND lease_until <= clock_timestamp()))
                ORDER BY created_at, id FOR UPDATE SKIP LOCKED LIMIT 1
            """), {"queue": queue}).mappings().one_or_none()
            if job is None:
                return None
            c.execute(text("""UPDATE job_attempts SET outcome='expired', finished_at=clock_timestamp()
                            WHERE job_id=:id AND finished_at IS NULL"""), {"id": job["id"]})
            fence, attempt_id = job["fence"]+1, uuid4()
            c.execute(text("""
                UPDATE jobs SET status='running', worker_id=:worker, fence=:fence,
                    attempt_number=attempt_number+1,
                    lease_until=clock_timestamp()+:seconds*interval '1 second'
                WHERE id=:id
            """), {"id": job["id"], "worker": worker_id, "fence": fence, "seconds": self.lease_seconds})
            c.execute(text("""INSERT INTO job_attempts(id,job_id,run_id,attempt_number,fence)
                       VALUES (:attempt,:id,:run,:number,:fence)"""),
                      {"attempt": attempt_id, "id": job["id"], "run": job["run_id"],
                       "number": job["attempt_number"]+1, "fence": fence})
            c.execute(text("UPDATE runs SET status='running', error=NULL WHERE id=:id"), {"id": job["run_id"]})
            return Lease(job["id"], job["run_id"], attempt_id, fence, worker_id, job["stage"])

    def _owned(self, c, lease):
        row = c.execute(text("""
            SELECT * FROM jobs WHERE id=:id AND fence=:fence AND worker_id=:worker
                AND status='running' AND cancel_requested=false
                AND lease_until > clock_timestamp() FOR UPDATE
        """), {"id": lease.job_id, "fence": lease.fence, "worker": lease.worker_id}).mappings().one_or_none()
        if row is None:
            raise LeaseLost("Lease expired, cancelled or superseded")
        return row

    def heartbeat(self, lease):
        with self.engine.begin() as c:
            self._owned(c, lease)
            c.execute(text("""UPDATE jobs SET lease_until=clock_timestamp()+:seconds*interval '1 second'
                              WHERE id=:id"""), {"id": lease.job_id, "seconds": self.lease_seconds})

    def finish(self, lease, publish=None):
        """Publish metadata and terminal state atomically. Callback must not do network or computation."""
        with self.engine.begin() as c:
            self._owned(c, lease)
            if publish:
                publish(c)
            # Guard again immediately before publication commit after callback execution.
            self._owned(c, lease)
            self._terminal(c, lease.job_id, lease.run_id, "succeeded", None)

    def fail(self, lease, code, retryable=False, retry_delay=1):
        if retry_delay < 0:
            raise ValueError("retry_delay must be nonnegative")
        with self.engine.begin() as c:
            job = self._owned(c, lease)
            if retryable and job["attempt_number"] < job["max_attempts"]:
                c.execute(text("""UPDATE jobs SET status='queued', worker_id=NULL, lease_until=NULL,
                    error=jsonb_build_object('code',CAST(:code AS text)),
                    available_at=clock_timestamp()+:delay*interval '1 second' WHERE id=:id"""),
                          {"id": lease.job_id, "code": code, "delay": retry_delay})
                c.execute(text("""UPDATE job_attempts SET outcome='failed', finished_at=clock_timestamp(),
                    error=jsonb_build_object('code',CAST(:code AS text)) WHERE id=:id"""),
                          {"id": lease.attempt_id, "code": code})
                c.execute(text("UPDATE runs SET status='queued' WHERE id=:id"), {"id": lease.run_id})
            else:
                self._terminal(c, lease.job_id, lease.run_id, "failed", code)

    def cancel(self, job_id):
        with self.engine.begin() as c:
            return self.cancel_in_transaction(c,job_id)

    def cancel_in_transaction(self,c,job_id):
        job=c.execute(text('SELECT * FROM jobs WHERE id=:id FOR UPDATE'),{'id':job_id}).mappings().one()
        if job['status'] in ('succeeded','failed','cancelled'):return job['status']
        c.execute(text('UPDATE jobs SET cancel_requested=true,fence=fence+1 WHERE id=:id'),{'id':job_id})
        self._terminal(c,job_id,job['run_id'],'cancelled','CANCELLED')
        return 'cancelled'

    @staticmethod
    def _terminal(c, job_id, run_id, status, code):
        params = {"id": job_id, "run": run_id, "status": status, "code": code}
        c.execute(text("""UPDATE jobs SET status=:status, lease_until=NULL, worker_id=NULL,
            error=CASE WHEN CAST(:code AS text) IS NULL THEN NULL ELSE jsonb_build_object('code',CAST(:code AS text)) END
            WHERE id=:id"""), params)
        c.execute(text("""UPDATE runs SET status=:status,
            error=CASE WHEN CAST(:code AS text) IS NULL THEN NULL ELSE jsonb_build_object('code',CAST(:code AS text)) END
            WHERE id=:run"""), params)
        c.execute(text("""UPDATE job_attempts SET outcome=:status, finished_at=clock_timestamp(),
            error=CASE WHEN CAST(:code AS text) IS NULL THEN NULL ELSE jsonb_build_object('code',CAST(:code AS text)) END
            WHERE job_id=:id AND finished_at IS NULL"""), params)
