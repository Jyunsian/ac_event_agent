import copy
import pytest
from server.checkpoints import CheckpointStore,StageRunner,CheckpointError
from server.validation_batches import ValidationBatches
from server.jobs import JobQueue
from tests.test_jobs import jobdb,submit
from tests.test_upload_api import api


def test_real_pg_s3_batch_readback_and_no_partial_verdict(api,jobdb,tmp_path):
    _,engine,storage=api
    submit(jobdb)
    lease=JobQueue(engine).claim('synthetic-validation-batch')
    runner=StageRunner(CheckpointStore(engine,storage,lease),tmp_path/'first','v2','synthetic',{})
    batches=ValidationBatches(runner,'a'*64,['one','two'])
    assert batches.load(0) is None
    entries=[{'row':{'candidate_id':i,'evidence_status':'exploratory','metrics':None},
              'test':{'testable':False,'p_value':1}} for i in ('one','two')]
    assert batches.save(0,entries)==entries
    fresh=ValidationBatches(StageRunner(CheckpointStore(engine,storage,lease),tmp_path/'fresh','v2','synthetic',{}),
                            'a'*64,['one','two'])
    assert fresh.load(0)==entries
    assert ValidationBatches(runner,'b'*64,['one','two']).load(0) is None
    invalid=copy.deepcopy(entries);invalid[0]['row']['evidence_status']='historically_validated'
    with pytest.raises(CheckpointError,match='PARTIAL_VALIDATION_VERDICT_FORBIDDEN'):batches.save(0,invalid)
    with pytest.raises(CheckpointError,match='VALIDATION_BATCH_MISMATCH'):batches.save(0,entries[:1])
    assert fresh.load(0)==entries


def test_interrupt_after_first_batch_resumes_without_recomputing(api,jobdb,tmp_path,monkeypatch):
    import json
    from sqlalchemy import text
    from tests.test_search import prepare,CONFIG
    from server.analysis.search import generate_candidates
    from server.analysis.freeze import freeze_candidates
    import server.analysis.validation as validation
    _,engine,storage=api
    run=submit(jobdb)
    queue=JobQueue(engine,lease_seconds=120)
    lease=queue.claim('synthetic-batch-interruption')
    data=tmp_path/'data';prepare(data)
    config={**CONFIG,'max_candidates':51}
    search=generate_candidates(data/'exploration/features',data/'targets',config,data/'search')
    receipt=freeze_candidates(data/'search',[],data/'freeze',full_family=True)
    ids=[r['candidate_id'] for r in search['candidates']]
    assert len(ids)==51
    original_summary=validation.summarize_users;calls=[]
    def observed(*args,**kwargs):
        calls.append(1)
        return original_summary(*args,**kwargs)
    monkeypatch.setattr(validation,'summarize_users',observed)
    first=ValidationBatches(StageRunner(CheckpointStore(engine,storage,lease),tmp_path/'work1','v2','synthetic',config),receipt['sha256'],ids)
    original_save=first.save
    def interrupted(index,entries):
        original_save(index,entries)
        raise RuntimeError('SYNTHETIC_AFTER_DURABLE_BATCH')
    monkeypatch.setattr(first,'save',interrupted)
    args=(data/'normalized',data/'features',data/'targets',data/'freeze',receipt['sha256'])
    with pytest.raises(RuntimeError,match='SYNTHETIC_AFTER_DURABLE_BATCH'):
        validation.validate_frozen(*args,tmp_path/'interrupted',batch_store=first)
    calls_after_first=len(calls)
    assert 0<calls_after_first<=50  # Exact membership memo may reuse statistics.
    assert len(first.load(0))==50  # All 50 candidate records really reached S3.
    assert not (tmp_path/'interrupted/manifest.json').exists()
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM report_versions WHERE run_id=:id'),{'id':run['id']}).scalar_one()==0
    queue.fail(lease,'SYNTHETIC_RETRY',retryable=True,retry_delay=0)
    next_lease=queue.claim('synthetic-batch-resumed')
    resumed=ValidationBatches(StageRunner(CheckpointStore(engine,storage,next_lease),tmp_path/'work2','v2','synthetic',config),receipt['sha256'],ids)
    result=validation.validate_frozen(*args,tmp_path/'resumed',batch_store=resumed)
    assert len(calls)==calls_after_first+1  # First 50 read from S3; only last row computed.
    assert result['family_correction_complete'] and result['family_size']==51
    assert all(r['inference']['family_size']==51 for r in result['results'])
    plain=validation.validate_frozen(*args,tmp_path/'plain')
    assert result==plain
