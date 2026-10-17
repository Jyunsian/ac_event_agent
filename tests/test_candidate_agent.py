from sqlalchemy import text
import json
import os
import socket
import subprocess
import threading
import uvicorn
import pytest
from server.api.main import create_app

from server.agent_queue import AgentQueue
from server.worker import Worker
from tests.test_jobs import jobdb
from tests.test_upload_api import api
from tests.test_pipeline import create_run, configure_worker


def test_full_catalog_agent_scope_references_and_no_new_jobs(api, jobdb, tmp_path, monkeypatch):
    client, engine, storage = api
    run = create_run(jobdb, storage, tmp_path/'source'); rid = str(run['id'])
    configure_worker(engine, storage, monkeypatch)
    assert Worker(engine, task_timeout=120).run_once()
    before_report = client.get(f'/api/runs/{rid}/reports/1/json')
    assert before_report.status_code == 200
    assert before_report.json()['candidates'] == []  # Test the non-priority path, not a vacuous top-10 comparison.
    cid = client.post(f'/api/runs/{rid}/conversations', headers={'Idempotency-Key':'c'}).json()['id']
    sent = client.post(f'/api/conversations/{cid}/messages', headers={'Idempotency-Key':'m'},
                      json={'content':'查看全部候選', 'selected_run_id':rid}).json()
    claim = AgentQueue(engine).claim('catalog-test')
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN', 'synthetic-internal-token')
    headers = {'Authorization':'Bearer synthetic-internal-token'}
    body = {'turn_id':sent['turn_id'], 'parent_run_id':rid, 'worker_id':claim['worker_id'],
            'fence':claim['fence'], 'tool_call_id':'catalog-read', 'arguments':{}}
    with engine.connect() as c:
        before = c.execute(text('SELECT count(*) FROM jobs')).scalar_one()
    search = client.post('/internal/tools/search_candidates', headers=headers, json=body)
    assert search.status_code == 200, search.text
    result = search.json()
    assert 0 < len(result['content']['items']) <= 50
    assert result['content']['evaluated_count'] > 10
    assert 'object_key' not in search.text
    entry = result['content']['items'][0]
    reference = result['references'][0]
    assert reference['json_pointer'].startswith('/entries/')
    route = f"/api/runs/{rid}/references/{reference['artifact_id']}"
    resolved = client.get(route, params={'version':1, 'pointer':reference['json_pointer']})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()['candidate_id'] == entry['candidate_id']
    assert client.get(route, params={'version':2, 'pointer':reference['json_pointer']}).status_code == 404
    assert client.get(route, params={'version':1, 'pointer':'/entries/9999'}).status_code == 404
    compared = client.post('/internal/tools/compare_candidates', headers=headers,
                          json={**body, 'arguments':{'candidate_ids':[entry['candidate_id']]}})
    assert compared.status_code == 200, compared.text
    candidate = compared.json()['content']['candidates'][0]
    assert candidate['candidate_id'] == entry['candidate_id']
    assert candidate['evidence_id'] == entry['evidence_id']
    finding=client.post('/internal/tools/save_findings',headers=headers,json={**body,
        'tool_call_id':'save-unselected','arguments':{'candidate_id':entry['candidate_id'],
        'hypothesis':'合成測試：記錄未入優先清單的條件','limitations':['樣本不足，不代表投放效果'],'counterexamples':[]}})
    assert finding.status_code==200,finding.text
    assert finding.json()['references'][0]['evidence_id']==entry['evidence_id']
    loaded=client.post('/internal/tools/load_app_findings',headers=headers,
                      json={**body,'tool_call_id':'load-unselected','arguments':{}})
    assert loaded.status_code==200,loaded.text
    assert loaded.json()['items'][0]['candidate_id']==entry['candidate_id']
    assert loaded.json()['items'][0]['requires_new_batch_validation'] is True
    assert loaded.json()['references'][0]['evidence_id']==entry['evidence_id']
    for args in ({'page':41}, {'page':True}, {'descending':'false'}, {'run_id':rid}):
        assert client.post('/internal/tools/search_candidates', headers=headers,
                           json={**body, 'arguments':args}).status_code == 422
    assert client.post('/internal/tools/compare_candidates', headers=headers,
                       json={**body,'arguments':{'candidate_ids':[str(i) for i in range(11)]}}).status_code == 422
    assert client.post('/internal/tools/search_candidates', headers=headers,
                       json={**body,'fence':claim['fence']+1}).status_code == 409
    assert client.get(f'/api/runs/{rid}/reports/1/json').content == before_report.content
    subprocess.run(['npm','run','build','--workspace=agent'], check=True, capture_output=True, timeout=30)
    listener=socket.socket(); listener.bind(('127.0.0.1',0)); listener.listen()
    url=f'http://127.0.0.1:{listener.getsockname()[1]}'
    server=uvicorn.Server(uvicorn.Config(create_app(engine,storage),log_level='warning',access_log=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True); thread.start()
    try:
        scope={key:body[key] for key in ('turn_id','parent_run_id','worker_id','fence')}
        process=subprocess.run(['node','agent/catalog.integration.mjs',url,json.dumps(scope)],
            env={**os.environ,'AGENT_INTERNAL_TOKEN':'synthetic-internal-token'},
            capture_output=True,text=True,timeout=30)
        assert process.returncode==0,process.stdout+process.stderr
        assert json.loads(process.stdout)['steps']==3
    finally:
        server.should_exit=True; thread.join(10); listener.close()
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM jobs')).scalar_one() == before
        calls=c.execute(text('SELECT tool_name FROM agent_tool_calls WHERE turn_id=:turn ORDER BY ordinal'),
                        {'turn':sent['turn_id']}).scalars().all()
        assert calls == ['search_candidates','compare_candidates']
    client.post(f"/api/turns/{sent['turn_id']}/cancel", headers={'Idempotency-Key':'cancel'})
    selected = client.post(f'/api/conversations/{cid}/messages', headers={'Idempotency-Key':'selected'},
        json={'content':'解釋這個非優先候選','selected_run_id':rid,'selected_candidate_id':entry['candidate_id']})
    assert selected.status_code == 202, selected.text
    # A stored non-priority observation carries its exact rule to a different
    # batch; the same batch must still be rejected as independent validation.
    from server.finding_rechecks import resolve_sources
    from server.uploads import UploadService, APIError
    from tests.test_search import CONFIG
    service=UploadService(engine,storage)
    finding_ids=[finding.json()['finding_id']]
    with pytest.raises(APIError,match='RECHECK_NEW_BATCH_REQUIRED'):
        resolve_sources(service,run['dataset_id'],finding_ids,CONFIG)
    next_run=create_run(jobdb,storage,tmp_path/'next-source')
    sources=resolve_sources(service,next_run['dataset_id'],finding_ids,CONFIG)
    assert sources[0]['candidate_id']==entry['candidate_id']
    assert sources[0]['event_spec']==candidate['event_spec']
