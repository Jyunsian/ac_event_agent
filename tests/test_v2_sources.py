from server.analysis.source_diagnostics import summarize_sources


def test_source_small_groups_hide_values_and_unknown_is_separate():
    rows=[]
    for source,n in [('A',20),('B',19),(None,20)]:
        for hit in (False,True):
            rows.extend({'acquisition_source':source,'triggered':hit,'revenue_usd':2 if hit else 1}
                        for _ in range(n))
    result={r['acquisition_source']:r for r in summarize_sources(rows)}
    assert set(result)=={'A','B','unknown'}
    assert result['A']['difference_usd']==result['unknown']['difference_usd']==1
    assert result['B']['triggered_arpu_usd'] is None
    assert result['B']['untriggered_arpu_usd'] is None
    assert result['B']['direction'] is None
    assert result['B']['reasons']==['INSUFFICIENT_SOURCE_GROUP_USERS']
    rows[0]['revenue_usd']=None
    result={r['acquisition_source']:r for r in summarize_sources(rows)}
    assert result['A']['difference_usd'] is None
    assert 'UNKNOWN_SOURCE_REVENUE' in result['A']['reasons']
