from server.analysis.metrics import summarize_users


def test_missing_install_day_is_not_zero_coverage_or_a_failed_observed_day():
    rows=[]
    for day in ('2026-01-01','2026-01-03'):
        for i in range(40):
            rows.append({'app_id':'synthetic','user_id':f'{day}-{i}','install_day':day,
                         'revenue_usd':2.0 if i<20 else 1.0,'triggered':i<20,
                         'delay_seconds':100 if i<20 else None})
    result=summarize_users(rows,bootstrap_replicates=100,min_group_users=20,frozen=True,split='holdout')
    assert [d['install_day'] for d in result['days']]==['2026-01-01','2026-01-02','2026-01-03']
    empty=result['days'][1]
    assert empty['users']==empty['triggered_users']==0
    assert empty['coverage'] is None and empty['difference_usd'] is None
    assert 'UNSTABLE_OR_NONPOSITIVE_DAILY_DIFFERENCE' not in result['reasons']
    assert result['days'][0]['coverage']==.5
