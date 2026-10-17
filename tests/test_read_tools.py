from sqlalchemy import text
import json
import os
import socket
import subprocess
import threading
import uvicorn
from server.api.main import create_app
from server.agent_queue import AgentQueue
from server.worker import Worker
from tests.test_jobs import jobdb
from tests.test_upload_api import api
from tests.test_pipeline import create_run, configure_worker


def test_scoped_read_tools_real_report_and_no_jobs(api,jobdb,tmp_path,monkeypatch):
    client,engine,storage=api
    run=create_run(jobdb,storage,tmp_path/'source');rid=str(run['id'])
    configure_worker(engine,storage,monkeypatch);assert Worker(engine,task_timeout=120).run_once()
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'c'}).json()['id']
    sent=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'m'},json={'content':'Compare evidence','selected_run_id':rid}).json()
    claim=AgentQueue(engine).claim('readonly-test')
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-internal-token')
    body={'turn_id':sent['turn_id'],'parent_run_id':rid,'worker_id':claim['worker_id'],'fence':claim['fence'],
          'tool_call_id':'read-1','arguments':{}}
    headers={'Authorization':'Bearer synthetic-internal-token'}
    with engine.connect() as c:before=c.execute(text('SELECT count(*) FROM jobs')).scalar_one()
    route='/internal/tools/get_baseline_report'
    assert client.post(route,json=body).status_code==401
    result=client.post(route,json=body,headers=headers)
    assert result.status_code==200,result.text
    data=result.json();assert data['run_id']==rid and data['references']
    with engine.connect() as c:
        exposure=c.execute(text('SELECT * FROM validation_exposures')).mappings().one()
        assert exposure['channel']=='agent_tool' and str(exposure['source_run_id'])==rid
    reference=data['references'][0]
    resolved=client.get(f"/api/runs/{rid}/references/{reference['artifact_id']}",params={'version':1,'pointer':reference['json_pointer']})
    assert resolved.status_code==200,resolved.text
    assert resolved.json()['candidate_id'] is None
    assert data['content']['candidates']==[]  # Small exploration sample does not qualify for priority.
    for version,pointer,status in [(2,'/summary',404),(1,'/candidates/9999',404),(1,'/summary/../../private',422)]:
        assert client.get(f"/api/runs/{rid}/references/{reference['artifact_id']}",params={'version':version,'pointer':pointer}).status_code==status
    listed=client.get(f'/api/runs/{rid}/conversations').json()
    assert listed['conversations'][0]['id']==cid
    assert 'object_key' not in result.text
    original=client.get(f'/api/runs/{rid}/reports/1/json').json()
    for i,row in enumerate(data['content']['candidates']):
        assert row['metrics']==original['candidates'][i]['metrics']
        from server.analysis.report_language import condition_name
        assert condition_name(row['event_spec']['predicate']) in row['display_name']
        assert f"{row['event_spec']['window_hours']:g} 小時" in row['display_name']
        assert data['references'][i]['json_pointer']==f'/candidates/{i}'
        assert row['evidence_id']==data['references'][i]['evidence_id']
    assert data['content']['interpretation']['configured_validation_rules']==original['audit']['validation_rules']
    assert 'not the source dataset' in data['content']['interpretation']['candidate_metrics_scope']
    catalog=client.post('/internal/tools/search_candidates',json=body,headers=headers)
    assert catalog.status_code==200,catalog.text
    assert catalog.json()['content']['evaluated_count']>10
    ids=[row['candidate_id'] for row in catalog.json()['content']['items'][:2]]
    assert len(ids)==2
    comparison=client.post('/internal/tools/compare_candidates',json={**body,'arguments':{'candidate_ids':ids}},headers=headers)
    assert comparison.status_code==200,comparison.text
    assert {r['candidate_id'] for r in comparison.json()['content']['candidates']}==set(ids)
    for row in comparison.json()['content']['candidates']:
        detail=client.get(f"/api/runs/{rid}/reports/1/candidates/{row['candidate_id']}").json()['content']
        assert row['metrics']==detail['validation']['metrics']
        from server.analysis.report_language import condition_name
        assert condition_name(row['event_spec']['predicate']) in row['display_name']
        assert f"{row['event_spec']['window_hours']:g} 小時" in row['display_name']
    profile=client.post('/internal/tools/profile_dataset',json=body,headers=headers)
    assert profile.status_code==200,profile.text
    assert profile.json()['content']['users']==original['summary']['data_profile']['users']
    for name,args in [('get_baseline_report',{'run_id':rid}),('shell',{}),('compare_candidates',{'candidate_ids':['unknown']})]:
        assert client.post(f'/internal/tools/{name}',json={**body,'arguments':args},headers=headers).status_code==422
    assert client.post(route,json={**body,'fence':claim['fence']+1},headers=headers).status_code==409
    subprocess.run(['npm','run','build','--workspace','agent'],check=True,capture_output=True,timeout=30)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
    url=f'http://127.0.0.1:{listener.getsockname()[1]}'
    server=uvicorn.Server(uvicorn.Config(create_app(engine,storage),log_level='warning',access_log=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        scope={k:body[k] for k in ('turn_id','parent_run_id','worker_id','fence')}
        process=subprocess.run(['node','agent/readonly.integration.mjs',url,json.dumps(scope),json.dumps(ids)],
            env={**os.environ,'AGENT_INTERNAL_TOKEN':'synthetic-internal-token'},capture_output=True,text=True,timeout=30)
        assert process.returncode==0,process.stdout+process.stderr
        result=json.loads(process.stdout);assert result['steps']==4 and result['invalidReferenceRejected']
        # Release the earlier direct-read test claim, then use the production
        # Node worker to claim, read context, renew, invoke tools and finish.
        assert client.post(f"/api/turns/{sent['turn_id']}/cancel",headers={'Idempotency-Key':'cancel-read'}).status_code==200
        sent2=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'worker-message'},
            json={'content':'請解釋目前選中的候選','selected_run_id':rid,'selected_candidate_id':ids[0]}).json()
        assert client.post('/internal/agent/claim',json={'worker_id':'unauthorized'}).status_code==401
        process=subprocess.run(['node','agent/worker.integration.mjs',url,ids[0]],
            env={**os.environ,'AGENT_INTERNAL_TOKEN':'synthetic-internal-token'},capture_output=True,text=True,timeout=30)
        assert process.returncode==0,process.stdout+process.stderr
        worker_result=json.loads(process.stdout);assert worker_result['bridge'] and worker_result['steps']==2
        with engine.connect() as c:
            completed=c.execute(text('SELECT * FROM agent_turns WHERE id=:id'),{'id':sent2['turn_id']}).mappings().one()
            assert completed['status']=='succeeded' and completed['worker_id'] is None
            answer=c.execute(text("SELECT content FROM messages WHERE turn_id=:id AND role='assistant'"),{'id':sent2['turn_id']}).scalar_one()
            assert ids[0] in answer and 'report:' in answer
        events=client.get(f'/api/conversations/{cid}/events').json()['events']
        assert events[-1]['kind']=='turn_succeeded'
        stale={'turn_id':sent2['turn_id'],'fence':1,'worker_id':worker_result['workerId']}
        assert client.post('/internal/agent/finish',headers=headers,json={**stale,'content':'duplicate'}).status_code==409
        for mode,expected in [('failure','failed'),('cancel','cancelled')]:
            next_turn=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':mode},
                json={'content':f'Synthetic {mode}','selected_run_id':rid,'selected_candidate_id':ids[0]}).json()['turn_id']
            process=subprocess.run(['node','agent/worker.integration.mjs',url,ids[0],mode,next_turn],
                env={**os.environ,'AGENT_INTERNAL_TOKEN':'synthetic-internal-token'},capture_output=True,text=True,timeout=30)
            assert process.returncode==0,process.stdout+process.stderr
            with engine.connect() as c:
                row=c.execute(text('SELECT status,error FROM agent_turns WHERE id=:id'),{'id':next_turn}).mappings().one()
                assert row['status']==expected
                if mode=='failure':assert row['error']=={'code':'AGENT_MODEL_FAILED'}
                assert c.execute(text("SELECT count(*) FROM messages WHERE turn_id=:id AND role='assistant'"),{'id':next_turn}).scalar_one()==0
        assert client.get(f'/api/runs/{rid}/view').json()['ready'] is True
    finally:
        server.should_exit=True;thread.join(10);listener.close()
    with engine.connect() as c:assert c.execute(text('SELECT count(*) FROM jobs')).scalar_one()==before
