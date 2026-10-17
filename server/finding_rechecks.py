"""Resolve source observations before sealing a new baseline; no model-supplied AST."""
from uuid import UUID
from sqlalchemy import select,insert
from server.db import fingerprint
from server.findings import _source
from server.uploads import APIError


def list_recheck_sources(service,dataset_id,limit=25,cursor=None):
    from datetime import datetime
    from sqlalchemy import tuple_
    with service.engine.connect() as c:
        ds=service.row(c,'datasets',dataset_id)
        app=service.row(c,'projects',ds['project_id'])['app_id']
        table=service.tables['app_findings']
        runs=service.tables['runs']
        query=select(table.c.id,table.c.hypothesis,table.c.source_dataset_id,table.c.source_run_id,
                     table.c.candidate_id,table.c.event_spec,table.c.outcome,table.c.created_at,
                     runs.c.config['analysis_version'].as_string().label('analysis_version')).join(
                     runs,runs.c.id==table.c.source_run_id).where(
                     table.c.app_id==app,table.c.source_dataset_id!=dataset_id)
        if cursor:
            try:
                date,identity=cursor.split('|');date=datetime.fromisoformat(date);identity=UUID(identity)
                if date.tzinfo is None:raise ValueError()
            except (ValueError,TypeError,AttributeError):raise APIError('INVALID_FINDING_CURSOR',422)
            query=query.where(tuple_(table.c.created_at,table.c.id)<tuple_(date,identity))
        rows=c.execute(query.order_by(table.c.created_at.desc(),table.c.id.desc()).limit(limit+1)).mappings().all()
    items=[dict(row) for row in rows[:limit]]
    last=items[-1] if len(rows)>limit else None
    return {'app_id':app,'items':items,'next_cursor':f"{last['created_at'].isoformat()}|{last['id']}" if last else None,
            'notice':'Prior observations are not validation of this batch. Selection freezes rules, not success.'}


def resolve_sources(service,dataset_id,finding_ids,config):
    try:
        if not isinstance(finding_ids,list) or not 1<=len(finding_ids)<=min(10,config['max_finalists'],config['max_candidates']):raise ValueError()
        ids=[UUID(str(x)) for x in finding_ids]
        if len(set(ids))!=len(ids):raise ValueError()
    except (ValueError,TypeError,KeyError):raise APIError('INVALID_RECHECK_FINDINGS',422)
    with service.engine.connect() as c:
        ds=service.row(c,'datasets',dataset_id)
        app=service.row(c,'projects',ds['project_id'])['app_id']
        table=service.tables['app_findings']
        rows=c.execute(select(table).where(table.c.id.in_(ids),table.c.app_id==app)).mappings().all()
    if len(rows)!=len(ids):raise APIError('RECHECK_FINDING_NOT_FOUND',422)
    sources=[]
    for row in sorted(rows,key=lambda x:str(x['id'])):
        if row['source_dataset_id']==dataset_id:raise APIError('RECHECK_NEW_BATCH_REQUIRED',422)
        source_run,_,artifact,candidate,_=_source(service,row['source_run_id'],row['report_version'],row['candidate_id'])
        source_version=source_run['config'].get('analysis_version',source_run['calculation_version'])
        if source_version!=config.get('analysis_version'):
            raise APIError('RECHECK_ANALYSIS_VERSION_MISMATCH',422)
        if source_version=='4.0-time-aware':raise APIError('V4_RECHECK_NOT_SUPPORTED',422)
        if source_version=='3.0-casual-game':
            raise APIError('V3_RECHECK_NOT_SUPPORTED',422)
        if artifact['sha256']!=row['report_sha256'] or candidate['event_spec']!=row['event_spec']:raise APIError('FINDING_EVIDENCE_MISMATCH')
        if candidate['event_spec']['window_hours'] not in config['windows_hours']:raise APIError('RECHECK_WINDOW_REQUIRED',422)
        if any(candidate['event_spec'][key]!=ds['export_metadata'].get(key) for key in ('origin','revenue_timing')):
            raise APIError('RECHECK_TIME_SEMANTICS_MISMATCH',422)
        sources.append({'finding_id':str(row['id']),'candidate_id':row['candidate_id'],'event_spec':row['event_spec'],
                        'report_sha256':row['report_sha256'],'source_run_id':str(row['source_run_id']),
                        'source_dataset_id':str(row['source_dataset_id']),'report_version':row['report_version']})
    return sources


def save_recheck(c,service,run_id,sources):
    c.execute(insert(service.tables['finding_rechecks']).values(run_id=run_id,sources=sources,snapshot_sha256=fingerprint(sources)))
