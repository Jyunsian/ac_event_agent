"""Exact empirical user bootstrap via category counts, not a parametric approximation.

Equal-valued users are compressed only with their integer multiplicity. Common
cohort categories retain the hit flag, preserving hit/all covariance. Seeded
draws differ from the historical Python RNG and are explicitly versioned.
"""
from collections import Counter
from functools import lru_cache
import numpy as np

METHOD='percentile_user_bootstrap; stratified hit/miss; common cohort draw for hit/all; empirical_hybrid_v4_shared_counts_PCG64'
_CATEGORY=np.dtype([('value','<f8'),('users','<i8')])
_SHARED_BYTES=128*1024*1024


@lru_cache(maxsize=1)
def _common_counts(total,seed,replicates):
    """Revenue-free random draw cache; exact counts of the original stream 2.

    uint16 is exact because every row contains at most 65535 draws, including
    prefix counts. Both arrays together are bounded independently of inputs.
    """
    if not 0<total<=65535 or replicates<1 or total*replicates*4>_SHARED_BYTES:
        raise ValueError('SHARED_BOOTSTRAP_WORKSPACE_LIMIT')
    rng=np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed).spawn(3)[2]))
    counts=np.empty((replicates,total),dtype=np.uint16)
    batch=max(1,min(32,1048576//total))
    for offset in range(0,replicates,batch):
        indices=rng.integers(total,size=(min(batch,replicates-offset),total))
        for row,values in enumerate(indices):
            counts[offset+row]=np.bincount(values,minlength=total)
    prefixes=np.cumsum(counts,axis=1,dtype=np.uint16)
    counts.setflags(write=False);prefixes.setflags(write=False)
    return counts,prefixes


def _can_share(total,replicates,values):
    if not 2048<=total<=65535 or total*replicates*4>_SHARED_BYTES:return False
    # Weighted raw sums need headroom. Extreme magnitudes retain the existing
    # divide-before-sum implementation instead of overflowing or underflowing.
    magnitudes=np.abs(values);positive=magnitudes[magnitudes>0];info=np.finfo(np.float64)
    return not len(positive) or (positive.max()<=info.max/(2*total) and positive.min()>=info.tiny*total)


def bootstrap_differences(hit_values,miss_values,*,seed,replicates):
    # Exact binary values/counts, not rounded buckets or digest-only keys.
    h=np.array(sorted(Counter(hit_values).items()),dtype=_CATEGORY).tobytes()
    m=np.array(sorted(Counter(miss_values).items()),dtype=_CATEGORY).tobytes()
    # Only identical empirical distributions reuse draws. Bound key cardinality
    # as well as entry count; high-cardinality populations bypass the cache.
    draw=_draw if len(h)+len(m)<=8192*_CATEGORY.itemsize else _draw.__wrapped__
    differences,paired=draw(h,m,seed,replicates)
    return list(differences),list(paired)


@lru_cache(maxsize=1024)
def _draw(h,m,seed,replicates):
    def arrays(counted):
        data=np.frombuffer(counted,dtype=_CATEGORY)
        return data['value'],data['users']
    hv,hc=arrays(h);mv,mc=arrays(m)
    nh,nm=int(hc.sum()),int(mc.sum());total=nh+nm
    if not nh or not nm:raise ValueError('BOOTSTRAP_EMPTY_GROUP')
    streams=[np.random.Generator(np.random.PCG64(s)) for s in np.random.SeedSequence(seed).spawn(3)]
    # A deterministic cost choice between two exact empirical samplers. For
    # moderately sized, diverse populations, direct uniform user indices avoid
    # thousands of sequential binomial draws per multinomial replicate.
    # Expansion is capped at 262144 users; highly repeated/large populations
    # retain the bounded category-count implementation below.
    if total<=262144 and total<=32*(len(hv)+len(mv)):
        shared=_common_counts(total,seed,replicates) if _can_share(total,replicates,np.concatenate((hv,mv))) else None
        return _draw_indexed(hv,hc,mv,mc,streams,replicates,shared_counts=shared)
    values=np.concatenate((hv,mv));probabilities=np.concatenate((hc,mc))/total
    # At most ~8 MiB per count matrix, independent of requested replicate count.
    batch=max(1,min(32,1048576//len(values)))
    differences=[];paired=[]
    for offset in range(0,replicates,batch):
        size=min(batch,replicates-offset)
        hit_draw=streams[0].multinomial(nh,hc/nh,size=size)
        miss_draw=streams[1].multinomial(nm,mc/nm,size=size)
        differences.extend((np.sum((hit_draw/nh)*hv,axis=1)-np.sum((miss_draw/nm)*mv,axis=1)).tolist())
        del hit_draw,miss_draw
        common=streams[2].multinomial(total,probabilities,size=size)
        hit_count=np.sum(common[:,:len(hv)],axis=1)
        valid=hit_count>0
        common=common[valid];hit_count=hit_count[valid]
        paired.extend((np.sum((common[:,:len(hv)]/hit_count[:,None])*hv,axis=1)
                       -np.sum((common/total)*values,axis=1)).tolist())
    return tuple(differences),tuple(paired)


def _draw_indexed(hv,hc,mv,mc,streams,replicates,*,shared_counts=None):
    hits=np.repeat(hv,hc);misses=np.repeat(mv,mc)
    nh,nm=len(hits),len(misses);total=nh+nm
    values=np.concatenate((hits,misses))
    # Identical division per sampled value, but once per source user instead
    # of once per draw cell. Keep raw values for the common-cohort estimator.
    normalized_hits=hits/nh;normalized_misses=misses/nm
    batch=max(1,min(32,1048576//total))
    differences=[];paired=[]
    for offset in range(0,replicates,batch):
        size=min(batch,replicates-offset)
        indices=streams[0].integers(nh,size=(size,nh))
        hit_means=np.sum(normalized_hits[indices],axis=1)
        del indices
        indices=streams[1].integers(nm,size=(size,nm))
        miss_means=np.sum(normalized_misses[indices],axis=1)
        differences.extend((hit_means-miss_means).tolist())
        del indices
        if shared_counts is not None:continue
        indices=streams[2].integers(total,size=(size,total))
        flags=indices<nh
        sampled=values[indices]
        del indices
        hit_count=np.sum(flags,axis=1)
        valid=hit_count>0
        all_means=np.sum(sampled/total,axis=1)
        # Divide before summing, as in the count sampler, to avoid overflowing
        # a raw revenue total. Zero-hit draws remain invalid, never filled in.
        # Reuse the sampled matrix instead of allocating multiple filtered
        # copies. Draws, division operands and row-wise sum order are unchanged.
        np.copyto(sampled,0,where=~flags)
        np.divide(sampled,hit_count[:,None],out=sampled,where=valid[:,None])
        paired.extend((np.sum(sampled,axis=1)[valid]-all_means[valid]).tolist())
    if shared_counts is not None:
        counts,prefixes=shared_counts
        # These are the SAME sampled positions as stream 2 above. Aggregating
        # multiplicities changes floating reduction order, not the resample or
        # hit/all covariance. V4 explicitly versions those last-bit differences.
        hit_sums=np.einsum('ij,j->i',counts[:,:nh],hits,optimize=False)
        miss_sums=np.einsum('ij,j->i',counts[:,nh:],misses,optimize=False)
        hit_count=prefixes[:,nh-1];valid=hit_count>0
        paired=(hit_sums[valid]/hit_count[valid]-(hit_sums[valid]+miss_sums[valid])/total).tolist()
    return tuple(differences),tuple(paired)
