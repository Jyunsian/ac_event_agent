"""Public SDK message checkpoints. Model reasoning and provider metadata are excluded."""
from uuid import UUID
from sqlalchemy import text
from fastapi.encoders import jsonable_encoder
from server.agent_queue import AgentQueue
from server.agent_journal import encoded
from server.db import fingerprint
from server.uploads import APIError


def validate_messages(c,turn_id,messages):
    if not isinstance(messages,list) or len(messages)>200:raise APIError('AGENT_STEP_INVALID',422)
    encoded(messages,256000)
    calls={};results=set()
    rows=c.execute(text('''SELECT t.tool_call_id,t.tool_name,t.arguments,r.output FROM agent_tool_calls t
        LEFT JOIN agent_tool_results r USING(turn_id,tool_call_id) WHERE t.turn_id=:id'''),{'id':turn_id}).mappings().all()
    journal={row['tool_call_id']:row for row in rows}
    for message in messages:
        if not isinstance(message,dict) or set(message)!={'role','content'}:raise APIError('AGENT_STEP_INVALID',422)
        role=message['role'];content=message['content']
        if role not in {'assistant','tool'} or not isinstance(content,list):raise APIError('AGENT_STEP_INVALID',422)
        for part in content:
            if not isinstance(part,dict):raise APIError('AGENT_STEP_INVALID',422)
            kind=part.get('type')
            if kind=='text' and role=='assistant':
                if set(part)!={'type','text'} or not isinstance(part['text'],str):raise APIError('AGENT_STEP_INVALID',422)
                continue
            call_id=part.get('toolCallId');row=journal.get(call_id) if isinstance(call_id,str) else None
            if row is None or part.get('toolName')!=row['tool_name']:raise APIError('AGENT_STEP_TOOL_MISMATCH',422)
            if kind=='tool-call' and role=='assistant':
                if set(part)!={'type','toolCallId','toolName','input'} or fingerprint(part['input'])!=fingerprint(row['arguments']) or call_id in calls:
                    raise APIError('AGENT_STEP_TOOL_MISMATCH',422)
                calls[call_id]=True
            elif kind=='tool-result' and role=='tool':
                if set(part)!={'type','toolCallId','toolName','output'} or call_id not in calls or call_id in results:
                    raise APIError('AGENT_STEP_TOOL_MISMATCH',422)
                if row['output'] is None or fingerprint(part['output'])!=fingerprint({'type':'json','value':row['output']}):
                    raise APIError('AGENT_STEP_TOOL_MISMATCH',422)
                results.add(call_id)
            else:raise APIError('AGENT_STEP_INVALID',422)
    if set(calls)!=results:raise APIError('AGENT_STEP_TOOL_MISMATCH',422)


def steps(service,claim,operation,body):
    queue=AgentQueue(service.engine);params={'id':claim['id']}
    with service.engine.begin() as c:
        queue.owned(c,claim)
        session=c.execute(text('SELECT * FROM agent_runtime_sessions WHERE turn_id=:id'),params).mappings().one_or_none()
        if operation=='init':
            config=body.get('config')
            if not isinstance(config,dict) or set(config)!={'model_id','sdk_version','prompt_version','max_steps','timeout_ms'}:
                raise APIError('AGENT_STEP_INVALID',422)
            if any(not isinstance(config[key],str) or not 1<=len(config[key])<=200 for key in ['model_id','sdk_version','prompt_version']):
                raise APIError('AGENT_STEP_INVALID',422)
            if type(config['max_steps']) is not int or not 1<=config['max_steps']<=20 or type(config['timeout_ms']) is not int or not 1<=config['timeout_ms']<=600000:
                raise APIError('AGENT_STEP_INVALID',422)
            digest=fingerprint(config)
            if session:
                if session['config_sha256']!=digest:raise APIError('AGENT_RUNTIME_CONFIG_CHANGED',409)
            else:
                c.execute(text('''INSERT INTO agent_runtime_sessions(turn_id,config,config_sha256,max_steps,deadline)
                    VALUES(:id,CAST(:config AS jsonb),:digest,:max_steps,clock_timestamp()+:ms*interval '1 millisecond')'''),
                    {**params,'config':encoded(config,4096),'digest':digest,'max_steps':config['max_steps'],'ms':config['timeout_ms']})
                session=c.execute(text('SELECT * FROM agent_runtime_sessions WHERE turn_id=:id'),params).mappings().one()
        if session is None:raise APIError('AGENT_RUNTIME_NOT_INITIALIZED',409)
        if operation in {'init','load'}:
            records=c.execute(text('''SELECT s.ordinal,s.request_id,s.fence,r.usage,r.finish_reason
                FROM agent_model_steps s LEFT JOIN agent_step_results r USING(turn_id,ordinal)
                WHERE s.turn_id=:id ORDER BY s.ordinal'''),params).mappings().all()
            checkpoint=c.execute(text('''SELECT ordinal,messages,usage,finish_reason FROM agent_step_results
                WHERE turn_id=:id ORDER BY ordinal DESC LIMIT 1'''),params).mappings().one_or_none()
            result=jsonable_encoder({'config':session['config'],'deadline':session['deadline'],
                'steps':[dict(row) for row in records],'checkpoint':dict(checkpoint) if checkpoint else None})
            encoded(result,256000);return result
        if operation=='start':
            try:request_id=UUID(body.get('request_id'))
            except (ValueError,TypeError,AttributeError):raise APIError('AGENT_STEP_INVALID',422)
            existing=c.execute(text('SELECT * FROM agent_model_steps WHERE turn_id=:id AND request_id=:request'),{**params,'request':request_id}).mappings().one_or_none()
            if existing:
                if existing['fence']!=claim['fence']:raise APIError('AGENT_STEP_ATTEMPT_CHANGED',409)
                return {'ordinal':existing['ordinal']}
            consumed=c.execute(text('SELECT count(*) FROM agent_model_steps WHERE turn_id=:id'),params).scalar_one()
            if consumed>=session['max_steps']:raise APIError('AGENT_STEP_LIMIT',409)
            if c.execute(text('SELECT clock_timestamp()>=:deadline'),{'deadline':session['deadline']}).scalar_one():raise APIError('AGENT_TIMEOUT',409)
            c.execute(text('INSERT INTO agent_model_steps(turn_id,ordinal,request_id,fence) VALUES(:id,:n,:request,:fence)'),
                {**params,'n':consumed+1,'request':request_id,'fence':claim['fence']})
            return {'ordinal':consumed+1}
        if operation!='complete':raise APIError('OPERATION_NOT_ALLOWED',422)
        ordinal=body.get('ordinal')
        if type(ordinal) is not int:raise APIError('AGENT_STEP_INVALID',422)
        step=c.execute(text('SELECT * FROM agent_model_steps WHERE turn_id=:id AND ordinal=:n'),{**params,'n':ordinal}).mappings().one_or_none()
        if step is None or step['fence']!=claim['fence']:raise APIError('AGENT_STEP_ATTEMPT_CHANGED',409)
        messages=body.get('messages');usage=body.get('usage');reason=body.get('finish_reason')
        validate_messages(c,claim['id'],messages)
        if not isinstance(usage,dict) or set(usage)-{'input_tokens','output_tokens','total_tokens'} or any(value is not None and (type(value) is not int or value<0) for value in usage.values()):
            raise APIError('AGENT_STEP_INVALID',422)
        if reason not in {'stop','tool-calls','length','content-filter','error','other'}:raise APIError('AGENT_STEP_INVALID',422)
        snapshot={'messages':messages,'usage':usage,'finish_reason':reason};digest=fingerprint(snapshot)
        existing=c.execute(text('SELECT snapshot_sha256 FROM agent_step_results WHERE turn_id=:id AND ordinal=:n'),{**params,'n':ordinal}).scalar_one_or_none()
        if existing is not None:
            if existing!=digest:raise APIError('AGENT_STEP_CONFLICT',409)
        else:
            c.execute(text('''INSERT INTO agent_step_results(turn_id,ordinal,messages,usage,finish_reason,snapshot_sha256)
                VALUES(:id,:n,CAST(:messages AS jsonb),CAST(:usage AS jsonb),:reason,:digest)'''),
                {**params,'n':ordinal,'messages':encoded(messages,256000),'usage':encoded(usage,1024),'reason':reason,'digest':digest})
        queue.owned(c,claim)
        return {'ordinal':ordinal,'saved':True}
