"""Upgrade a real nonempty 0011 database; never downgrade or delete user data."""
import os
import subprocess
import sys
import pytest
from sqlalchemy import text,insert
from scripts.local_postgres import LocalPostgres
from server.db import Repository,database_engine
from server.worker import Worker
from tests.test_upload_api import api
from tests.test_pipeline import create_run,configure_worker
from tests.test_search import CONFIG


@pytest.fixture
def jobdb():
    with LocalPostgres() as pg:
        subprocess.run([sys.executable,'-m','alembic','upgrade','0011'],check=True,capture_output=True,
            env={**os.environ,'DATABASE_URL':pg.url},timeout=30)
        engine=database_engine(pg.url);repo=Repository(engine)
        with engine.begin() as c:
            project=repo.create_project(c,'synthetic','Legacy migration fixture')
            dataset=repo.create_dataset(c,project['id'])
            repo.seal_dataset(c,dataset['id'],[{'synthetic':True}],{},{})
        yield engine,repo,dataset['id']
        engine.dispose()


def test_nonempty_legacy_branches_backfill_without_reset(api,jobdb,tmp_path,monkeypatch):
    client,engine,storage=api;_,repo,_=jobdb
    parent=create_run(jobdb,storage,tmp_path/'parent');rid=str(parent['id'])
    configure_worker(engine,storage,monkeypatch);assert Worker(engine,task_timeout=120).run_once()
    report=client.get(f'/api/runs/{rid}/reports/1/json').content
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'c'}).json()['id']
    tid=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'m'},json={'content':'Legacy synthetic round','selected_run_id':rid}).json()['turn_id']
    children=[]
    with engine.begin() as c:
        assert c.execute(text("SELECT to_regclass('exploration_budgets')")).scalar_one() is None
        artifact=c.execute(text('''SELECT a.* FROM report_versions v JOIN artifacts a ON a.id=v.artifact_id
            WHERE v.run_id=:id AND v.version=1'''),{'id':rid}).mappings().one()
        for ordinal,cap in enumerate([20,30],1):
            child=repo.create_run(c,parent['dataset_id'],{**CONFIG,'windows_hours':[3],'max_candidates':cap},
                f'legacy-{ordinal}',parent_run_id=parent['id'])
            c.execute(insert(repo.tables['analysis_branches']).values(run_id=child['id'],source_turn_id=tid,
                tool_call_id=f'legacy-{ordinal}',parent_report_artifact_id=artifact['id'],parent_report_version=1,
                parent_report_sha256=artifact['sha256'],config_delta={},cache_context={}))
            children.append(child['id'])
        before=c.execute(text('SELECT created_at FROM agent_turns WHERE id=:id'),{'id':tid}).scalar_one()
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],check=True,capture_output=True,
        env={**os.environ,'DATABASE_URL':engine.url.render_as_string(hide_password=False)},timeout=30)
    with engine.connect() as c:
        budget=c.execute(text('SELECT * FROM exploration_budgets WHERE turn_id=:id'),{'id':tid}).mappings().one()
        rows=c.execute(text('SELECT * FROM exploration_rounds WHERE turn_id=:id ORDER BY ordinal'),{'id':tid}).mappings().all()
        assert [r['run_id'] for r in rows]==children
        assert [r['reserved_candidates'] for r in rows]==[20,30]
        assert [r['ordinal'] for r in rows]==[1,2]
        assert budget['created_at']==before and (budget['deadline']-before).total_seconds()==600
        notes=c.execute(text('SELECT hypothesis,based_on FROM exploration_round_notes ORDER BY run_id')).mappings().all()
        assert len(notes)==2 and all(r['hypothesis'] is None and r['based_on']==[] for r in notes)
        assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0017'
        assert c.execute(text('SELECT count(*) FROM app_findings')).scalar_one()==0
        assert c.execute(text('SELECT count(*) FROM finding_rechecks')).scalar_one()==0
        assert c.execute(text('SELECT count(*) FROM agent_tool_calls')).scalar_one()==0
        assert c.execute(text('SELECT count(*) FROM agent_tool_results')).scalar_one()==0
        assert c.execute(text('SELECT count(*) FROM agent_runtime_sessions')).scalar_one()==0
        assert c.execute(text('SELECT count(*) FROM agent_model_steps')).scalar_one()==0
        assert c.execute(text('SELECT count(*) FROM agent_step_results')).scalar_one()==0
    assert client.get(f'/api/runs/{rid}/reports/1/json').content==report
