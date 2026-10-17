"""Fault injection only: kill a live Worker after the real fixed-rule checkpoint."""
import multiprocessing as mp
import time
from sqlalchemy import text
from server.db import database_engine
from server.worker import Worker,baseline_handler


def barrier_handler(payload):
    import server.pipeline as pipeline
    original=pipeline.evaluate_candidates
    def wait_before_triggers(*args,**kwargs):
        engine=database_engine()
        try:
            with engine.connect() as c:
                c.execute(text('SELECT pg_advisory_lock(350036)'))
                c.execute(text('SELECT pg_advisory_unlock(350036)'))
        finally:engine.dispose()
        return original(*args,**kwargs)
    pipeline.evaluate_candidates=wait_before_triggers
    return baseline_handler(payload)


def interrupted_worker(url):
    engine=database_engine(url)
    try:Worker(engine,handler=barrier_handler,lease_seconds=3,heartbeat_seconds=.3,task_timeout=120).run_once()
    finally:engine.dispose()


def recover_fixed_recheck(engine,run_id):
    lock=engine.connect();lock.execute(text('SELECT pg_advisory_lock(350036)'))
    process=mp.get_context('spawn').Process(target=interrupted_worker,
        args=(engine.url.render_as_string(hide_password=False),))
    process.start()
    try:
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            with engine.connect() as c:
                blocked=c.execute(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid=350036 AND NOT granted")).scalar_one()
            if blocked:break
            assert process.is_alive(),'Worker exited before fixed checkpoint'
            time.sleep(.02)
        assert blocked==1,'Real compute subprocess never reached barrier'
        with engine.connect() as c:
            snapshot=dict(c.execute(text('SELECT * FROM finding_rechecks WHERE run_id=:id'),{'id':run_id}).mappings().one())
            fixed=dict(c.execute(text("SELECT * FROM stage_checkpoints WHERE run_id=:id AND stage='fixed_recheck'"),{'id':run_id}).mappings().one())
            assert c.execute(text('SELECT count(*) FROM report_versions WHERE run_id=:id'),{'id':run_id}).scalar_one()==0
        process.kill();process.join(5)
        assert process.exitcode is not None and process.exitcode!=0
        # PostgreSQL may not notice a disconnected socket while its query is lock-blocked.
        # Release only the test barrier so that backend can finish and close normally.
        lock.execute(text('SELECT pg_advisory_unlock(350036)'))
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            with engine.connect() as c:
                expired=c.execute(text('SELECT lease_until<=clock_timestamp() FROM jobs WHERE run_id=:id'),{'id':run_id}).scalar_one()
                orphan=c.execute(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid=350036 AND NOT granted")).scalar_one()
            if expired and not orphan:break
            time.sleep(.05)
        assert expired and not orphan,'Lease or orphan computation remained live'
        assert Worker(engine,lease_seconds=3,heartbeat_seconds=.3,task_timeout=120).run_once()
        with engine.connect() as c:
            saved=c.execute(text('SELECT status,progress FROM runs WHERE id=:id'),{'id':run_id}).mappings().one()
            assert saved['status']=='succeeded',saved
            assert saved['progress']['stage_modes']['fixed_recheck']=='restored'
            assert c.execute(text('SELECT attempt_number FROM jobs WHERE run_id=:id'),{'id':run_id}).scalar_one()==2
            assert c.execute(text('SELECT count(*) FROM report_versions WHERE run_id=:id'),{'id':run_id}).scalar_one()==1
            assert dict(c.execute(text('SELECT * FROM finding_rechecks WHERE run_id=:id'),{'id':run_id}).mappings().one())==snapshot
            assert dict(c.execute(text("SELECT * FROM stage_checkpoints WHERE run_id=:id AND stage='fixed_recheck'"),{'id':run_id}).mappings().one())==fixed
    finally:
        if process.is_alive():process.kill()
        process.join(5);process.close()
        lock.execute(text('SELECT pg_advisory_unlock(350036)'));lock.close()
