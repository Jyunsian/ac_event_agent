"""Complete, immutable candidate evidence artifacts; independent of priority projection."""
import json
from pathlib import Path

from server.analysis.ingest import IngestError,file_hash
from server.analysis.v2_contract import validate_catalog,validate_candidate_detail


def candidate_summary(detail):
    spec = detail['event_spec']; predicate = spec['predicate']
    family = 'compound' if predicate['op'] in ('and', 'or') else 'sequence' if predicate['op'] == 'sequence' else 'atom'
    atoms = predicate.get('clauses', [predicate])
    metrics = detail['validation'].get('metrics') or {}
    groups = metrics.get('groups', {})
    return {'event_spec': spec, 'family': family,
            'ad_formats': sorted({a.get('ad_format', 'all') for a in atoms if a['op'] in ('count', 'revenue_sum')}),
            'role': detail['selection'].get('role'), 'selection': detail['selection'],
            'timing_status': detail['timing_status'],
            'triggered_users': groups.get('triggered', {}).get('users'),
            'untriggered_users': groups.get('untriggered', {}).get('users'),
            'triggered_arpu_usd': groups.get('triggered', {}).get('arpu_usd'),
            'untriggered_arpu_usd': groups.get('untriggered', {}).get('arpu_usd'),
            'all_arpu_usd': groups.get('all', {}).get('arpu_usd'),
            'difference_usd': metrics.get('comparisons', {}).get('triggered_minus_untriggered'),
            'coverage': metrics.get('coverage'),
            'median_seconds': metrics.get('delay_seconds', {}).get('median'),
            'p90_seconds': metrics.get('delay_seconds', {}).get('p90')}


def build_catalog(search,selection,validation,run_id,dataset_id,destination,event_spec):
    destination=Path(destination)
    candidates=search['candidates'];ids=[c['candidate_id'] for c in candidates]
    if (validation.get('validation_version')!='2.0' or not validation.get('family_correction_complete')
            or [r['candidate_id'] for r in validation['results']]!=ids
            or validation.get('family_size')!=len(ids)
            or selection['selected_ids']!=validation['priority_ids']
            or selection['family_frozen']['sha256']!=validation['frozen_sha256']):
        raise IngestError('CATALOG_FAMILY_MISMATCH')
    destination.mkdir(parents=True,exist_ok=False)
    details=destination/'details';details.mkdir()
    ranking={r['candidate_id']:r for r in selection['ranking']}
    entries=[]
    for candidate,result in zip(candidates,validation['results']):
        identity=candidate['candidate_id']
        detail={'schema_version':'2.0','run_id':str(run_id),'dataset_id':str(dataset_id),
                'candidate_id':identity,'frozen_sha256':validation['frozen_sha256'],
                'event_spec':event_spec(candidate,search['export_metadata']),
                'exploration':ranking[identity], 'validation':result,
                'revenue_decomposition':result.get('revenue_decomposition'),
                'source_diagnostics':result.get('source_diagnostics'),
                'selection':{k:ranking[identity].get(k) for k in ('eligible','reasons','role','pareto_layer','similar_priority_id','jaccard')},
                'timing_status':'observed'}
        validate_candidate_detail(detail)
        path=details/f'{identity}.json'
        with path.open('x') as stream:json.dump(detail,stream,ensure_ascii=False,sort_keys=True,allow_nan=False)
        entries.append({'candidate_id':identity,'window_hours':candidate['window_hours'],
                        'evidence_status':result['evidence_status'],'reasons':result['reasons'],
                        'detail_sha256':file_hash(path),'summary':candidate_summary(detail)})
    catalog={'schema_version':'2.0','run_id':str(run_id),'dataset_id':str(dataset_id),
             'frozen_sha256':validation['frozen_sha256'],'priority_ids':selection['selected_ids'],
             'entries':entries,'evaluated_count':len(entries)}
    validate_catalog(catalog)
    with (destination/'catalog.json').open('x') as stream:json.dump(catalog,stream,sort_keys=True,allow_nan=False)
    with (destination/'search.json').open('x') as stream:
        json.dump({k:search.get(k) for k in ('search_version','searched_windows','enumerated','unique_before_cap',
                  'selected_count','truncated','budget','thresholds','pruning','compound_parents')},stream,ensure_ascii=False,sort_keys=True,allow_nan=False)
    return catalog
