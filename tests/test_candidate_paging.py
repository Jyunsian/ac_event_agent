import pytest

from server.candidate_reader import filter_candidates
from server.uploads import APIError


def test_revenue_series_keeps_exact_thresholds_nulls_and_separate_populations():
    from copy import deepcopy
    from server.candidate_reader import revenue_series
    def entry(id, window=6, format='all', threshold=.123456789, difference=-2, hit=3):
        return {'candidate_id': id, 'window_hours': window,
                'evidence_status': 'insufficient_data', 'detail_sha256': 'a'*64,
                'summary': {'event_spec': {'predicate': {'op': 'revenue_sum',
                    'threshold': threshold, 'ad_format': format}},
                    'triggered_users': hit, 'untriggered_users': 7,
                    'coverage': None if hit is None else .3, 'difference_usd': difference}}
    catalog = {'entries': [entry('b', threshold=2), entry('a'),
                          entry('c', format='rewarded', difference=None, hit=None),
                          entry('d', window=144)]}
    other = entry('compound')
    other['summary']['event_spec']['predicate'] = {'op': 'and', 'clauses': []}
    catalog['entries'].append(other)
    original = deepcopy(catalog)
    groups = revenue_series(catalog)
    assert [(g['window_hours'],g['ad_format']) for g in groups] == [(6,'all'),(6,'rewarded'),(144,'all')]
    assert [p['candidate_id'] for p in groups[0]['points']] == ['a','b']
    assert groups[0]['points'][0]['threshold_usd'] == .123456789
    assert groups[0]['points'][0]['difference_usd'] == -2
    assert groups[0]['points'][0]['sample_size'] == 10
    assert groups[1]['points'][0]['sample_size'] is None
    assert groups[1]['points'][0]['coverage'] is None
    assert groups[1]['points'][0]['difference_usd'] is None
    assert catalog == original


def test_filters_sort_and_nulls_do_not_mutate_catalog():
    entries = [
        {'candidate_id': 'a', 'window_hours': 6, 'evidence_status': 'insufficient_data',
         'summary': {'family': 'atom', 'ad_formats': ['rewarded'], 'role': None,
                     'coverage': None, 'difference_usd': None, 'p90_seconds': None}},
        {'candidate_id': 'b', 'window_hours': 6, 'evidence_status': 'exploratory',
         'summary': {'family': 'compound', 'ad_formats': ['rewarded', 'all'], 'role': '覆蓋較廣',
                     'coverage': .5, 'difference_usd': -1, 'p90_seconds': 200}},
        {'candidate_id': 'c', 'window_hours': 144, 'evidence_status': 'historically_validated',
         'summary': {'family': 'atom', 'ad_formats': ['all'], 'role': '價值差較大',
                     'coverage': .5, 'difference_usd': 2, 'p90_seconds': 500}},
    ]
    catalog = {'entries': entries, 'priority_ids': ['b', 'c']}
    ids = lambda **q: [r['candidate_id'] for r in filter_candidates(catalog, **q)]
    assert ids(sort='coverage', descending=True) == ['b', 'c', 'a']
    assert ids(sort='difference_usd') == ['b', 'c', 'a']
    assert ids(sort='difference_usd', descending=True) == ['c', 'b', 'a']
    assert ids(sort='p90_seconds') == ['b', 'c', 'a']
    assert ids(window_hours=6, ad_format='rewarded', family='atom') == ['a']
    assert ids(evidence_status='insufficient_data') == ['a']
    assert ids(role='unselected') == ['a']
    assert ids(role='覆蓋較廣') == ['b']
    assert ids(ad_format='nonexistent') == []
    assert ids() == ['a', 'b', 'c']
    assert entries[0]['summary']['coverage'] is None


@pytest.mark.parametrize('query', [{'sort':'sql'}, {'family':'iap'}, {'window_hours':7},
                                   {'evidence_status':'guaranteed_roi'}, {'role':'best'}])
def test_rejects_invalid_query(query):
    with pytest.raises(APIError, match='CANDIDATE_QUERY_INVALID'):
        filter_candidates({'entries': [], 'priority_ids': []}, **query)
