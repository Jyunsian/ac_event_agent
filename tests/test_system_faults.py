import errno
import os
import subprocess
import sys
import time
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from scripts.local_postgres import LocalPostgres
from scripts.local_s3 import LocalS3
from server.db import database_engine,Repository
from server.storage import S3Storage
from server.api.main import create_app
from server.worker import Worker,baseline_handler
from tests.test_pipeline import create_run,configure_worker
from tests.test_jobs import jobdb
from tests.test_upload_api import api


def disk_full_baseline(payload):
    # Inject the OS errno at the actual raw-file allocation boundary, not fake report output.
    # Never fill the host filesystem to induce failure.
    with patch('server.storage.tempfile.mkstemp',side_effect=OSError(errno.ENOSPC,'synthetic disk full')):
        return baseline_handler(payload)


def test_disk_full_is_terminal_without_report_or_unbounded_retry(api,jobdb,tmp_path,monkeypatch):
    client,engine,storage=api
    run=create_run(jobdb,storage,tmp_path/'source');rid=str(run['id'])
    configure_worker(engine,storage,monkeypatch)
    assert Worker(engine,disk_full_baseline,task_timeout=30).run_once()
    with engine.connect() as c:
        job=c.execute(text('SELECT status,error,attempt_number FROM jobs WHERE run_id=:id'),{'id':rid}).mappings().one()
        assert job['status']=='failed' and job['error']=={'code':'DISK_FULL'} and job['attempt_number']==1
        assert c.execute(text('SELECT count(*) FROM report_versions WHERE run_id=:id'),{'id':rid}).scalar_one()==0
    assert not client.get(f'/api/runs/{rid}/view').json()['ready']
    assert not Worker(engine).run_once()


def test_real_db_and_s3_stop_api_failure_and_compute_recovery(tmp_path,monkeypatch):
    with LocalPostgres() as pg,LocalS3() as s3:
        subprocess.run([sys.executable,'-m','alembic','upgrade','head'],check=True,
            env={**os.environ,'DATABASE_URL':pg.url},capture_output=True,timeout=30)
        engine=database_engine(pg.url)
        try:
            storage=S3Storage('fault-synthetic',s3.endpoint,s3.access_key,s3.secret_key,timeout=1);storage.create_bucket()
            configure_worker(engine,storage,monkeypatch)
            db=(engine,Repository(engine),None)
            run=create_run(db,storage,tmp_path/'original');rid=str(run['id'])
            worker=Worker(engine,task_timeout=60);assert worker.run_once()
            with TestClient(create_app(engine,storage)) as client:
                path=f'/api/runs/{rid}/reports/1/json'
                original=client.get(path);assert original.status_code==200
                pg.stop()
                try:
                    failure=client.get(path);assert failure.status_code==503
                    assert failure.json()['error_code']=='DATABASE_UNAVAILABLE'
                    with pytest.raises(SQLAlchemyError):worker.run_once()
                finally:pg.start()
                assert client.get(path).content==original.content
                child=create_run(db,storage,tmp_path/'second');second=str(child['id'])
                s3.stop()
                try:
                    failure=client.get(path);assert failure.status_code==503
                    assert failure.json()['error_code']=='STORAGE_UNAVAILABLE'
                    assert worker.run_once()
                    with engine.connect() as c:
                        job=c.execute(text('SELECT status,error FROM jobs WHERE run_id=:id'),{'id':second}).mappings().one()
                        assert job['status']=='queued' and job['error']['code']=='STORAGE_UNAVAILABLE'
                        assert c.execute(text('SELECT count(*) FROM report_versions WHERE run_id=:id'),{'id':second}).scalar_one()==0
                finally:s3.start()
                deadline=time.monotonic()+10
                while not worker.run_once():
                    assert time.monotonic()<deadline
                    time.sleep(.05)
                assert client.get(f'/api/runs/{second}/view').json()['ready']
                assert client.get(path).content==original.content
                with engine.connect() as c:
                    assert c.execute(text('SELECT attempt_number FROM jobs WHERE run_id=:id'),{'id':second}).scalar_one()==2
        finally:engine.dispose()
