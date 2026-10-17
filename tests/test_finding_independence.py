from uuid import uuid4
from sqlalchemy import text
from server.worker import Worker
from server.agent_queue import AgentQueue
from server.uploads import UploadService
from server.finding_rechecks import resolve_sources,save_recheck
from tests.test_jobs import jobdb
from tests.test_upload_api import api
from tests.test_pipeline import configure_worker
from tests.test_ingest import MAPPING,write_source
from tests.test_quality import EXPORT
from tests.test_search import CONFIG
from tests.test_findings import finding_heartbeats
import pytest


def test_actual_independent_positive_and_reversed_batches(api,jobdb,tmp_path,monkeypatch,finding_heartbeats):
    client,engine,storage=api;_,repo,_=jobdb
    configure_worker(engine,storage,monkeypatch)
    config={**CONFIG,'windows_hours':[3],'thresholds':{'count':[1]}}
    export={**EXPORT,'complete_through':'2026-01-20T00:00:00Z','exported_at':'2026-01-21T00:00:00Z'}
    def batch(prefix,reverse=False):
        directory=tmp_path/prefix;directory.mkdir();users=[];events=[]
        for day in range(1,5):
            for index in range(100):
                identity=f'{prefix}-day{day}-{index}';hit=index<50
                users.append({'app_id':'synthetic','user_id':identity,'installed_at':f'2026-01-{day:02}T00:00:00Z','platform':'android'})
                events.append({'app_id':'synthetic','user_id':identity,'event_id':identity+'-ad','event_name':'ad_impression',
                    'event_time':f'2026-01-{day:02}T01:00:00Z','available_at':f'2026-01-{day:02}T01:00:00Z',
                    'revenue_usd':(2 if hit!=reverse else 0)+.01*(index%2),'ad_format':'rewarded' if hit else 'interstitial'})
        manifest=[]
        for role,rows in [('users',users),('events',events)]:
            source=write_source(directory,role,rows)
            saved=storage.put_file(storage.new_key('synthetic-independent','csv'),source['path'])
            manifest.append({**saved.to_dict(),'role':role,'format':'csv'})
        with engine.begin() as c:
            project=repo.create_project(c,'synthetic','Independent finding fixture')
            dataset=repo.create_dataset(c,project['id']);repo.seal_dataset(c,dataset['id'],manifest,MAPPING,export)
            run=repo.create_run(c,dataset['id'],config,str(uuid4()))
        return run
    old=batch('old');assert Worker(engine,task_timeout=120).run_once()
    old_bytes=client.get(f"/api/runs/{old['id']}/reports/1/json").content
    import json
    old_report=json.loads(old_bytes)
    from server.candidate_reader import candidate_context,read_candidate_detail
    service=UploadService(engine,storage)
    _,_,catalog,_=candidate_context(service,old['id'],1)
    entry=next(row for row in catalog['entries'] if row['summary']['event_spec']['predicate']=={'op':'count','threshold':1,'ad_format':'rewarded'})
    detail=read_candidate_detail(service,old['id'],1,entry['candidate_id'])['content']
    rule={**detail['validation'],'event_spec':detail['event_spec']}
    assert rule['evidence_status']=='historically_validated'
    cid=client.post(f"/api/runs/{old['id']}/conversations",headers={'Idempotency-Key':'independent'}).json()['id']
    turn=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'observe'},
        json={'content':'保存激勵廣告規則','selected_run_id':str(old['id'])}).json()['turn_id']
    claim=AgentQueue(engine).claim('independent-finding')
    finding_heartbeats(claim)
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-independent-token')
    saved=client.post('/internal/tools/save_findings',headers={'Authorization':'Bearer synthetic-independent-token'},json={
        'turn_id':turn,'parent_run_id':str(old['id']),'worker_id':claim['worker_id'],'fence':claim['fence'],'tool_call_id':'save',
        'arguments':{'candidate_id':rule['candidate_id'],'hypothesis':'激勵展示候選','limitations':['合成資料；不代表投放成效'],'counterexamples':[]}})
    assert saved.status_code==200,saved.text
    finding=saved.json()['finding_id'];service=UploadService(engine,storage)
    for prefix,reverse,status in [('fresh-positive',False,'reusable_evidence'),('fresh-reversed',True,'not_supported')]:
        run=batch(prefix,reverse)
        snapshots=resolve_sources(service,run['dataset_id'],[finding],config)
        with engine.begin() as c:save_recheck(c,service,run['id'],snapshots)
        if not reverse:
            from tests.finding_recovery import recover_fixed_recheck
            recover_fixed_recheck(engine,run['id'])
        else:assert Worker(engine,task_timeout=120).run_once()
        assert client.get(f"/api/runs/{old['id']}/reports/1/json").content==old_bytes
        response=client.get(f"/api/runs/{run['id']}/reports/1/json")
        assert response.status_code==200,response.text
        report=response.json();assessment=report['summary']['finding_recheck']['assessments'][0]
        assert report['audit']['validation_policy']['eligible'] is True
        assert assessment['status']==status,assessment
        assert assessment['reusable']==(not reverse)
        candidate=report['candidates'][0]
        assert candidate['event_spec']==rule['event_spec']
        groups=candidate['metrics']['groups']
        assert groups['triggered']['users']==groups['untriggered']['users']==100
        assert groups['triggered']['arpu_usd']==pytest.approx(.005 if reverse else 2.005)
        assert groups['untriggered']['arpu_usd']==pytest.approx(2.005 if reverse else .005)
        interval=candidate['metrics']['bootstrap']['intervals']['triggered_minus_untriggered']
        expected=-2 if reverse else 2
        assert expected-.01<=interval['lower']<=expected<=interval['upper']<=expected+.01
        assert interval['valid_replicates']==interval['requested_replicates']==1000
        with engine.connect() as c:
            assert not c.execute(text("SELECT 1 FROM stage_checkpoints WHERE run_id=:id AND stage='search'"),{'id':run['id']}).first()
    loaded=client.post('/internal/tools/load_app_findings',headers={'Authorization':'Bearer synthetic-independent-token'},json={
        'turn_id':turn,'parent_run_id':str(old['id']),'worker_id':claim['worker_id'],'fence':claim['fence'],
        'tool_call_id':'history','arguments':{}})
    assert loaded.status_code==200,loaded.text
    history=loaded.json()['items'][0]['recheck_history']
    assert [row['status'] for row in history]==['not_supported','reusable_evidence']
    assert len(loaded.json()['references'])==3
    assert loaded.json()['items'][0]['requires_new_batch_validation'] is True
