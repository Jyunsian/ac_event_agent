"""One empty, real workspace, UI upload through four Agent requests to downloaded artifacts."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
from sqlalchemy import text
from scripts.local_postgres import LocalPostgres
from scripts.local_s3 import LocalS3
from server.db import database_engine
from server.storage import S3Storage
from tests.browser_runtime import live_web
from tests.test_ingest import sources, MAPPING
from tests.test_pipeline import configure_worker


def test_empty_workspace_upload_to_agent_branches_and_export(tmp_path,monkeypatch):
    root=Path(tempfile.mkdtemp(prefix='product-e2e-',dir=Path('.runtime').resolve()))
    files=sources(tmp_path)
    manifest=root/'inputs.json'
    manifest.write_text(json.dumps({'users':next(f['path'] for f in files if f['role']=='users'),
        'events':[f['path'] for f in files if f['role']=='events'],'mapping':MAPPING}))
    with LocalPostgres() as pg, LocalS3() as s3:
        subprocess.run([sys.executable,'-m','alembic','upgrade','head'],check=True,
            env={**os.environ,'DATABASE_URL':pg.url},capture_output=True,timeout=30)
        engine=database_engine(pg.url)
        try:
            storage=S3Storage('product-synthetic',s3.endpoint,s3.access_key,s3.secret_key);storage.create_bucket()
            configure_worker(engine,storage,monkeypatch)
            monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-product-token')
            with engine.connect() as c:
                for table in ['projects','datasets','runs','messages','jobs']:
                    assert c.execute(text(f'SELECT count(*) FROM {table}')).scalar_one()==0
            subprocess.run(['npm','run','build','--workspace','agent'],check=True,capture_output=True,timeout=30)
            with live_web(engine,storage,root,include_api=True) as (base,endpoint):
                with (root/'python.log').open('w') as log:
                    compute=subprocess.Popen([sys.executable,'-m','server.worker'],stdout=log,stderr=subprocess.STDOUT)
                    agent=subprocess.Popen(['node','agent/product-browser-worker.mjs',endpoint],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                    try:
                        assert select.select([agent.stdout],[],[],10)[0],'Agent startup timeout'
                        health=agent.stdout.readline().strip();assert health.startswith('http://127.0.0.1:')
                        monkeypatch.setenv('AGENT_HEALTH_URL',health)
                        result=subprocess.run(['node','scripts/product_browser_qa.cjs',base,str(manifest),str(root/'visual')],capture_output=True,text=True,timeout=240)
                        assert result.returncode==0,result.stdout+result.stderr+f'\nEvidence: {root}'
                        checks=json.loads((root/'visual/checks.json').read_text())
                        with engine.connect() as c:
                            assert c.execute(text('SELECT count(*) FROM datasets')).scalar_one()==1
                            assert c.execute(text("SELECT count(*) FROM agent_turns WHERE status='succeeded'")).scalar_one()==4
                            assert c.execute(text('SELECT count(*) FROM analysis_branches')).scalar_one()==3
                            calls=c.execute(text('SELECT tool_name FROM agent_tool_calls')).scalars().all()
                            for tool in ['profile_dataset','get_baseline_report','search_candidates','rerun_analysis','analyze_segment','evaluate_analysis']:assert tool in calls
                            rows=c.execute(text('SELECT config FROM runs WHERE parent_run_id=:id'),{'id':checks['parent']}).scalars().all()
                            assert any(row['windows_hours']==[3] for row in rows)
                        print(f'Product browser evidence: {root}\n{result.stdout}')
                    finally:
                        agent.terminate();agent.wait(timeout=10)
                        compute.terminate();compute.wait(timeout=10)
        finally:engine.dispose()
