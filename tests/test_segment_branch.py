import pytest
import csv
import io
import json
from sqlalchemy import text
from server.worker import Worker
from server.agent_queue import AgentQueue
from tests.test_jobs import jobdb
from tests.test_upload_api import api
from tests.test_pipeline import create_run,configure_worker
from tests.test_search import CONFIG


@pytest.mark.parametrize('field,value,positive',[('country','US',False),('acquisition_source','paid',False),('country','US',True)])
def test_segment_branch_true_worker_preserves_parent(api,jobdb,tmp_path,monkeypatch,field,value,positive):
    client,engine,storage=api
    if positive:
        from tests.positive_sources import positive_sources,POSITIVE_EXPORT
        monkeypatch.setattr('tests.test_pipeline.sources',positive_sources)
        monkeypatch.setattr('tests.test_pipeline.EXPORT',POSITIVE_EXPORT)
    else:monkeypatch.setattr('tests.test_pipeline.CONFIG',{**CONFIG,'min_group_users':2})
    parent=create_run(jobdb,storage,tmp_path/'parent');rid=str(parent['id'])
    configure_worker(engine,storage,monkeypatch);assert Worker(engine,task_timeout=120).run_once()
    original=client.get(f'/api/runs/{rid}/reports/1/json')
    if positive:assert original.json()['candidates']
    assert client.post(f"/api/datasets/{parent['dataset_id']}/baseline",headers={'Idempotency-Key':'invalid-segment-baseline'},
        json={**CONFIG,'segment':{'field':field,'value':value}}).status_code==422
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'c'}).json()['id']
    turn=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'m'},json={'content':'分析美國子群','selected_run_id':rid}).json()['turn_id']
    claim=AgentQueue(engine).claim('segment-test')
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-segment-token');headers={'Authorization':'Bearer synthetic-segment-token'}
    body={'turn_id':turn,'parent_run_id':rid,'worker_id':claim['worker_id'],'fence':claim['fence'],
        'tool_call_id':'segment-1','arguments':{'field':field,'value':value}}
    created=client.post('/internal/tools/analyze_segment',json=body,headers=headers)
    assert created.status_code==200,created.text
    child=created.json()['child_run_id']
    assert client.post('/internal/tools/analyze_segment',json=body,headers=headers).json()['child_run_id']==child
    assert Worker(engine,task_timeout=120).run_once()
    evaluated=client.post('/internal/tools/evaluate_analysis',json={**body,'tool_call_id':'evaluate-1','arguments':{'child_run_id':child}},headers=headers)
    assert evaluated.status_code==200,evaluated.text
    result=evaluated.json();assert result['status']=='succeeded',result
    segment=result['content']['segment']
    assert segment['split_id']==original.json()['summary']['targets']['split_id']
    assert segment['evidence_status']=='exploratory'
    assert [c['candidate_id'] for c in segment['candidate_specs']]==[c['candidate_id'] for c in original.json()['candidates']]
    if positive:
        assert segment['selected_users']==400 and segment['immature_users']==0
        assert segment['candidates']
        assert all(group['users']==200 and group['arpu_usd']==pytest.approx(1.05295) for group in segment['cohorts'].values())
    elif field=='country':
        assert segment['selected_users']==3 and segment['immature_users']==0
        assert segment['cohorts']['exploration']['users']==2
        assert segment['cohorts']['exploration']['arpu_usd']==pytest.approx(.1)
        assert segment['cohorts']['holdout']['users']==1
        assert segment['cohorts']['holdout']['arpu_usd'] is None
    else:assert 'SEGMENT_FIELD_UNAVAILABLE' in segment['reasons'] and segment['candidates']==[]
    with engine.connect() as c:
        stages=c.execute(text('SELECT stage FROM stage_checkpoints WHERE run_id=:id'),{'id':child}).scalars().all()
        assert 'segment' in stages and not set(stages)&{'search','selection','validation'}
    assert client.get(f'/api/runs/{child}/lineage').json()['parent_run_id']==rid
    assert client.get(f'/api/runs/{rid}/reports/1/json').content==original.content
    assert result['references'] and all(ref['run_id']==child for ref in result['references'])
    html=client.get(f'/api/runs/{child}/reports/1/html');assert html.status_code==200
    if field=='country':
        assert '國家：US 的用戶分析' in html.text and '分群分母與收益' in html.text
    else:
        assert '資料中缺少用來篩選這個人群的欄位' in html.text
    assert '原始候選完整打點規格' in html.text and '來源資料範圍' in html.text
    if positive:
        assert 'per_user_limit' in html.text and 'expired_policy' in html.text
    else:
        assert not segment['candidate_specs'] and 'NO_PARENT_CANDIDATES' in segment['reasons']
    exported=client.get(f'/api/runs/{child}/reports/1/csv');assert exported.status_code==200
    rows=list(csv.DictReader(io.StringIO(exported.text)))
    assert rows and all(row['segment_field']==field and row['segment_value']==value and row['evidence_status']=='exploratory' for row in rows)
    assert all(row['run_id']==child and row['parent_run_id']==rid and row['csv_schema_version']=='2.0' for row in rows)
    parent_specs={row['candidate_id']:row['event_spec'] for row in original.json()['candidates']}
    for row in rows:
        assert json.loads(row['data_scope_json'])['complete_through']
        if row['record_type']=='candidate':assert json.loads(row['event_spec_json'])==parent_specs[row['candidate_id']]
    if positive:
        assert any(row['record_type']=='candidate' for row in rows)
        groups=[row for row in rows if row['record_type']=='cohort']
        assert len(groups)==2 and all(row['users']=='200' and float(row['arpu_usd'])==pytest.approx(1.05295) for row in groups)
    elif field=='country':
        groups={row['split']:row for row in rows if row['record_type']=='cohort'}
        assert float(groups['exploration']['arpu_usd'])==pytest.approx(.1)
        assert groups['holdout']['users']=='1' and groups['holdout']['arpu_usd']==''
    else:assert rows[0]['record_type']=='limitation'
    # A subsequent turn can read this published segment without rerunning it.
    client.post(f'/api/turns/{turn}/cancel',headers={'Idempotency-Key':'done'})
    next_turn=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'read-segment'},
        json={'content':'解釋這份分群報告','selected_run_id':child}).json()['turn_id']
    next_claim=AgentQueue(engine).claim('segment-read-test')
    read=client.post('/internal/tools/get_baseline_report',headers=headers,json={
        'turn_id':next_turn,'parent_run_id':child,'worker_id':next_claim['worker_id'],'fence':next_claim['fence'],
        'tool_call_id':'read-segment','arguments':{}})
    assert read.status_code==200,read.text
    assert read.json()['content']['segment']==segment
