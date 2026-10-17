"""Business limits live in PG, not model instructions or a second agent loop."""
import json
from uuid import UUID
from sqlalchemy import text
from server.uploads import APIError


def validate_note(c,turn_id,note):
    if not isinstance(note,dict) or set(note)-{'hypothesis','based_on'}:raise APIError('TOOL_ARGUMENTS_INVALID',422)
    hypothesis=note.get('hypothesis');basis=note.get('based_on',[])
    if hypothesis is not None and (not isinstance(hypothesis,str) or not hypothesis.strip() or len(hypothesis)>1000):
        raise APIError('TOOL_ARGUMENTS_INVALID',422)
    if (not isinstance(basis,list) or len(basis)>10 or any(not isinstance(ref,str) or len(ref)>500 for ref in basis)
            or len(set(basis))!=len(basis)):raise APIError('TOOL_ARGUMENTS_INVALID',422)
    for reference in basis:
        found=c.execute(text('''SELECT 1 FROM conversation_events e,
            LATERAL jsonb_array_elements(coalesce(e.payload->'references','[]'::jsonb)) r
            WHERE e.turn_id=:turn AND e.kind='tool_completed' AND r->>'evidence_id'=:ref LIMIT 1'''),
            {'turn':turn_id,'ref':reference}).first()
        if not found:raise APIError('ROUND_EVIDENCE_NOT_DELIVERED',422)
    return {'hypothesis':hypothesis,'based_on':sorted(basis)}


def record_note(c,run_id,note):
    c.execute(text('''INSERT INTO exploration_round_notes(run_id,hypothesis,based_on)
        VALUES(:run,:hypothesis,CAST(:basis AS jsonb))'''),{'run':run_id,'hypothesis':note['hypothesis'],'basis':json.dumps(note['based_on'])})


def ensure_budget(c,turn_id,parent_config):
    c.execute(text('''INSERT INTO exploration_budgets(turn_id,max_rounds,max_candidates,deadline)
        VALUES(:turn,4,:candidates,clock_timestamp()+interval '600 seconds') ON CONFLICT DO NOTHING'''),
        {'turn':turn_id,'candidates':parent_config['max_candidates']*4})


def budget_view(c,turn_id):
    budget=c.execute(text('''SELECT b.*,clock_timestamp()>=b.deadline expired,
        (SELECT count(*) FROM exploration_rounds r WHERE r.turn_id=b.turn_id) rounds_used,
        (SELECT coalesce(sum(reserved_candidates),0) FROM exploration_rounds r WHERE r.turn_id=b.turn_id) candidates_used,
        EXISTS(SELECT 1 FROM exploration_finalizations f WHERE f.turn_id=b.turn_id) finalized
        FROM exploration_budgets b WHERE b.turn_id=:turn'''),{'turn':turn_id}).mappings().one()
    return dict(budget)


def check_budget(c,turn_id,reserved):
    state=budget_view(c,turn_id)
    if state['finalized']:raise APIError('EXPLORATION_FINALIZED',409)
    if state['expired']:raise APIError('EXPLORATION_TIME_LIMIT',409)
    if state['rounds_used']>=state['max_rounds']:raise APIError('EXPLORATION_ROUND_LIMIT',409)
    if state['candidates_used']+reserved>state['max_candidates']:raise APIError('EXPLORATION_CANDIDATE_LIMIT',409)
    return state['rounds_used']+1


def record_round(c,turn_id,run_id,ordinal,config):
    c.execute(text('''INSERT INTO exploration_rounds(run_id,turn_id,ordinal,reserved_candidates,parameters)
        VALUES(:run,:turn,:ordinal,:reserved,CAST(:config AS jsonb))'''),
        {'run':run_id,'turn':turn_id,'ordinal':ordinal,'reserved':config['max_candidates'],'config':json.dumps(config,allow_nan=False)})


def exploration_tool(service,name,envelope):
    from server.agent_queue import AgentQueue
    from server.branches import evaluate_analysis
    args=envelope['arguments'];queue=AgentQueue(service.engine)
    with service.engine.begin() as c:
        turn=service.row(c,'agent_turns',envelope['turn_id'])
        claim={'id':turn['id'],'conversation_id':turn['conversation_id'],'worker_id':envelope['worker_id'],'fence':envelope['fence']}
        turn=queue.owned(c,claim)
        if turn['selected_run_id']!=envelope['parent_run_id']:raise APIError('TOOL_RUN_MISMATCH')
        parent=service.row(c,'runs',turn['selected_run_id'])
        ensure_budget(c,turn['id'],parent['config'])
        if name=='get_exploration_budget':
            if args:raise APIError('TOOL_ARGUMENTS_INVALID',422)
            rounds=c.execute(text('''SELECT r.*,u.status,n.hypothesis,n.based_on FROM exploration_rounds r JOIN runs u ON u.id=r.run_id
                LEFT JOIN exploration_round_notes n ON n.run_id=r.run_id
                WHERE r.turn_id=:turn ORDER BY r.ordinal'''),{'turn':turn['id']}).mappings().all()
            return {'tool':name,'parent_run_id':str(parent['id']),'budget':budget_view(c,turn['id']),
                'rounds':[dict(row) for row in rounds],'references':[]}
    if name!='finalize_candidates':raise APIError('TOOL_NOT_ALLOWED',422)
    try:
        if set(args)!={'child_run_id','candidate_ids'}:raise ValueError()
        child=UUID(args['child_run_id']);ids=args['candidate_ids']
        if (not isinstance(ids,list) or len(ids)>10 or any(not isinstance(i,str) or not 1<=len(i)<=256 for i in ids)
                or len(set(ids))!=len(ids)):raise ValueError()
    except (ValueError,TypeError,AttributeError):raise APIError('TOOL_ARGUMENTS_INVALID',422)
    result=evaluate_analysis(service,{**envelope,'arguments':{'child_run_id':str(child)}})
    if result['status']!='succeeded':raise APIError('FINALIZE_REPORT_NOT_READY',409)
    if result['content'].get('segment') is not None:raise APIError('FINALIZE_SEGMENT_DIAGNOSTIC',422)
    known={row['candidate_id'] for row in result['content']['candidates']}
    if not set(ids)<=known:raise APIError('CANDIDATE_NOT_IN_REPORT',422)
    canonical=sorted(ids);reference=result['references'][0]
    with service.engine.begin() as c:
        queue.owned(c,claim)
        existing=c.execute(text('SELECT * FROM exploration_finalizations WHERE turn_id=:turn'),{'turn':turn['id']}).mappings().one_or_none()
        if existing:
            if existing['run_id']!=child or existing['candidate_ids']!=canonical:raise APIError('EXPLORATION_FINALIZED',409)
        else:
            state=budget_view(c,turn['id'])
            if state['expired']:raise APIError('EXPLORATION_TIME_LIMIT',409)
            owned=c.execute(text('SELECT 1 FROM exploration_rounds WHERE turn_id=:turn AND run_id=:run'),{'turn':turn['id'],'run':child}).first()
            if not owned:raise APIError('TOOL_CHILD_NOT_OWNED',422)
            c.execute(text('''INSERT INTO exploration_finalizations(turn_id,run_id,report_artifact_id,report_version,report_sha256,candidate_ids)
                VALUES(:turn,:run,:artifact,:version,:sha,CAST(:ids AS jsonb))'''),
                {'turn':turn['id'],'run':child,'artifact':reference['artifact_id'],'version':result['report_version'],
                 'sha':reference['sha256'],'ids':json.dumps(canonical)})
            queue.event(c,turn['conversation_id'],turn['id'],'tool_completed',{
                'tool':name,'tool_call_id':envelope['tool_call_id'],'fence':envelope['fence'],
                'run_id':str(child),'report_version':result['report_version'],'references':result['references']})
        return {'tool':name,'parent_run_id':str(parent['id']),'run_id':str(child),'status':'finalized',
            'candidate_ids':canonical,'report_version':result['report_version'],'references':result['references'],
            'evidence_status':'exploratory','reused':existing is not None}
