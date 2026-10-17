import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from server.analysis.v2_contract import WINDOWS, QUANTILES, validate_catalog, validate_report_header, validate_candidate_detail


def catalog():
    return {'schema_version':'2.0','run_id':'00000000-0000-0000-0000-000000000001',
            'dataset_id':'00000000-0000-0000-0000-000000000002','frozen_sha256':'a'*64,
            'priority_ids':['b'*64],'evaluated_count':1,'entries':[
                {'candidate_id':'b'*64,'window_hours':144,'evidence_status':'insufficient_data',
                 'reasons':['INSUFFICIENT_GROUP_USERS'],'detail_sha256':'c'*64}]}


def test_catalog_binds_complete_population_and_boundary():
    assert validate_catalog(catalog())['evaluated_count'] == 1
    for mutate in (
        lambda x:x.update(evaluated_count=2),
        lambda x:x.update(priority_ids=['d'*64]),
        lambda x:x['entries'][0].update(window_hours=168),
        lambda x:x['entries'][0].update(window_hours=float('nan')),
        lambda x:x['entries'][0].update(evidence_status='campaign_validated'),
        lambda x:x.update(schema_version='1.0'),
        lambda x:x.update(entries=x['entries']*2,evaluated_count=2),
    ):
        value=copy.deepcopy(catalog());mutate(value)
        with pytest.raises(ValueError):validate_catalog(value)
    boundary=catalog();boundary['entries'][0]['window_hours']=168;boundary['priority_ids']=[]
    validate_catalog(boundary)


def test_hand_revenue_truth_and_first_trigger():
    fixture=json.loads(Path('tests/fixtures/candidate_v2.json').read_text(),parse_float=Decimal)
    assert fixture['synthetic'] is True
    assert WINDOWS == (1,3,6,12,24,48,72,96,120,144)
    assert len(QUANTILES) == 19 and QUANTILES[0] == .05 and QUANTILES[-1] == .95
    for user in fixture['users']:
        events=user['events']
        assert sum(v for h,v in events if h<168) == user['d7']
        for window in (6,144):
            before=sum(v for h,v in events if h<window)
            after=sum(v for h,v in events if window<=h<168)
            assert before == user[f'before{window}']
            assert after == user[f'after{window}']
            assert before+after == user['d7']
        cumulative=0;first=None
        for h,v in events:
            cumulative+=v
            if cumulative>=fixture['revenue_threshold']:
                first=h;break
        assert first == fixture['expected_first_threshold_hours'][user['id']]


def test_actual_v1_report_and_v2_envelope_preserve_original(tmp_path):
    from tests.test_report import diagnostic_sources
    from server.analysis.report import build_report
    old = build_report(diagnostic_sources(tmp_path), tmp_path/'report')
    original = (tmp_path/'report/report.json').read_bytes()
    assert validate_report_header(old, run_id='synthetic-run') is old
    new = copy.deepcopy(old)
    new.update(schema_version='2.0', catalog={'sha256':'a'*64, 'evaluated_count':0, 'priority_ids':[]})
    assert validate_report_header(new) is new
    for update in ({'schema_version':'3.0'}, {'catalog':None}, {'catalog':{'sha256':'a'*64,'evaluated_count':1,'priority_ids':['b'*64]}}):
        with pytest.raises(ValueError):validate_report_header({**new, **update})
    with pytest.raises(ValueError):validate_report_header(old,run_id='another-run')
    assert (tmp_path/'report/report.json').read_bytes() == original
    assert 'catalog' not in old


def test_detail_rejects_assumed_verified_or_unexecutable_condition():
    from server.analysis.metrics import summarize_users
    summary = summarize_users([], bootstrap_replicates=100)
    value={'schema_version':'2.0','run_id':catalog()['run_id'],'dataset_id':catalog()['dataset_id'],
           'candidate_id':'b'*64,'frozen_sha256':'a'*64,
           'event_spec':{'window_hours':144,'predicate':{'op':'revenue_sum','threshold':.5},
                         'trigger_policy':'first_match_once','dependencies':[]},
           'exploration':{'candidate_id':'b'*64,'triggered_users':0,'untriggered_users':0},
           'validation':{'candidate_id':'b'*64,'metrics':copy.deepcopy(summary),'evidence_status':'insufficient_data','reasons':['INSUFFICIENT_GROUP_USERS']},
           'revenue_decomposition':{},'source_diagnostics':[],'selection':{},'timing_status':'assumed_event_time'}
    validate_candidate_detail(value)
    value['validation']['evidence_status']='historically_validated'
    with pytest.raises(ValueError):validate_candidate_detail(value)
    value['timing_status']='observed'
    validate_candidate_detail(value)
    value['event_spec']['predicate']={'op':'sql','query':'select 1'}
    from server.analysis.ingest import IngestError
    with pytest.raises(IngestError):validate_candidate_detail(value)


def test_metric_contract_rejects_false_precision_and_inconsistent_groups():
    from server.analysis.metrics import summarize_users
    from server.analysis.v2_contract import validate_metric_summary
    rows = [{'app_id':'synthetic', 'user_id':str(i), 'revenue_usd':float(i),
             'install_day':'2026-01-01', 'triggered':bool(i),
             'delay_seconds':10 if i else None} for i in range(2)]
    summary = summarize_users(rows, bootstrap_replicates=100)
    assert validate_metric_summary(summary) is summary
    for mutate in (
        lambda x:x.update(coverage=.1),
        lambda x:x['groups']['all'].update(users=3),
        lambda x:x['groups']['triggered'].update(arpu_usd=9),
        lambda x:x['groups']['triggered'].update(unknown_revenue_users=1),
        lambda x:x['delay_seconds'].update(p90=float('nan')),
        lambda x:x['delay_seconds'].update(median=20),
        lambda x:x.update(reasons='missing'),
    ):
        invalid=copy.deepcopy(summary);mutate(invalid)
        with pytest.raises(ValueError):validate_metric_summary(invalid)
    rows[0]['revenue_usd']=None
    unknown=summarize_users(rows, bootstrap_replicates=100)
    validate_metric_summary(unknown)
    assert unknown['groups']['all']['revenue_usd'] is None


def test_hand_fixture_through_canonical_targets_and_features(tmp_path):
    from datetime import datetime, timedelta, timezone
    from server.analysis.ingest import canonicalize
    from server.analysis.targets import build_targets
    from server.analysis.features import build_features
    from tests.test_ingest import write_source, MAPPING
    from tests.test_quality import EXPORT
    from tests.test_targets import read_rows
    from tests.test_features import value
    fixture=json.loads(Path('tests/fixtures/candidate_v2.json').read_text())
    origin=datetime(2026,1,1,tzinfo=timezone.utc)
    def at(hours):return (origin+timedelta(hours=hours)).isoformat().replace('+00:00','Z')
    users=[{'app_id':'synthetic','user_id':u['id'],'installed_at':at(0),
            'platform':'android','acquisition_source':u['source']} for u in fixture['users']]
    users.append({'app_id':'synthetic','user_id':'immature','installed_at':at(160),'platform':'android'})
    events=[{'app_id':'synthetic','user_id':u['id'],'event_id':f'{u["id"]}-{i}',
             'event_name':'ad_impression','event_time':at(h),'available_at':at(h+2),
             'ad_format':'rewarded','revenue_usd':income}
            for u in fixture['users'] for i,(h,income) in enumerate(u['events'])]
    canonicalize([write_source(tmp_path,'users',users),write_source(tmp_path,'events',events)],MAPPING,tmp_path/'normalized')
    export={**EXPORT,'complete_through':at(170),'exported_at':at(180),'revenue_timing':'available_at'}
    build_targets(tmp_path/'normalized',export,tmp_path/'targets')
    targets=read_rows(tmp_path/'targets/targets.parquet')
    for user in fixture['users']:assert targets[user['id']]['d7_revenue_usd']==pytest.approx(user['d7'])
    assert targets['immature']['d7_revenue_usd'] is None
    build_features(tmp_path/'normalized',export,tmp_path/'features',[*WINDOWS,168])
    assert value(tmp_path/'features','late','revenue_sum',144)==pytest.approx(.2)
    assert value(tmp_path/'features','early','revenue_sum',6)==pytest.approx(.3)
    assert value(tmp_path/'features','zero','count',144)==0
    assert value(tmp_path/'features','immature','count',144) is None
    build_features(tmp_path/'normalized',{**export,'revenue_timing':'unknown'},tmp_path/'unknown',WINDOWS)
    assert value(tmp_path/'unknown','early','revenue_sum',6) is None
