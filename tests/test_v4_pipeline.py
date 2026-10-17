import json
from pathlib import Path
from uuid import uuid4
from server.analysis.v4_contract import defaults
from server.candidate_reader import candidate_context,read_candidate_detail,read_candidate_page,read_candidate_search
from server.candidate_exports import read_candidate_export
from server.artifact_reader import read_report_export
from server.uploads import UploadService
from server.worker import Worker
from server.pipeline import run_baseline
from server.jobs import JobQueue
from tests.test_v3_pipeline import v3_sources,MAPPING,EXPORT
from tests.test_jobs import jobdb
from tests.test_upload_api import api
from tests.test_pipeline import configure_worker


def test_v4_upload_to_report_with_named_rule(api,jobdb,tmp_path,monkeypatch):
    from tests.test_upload_api import request,begin,put,finish
    from server.analysis.v4_search import atom_rule
    client,engine,storage=api
    project=request(client,'POST','/api/projects',{'app_id':'game','name':'V4 upload acceptance'})
    assert project.status_code==201,project.text
    ds=request(client,'POST','/api/datasets',{'project_id':project.json()['id']}).json()['id']
    for source in v3_sources(tmp_path):
        data=Path(source['path']).read_bytes()
        upload,fp=begin(client,ds,data,source['role'])
        put(client,upload,fp,1,data);finish(client,upload,fp)
    mapping=request(client,'PUT',f'/api/datasets/{ds}/mapping',{'mapping':MAPPING,'export_metadata':EXPORT})
    assert mapping.status_code==200,mapping.text
    rule=atom_rule('ad_count',{'ad_format':'all'},2)
    config={**defaults(),'max_discovery_candidates':50,'max_candidates':48,'min_group_users':2,
        'existing_rules':[{'name':'目前廣告兩次方案','rule':rule,'deadline_hours':48}]}
    started=request(client,'POST',f'/api/datasets/{ds}/baseline',config)
    assert started.status_code==202,started.text
    rid=started.json()['run_id'];configure_worker(engine,storage,monkeypatch)
    assert Worker(engine,task_timeout=180).run_once()
    result=client.get(f'/api/runs/{rid}/reports/1/json')
    assert result.status_code==200,result.text
    report=result.json();assert report['schema_version']=='4.0'
    _,_,catalog,_=candidate_context(UploadService(engine,storage),rid,1)
    assert any(row['candidate_id']==rule['rule_id'] for row in catalog['entries'])
    detail=read_candidate_detail(UploadService(engine,storage),rid,1,rule['rule_id'])['content']
    assert '目前廣告兩次方案' in json.dumps(detail,ensure_ascii=False)


def create_v4(jobdb,storage,root):
    root.mkdir();engine,repo,_=jobdb;manifest=[]
    for source in v3_sources(root):
        saved=storage.put_file(storage.new_key('v4-input',source['format']),source['path'])
        manifest.append({**saved.to_dict(),'role':source['role'],'format':source['format']})
    config={**defaults(),'max_discovery_candidates':50,'max_candidates':48,'min_group_users':2}
    with engine.begin() as c:
        project=repo.create_project(c,'game','V4 test');dataset=repo.create_dataset(c,project['id'])
        repo.seal_dataset(c,dataset['id'],manifest,MAPPING,EXPORT)
        return repo.create_run(c,dataset['id'],config,str(uuid4()),calculation_version=config['analysis_version'])


def test_v4_pg_s3_worker_all_exports_and_candidate_read(api,jobdb,tmp_path,monkeypatch):
    _,engine,storage=api;run=create_v4(jobdb,storage,tmp_path/'source');configure_worker(engine,storage,monkeypatch)
    assert Worker(engine,task_timeout=180).run_once()
    with engine.connect() as c:saved=jobdb[1].get_run(c,run['id'])
    assert saved['status']=='succeeded',saved['error']
    service=UploadService(engine,storage)
    report,_,catalog,files=candidate_context(service,run['id'],1)
    assert report['schema_version']=='4.0' and catalog['evaluated_count']>0
    assert read_candidate_page(service,run['id'],1)['comparison_users']==32
    first=catalog['entries'][0]['candidate_id']
    d=read_candidate_detail(service,run['id'],1,first)['content']
    assert len(d['validation']['observation'])==6
    read_candidate_search(service,run['id'],1)
    for fmt in ('json','csv','html'):
        data,_,_=read_report_export(service,run['id'],1,fmt);assert data
        data,_,_=read_candidate_export(service,run['id'],1,fmt);assert data


def test_v4_outer_stages_restore_exact_bytes(api,jobdb,tmp_path):
    _,engine,storage=api;create_v4(jobdb,storage,tmp_path/'source')
    q=JobQueue(engine,lease_seconds=120);first=q.claim('v4-one')
    original=run_baseline(engine,storage,first,tmp_path/'work-one')
    q.fail(first,'RESTART_TEST',retryable=True,retry_delay=0)
    second=q.claim('v4-two');restored=run_baseline(engine,storage,second,tmp_path/'work-two')
    assert set(restored['summary']['stage_modes'].values())=={'restored'}
    assert restored['artifacts']==original['artifacts']


def test_v4_agent_aggregate_numbers_and_discovery_download(api,jobdb,tmp_path,monkeypatch):
    from server.agent_queue import AgentQueue
    client,engine,storage=api
    run=create_v4(jobdb,storage,tmp_path/'source');rid=str(run['id']);configure_worker(engine,storage,monkeypatch)
    assert Worker(engine,task_timeout=180).run_once()
    report=client.get(f'/api/runs/{rid}/reports/1/json').json()
    exported=client.get(f'/api/runs/{rid}/reports/1/discovery');assert exported.status_code==200
    assert exported.json()['discovery_count']==report['summary']['searched_candidate_count']
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'v4c'}).json()['id']
    sent=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'v4m'},json={'content':'比較每天的結果','selected_run_id':rid,'report_view':{'hours':48,'cohort':'exploration'}}).json()
    claim=AgentQueue(engine).claim('v4-read');monkeypatch.setenv('AGENT_INTERNAL_TOKEN','test-only')
    body={'turn_id':sent['turn_id'],'parent_run_id':rid,'worker_id':claim['worker_id'],'fence':claim['fence'],'tool_call_id':'v4tool','arguments':{'window_hours':48}}
    headers={'Authorization':'Bearer test-only'}
    result=client.post('/internal/tools/get_baseline_report',json=body,headers=headers)
    assert result.status_code==200,result.text
    from server.conversations import turn_context
    assert turn_context(UploadService(engine,storage),claim)['report_view']=={'hours':48,'cohort':'exploration'}
    row=result.json()['content']['candidates'][0]
    assert row['time_analysis']['exploration'][0]['hours']==48
    assert row['time_analysis']['exploration'][0]['users']==report['candidates'][0]['time_analysis']['exploration'][1]['groups']['triggered']['users']
    assert 'metrics' not in row
    expected=report['candidates'][0]['time_analysis']['observation'][1]['groups']['added']['users']
    assert row['time_analysis']['observation'][0]['added_users']==expected
    result=client.post('/internal/tools/compare_candidates',json={**body,'arguments':{'candidate_ids':[row['candidate_id']],'window_hours':48}},headers=headers)
    assert result.status_code==200,result.text
    assert result.json()['content']['candidates'][0]['time_analysis']['observation'][0]['added_users']==expected
    page=client.get(f'/api/runs/{rid}/reports/1/candidates',params={'window_hours':48}).json()
    assert all(p['summary']['display_checkpoint_hours']==48 for p in page['items'])
    assert all(p['summary']['decision']['point']['hours']==48 for p in page['items'])
    assert all(t['hours']==48 for p in page['items'] for t in p['summary']['decision']['tests'])
    assert all('time_evidence' not in p['summary'] for p in page['items'])
    for item in page['items']:
        d=item['summary']['decision']
        assert set(d['scopes'])=={'exploration','holdout'}
        assert d['point']['groups']['all']['users']==sum(d['scopes'][k]['point']['groups']['all']['users'] for k in d['scopes'])


def test_running_v4_keeps_v3_report_bytes(api,jobdb,tmp_path,monkeypatch):
    from tests.test_v3_pipeline import create_v3_run
    from sqlalchemy import select
    client,engine,storage=api;old=create_v3_run(jobdb,storage,tmp_path/'old');configure_worker(engine,storage,monkeypatch)
    assert Worker(engine,task_timeout=180).run_once()
    service=UploadService(engine,storage)
    original={fmt:read_report_export(service,old['id'],1,fmt)[0] for fmt in ('json','csv','html')}
    assert client.get(f"/api/runs/{old['id']}/reports/1/json").status_code==200
    # Same immutable dataset; a new version must not refresh validation eligibility.
    with engine.begin() as c:
        new=jobdb[1].create_run(c,old['dataset_id'],{**defaults(),'max_discovery_candidates':50,'max_candidates':48},str(uuid4()),calculation_version='4.0-time-aware')
    assert Worker(engine,task_timeout=180).run_once()
    with engine.connect() as c:assert jobdb[1].get_run(c,new['id'])['status']=='succeeded'
    latest=json.loads(read_report_export(service,new['id'],1,'json')[0])
    assert all(r['evidence_status']=='exploratory' for r in latest['candidates'])
    for fmt,data in original.items():assert read_report_export(service,old['id'],1,fmt)[0]==data
