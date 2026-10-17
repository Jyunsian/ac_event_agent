"""Turn-scoped aggregate tools; no user logs, SQL or arbitrary artifact paths."""
import json
from sqlalchemy import select
from server.agent_queue import AgentQueue, AgentLeaseLost
from server.artifact_reader import read_report_export
from server.uploads import APIError
from server.analysis.report_language import event_name

TOOLS={'profile_dataset','get_baseline_report','compare_candidates','search_candidates'}


def read_tool(service, name, envelope):
    if name not in TOOLS:raise APIError('TOOL_NOT_ALLOWED',422)
    queue=AgentQueue(service.engine)
    with service.engine.connect() as c:turn=service.row(c,'agent_turns',envelope['turn_id'])
    claim={'id':turn['id'],'conversation_id':turn['conversation_id'],'worker_id':envelope['worker_id'],'fence':envelope['fence']}
    with service.engine.begin() as c:
        owned=queue.owned(c,claim)
        if owned['selected_run_id']!=envelope['parent_run_id']:raise APIError('TOOL_RUN_MISMATCH')
        queue.event(c,turn['conversation_id'],turn['id'],'tool_running',{'tool':name,'tool_call_id':envelope['tool_call_id'],'fence':envelope['fence']})
    try:
        result=_read_tool(service,name,envelope)
        from server.validation_exposure import record_report_exposure
        record_report_exposure(service,turn['selected_run_id'],turn['report_version'],'agent_tool')
    except Exception:
        try:
            with service.engine.begin() as c:
                queue.owned(c,claim)
                queue.event(c,turn['conversation_id'],turn['id'],'tool_failed',{'tool':name,'tool_call_id':envelope['tool_call_id'],'fence':envelope['fence']})
        except AgentLeaseLost:pass
        raise
    with service.engine.begin() as c:
        queue.owned(c,claim)
        queue.event(c,turn['conversation_id'],turn['id'],'tool_completed',{'tool':name,'tool_call_id':envelope['tool_call_id'],'fence':envelope['fence'],'references':result['references']})
    return result


def _read_tool(service, name, envelope):
    if name not in TOOLS:
        raise APIError('TOOL_NOT_ALLOWED',422)
    args=envelope['arguments']
    allowed=({'candidate_ids','window_hours'} if name=='compare_candidates' else
             {'page','window_hours','family','ad_format','evidence_status','role','sort','descending'}
             if name=='search_candidates' else {'window_hours'} if name=='get_baseline_report' else set())
    if set(args)-allowed:
        raise APIError('TOOL_ARGUMENTS_INVALID',422)
    if name in ('compare_candidates','get_baseline_report') and (type(args.get('window_hours',24)) is not int or args.get('window_hours',24) not in (24,48,72,96,120,144)):
        raise APIError('TOOL_ARGUMENTS_INVALID',422)
    ids=args.get('candidate_ids')
    if name=='compare_candidates' and (not isinstance(ids,list) or not 1<=len(ids)<=10
            or any(not isinstance(i,str) or not 1<=len(i)<=256 for i in ids) or len(set(ids))!=len(ids)):
        raise APIError('TOOL_ARGUMENTS_INVALID',422)
    queue=AgentQueue(service.engine)
    with service.engine.connect() as c:
        turn=service.row(c,'agent_turns',envelope['turn_id'])
    claim={'id':turn['id'],'conversation_id':turn['conversation_id'],
           'worker_id':envelope['worker_id'],'fence':envelope['fence']}
    try:
        with service.engine.begin() as c:
            turn=dict(queue.owned(c,claim))
    except AgentLeaseLost as error:
        raise APIError('AGENT_LEASE_LOST') from error
    run_id=turn['selected_run_id']
    if envelope['parent_run_id']!=run_id:
        raise APIError('TOOL_RUN_MISMATCH')
    with service.engine.connect() as c:
        run=service.row(c,'runs',run_id)
        conversation=service.row(c,'conversations',turn['conversation_id'])
        if run['root_run_id']!=conversation['baseline_run_id']:
            raise APIError('TOOL_RUN_MISMATCH')
        versions,artifacts=service.tables['report_versions'],service.tables['artifacts']
        artifact=c.execute(select(artifacts).join(versions,versions.c.artifact_id==artifacts.c.id)
            .where(versions.c.run_id==run_id,versions.c.version==turn['report_version'])).mappings().one()
    raw,_,sha=read_report_export(service,run_id,turn['report_version'],'json')
    report=json.loads(raw)
    if report.get('run_id')!=str(run_id) or report.get('dataset_id')!=str(run['dataset_id']) or sha!=artifact['sha256']:
        raise APIError('TOOL_REPORT_IDENTITY_MISMATCH')
    references=[]
    def ref(pointer):
        identity=f'report:{artifact["id"]}#{pointer}'
        references.append({'evidence_id':identity,'artifact_id':str(artifact['id']),'run_id':str(run_id),
                           'sha256':sha,'json_pointer':pointer})
        return identity
    if name=='profile_dataset':
        summary=report['summary'];profile=summary.get('data_profile') or {};targets=summary.get('targets') or {}
        content={'users':profile.get('users'),'events':profile.get('events'),'complete_through':profile.get('complete_through'),
                 'quality':summary['quality'],'mature_users':targets.get('mature_users'),
                 'immature_users':targets.get('immature_users'),'evidence_id':ref('/summary')}
        # Bounded aggregate categories only. Tiny cells withheld, not labelled zero.
        content['distributions']={k:[row for row in rows if row.get('users',0)>=20][:10]
            for k,rows in profile.get('distributions',{}).items() if k in {'country','platform','acquisition_source'}}
        content['distribution_policy']='Only cells >=20 users, first 10 per dimension; omitted cells are not zero.'
    elif name=='search_candidates' or (name=='compare_candidates' and report['schema_version'] in ('2.0','3.0','4.0')):
        from server.candidate_reader import candidate_context, read_candidate_page, read_candidate_detail
        _, _, catalog, _ = candidate_context(service, run_id, turn['report_version'])
        with service.engine.connect() as c:
            catalog_artifacts = c.execute(select(artifacts).where(artifacts.c.run_id==run_id,
                artifacts.c.attempt_id==artifact['attempt_id'], artifacts.c.kind=='candidate_catalog',
                artifacts.c.sha256==report['catalog']['sha256'])).mappings().all()
        if len(catalog_artifacts)!=1:raise APIError('TOOL_CATALOG_IDENTITY_MISMATCH')
        catalog_artifact=catalog_artifacts[0]
        positions={row['candidate_id']:i for i,row in enumerate(catalog['entries'])}
        def catalog_ref(identity):
            pointer=f'/entries/{positions[identity]}'
            evidence=f'report:{catalog_artifact["id"]}#{pointer}'
            references.append({'evidence_id':evidence,'artifact_id':str(catalog_artifact['id']),
                'run_id':str(run_id),'sha256':catalog_artifact['sha256'],'json_pointer':pointer})
            return evidence
        if name=='search_candidates':
            page=read_candidate_page(service,run_id,turn['report_version'],**args)
            content={**page,'items':[{**row,'display_name':event_name(row['summary']['event_spec'])
                if row.get('summary') else '此版本未計算',
                'evidence_id':catalog_ref(row['candidate_id'])} for row in page['items']]}
        else:
            if not set(ids)<=set(positions):raise APIError('CANDIDATE_NOT_IN_REPORT',422)
            rows=[]
            for identity in ids:
                detail=read_candidate_detail(service,run_id,turn['report_version'],identity)['content']
                rows.append({'candidate_id':identity,'event_spec':detail['event_spec'],
                    'display_name':event_name(detail['event_spec']),
                    **{k:detail['validation'][k] for k in ('metrics','evidence_status','reasons')},
                    'selection':detail['selection'],**({'time_analysis':catalog['entries'][positions[identity]]['summary']['time_evidence']} if report['schema_version']=='4.0' else {}),'evidence_id':catalog_ref(identity)})
            content={'candidates':rows,'overlap':None,
                'overlap_note':'完整清單的任意配對重疊未預先計算，不以零代替未知。',
                'limitations':report['limitations']}
        content['report_evidence_id']=ref('/summary')
        content['interpretation']='全來源合併的離線歷史比較，不證明投放提升。優先名單已在探索集固定；篩選不重新選擇或驗證。'
    else:
        candidates=report['candidates'];known={row['candidate_id'] for row in candidates}
        if ids is not None and not set(ids)<=known:
            raise APIError('CANDIDATE_NOT_IN_REPORT',422)
        selected=[(i,row) for i,row in enumerate(candidates) if ids is None or row['candidate_id'] in ids]
        content={'analysis_status':report['analysis_status'],'candidates':[
            {**{k:row[k] for k in ('candidate_id','metrics','event_spec','evidence_status','reasons')},
             **({'time_analysis':__import__('server.analysis.v4_metrics',fromlist=['compact_evidence']).compact_evidence(row['time_analysis'])} if report['schema_version']=='4.0' else {}),
             'display_name': event_name(row['event_spec']),
             'evidence_id':ref(f'/candidates/{i}')} for i,row in selected],
             'limitations':report['limitations']}
        content['interpretation']={
            'candidate_metrics_scope':'Each candidate metrics.groups.all.users is its comparison denominator, not the source dataset user count. Zero triggered users applies only to that comparison group. It does not prove zero in exploration or in all source users.',
            'condition_names':'display_name preserves all AND/OR clauses. Do not shorten it by removing conditions.',
            'sample_guidance':'Do not invent daily acquisition targets. Report configured checks as checks, not guarantees of statistical power or campaign performance.',
            'configured_validation_rules':report.get('audit',{}).get('validation_rules'),
        }
        content['report_evidence_id']=ref('/summary')
        if report['summary'].get('segment') is not None:
            content['segment']=report['summary']['segment']
        if name=='compare_candidates':
            overlap=report['diagnostics'].get('overlap')
            content['overlap']=None if not overlap else {k:overlap[k] for k in ('split','cohort_users','evidence_status')}
            if overlap:
                content['overlap']['pairs']=[p for p in overlap['pairs'] if p['a'] in ids and p['b'] in ids]
                content['overlap']['evidence_id']=ref('/diagnostics/overlap')
    if report['schema_version']=='4.0':
        for row in content.get('candidates',[]):
            if row.get('metrics'):row['metrics']={k:v for k,v in row['metrics'].items() if k!='time_comparisons'}
            if row.get('time_analysis'):
                # Bounded three-cohort evidence at one explicitly labelled clock.
                h=args.get('window_hours',24);a=row['time_analysis']
                row['time_analysis']={**a,'display_checkpoint_hours':h,'available_hours':[24,48,72,96,120,144],
                    **{scope:[p for p in a.get(scope,[]) if p['hours']==h] for scope in ('observation','exploration','holdout')},
                    'controls':{k:v for k,v in a.get('controls',{}).items() if k==str(h)},
                    'inference':[t for t in a.get('inference',[]) if t['hours']==h]}
                if a.get('cumulative_comparison'):
                    row['time_analysis']['cumulative_comparison']={scope:[p for p in points if p['hours']==h] for scope,points in a['cumulative_comparison'].items()}
                # Legacy metrics are explicitly 24h; omit rather than mix clocks.
                if h!=24:row.pop('metrics',None)
        for row in content.get('items',[]):
            row['summary']={k:v for k,v in row['summary'].items() if k not in ('time_comparisons','time_evidence','decision','time_scopes','time_controls')}
    result={'tool':name,'run_id':str(run_id),'dataset_id':str(run['dataset_id']),'report_version':turn['report_version'],
            'synthetic':report['synthetic'],'content':content,'references':references}
    if len(json.dumps(result,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode())>128*1024:
        raise APIError('TOOL_PAYLOAD_TOO_LARGE',413)
    try:
        with service.engine.begin() as c:queue.owned(c,claim)
    except AgentLeaseLost as error:
        raise APIError('AGENT_LEASE_LOST') from error
    return result
