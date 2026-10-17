"""Fenced, immutable tool intent/result journal; not a model-authored evidence source."""
import json
from sqlalchemy import text
from server.agent_queue import AgentQueue
from server.db import fingerprint
from server.uploads import APIError

TOOLS={'profile_dataset','get_baseline_report','compare_candidates','search_candidates','rerun_analysis',
       'analyze_segment','evaluate_analysis','get_exploration_budget','finalize_candidates',
       'load_app_findings','save_findings'}


def encoded(value,limit):
    try:raw=json.dumps(value,ensure_ascii=False,allow_nan=False)
    except (ValueError,TypeError):raise APIError('AGENT_JOURNAL_INVALID',422)
    if len(raw.encode())>limit:raise APIError('AGENT_CONTEXT_LIMIT',413)
    return raw


def journal(service,claim,operation,body):
    queue=AgentQueue(service.engine)
    with service.engine.begin() as c:
        queue.owned(c,claim)
        if operation=='load':
            rows=c.execute(text('''SELECT t.tool_call_id,t.ordinal,t.tool_name,t.arguments,t.input_sha256,
                r.output,r.output_sha256 FROM agent_tool_calls t LEFT JOIN agent_tool_results r
                USING(turn_id,tool_call_id) WHERE t.turn_id=:id ORDER BY t.ordinal'''),{'id':claim['id']}).mappings().all()
            result={'calls':[dict(row) for row in rows]}
            encoded(result,256000)
            return result
        identity=body.get('tool_call_id')
        if not isinstance(identity,str) or not 1<=len(identity)<=200:raise APIError('AGENT_JOURNAL_INVALID',422)
        params={'id':claim['id'],'call':identity}
        existing=c.execute(text('SELECT * FROM agent_tool_calls WHERE turn_id=:id AND tool_call_id=:call'),params).mappings().one_or_none()
        if operation=='begin':
            name=body.get('tool_name');args=body.get('arguments')
            if name not in TOOLS or not isinstance(args,dict):raise APIError('AGENT_JOURNAL_INVALID',422)
            raw=encoded(args,32768);digest=fingerprint({'tool':name,'arguments':args})
            if existing:
                if existing['input_sha256']!=digest:raise APIError('AGENT_JOURNAL_CONFLICT',409)
            else:
                count=c.execute(text('SELECT count(*) FROM agent_tool_calls WHERE turn_id=:id'),params).scalar_one()
                if count>=100:raise APIError('AGENT_CONTEXT_LIMIT',413)
                c.execute(text('''INSERT INTO agent_tool_calls(turn_id,tool_call_id,ordinal,tool_name,arguments,input_sha256)
                    VALUES(:id,:call,:ordinal,:name,CAST(:args AS jsonb),:digest)'''),
                    {**params,'ordinal':count+1,'name':name,'args':raw,'digest':digest})
            result=c.execute(text('SELECT output FROM agent_tool_results WHERE turn_id=:id AND tool_call_id=:call'),params).scalar_one_or_none()
            return {'tool_call_id':identity,'state':'completed' if result is not None else 'pending','output':result}
        if operation!='complete':raise APIError('OPERATION_NOT_ALLOWED',422)
        if existing is None:raise APIError('AGENT_JOURNAL_CALL_MISSING',409)
        output=body.get('output')
        if not isinstance(output,dict):raise APIError('AGENT_JOURNAL_INVALID',422)
        raw=encoded(output,128*1024);digest=fingerprint(output)
        # Evidence must already have been delivered by the real tool under this exact call.
        references=output.get('references',[])
        if not isinstance(references,list):raise APIError('AGENT_JOURNAL_INVALID',422)
        events=c.execute(text("""SELECT payload FROM conversation_events WHERE turn_id=:id
            AND kind='tool_completed' AND payload->>'tool_call_id'=:call AND payload->>'tool'=:name"""),
            {**params,'name':existing['tool_name']}).scalars().all()
        allowed=[ref for event in events for ref in event.get('references',[])]
        if any(ref not in allowed for ref in references):raise APIError('AGENT_JOURNAL_EVIDENCE_INVALID',422)
        result=c.execute(text('SELECT output_sha256 FROM agent_tool_results WHERE turn_id=:id AND tool_call_id=:call'),params).scalar_one_or_none()
        if result is not None:
            if result!=digest:raise APIError('AGENT_JOURNAL_CONFLICT',409)
        else:
            c.execute(text('''INSERT INTO agent_tool_results(turn_id,tool_call_id,output,output_sha256)
                VALUES(:id,:call,CAST(:output AS jsonb),:digest)'''),{**params,'output':raw,'digest':digest})
        queue.owned(c,claim)
        return {'tool_call_id':identity,'state':'completed','output':output}
