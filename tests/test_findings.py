from uuid import uuid4
from sqlalchemy import insert,select,text,update
from sqlalchemy.exc import IntegrityError,ProgrammingError
import pytest
from server.worker import Worker
from tests.test_jobs import jobdb
from tests.test_upload_api import api
from tests.test_pipeline import create_run,configure_worker
from tests.positive_sources import positive_sources,POSITIVE_EXPORT


@pytest.fixture(autouse=True)
def finding_signal_sources(monkeypatch):
    # Success-path provenance needs real selected evidence, not lower sample gates.
    monkeypatch.setattr('tests.test_pipeline.sources',positive_sources)
    monkeypatch.setattr('tests.test_pipeline.EXPORT',POSITIVE_EXPORT)


@pytest.fixture
def finding_heartbeats(api):
    from threading import Event,Thread,Lock
    from server.agent_queue import AgentQueue
    _,engine,_=api
    stop=Event();lock=Lock();claims=[];errors=[]
    def track(claim):
        with lock:claims.append(claim)
    def pulse():
        while not stop.wait(2):
            with lock:active=list(claims)
            for claim in active:
                try:
                    with engine.connect() as c:
                        status=c.execute(text('SELECT status FROM agent_turns WHERE id=:id'),{'id':claim['id']}).scalar_one()
                    if status=='running':AgentQueue(engine).heartbeat(claim)
                except Exception as error:errors.append(error)
    thread=Thread(target=pulse);thread.start()
    try:yield track
    finally:
        stop.set();thread.join(timeout=10)
        assert not thread.is_alive() and not errors,errors


def test_findings_provenance_and_immutable_storage(api,jobdb,tmp_path,monkeypatch,finding_heartbeats):
    client,engine,storage=api
    _,repo,_=jobdb
    run=create_run(jobdb,storage,tmp_path/'source');rid=str(run['id'])
    configure_worker(engine,storage,monkeypatch)
    assert Worker(engine,task_timeout=120).run_once()
    report=client.get(f'/api/runs/{rid}/reports/1/json').json()
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'findings'}).json()['id']
    turn=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'question'},
                    json={'content':'保存候選觀察','selected_run_id':rid}).json()['turn_id']
    with engine.connect() as c:
        artifact=c.execute(text("SELECT * FROM artifacts WHERE run_id=:id AND kind='report_json'"),{'id':rid}).mappings().one()
        app=c.execute(text('SELECT p.app_id FROM projects p JOIN datasets d ON d.project_id=p.id WHERE d.id=:id'),{'id':run['dataset_id']}).scalar_one()
    candidate=report['candidates'][0]
    payload=dict(id=uuid4(),app_id=app,source_run_id=run['id'],source_dataset_id=run['dataset_id'],
                 report_version=1,report_artifact_id=artifact['id'],report_sha256=artifact['sha256'],
                 candidate_id=candidate['candidate_id'],event_spec=candidate['event_spec'],hypothesis='合成資料觀察',
                 limitations=['小樣本；非投放成效'],counterexamples=[],outcome='observation',
                 source_turn_id=turn,tool_call_id='save-1',payload_hash='a'*64)
    table=repo.tables['app_findings']
    with engine.begin() as c:c.execute(insert(table).values(**payload))
    with engine.connect() as c:assert c.execute(select(table.c.hypothesis)).scalar_one()=='合成資料觀察'
    for patch in ({'app_id':'foreign-app'},{'report_sha256':'b'*64},{'report_version':999},
                  {'outcome':'supported','previous_finding_id':payload['id']}):
        with pytest.raises(IntegrityError),engine.begin() as c:
            c.execute(insert(table).values(**{**payload,'id':uuid4(),'tool_call_id':str(uuid4()),'payload_hash':'c'*64,**patch}))
    with pytest.raises(ProgrammingError,match='immutable'),engine.begin() as c:
        c.execute(update(table).where(table.c.id==payload['id']).values(hypothesis='改寫'))
    with pytest.raises(IntegrityError),engine.begin() as c:c.execute(insert(table).values(**{**payload,'id':uuid4()}))
    with engine.connect() as c:assert c.execute(text('SELECT count(*) FROM app_findings')).scalar_one()==1

    from server.agent_queue import AgentQueue
    claim=AgentQueue(engine).claim('finding-test')
    finding_heartbeats(claim)
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-findings-token')
    headers={'Authorization':'Bearer synthetic-findings-token'}
    envelope={'turn_id':turn,'parent_run_id':rid,'worker_id':claim['worker_id'],'fence':claim['fence'],
              'tool_call_id':'save-tool','arguments':{'candidate_id':candidate['candidate_id'],
              'hypothesis':'觀察此規則','limitations':['合成小樣本'],'counterexamples':[]}}
    def call(name,body):return client.post('/internal/tools/'+name,json=body,headers=headers)
    saved=call('save_findings',envelope)
    assert saved.status_code==200,saved.text
    assert saved.json()['requires_new_batch_validation'] and not saved.json()['reused']
    assert call('save_findings',envelope).json()==saved.json()
    repeat=call('save_findings',{**envelope,'tool_call_id':'same-content'})
    assert repeat.json()['finding_id']==saved.json()['finding_id'] and repeat.json()['reused']
    changed=call('save_findings',{**envelope,'arguments':{**envelope['arguments'],'hypothesis':'改寫同call'}})
    assert changed.status_code==409
    for patch in ({'candidate_id':'fake'},{'limitations':[]},
                  {'outcome':'supported','previous_finding_id':saved.json()['finding_id']},
                  {'outcome':'historically_validated'}):
        rejected=call('save_findings',{**envelope,'tool_call_id':str(uuid4()),'arguments':{**envelope['arguments'],**patch}})
        assert rejected.status_code==422,rejected.text
    first=call('load_app_findings',{**envelope,'tool_call_id':'load','arguments':{'limit':1}})
    assert first.status_code==200,first.text
    item=first.json()['items'][0]
    assert item['event_spec']==candidate['event_spec'] and item['metrics']==candidate['metrics']
    assert item['requires_new_batch_validation'] and item['outcome_is_observation']
    assert 'object_key' not in first.text and 'user_id' not in first.text
    assert first.json()['next_cursor']
    rest=call('load_app_findings',{**envelope,'tool_call_id':'load-next','arguments':{'limit':1,'cursor':first.json()['next_cursor']}})
    assert len(rest.json()['items'])==1 and rest.json()['next_cursor'] is None
    assert call('load_app_findings',{**envelope,'arguments':{'app_id':'foreign'}}).status_code==422
    assert call('load_app_findings',{**envelope,'arguments':{'cursor':'bad'}}).status_code==422
    with engine.connect() as c:assert c.execute(text('SELECT count(*) FROM app_findings')).scalar_one()==2
    import subprocess
    import os
    from tests.browser_runtime import live_web
    subprocess.run(['npm','run','build','--workspace','agent'],check=True,capture_output=True,timeout=30)
    with live_web(engine,storage,tmp_path,include_api=True) as (_,base):
        sdk=subprocess.run(['node','agent/findings.integration.mjs',base,turn,rid,claim['worker_id'],str(claim['fence'])],
                           env=os.environ.copy(),capture_output=True,text=True,timeout=30)
        assert sdk.returncode==0,sdk.stdout+sdk.stderr
        print(sdk.stdout)
    with engine.connect() as c:assert c.execute(text('SELECT count(*) FROM app_findings')).scalar_one()==3
    assert call('save_findings',{**envelope,'fence':claim['fence']+1,'tool_call_id':'stale'}).status_code==409
    # Corrupt only this isolated synthetic object's bytes, then restore it exactly.
    from server.storage import ObjectManifest
    obj=ObjectManifest(artifact['object_key'],artifact['sha256'],artifact['size_bytes'],'application/json')
    original_bytes=storage.get_bytes(obj)
    try:
        storage.client.put_object(Bucket=storage.bucket,Key=artifact['object_key'],Body=b'corrupt-synthetic')
        broken=call('load_app_findings',{**envelope,'tool_call_id':'broken-source','arguments':{}})
        assert broken.status_code>=400 and 'references' not in broken.json()
        assert call('save_findings',{**envelope,'tool_call_id':'broken-save'}).status_code>=400
    finally:
        storage.client.put_object(Bucket=storage.bucket,Key=artifact['object_key'],Body=original_bytes)
    assert call('load_app_findings',{**envelope,'tool_call_id':'restored','arguments':{}}).status_code==200
    # Valid bounded observations can collectively exceed the model response budget.
    # Refuse the whole oversized page; a smaller page remains usable and paginated.
    large=['界'*990+str(i) for i in range(10)]
    for i in range(3):
        response=call('save_findings',{**envelope,'tool_call_id':f'large-{i}',
            'arguments':{**envelope['arguments'],'hypothesis':f'合成長限制 {i}',
                         'limitations':large,'counterexamples':large}})
        assert response.status_code==200,response.text
    oversized=call('load_app_findings',{**envelope,'tool_call_id':'too-large','arguments':{'limit':10}})
    assert oversized.status_code==413 and 'references' not in oversized.json()
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM conversation_events WHERE turn_id=:id AND kind='tool_completed' AND payload->>'tool_call_id'='too-large'"),{'id':turn}).scalar_one()==0
    small=call('load_app_findings',{**envelope,'tool_call_id':'smaller-page','arguments':{'limit':1}})
    assert small.status_code==200 and small.json()['next_cursor']
    assert client.post(f'/api/turns/{turn}/cancel',headers={'Idempotency-Key':'cancel-findings'}).status_code==200
    assert call('save_findings',{**envelope,'tool_call_id':'after-cancel'}).status_code==409
    assert call('load_app_findings',{**envelope,'tool_call_id':'read-after-cancel','arguments':{}}).status_code==409
    with engine.connect() as c:assert c.execute(text('SELECT count(*) FROM app_findings')).scalar_one()==6


def test_new_batch_observations_app_isolation_and_parallel_dedup(api,jobdb,tmp_path,monkeypatch,finding_heartbeats):
    from server.agent_queue import AgentQueue
    from concurrent.futures import ThreadPoolExecutor
    client,engine,storage=api
    configure_worker(engine,storage,monkeypatch)
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-findings-token')
    headers={'Authorization':'Bearer synthetic-findings-token'}
    def baseline(label,app='synthetic'):
        run=create_run(jobdb,storage,tmp_path/label)
        # Separate synthetic app fixture is configured before processing, not changing a published source.
        if app!='synthetic':
            with engine.begin() as c:c.execute(text('UPDATE projects SET app_id=:app WHERE id=(SELECT project_id FROM datasets WHERE id=:id)'),{'app':app,'id':run['dataset_id']})
        assert Worker(engine,task_timeout=120).run_once()
        response=client.get(f"/api/runs/{run['id']}/reports/1/json")
        with engine.connect() as c:
            state=c.execute(text('SELECT status,error,progress FROM runs WHERE id=:id'),{'id':run['id']}).mappings().one()
        assert response.status_code==200, {'response':response.text,'run':dict(state)}
        report=response.json()
        return str(run['id']),report
    def scope(rid,key):
        cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':key}).json()['id']
        turn=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':key},
                        json={'content':'保存或重驗觀察','selected_run_id':rid}).json()['turn_id']
        claim=AgentQueue(engine).claim(key)
        finding_heartbeats(claim)
        assert str(claim['id'])==turn
        return {'turn_id':turn,'parent_run_id':rid,'worker_id':claim['worker_id'],'fence':claim['fence']}
    def call(name,owner,args,key):
        return client.post('/internal/tools/'+name,headers=headers,json={**owner,'tool_call_id':key,'arguments':args})
    first,report=baseline('first');one=scope(first,'first-conversation')
    rule=report['candidates'][0]
    args={'candidate_id':rule['candidate_id'],'hypothesis':'記錄候選條件','limitations':['合成批次；不能宣稱獨立投放驗證'],'counterexamples':[]}
    saved=call('save_findings',one,args,'original');assert saved.status_code==200,saved.text
    previous=saved.json()['finding_id']
    second,new_report=baseline('second');two=scope(second,'second-conversation')
    loaded=call('load_app_findings',two,{},'prior').json()
    assert loaded['items'][0]['id']==previous and loaded['items'][0]['requires_new_batch_validation']
    assert loaded['items'][0]['source_run_id']==first
    ref=loaded['references'][0]
    resolved=client.get(f"/api/runs/{first}/references/{ref['artifact_id']}",params={'version':ref['report_version'],'pointer':ref['json_pointer']}).json()
    assert resolved['root_run_id']==first and resolved['root_run_id']!=second
    same=next(row for row in new_report['candidates'] if row['event_spec']==rule['event_spec'])
    for outcome in ['supported','contradicted','inconclusive']:
        observed=call('save_findings',two,{**args,'candidate_id':same['candidate_id'],'previous_finding_id':previous,
            'outcome':outcome,'hypothesis':f'合成儲存測試：{outcome}',
            'counterexamples':['此紀錄測試反例欄位，不是實際商業效果'] if outcome=='contradicted' else []},outcome)
        assert observed.status_code==200,observed.text
        assert observed.json()['requires_new_batch_validation']
    # This fixture reuses users intentionally: a new dataset ID must not remove existing contamination warnings.
    assert not new_report['audit']['validation_policy']['eligible']
    three=scope(second,'parallel-conversation')
    parallel={**args,'candidate_id':same['candidate_id'],'hypothesis':'兩個對話保存相同觀察'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda owner:call('save_findings',owner,parallel,'parallel'),[two,three]))
    assert all(r.status_code==200 for r in results),[r.text for r in results]
    assert len({r.json()['finding_id'] for r in results})==1
    assert sum(not r.json()['reused'] for r in results)==1
    foreign,foreign_report=baseline('foreign','other-app');other=scope(foreign,'foreign-conversation')
    assert call('load_app_findings',other,{},'empty').json()['items']==[]
    rejected=call('save_findings',other,{**args,'candidate_id':foreign_report['candidates'][0]['candidate_id'],
        'previous_finding_id':previous,'outcome':'supported'},'foreign-support')
    assert rejected.status_code==422
    with engine.connect() as c:assert c.execute(text('SELECT count(*) FROM app_findings')).scalar_one()==5
    from tests.test_upload_api import dataset,begin,put,finish,request
    from tests.test_ingest import MAPPING
    upload_sources=positive_sources
    EXPORT=POSITIVE_EXPORT
    from pathlib import Path
    from tests.test_search import CONFIG
    ds=dataset(client)
    index=client.get(f"/api/datasets/{ds['id']}/recheck-sources?limit=1").json()
    assert index['items'] and index['next_cursor']
    assert client.get(f"/api/datasets/{ds['id']}/recheck-sources?cursor=bad").status_code==422
    route=f"/api/datasets/{ds['id']}/finding-recheck"
    body={'config':CONFIG,'finding_ids':[previous]}
    # Missing mapping/time semantics rejects before sealing or creating a run.
    assert request(client,'POST',route,body).status_code in (409,422)
    source_dir=tmp_path/'uploaded-recheck';source_dir.mkdir()
    for source in upload_sources(source_dir):
        data=Path(source['path']).read_bytes()
        upload,digest=begin(client,ds['id'],data,role=source['role'])
        put(client,upload,digest,1,data);finish(client,upload,digest)
    assert request(client,'PUT',f"/api/datasets/{ds['id']}/mapping",{'mapping':MAPPING,'export_metadata':EXPORT}).status_code==200
    assert request(client,'POST',route,{**body,'finding_ids':[str(uuid4())]}).status_code==422
    assert request(client,'POST',route,{**body,'finding_ids':None}).status_code==422
    assert client.get(f"/api/datasets/{ds['id']}").json()['sealed_at'] is None
    import subprocess,tempfile
    from tests.browser_runtime import live_web
    selection_visual=Path(tempfile.mkdtemp(prefix='finding-selector-',dir=Path('.runtime').resolve()))
    from threading import Event,Thread
    import json
    stop=Event();worker_errors=[]
    def consume():
        try:
            while not stop.is_set():
                if not Worker(engine,task_timeout=120).run_once():stop.wait(.1)
        except BaseException as error:worker_errors.append(error)
    with live_web(engine,storage,selection_visual) as browser_url:
        consumer=Thread(target=consume);consumer.start()
        try:
            ui=subprocess.run(['node','scripts/finding_selector_qa.cjs',browser_url,ds['id'],previous,str(selection_visual/'visual'),'submit'],
                              capture_output=True,text=True,timeout=110)
        finally:
            stop.set();consumer.join(timeout=130)
        assert not consumer.is_alive() and not worker_errors,worker_errors
        print(f'Finding selector evidence: {selection_visual}\n{ui.stdout}')
        assert ui.returncode==0,ui.stdout+ui.stderr
    submitted=next(json.loads(line) for line in ui.stdout.splitlines() if 'browserSubmission' in line)
    body=submitted['body'];key=submitted['key']
    queued=request(client,'POST',route,body,key)
    assert queued.status_code==202,queued.text
    assert queued.json()==submitted['queued']
    assert request(client,'POST',route,body,key).json()==queued.json()
    assert request(client,'POST',route,{**body,'config':{**body['config'],'seed':body['config']['seed']+1}},key).status_code==409
    recheck={'id':queued.json()['run_id']}
    response=client.get(f"/api/runs/{recheck['id']}/reports/1/json")
    assert response.status_code==200,response.text
    fixed=response.json()
    assert [row['candidate_id'] for row in fixed['candidates']]==[rule['candidate_id']]
    assert fixed['candidates'][0]['event_spec']==rule['event_spec']
    assert fixed['summary']['finding_recheck']['sources'][0]['finding_id']==previous
    assessment=fixed['summary']['finding_recheck']['assessments'][0]
    assert assessment['status']=='exploratory_only' and assessment['reusable'] is False
    assert 'USERS_OVERLAP_EXPOSED_DATA' in assessment['reasons']
    html=client.get(f"/api/runs/{recheck['id']}/reports/1/html")
    assert html.status_code==200 and '固定舊規則重驗' in html.text and '僅探索性結果' in html.text and previous in html.text
    assert fixed['candidates'][0]['selection_evidence'] is None
    assert fixed['audit']['validation_policy']['eligible'] is False
    with engine.connect() as c:
        stages=c.execute(text('SELECT stage FROM stage_checkpoints WHERE run_id=:id'),{'id':recheck['id']}).scalars().all()
        assert 'fixed_recheck' in stages and 'search' not in stages and 'selection' not in stages
    import subprocess,tempfile
    from pathlib import Path
    from tests.browser_runtime import live_web
    with engine.connect() as c:
        current=c.execute(text('SELECT * FROM agent_turns WHERE id=:id'),{'id':two['turn_id']}).mappings().one()
    # Persist a clearly synthetic assistant message referencing the actual load-tool evidence.
    AgentQueue(engine).finish(dict(current),'合成歷史觀察引用：'+ref['evidence_id'])
    visual=Path(tempfile.mkdtemp(prefix='finding-ui-',dir=Path('.runtime').resolve()))
    with live_web(engine,storage,visual) as base:
        checked=subprocess.run(['node','scripts/finding_reference_qa.cjs',base,second,first,str(current['conversation_id']),str(visual/'visual')],
                               capture_output=True,text=True,timeout=30)
        print(f'Finding browser evidence: {visual}\n{checked.stdout}')
        assert checked.returncode==0,checked.stdout+checked.stderr
