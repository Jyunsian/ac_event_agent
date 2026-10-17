from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
import pytest
from server.worker import Worker
from server.agent_queue import AgentQueue
from tests.test_jobs import jobdb
from tests.test_upload_api import api
from tests.test_pipeline import create_run,configure_worker


def test_budget_concurrent_round_limit_and_finalize_are_durable(api,jobdb,tmp_path,monkeypatch):
    from tests.positive_sources import positive_sources, POSITIVE_EXPORT
    monkeypatch.setattr('tests.test_pipeline.sources',positive_sources)
    monkeypatch.setattr('tests.test_pipeline.EXPORT',POSITIVE_EXPORT)
    client,engine,storage=api
    parent=create_run(jobdb,storage,tmp_path/'parent');rid=str(parent['id'])
    configure_worker(engine,storage,monkeypatch);assert Worker(engine,task_timeout=120).run_once()
    original=client.get(f'/api/runs/{rid}/reports/1/json').content
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'c'}).json()['id']
    tid=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'m'},json={'content':'調整分析','selected_run_id':rid}).json()['turn_id']
    claim=AgentQueue(engine).claim('budget-test')
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-budget');headers={'Authorization':'Bearer synthetic-budget'}
    body={'turn_id':tid,'parent_run_id':rid,'worker_id':claim['worker_id'],'fence':claim['fence'],'tool_call_id':'budget','arguments':{}}
    state=client.post('/internal/tools/get_exploration_budget',headers=headers,json=body).json()
    assert state['budget']['rounds_used']==0 and state['budget']['max_rounds']==4
    def run(i):
        return client.post('/internal/tools/rerun_analysis',headers=headers,json={**body,'tool_call_id':f'round-{i}','arguments':{'windows_hours':[3]}})
    with ThreadPoolExecutor(max_workers=5) as pool:responses=list(pool.map(run,range(5)))
    assert sorted(r.status_code for r in responses)==[200,200,200,200,409]
    successful=[(i,r.json()) for i,r in enumerate(responses) if r.status_code==200]
    index,first=successful[0]
    assert run(index).json()['child_run_id']==first['child_run_id']
    state=client.post('/internal/tools/get_exploration_budget',headers=headers,json=body).json()
    assert state['budget']['rounds_used']==4 and state['budget']['candidates_used']==8000
    assert [r['ordinal'] for r in state['rounds']]==[1,2,3,4]
    pending=client.post('/internal/tools/finalize_candidates',headers=headers,json={**body,'arguments':{
        'child_run_id':first['child_run_id'],'candidate_ids':[]}})
    assert pending.status_code==409 and pending.json()['error_code']=='FINALIZE_REPORT_NOT_READY'
    # Complete all queued children; no new candidate selection happens at finalize.
    for _ in range(4):assert Worker(engine,task_timeout=120).run_once()
    child=first['child_run_id'];report=client.get(f'/api/runs/{child}/reports/1/json').json()
    ids=[r['candidate_id'] for r in report['candidates'][:2]]
    assert ids, 'Finalization mutation must compare a nonempty selection with an empty one'
    finalize={**body,'tool_call_id':'finalize','arguments':{'child_run_id':child,'candidate_ids':ids}}
    invalid=client.post('/internal/tools/finalize_candidates',headers=headers,json={**finalize,
        'arguments':{'child_run_id':child,'candidate_ids':['not-in-report']}})
    assert invalid.status_code==422 and invalid.json()['error_code']=='CANDIDATE_NOT_IN_REPORT'
    result=client.post('/internal/tools/finalize_candidates',headers=headers,json=finalize)
    assert result.status_code==200,result.text
    assert result.json()['status']=='finalized' and result.json()['evidence_status']=='exploratory'
    assert client.post('/internal/tools/finalize_candidates',headers=headers,json=finalize).json()['reused']
    changed=client.post('/internal/tools/finalize_candidates',headers=headers,json={**finalize,
        'arguments':{'child_run_id':child,'candidate_ids':[]}})
    assert changed.status_code==409 and changed.json()['error_code']=='EXPLORATION_FINALIZED'
    rejected=run(99);assert rejected.status_code==409 and rejected.json()['error_code']=='EXPLORATION_FINALIZED'
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM exploration_rounds WHERE turn_id=:id'),{'id':tid}).scalar_one()==4
        assert c.execute(text('SELECT count(*) FROM exploration_finalizations WHERE turn_id=:id'),{'id':tid}).scalar_one()==1
    assert client.get(f'/api/runs/{rid}/reports/1/json').content==original
    for table in ('exploration_budgets','exploration_rounds','exploration_finalizations'):
        with pytest.raises(DBAPIError):
            with engine.begin() as c:c.execute(text(f'DELETE FROM {table} WHERE turn_id=:id'),{'id':tid})
    with pytest.raises(DBAPIError):
        with engine.begin() as c:c.execute(text('UPDATE exploration_round_notes SET hypothesis=:h WHERE run_id=:id'),{'h':'rewrite','id':child})
    with pytest.raises(DBAPIError,match='FINALIZATION_PROVENANCE_MISMATCH'):
        with engine.begin() as c:c.execute(text('''INSERT INTO exploration_finalizations(turn_id,run_id,report_artifact_id,report_version,report_sha256,candidate_ids)
            SELECT turn_id,run_id,report_artifact_id,report_version,repeat('0',64),candidate_ids FROM exploration_finalizations WHERE turn_id=:id'''),{'id':tid})


@pytest.mark.parametrize('case',['time','candidates'])
def test_explicit_budget_edges_preserve_completed_artifacts(api,jobdb,tmp_path,monkeypatch,case):
    client,engine,storage=api
    parent=create_run(jobdb,storage,tmp_path/'parent');rid=str(parent['id'])
    configure_worker(engine,storage,monkeypatch);assert Worker(engine,task_timeout=120).run_once()
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'c'}).json()['id']
    tid=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'m'},json={'content':'邊界測試','selected_run_id':rid}).json()['turn_id']
    claim=AgentQueue(engine).claim('budget-edge')
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-budget');headers={'Authorization':'Bearer synthetic-budget'}
    body={'turn_id':tid,'parent_run_id':rid,'worker_id':claim['worker_id'],'fence':claim['fence'],'tool_call_id':'first','arguments':{'windows_hours':[3],'max_candidates':1}}
    forged=client.post('/internal/tools/rerun_analysis',headers=headers,json={**body,'arguments':{
        **body['arguments'],'hypothesis':'假引用測試','based_on':['report:foreign#/summary']}})
    assert forged.status_code==422 and forged.json()['error_code']=='ROUND_EVIDENCE_NOT_DELIVERED'
    # Test-owned server policy seed: shorter deadline/smaller total quota, not
    # a model override or an update to immutable production budget records.
    with engine.begin() as c:
        c.execute(text('''INSERT INTO exploration_budgets(turn_id,max_rounds,max_candidates,deadline)
            VALUES(:id,4,2,clock_timestamp()+:seconds*interval '1 second')'''),{'id':tid,'seconds':-1 if case=='time' else 600})
    before=None;child=None
    if case=='candidates':
        first=client.post('/internal/tools/rerun_analysis',headers=headers,json=body)
        assert first.status_code==200,first.text
        child=first.json()['child_run_id'];assert Worker(engine,task_timeout=120).run_once()
        before=client.get(f'/api/runs/{child}/reports/1/json').content
    rejected=client.post('/internal/tools/rerun_analysis',headers=headers,json={**body,'tool_call_id':'over-limit','arguments':{'max_candidates':2}})
    assert rejected.status_code==409
    assert rejected.json()['error_code']==('EXPLORATION_TIME_LIMIT' if case=='time' else 'EXPLORATION_CANDIDATE_LIMIT')
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM exploration_rounds WHERE turn_id=:id'),{'id':tid}).scalar_one()==(0 if case=='time' else 1)
    if child:assert client.get(f'/api/runs/{child}/reports/1/json').content==before
