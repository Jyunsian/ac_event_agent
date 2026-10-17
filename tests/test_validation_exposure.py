import concurrent.futures
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from fastapi.testclient import TestClient
from server.api.main import create_app
from server.worker import Worker
from server.storage import StorageError
from server.run_views import run_view
from server.uploads import UploadService
from tests.test_jobs import jobdb
from tests.test_upload_api import api
from tests.test_pipeline import create_run,configure_worker


def test_disclosure_is_durable_cross_conversation_and_append_only(api,jobdb,tmp_path,monkeypatch):
    client,engine,storage=api
    run=create_run(jobdb,storage,tmp_path/'source');rid=str(run['id'])
    configure_worker(engine,storage,monkeypatch);assert Worker(engine,task_timeout=120).run_once()
    assert run_view(UploadService(engine,storage),run['id'])['ready']
    first=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'first'}).json()['id']
    assert client.get(f'/api/runs/{rid}/reports/9/json').status_code==409
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM validation_exposures')).scalar_one()==0
    original_get=storage.get_bytes
    def unavailable(*args,**kwargs):raise StorageError('STORAGE_UNAVAILABLE',retryable=True)
    monkeypatch.setattr(storage,'get_bytes',unavailable)
    assert client.get(f'/api/runs/{rid}/reports/1/json').status_code==503
    monkeypatch.setattr(storage,'get_bytes',original_get)
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM validation_exposures')).scalar_one()==0
    # Concurrent exports publish one first-disclosure record, not one per session.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda format:client.get(f'/api/runs/{rid}/reports/1/{format}'),['json','html','csv']))
    assert all(response.status_code==200 for response in results)
    report=results[0].json()
    with engine.connect() as c:
        before=dict(c.execute(text('SELECT * FROM validation_exposures')).mappings().one())
        assert before['split_id']==report['summary']['targets']['split_id']
        assert str(before['dataset_id'])==str(run['dataset_id'])
        assert before['channel']=='report_export'
    with TestClient(create_app(engine,storage)) as reopened:
        second=reopened.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'second'}).json()['id']
        assert second!=first
        assert reopened.get(f'/api/runs/{rid}/reports/1/json').status_code==200
    with engine.connect() as c:
        assert dict(c.execute(text('SELECT * FROM validation_exposures')).mappings().one())==before
    with pytest.raises(DBAPIError):
        with engine.begin() as c:c.execute(text('DELETE FROM validation_exposures'))
    with pytest.raises(DBAPIError):
        with engine.begin() as c:c.execute(text("UPDATE validation_exposures SET split_id='reset'"))
