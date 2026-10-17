"""Queue-only fault fixtures: real PostgreSQL, no fake model or ready assertions."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from sqlalchemy import text
from server.agent_queue import AgentQueue, AgentLeaseLost
from server.conversations import cancel_turn, conversation_state, retry_turn, turn_context
from server.uploads import UploadService
from tests.test_jobs import jobdb, submit


def seed(jobdb):
    run=submit(jobdb);cid=uuid4();ids=[uuid4(),uuid4()]
    with jobdb[0].begin() as c:
        c.execute(text('INSERT INTO conversations(id,baseline_run_id) VALUES(:id,:rid)'),{'id':cid,'rid':run['id']})
        for i,identity in enumerate(ids):
            c.execute(text('''INSERT INTO agent_turns(id,conversation_id,ordinal,selected_run_id,report_version)
                              VALUES(:id,:cid,:n,:rid,1)'''),{'id':identity,'cid':cid,'n':i+1,'rid':run['id']})
    return cid,ids,run


def test_fifo_concurrency_reclaim_fencing_and_finish(jobdb):
    cid,ids,run=seed(jobdb);engine=jobdb[0];queue=AgentQueue(engine)
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims=list(pool.map(queue.claim,['a','b','c','d']))
    active=[c for c in claims if c is not None]
    assert len(active)==1 and active[0]['id']==ids[0]
    first=active[0];queue.heartbeat(first)
    assert queue.claim('other') is None
    with engine.begin() as c:
        c.execute(text("UPDATE agent_turns SET lease_until=clock_timestamp()-interval '1 second' WHERE id=:id"),{'id':first['id']})
    recovered=AgentQueue(engine).claim('replacement')
    assert recovered['id']==first['id'] and recovered['fence']==first['fence']+1
    for operation in [lambda:queue.heartbeat(first),lambda:queue.finish(first,'stale reply')]:
        with pytest.raises(AgentLeaseLost):operation()
    queue.finish(recovered,'Synthetic queue test reply, not model-generated')
    next_turn=queue.claim('next');assert next_turn['id']==ids[1]
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM messages')).scalar_one()==1
        assert c.execute(text('SELECT status FROM runs WHERE id=:id'),{'id':run['id']}).scalar_one()=='queued'
        events=c.execute(text('SELECT seq,kind FROM conversation_events ORDER BY seq')).all()
        assert [r.seq for r in events]==list(range(1,len(events)+1))
        assert [r.kind for r in events]==['turn_running','turn_running','message_created','turn_succeeded','turn_running']


def test_expired_attempt_limit_unblocks_next_turn(jobdb):
    _,ids,_=seed(jobdb);engine=jobdb[0];queue=AgentQueue(engine)
    first=queue.claim('one')
    with engine.begin() as c:
        c.execute(text("UPDATE agent_turns SET max_attempts=1,lease_until=clock_timestamp()-interval '1 second' WHERE id=:id"),{'id':first['id']})
    assert queue.claim('two') is None
    assert queue.claim('two')['id']==ids[1]
    with engine.connect() as c:
        assert c.execute(text('SELECT status FROM agent_turns WHERE id=:id'),{'id':ids[0]}).scalar_one()=='failed'


def test_stale_eligibility_never_reclaims_a_current_live_lease(jobdb):
    from sqlalchemy import event
    _,ids,_=seed(jobdb);engine=jobdb[0]
    injected=[]
    def refresh_head(connection,cursor,statement,parameters,context,executemany):
        if 'SELECT *,lease_until>clock_timestamp() AS lease_active' in statement and not injected:
            # Deterministically model an eligibility read becoming stale before
            # the locked head recheck. The actual concurrent case is tested above.
            cursor.execute("UPDATE agent_turns SET status='running',worker_id='existing',fence=1,lease_until=clock_timestamp()+interval '90 seconds' WHERE id=%s",(ids[0],))
            injected.append(True)
    event.listen(engine,'before_cursor_execute',refresh_head)
    try:assert AgentQueue(engine).claim('late-claimant') is None
    finally:event.remove(engine,'before_cursor_execute',refresh_head)
    assert injected
    with engine.connect() as c:
        row=c.execute(text('SELECT worker_id,fence FROM agent_turns WHERE id=:id'),{'id':ids[0]}).one()
        assert row.worker_id=='existing' and row.fence==1
        assert c.execute(text('SELECT count(*) FROM agent_turn_attempts')).scalar_one()==0


def test_truncated_answer_status_is_persisted_without_publishing_text(jobdb):
    cid,ids,_=seed(jobdb);engine=jobdb[0];queue=AgentQueue(engine)
    claim=queue.claim('length-check')
    queue.fail(claim,'AGENT_OUTPUT_LIMIT')
    state=conversation_state(UploadService(engine,None),cid)
    assert state['turns'][0]['status']=='failed'
    assert state['turns'][0]['error']=={'code':'AGENT_OUTPUT_LIMIT'}
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM messages')).scalar_one()==0
    assert queue.claim('next')['id']==ids[1]


def test_finish_rolls_back_event_message_and_cursor_together(jobdb,monkeypatch):
    cid,_,_=seed(jobdb);engine=jobdb[0];queue=AgentQueue(engine);claim=queue.claim('worker')
    original=queue.event
    def fault(c,*args):
        original(c,*args)
        raise RuntimeError('synthetic failure after event insert')
    monkeypatch.setattr(queue,'event',fault)
    with pytest.raises(RuntimeError,match='synthetic failure'):
        queue.finish(claim,'Synthetic reply')
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM messages')).scalar_one()==0
        assert c.execute(text('SELECT count(*) FROM conversation_events')).scalar_one()==1
        assert c.execute(text('SELECT next_seq FROM conversations WHERE id=:id'),{'id':cid}).scalar_one()==2
    monkeypatch.setattr(queue,'event',original)
    queue.finish(claim,'Synthetic recovered reply')


def test_cancel_fences_worker_and_preserves_history(jobdb):
    cid,ids,_=seed(jobdb);engine=jobdb[0];queue=AgentQueue(engine);service=UploadService(engine,None)
    claim=queue.claim('worker')
    first=cancel_turn(service,ids[0],'cancel')
    assert first['status']=='cancelled'
    assert cancel_turn(service,ids[0],'cancel')==first
    with pytest.raises(AgentLeaseLost):queue.finish(claim,'Stale synthetic reply')
    state=conversation_state(service,cid)
    assert [turn['status'] for turn in state['turns']]==['cancelled','queued']
    next_turn=queue.claim('next');assert next_turn['id']==ids[1]
    queue.fail(next_turn,'private error body must not be persisted')
    assert conversation_state(service,cid)['turns'][1]['error']=={'code':'AGENT_WORKER_FAILED'}


def test_retry_goes_to_tail_and_context_excludes_future_questions(jobdb):
    cid,ids,_=seed(jobdb);engine=jobdb[0];service=UploadService(engine,None);queue=AgentQueue(engine)
    with engine.begin() as c:
        for i,tid in enumerate(ids):
            c.execute(text("""INSERT INTO messages(id,conversation_id,turn_id,seq,role,content,context)
                VALUES(:id,:cid,:tid,:seq,'user',:content,'{}')"""),
                {'id':uuid4(),'cid':cid,'tid':tid,'seq':i+1,'content':f'Synthetic question {i+1}'})
        c.execute(text('UPDATE conversations SET next_seq=3 WHERE id=:id'),{'id':cid})
    first=queue.claim('one')
    assert turn_context(service,first)['messages']==[{'role':'user','content':'Synthetic question 1'}]
    queue.fail(first,'AGENT_MODEL_FAILED')
    retried=retry_turn(service,ids[0],'retry')
    assert retry_turn(service,ids[0],'retry')==retried
    assert retry_turn(service,ids[0],'other-key')['turn_id']==retried['turn_id']
    second=queue.claim('two');assert second['id']==ids[1]
    assert turn_context(service,second)['messages']==[{'role':'user','content':'Synthetic question 2'}]
    queue.finish(second,'Synthetic answer 2')
    retry=queue.claim('three');assert str(retry['id'])==retried['turn_id']
    assert [m['content'] for m in turn_context(service,retry)['messages']]==[
        'Synthetic question 2','Synthetic answer 2','Synthetic question 1']
