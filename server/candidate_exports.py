"""Customer exports from verified, immutable candidate artifacts, never recomputation."""
import csv
import hashlib
import io
import json

from server.candidate_reader import candidate_context, filter_candidates, verified_detail
from server.storage import ObjectManifest
from server.analysis.report_language import event_name
from server.uploads import APIError


def packed(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',', ':'))


def csv_cell(value):
    if value is None:return ''
    # Numeric negative differences must remain numbers; only untrusted text
    # receives formula-injection protection.
    if isinstance(value,str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
        return "'"+value
    return value


METRICS=('triggered_users','untriggered_users','coverage','triggered_arpu_usd',
         'untriggered_arpu_usd','all_arpu_usd','difference_usd','median_seconds','p90_seconds')
COLUMNS=('record_type','candidate_id','condition','window_hours','family','ad_formats','role',
         'category','indicator_type','observation_start_hours','observation_end_hours','decision_time_hours','trigger_mode',
         'd2_early_difference_usd','d2_remaining_difference_usd','d3_early_difference_usd','d3_remaining_difference_usd','d7_difference_usd',
         'evidence_status','reasons',*METRICS,'detail_sha256','event_spec_json','evidence_json',
         'run_id','dataset_id','report_version','report_sha256','catalog_sha256','frozen_sha256',
         'synthetic','export_scope','evaluated_count','exported_count','filters_json','missing_value_policy')


def read_candidate_export(service,run_id,version,format,*,scope='complete',**query):
    if format not in ('csv','json','html') or scope not in ('complete','filtered'):
        raise APIError('CANDIDATE_EXPORT_INVALID',422)
    if scope=='complete' and any(value is not None for value in query.values()):
        raise APIError('COMPLETE_EXPORT_CANNOT_FILTER',422)
    report,report_sha,catalog,files=candidate_context(service,run_id,version)
    rows=filter_candidates(catalog,**query) if scope=='filtered' else catalog['entries']
    context={'run_id':str(run_id),'dataset_id':catalog['dataset_id'],'report_version':version,
             'report_sha256':report_sha,'catalog_sha256':report['catalog']['sha256'],
             'frozen_sha256':catalog['frozen_sha256'],'synthetic':report['synthetic'],
             'export_scope':scope,'evaluated_count':catalog['evaluated_count'],'exported_count':len(rows),
             'filters_json':packed(query),'missing_value_policy':'空白/null表示未知或未計算，不代表0。'}
    details=[]
    for entry in rows:
        details.append(verified_detail(service.storage,catalog,files,entry))
    if format in ('json','html'):
        search=json.loads(service.storage.get_bytes(ObjectManifest(**files['catalog/search.json'])))
        payload={'schema_version':report['schema_version'],'export':context,'report':report,
                 'entries':rows,'details':details,'search':search}
        if format=='html':
            if report['schema_version']=='4.0':
                from server.analysis.v4_report import table_html
                import html
                data=('<!doctype html><meta charset="utf-8"><h1>行為與時間分析</h1>'+''.join('<h2>'+html.escape(d['event_spec']['name'])+'</h2>'+table_html(d['validation'])+'<details><summary>完整證據</summary><pre>'+html.escape(packed(d))+'</pre></details>' for d in details)).encode('utf-8')
            else:
                from server.candidate_html import render_candidate_html
                data=render_candidate_html(payload)
            mime='text/html'
        else:
            data=packed(payload).encode('utf-8');mime='application/json'
    else:
        output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=COLUMNS)
        writer.writeheader()
        for entry,detail in zip(rows,details):
            if detail.get('schema_version') in ('3.0','4.0'):summary=entry['summary']
            else:
                from server.analysis.catalog import candidate_summary
                summary=candidate_summary(detail)
            row={**context,'record_type':'candidate','candidate_id':entry['candidate_id'],
                 'condition':event_name(detail['event_spec']),'window_hours':entry['window_hours'],
                 'family':summary['family'],'ad_formats':packed(summary['ad_formats']),'role':summary['role'],
                 'evidence_status':entry['evidence_status'],'reasons':packed(entry['reasons']),
                 **{key:summary[key] for key in METRICS},'detail_sha256':entry['detail_sha256'],
                 'event_spec_json':packed(detail['event_spec']),'evidence_json':packed(detail)}
            if detail.get('schema_version')=='3.0':
                candidate=detail['candidate'];check=detail['validation']['checkpoints']
                def difference(point,field):return point['comparisons'][field]['difference_usd'] if point['comparisons'] else None
                row.update(category=candidate['category'],indicator_type=candidate['indicator_type'],
                    observation_start_hours=candidate['observation_start_hours'],observation_end_hours=candidate['observation_end_hours'],
                    decision_time_hours=candidate['decision_time_hours'],trigger_mode=candidate['trigger_mode'],
                    d2_early_difference_usd=difference(check['d2'],'early'),d2_remaining_difference_usd=difference(check['d2'],'remaining'),
                    d3_early_difference_usd=difference(check['d3'],'early'),d3_remaining_difference_usd=difference(check['d3'],'remaining'),
                    d7_difference_usd=difference(check['d7'],'d7'))
            writer.writerow({key:csv_cell(value) for key,value in row.items()})
        if not rows:writer.writerow({**context,'record_type':'export_metadata'})
        data=('\ufeff'+output.getvalue()).encode('utf-8');mime='text/csv'
    return data,mime,hashlib.sha256(data).hexdigest()
