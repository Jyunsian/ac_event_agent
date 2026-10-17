from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import text
from server.agent_queue import AgentQueue
from server.worker import Worker
from server.jobs import JobQueue,LeaseLost
from tests.test_jobs import jobdb
from tests.test_upload_api import api
from tests.test_pipeline import create_run,configure_worker
from tests.test_search import CONFIG


def test_controlled_rerun_and_scoped_result(api,jobdb,tmp_path,monkeypatch):
    client,engine,storage=api
    from tests.positive_sources import positive_sources,POSITIVE_EXPORT
    monkeypatch.setattr('tests.test_pipeline.sources',positive_sources)
    monkeypatch.setattr('tests.test_pipeline.EXPORT',POSITIVE_EXPORT)
    monkeypatch.setattr('tests.test_pipeline.CONFIG',{**CONFIG,'max_candidates':20})
    parent=create_run(jobdb,storage,tmp_path/'parent');rid=str(parent['id'])
    configure_worker(engine,storage,monkeypatch);assert Worker(engine,task_timeout=120).run_once()
    original=client.get(f'/api/runs/{rid}/reports/1/json').content
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'conversation'}).json()['id']
    sent=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'question'},json={'content':'只看前3小時，展示2次或收益0.02美元','selected_run_id':rid}).json()
    claim=AgentQueue(engine).claim('controlled-test')
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-branch-token')
    headers={'Authorization':'Bearer synthetic-branch-token'}
    body={'turn_id':sent['turn_id'],'parent_run_id':rid,'worker_id':claim['worker_id'],'fence':claim['fence'],
          'tool_call_id':'controlled-1','arguments':{'windows_hours':[3],'thresholds':{'count':[2],'revenue_sum':[.02]}}}
    for invalid in ({},{'windows_hours':[169]},{'windows_hours':[0]},{'windows_hours':[True]},
                    {'windows_hours':[3,3]},{'max_candidates':2001},{'seed':1},{'code':'print(1)'},
                    {'thresholds':{'sql':[1]}},{'thresholds':{'count':[1.5]}},
                    {'thresholds':{'revenue_sum':[0]}},{'thresholds':{'count':list(range(1,22))}}):
        response=client.post('/internal/tools/rerun_analysis',json={**body,'arguments':invalid},headers=headers)
        assert response.status_code==422,(invalid,response.text)
    with engine.connect() as c:assert c.execute(text('SELECT count(*) FROM analysis_branches')).scalar_one()==0
    over_parent=client.post('/internal/tools/rerun_analysis',json={**body,'arguments':{'max_candidates':21}},headers=headers)
    assert over_parent.status_code==422
    assert over_parent.json()['error_code']=='TOOL_CANDIDATE_BUDGET_EXCEEDED'
    response=client.post('/internal/tools/rerun_analysis',json=body,headers=headers)
    assert response.status_code==200,response.text
    child=response.json()['child_run_id']
    assert client.post('/internal/tools/rerun_analysis',json=body,headers=headers).json()['child_run_id']==child
    evaluate={**body,'tool_call_id':'evaluate-1','arguments':{'child_run_id':child}}
    progress=client.post('/internal/tools/evaluate_analysis',json=evaluate,headers=headers).json()
    assert progress['status']=='queued' and progress['references']==[]
    assert client.post('/internal/tools/evaluate_analysis',json={**evaluate,'arguments':{'child_run_id':rid}},headers=headers).status_code==422
    assert Worker(engine,task_timeout=120).run_once()
    result=client.post('/internal/tools/evaluate_analysis',json=evaluate,headers=headers)
    assert result.status_code==200,result.text
    data=result.json();assert data['status']=='succeeded' and data['run_id']==child
    assert data['content']['config']['windows_hours']==[3]
    assert data['content']['config']['exploration_fraction']==CONFIG['exploration_fraction']
    assert data['content']['config']['seed']==CONFIG['seed']
    assert data['content']['candidates']
    assert all(row['event_spec']['window_hours']==3 and row['evidence_status']=='exploratory' for row in data['content']['candidates'])
    assert all(ref['run_id']==child and len(ref['sha256'])==64 for ref in data['references'])
    assert client.get(f'/api/runs/{rid}/reports/1/json').content==original
    assert 'object_key' not in result.text and 'user_id' not in result.text
    # Published branch identities are paginated within the root, without creating work.
    with engine.connect() as c:
        job_count=c.execute(text('SELECT count(*) FROM jobs')).scalar_one()
    page=client.get(f'/api/runs/{rid}/branch-reports?limit=1').json()
    assert page['root_run_id']==rid and page['items'][0]['run_id']==child
    entry=page['items'][0]
    rest=client.get(f'/api/runs/{child}/branch-reports',params={'limit':1,'cursor':page['next_cursor']}).json()
    assert [x['run_id'] for x in rest['items']]==[rid] and rest['next_cursor'] is None
    assert 'object_key' not in str(page) and 'metrics' not in str(page)
    selected=client.get(f'/api/runs/{child}/view',params={'version':entry['report_version'],'artifact':entry['artifact_id']})
    assert selected.status_code==200 and selected.json()['report_artifact_id']==entry['artifact_id']
    assert client.get(f'/api/runs/{rid}/view',params={'version':1,'artifact':entry['artifact_id']}).status_code==422
    assert client.get(f'/api/runs/{rid}/view?version=999').status_code==404
    assert client.get(f'/api/runs/{rid}/branch-reports?cursor=bad').status_code==422
    assert client.get(f'/api/runs/{rid}/branch-reports?limit=0').status_code==422
    unrelated=create_run(jobdb,storage,tmp_path/'unrelated')
    assert client.get(f"/api/runs/{unrelated['id']}/branch-reports").json()['items']==[]
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM jobs')).scalar_one()==job_count+1
    client.post(f"/api/turns/{sent['turn_id']}/cancel",headers={'Idempotency-Key':'cancel'})
    assert client.post('/internal/tools/evaluate_analysis',json=evaluate,headers=headers).status_code==409


def test_branch_creation_scoped_idempotent_and_immutable_parent(api,jobdb,tmp_path,monkeypatch):
    client,engine,storage=api
    parent=create_run(jobdb,storage,tmp_path/'parent');rid=str(parent['id'])
    configure_worker(engine,storage,monkeypatch);assert Worker(engine,task_timeout=120).run_once()
    original=client.get(f'/api/runs/{rid}/reports/1/json').content
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'conversation'}).json()['id']
    sent=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'question'},json={'content':'縮短窗口','selected_run_id':rid}).json()
    claim=AgentQueue(engine).claim('branch-test')
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-branch-token')
    headers={'Authorization':'Bearer synthetic-branch-token'}
    config={**CONFIG,'windows_hours':[3,24]}
    body={'turn_id':sent['turn_id'],'parent_run_id':rid,'worker_id':claim['worker_id'],'fence':claim['fence'],
          'tool_call_id':'branch-1','arguments':{'config':config}}
    assert client.post('/internal/analysis/branches',json=body).status_code==401
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses=list(pool.map(lambda _:client.post('/internal/analysis/branches',json=body,headers=headers),range(4)))
    assert all(r.status_code==202 for r in responses),[r.text for r in responses]
    ids={r.json()['child_run_id'] for r in responses};assert len(ids)==1
    assert len({r.json()['job_id'] for r in responses})==1
    child=ids.pop()
    assert sum(not r.json()['reused'] for r in responses)==1
    view=client.get(f'/api/runs/{child}/lineage').json()
    assert view['parent_run_id']==view['root_run_id']==rid
    assert view['dataset_id']==str(parent['dataset_id']) and view['evidence_status']=='exploratory'
    assert view['branch']['source_turn_id']==sent['turn_id']
    assert view['branch']['config_delta']=={'windows_hours':{'before':CONFIG['windows_hours'],'after':[3,24]}}
    conflict={**body,'arguments':{'config':{**config,'seed':config['seed']+1}}}
    assert client.post('/internal/analysis/branches',json=conflict,headers=headers).status_code==409
    split_change={**body,'tool_call_id':'split-change','arguments':{'config':{**config,'exploration_fraction':.5}}}
    assert client.post('/internal/analysis/branches',json=split_change,headers=headers).status_code==422
    wrong_fence={**body,'fence':claim['fence']+1}
    assert client.post('/internal/analysis/branches',json=wrong_fence,headers=headers).status_code==409
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM analysis_branches')).scalar_one()==1
        assert c.execute(text('SELECT count(*) FROM jobs WHERE run_id=:id'),{'id':child}).scalar_one()==1
    assert client.get(f'/api/runs/{rid}/reports/1/json').content==original
    # Execute the real child on Python Worker, without depending on the model.
    assert Worker(engine,task_timeout=120).run_once()
    child_view=client.get(f'/api/runs/{child}/view').json()
    assert child_view['ready'],child_view
    child_report=client.get(f'/api/runs/{child}/reports/1/json').json()
    assert child_report['run_id']==child and child_report['dataset_id']==str(parent['dataset_id'])
    assert child_report['audit']['validation_policy']['eligible'] is False
    cache={entry['stage']:entry for entry in child_report['audit']['cache']['entries']}
    for stage in ('normalized','quality','targets'):
        assert cache[stage]['mode']=='cached',cache
        assert cache[stage]['source_run_id']==rid
    for stage in ('exploration','features'):
        assert cache[stage]['mode']=='computed',cache
    assert 'FOLLOWUP_IS_EXPLORATORY' in child_report['audit']['validation_policy']['reasons']
    assert all(row['evidence_status']=='exploratory' and row['event_spec']['window_hours'] in [3,24] for row in child_report['candidates'])
    assert client.get(f'/api/runs/{rid}/reports/1/json').content==original
    # Two additional child jobs are cancelled atomically with the parent turn;
    # completed child reports remain immutable and readable.
    pending=[client.post('/internal/analysis/branches',headers=headers,json={**body,'tool_call_id':f'cancel-{i}'}).json() for i in range(2)]
    computing=JobQueue(engine).claim('cancel-fence-test')
    assert str(computing.run_id) in {item['child_run_id'] for item in pending}
    original_event=AgentQueue.event
    def fault(*args,**kwargs):raise RuntimeError('synthetic cancel commit fault')
    monkeypatch.setattr(AgentQueue,'event',fault)
    with pytest.raises(RuntimeError,match='synthetic cancel commit fault'):
        client.post(f"/api/turns/{sent['turn_id']}/cancel",headers={'Idempotency-Key':'cancel-children'})
    with engine.connect() as c:
        assert c.execute(text('SELECT status FROM agent_turns WHERE id=:id'),{'id':sent['turn_id']}).scalar_one()=='running'
        statuses=c.execute(text('SELECT status FROM jobs WHERE run_id IN (:a,:b)'),{'a':pending[0]['child_run_id'],'b':pending[1]['child_run_id']}).scalars().all()
        assert sorted(statuses)==['queued','running']
    monkeypatch.setattr(AgentQueue,'event',original_event)
    cancelled=client.post(f"/api/turns/{sent['turn_id']}/cancel",headers={'Idempotency-Key':'cancel-children'})
    assert cancelled.status_code==200
    assert client.post(f"/api/turns/{sent['turn_id']}/cancel",headers={'Idempotency-Key':'cancel-children'}).json()==cancelled.json()
    with pytest.raises(LeaseLost):JobQueue(engine).finish(computing)
    for item in pending:assert client.get(f"/api/runs/{item['child_run_id']}/view").json()['status']=='cancelled'
    assert client.get(f'/api/runs/{child}/reports/1/json').json()==child_report
    assert client.get(f'/api/runs/{rid}/reports/1/json').content==original
