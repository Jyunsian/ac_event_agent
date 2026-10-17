"""Fenced step checkpoints and non-resetting budgets on real PostgreSQL."""
from uuid import uuid4
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
import pytest
from server.agent_queue import AgentQueue
from tests.test_agent_queue import seed
from tests.test_jobs import jobdb
from tests.test_upload_api import api

CONFIG={'model_id':'synthetic-model','sdk_version':'7.0.94','prompt_version':'iaa-v1','max_steps':2,'timeout_ms':120000}


def test_step_budget_checkpoint_and_new_fence(api,jobdb,monkeypatch):
    client,engine,_=api;seed(jobdb);claim=AgentQueue(engine).claim('steps-one')
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-step-token')
    headers={'Authorization':'Bearer synthetic-step-token'}
    envelope={'turn_id':str(claim['id']),'worker_id':claim['worker_id'],'fence':claim['fence']}
    def call(operation,**body):return client.post('/internal/agent/steps/'+operation,headers=headers,json={**envelope,**body})
    assert client.post('/internal/agent/steps/init',json={**envelope,'config':CONFIG}).status_code==401
    assert call('load').status_code==409
    init=call('init',config=CONFIG);assert init.status_code==200,init.text
    assert call('init',config=CONFIG).json()==init.json()
    assert call('init',config={**CONFIG,'model_id':'changed'}).status_code==409
    assert call('init',config={**CONFIG,'max_steps':True}).status_code==422
    identity=str(uuid4());start=call('start',request_id=identity)
    assert start.json()=={'ordinal':1}
    assert call('start',request_id=identity).json()==start.json()
    snapshot={'ordinal':1,'messages':[{'role':'assistant','content':[{'type':'text','text':'合成公開說明'}]}],
              'usage':{'input_tokens':12,'output_tokens':4,'total_tokens':16},'finish_reason':'stop'}
    for message in [
        {'role':'system','content':[]},
        {'role':'assistant','content':[{'type':'reasoning','text':'not stored'}]},
        {'role':'assistant','content':[{'type':'text','text':'public','providerOptions':{}}]},
        {'role':'assistant','content':[{'type':'tool-call','toolCallId':'missing','toolName':'get_baseline_report','input':{}}]},
    ]:assert call('complete',**{**snapshot,'messages':[message]}).status_code==422
    assert call('complete',**{**snapshot,'usage':{'input_tokens':-1}}).status_code==422
    complete=call('complete',**snapshot);assert complete.status_code==200,complete.text
    assert call('complete',**snapshot).json()==complete.json()
    assert call('complete',**{**snapshot,'finish_reason':'length'}).status_code==409
    loaded=call('load').json()
    assert loaded['checkpoint']['messages']==snapshot['messages']
    assert loaded['steps'][0]['usage']==snapshot['usage']
    assert 'messages' not in loaded['steps'][0]
    # Queue contract fixture expires the lease; real process kill is a separate integration gate.
    with engine.begin() as c:c.execute(text("UPDATE agent_turns SET lease_until=clock_timestamp()-interval '1 second' WHERE id=:id"),{'id':claim['id']})
    replacement=AgentQueue(engine).claim('steps-two')
    assert call('load').status_code==409
    envelope.update(worker_id=replacement['worker_id'],fence=replacement['fence'])
    resumed=call('init',config=CONFIG).json()
    assert resumed['deadline']==init.json()['deadline'] and len(resumed['steps'])==1
    assert call('start',request_id=identity).status_code==409
    assert call('complete',**snapshot).status_code==409
    assert call('start',request_id=str(uuid4())).json()=={'ordinal':2}
    # Even an incomplete model request consumes a step; process loss cannot reset the budget.
    limit=call('start',request_id=str(uuid4()))
    assert limit.status_code==409 and limit.json()['error_code']=='AGENT_STEP_LIMIT'
    for table in ['agent_runtime_sessions','agent_model_steps','agent_step_results']:
        with pytest.raises(ProgrammingError,match='immutable'),engine.begin() as c:
            c.execute(text(f'DELETE FROM {table} WHERE turn_id=:id'),{'id':claim['id']})


def test_checkpoint_tool_pair_must_equal_journal_and_deadline(api,jobdb,monkeypatch):
    from server.agent_journal import journal
    from server.uploads import UploadService
    client,engine,_=api;seed(jobdb);claim=AgentQueue(engine).claim('steps-tool')
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-step-token')
    headers={'Authorization':'Bearer synthetic-step-token'}
    envelope={'turn_id':str(claim['id']),'worker_id':claim['worker_id'],'fence':claim['fence']}
    def call(operation,**body):return client.post('/internal/agent/steps/'+operation,headers=headers,json={**envelope,**body})
    assert call('init',config=CONFIG).status_code==200
    assert call('start',request_id=str(uuid4())).status_code==200
    service=UploadService(engine,None)
    intent={'tool_call_id':'read','tool_name':'get_baseline_report','arguments':{}}
    journal(service,claim,'begin',intent)
    output={'available':False,'error_code':'synthetic-unit-contract'}
    journal(service,claim,'complete',{'tool_call_id':'read','output':output})
    first={'role':'assistant','content':[{'type':'tool-call','toolCallId':'read','toolName':'get_baseline_report','input':{}}]}
    second={'role':'tool','content':[{'type':'tool-result','toolCallId':'read','toolName':'get_baseline_report','output':{'type':'json','value':output}}]}
    snapshot={'ordinal':1,'messages':[first,second],'usage':{},'finish_reason':'tool-calls'}
    for messages in [[first],[second,first],[first,second,second]]:
        assert call('complete',**{**snapshot,'messages':messages}).status_code==422
    import copy
    forged=copy.deepcopy(second);forged['content'][0]['output']['value']['available']=0
    assert call('complete',**{**snapshot,'messages':[first,forged]}).status_code==422
    assert call('complete',**snapshot).status_code==200
    # Use the second queued turn for a naturally elapsed short runtime deadline.
    AgentQueue(engine).finish(claim,'Synthetic queue fixture only')
    next_claim=AgentQueue(engine).claim('deadline')
    envelope.update(turn_id=str(next_claim['id']),worker_id=next_claim['worker_id'],fence=next_claim['fence'])
    short=call('init',config={**CONFIG,'timeout_ms':1})
    assert short.status_code==200
    import time
    time.sleep(.01)
    timeout=call('start',request_id=str(uuid4()))
    assert timeout.status_code==409 and timeout.json()['error_code']=='AGENT_TIMEOUT'
