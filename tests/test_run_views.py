from uuid import uuid4
from sqlalchemy import text
from fastapi.testclient import TestClient
from server.api.main import create_app
from server.jobs import JobQueue, LeaseLost
from tests.test_jobs import jobdb, submit
from tests.test_upload_api import api, request
import pytest


def test_history_cursor_and_service_reopen(api, jobdb):
    client, engine, storage = api
    ids = [str(submit(jobdb)["id"]) for _ in range(3)]
    first = client.get('/api/runs?limit=2').json()
    assert [r['run_id'] for r in first['items']] == list(reversed(ids))[:2]
    cursor = first['next_cursor']
    # New rows do not shift the keyset cursor into duplication.
    submit(jobdb)
    with TestClient(create_app(engine, storage)) as reopened:
        rest = reopened.get('/api/runs', params={'limit':2,'cursor':cursor}).json()
        assert [r['run_id'] for r in rest['items']] == [ids[0]]
        assert rest['next_cursor'] is None
        assert len(reopened.get('/api/runs').json()['items']) == 4
        assert reopened.get('/api/runs?cursor=bad').status_code == 422
        assert reopened.get('/api/runs?limit=0').status_code == 422


def test_retry_keeps_attempts_fences_stale_worker_and_is_idempotent(api, jobdb):
    client, engine, _ = api
    run = submit(jobdb); base = f'/api/runs/{run["id"]}'
    queue = JobQueue(engine); lease = queue.claim('technical-failure')
    queue.fail(lease,'TASK_TIMEOUT')
    view = client.get(base+'/view').json()
    assert view['can_retry'] and not view['ready'] and view['error']['code']=='TASK_TIMEOUT'
    key=str(uuid4())
    response=request(client,'POST',base+'/retry',{},key)
    assert response.status_code==202
    assert request(client,'POST',base+'/retry',{},key).json()==response.json()
    assert request(client,'POST',base+'/retry',{}).status_code==409
    with pytest.raises(LeaseLost): queue.finish(lease)
    next_lease=queue.claim('manual-retry')
    assert next_lease.attempt_id!=lease.attempt_id and next_lease.fence>lease.fence
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM job_attempts WHERE job_id=:id'),{'id':lease.job_id}).scalar_one()==2
    queue.fail(next_lease,'INVALID_BASELINE_DATASET')
    assert not client.get(base+'/view').json()['can_retry']
    assert request(client,'POST',base+'/retry',{}).status_code==409


def test_succeeded_without_report_is_not_ready_and_cannot_retry(api, jobdb):
    client, engine, _ = api
    run=submit(jobdb); queue=JobQueue(engine);lease=queue.claim('legacy-completion')
    queue.finish(lease)
    response=client.get(f'/api/runs/{run["id"]}/view')
    assert response.json()['status']=='succeeded'
    assert response.json()['ready'] is False and not response.json()['can_retry']
    assert client.get(f'/api/runs/{uuid4()}/view').status_code==404


def test_partial_published_metadata_blocks_retry_and_ready(api,jobdb):
    client,engine,storage=api
    _,repo,_=jobdb
    run=submit(jobdb);queue=JobQueue(engine);lease=queue.claim('synthetic-partial-metadata')
    obj=storage.put_bytes(storage.new_key('synthetic-partial-report','json'),b'{}')
    with engine.begin() as c:
        artifact=repo.add_artifact(c,run['id'],lease.attempt_id,'report_json',obj.object_key,obj.sha256,obj.size_bytes)
        repo.add_report(c,run['id'],artifact['id'])
    queue.fail(lease,'TASK_TIMEOUT')
    base=f'/api/runs/{run["id"]}'
    view=client.get(base+'/view').json()
    assert not view['ready'] and not view['can_retry']
    assert request(client,'POST',base+'/retry',{}).json()['error_code']=='PUBLISHED_RUN_CANNOT_RETRY'
