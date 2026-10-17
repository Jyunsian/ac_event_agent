"""V4 orchestration on the existing durable stage/checkpoint infrastructure."""
import json
from pathlib import Path
from server.analysis.connection import connect
from server.analysis.ingest import canonicalize,USER_TYPES,EVENT_TYPES,file_hash
from server.analysis.quality import build_casual_quality
from server.analysis.targets import build_casual_targets
from server.analysis.v4_features import build_features_v4,write_json
from server.analysis.v4_search import discover
from server.analysis.v4_validation import validate
from server.analysis.v4_report import build_report
from server.analysis.v4_contract import ANALYSIS_VERSION,validate_config
from server.validation_policy import reserve_validation
from server.validation_batches import ValidationBatches
from server.checkpoints import StageRunner,CheckpointStore


def exploration_features(normalized,targets,export,output):
    output.mkdir(parents=True,exist_ok=False)
    with connect(config={'memory_limit':'256MB','threads':2}) as c:
        c.execute("CREATE TABLE ids AS SELECT app_id,user_id FROM read_parquet(?) WHERE split='exploration' AND is_mature",[str(targets/'targets.parquet')])
        sources=[]
        for name in ('users','events'):
            c.execute('CREATE OR REPLACE TABLE data AS SELECT s.* FROM read_parquet(?) s SEMI JOIN ids USING(app_id,user_id)',[str(normalized/f'{name}.parquet')])
            path=output/f'{name}.parquet';c.execute('COPY (SELECT * FROM data ORDER BY ALL) TO ? (FORMAT PARQUET)',[str(path)])
            sources.append({'role':name,'format':'parquet','path':path,'sha256':file_hash(path)})
    canonicalize(sources,{'users':{k:k for k in USER_TYPES},'events':{k:k for k in EVENT_TYPES}},output/'normalized')
    build_features_v4(output/'normalized',export,output/'features',scope={'kind':'exploration','targets_sha256':file_hash(targets/'manifest.json')})
    write_json(output/'manifest.json',{'schema_version':'4.0','analysis_version':ANALYSIS_VERSION,'stage':'exploration_features_v4',
                                     'features_sha256':file_hash(output/'features/manifest.json')})


def run_v4(engine,storage,lease,run,ds,normalized,stage,paths,saved,modes,preflight):
    from server.pipeline import pipeline_version
    config=run['config'];validate_config(config);export=ds['export_metadata']
    quality=stage('quality_v4',lambda p:build_casual_quality(normalized,export,p))
    q=json.loads((quality/'quality_v3.json').read_text())
    if {'SINGLE_APP_REQUIRED','NO_VALID_USERS','QUARANTINED_IDENTITIES','UNRECONCILED_EVENTS'}.intersection(q['capabilities']['revenue_analysis']['reasons']):raise ValueError('V4_STRUCTURAL_QUALITY_BLOCKED')
    targets=stage('targets_v4',lambda p:build_casual_targets(normalized,export,p,config['exploration_fraction']))
    exploration=stage('exploration_features_v4',lambda p:exploration_features(normalized,targets,export,p))
    search=stage('discovery_v4',lambda p:discover(exploration/'features',normalized,targets,config,p))
    search_info=json.loads((search/'manifest.json').read_text());frozen=json.loads((search/'frozen.json').read_text())
    policy=reserve_validation(engine,lease,run['dataset_id'],search,search_info['frozen_sha256'])
    full=stage('full_features_v4',lambda p:build_features_v4(normalized,export,p))
    batches=ValidationBatches(StageRunner(CheckpointStore(engine,storage,lease),Path(full).parents[1],pipeline_version(),ds['fingerprint'],config),search_info['frozen_sha256'],frozen['rule_ids'],version='4.0')
    validation=stage('validation_v4',lambda p:validate(normalized,full,targets,search,search_info['frozen_sha256'],p,policy,batches))
    report=stage('report_v4',lambda p:build_report(search,validation,run['id'],run['dataset_id'],p))
    stage('cache_audit_v4',lambda p:write_json(p/'manifest.json',{'schema_version':'4.0','analysis_version':ANALYSIS_VERSION,'stage_modes':modes}))
    exported={'quality_v4':{'quality_v3.json':'quality','dataset_profile_v3.json':'dataset_profile'},
              'targets_v4':{'manifest.json':'targets'},'discovery_v4':{'manifest.json':'search','frozen.json':'validation_freeze'},
              'validation_v4':{'manifest.json':'validation'},
              'report_v4':{'report.json':'report_json','report.html':'report_html','report.csv':'report_csv',
                           'catalog/catalog.json':'candidate_catalog','catalog/search.json':'candidate_search','discovery.json':'discovery_json'}}
    artifacts=[]
    for name,entries in exported.items():
        for entry in saved[name]['files']:
            if entry['path'] in entries:artifacts.append({'kind':entries[entry['path']],**{k:entry['object'][k] for k in ('object_key','sha256','size_bytes')}})
    return {'summary':{'stage':'baseline_v4','analysis_status':'analyzed','completed_stages':list(saved),'stage_modes':modes,
                       'counts':{'discovery':search_info['discovery_count'],'validation':search_info['formal_comparison_count'],
                                 'rules':search_info['validated_rule_count'],'priority':len(frozen['priority_ids'])},
                       'reasons':policy['reasons'],'resource_preflight':preflight},'artifacts':artifacts,'report_kind':'report_json'}
