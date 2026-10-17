"""Diagnostic cohorts over an existing target split, never a new validation split."""
import json
import os
from pathlib import Path
from server.analysis.connection import connect
from server.analysis.ingest import IngestError,file_hash
from server.analysis.metrics import summarize_users
from server.analysis.predicates import evaluate_candidates,validate_candidate,CAPABILITIES
from server.analysis.validation import verified_artifact

FIELDS={'country','platform','acquisition_source'}


def validate_segment(segment):
    if (not isinstance(segment,dict) or set(segment)!={'field','value'}
            or not isinstance(segment['field'],str) or segment['field'] not in FIELDS or not isinstance(segment['value'],str)
            or not 1<=len(segment['value'])<=200 or not segment['value'].strip()):
        raise IngestError('SEGMENT_INVALID')


def build_segment(normalized_dir,target_dir,feature_dir,candidates,segment,config,destination):
    validate_segment(segment)
    if not isinstance(candidates,list) or len(candidates)>config['max_finalists']:raise IngestError('SEGMENT_CANDIDATE_BUDGET')
    atoms=[(candidate,validate_candidate(candidate)) for candidate in candidates]
    if len({candidate['candidate_id'] for candidate in candidates})!=len(candidates):raise IngestError('DUPLICATE_CANDIDATE_ID')
    normalized_dir,target_dir,feature_dir,destination=map(Path,(normalized_dir,target_dir,feature_dir,destination))
    manifests={name:json.loads((root/'manifest.json').read_text()) for name,root in
               [('normalized',normalized_dir),('targets',target_dir),('features',feature_dir)]}
    source_hash=file_hash(normalized_dir/'manifest.json')
    target=manifests['targets'];feature=manifests['features']
    definition=feature['definition']
    if (target['source_manifest_sha256']!=source_hash or definition.get('scope') is not None
            or definition['source_manifest_sha256']!=source_hash
            or target['split_definition']['complete_through']!=definition['export_metadata']['complete_through']
            or target['split_definition']['exploration_fraction']!=config['exploration_fraction']):
        raise IngestError('SEGMENT_SOURCE_OR_SPLIT_MISMATCH')
    input_hashes=[(root/'manifest.json',file_hash(root/'manifest.json')) for root in (normalized_dir,target_dir,feature_dir)]
    users,user_hash=verified_artifact(normalized_dir,manifests['normalized'],'users')
    targets,target_hash=verified_artifact(target_dir,target,'targets')
    destination.mkdir(parents=True,exist_ok=False)
    disabled={candidate['candidate_id']:[CAPABILITIES[atom['op']] for atom in clauses
              if not feature['capabilities'][CAPABILITIES[atom['op']]]['enabled']] for candidate,clauses in atoms}
    supported=[candidate for candidate in candidates if not disabled[candidate['candidate_id']]]
    input_hashes.extend([(users,user_hash),(targets,target_hash)])
    result={'schema_version':'1.0','stage':'segment','synthetic':target['synthetic'],
            'segment':segment,'split_id':target['split_id'],'split_definition':target['split_definition'],
            'source_manifest_sha256':source_hash,'target_sha256':target_hash,
            'evidence_status':'exploratory','reasons':['SEGMENT_DIAGNOSTIC_NOT_NEW_VALIDATION'],
            'cohorts':{},'candidates':[],'candidate_specs':candidates}
    result['event_context']={key:definition['export_metadata'][key] for key in ['origin','revenue_timing']}
    if not candidates:result['reasons'].append('NO_PARENT_CANDIDATES')
    with connect(config={'memory_limit':'256MB','threads':2}) as c:
        c.read_parquet(str(users)).create_view('users')
        c.read_parquet(str(targets)).create_view('targets')
        # Identifiers come only from a fixed allowlist. Values stay bound.
        field=segment['field'];columns={row[0] for row in c.execute('DESCRIBE users').fetchall()}
        known=c.execute(f'SELECT count(*) FROM users WHERE "{field}" IS NOT NULL').fetchone()[0] if field in columns else 0
        result['field_known_users']=known
        result['field_unknown_users']=c.execute('SELECT count(*) FROM users').fetchone()[0]-known
        if not known:
            result['reasons'].append('SEGMENT_FIELD_UNAVAILABLE')
        else:
            # Evaluate only when the segment dimension exists. Capabilities
            # still come from the full dataset, never the selected subgroup.
            if supported:
                triggers=evaluate_candidates(normalized_dir,feature_dir,supported,destination/'triggers')
                trigger_path,trigger_hash=verified_artifact(destination/'triggers',triggers,'triggers')
                input_hashes.append((trigger_path,trigger_hash))
                c.read_parquet(str(trigger_path)).create_view('triggers')
            c.execute(f'''CREATE TABLE selected AS SELECT t.* FROM targets t JOIN users u USING(app_id,user_id)
                WHERE u."{field}"=?''',[segment['value']])
            result['selected_users']=c.execute('SELECT count(*) FROM selected').fetchone()[0]
            result['immature_users']=c.execute('SELECT count(*) FROM selected WHERE NOT is_mature').fetchone()[0]
            if not result['selected_users']:result['reasons'].append('SEGMENT_EMPTY')
            for split in ('exploration','holdout'):
                count,unknown,total=c.execute('''SELECT count(*),count(*) FILTER(WHERE d7_revenue_usd IS NULL),sum(d7_revenue_usd ORDER BY app_id,user_id)
                    FROM selected WHERE is_mature AND split=?''',[split]).fetchone()
                limited=count<config['min_group_users']
                reasons=['SEGMENT_TOO_SMALL'] if limited else []
                if unknown:reasons.append('UNKNOWN_REVENUE')
                result['cohorts'][split]={'users':count,'unknown_revenue_users':unknown,'reasons':reasons,
                    'revenue_usd':None if limited or unknown else total,
                    'arpu_usd':None if limited or unknown else total/count}
                for candidate in candidates:
                    metric=None
                    candidate_reasons=reasons+result['reasons']
                    if disabled[candidate['candidate_id']]:candidate_reasons=candidate_reasons+['FEATURE_CAPABILITY_DISABLED']
                    if not limited and not disabled[candidate['candidate_id']]:
                        query=c.execute('''SELECT t.app_id,t.user_id,t.d7_revenue_usd revenue_usd,t.install_day,
                            r.triggered_at IS NOT NULL triggered,epoch(r.triggered_at-t.installed_at) delay_seconds
                            FROM selected t LEFT JOIN triggers r ON t.app_id=r.app_id AND t.user_id=r.user_id AND r.candidate_id=?
                            WHERE t.is_mature AND t.split=? ORDER BY t.app_id,t.user_id''',[candidate['candidate_id'],split])
                        names=[column[0] for column in query.description]
                        rows=[dict(zip(names,values)) for values in query.fetchall()]
                        metric=summarize_users(rows,seed=config['seed'],bootstrap_replicates=config['bootstrap_replicates'],
                            min_group_users=config['min_group_users'],frozen=False,split=split)
                        metric['evidence_status']='exploratory'
                        metric['reasons']=sorted(set(metric['reasons']+result['reasons']))
                    result['candidates'].append({'candidate_id':candidate['candidate_id'],'split':split,
                        'users':count,'metrics':metric,'evidence_status':'exploratory','reasons':candidate_reasons,
                        'disabled_capabilities':sorted(set(disabled[candidate['candidate_id']]))})
    for path,digest in input_hashes:
        if file_hash(path)!=digest:raise IngestError('SEGMENT_SOURCE_CHANGED')
    partial=destination/'manifest.partial.json'
    with partial.open('x') as stream:
        json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    os.link(partial,destination/'manifest.json');partial.unlink()
    return result
