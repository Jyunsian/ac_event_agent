from collections import defaultdict
from datetime import datetime,timedelta,timezone
import pytest
from server.analysis.v4_features import FeatureIndex,repair_timeline,_scope
from server.analysis.v4_search import atom_rule
from server.analysis.v4_contract import CHECKPOINTS
from server.analysis.v4_metrics import Targets,describe,compact_evidence

@pytest.mark.parametrize('missing', ['amount','arrival','negative'])
def test_future_missing_revenue_never_rewrites_known_hit(missing):
    origin=datetime(2026,1,1,tzinfo=timezone.utc)
    events=[dict(event_id='a',event_name='ad_impression',event_time=origin+timedelta(hours=1),available_at=origin+timedelta(hours=1),revenue_usd=2.),
            dict(event_id='b',event_name='ad_impression',event_time=origin+timedelta(hours=72),available_at=None if missing=='arrival' else origin+timedelta(hours=72),revenue_usd=None if missing=='amount' else -1. if missing=='negative' else 1.)]
    key=('ad_revenue_sum',_scope({'ad_format':'all'}));u=('app','a')
    timeline=repair_timeline(events,origin,{},'available_at')[key]
    assert timeline[0]==(3600.,2.)
    ix=FeatureIndex.__new__(FeatureIndex);ix.users={u};ix.cache={};ix.timelines={key:{u:timeline}};ix.snapshots={}
    ix.rolling_revenue={(*u,'all'):[(3600,3600,2.),(259200,None if missing=='arrival' else 259200,events[1]['revenue_usd'])]}
    for h in CHECKPOINTS:ix.snapshots[(key,h)]={u:(2. if h<=72 else None,0,True)}
    for mode,expected in [('cumulative',3600.),('rolling',86400.)]:
        rule=atom_rule('ad_revenue_sum',{'ad_format':'all'},1.,mode=mode)
        for h in reversed(CHECKPOINTS):
            assert ix.evaluate(rule,h)[u]==('triggered',expected)
            status,delay=ix.evaluate_array(rule,h)
            assert status.tolist()==[1] and delay.tolist()==[expected]


def test_missing_before_first_hit_remains_unknown_in_both_evaluators():
    key=('ad_revenue_sum',_scope({'ad_format':'all'}));u=('app','a')
    ix=FeatureIndex.__new__(FeatureIndex);ix.users={u};ix.cache={};ix.timelines={key:{u:[(1000,None)]}}
    ix.snapshots={(key,h):{u:(None,0,True)} for h in CHECKPOINTS}
    ix.rolling_revenue={(*u,'all'):[(1000,1000,None),(3600,3600,2.)]}
    rule=atom_rule('ad_revenue_sum',{'ad_format':'all'},1.,mode='rolling')
    for h in CHECKPOINTS:
        assert ix.evaluate(rule,h)[u]==('unknown',None)
        assert ix.evaluate_array(rule,h)[0].tolist()==[-1]


def test_first_day_unknown_is_not_a_missed_player():
    class Index:
        def evaluate(self,rule,h):return {'a':('unknown',None) if h==24 else ('triggered',108000)}
    t=Targets.__new__(Targets);t.users={'a':{'revenue':1.,'split':'exploration'}};t.early={h:{'a':.1} for h in CHECKPOINTS}
    rows=describe({'mode':'cumulative'},Index(),t)
    assert rows[1]['groups']['triggered']['users']==1
    assert rows[1]['groups']['added']['users']==1
    assert rows[1]['baseline_24h_applicable'] is False
    assert rows[1]['groups']['added_since_24h']['users'] is None
    row={scope:rows for scope in ('observation','exploration','holdout')}
    row.update(controls={},inference=[],existing=[],cumulative_comparison=row.copy())
    compact=compact_evidence(row)
    assert compact['exploration'][1]['since_24h_users'] is None
    from server.analysis.v4_report import comparison_html,table_html
    assert '不適用 24 小時比較' in table_html(row)
    assert comparison_html(row).count('找規律的玩家')==2

@pytest.mark.parametrize('field',['revenue_usd','available_at'])
def test_real_feature_build_preserves_earlier_hits_despite_global_quality_warning(tmp_path,field):
    import csv
    from pathlib import Path
    from tests.test_v3_pipeline import v3_sources,MAPPING,EXPORT
    from server.analysis.ingest import canonicalize,file_hash
    from server.analysis.v4_features import build_features_v4
    sources=v3_sources(tmp_path);source=next(s for s in sources if s['role']=='events');path=Path(source['path'])
    with path.open() as f:reader=csv.DictReader(f);rows=list(reader);names=reader.fieldnames
    late={**next(r for r in rows if r['event_id']=='d0u4-ad-0'),'event_id':'late-missing','event_time':'2026-01-04T00:00:00Z','available_at':'2026-01-04T00:00:00Z',field:''}
    with path.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=names);w.writeheader();w.writerows([*rows,late])
    source['sha256']=file_hash(path)
    canonicalize(sources,MAPPING,tmp_path/'n')
    build_features_v4(tmp_path/'n',{**EXPORT,'revenue_timing':'available_at'},tmp_path/'f')
    ix=FeatureIndex(tmp_path/'f')
    assert not ix.quality['capabilities']['revenue_trigger']['enabled']
    for mode,delay in [('cumulative',3600.),('rolling',86400.)]:
        rule=atom_rule('ad_revenue_sum',{'ad_format':'all'},.01,mode=mode)
        for h in CHECKPOINTS:
            assert ix.evaluate(rule,h)[('game','d0u4')]==('triggered',delay)
            statuses,delays=ix.evaluate_array(rule,h)
            i=ix.ordered_users.index(('game','d0u4'))
            assert statuses[i]==1 and delays[i]==delay


def test_partly_unknown_first_day_is_excluded_from_extra_players():
    class Index:
        def evaluate(self,rule,h):
            return {'a':('untriggered',None),'b':('unknown',None)} if h==24 else {'a':('triggered',100000),'b':('triggered',100000)}
    t=Targets.__new__(Targets);t.users={u:{'revenue':1.,'split':'exploration'} for u in ('a','b')};t.early={h:{'a':.1,'b':.1} for h in CHECKPOINTS}
    point=describe({'mode':'cumulative'},Index(),t)[1]
    assert point['groups']['triggered']['users']==2
    assert point['groups']['added']['users']==2
    assert point['groups']['added_since_24h']['users']==1
    assert point['baseline_24h_unknown_users']==1
