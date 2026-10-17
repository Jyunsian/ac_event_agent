"""Record disclosure before returning evidence; never reset it per conversation."""
import json
import re
from sqlalchemy import select,text
from sqlalchemy.dialects.postgresql import insert
from server.artifact_reader import read_report_export
from server.uploads import APIError


def record_report_exposure(service,run_id,version,channel):
    if channel not in ('report_export','agent_tool','run_summary'):raise ValueError('Invalid disclosure channel')
    raw,_,sha=read_report_export(service,run_id,version,'json')
    report=json.loads(raw)
    targets=report.get('summary',{}).get('targets')
    split_id=targets.get('split_id') if isinstance(targets,dict) else None
    # A diagnostic report without calculable targets still discloses this dataset.
    # Do not invent a genuine split hash; eligibility must treat it conservatively.
    if split_id is None:split_id='unavailable'
    elif not isinstance(split_id,str) or not re.fullmatch('[a-f0-9]{64}',split_id):
        raise APIError('REPORT_SPLIT_INVALID')
    with service.engine.begin() as c:
        from server.validation_policy import POLICY_LOCK
        c.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':POLICY_LOCK})
        run=service.row(c,'runs',run_id)
        if report.get('run_id')!=str(run_id) or report.get('dataset_id')!=str(run['dataset_id']):
            raise APIError('REPORT_IDENTITY_MISMATCH')
        # Dataset lock also provides the serialization point for later eligibility
        # reservation. No potentially slow S3 request is made under this lock.
        service.row(c,'datasets',run['dataset_id'],True)
        versions=service.tables['report_versions']
        published=c.execute(select(versions).where(versions.c.run_id==run_id,versions.c.version==version)).mappings().one()
        table=service.tables['validation_exposures']
        c.execute(insert(table).values(dataset_id=run['dataset_id'],split_id=split_id,
            source_run_id=run_id,report_artifact_id=published['artifact_id'],report_version=version,
            report_sha256=sha,channel=channel).on_conflict_do_nothing(index_elements=['dataset_id','split_id']))
    return split_id
