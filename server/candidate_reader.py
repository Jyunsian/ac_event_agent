"""Read immutable candidate evidence bound to a committed report version."""
import json
import re

from sqlalchemy import text

from server.artifact_reader import read_report_export
from server.analysis.v2_contract import validate_catalog, validate_candidate_detail
from server.storage import ObjectManifest
from server.uploads import APIError


def filter_candidates(catalog, *, window_hours=None, family=None, ad_format=None,
                      evidence_status=None, role=None, category=None, sort='candidate_id', descending=False):
    if (type(descending) is not bool or (ad_format is not None and (not isinstance(ad_format,str) or len(ad_format)>100))
            or (window_hours is not None and type(window_hours) is not int)
            or sort not in ('candidate_id', 'difference_usd', 'coverage', 'p90_seconds')
            or family not in (None, 'atom', 'compound', 'sequence')
            or evidence_status not in (None, 'historically_validated', 'historically_supported', 'not_supported', 'exploratory', 'insufficient_data')
            or role not in (None, '價值差較大', '覆蓋較廣', '達標較快', 'unselected')
            or category not in (None,'iaa','session_retention','level_progress','level_friction','cross_category','sequence')
            or (window_hours is not None and window_hours not in (1, 3, 6, 12, 24, 48, 72, 96, 120, 144, 168))):
        raise APIError('CANDIDATE_QUERY_INVALID', 422)
    rows = []
    for entry in catalog['entries']:
        summary = entry.get('summary', {})
        if catalog.get('schema_version')=='4.0' and window_hours is not None:
            if window_hours not in (24,48,72,96,120,144):raise APIError('CANDIDATE_QUERY_INVALID',422)
            point=next(p for p in summary['time_comparisons'] if p['hours']==window_hours)
            summary={**summary,'display_checkpoint_hours':window_hours,'coverage':point['coverage'],
                     'difference_usd':point['difference_usd'],'p90_seconds':point['delay_seconds']['p90'],
                     'median_seconds':point['delay_seconds']['median'],
                     'triggered_users':point['groups']['triggered']['users'],
                     'untriggered_users':point['groups']['untriggered']['users'],
                     'triggered_arpu_usd':point['groups']['triggered']['arpu_usd'],
                     'untriggered_arpu_usd':point['groups']['untriggered']['arpu_usd']}
            entry={**entry,'summary':summary}

        if window_hours is not None and entry['window_hours'] != window_hours and catalog.get('schema_version')!='4.0': continue
        if family is not None and summary.get('family') != family: continue
        if ad_format is not None and ad_format not in summary.get('ad_formats', []): continue
        if evidence_status is not None and entry['evidence_status'] != evidence_status: continue
        if category is not None and entry.get('category') != category: continue
        if role == 'unselected' and entry['candidate_id'] in catalog['priority_ids']: continue
        if role not in (None, 'unselected') and summary.get('role') != role: continue
        rows.append(entry)
    rows.sort(key=lambda row: row['candidate_id'])
    if sort == 'candidate_id':
        if descending: rows.reverse()
    else:
        # Stable candidate-ID tie break; unknown values always last, never zero.
        known = [r for r in rows if r.get('summary', {}).get(sort) is not None]
        unknown = [r for r in rows if r.get('summary', {}).get(sort) is None]
        known.sort(key=lambda r: r['summary'][sort], reverse=descending)
        rows = known + unknown
    return rows


def read_candidate_page(service, run_id, version, *, page=1, **query):
    if type(page) is not int or not 1 <= page <= 40:
        raise APIError('CANDIDATE_PAGE_INVALID', 422)
    report, report_sha, catalog, _ = candidate_context(service, run_id, version)
    rows = filter_candidates(catalog, **query)
    if report['schema_version']=='4.0':
        hours=query.get('window_hours') or 24
        projected=[]
        for row in rows:
            source=row['summary'];evidence=source.get('time_evidence',{})
            point=next((p for p in source.get('time_comparisons',[]) if p['hours']==hours),None)
            control=evidence.get('controls',{}).get(str(hours),{})
            # One clock only; keep full immutable detail on demand, not 6 copies per page.
            decision={'point':point,'control_compact':control.get('observation'),
                      'threshold':control.get('threshold_usd'),
                      'holdout_compact':next((p for p in evidence.get('holdout',[]) if p['hours']==hours),None),
                      'tests':[t for t in evidence.get('inference',[]) if t['hours']==hours],
                      'scopes':{scope:{'point':next((p for p in points if p['hours']==hours),None),
                           'control':source.get('time_controls',{}).get(str(hours),{}).get(scope)}
                           for scope,points in source.get('time_scopes',{}).items()}}
            projected.append({**row,'summary':{**{k:v for k,v in source.items() if k not in ('time_comparisons','time_evidence','time_scopes','time_controls')},'decision':decision}})
        rows=projected
    comparison_users=(report.get('summary',{}).get('targets') or {}).get('mature_users')
    if type(comparison_users) is not int or comparison_users<0:
        raise APIError('CANDIDATE_PAGE_INVALID', 409)
    return {'run_id': str(run_id), 'report_version': version, 'report_sha256': report_sha,
            'catalog_sha256': report['catalog']['sha256'], 'evaluated_count': catalog['evaluated_count'],
            'comparison_users': comparison_users, 'filtered_count': len(rows), 'page': page, 'page_size': 50, 'query': query,
            'priority_ids': catalog['priority_ids'], 'items': rows[(page-1)*50:page*50]}


def read_candidate_search(service, run_id, version, page=1):
    if type(page) is not int or page<1:raise APIError('CANDIDATE_PAGE_INVALID',422)
    report,report_sha,_,files=candidate_context(service,run_id,version)
    try:
        manifest=files['catalog/search.json']
        search=json.loads(service.storage.get_bytes(ObjectManifest(**manifest)))
        if search.get('schema_version') in ('3.0','4.0'):
            pruning=search['search_log']
        else:
            pruning=search['pruning']
            if search['search_version']!='2.0':raise ValueError()
        if not isinstance(pruning,list):raise ValueError()
    except (KeyError,TypeError,ValueError) as error:
        raise APIError('CANDIDATE_SEARCH_INVALID') from error
    return {'run_id':str(run_id),'report_version':version,'report_sha256':report_sha,
            'catalog_sha256':report['catalog']['sha256'],'sha256':manifest['sha256'],
            'summary':{key:value for key,value in search.items() if key not in ('pruning','search_log')},
            'page':page,'page_size':50,'pruning_count':len(pruning),'items':pruning[(page-1)*50:page*50]}


def revenue_series(catalog):
    """Project evaluated atomic income thresholds, never mix window/format cohorts."""
    groups = {}
    for entry in catalog['entries']:
        summary = entry.get('summary', {})
        predicate = summary.get('event_spec', {}).get('predicate', {})
        if predicate.get('op') != 'revenue_sum':
            continue
        key = (entry['window_hours'], predicate.get('ad_format', 'all'))
        group = groups.setdefault(key, {'window_hours': key[0], 'ad_format': key[1], 'points': []})
        hit, miss = summary.get('triggered_users'), summary.get('untriggered_users')
        group['points'].append({
            'candidate_id': entry['candidate_id'], 'threshold_usd': predicate['threshold'],
            'coverage': summary.get('coverage'), 'difference_usd': summary.get('difference_usd'),
            'sample_size': hit + miss if hit is not None and miss is not None else None,
            'evidence_status': entry['evidence_status'], 'detail_sha256': entry['detail_sha256'],
        })
    for group in groups.values():
        group['points'].sort(key=lambda point: (point['threshold_usd'], point['candidate_id']))
    return [groups[key] for key in sorted(groups)]


def read_candidate_revenue_series(service, run_id, version):
    report, report_sha, catalog, _ = candidate_context(service, run_id, version)
    return {'run_id': str(run_id), 'report_version': version, 'report_sha256': report_sha,
            'catalog_sha256': report['catalog']['sha256'], 'groups': revenue_series(catalog)}


def candidate_context(service, run_id, version):
    raw, _, report_sha = read_report_export(service, run_id, version, 'json')
    report = json.loads(raw)
    if report['schema_version'] not in ('2.0','3.0','4.0'):
        raise APIError('CANDIDATES_NOT_COMPUTED_IN_VERSION', 409)
    with service.engine.connect() as connection:
        manifests = connection.execute(text(
            "SELECT manifest FROM stage_checkpoints WHERE run_id=:run AND stage IN ('report','report_v3','report_v4')"
        ), {'run': run_id}).scalars().all()
    matches = []
    for manifest in manifests:
        entries = manifest['files']
        files = {entry['path']: entry['object'] for entry in entries}
        if (files.get('report.json', {}).get('sha256') == report_sha
                and files.get('catalog/catalog.json', {}).get('sha256') == report['catalog']['sha256']):
            if len(files) != len(entries):
                raise APIError('CANDIDATE_CHECKPOINT_INVALID')
            matches.append(files)
    if len(matches) != 1:
        raise APIError('CANDIDATE_CHECKPOINT_AMBIGUOUS')
    files = matches[0]
    try:
        raw_catalog=json.loads(service.storage.get_bytes(ObjectManifest(**files['catalog/catalog.json'])))
        if report['schema_version']=='4.0':
            from server.analysis.v4_report import validate_catalog as validate_v4_catalog
            catalog=validate_v4_catalog(raw_catalog)
        elif report['schema_version']=='3.0':
            from server.analysis.catalog_v3 import validate_catalog_v3
            catalog=validate_catalog_v3(raw_catalog)
        else:catalog=validate_catalog(raw_catalog)
        if (catalog['run_id'] != str(run_id) or catalog['dataset_id'] != report['dataset_id']
                or catalog['frozen_sha256'] != report['audit']['frozen_sha256']
                or catalog['evaluated_count'] != report['catalog']['evaluated_count']
                or catalog['priority_ids'] != report['catalog']['priority_ids']):
            raise ValueError('CATALOG_SCOPE_MISMATCH')
    except (ValueError, TypeError, KeyError) as error:
        raise APIError('CANDIDATE_CATALOG_INVALID') from error
    return report, report_sha, catalog, files


def read_candidate_detail(service, run_id, version, candidate_id):
    if not re.fullmatch(r'[0-9a-f]{64}', candidate_id):
        raise APIError('CANDIDATE_ID_INVALID', 422)
    report, report_sha, catalog, files = candidate_context(service, run_id, version)
    entry = next((entry for entry in catalog['entries'] if entry['candidate_id'] == candidate_id), None)
    if entry is None:
        raise APIError('CANDIDATE_NOT_IN_REPORT', 404)
    detail = verified_detail(service.storage, catalog, files, entry)
    return {'run_id': str(run_id), 'report_version': version, 'report_sha256': report_sha,
            'catalog_sha256': report['catalog']['sha256'], 'sha256': entry['detail_sha256'], 'content': detail}


def verified_detail(storage, catalog, files, entry):
    """One evidence contract for API and full exports; caller binds the catalog."""
    candidate_id = entry['candidate_id']
    try:
        obj = files[f'catalog/details/{candidate_id}.json']
        if obj['sha256'] != entry['detail_sha256']:
            raise ValueError('DETAIL_HASH_MISMATCH')
        raw=json.loads(storage.get_bytes(ObjectManifest(**obj)))
        if catalog.get('schema_version')=='4.0':
            detail=raw
            if detail.get('schema_version')!='4.0' or detail.get('analysis_version')!='4.0-time-aware':raise ValueError('DETAIL_VERSION_MISMATCH')
        elif catalog.get('schema_version')=='3.0':
            detail=raw
            if detail.get('schema_version')!='3.0' or detail.get('analysis_version')!='3.0-casual-game':raise ValueError('DETAIL_VERSION_MISMATCH')
        else:detail=validate_candidate_detail(raw)
        if any(detail[key] != catalog[key] for key in ('run_id', 'dataset_id', 'frozen_sha256')):
            raise ValueError('DETAIL_SCOPE_MISMATCH')
        if (detail['candidate_id'] != candidate_id
                or detail['validation']['evidence_status'] != entry['evidence_status']
                or detail['validation']['reasons'] != entry['reasons']):
            raise ValueError('DETAIL_INDEX_MISMATCH')
        if detail['event_spec']['window_hours'] != entry['window_hours']:
            raise ValueError('DETAIL_WINDOW_MISMATCH')
        if 'summary' in entry and catalog.get('schema_version') not in ('3.0','4.0'):
            from server.analysis.catalog import candidate_summary
            if candidate_summary(detail) != entry['summary']:
                raise ValueError('DETAIL_SUMMARY_MISMATCH')
    except (ValueError, TypeError, KeyError) as error:
        raise APIError('CANDIDATE_DETAIL_INVALID') from error
    return detail
