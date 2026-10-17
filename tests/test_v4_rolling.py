from server.analysis.v4_features import rolling_first_hit

def test_warmup_half_open_deadline_and_expiry():
    assert rolling_first_hit([(3600,1),(7200,1)],2,86400)==86400
    assert rolling_first_hit([(86400,2)],2,86400) is None
    assert rolling_first_hit([(86400,2)],2,172800)==86400
    assert rolling_first_hit([(0,1),(86400,1)],2,172800) is None
    assert rolling_first_hit([(100000,1),(100000,1)],2,172800)==100000

def test_first_hit_is_sticky_and_unknown_is_not_zero():
    assert rolling_first_hit([(3600,3),(200000,1)],3,518400)==86400
    assert rolling_first_hit([(3600,3)],3,518400,unknown_at=1000) is None
    assert rolling_first_hit([(3600,3)],3,518400,unknown_at=100000)==86400

def test_rolling_subset_of_cumulative_for_nonnegative_counts():
    import random
    rng=random.Random(42)
    for _ in range(100):
        events=sorted((rng.randrange(518400),rng.random()) for _ in range(30))
        threshold=5
        hit=rolling_first_hit(events,threshold,518400)
        if hit is not None:assert sum(v for t,v in events if t<=hit)>=threshold

def test_delayed_revenue_requires_both_occurrence_and_availability():
    from server.analysis.v4_features import rolling_available_first_hit
    # A two-day-old ad arriving today is outside today's 24h window.
    assert rolling_available_first_hit([(3600,180000,1.)],1.,300000) is None
    # The same ad arriving within its 24h window is never backdated.
    assert rolling_available_first_hit([(90000,100000,1.)],1.,172800)==100000
    assert rolling_available_first_hit([(90000,100000,1.)],1.,100000) is None
    assert rolling_available_first_hit([(3600,7000,1.)],1.,86400)==86400
