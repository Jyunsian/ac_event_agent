import json
import pytest
from server.analysis.v4_contract import defaults
from server.analysis.v4_features import build_features_v4,write_json
from server.analysis.v4_search import discover,load_frozen
from server.analysis.v4_validation import validate,test_comparison
from server.analysis.targets import build_casual_targets
from server.analysis.ingest import canonicalize,file_hash
from tests.test_v3_pipeline import v3_sources,EXPORT,MAPPING
from server.analysis.connection import connect


def prepare(tmp_path,limit=48):
    canonicalize(v3_sources(tmp_path),MAPPING,tmp_path/'normalized')
    build_casual_targets(tmp_path/'normalized',EXPORT,tmp_path/'targets')
    # Only exploration users are materialized; holdout is never passed to search features.
    with connect() as c:
        c.execute('CREATE TABLE ids AS SELECT app_id,user_id FROM read_parquet(?) WHERE split=\'exploration\'',[str(tmp_path/'targets/targets.parquet')])
        sources=[]
        for name in ('users','events'):
            c.execute('CREATE OR REPLACE TABLE data AS SELECT x.* FROM read_parquet(?) x SEMI JOIN ids USING(app_id,user_id)',[str(tmp_path/'normalized'/f'{name}.parquet')])
            path=tmp_path/f'explore_{name}.parquet';c.execute('COPY data TO ? (FORMAT PARQUET)',[str(path)])
            sources.append({'role':name,'format':'parquet','path':path,'sha256':file_hash(path)})
    canonicalize(sources,MAPPING,tmp_path/'explore')
    build_features_v4(tmp_path/'explore',EXPORT,tmp_path/'ef',scope={'kind':'exploration'})
    config={**defaults(),'max_discovery_candidates':50,'max_candidates':limit,'min_group_users':2}
    discover(tmp_path/'ef',tmp_path/'normalized',tmp_path/'targets',config,tmp_path/'search')
    build_features_v4(tmp_path/'normalized',EXPORT,tmp_path/'full')
    return config


def test_whole_bundle_freeze_and_all_tests_accounted(tmp_path):
    prepare(tmp_path)
    sha=file_hash(tmp_path/'search/frozen.json');f=load_frozen(tmp_path/'search',sha)
    assert f['family_size']<=48
    assert len(f['units'])==len({u['test_id'] for u in f['units']})
    for rule in f['rules']:
        units=[u for u in f['units'] if u['rule_id']==rule['rule_id'] and u['question']=='d7_association']
        assert len(units)==6
    result=validate(tmp_path/'normalized',tmp_path/'full',tmp_path/'targets',tmp_path/'search',sha,tmp_path/'validation')
    assert result['family_correction_complete'] and result['family_size']==f['family_size']
    for r in result['results']:
        detail=json.loads((tmp_path/'validation'/r['path']).read_text())
        assert sum(row['groups']['added']['users'] for row in detail['observation'])==detail['observation'][-1]['groups']['triggered']['users']
        assert detail['observation'][0]['groups']['all']['users']>detail['holdout'][0]['groups']['all']['users']
        for a,e,h in zip(detail['observation'],detail['exploration'],detail['holdout']):
            for group in ('all','triggered','untriggered','unknown','added'):
                assert a['groups'][group]['users']==e['groups'][group]['users']+h['groups'][group]['users']
            if e['groups']['all']['revenue_usd'] is not None and h['groups']['all']['revenue_usd'] is not None:
                assert a['groups']['all']['revenue_usd']==pytest.approx(e['groups']['all']['revenue_usd']+h['groups']['all']['revenue_usd'])
    assert file_hash(tmp_path/'search/frozen.json')==sha


def test_paired_overlap_degenerate_unknown_and_real_signal():
    identical=test_comparison([1,2,3,4],[1,1,0,0],[1,1,0,0],paired=True,minimum=2,seed=42)
    assert not identical['testable']
    assert not test_comparison([1,None,3,4],[1,1,0,0],[0,0,1,1],paired=True,minimum=2,seed=42)['testable']
    values=list(range(1,201));a=[i>=100 for i in range(200)];b=[i<150 for i in range(200)]
    r=test_comparison(values,a,b,paired=True,minimum=100,seed=42)
    assert r['testable'] and r['p_value']<.001 and r['bootstrap']['replicates']==1000

def test_report_all_formats_and_identity(tmp_path):
    from uuid import uuid4
    from server.analysis.v4_report import build_report,validate_report
    prepare(tmp_path)
    sha=file_hash(tmp_path/'search/frozen.json')
    validate(tmp_path/'normalized',tmp_path/'full',tmp_path/'targets',tmp_path/'search',sha,tmp_path/'validation')
    report=build_report(tmp_path/'search',tmp_path/'validation',uuid4(),uuid4(),tmp_path/'report')
    validate_report(report)
    assert report['schema_version']=='4.0'
    assert '多觀察一天' in (tmp_path/'report/report.html').read_text()
    import csv
    rows=list(csv.DictReader((tmp_path/'report/report.csv').open(encoding='utf-8-sig')))
    assert len(rows)==report['catalog']['evaluated_count']*18
    first=report['candidates'][0];rid=first['candidate_id']
    exported=next(r for r in rows if r['rule_id']==rid and r['scope']=='observation' and r['hours']=='24')
    assert int(exported['triggered_users'])==first['time_analysis']['observation'][0]['groups']['triggered']['users']

def test_holdout_changes_cannot_change_search_or_pairs(tmp_path):
    config=prepare(tmp_path)
    before=(tmp_path/'search/frozen.json').read_bytes()
    with connect() as c:
        c.execute("CREATE TABLE changed AS SELECT * REPLACE(CASE WHEN split='holdout' THEN 900.0 ELSE d7_revenue_usd END AS d7_revenue_usd) FROM read_parquet(?)",[str(tmp_path/'targets/targets.parquet')])
        c.execute('COPY changed TO ? (FORMAT PARQUET)',[str(tmp_path/'changed.parquet')])
    (tmp_path/'changed.parquet').replace(tmp_path/'targets/targets.parquet')
    discover(tmp_path/'ef',tmp_path/'normalized',tmp_path/'targets',config,tmp_path/'search-again')
    assert (tmp_path/'search-again/frozen.json').read_bytes()==before


def test_no_holdout_is_descriptive_and_snapshot_exits(tmp_path):
    prepare(tmp_path)
    with connect() as c:
        c.execute("CREATE TABLE changed AS SELECT * REPLACE('exploration' AS split) FROM read_parquet(?)",[str(tmp_path/'targets/targets.parquet')])
        c.execute('COPY changed TO ? (FORMAT PARQUET)',[str(tmp_path/'changed.parquet')])
    (tmp_path/'changed.parquet').replace(tmp_path/'targets/targets.parquet')
    sha=file_hash(tmp_path/'search/frozen.json')
    result=validate(tmp_path/'normalized',tmp_path/'full',tmp_path/'targets',tmp_path/'search',sha,tmp_path/'validation')
    assert all(r['evidence_status']=='exploratory' and 'NO_HOLDOUT' in r['reasons'] for r in result['results'])
    for r in result['results']:
        detail=json.loads((tmp_path/'validation'/r['path']).read_text())
        assert all(not t['claim_allowed'] for t in detail['inference'])
        assert all(p['groups']['triggered']['arpu_usd'] is None for p in detail['holdout'])


def test_sequence_search_stays_within_three_repeats():
    from types import SimpleNamespace
    from server.analysis.v4_search import generate_rules
    index=SimpleNamespace(snapshots={(('level_fail_to_complete',json.dumps({'max_gap_seconds':1800})),24):{'u':(50,0,True)}})
    rules=generate_rules(index,defaults())['sequence'].values()
    assert {r['predicate']['repeats'] for r in rules}=={1,2,3}

def test_validation_resume_reuses_pending_batch_and_corrects_whole_family(tmp_path):
    prepare(tmp_path)
    sha=file_hash(tmp_path/'search/frozen.json')
    class Batches:
        size=1
        def __init__(self):self.saved={};self.stop=True
        def load(self,i):return json.loads(self.saved[i]) if i in self.saved else None
        def save(self,i,entries):
            assert all(r['row']['evidence_status']=='pending_family_correction' for r in entries)
            self.saved[i]=json.dumps(entries)
            if self.stop:self.stop=False;raise RuntimeError('SIMULATED_INTERRUPTION')
    batches=Batches()
    with pytest.raises(RuntimeError,match='SIMULATED_INTERRUPTION'):
        validate(tmp_path/'normalized',tmp_path/'full',tmp_path/'targets',tmp_path/'search',sha,tmp_path/'interrupted',batch_store=batches)
    assert not (tmp_path/'interrupted/manifest.json').exists()
    recovered=validate(tmp_path/'normalized',tmp_path/'full',tmp_path/'targets',tmp_path/'search',sha,tmp_path/'recovered',batch_store=batches)
    original=validate(tmp_path/'normalized',tmp_path/'full',tmp_path/'targets',tmp_path/'search',sha,tmp_path/'original')
    assert recovered==original
    assert (tmp_path/'recovered/manifest.json').read_bytes()==(tmp_path/'original/manifest.json').read_bytes()

def test_existing_rule_is_named_and_deadline_does_not_create_new_identity(tmp_path):
    from server.analysis.v4_search import atom_rule
    config=prepare(tmp_path)
    rule=atom_rule('ad_count',{'ad_format':'all'},2)
    config['existing_rules']=[{'name':'目前回傳方案','rule':rule,'deadline_hours':48}]
    discover(tmp_path/'ef',tmp_path/'normalized',tmp_path/'targets',config,tmp_path/'existing-search')
    frozen=json.loads((tmp_path/'existing-search/frozen.json').read_text())
    assert frozen['existing_rules'][rule['rule_id']]==[{'name':'目前回傳方案','deadline_hours':48}]
    assert rule['rule_id'] in frozen['priority_ids']
    assert len([u for u in frozen['units'] if u['rule_id']==rule['rule_id'] and u['question']=='d7_association'])==6

def test_compact_array_evaluator_matches_dictionary_truth(tmp_path):
    from server.analysis.v4_features import FeatureIndex
    from server.analysis.v4_search import generate_rules
    config=prepare(tmp_path)
    index=FeatureIndex(tmp_path/'full')
    for category,rules in generate_rules(index,config).items():
        for rule in rules.values():
            for h in (24,48,72,96,120,144):
                status,delay=index.evaluate_array(rule,h);truth=index.evaluate(rule,h)
                for i,u in enumerate(index.ordered_users):
                    expected,t=truth[u]
                    assert status[i]=={'triggered':1,'untriggered':0,'unknown':-1}[expected],(rule,h,u)
                    if expected=='triggered':assert delay[i]==t

def test_no_mature_users_still_produces_empty_descriptive_report(tmp_path):
    from server.pipeline_v4 import exploration_features
    from server.analysis.v4_report import build_report
    from uuid import uuid4
    export={**EXPORT,'exported_at':'2026-01-06T00:00:00Z','complete_through':'2026-01-05T00:00:00Z'}
    canonicalize(v3_sources(tmp_path),MAPPING,tmp_path/'normalized')
    build_casual_targets(tmp_path/'normalized',export,tmp_path/'targets')
    exploration_features(tmp_path/'normalized',tmp_path/'targets',export,tmp_path/'explore')
    discover(tmp_path/'explore/features',tmp_path/'normalized',tmp_path/'targets',defaults(),tmp_path/'search')
    build_features_v4(tmp_path/'normalized',export,tmp_path/'full')
    validate(tmp_path/'normalized',tmp_path/'full',tmp_path/'targets',tmp_path/'search',file_hash(tmp_path/'search/frozen.json'),tmp_path/'validation')
    report=build_report(tmp_path/'search',tmp_path/'validation',uuid4(),uuid4(),tmp_path/'report')
    assert report['summary']['targets']['mature_users']==0
    assert report['summary']['targets']['immature_users']==32
    assert report['candidates']==[]
