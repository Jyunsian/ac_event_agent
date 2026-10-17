from collections import Counter
import numpy as np
import pytest
from server.analysis.bootstrap import bootstrap_differences


def test_duplicate_values_retain_user_multiplicity_not_uniform_value_sampling():
    # H empirical distribution: P(0)=2/3, P(3)=1/3. Three independent
    # user draws have mean 1 and variance 2/3; subtract constant M mean 1.
    values,_=bootstrap_differences([0,0,3],[1,1],seed=91,replicates=20000)
    assert abs(np.mean(values))<.03
    assert np.var(values)==pytest.approx(2/3,abs=.03)
    assert set(values)<=set(range(-1,3))


def test_common_cohort_matches_exhaustive_three_user_distribution():
    # Three users H=2,H=2,M=0, 27 equally likely ordered full-cohort draws.
    # H-count k=0,1,2,3 has multiplicities 1,6,12,8. k=0 is invalid.
    separate,paired=bootstrap_differences([2,2],[0],seed=42,replicates=27000)
    assert separate==[2.0]*27000
    counts=Counter(round(value,8) for value in paired)
    assert set(counts)=={0,round(2/3,8),round(4/3,8)}
    for value,expected in [(0,8000),(round(2/3,8),12000),(round(4/3,8),6000)]:
        assert abs(counts[value]-expected)<350
    assert abs((27000-len(paired))-1000)<150


def test_fixed_seed_reproducible_with_permuted_users_and_heavy_tail():
    hits=[0,.1,.1,1e6,3.5];misses=[0,0,.2,.3]
    first=bootstrap_differences(hits,misses,seed=7,replicates=1000)
    assert first==bootstrap_differences(list(reversed(hits)),list(reversed(misses)),seed=7,replicates=1000)
    assert all(np.isfinite(part).all() for part in first)
    assert len(first[0])==1000 and 0<len(first[1])<=1000


def test_cached_distributions_do_not_share_mutable_results_or_ignore_seed():
    from server.analysis.bootstrap import _draw
    _draw.cache_clear()
    first=bootstrap_differences([0,2],[0,1],seed=5,replicates=1000)
    original=list(first[0]);first[0][0]=99999
    second=bootstrap_differences([2,0],[1,0],seed=5,replicates=1000)
    assert second[0]==original and _draw.cache_info().hits==1
    assert second!=bootstrap_differences([0,2],[0,1],seed=6,replicates=1000)
    assert second!=bootstrap_differences([0,0,2],[0,1],seed=5,replicates=1000)


def test_equal_zero_revenue_does_not_merge_hit_flag_or_invent_valid_draws():
    separate,paired=bootstrap_differences([0],[0]*9999,seed=42,replicates=2000)
    assert separate==[0.0]*2000 and set(paired)=={0.0}
    # A full-cohort draw misses the sole hit with probability (9999/10000)^10000.
    expected=2000*(1-(9999/10000)**10000)
    assert abs(len(paired)-expected)<100
    assert len(paired)<2000


def test_cache_has_bounded_entries_and_high_cardinality_bypasses_it():
    from server.analysis.bootstrap import _draw
    _draw.cache_clear()
    for seed in range(1030):bootstrap_differences([0,2],[0,1],seed=seed,replicates=100)
    assert _draw.cache_info().currsize==1024
    before=_draw.cache_info()
    result=bootstrap_differences(list(range(4097)),list(range(5000,9097)),seed=1,replicates=100)
    assert len(result[0])==100
    assert _draw.cache_info()==before


def test_binary_cache_keys_do_not_round_adjacent_float_values():
    from server.analysis.bootstrap import _draw
    _draw.cache_clear()
    adjacent=float(np.nextafter(1.0,2.0))
    first=bootstrap_differences([1.0,adjacent],[0.0],seed=17,replicates=1000)
    second=bootstrap_differences([1.0,1.0],[0.0],seed=17,replicates=1000)
    assert _draw.cache_info().misses==2
    assert first[0]!=second[0]


def test_indexed_sampler_matches_independent_per_user_draws_across_batches():
    # Independent scalar-replicate reference; asymmetric values retain hit flag
    # in the common cohort. 100 draws cross the implementation's 32-row batches.
    hits=[2.0,2.0];misses=[0.0,4.0];population=hits+misses
    streams=[np.random.Generator(np.random.PCG64(s)) for s in np.random.SeedSequence(19).spawn(3)]
    separate=[];paired=[]
    for _ in range(100):
        h=[hits[i] for i in streams[0].integers(2,size=2)]
        m=[misses[i] for i in streams[1].integers(2,size=2)]
        separate.append(sum(h)/2-sum(m)/2)
        indices=streams[2].integers(4,size=4)
        selected=[population[i] for i in indices if i<2]
        if selected:paired.append(sum(selected)/len(selected)-sum(population[i] for i in indices)/4)
    assert bootstrap_differences(hits,misses,seed=19,replicates=100)==(separate,paired)
    assert len(paired)<100


def test_large_diverse_population_does_not_expand_indexed_workspace(monkeypatch):
    import server.analysis.bootstrap as module
    def forbidden(*args,**kwargs):
        raise AssertionError('Large populations must use category counts')
    monkeypatch.setattr(module,'_draw_indexed',forbidden)
    # N=300000 and K=10000 satisfies the density condition, but exceeds the
    # independent 262144-user expansion cap. Keep all users and 100 replicates.
    hits=[float(i) for i in range(5000) for _ in range(30)]
    misses=[float(i) for i in range(5000,10000) for _ in range(30)]
    separate,paired=bootstrap_differences(hits,misses,seed=67,replicates=100)
    assert len(separate)==len(paired)==100
    assert np.isfinite(separate).all() and np.isfinite(paired).all()


@pytest.mark.parametrize('hits,misses',[
    ([.123456789],[0.0]*100),
    ([.0000001,2.123456789,2.123456789,1000000.0],[.0001,1.0,5.0]*19),
    ([1e308,1e-100],[0.0,1e307,1.123456789]),
])
def test_indexed_matrix_reuse_preserves_every_legacy_float_draw(hits,misses):
    from collections import Counter
    from server.analysis.bootstrap import _draw_indexed
    hv,hc=map(np.asarray,zip(*sorted(Counter(hits).items())))
    mv,mc=map(np.asarray,zip(*sorted(Counter(misses).items())))
    def streams():return [np.random.Generator(np.random.PCG64(s)) for s in np.random.SeedSequence(31).spawn(3)]
    actual=_draw_indexed(hv,hc,mv,mc,streams(),100)
    # Original matrix implementation, retained only as an independent reference.
    h=np.repeat(hv,hc);m=np.repeat(mv,mc);values=np.concatenate((h,m))
    nh,nm=len(h),len(m);total=nh+nm;rng=streams();separate=[];paired=[]
    for offset in range(0,100,32):
        size=min(32,100-offset)
        hm=np.sum(h[rng[0].integers(nh,size=(size,nh))]/nh,axis=1)
        mm=np.sum(m[rng[1].integers(nm,size=(size,nm))]/nm,axis=1)
        separate.extend((hm-mm).tolist())
        indices=rng[2].integers(total,size=(size,total));flags=indices<nh
        sampled=values[indices];count=flags.sum(axis=1);valid=count>0
        all_mean=np.sum(sampled/total,axis=1)
        selected=np.where(flags[valid],sampled[valid],0)/count[valid,None]
        paired.extend((np.sum(selected,axis=1)-all_mean[valid]).tolist())
    assert actual==(tuple(separate),tuple(paired))


def test_shared_counts_are_exact_original_positions_and_readonly():
    from server.analysis.bootstrap import _common_counts
    _common_counts.cache_clear()
    counts,prefixes=_common_counts(7,51,100)
    rng=np.random.Generator(np.random.PCG64(np.random.SeedSequence(51).spawn(3)[2]))
    indices=rng.integers(7,size=(100,7))
    expected=np.array([np.bincount(row,minlength=7) for row in indices])
    assert np.array_equal(counts,expected)
    assert np.array_equal(prefixes,np.cumsum(expected,axis=1))
    assert np.all(prefixes[:,-1]==7)
    with pytest.raises(ValueError):counts[0,0]=0
    with pytest.raises(ValueError):prefixes[0,0]=0
    assert _common_counts(7,51,100)[0] is counts
    _common_counts(8,51,100)
    assert _common_counts.cache_info().currsize==1
    with pytest.raises(ValueError,match='WORKSPACE_LIMIT'):_common_counts(65536,1,100)
    with pytest.raises(ValueError,match='WORKSPACE_LIMIT'):_common_counts(65535,1,1000)


def test_shared_weighted_draws_match_original_samples_and_keep_invalid_draws():
    from server.analysis.bootstrap import _common_counts,_draw_indexed,_can_share
    hv=np.array([.123456789]);hc=np.array([1])
    mv=np.linspace(0,.5,2047);mc=np.ones(2047,dtype=int)
    def streams():return [np.random.Generator(np.random.PCG64(s)) for s in np.random.SeedSequence(53).spawn(3)]
    old=_draw_indexed(hv,hc,mv,mc,streams(),1000)
    new=_draw_indexed(hv,hc,mv,mc,streams(),1000,shared_counts=_common_counts(2048,53,1000))
    assert old[0]==new[0] and len(old[1])==len(new[1])<1000
    # Weighted and per-draw sums differ only in floating reduction order.
    np.testing.assert_allclose(old[1],new[1],rtol=1e-12,atol=1e-15)
    assert _can_share(2048,1000,np.array([0,.1]))
    assert not _can_share(2048,1000,np.array([1e308]))
    assert not _can_share(2048,1000,np.array([1e-320]))
    assert not _can_share(65535,1000,np.array([.1]))
    first=bootstrap_differences(hv.tolist(),mv.tolist(),seed=53,replicates=1000)
    second=bootstrap_differences(hv.tolist(),list(reversed(mv.tolist())),seed=53,replicates=1000)
    assert first==second and first==(list(new[0]),list(new[1]))
