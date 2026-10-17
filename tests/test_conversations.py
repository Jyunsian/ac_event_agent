from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import pytest
from server.api.main import create_app
from server.worker import Worker
from tests.test_jobs import jobdb, submit
from tests.test_upload_api import api
from tests.test_pipeline import create_run, configure_worker


def test_durable_ordered_messages_and_retry(api, jobdb, tmp_path, monkeypatch):
    client, engine, storage = api
    run = create_run(jobdb, storage, tmp_path/'source')
    rid = str(run['id'])
    route = f'/api/runs/{rid}/conversations'
    assert client.post(route, headers={'Idempotency-Key': 'conversation'}).status_code == 409
    configure_worker(engine, storage, monkeypatch)
    assert Worker(engine, task_timeout=120).run_once()
    response = client.post(route, headers={'Idempotency-Key': 'conversation'})
    assert response.status_code == 201, response.text
    conversation = response.json()['id']
    assert client.post(route, headers={'Idempotency-Key': 'conversation'}).json()['id'] == conversation
    url = f'/api/conversations/{conversation}/messages'
    payload = {'content': '比較小時與天級窗口', 'selected_run_id': rid}
    first = client.post(url, json=payload, headers={'Idempotency-Key': 'first'})
    assert first.status_code == 202, first.text
    assert client.post(url, json=payload, headers={'Idempotency-Key': 'first'}).json() == first.json()
    assert client.post(url, json={**payload, 'content': 'changed'}, headers={'Idempotency-Key': 'first'}).status_code == 409
    assert client.post(url, json={**payload, 'selected_candidate_id': 'not-real'}, headers={'Idempotency-Key': 'invalid'}).status_code == 422
    def send(i):
        r = client.post(url, json={**payload, 'content': f'並行問題 {i}'}, headers={'Idempotency-Key': f'parallel-{i}'})
        assert r.status_code == 202, r.text
        return r.json()['seq']
    with ThreadPoolExecutor(max_workers=4) as pool:
        seqs = list(pool.map(send, range(4)))
    assert sorted(seqs) == [2, 3, 4, 5]
    reopened = TestClient(create_app(engine, storage))
    events = f'/api/conversations/{conversation}/events'
    page = reopened.get(events, params={'limit': 2}).json()
    assert [e['seq'] for e in page['events']] == [1, 2]
    assert page['has_more'] and page['next_after'] == 2
    rest = reopened.get(events, params={'after': 2}).json()
    assert [e['seq'] for e in rest['events']] == [3, 4, 5]
    assert rest['events'][0]['payload']['context']['selected_run_id'] == rid
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM messages')).scalar_one() == 5
        assert c.execute(text('SELECT count(*) FROM agent_turns')).scalar_one() == 5
        assert c.execute(text('SELECT next_seq FROM conversations')).scalar_one() == 6
    assert reopened.get(events, params={'after': -1}).status_code == 422
    other = submit(jobdb)
    assert reopened.post(url, json={**payload, 'selected_run_id': str(other['id'])},
                         headers={'Idempotency-Key': 'wrong-root'}).status_code == 409
    with engine.begin() as c:
        ids = c.execute(text('SELECT id FROM agent_turns ORDER BY ordinal')).scalars().all()
        c.execute(text("UPDATE agent_turns SET status='running' WHERE id=:id"), {'id': ids[0]})
    with pytest.raises(IntegrityError), engine.begin() as c:
        c.execute(text("UPDATE agent_turns SET status='running' WHERE id=:id"), {'id': ids[1]})
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM agent_turns WHERE status='running'")).scalar_one() == 1


def test_selected_report_version_is_pinned_in_message_context(api,jobdb,tmp_path,monkeypatch):
    import subprocess
    import tempfile
    from pathlib import Path
    from tests.browser_runtime import live_web
    client,engine,storage=api
    _,repo,_=jobdb
    run=create_run(jobdb,storage,tmp_path/'source');rid=str(run['id'])
    configure_worker(engine,storage,monkeypatch)
    assert Worker(engine,task_timeout=120).run_once()
    original=client.get(f'/api/runs/{rid}/reports/1/json').content
    artifact=client.get(f'/api/runs/{rid}/view').json()['report_artifact_id']
    # Metadata version fixture deliberately shares the immutable calculation artifact.
    # This tests selection/context, not narrative generation (PH37).
    with engine.begin() as c:repo.add_report(c,run['id'],artifact,version=2)
    assert client.get(f'/api/runs/{rid}/view').json()['report_version']==2
    old=client.get(f'/api/runs/{rid}/view?version=1&artifact={artifact}').json()
    assert old['ready'] and old['report_version']==1
    first=client.get(f'/api/runs/{rid}/branch-reports?limit=1').json()
    assert first['items'][0]['report_version']==2
    second=client.get(f'/api/runs/{rid}/branch-reports',params={'limit':1,'cursor':first['next_cursor']}).json()
    assert second['items'][0]['report_version']==1 and second['next_cursor'] is None
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'versions'}).json()['id']
    url=f'/api/conversations/{cid}/messages'
    body={'content':'解釋我選定的舊版','selected_run_id':rid,'report_version':1}
    sent=client.post(url,json=body,headers={'Idempotency-Key':'old'})
    assert sent.status_code==202 and sent.json()['context']['report_version']==1
    assert client.post(url,json={**body,'report_version':999},headers={'Idempotency-Key':'missing'}).status_code==404
    assert client.post(url,json={**body,'report_version':True},headers={'Idempotency-Key':'bool'}).status_code==422
    with engine.connect() as c:
        assert c.execute(text('SELECT report_version FROM agent_turns WHERE conversation_id=:id'),{'id':cid}).scalar_one()==1
    assert client.get(f'/api/runs/{rid}/reports/1/json').content==original
    visual=Path(tempfile.mkdtemp(prefix='version-ui-',dir=Path('.runtime').resolve()))
    with live_web(engine,storage,visual) as base:
        checked=subprocess.run(['node','scripts/version_browser_qa.cjs',base,rid,cid,str(visual/'visual')],
                               capture_output=True,text=True,timeout=40)
        print(f'Version browser evidence: {visual}\n{checked.stdout}')
        assert checked.returncode==0,checked.stdout+checked.stderr
