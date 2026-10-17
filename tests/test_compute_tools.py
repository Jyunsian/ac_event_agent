import json
import os
import socket
import subprocess
import threading
import time
import pytest
from pathlib import Path
import tempfile
import shutil
import uvicorn
from sqlalchemy import text
from server.api.main import create_app
from server.worker import Worker
from server.agent_queue import AgentQueue
from tests.test_jobs import jobdb
from tests.test_upload_api import api
from tests.test_pipeline import create_run,configure_worker
from tests.browser_runtime import live_web


def blocked_search_handler(payload):
    """Test-only barrier inside the real pipeline, after normalized/target work."""
    import server.pipeline as pipeline
    from server.db import database_engine
    from server.worker import baseline_handler
    original=pipeline.generate_candidates
    def search(*args,**kwargs):
        engine=database_engine()
        with engine.connect() as c:c.execute(text('SELECT pg_advisory_lock(310031)'))
        engine.dispose()
        return original(*args,**kwargs)
    pipeline.generate_candidates=search
    return baseline_handler(payload)


def test_agent_cancellation_terminates_real_pipeline_process(api,jobdb,tmp_path,monkeypatch):
    client,engine,storage=api
    parent=create_run(jobdb,storage,tmp_path/'parent');rid=str(parent['id'])
    configure_worker(engine,storage,monkeypatch);assert Worker(engine,task_timeout=120).run_once()
    original=client.get(f'/api/runs/{rid}/reports/1/json').content
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'c'}).json()['id']
    turn=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'m'},json={
        'content':'分析前3小時','selected_run_id':rid}).json()['turn_id']
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-compute-token')
    subprocess.run(['npm','run','build','--workspace','agent'],check=True,capture_output=True,timeout=30)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
    url=f'http://127.0.0.1:{listener.getsockname()[1]}'
    server=uvicorn.Server(uvicorn.Config(create_app(engine,storage),log_level='warning',access_log=False))
    api_thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);api_thread.start()
    worker=Worker(engine,handler=blocked_search_handler,heartbeat_seconds=.1,lease_seconds=3,task_timeout=120)
    compute_thread=None;process=None;lock=engine.connect()
    try:
        lock.execute(text('SELECT pg_advisory_lock(310031)'))
        process=subprocess.Popen(['node','agent/compute.integration.mjs',url,'cancel'],env=os.environ.copy(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        deadline=time.monotonic()+20;child=None
        while time.monotonic()<deadline:
            with engine.connect() as c:
                child=c.execute(text('SELECT run_id FROM analysis_branches WHERE source_turn_id=:id'),{'id':turn}).scalar_one_or_none()
            if child:break
            assert process.poll() is None;time.sleep(.05)
        assert child,'Agent did not create branch'
        compute_thread=threading.Thread(target=worker.run_once,daemon=True);compute_thread.start()
        while time.monotonic()<deadline:
            with engine.connect() as c:
                blocked=c.execute(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid=310031 AND NOT granted")).scalar_one()
                waiting=c.execute(text("SELECT count(*) FROM conversation_events WHERE turn_id=:id AND kind='tool_running' AND payload->>'tool'='evaluate_analysis'"),{'id':turn}).scalar_one()
            if blocked and waiting:break
            time.sleep(.05)
        assert blocked==1 and waiting==1
        assert worker.child and worker.child.is_alive();pid=worker.child.pid
        # Read the immutable report while the child is demonstrably executing.
        assert client.get(f'/api/runs/{rid}/reports/1/json').content==original
        visual=Path(tempfile.mkdtemp(prefix='pending-ui-',dir=Path('.runtime').resolve()))
        with live_web(engine,storage,visual) as browser_url:
            checked=subprocess.run(['node','scripts/version_browser_qa.cjs',browser_url,rid,cid,str(visual/'visual'),'pending'],
                                   capture_output=True,text=True,timeout=25)
            print(f'Pending browser evidence: {visual}\n{checked.stdout}')
            assert checked.returncode==0,checked.stdout+checked.stderr
        assert worker.child and worker.child.is_alive()
        response=client.post(f'/api/turns/{turn}/cancel',headers={'Idempotency-Key':'cancel-active-compute'})
        assert response.status_code==200
        compute_thread.join(5);assert not compute_thread.is_alive() and worker.child is None
        with pytest.raises(ProcessLookupError):os.kill(pid,0)
        stdout,stderr=process.communicate(timeout=10)
        assert process.returncode==0,stdout+stderr
        assert json.loads(stdout)['cancelled'] is True
        with engine.connect() as c:
            assert c.execute(text('SELECT status FROM agent_turns WHERE id=:id'),{'id':turn}).scalar_one()=='cancelled'
            assert c.execute(text('SELECT status FROM jobs WHERE run_id=:id'),{'id':child}).scalar_one()=='cancelled'
            assert c.execute(text('SELECT count(*) FROM report_versions WHERE run_id=:id'),{'id':child}).scalar_one()==0
            assert c.execute(text("SELECT count(*) FROM messages WHERE turn_id=:id AND role='assistant'"),{'id':turn}).scalar_one()==0
            assert c.execute(text('SELECT count(*) FROM stage_checkpoints WHERE run_id=:id'),{'id':child}).scalar_one()>=3
        assert client.get(f'/api/runs/{rid}/reports/1/json').content==original
    finally:
        worker.stop()
        lock.execute(text('SELECT pg_advisory_unlock(310031)'));lock.close()
        if compute_thread:compute_thread.join(5)
        if process and process.poll() is None:process.terminate();process.wait(timeout=5)
        server.should_exit=True;api_thread.join(10);listener.close()


@pytest.mark.parametrize('mode',['success','segment','adaptive','step_limit','timeout'])
def test_sdk_natural_language_rerun_computes_real_child(api,jobdb,tmp_path,monkeypatch,mode):
    client,engine,storage=api
    if mode in ('success','adaptive'):
        from tests.positive_sources import positive_sources,adaptive_sources, POSITIVE_EXPORT
        monkeypatch.setattr('tests.test_pipeline.sources',adaptive_sources if mode=='adaptive' else positive_sources)
        monkeypatch.setattr('tests.test_pipeline.EXPORT',POSITIVE_EXPORT)
    if mode=='segment':
        from tests.test_search import CONFIG
        monkeypatch.setattr('tests.test_pipeline.CONFIG',{**CONFIG,'min_group_users':2})
    parent=create_run(jobdb,storage,tmp_path/'parent');rid=str(parent['id'])
    configure_worker(engine,storage,monkeypatch);assert Worker(engine,task_timeout=120).run_once()
    original=client.get(f'/api/runs/{rid}/reports/1/json').content
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'conversation'}).json()['id']
    sent=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'question'},json={
        'content':'分析美國子群' if mode=='segment' else '分析前3小時，展示2次或收益0.02美元的候選事件','selected_run_id':rid}).json()
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-compute-token')
    subprocess.run(['npm','run','build','--workspace','agent'],check=True,capture_output=True,timeout=30)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
    url=f'http://127.0.0.1:{listener.getsockname()[1]}'
    server=uvicorn.Server(uvicorn.Config(create_app(engine,storage),log_level='warning',access_log=False))
    api_thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);api_thread.start()
    stopping=threading.Event();errors=[];heartbeats=[];agent_heartbeats=[]
    agent_heartbeat=AgentQueue.heartbeat
    def tracked_agent(queue,claim):
        agent_heartbeat(queue,claim);agent_heartbeats.append(claim['turn_id'] if 'turn_id' in claim else claim['id'])
    monkeypatch.setattr(AgentQueue,'heartbeat',tracked_agent)
    worker=Worker(engine,heartbeat_seconds=.1,lease_seconds=5,task_timeout=120)
    heartbeat=worker.queue.heartbeat
    def tracked(lease):
        heartbeat(lease);heartbeats.append(lease.run_id)
    monkeypatch.setattr(worker.queue,'heartbeat',tracked)
    def loop():
        try:
            while not stopping.is_set():
                if not worker.run_once():stopping.wait(.05)
        except BaseException as error:errors.append(error)
    compute_thread=threading.Thread(target=loop,daemon=True);compute_thread.start()
    try:
        process=subprocess.run(['node','agent/compute.integration.mjs',url,mode],env=os.environ.copy(),
            capture_output=True,text=True,timeout=90)
        assert process.returncode==0,process.stdout+process.stderr
        data=json.loads(process.stdout);child=data['child']
        if mode in ('step_limit','timeout'):
            assert data['limited']==mode and not errors
            with engine.connect() as c:
                limited=c.execute(text('SELECT status,error FROM agent_turns WHERE id=:id'),{'id':sent['turn_id']}).mappings().one()
                assert limited['status']=='failed'
                assert limited['error']['code']==('AGENT_STEP_LIMIT' if mode=='step_limit' else 'AGENT_TIMEOUT')
                assert c.execute(text("SELECT count(*) FROM messages WHERE turn_id=:id AND role='assistant'"),{'id':sent['turn_id']}).scalar_one()==0
            assert client.get(f'/api/runs/{child}/view').json()['ready']
            assert client.get(f'/api/runs/{child}/reports/1/json').status_code==200
            assert client.get(f'/api/runs/{rid}/reports/1/json').content==original
            return
        assert data['synthetic'] and data['steps']>=3 and not errors
        assert sum(str(r)==child for r in heartbeats)>=2
        assert sum(str(t)==sent['turn_id'] for t in agent_heartbeats)>=2
        actual=client.get(f'/api/runs/{child}/reports/1/json').json()
        assert actual['run_id']==child
        assert data['result']['content']['candidates'] or mode=='segment'
        for returned,row in zip(data['result']['content']['candidates'],actual['candidates'],strict=True):
            assert returned['metrics']==row['metrics'] and returned['event_spec']==row['event_spec']
        # Independent hand fixture truth: holdout u4/u5; only u5 has a 3h
        # ad (at 2h), D7 revenue .02. u4's ad is outside this window.
        metrics=[row['metrics'] for row in actual['candidates'] if row['metrics']] if mode!='adaptive' else []
        assert (metrics or mode in ('segment','adaptive')) and all(m['groups']['all']['users']==(200 if mode=='success' else 2) for m in metrics)
        hits=[m for m in metrics if m['groups']['triggered']['users']]
        assert hits or mode in ('segment','adaptive')
        for metric in hits:
            assert metric['groups']['triggered']['users']==(100 if mode=='success' else 1)
            assert metric['groups']['triggered']['arpu_usd']==pytest.approx(2.00294 if mode=='success' else .02)
            assert metric['coverage']==.5 and metric['delay_seconds']['median']==(3600 if mode=='success' else 7200)
        with engine.connect() as c:
            turn=c.execute(text('SELECT * FROM agent_turns WHERE id=:id'),{'id':sent['turn_id']}).mappings().one()
            assert turn['status']=='succeeded' and turn['fence']==1
            assert c.execute(text('SELECT count(*) FROM analysis_branches WHERE source_turn_id=:id'),{'id':sent['turn_id']}).scalar_one()==(2 if mode=='adaptive' else 1)
            if mode=='adaptive':
                rounds=c.execute(text('SELECT * FROM exploration_rounds WHERE turn_id=:id ORDER BY ordinal'),{'id':sent['turn_id']}).mappings().all()
                assert [r['parameters']['windows_hours'] for r in rounds]==[[3],[24]]
                assert [str(r['run_id']) for r in rounds]==data['children']
                notes=c.execute(text('''SELECT n.* FROM exploration_round_notes n JOIN exploration_rounds r ON r.run_id=n.run_id
                    WHERE r.turn_id=:id ORDER BY r.ordinal'''),{'id':sent['turn_id']}).mappings().all()
                assert notes[0]['hypothesis']=='先檢查較早窗口的覆蓋。'
                assert notes[1]['based_on']==[data['firstEvidence']]
                final=c.execute(text('SELECT * FROM exploration_finalizations WHERE turn_id=:id'),{'id':sent['turn_id']}).mappings().one()
                assert str(final['run_id'])==child and len(final['candidate_ids'])==2
                assert data['firstEvidence'].startswith('report:') and data['steps']==7
            answer=c.execute(text("SELECT content FROM messages WHERE turn_id=:id AND role='assistant'"),{'id':sent['turn_id']}).scalar_one()
            assert data['result']['references'][0]['evidence_id'] in answer
        assert client.get(f'/api/runs/{rid}/reports/1/json').content==original
        events=client.get(f'/api/conversations/{cid}/events').json()['events']
        cards=[event for event in events if event['kind'].startswith('tool_')]
        expected=[
            ('analyze_segment' if mode=='segment' else 'rerun_analysis','tool_running'),('analyze_segment' if mode=='segment' else 'rerun_analysis','tool_completed'),
            ('evaluate_analysis','tool_running'),('evaluate_analysis','tool_completed')]
        if mode=='adaptive':expected=expected*2+[('finalize_candidates','tool_completed')]
        assert [(event['payload']['tool'],event['kind']) for event in cards]==expected
        assert cards[-1]['payload']['run_id']==child
        assert cards[-1]['payload']['report_version']==1
        assert cards[-1]['payload']['references']==data['result']['references']
    finally:
        stopping.set();worker.stop();compute_thread.join(10)
        server.should_exit=True;api_thread.join(10);listener.close()
    assert not compute_thread.is_alive() and not errors
    if mode=='adaptive':return  # Two-round business flow; shared UI already covered by sibling cases.
    with live_web(engine,storage,tmp_path) as browser_url:
        browser=subprocess.run(['node','scripts/compute_browser_qa.cjs',browser_url,rid,child,cid,str(tmp_path/'visual'),mode],
            capture_output=True,text=True,timeout=60)
        assert browser.returncode==0,browser.stdout+browser.stderr
        retained=Path(tempfile.mkdtemp(prefix='compute-ui-',dir=Path('.runtime')))
        shutil.copytree(tmp_path/'visual',retained/'visual')
        print(f'Browser evidence retained: {retained.resolve()}\n{browser.stdout}')
