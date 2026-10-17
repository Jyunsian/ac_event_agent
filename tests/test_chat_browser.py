import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import select
from urllib.parse import urlparse
from sqlalchemy import text
from server.worker import Worker
from tests.browser_runtime import live_web
from tests.test_jobs import jobdb
from tests.test_upload_api import api
from tests.test_pipeline import create_run,configure_worker


def test_chat_with_real_worker_api_and_persistent_report(api,jobdb,tmp_path,monkeypatch):
    _,engine,storage=api
    from tests.positive_sources import positive_sources,POSITIVE_EXPORT
    monkeypatch.setattr('tests.test_pipeline.sources',positive_sources)
    monkeypatch.setattr('tests.test_pipeline.EXPORT',POSITIVE_EXPORT)
    run=create_run(jobdb,storage,tmp_path/'source');configure_worker(engine,storage,monkeypatch)
    assert Worker(engine,task_timeout=120).run_once()
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-browser-token')
    subprocess.run(['npm','run','build','--workspace','agent'],check=True,capture_output=True,timeout=30)
    with live_web(engine,storage,tmp_path,include_api=True) as (url,endpoint):
        worker=subprocess.Popen(['node','agent/browser-worker.mjs',endpoint],env=os.environ.copy(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            assert select.select([worker.stdout],[],[],10)[0],'Node worker did not start in 10 seconds'
            health=worker.stdout.readline().strip();assert health.startswith('http://127.0.0.1:')
            monkeypatch.setenv('AGENT_HEALTH_URL',health)
            process=subprocess.run(['node','scripts/chat_browser_qa.cjs',url,str(run['id']),str(tmp_path/'visual')],capture_output=True,text=True,timeout=120)
            assert process.returncode==0,process.stdout+process.stderr
            with engine.connect() as c:
                saved=c.execute(text('''SELECT count(*) FROM agent_tool_results r JOIN agent_tool_calls t
                    USING(turn_id,tool_call_id) WHERE t.tool_name='get_baseline_report'
                    AND r.output->>'tool'='get_baseline_report' ''')).scalar_one()
                assert saved>0,'Production Node Worker did not persist any real SDK tool results'
                steps=c.execute(text("SELECT messages,usage FROM agent_step_results WHERE finish_reason='stop'")).mappings().all()
                assert steps,'Production Node Worker did not persist completed SDK steps'
                assert all(row['messages'] and row['usage']['input_tokens'] is not None for row in steps)
                assert all(any(message['role']=='tool' for message in row['messages']) for row in steps), 'Final checkpoint lost prior tool messages'
            worker.terminate();worker.wait(timeout=10)
            worker=subprocess.Popen(['node','agent/dist/index.js'],env={**os.environ,'AGENT_PORT':str(urlparse(health).port),
                'OPENROUTER_API_KEY':'','OPENROUTER_MODEL':'','AGENT_INTERNAL_TOKEN':'','AGENT_API_BASE_URL':''},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            assert select.select([worker.stdout],[],[],10)[0],'No-key Node did not start'
            assert 'listening' in worker.stdout.readline()
            missing=subprocess.run(['node','scripts/chat_browser_qa.cjs',url,str(run['id']),str(tmp_path/'visual'),'no-key'],capture_output=True,text=True,timeout=60)
            assert missing.returncode==0,missing.stdout+missing.stderr
            retained=Path(tempfile.mkdtemp(prefix='chat-ui-',dir=Path('.runtime')))
            shutil.copytree(tmp_path/'visual',retained/'visual');print(f'Browser evidence retained: {retained.resolve()}\n{process.stdout}\n{missing.stdout}')
        finally:
            worker.terminate();worker.wait(timeout=10)
