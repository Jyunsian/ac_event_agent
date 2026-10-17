from datetime import datetime,timedelta,timezone
from server.analysis.v4_features import repair_timeline,_scope

def test_revenue_first_hit_follows_availability_not_event_order():
    origin=datetime(2026,1,1,tzinfo=timezone.utc)
    events=[{'event_id':'a','event_name':'ad_impression','event_time':origin+timedelta(hours=1),'available_at':origin+timedelta(hours=60),'revenue_usd':.1},
            {'event_id':'b','event_name':'ad_impression','event_time':origin+timedelta(hours=2),'available_at':origin+timedelta(hours=3),'revenue_usd':.2}]
    rows=repair_timeline(events,origin,{},'available_at')[('ad_revenue_sum',_scope({'ad_format':'all'}))]
    assert rows[0]==(10800,.2)
    assert rows[1][0]==216000 and abs(rows[1][1]-.3)<1e-12

def test_unknown_revenue_is_not_zero_or_backdated():
    origin=datetime(2026,1,1,tzinfo=timezone.utc)
    event={'event_id':'a','event_name':'ad_impression','event_time':origin,'available_at':None,'revenue_usd':.1}
    assert repair_timeline([event],origin,{},'available_at')[('ad_revenue_sum',_scope({'ad_format':'all'}))]==[(0.,None)]

def test_exact_hits_and_half_open_deadlines(tmp_path):
    from tests.test_v3_pipeline import v3_sources,EXPORT,MAPPING
    from server.analysis.ingest import canonicalize
    from server.analysis.v4_features import build_features_v4,FeatureIndex
    from server.analysis.v4_contract import rule_from_candidate
    from tests.test_v3_contract import candidate,atom
    canonicalize(v3_sources(tmp_path),MAPPING,tmp_path/'normalized')
    build_features_v4(tmp_path/'normalized',EXPORT,tmp_path/'features')
    ix=FeatureIndex(tmp_path/'features')
    rule=rule_from_candidate(candidate(category='iaa',indicator_type='ad_count',predicate={**atom('ad_count',2),'scope':{'ad_format':'all'}},dependencies=['ad_impression']))
    early=ix.evaluate(rule,24);late=ix.evaluate(rule,144)
    assert early==late
    assert early[('game','d0u4')]==('triggered',3660.)
    assert early[('game','d0u0')]==('untriggered',None)

def test_delayed_rolling_and_array_membership_share_exact_truth():
    from collections import defaultdict
    from server.analysis.v4_features import FeatureIndex
    from server.analysis.v4_search import atom_rule
    ix=FeatureIndex.__new__(FeatureIndex);ix.users={('app','old'),('app','recent')};ix.cache={}
    ix.snapshots=defaultdict(dict);ix.timelines=defaultdict(dict);ix.rolling_revenue=defaultdict(list)
    key=('ad_revenue_sum',_scope({'ad_format':'all'}))
    for h in (24,48,72,96,120,144):
        ix.snapshots[(key,h)]={('app','old'):(.2 if h>=72 else 0,0,True),('app','recent'):(.2 if h>=48 else 0,0,True)}
    ix.timelines[key]={('app','old'):[(180000,.2)],('app','recent'):[(100000,.2)]}
    ix.rolling_revenue[('app','old','all')]=[(3600,180000,.2)]
    ix.rolling_revenue[('app','recent','all')]=[(90000,100000,.2)]
    rolling=atom_rule('ad_revenue_sum',{'ad_format':'all'},.1,mode='rolling')
    for h in (24,48,72,96,120,144):
        statuses,_=ix.evaluate_array(rolling,h);truth=ix.evaluate(rolling,h)
        assert statuses.tolist()==[{'triggered':1,'untriggered':0,'unknown':-1}[truth[u][0]] for u in ix.ordered_users]
    assert ix.evaluate(rolling,72)[('app','old')]==('untriggered',None)
    assert ix.evaluate(rolling,72)[('app','recent')]==('triggered',100000)
    cumulative=atom_rule('ad_revenue_sum',{'ad_format':'all'},.1)
    assert ix.evaluate(cumulative,72)[('app','old')]==('triggered',180000)

def test_missing_exact_timeline_is_unknown_not_a_deadline_fallback():
    from collections import defaultdict
    from server.analysis.v4_features import FeatureIndex
    from server.analysis.v4_search import atom_rule
    ix=FeatureIndex.__new__(FeatureIndex);ix.users={('app','a')};ix.cache={};ix.timelines={};ix.rolling_revenue={}
    ix.snapshots={(("ad_count",_scope({'ad_format':'all'})),24):{('app','a'):(5,0,True)}}
    rule=atom_rule('ad_count',{'ad_format':'all'},3)
    assert ix.evaluate(rule,24)[('app','a')]==('unknown',None)
    assert ix.evaluate_array(rule,24)[0].tolist()==[-1]
