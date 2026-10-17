from datetime import datetime, timedelta, timezone

from server.analysis.ingest import canonicalize
from server.analysis.targets import build_targets
from server.analysis.exploration import build_search_features
from server.analysis.search import generate_candidates
from tests.test_ingest import write_source, MAPPING
from tests.test_search import CONFIG
from tests.test_quality import EXPORT


def test_real_per_window_parents_have_speed_and_sample_gates(tmp_path):
    origin=datetime(2026,1,1,tzinfo=timezone.utc)
    def stamp(value):return value.isoformat().replace('+00:00','Z')
    users=[];events=[]
    for day in range(6):
        for person in range(100):
            identity=f'{day}-{person}';installed=origin+timedelta(days=day)
            users.append({'app_id':'synthetic','user_id':identity,'installed_at':stamp(installed),'platform':'android'})
            for n in range(1+person%5):
                events.append({'app_id':'synthetic','user_id':identity,'event_id':f'{identity}-{n}',
                    'event_name':'ad_impression','event_time':stamp(installed+timedelta(minutes=5*(n+1))),
                    'ad_format':'rewarded','revenue_usd':.01*(1+person%5)})
    canonicalize([write_source(tmp_path,'users',users),write_source(tmp_path,'events',events)],MAPPING,tmp_path/'normalized')
    export={**EXPORT,'complete_through':stamp(origin+timedelta(days=20)),
            'exported_at':stamp(origin+timedelta(days=21)),'revenue_timing':'immediate'}
    build_targets(tmp_path/'normalized',export,tmp_path/'targets')
    build_search_features(tmp_path/'normalized',tmp_path/'targets',export,tmp_path/'exploration',[1,3])
    result=generate_candidates(tmp_path/'exploration/features',tmp_path/'targets',
        {**CONFIG,'windows_hours':[1,3]},tmp_path/'search')
    assert result==generate_candidates(tmp_path/'exploration/features',tmp_path/'targets',
        {**CONFIG,'windows_hours':[1,3]},tmp_path/'repeat-search')
    atoms={a['candidate_id']:a for a in result['atom_ranking']}
    for selection in result['compound_parents'].values():
        assert 0<len(selection['priority_ids'])<=20
        for identity in selection['priority_ids']:
            row=atoms[identity]
            assert row['triggered_users']>=100 and row['untriggered_users']>=100
            assert row['difference_usd']>0 and 0<row['p90_seconds']<=1500
    assert any(c['predicate']['op'] in ('and','or') for c in result['candidates'])
    assert 'EQUIVALENT_PREDICATE' in {p['reason'] for p in result['pruning']}
    assert result['enumerated']==result['unique_before_cap']+sum(p['reason']=='EQUIVALENT_PREDICATE' for p in result['pruning'])
    from server.analysis.predicates import evaluate_candidates
    from server.analysis.finalists import select_and_freeze
    evaluate_candidates(tmp_path/'exploration/normalized',tmp_path/'exploration/features',result['candidates'],tmp_path/'triggers')
    selection=select_and_freeze(tmp_path/'search',tmp_path/'triggers',tmp_path/'targets',tmp_path/'selection')
    assert 0<len(selection['selected_ids'])<=10
    assert len(selection['ranking'])==len(result['candidates'])
    assert any('SIMILAR_ALTERNATIVE' in r['reasons'] for r in selection['ranking'])
    for row in selection['ranking']:
        if row['candidate_id'] in selection['selected_ids']:
            assert row['eligible'] and row['p90_seconds']>0 and row['role']
    assert selection==select_and_freeze(tmp_path/'search',tmp_path/'triggers',tmp_path/'targets',tmp_path/'repeat-selection')
    # The final two whole install days are holdout. Change only their outcomes;
    # provenance hashes must change, while every exploration decision stays fixed.
    changed=tmp_path/'changed';changed.mkdir()
    changed_events=[{**event,'revenue_usd':999.0} if int(event['user_id'].split('-')[0])>=4
                    else event for event in events]
    canonicalize([write_source(changed,'users',users),write_source(changed,'events',changed_events)],MAPPING,changed/'normalized')
    build_targets(changed/'normalized',export,changed/'targets')
    build_search_features(changed/'normalized',changed/'targets',export,changed/'exploration',[1,3])
    changed_search=generate_candidates(changed/'exploration/features',changed/'targets',
                                      {**CONFIG,'windows_hours':[1,3]},changed/'search')
    for key in ('candidates','thresholds','atom_ranking','compound_parents','pruning','budget'):
        assert result[key]==changed_search[key]
    evaluate_candidates(changed/'exploration/normalized',changed/'exploration/features',changed_search['candidates'],changed/'triggers')
    changed_selection=select_and_freeze(changed/'search',changed/'triggers',changed/'targets',changed/'selection')
    assert selection['selected_ids']==changed_selection['selected_ids']
    assert selection['ranking']==changed_selection['ranking']
    from server.analysis.freeze import load_frozen
    original_family=load_frozen(tmp_path/'selection/family_freeze',selection['family_frozen']['sha256'])
    changed_family=load_frozen(changed/'selection/family_freeze',changed_selection['family_frozen']['sha256'])
    for key in ('candidates','priority_ids','rules','family_size','diagnostic_windows_hours'):
        assert original_family[key]==changed_family[key]
    assert original_family['source_manifest_sha256']!=changed_family['source_manifest_sha256']
