from copy import deepcopy
from server.stage_cache import stage_identity
from server.db import fingerprint
import json
import pytest
from sqlalchemy import text
from server.stage_cache import StageCache
from server.checkpoints import CheckpointStore,StageRunner
from server.jobs import JobQueue
from server.storage import StorageError
from tests.test_jobs import jobdb,submit
from tests.test_upload_api import api


def test_cache_input_boundaries_are_exact_and_stage_specific():
    dataset={'fingerprint':'a'*64,'mapping':{'users':{'id':'user_id'}},'export_metadata':{'complete_through':'2026-01-31'}}
    config={'seed':7,'exploration_fraction':.7,'windows_hours':[1,3,24]}
    upstream={'normalized':{'files':[{'path':'events.parquet','object':{'sha256':'b'*64,'object_key':'private-source'}}]}}
    key=lambda ds=dataset,cfg=config,version='v1',refs=upstream: fingerprint(stage_identity('features',ds,cfg,version,refs))
    original=key()
    for field,value in [('mapping',{'users':{'id':'different'}}),('fingerprint','c'*64),('export_metadata',{'complete_through':'2026-02-01'})]:
        assert key(ds={**dataset,field:value})!=original
    for field,value in [('seed',8),('exploration_fraction',.6),('windows_hours',[3])]:
        assert key(cfg={**config,field:value})!=original
    assert key(version='v2')!=original
    changed=deepcopy(upstream);changed['normalized']['files'][0]['object']['sha256']='d'*64
    assert key(refs=changed)!=original
    moved=deepcopy(upstream);moved['normalized']['files'][0]['object']['object_key']='new-private-location'
    assert key(refs=moved)==original  # Physical object relocation is not a data change.
    assert stage_identity('validation',dataset,config,'v1',upstream) is None
    assert stage_identity('normalized',dataset,config,'v1',{})==stage_identity('normalized',dataset,{**config,'windows_hours':[3]},'v1',{})


def test_real_cache_restore_verifies_storage_and_never_publishes_corruption(api,jobdb,tmp_path):
    # Small explicit cache-contract fixture, not a substitute for test_branches'
    # complete normalized-data/Worker integration.
    _,engine,storage=api;queue=JobQueue(engine)
    dataset={'fingerprint':'a'*64,'mapping':{},'export_metadata':{}}
    config={'seed':7,'exploration_fraction':.7,'windows_hours':[3]}
    def cache_for(name):
        run=submit(jobdb);lease=queue.claim(name)
        runner=StageRunner(CheckpointStore(engine,storage,lease),tmp_path/name,'v1',dataset['fingerprint'],config)
        return run,lease,StageCache(engine,runner,dataset,config,'v1',True)
    first,lease,cache=cache_for('first')
    def build(path):
        path.mkdir();(path/'manifest.json').write_text(json.dumps({'synthetic':True,'value':42}))
    _,manifest,mode=cache.run('normalized',build,{},{});assert mode=='computed'
    queue.finish(lease)
    _,lease,cache=cache_for('second')
    def forbidden(path):raise AssertionError('Exact cache hit must not execute the builder')
    restored,_,mode=cache.run('normalized',forbidden,{},{});assert mode=='cached'
    assert json.loads((restored/'manifest.json').read_text())=={'synthetic':True,'value':42}
    assert cache.audit[0]['source_run_id']==str(first['id'])
    queue.finish(lease)
    # Fault inject only this test-created object in isolated MinIO.
    key=manifest['files'][0]['object']['object_key']
    storage.client.put_object(Bucket=storage.bucket,Key=key,Body=b'synthetic corruption')
    broken,lease,cache=cache_for('broken')
    with pytest.raises(StorageError,match='CHECKSUM_MISMATCH|SIZE_MISMATCH'):
        cache.run('normalized',forbidden,{},{})
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM stage_checkpoints WHERE run_id=:id'),{'id':broken['id']}).scalar_one()==0
    queue.cancel(lease.job_id)
