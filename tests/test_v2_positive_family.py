from tests.test_ingest import write_source,MAPPING
from tests.test_quality import EXPORT
from tests.test_search import CONFIG
from server.analysis.ingest import canonicalize
from server.analysis.features import build_features
from server.analysis.targets import build_targets
from server.analysis.exploration import build_search_features
from server.analysis.search import generate_candidates,candidate_for
from server.analysis.freeze import freeze_candidates
from server.analysis.validation import validate_frozen


def test_full_family_retains_true_signal_after_all_gates(tmp_path):
    users=[];events=[]
    for day in range(1,5):
        for i in range(100):
            identity=f'{day}-{i}'
            users.append({'app_id':'synthetic','user_id':identity,'platform':'android',
                          'installed_at':f'2026-01-{day:02}T00:00:00Z','acquisition_source':'A' if i%2 else 'B'})
            hour=1 if i<50 else 4
            events.append({'app_id':'synthetic','user_id':identity,'event_id':identity,
                           'event_name':'ad_impression','event_time':f'2026-01-{day:02}T0{hour}:00:00Z',
                           'available_at':f'2026-01-{day:02}T0{hour}:00:00Z','ad_format':'rewarded',
                           'revenue_usd':(2 if i<50 else .1)+(i%7)*.001})
    export={**EXPORT,'complete_through':'2026-01-20T00:00:00Z','exported_at':'2026-01-21T00:00:00Z'}
    canonicalize([write_source(tmp_path,'users',users),write_source(tmp_path,'events',events)],MAPPING,tmp_path/'normalized')
    # Materialize all landmark horizons even though the tested condition uses 3h.
    build_features(tmp_path/'normalized',export,tmp_path/'features')
    build_targets(tmp_path/'normalized',export,tmp_path/'targets')
    build_search_features(tmp_path/'normalized',tmp_path/'targets',export,tmp_path/'exploration',[3])
    config={**CONFIG,'windows_hours':[3],'max_candidates':20,'thresholds':{'count':[1],'revenue_sum':[1]}}
    search=generate_candidates(tmp_path/'exploration/features',tmp_path/'targets',config,tmp_path/'search')
    identity=candidate_for(3,{'op':'count','threshold':1})['candidate_id']
    assert identity in [c['candidate_id'] for c in search['candidates']]
    receipt=freeze_candidates(tmp_path/'search',[identity],tmp_path/'freeze',full_family=True)
    result=validate_frozen(tmp_path/'normalized',tmp_path/'features',tmp_path/'targets',tmp_path/'freeze',receipt['sha256'],tmp_path/'validation')
    row=next(r for r in result['results'] if r['candidate_id']==identity)
    assert result['family_size']==20 and len(result['results'])==20
    assert row['evidence_status']=='historically_validated' and row['reasons']==[]
    assert row['inference']['passed'] and row['inference']['adjusted_p_value']<=.05
    assert row['metrics']['bootstrap']['replicates']==1000
    assert row['metrics']['bootstrap']['intervals']['triggered_minus_untriggered']['lower']>0
    assert row['metrics']['groups']['triggered']['users']==100
    assert row['metrics']['groups']['untriggered']['users']==100
    assert all(source['direction']=='positive' for source in row['source_diagnostics'])
    assert [landmark['window_hours'] for landmark in row['landmarks']]==[24,72,144]
