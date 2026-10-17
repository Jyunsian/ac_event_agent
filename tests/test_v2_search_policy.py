from server.analysis.search_policy import threshold_grid, allocate_candidates
from server.analysis.search import candidate_for


def test_revenue_log_scales_exact_quantiles_and_integer_rounding():
    assert threshold_grid('revenue_sum',[.037],.01,1)==[.01,.02,.037,.05,.1,.2,.5,1]
    assert threshold_grid('count',[.1,1.2,2.1],1,3,[1,2,5])==[1,2,3,5]
    assert threshold_grid('engaged_seconds',[1.01,1.9],1,2)==[2]
    assert threshold_grid('revenue_sum',None,None,None)==[]


def test_family_budget_round_robin_and_surplus_refill():
    pool=[]
    for window in (1,3,6):
        for threshold in range(1,21):
            pool.append(candidate_for(window,{'op':'count','threshold':threshold}))
        for repeats in (1,2,3):
            pool.append(candidate_for(window,{'op':'sequence','steps':['ad_impression','ad_impression'],
                'max_gap_seconds':60,'repeats':repeats,'matching':'non_overlapping'}))
    selected,excluded,audit=allocate_candidates(pool,[1,3,6],20)
    assert audit['initial_quotas']=={'atom':10,'compound':6,'sequence':4}
    assert audit['allocated']=={'atom':16,'compound':0,'sequence':4}
    assert [c['window_hours'] for c in selected[:6]]==[1,3,6,1,3,6]
    assert len(selected)==20 and len(excluded)==len(pool)-20
    assert (selected,excluded,audit)==allocate_candidates(list(reversed(pool)),[1,3,6],20)
    all_selected,none,audit=allocate_candidates(pool,[1,3,6],2000)
    assert len(all_selected)==len(pool) and none==[] and audit['unused']==2000-len(pool)
