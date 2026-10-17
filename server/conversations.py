"""Ordered durable input queue. No model output is fabricated here."""
import json
from uuid import uuid4
from sqlalchemy import insert, select, update
from server.artifact_reader import read_report_export
from server.run_views import run_view
from server.uploads import APIError


def cancel_turn(service, turn_id, key):
    from server.agent_queue import AgentQueue
    from sqlalchemy import text
    def action(c):
        turn=service.row(c,'agent_turns',turn_id)
        service.row(c,'conversations',turn['conversation_id'],True)
        turn=service.row(c,'agent_turns',turn_id,True)
        if turn['status'] not in ('queued','running'):
            return {'turn_id':turn_id,'status':turn['status']}
        from server.jobs import JobQueue
        child_jobs=c.execute(text('''SELECT j.id FROM jobs j JOIN analysis_branches b ON b.run_id=j.run_id
            WHERE b.source_turn_id=:id ORDER BY j.id'''),{'id':turn_id}).scalars().all()
        for job_id in child_jobs:JobQueue(service.engine).cancel_in_transaction(c,job_id)
        c.execute(text("UPDATE agent_turns SET status='cancelled',fence=fence+1,worker_id=NULL,lease_until=NULL WHERE id=:id"),{'id':turn_id})
        if turn['status']=='running':
            c.execute(text("UPDATE agent_turn_attempts SET finished_at=clock_timestamp(),outcome='cancelled' WHERE turn_id=:id AND fence=:f"),{'id':turn_id,'f':turn['fence']})
        AgentQueue(service.engine).event(c,turn['conversation_id'],turn_id,'turn_cancelled',{})
        return {'turn_id':turn_id,'status':'cancelled'}
    return service.request(f'cancel-turn:{turn_id}',key,{},action)


def conversation_state(service, conversation_id):
    with service.engine.connect() as c:
        conversation=service.row(c,'conversations',conversation_id)
        turns=service.tables['agent_turns']
        rows=c.execute(select(turns.c.id,turns.c.ordinal,turns.c.status,turns.c.error,
            turns.c.selected_run_id,turns.c.selected_candidate_id,turns.c.report_version)
            .where(turns.c.conversation_id==conversation_id).order_by(turns.c.ordinal.desc()).limit(100)).mappings().all()
        return {'id':conversation_id,'baseline_run_id':conversation['baseline_run_id'],
                'turns':[dict(row) for row in reversed(rows)],'turn_limit':100}


def retry_turn(service, turn_id, key):
    from server.agent_queue import AgentQueue
    def action(c):
        old=service.row(c,'agent_turns',turn_id)
        conversation=service.row(c,'conversations',old['conversation_id'],True)
        old=service.row(c,'agent_turns',turn_id,True)
        if old['status'] not in ('failed','cancelled'):
            raise APIError('TURN_NOT_RETRYABLE')
        turns,messages=service.tables['agent_turns'],service.tables['messages']
        existing=c.execute(select(turns).where(turns.c.retry_of_turn_id==turn_id)).mappings().one_or_none()
        if existing:
            return {'turn_id':existing['id'],'status':existing['status'],'retry_of_turn_id':turn_id}
        original=c.execute(select(messages).where(messages.c.turn_id==turn_id,messages.c.role=='user')).mappings().one()
        identity=uuid4();message_id=uuid4();seq=conversation['next_seq']
        c.execute(insert(turns).values(id=identity,conversation_id=old['conversation_id'],ordinal=seq,
            selected_run_id=old['selected_run_id'],selected_candidate_id=old['selected_candidate_id'],
            report_version=old['report_version'],retry_of_turn_id=turn_id))
        context={**original['context'],'retry_of_turn_id':str(turn_id)}
        c.execute(insert(messages).values(id=message_id,conversation_id=old['conversation_id'],turn_id=identity,
            seq=seq,role='user',content=original['content'],context=context))
        AgentQueue(service.engine).event(c,old['conversation_id'],identity,'message_created',
            {'message_id':str(message_id),'role':'user','content':original['content'],'context':context})
        return {'turn_id':identity,'status':'queued','retry_of_turn_id':turn_id}
    return service.request(f'retry-turn:{turn_id}',key,{},action)


def turn_context(service, claim):
    from server.agent_queue import AgentQueue
    from sqlalchemy import and_, or_
    with service.engine.begin() as c:
        current=AgentQueue(service.engine).owned(c,claim)
        turns,messages=service.tables['agent_turns'],service.tables['messages']
        rows=c.execute(select(messages.c.role,messages.c.content,messages.c.context)
            .join(turns,turns.c.id==messages.c.turn_id)
            .where(turns.c.conversation_id==current['conversation_id'],or_(turns.c.id==current['id'],
                and_(turns.c.status=='succeeded',turns.c.ordinal<current['ordinal'])))
            .order_by(turns.c.ordinal,messages.c.seq).limit(101)).mappings().all()
        result=[{'role':row['role'],'content':row['content']} for row in rows]
        if len(rows)>100 or len(json.dumps(result,ensure_ascii=False).encode())>256000:
            raise APIError('AGENT_CONTEXT_LIMIT',413)
        return {'messages':result,'selected_run_id':current['selected_run_id'],
                'selected_candidate_id':current['selected_candidate_id'],'report_version':current['report_version'],
                'report_view':next((row['context'].get('report_view') for row in reversed(rows) if row['role']=='user'),None)}


def ready_report(service, run_id, version=None):
    view = run_view(service, run_id, version)
    if not view['ready']:
        raise APIError('RUN_NOT_READY')
    content, _, _ = read_report_export(service, run_id, view['report_version'], 'json')
    report = json.loads(content)
    if report['run_id'] != str(run_id) or report['dataset_id'] != str(view['dataset_id']):
        raise APIError('REPORT_IDENTITY_MISMATCH')
    return view, report


def create_conversation(service, run_id, key):
    def action(c):
        view, _ = ready_report(service, run_id)
        if view['kind'] != 'baseline':
            raise APIError('BASELINE_REQUIRED')
        table = service.tables['conversations']
        return dict(c.execute(insert(table).values(id=uuid4(), baseline_run_id=run_id).returning(table)).mappings().one())
    return service.request(f'conversations:{run_id}', key, {}, action)


def resolve_reference(service,run_id,artifact_id,version,pointer):
    import re
    catalog_pointer=bool(re.fullmatch(r'/entries/\d+',pointer))
    if pointer not in ('/summary','/diagnostics/overlap') and not re.fullmatch(r'/candidates/\d+',pointer) and not catalog_pointer:
        raise APIError('REFERENCE_INVALID',422)
    with service.engine.connect() as c:
        run=service.row(c,'runs',run_id)
        table=service.tables['report_versions']
        query=select(table).where(table.c.run_id==run_id,table.c.version==version)
        if not catalog_pointer:query=query.where(table.c.artifact_id==artifact_id)
        row=c.execute(query).mappings().one_or_none()
        if row is None:raise APIError('REFERENCE_NOT_FOUND',404)
        if catalog_pointer:
            artifacts=service.tables['artifacts']
            model=c.execute(select(artifacts).where(artifacts.c.id==row['artifact_id'])).mappings().one()
            catalog_artifact=c.execute(select(artifacts).where(artifacts.c.id==artifact_id,
                artifacts.c.run_id==run_id,artifacts.c.attempt_id==model['attempt_id'],
                artifacts.c.kind=='candidate_catalog')).mappings().one_or_none()
            if catalog_artifact is None:raise APIError('REFERENCE_NOT_FOUND',404)
    raw,_,_=read_report_export(service,run_id,version,'json');report=json.loads(raw)
    candidate=None
    if catalog_pointer:
        from server.candidate_reader import candidate_context, read_candidate_detail
        _, _, catalog, _ = candidate_context(service,run_id,version)
        if catalog_artifact['sha256']!=report['catalog']['sha256']:raise APIError('REFERENCE_NOT_FOUND',404)
        index=int(pointer.rsplit('/',1)[1])
        if index>=len(catalog['entries']):raise APIError('REFERENCE_NOT_FOUND',404)
        candidate=catalog['entries'][index]['candidate_id']
        read_candidate_detail(service,run_id,version,candidate)
    if pointer.startswith('/candidates/'):
        index=int(pointer.rsplit('/',1)[1])
        if index>=len(report['candidates']):raise APIError('REFERENCE_NOT_FOUND',404)
        candidate=report['candidates'][index]['candidate_id']
    return {'run_id':run_id,'root_run_id':run['root_run_id'],'artifact_id':artifact_id,'report_version':version,'candidate_id':candidate,
            'tab':'候選事件' if candidate else '圖表' if pointer=='/diagnostics/overlap' else '概覽'}


def send_message(service, conversation_id, key, payload):
    def action(c):
        conversation = service.row(c, 'conversations', conversation_id, True)
        selected_id = payload['selected_run_id']
        run = service.row(c, 'runs', selected_id)
        if run['root_run_id'] != conversation['baseline_run_id']:
            raise APIError('CONVERSATION_RUN_MISMATCH')
        view, report = ready_report(service, selected_id, payload.get('report_version'))
        candidate_id = payload.get('selected_candidate_id')
        if candidate_id and candidate_id not in {row['candidate_id'] for row in report['candidates']}:
            if report['schema_version'] not in ('2.0','3.0','4.0'):raise APIError('CANDIDATE_NOT_IN_REPORT', 422)
            from server.candidate_reader import read_candidate_detail
            read_candidate_detail(service,selected_id,view['report_version'],candidate_id)
        seq = conversation['next_seq']
        turn_id, message_id = uuid4(), uuid4()
        turns, messages, events, conversations = [service.tables[name] for name in
            ('agent_turns', 'messages', 'conversation_events', 'conversations')]
        context = {'selected_run_id': str(selected_id), 'selected_candidate_id': candidate_id,
                   'report_version': view['report_version']}
        if payload.get('report_view') is not None:
            from server.api.schemas import ReportView
            context['report_view']=ReportView.model_validate(payload['report_view']).model_dump()
        c.execute(insert(turns).values(id=turn_id, conversation_id=conversation_id, ordinal=seq,
            selected_run_id=selected_id, selected_candidate_id=candidate_id, report_version=view['report_version']))
        c.execute(insert(messages).values(id=message_id, conversation_id=conversation_id, turn_id=turn_id,
            seq=seq, role='user', content=payload['content'], context=context))
        c.execute(insert(events).values(conversation_id=conversation_id, seq=seq, turn_id=turn_id,
            kind='message_created', payload={'message_id': str(message_id), 'role': 'user',
                                           'content': payload['content'], 'context': context}))
        c.execute(update(conversations).where(conversations.c.id == conversation_id).values(next_seq=seq+1))
        return {'conversation_id': conversation_id, 'turn_id': turn_id, 'message_id': message_id,
                'seq': seq, 'status': 'queued', 'context': context}
    return service.request(f'messages:{conversation_id}', key, payload, action)


def read_events(service, conversation_id, after=0, limit=100):
    with service.engine.connect() as c:
        conversation = service.row(c, 'conversations', conversation_id)
        table = service.tables['conversation_events']
        rows = c.execute(select(table).where(table.c.conversation_id == conversation_id,
            table.c.seq > after).order_by(table.c.seq).limit(limit+1)).mappings().all()
        items = [dict(row) for row in rows[:limit]]
        return {'conversation_id': conversation_id, 'baseline_run_id': conversation['baseline_run_id'],
                'events': items, 'next_after': items[-1]['seq'] if items else after,
                'has_more': len(rows) > limit}
