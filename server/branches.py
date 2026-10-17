"""Turn-scoped branch creation. Models cannot select another dataset or split."""
import json
import math
from sqlalchemy import insert,select,text
from server.agent_queue import AgentQueue,AgentLeaseLost
from server.conversations import ready_report
from server.db import fingerprint,IdempotencyConflict
from server.pipeline import pipeline_version
from server.uploads import APIError


def compute_tool(service,name,envelope):
    """Persist bounded cards once per fence/call, including across polling."""
    queue=AgentQueue(service.engine)
    with service.engine.connect() as c:turn=service.row(c,'agent_turns',envelope['turn_id'])
    claim={'id':turn['id'],'conversation_id':turn['conversation_id'],'worker_id':envelope['worker_id'],'fence':envelope['fence']}
    def event_once(kind,extra=None):
        with service.engine.begin() as c:
            owned=queue.owned(c,claim)
            if owned['selected_run_id']!=envelope['parent_run_id']:raise APIError('TOOL_RUN_MISMATCH')
            exists=c.execute(text('''SELECT 1 FROM conversation_events WHERE turn_id=:turn AND kind=:kind
                AND payload->>'tool'=:tool AND payload->>'tool_call_id'=:call
                AND payload->>'fence'=:fence LIMIT 1'''),{'turn':turn['id'],'kind':kind,'tool':name,
                'call':envelope['tool_call_id'],'fence':str(envelope['fence'])}).first()
            if not exists:queue.event(c,turn['conversation_id'],turn['id'],kind,
                {'tool':name,'tool_call_id':envelope['tool_call_id'],'fence':envelope['fence'],**(extra or {})})
    event_once('tool_running')
    try:
        result={'rerun_analysis':rerun_analysis,'analyze_segment':analyze_segment,'evaluate_analysis':evaluate_analysis}[name](service,envelope)
        if name in ('rerun_analysis','analyze_segment') or result['status'] in ('succeeded','failed','cancelled'):
            event_once('tool_failed' if result['status'] in ('failed','cancelled') else 'tool_completed',
                {k:str(v) if k in ('job_id','child_run_id','run_id') else v for k,v in result.items()
                 if k in ('job_id','child_run_id','run_id','status','report_version','references')})
        return result
    except Exception:
        try:event_once('tool_failed')
        except AgentLeaseLost:pass
        raise


def rerun_analysis(service,envelope):
    """Merge a small model-facing patch into immutable parent configuration."""
    args=envelope['arguments']
    if not set(args)&{'windows_hours','thresholds','max_candidates'} or set(args)-{'windows_hours','thresholds','max_candidates','hypothesis','based_on'}:
        raise APIError('TOOL_ARGUMENTS_INVALID',422)
    # JSON schema numbers alone do not reliably reject non-finite Python floats.
    def finite(value):
        if isinstance(value,float):return math.isfinite(value)
        if isinstance(value,dict):return all(finite(v) for v in value.values())
        if isinstance(value,list):return all(finite(v) for v in value)
        return True
    if not finite(args):raise APIError('TOOL_ARGUMENTS_INVALID',422)
    queue=AgentQueue(service.engine)
    with service.engine.begin() as c:
        turn=service.row(c,'agent_turns',envelope['turn_id'])
        claim={'id':turn['id'],'conversation_id':turn['conversation_id'],'worker_id':envelope['worker_id'],'fence':envelope['fence']}
        turn=queue.owned(c,claim)
        if turn['selected_run_id']!=envelope['parent_run_id']:raise APIError('TOOL_RUN_MISMATCH')
        parent=service.row(c,'runs',turn['selected_run_id'])
        config={**parent['config'],**{k:v for k,v in args.items() if k not in ('hypothesis','based_on')}}
        config.pop('segment',None)  # Rerun searches the full dataset; segment is a separate diagnostic tool.
        if not service.validators['config'].is_valid(config):raise APIError('TOOL_ARGUMENTS_INVALID',422)
        if config.get('analysis_version')=='4.0-time-aware':
            from server.analysis.v4_contract import validate_config
            try:validate_config(config)
            except ValueError:raise APIError('TOOL_ARGUMENTS_INVALID',422) from None
        # A turn may reduce its inherited budget, never silently raise it.
        if config['max_candidates']>parent['config']['max_candidates']:
            raise APIError('TOOL_CANDIDATE_BUDGET_EXCEEDED',422)
    result=create_branch(service,{**envelope,'arguments':{'config':config},'round_note':{k:args[k] for k in ('hypothesis','based_on') if k in args}})
    return {'tool':'rerun_analysis','parent_run_id':str(envelope['parent_run_id']),
            **result,'references':[]}


def analyze_segment(service,envelope):
    from server.analysis.segments import validate_segment
    from server.analysis.ingest import IngestError
    try:validate_segment(envelope['arguments'])
    except IngestError:raise APIError('TOOL_ARGUMENTS_INVALID',422)
    queue=AgentQueue(service.engine)
    with service.engine.begin() as c:
        turn=service.row(c,'agent_turns',envelope['turn_id'])
        claim={'id':turn['id'],'conversation_id':turn['conversation_id'],'worker_id':envelope['worker_id'],'fence':envelope['fence']}
        turn=queue.owned(c,claim)
        if turn['selected_run_id']!=envelope['parent_run_id']:raise APIError('TOOL_RUN_MISMATCH')
        parent=service.row(c,'runs',turn['selected_run_id'])
        if parent['config'].get('analysis_version')=='4.0-time-aware':raise APIError('V4_SEGMENT_NOT_SUPPORTED',422)
        config={**parent['config'],'segment':envelope['arguments']}
    result=create_branch(service,{**envelope,'arguments':{'config':config}})
    return {'tool':'analyze_segment','parent_run_id':str(envelope['parent_run_id']),**result,'references':[]}


def evaluate_analysis(service,envelope):
    """Bounded progress/result read for a child created by this exact turn."""
    args=envelope['arguments']
    from uuid import UUID
    try:
        if set(args)!={'child_run_id'} or not isinstance(args['child_run_id'],str):raise ValueError()
        child_id=UUID(args['child_run_id'])
    except (ValueError,TypeError):raise APIError('TOOL_ARGUMENTS_INVALID',422)
    queue=AgentQueue(service.engine)
    with service.engine.begin() as c:
        turn=service.row(c,'agent_turns',envelope['turn_id'])
        claim={'id':turn['id'],'conversation_id':turn['conversation_id'],'worker_id':envelope['worker_id'],'fence':envelope['fence']}
        turn=queue.owned(c,claim)
        if turn['selected_run_id']!=envelope['parent_run_id']:raise APIError('TOOL_RUN_MISMATCH')
        branches=service.tables['analysis_branches']
        branch=c.execute(select(branches).where(branches.c.run_id==child_id,branches.c.source_turn_id==turn['id'])).mappings().one_or_none()
        if not branch:raise APIError('TOOL_CHILD_NOT_OWNED',422)
        child=service.row(c,'runs',child_id)
        if child['parent_run_id']!=turn['selected_run_id']:raise APIError('TOOL_RUN_MISMATCH')
        result={'tool':'evaluate_analysis','parent_run_id':str(turn['selected_run_id']),
                'run_id':str(child_id),'status':child['status'],'references':[]}
    if child['status']=='succeeded':
        view,report=ready_report(service,child_id)
        with service.engine.connect() as c:
            versions,artifacts=service.tables['report_versions'],service.tables['artifacts']
            artifact=c.execute(select(artifacts).join(versions,versions.c.artifact_id==artifacts.c.id)
                .where(versions.c.run_id==child_id,versions.c.version==view['report_version'])).mappings().one()
        def ref(pointer):
            identity=f'report:{artifact["id"]}#{pointer}'
            result['references'].append({'evidence_id':identity,'artifact_id':str(artifact['id']),
                'run_id':str(child_id),'sha256':artifact['sha256'],'json_pointer':pointer})
            return identity
        from server.analysis.report_language import event_name
        result.update(report_version=view['report_version'],synthetic=report['synthetic'],
            content={'analysis_status':report['analysis_status'],'evidence_status':'exploratory',
                'config':child['config'],'report_evidence_id':ref('/summary'),
                'candidates':[{**{k:row[k] for k in ('candidate_id','metrics','event_spec','evidence_status','reasons')},
                    'display_name':event_name(row['event_spec']),
                    'evidence_id':ref(f'/candidates/{i}')} for i,row in enumerate(report['candidates'])],
                'limitations':report['limitations']})
        if report.get('schema_version')=='4.0':
            from server.analysis.v4_metrics import compact_evidence
            for target,source in zip(result['content']['candidates'],report['candidates']):
                target['metrics']={k:v for k,v in target['metrics'].items() if k!='time_comparisons'}
                target['time_analysis']=compact_evidence(source['time_analysis'])
        if report['summary'].get('segment') is not None:
            result['content']['segment']=report['summary']['segment']
        from server.validation_exposure import record_report_exposure
        record_report_exposure(service,child_id,view['report_version'],'agent_tool')
    if len(json.dumps(result,default=str,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode())>128*1024:
        raise APIError('TOOL_PAYLOAD_TOO_LARGE',413)
    with service.engine.begin() as c:queue.owned(c,claim)
    return result


def create_branch(service,envelope):
    arguments=envelope['arguments']
    if set(arguments)!={'config'} or not service.validators['config'].is_valid(arguments['config']):
        raise APIError('BRANCH_CONFIG_INVALID',422)
    config=arguments['config']
    if config.get('analysis_version')=='4.0-time-aware':
        from server.analysis.v4_contract import validate_config
        try:validate_config(config)
        except ValueError:raise APIError('BRANCH_CONFIG_INVALID',422) from None
    queue=AgentQueue(service.engine)
    with service.engine.begin() as c:
        turn=service.row(c,'agent_turns',envelope['turn_id'])
        claim={'id':turn['id'],'conversation_id':turn['conversation_id'],'worker_id':envelope['worker_id'],'fence':envelope['fence']}
        turn=queue.owned(c,claim)
        if turn['selected_run_id']!=envelope['parent_run_id']:raise APIError('TOOL_RUN_MISMATCH')
    view,report=ready_report(service,envelope['parent_run_id'])
    if view['report_version']!=turn['report_version']:raise APIError('BRANCH_REPORT_VERSION_CHANGED')
    with service.engine.begin() as c:
        turn=queue.owned(c,claim)
        parent=service.row(c,'runs',turn['selected_run_id'])
        conversation=service.row(c,'conversations',turn['conversation_id'])
        if parent['root_run_id']!=conversation['baseline_run_id']:raise APIError('TOOL_RUN_MISMATCH')
        if config['exploration_fraction']!=parent['config']['exploration_fraction']:
            raise APIError('BRANCH_SPLIT_CHANGE_FORBIDDEN',422)
        branches=service.tables['analysis_branches'];runs=service.tables['runs']
        from server.exploration import validate_note,record_note
        note=validate_note(c,turn['id'],envelope.get('round_note',{}))
        existing=c.execute(select(runs).join(branches,branches.c.run_id==runs.c.id)
            .where(branches.c.source_turn_id==turn['id'],branches.c.tool_call_id==envelope['tool_call_id'])).mappings().one_or_none()
        if existing:
            if existing['config']!=config or existing['parent_run_id']!=parent['id']:raise IdempotencyConflict()
            old_note=c.execute(text('SELECT hypothesis,based_on FROM exploration_round_notes WHERE run_id=:id'),{'id':existing['id']}).mappings().one()
            if dict(old_note)!=note:raise IdempotencyConflict()
            jobs=service.tables['jobs']
            job_id=c.execute(select(jobs.c.id).where(jobs.c.run_id==existing['id'])).scalar_one()
            return {'job_id':job_id,'child_run_id':existing['id'],'status':existing['status'],'reused':True}
        from server.exploration import ensure_budget,check_budget,record_round
        ensure_budget(c,turn['id'],parent['config'])
        ordinal=check_budget(c,turn['id'],config['max_candidates'])
        dataset=service.row(c,'datasets',parent['dataset_id'])
        versions=service.tables['report_versions'];artifacts=service.tables['artifacts']
        artifact=c.execute(select(artifacts).join(versions,versions.c.artifact_id==artifacts.c.id)
            .where(versions.c.run_id==parent['id'],versions.c.version==turn['report_version'])).mappings().one()
        version=pipeline_version()
        child=service.repo.create_run(c,parent['dataset_id'],config,
            f"branch:{turn['id']}:{envelope['tool_call_id']}",parent_run_id=parent['id'],calculation_version=version)
        delta={key:{'before':parent['config'].get(key),'after':value} for key,value in config.items() if parent['config'].get(key)!=value}
        context={'dataset_fingerprint':dataset['fingerprint'],'mapping_sha256':fingerprint(dataset['mapping']),
                 'parent_split_id':(report['summary'].get('targets') or {}).get('split_id'),'calculation_version':version,'config_sha256':fingerprint(config),
                 'seed':config['seed'],'reuse_policy':'exact_stage_inputs_only'}
        c.execute(insert(branches).values(run_id=child['id'],source_turn_id=turn['id'],tool_call_id=envelope['tool_call_id'],
            parent_report_artifact_id=artifact['id'],parent_report_version=turn['report_version'],
            parent_report_sha256=artifact['sha256'],config_delta=delta,cache_context=context))
        record_round(c,turn['id'],child['id'],ordinal,config)
        record_note(c,child['id'],note)
        queue.owned(c,claim)
        jobs=service.tables['jobs']
        job_id=c.execute(select(jobs.c.id).where(jobs.c.run_id==child['id'])).scalar_one()
        return {'job_id':job_id,'child_run_id':child['id'],'status':child['status'],'reused':False}


def branch_lineage(service,run_id):
    with service.engine.connect() as c:
        run=service.row(c,'runs',run_id)
        table=service.tables['analysis_branches']
        branch=c.execute(select(table).where(table.c.run_id==run_id)).mappings().one_or_none()
        return {'run_id':run_id,'dataset_id':run['dataset_id'],'parent_run_id':run['parent_run_id'],
                'root_run_id':run['root_run_id'],'evidence_status':run['evidence_status'],
                'branch':dict(branch) if branch else None}
