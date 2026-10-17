import json
import concurrent.futures
import time
import pytest
from uuid import uuid4
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from server.worker import Worker
from tests.test_jobs import jobdb
from tests.test_upload_api import api
from tests.test_pipeline import create_run,configure_worker
from tests.test_ingest import HAND,MAPPING,write_source
from tests.test_quality import EXPORT
from tests.test_search import CONFIG
from server.jobs import JobQueue
from server.uploads import UploadService
from server.validation_exposure import record_report_exposure
from server.analysis.ingest import IngestError,file_hash
from server.storage import ObjectManifest
import server.pipeline as pipeline
from server.validation_policy import POLICY_LOCK


def new_users_run(jobdb,storage,directory):
    directory.mkdir();manifest=[]
    for role in ('users','events'):
        rows=json.loads((HAND/f'{role}.json').read_text())
        rows=[{**row,'user_id':'new-'+row['user_id']} for row in rows]
        source=write_source(directory,role,rows)
        saved=storage.put_file(storage.new_key('synthetic-new-batch','csv'),source['path'])
        manifest.append({**saved.to_dict(),'role':role,'format':'csv'})
    engine,repo,_=jobdb
    with engine.begin() as c:
        project=repo.create_project(c,'synthetic','Independent synthetic batch')
        dataset=repo.create_dataset(c,project['id'])
        repo.seal_dataset(c,dataset['id'],manifest,MAPPING,EXPORT)
        return repo.create_run(c,dataset['id'],CONFIG,str(uuid4()))


def test_new_config_duplicate_upload_and_independent_population(api,jobdb,tmp_path,monkeypatch):
    client,engine,storage=api;repo=jobdb[1]
    configure_worker(engine,storage,monkeypatch)
    original=create_run(jobdb,storage,tmp_path/'original')
    assert Worker(engine,task_timeout=120).run_once()
    first=client.get(f"/api/runs/{original['id']}/reports/1/json")
    assert first.status_code==200,first.text
    first_policy=first.json()['audit']['validation_policy'];assert first_policy['eligible'] is True
    with engine.begin() as c:
        changed=repo.create_run(c,original['dataset_id'],{**CONFIG,'seed':CONFIG['seed']+1},str(uuid4()))
    assert Worker(engine,task_timeout=120).run_once()
    changed_report=client.get(f"/api/runs/{changed['id']}/reports/1/json").json()
    assert 'DATASET_ALREADY_EXPOSED' in changed_report['audit']['validation_policy']['reasons']
    # The tiny exploration cohort has no priority items. Verify contamination
    # on the persisted full family, not a vacuous loop over an empty projection.
    with engine.connect() as c:
        artifact=c.execute(text("SELECT object_key,sha256,size_bytes FROM artifacts WHERE run_id=:id AND kind='baseline'"),
                           {'id':changed['id']}).mappings().one()
    full=json.loads(storage.get_bytes(ObjectManifest(artifact['object_key'],artifact['sha256'],artifact['size_bytes'],'application/json')))['validation']
    assert full and all(row['evidence_status']=='exploratory' for row in full)
    assert all(row['metrics'] is None or row['metrics']['evidence_status']=='exploratory' for row in full)
    with engine.connect() as c:
        assert c.execute(text('SELECT evidence_status FROM runs WHERE id=:id'),{'id':changed['id']}).scalar_one()=='exploratory'
    with pytest.raises(DBAPIError):
        with engine.begin() as c:c.execute(text("UPDATE runs SET evidence_status='historically_validated' WHERE id=:id"),{'id':changed['id']})
    with pytest.raises(DBAPIError):
        with engine.begin() as c:c.execute(text("UPDATE runs SET split_id='different' WHERE id=:id"),{'id':changed['id']})
    duplicate=create_run(jobdb,storage,tmp_path/'duplicate')
    assert duplicate['dataset_id']!=original['dataset_id']
    assert Worker(engine,task_timeout=120).run_once()
    duplicate_report=client.get(f"/api/runs/{duplicate['id']}/reports/1/json").json()
    assert 'USERS_OVERLAP_EXPOSED_DATA' in duplicate_report['audit']['validation_policy']['reasons']
    assert all(row['evidence_status']=='exploratory' for row in duplicate_report['candidates'])
    independent=new_users_run(jobdb,storage,tmp_path/'independent')
    assert Worker(engine,task_timeout=120).run_once()
    report=client.get(f"/api/runs/{independent['id']}/reports/1/json").json()
    assert report['audit']['validation_policy']['eligible'] is True
    assert report['audit']['validation_policy']['reasons']==[]
    # Eligibility is not statistical success: this hand fixture remains too small.
    assert report['summary']['historically_validated_count']==0
    with engine.connect() as c:
        reservation=c.execute(text('SELECT * FROM validation_reservations WHERE run_id=:id'),{'id':independent['id']}).mappings().one()
        stages=dict(c.execute(text("SELECT stage,created_at FROM stage_checkpoints WHERE run_id=:id AND stage IN ('selection','validation')"),{'id':independent['id']}).all())
        assert stages['selection']<=reservation['reserved_at']<=stages['validation']
        assert reservation['frozen_sha256']==report['audit']['frozen_sha256']
        assert c.execute(text('SELECT count(*) FROM validation_population_members WHERE dataset_id=:id'),{'id':independent['dataset_id']}).scalar_one()==6
    assert client.get(f"/api/runs/{original['id']}/reports/1/json").content==first.content
    for table in ('validation_reservations','validation_population_members','validation_populations'):
        with pytest.raises(DBAPIError):
            with engine.begin() as c:c.execute(text(f'DELETE FROM {table}'))


@pytest.mark.parametrize('exposure_first',[True,False])
def test_freeze_disclosure_order_replay_and_tamper(api,jobdb,tmp_path,monkeypatch,exposure_first):
    _,engine,storage=api;repo=jobdb[1]
    configure_worker(engine,storage,monkeypatch)
    original=create_run(jobdb,storage,tmp_path/'original')
    assert Worker(engine,task_timeout=120).run_once()
    with engine.begin() as c:
        next_run=repo.create_run(c,original['dataset_id'],{**CONFIG,'seed':CONFIG['seed']+3},str(uuid4()))
    queue=JobQueue(engine,lease_seconds=120);lease=queue.claim('ordering-integration')
    assert lease.run_id==next_run['id']
    reserve=pipeline.reserve_validation;observed=[]
    def ordered(*args):
        if exposure_first:record_report_exposure(UploadService(engine,storage),original['id'],1,'report_export')
        result=reserve(*args)
        if not exposure_first:record_report_exposure(UploadService(engine,storage),original['id'],1,'report_export')
        assert reserve(*args)==result  # Retry after disclosure reuses the fixed decision.
        assert result['eligible'] is (not exposure_first)
        altered=tmp_path/'altered-freeze';altered.mkdir()
        contract=json.loads((args[3]/'frozen.json').read_text());contract['rules']['seed']+=1
        path=altered/'frozen.json';path.write_text(json.dumps(contract))
        with pytest.raises(IngestError,match='VALIDATION_RESERVATION_CHANGED'):
            reserve(*args[:3],altered,file_hash(path))
        with pytest.raises(IngestError,match='FROZEN_CONTRACT_CHANGED'):
            reserve(*args[:4],'0'*64)
        observed.append(result)
        return result
    monkeypatch.setattr(pipeline,'reserve_validation',ordered)
    result=pipeline.run_baseline(engine,storage,lease,tmp_path/'work')
    artifact=next(item for item in result['artifacts'] if item['kind']=='validation')
    data=json.loads(storage.get_bytes(ObjectManifest(artifact['object_key'],artifact['sha256'],artifact['size_bytes'],'application/json')))
    assert len(observed)==1 and data['validation_policy']==observed[0]
    if exposure_first:assert all(item['evidence_status']=='exploratory' for item in data['results'])
    queue.cancel(lease.job_id)


@pytest.mark.parametrize('source_available',[True,False])
def test_legacy_population_backfill_or_unknown_denial(api,jobdb,tmp_path,monkeypatch,source_available):
    client,engine,storage=api
    configure_worker(engine,storage,monkeypatch)
    original=create_run(jobdb,storage,tmp_path/'legacy')
    assert Worker(engine,task_timeout=120).run_once()
    before=client.get(f"/api/runs/{original['id']}/reports/1/json")
    assert before.status_code==200
    # Explicit legacy/fault fixture, restricted to this disposable PG database.
    # Remove only PH29 indexes, never source S3 objects or the real report.
    assert engine.url.username=='ac_test' and engine.url.host=='127.0.0.1'
    with engine.begin() as c:
        for table in ('validation_reservations','validation_population_members','validation_populations'):
            c.execute(text(f'ALTER TABLE {table} DISABLE TRIGGER USER'))
            c.execute(text(f'DELETE FROM {table} WHERE dataset_id=:ds'),{'ds':original['dataset_id']})
            c.execute(text(f'ALTER TABLE {table} ENABLE TRIGGER USER'))
        if not source_available:
            # Simulate the older state without cache references before removing
            # checkpoint provenance; FK protection remains enabled otherwise.
            c.execute(text('ALTER TABLE analysis_stage_cache DISABLE TRIGGER USER'))
            c.execute(text('DELETE FROM analysis_stage_cache WHERE source_run_id=:id'),{'id':original['id']})
            c.execute(text('ALTER TABLE analysis_stage_cache ENABLE TRIGGER USER'))
            c.execute(text('ALTER TABLE stage_checkpoints DISABLE TRIGGER USER'))
            c.execute(text("UPDATE stage_checkpoints SET stage='unavailable_legacy_normalized' WHERE run_id=:id AND stage='normalized'"),{'id':original['id']})
            c.execute(text('ALTER TABLE stage_checkpoints ENABLE TRIGGER USER'))
    independent=new_users_run(jobdb,storage,tmp_path/'independent')
    assert Worker(engine,task_timeout=120).run_once()
    response=client.get(f"/api/runs/{independent['id']}/reports/1/json")
    assert response.status_code==200,response.text
    policy=response.json()['audit']['validation_policy']
    assert policy['eligible'] is source_available
    if not source_available:assert 'EXPOSED_POPULATION_UNKNOWN' in policy['reasons']
    with engine.connect() as c:
        count=c.execute(text('SELECT count(*) FROM validation_population_members WHERE dataset_id=:ds'),{'ds':original['dataset_id']}).scalar_one()
        assert count==(6 if source_available else 0)
    assert client.get(f"/api/runs/{original['id']}/reports/1/json").content==before.content


def test_concurrent_disclosure_and_reservation_share_database_lock(api,jobdb,tmp_path,monkeypatch):
    _,engine,storage=api;repo=jobdb[1]
    configure_worker(engine,storage,monkeypatch)
    original=create_run(jobdb,storage,tmp_path/'original')
    assert Worker(engine,task_timeout=120).run_once()
    with engine.begin() as c:
        current=repo.create_run(c,original['dataset_id'],{**CONFIG,'seed':CONFIG['seed']+7},str(uuid4()))
    queue=JobQueue(engine,lease_seconds=120);lease=queue.claim('concurrent-validation')
    reserve=pipeline.reserve_validation;observed=[]
    def race(*args):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            with engine.begin() as blocker:
                blocker.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':POLICY_LOCK})
                reserving=pool.submit(reserve,*args)
                exposing=pool.submit(record_report_exposure,UploadService(engine,storage),original['id'],1,'report_export')
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    blocked=blocker.execute(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid=:key AND NOT granted"),{'key':POLICY_LOCK}).scalar_one()
                    if blocked==2:break
                    time.sleep(.02)
                assert blocked==2,'Both operations must reach the shared PostgreSQL lock'
                assert not reserving.done() and not exposing.done()
            decision=reserving.result(timeout=10);exposing.result(timeout=10)
        with engine.connect() as c:
            reserved=c.execute(text('SELECT reserved_at FROM validation_reservations WHERE run_id=:id'),{'id':current['id']}).scalar_one()
            exposed=c.execute(text('SELECT exposed_at FROM validation_exposures WHERE dataset_id=:id'),{'id':original['dataset_id']}).scalar_one()
        assert decision['eligible']==(reserved<exposed)
        observed.append(decision)
        return decision
    monkeypatch.setattr(pipeline,'reserve_validation',race)
    pipeline.run_baseline(engine,storage,lease,tmp_path/'work')
    assert len(observed)==1
    queue.cancel(lease.job_id)
