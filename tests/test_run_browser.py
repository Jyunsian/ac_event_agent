import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from sqlalchemy import text
from server.jobs import JobQueue
from server.worker import Worker
from tests.browser_runtime import live_web
from tests.test_jobs import jobdb, submit
from tests.test_pipeline import create_run, configure_worker
from tests.test_upload_api import api


def test_caller_closes_real_worker_finishes_and_history_restores(api,jobdb,tmp_path,monkeypatch):
    from tests.positive_sources import positive_sources,POSITIVE_EXPORT
    monkeypatch.setattr('tests.test_pipeline.sources',positive_sources)
    monkeypatch.setattr('tests.test_pipeline.EXPORT',POSITIVE_EXPORT)
    _,engine,storage=api
    queue=JobQueue(engine)
    failed=submit(jobdb);queue.fail(queue.claim('synthetic-timeout'),'TASK_TIMEOUT')
    legacy=submit(jobdb);queue.finish(queue.claim('synthetic-unpublished-completion'))
    run=create_run(jobdb,storage,tmp_path/'source')
    config=tmp_path/'config.json';config.write_text(json.dumps({'runId':str(run['id']),'failedId':str(failed['id']),'legacyId':str(legacy['id'])}))
    configure_worker(engine,storage,monkeypatch)
    with live_web(engine,storage,tmp_path) as url:
        process=subprocess.Popen(['node','scripts/run_browser_qa.cjs',url,str(config),str(tmp_path/'visual')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if (tmp_path/'visual/caller-closed').exists():break
                assert process.poll() is None,process.communicate()
                time.sleep(.05)
            else:raise AssertionError('Browser did not close caller')
            assert Worker(engine,task_timeout=120).run_once()
            out,err=process.communicate(timeout=90)
            assert process.returncode==0,out+err
            with engine.connect() as c:
                assert c.execute(text('SELECT status FROM runs WHERE id=:id'),{'id':run['id']}).scalar_one()=='succeeded'
                assert c.execute(text('SELECT status FROM runs WHERE id=:id'),{'id':failed['id']}).scalar_one()=='queued'
            retained=Path(tempfile.mkdtemp(prefix='run-ui-',dir=Path('.runtime')))
            shutil.copytree(tmp_path/'visual',retained/'visual');print(f'Browser evidence retained: {retained.resolve()}')
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=10)
