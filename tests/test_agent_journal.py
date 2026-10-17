"""Real PostgreSQL journal contracts; queue fixtures are not model integration evidence."""
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
import pytest
from server.agent_queue import AgentQueue
from server.conversations import cancel_turn
from server.uploads import UploadService
from tests.test_agent_queue import seed
from tests.test_jobs import jobdb
from tests.test_upload_api import api


def test_fenced_immutable_journal_http_replay(api,jobdb,monkeypatch):
    client,engine,_=api
    seed(jobdb);claim=AgentQueue(engine).claim('journal-worker')
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-journal-token')
    headers={'Authorization':'Bearer synthetic-journal-token'}
    envelope={'turn_id':str(claim['id']),'worker_id':claim['worker_id'],'fence':claim['fence']}
    intent={'tool_call_id':'read-1','tool_name':'get_baseline_report','arguments':{}}
    def call(operation,**body):
        return client.post('/internal/agent/journal/'+operation,headers=headers,json={**envelope,**body})
    assert client.post('/internal/agent/journal/load',json=envelope).status_code==401
    assert call('load').json()=={'calls':[]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:call('begin',**intent),range(2)))
    assert all(r.status_code==200 for r in responses)
    assert responses[0].json()==responses[1].json()
    assert responses[0].json()['state']=='pending'
    assert call('begin',**{**intent,'arguments':{'unexpected':1}}).status_code==409
    assert call('begin',**{**intent,'tool_name':'shell'}).status_code==422
    assert call('begin',**{**intent,'tool_call_id':'large','arguments':{'text':'界'*20000}}).status_code==413
    assert call('complete',tool_call_id='missing',output={}).status_code==409
    assert call('complete',tool_call_id='read-1',output={'references':[{'evidence_id':'invented'}]}).status_code==422
    error={'available':False,'error_code':'TOOL_READ_FAILED'}
    completed=call('complete',tool_call_id='read-1',output=error)
    assert completed.status_code==200
    assert call('complete',tool_call_id='read-1',output=error).json()==completed.json()
    assert call('complete',tool_call_id='read-1',output={'available':True}).status_code==409
    assert call('begin',**intent).json()==completed.json()
    loaded=call('load').json()['calls']
    assert len(loaded)==1 and loaded[0]['ordinal']==1 and loaded[0]['output']==error
    # A synthetic completed-tool event tests exact reference binding, not report generation.
    intent2={**intent,'tool_call_id':'read-2'}
    assert call('begin',**intent2).status_code==200
    ref={'evidence_id':'synthetic-reference-contract'}
    with engine.begin() as c:
        AgentQueue(engine).event(c,claim['conversation_id'],claim['id'],'tool_completed',
            {'tool':'get_baseline_report','tool_call_id':'read-2','references':[ref]})
    assert call('complete',tool_call_id='read-2',output={'references':[ref]}).status_code==200
    assert call('load',fence=claim['fence']+1).status_code==409
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM agent_tool_calls')).scalar_one()==2
        assert c.execute(text('SELECT count(*) FROM agent_tool_results')).scalar_one()==2
    for table in ['agent_tool_calls','agent_tool_results']:
        with pytest.raises(ProgrammingError,match='immutable'),engine.begin() as c:
            c.execute(text(f'DELETE FROM {table} WHERE turn_id=:id'),{'id':claim['id']})
    cancel_turn(UploadService(engine,None),claim['id'],'cancel-journal')
    assert call('load').status_code==409
    assert call('begin',**intent).status_code==409
    assert call('complete',tool_call_id='read-1',output=error).status_code==409
