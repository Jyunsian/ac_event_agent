"""Evidence-backed App observations. Outcomes are claims, never validation grants."""
import json
from datetime import datetime
from uuid import UUID,uuid4
from sqlalchemy import select,tuple_,insert,text
from fastapi.encoders import jsonable_encoder
from server.agent_queue import AgentQueue
from server.artifact_reader import read_report_export
from server.db import fingerprint
from server.uploads import APIError


def _source(service,run_id,version,candidate_id):
    with service.engine.connect() as c:
        run=service.row(c,'runs',run_id)
        dataset=service.row(c,'datasets',run['dataset_id'])
        project=service.row(c,'projects',dataset['project_id'])
        versions,artifacts=service.tables['report_versions'],service.tables['artifacts']
        artifact=c.execute(select(artifacts).join(versions,versions.c.artifact_id==artifacts.c.id)
            .where(versions.c.run_id==run_id,versions.c.version==version)).mappings().one_or_none()
    if not artifact:raise APIError('REPORT_VERSION_NOT_AVAILABLE',404)
    raw,_,sha=read_report_export(service,run_id,version,'json')
    report=json.loads(raw)
    if sha!=artifact['sha256'] or report['run_id']!=str(run_id) or report['dataset_id']!=str(dataset['id']):
        raise APIError('TOOL_REPORT_IDENTITY_MISMATCH')
    if report['summary'].get('segment') is not None:raise APIError('FINDING_SEGMENT_NOT_SUPPORTED',422)
    candidate=next(((i,row) for i,row in enumerate(report['candidates']) if row['candidate_id']==candidate_id),None)
    if candidate is None and report['schema_version']=='2.0':
        from server.candidate_reader import candidate_context, read_candidate_detail
        _,_,catalog,_=candidate_context(service,run_id,version)
        index=next((i for i,item in enumerate(catalog['entries']) if item['candidate_id']==candidate_id),None)
        if index is None:raise APIError('CANDIDATE_NOT_IN_REPORT',422)
        detail=read_candidate_detail(service,run_id,version,candidate_id)['content']
        with service.engine.connect() as c:
            candidates=c.execute(select(artifacts).where(artifacts.c.run_id==run_id,
                artifacts.c.attempt_id==artifact['attempt_id'],artifacts.c.kind=='candidate_catalog',
                artifacts.c.sha256==report['catalog']['sha256'])).mappings().all()
        if len(candidates)!=1:raise APIError('FINDING_EVIDENCE_MISMATCH')
        evidence=candidates[0];pointer=f'/entries/{index}'
        reference={'evidence_id':f'report:{evidence["id"]}#{pointer}','artifact_id':str(evidence['id']),
                   'run_id':str(run_id),'report_version':version,'sha256':evidence['sha256'],'json_pointer':pointer}
        row={'candidate_id':candidate_id,'event_spec':detail['event_spec'],**detail['validation']}
        # Finding persistence remains bound to the report artifact, while its
        # displayed evidence points to the verified complete catalog entry.
        return run,project,artifact,row,reference
    if candidate is None:raise APIError('CANDIDATE_NOT_IN_REPORT',422)
    index,row=candidate
    reference={'evidence_id':f'report:{artifact["id"]}#/candidates/{index}','artifact_id':str(artifact['id']),
               'run_id':str(run_id),'report_version':version,'sha256':sha,'json_pointer':f'/candidates/{index}'}
    return run,project,artifact,row,reference


def _strings(value):
    if not isinstance(value,list) or len(value)>10 or any(not isinstance(x,str) or not x.strip() or len(x)>1000 for x in value):
        raise APIError('TOOL_ARGUMENTS_INVALID',422)
    return sorted(set(value))


def _recheck_history(service,finding):
    """Two most recent published fixed-rule checks, each reverified from immutable bytes."""
    with service.engine.connect() as c:
        rows=c.execute(text('''SELECT r.run_id,v.version,v.artifact_id,a.sha256 FROM finding_rechecks r
            JOIN runs u ON u.id=r.run_id JOIN report_versions v ON v.run_id=r.run_id
            JOIN artifacts a ON a.id=v.artifact_id AND a.run_id=r.run_id
            WHERE r.sources @> CAST(:source AS jsonb) AND u.status='succeeded'
            ORDER BY r.created_at DESC,r.run_id DESC,v.version DESC LIMIT 2'''),
            {'source':json.dumps([{'finding_id':str(finding['id'])}])}).mappings().all()
    history=[];refs=[]
    for row in rows:
        raw,_,sha=read_report_export(service,row['run_id'],row['version'],'json')
        report=json.loads(raw)
        if sha!=row['sha256'] or report['run_id']!=str(row['run_id']):raise APIError('FINDING_EVIDENCE_MISMATCH')
        assessment=next((item for item in (report['summary'].get('finding_recheck') or {}).get('assessments',[])
                         if item['finding_id']==str(finding['id'])),None)
        if assessment is None:raise APIError('FINDING_EVIDENCE_MISMATCH')
        index=next((i for i,item in enumerate(report['candidates']) if item['candidate_id']==finding['candidate_id']),None)
        pointer=f'/candidates/{index}' if index is not None else '/summary'
        ref={'evidence_id':f'report:{row["artifact_id"]}#{pointer}','artifact_id':str(row['artifact_id']),
             'run_id':str(row['run_id']),'report_version':row['version'],'sha256':sha,'json_pointer':pointer}
        from server.validation_exposure import record_report_exposure
        record_report_exposure(service,row['run_id'],row['version'],'agent_tool')
        history.append({**assessment,'run_id':str(row['run_id']),'report_version':row['version'],'evidence_id':ref['evidence_id']})
        refs.append(ref)
    return history,refs


def findings_tool(service,name,envelope):
    args=envelope['arguments'];queue=AgentQueue(service.engine)
    with service.engine.begin() as c:
        turn=service.row(c,'agent_turns',envelope['turn_id'])
        claim={'id':turn['id'],'conversation_id':turn['conversation_id'],'worker_id':envelope['worker_id'],'fence':envelope['fence']}
        turn=dict(queue.owned(c,claim))
        if turn['selected_run_id']!=envelope['parent_run_id']:raise APIError('TOOL_RUN_MISMATCH')
        selected=service.row(c,'runs',turn['selected_run_id'])
        dataset=service.row(c,'datasets',selected['dataset_id'])
        app=service.row(c,'projects',dataset['project_id'])['app_id']
    table=service.tables['app_findings']
    if name=='load_app_findings':
        if set(args)-{'cursor','limit'}:raise APIError('TOOL_ARGUMENTS_INVALID',422)
        limit=args.get('limit',5)
        if type(limit) is not int or not 1<=limit<=10:raise APIError('TOOL_ARGUMENTS_INVALID',422)
        query=select(table).where(table.c.app_id==app)
        if args.get('cursor'):
            try:
                date,identity=args['cursor'].split('|');date=datetime.fromisoformat(date);identity=UUID(identity)
                if date.tzinfo is None:raise ValueError()
            except (ValueError,TypeError,AttributeError):raise APIError('INVALID_FINDING_CURSOR',422)
            query=query.where(tuple_(table.c.created_at,table.c.id)<tuple_(date,identity))
        with service.engine.connect() as c:
            rows=c.execute(query.order_by(table.c.created_at.desc(),table.c.id.desc()).limit(limit+1)).mappings().all()
        items=[];refs=[]
        for row in rows[:limit]:
            _,_,artifact,candidate,reference=_source(service,row['source_run_id'],row['report_version'],row['candidate_id'])
            if artifact['sha256']!=row['report_sha256'] or candidate['event_spec']!=row['event_spec']:
                raise APIError('FINDING_EVIDENCE_MISMATCH')
            from server.validation_exposure import record_report_exposure
            record_report_exposure(service,row['source_run_id'],row['report_version'],'agent_tool')
            history,history_refs=_recheck_history(service,row)
            items.append({**dict(row),'metrics':candidate['metrics'],'evidence_status':candidate['evidence_status'],
                          'requires_new_batch_validation':True,'outcome_is_observation':True,'evidence_id':reference['evidence_id'],
                          'evidence_artifact_id':reference['artifact_id'],'evidence_sha256':reference['sha256'],
                          'recheck_history':history,'recheck_history_limit':2})
            refs.append(reference)
            refs.extend(history_refs)
        last=rows[limit-1] if len(rows)>limit else None
        result={'tool':name,'parent_run_id':str(selected['id']),'app_id':app,'items':items,'references':refs,
                'next_cursor':f"{last['created_at'].isoformat()}|{last['id']}" if last else None}
        with service.engine.begin() as c:
            queue.owned(c,claim)
            _complete(queue,c,turn,envelope,name,result)
        return jsonable_encoder(result)
    if name!='save_findings':raise APIError('TOOL_NOT_ALLOWED',422)
    required={'candidate_id','hypothesis','limitations','counterexamples'}
    if not required<=set(args) or set(args)-required-{'source_run_id','previous_finding_id','outcome'}:
        raise APIError('TOOL_ARGUMENTS_INVALID',422)
    if not isinstance(args['hypothesis'],str) or not args['hypothesis'].strip() or len(args['hypothesis'])>1000:
        raise APIError('TOOL_ARGUMENTS_INVALID',422)
    if not isinstance(args['candidate_id'],str) or not 1<=len(args['candidate_id'])<=256:raise APIError('TOOL_ARGUMENTS_INVALID',422)
    try:
        source=UUID(args.get('source_run_id',str(selected['id'])))
        previous=UUID(args['previous_finding_id']) if args.get('previous_finding_id') else None
    except (ValueError,TypeError,AttributeError):raise APIError('TOOL_ARGUMENTS_INVALID',422)
    outcome=args.get('outcome','observation')
    if outcome not in {'observation','supported','contradicted','inconclusive'} or (outcome=='observation')!=(previous is None):
        raise APIError('TOOL_ARGUMENTS_INVALID',422)
    limitations=_strings(args['limitations']);counterexamples=_strings(args['counterexamples'])
    if not limitations:raise APIError('FINDING_LIMITATIONS_REQUIRED',422)
    version=turn['report_version']
    if source!=selected['id']:
        from server.branches import evaluate_analysis
        evaluated=evaluate_analysis(service,{**envelope,'arguments':{'child_run_id':str(source)}})
        if evaluated['status']!='succeeded':raise APIError('FINDING_REPORT_NOT_READY',409)
        version=evaluated['report_version']
    run,project,artifact,candidate,reference=_source(service,source,version,args['candidate_id'])
    if project['app_id']!=app:raise APIError('FINDING_APP_MISMATCH',422)
    canonical={'source_run_id':str(source),'report_version':version,'candidate_id':args['candidate_id'],
               'hypothesis':args['hypothesis'].strip(),'limitations':limitations,'counterexamples':counterexamples,
               'outcome':outcome,'previous_finding_id':str(previous) if previous else None}
    digest=fingerprint(canonical)
    from server.validation_exposure import record_report_exposure
    record_report_exposure(service,source,version,'agent_tool')
    def action(c):
        queue.owned(c,claim)
        c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,350035))'),
                  {'key':f'{app}:{source}:{version}:{args["candidate_id"]}:{digest}'})
        if previous:
            prior=c.execute(select(table).where(table.c.id==previous,table.c.app_id==app)).mappings().one_or_none()
            if not prior or prior['source_dataset_id']==run['dataset_id'] or prior['event_spec']!=candidate['event_spec']:
                raise APIError('FINDING_RECHECK_MISMATCH',422)
        existing=c.execute(select(table).where(table.c.app_id==app,table.c.source_run_id==source,
            table.c.report_version==version,table.c.candidate_id==args['candidate_id'],table.c.payload_hash==digest)).mappings().one_or_none()
        identity=existing['id'] if existing else uuid4()
        if not existing:
            c.execute(insert(table).values(id=identity,app_id=app,source_run_id=source,source_dataset_id=run['dataset_id'],
                report_version=version,report_artifact_id=artifact['id'],report_sha256=artifact['sha256'],
                candidate_id=args['candidate_id'],event_spec=candidate['event_spec'],hypothesis=canonical['hypothesis'],
                limitations=limitations,counterexamples=counterexamples,outcome=outcome,previous_finding_id=previous,
                source_turn_id=turn['id'],tool_call_id=envelope['tool_call_id'],payload_hash=digest))
        result={'tool':name,'parent_run_id':str(selected['id']),'finding_id':str(identity),'run_id':str(source),
                'report_version':version,'outcome':outcome,'reused':existing is not None,
                'requires_new_batch_validation':True,'references':[reference]}
        _complete(queue,c,turn,envelope,name,result)
        return result
    return service.request(f"findings:{turn['id']}",envelope['tool_call_id'],canonical,action)


def _complete(queue,c,turn,envelope,name,result):
    if len(json.dumps(jsonable_encoder(result),ensure_ascii=False).encode())>128*1024:
        raise APIError('TOOL_PAYLOAD_TOO_LARGE',413)
    queue.event(c,turn['conversation_id'],turn['id'],'tool_completed',{
        'tool':name,'tool_call_id':envelope['tool_call_id'],'fence':envelope['fence'],
        'run_id':result.get('run_id'),'report_version':result.get('report_version'),'references':result['references']})
