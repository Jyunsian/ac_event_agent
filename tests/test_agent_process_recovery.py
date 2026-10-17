"""SIGKILL the real Node Worker at three durable boundaries; real Python/PG/S3."""
import os
import json
import select
import subprocess
import time
from threading import Event,Thread
from sqlalchemy import text
import pytest
from server.agent_queue import AgentQueue
from server.worker import Worker
from tests.test_jobs import jobdb
from tests.test_upload_api import api
from tests.test_pipeline import create_run,configure_worker
from tests.browser_runtime import live_web


def failed_compute(payload):
    from server.worker import TaskFailure
    raise TaskFailure('SYNTHETIC_COMPUTE_FAILED')


@pytest.mark.parametrize('mode',['before','after','finish'])
def test_node_sigkill_restores_original_tool_identity(api,jobdb,tmp_path,monkeypatch,mode):
    client,engine,storage=api
    run=create_run(jobdb,storage,tmp_path/'source');rid=str(run['id'])
    configure_worker(engine,storage,monkeypatch);assert Worker(engine,task_timeout=120).run_once()
    original=client.get(f'/api/runs/{rid}/reports/1/json').content
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'recovery'}).json()['id']
    tid=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'question'},
        json={'content':'合成測試：比較前3小時','selected_run_id':rid}).json()['turn_id']
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-recovery-token')
    # Real leases expire naturally, shortened only in this isolated API fixture.
    monkeypatch.setattr('server.api.main.AgentQueue',lambda engine:AgentQueue(engine,lease_seconds=3))
    subprocess.run(['npm','run','build','--workspace','agent'],check=True,capture_output=True,timeout=30)
    stop=Event();errors=[]
    def consume():
        try:
            while not stop.is_set():
                if not Worker(engine,task_timeout=120).run_once():stop.wait(.1)
        except BaseException as error:errors.append(error)
    consumer=Thread(target=consume);consumer.start();process=None
    try:
        with live_web(engine,storage,tmp_path,include_api=True) as (_,base):
            process=subprocess.Popen(['node','agent/recovery.integration.mjs',base,mode],env=os.environ.copy(),
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            assert select.select([process.stdout],[],[],45)[0],'Live Node did not reach requested fault boundary'
            marker=process.stdout.readline().strip()
            assert json.loads(marker)=={'barrier':mode},marker
            assert process.poll() is None
            with engine.connect() as c:
                count=c.execute(text('SELECT count(*) FROM analysis_branches WHERE source_turn_id=:id'),{'id':tid}).scalar_one()
                assert count==(0 if mode=='before' else 1)
                before=c.execute(text('SELECT count(*) FROM agent_model_steps WHERE turn_id=:id'),{'id':tid}).scalar_one()
                assert before>=2
                assert c.execute(text("SELECT count(*) FROM messages WHERE turn_id=:id AND role='assistant'"),{'id':tid}).scalar_one()==0
            process.kill();process.wait(timeout=5);assert process.returncode!=0
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                with engine.connect() as c:
                    expired=c.execute(text('SELECT lease_until<=clock_timestamp() FROM agent_turns WHERE id=:id'),{'id':tid}).scalar_one()
                if expired:break
                time.sleep(.05)
            assert expired,'Exact killed Node lease did not expire'
            resumed=subprocess.run(['node','agent/recovery.integration.mjs',base,'resume'],env=os.environ.copy(),
                capture_output=True,text=True,timeout=60)
            assert resumed.returncode==0,resumed.stdout+resumed.stderr
            output=json.loads(resumed.stdout.strip())
            assert output['finished']
            if mode=='finish':assert output['generations']==0,'Committed final checkpoint should not call the model again'
        with engine.connect() as c:
            turn=c.execute(text('SELECT status,fence,error FROM agent_turns WHERE id=:id'),{'id':tid}).mappings().one()
            assert turn['status']=='succeeded' and turn['fence']==2,turn
            children=c.execute(text('SELECT run_id,tool_call_id FROM analysis_branches WHERE source_turn_id=:id'),{'id':tid}).mappings().all()
            assert len(children)==1 and children[0]['tool_call_id']=='rerun'
            assert c.execute(text('SELECT count(*) FROM report_versions WHERE run_id=:id'),{'id':children[0]['run_id']}).scalar_one()==1
            assert c.execute(text("SELECT count(*) FROM messages WHERE turn_id=:id AND role='assistant'"),{'id':tid}).scalar_one()==1
            assert c.execute(text("SELECT count(*) FROM agent_tool_calls WHERE turn_id=:id AND tool_call_id='rerun'"),{'id':tid}).scalar_one()==1
            after=c.execute(text('SELECT count(*) FROM agent_model_steps WHERE turn_id=:id'),{'id':tid}).scalar_one()
            assert after==before if mode=='finish' else after>before
        assert client.get(f'/api/runs/{rid}/reports/1/json').content==original
    finally:
        if process and process.poll() is None:process.kill();process.wait(timeout=5)
        stop.set();consumer.join(timeout=130)
        assert not consumer.is_alive() and not errors,errors


@pytest.mark.parametrize('mode',['model-failure','compute-failure'])
def test_model_and_compute_failure_preserve_distinct_states(api,jobdb,tmp_path,monkeypatch,mode):
    client,engine,storage=api
    run=create_run(jobdb,storage,tmp_path/'source');rid=str(run['id'])
    configure_worker(engine,storage,monkeypatch);assert Worker(engine,task_timeout=120).run_once()
    original=client.get(f'/api/runs/{rid}/reports/1/json').content
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'failure'}).json()['id']
    tid=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'question'},
        json={'content':'合成模型與計算失敗驗收','selected_run_id':rid}).json()['turn_id']
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-recovery-token')
    subprocess.run(['npm','run','build','--workspace','agent'],check=True,capture_output=True,timeout=30)
    stop=Event();errors=[]
    def consume():
        try:
            while not stop.is_set():
                kwargs={'handler':failed_compute} if mode=='compute-failure' else {}
                if not Worker(engine,task_timeout=120,**kwargs).run_once():stop.wait(.1)
        except BaseException as error:errors.append(error)
    consumer=Thread(target=consume);consumer.start()
    try:
        with live_web(engine,storage,tmp_path,include_api=True) as (_,base):
            process=subprocess.run(['node','agent/recovery.integration.mjs',base,mode],env=os.environ.copy(),
                capture_output=True,text=True,timeout=60)
            assert process.returncode==0,process.stdout+process.stderr
        with engine.connect() as c:
            turn=c.execute(text('SELECT status,error FROM agent_turns WHERE id=:id'),{'id':tid}).mappings().one()
            child=c.execute(text('''SELECT r.id,r.status,r.error FROM runs r JOIN analysis_branches b ON b.run_id=r.id
                WHERE b.source_turn_id=:id'''),{'id':tid}).mappings().one()
            reports=c.execute(text('SELECT count(*) FROM report_versions WHERE run_id=:id'),{'id':child['id']}).scalar_one()
            if mode=='model-failure':
                assert turn['status']=='failed' and turn['error']['code']=='AGENT_MODEL_FAILED'
                assert child['status']=='succeeded' and reports==1
                assert client.get(f"/api/runs/{child['id']}/reports/1/json").status_code==200
            else:
                assert turn['status']=='succeeded' and turn['error'] is None
                assert child['status']=='failed' and reports==0
                assert child['error']['code']=='SYNTHETIC_COMPUTE_FAILED'
        assert client.get(f'/api/runs/{rid}/reports/1/json').content==original
    finally:
        stop.set();consumer.join(timeout=130)
        assert not consumer.is_alive() and not errors,errors
