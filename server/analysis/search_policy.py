"""V2 finite threshold grids and auditable family budget allocation."""
import math
from itertools import zip_longest

from server.analysis.v2_contract import FAMILY_WEIGHTS


def threshold_grid(metric, quantiles, minimum, maximum, fixed=()):
    values=set(fixed)
    values.update(quantiles or ())
    if metric=='revenue_sum' and minimum is not None and maximum is not None and minimum>0:
        for exponent in range(math.floor(math.log10(minimum))-1, math.ceil(math.log10(maximum))+1):
            for multiplier in (1,2,5):
                value=multiplier*10.0**exponent
                if minimum<=value<=maximum: values.add(value)
    if metric!='revenue_sum': values={math.ceil(v) for v in values}
    return sorted(v for v in values if math.isfinite(v) and v>0)


def family(candidate):
    op=candidate['predicate']['op']
    return 'compound' if op in ('and','or') else 'sequence' if op=='sequence' else 'atom'


def allocate_candidates(pool, windows, limit):
    queues={}
    for name in FAMILY_WEIGHTS:
        by_window=[sorted((p for p in pool if family(p)==name and p['window_hours']==w),
                          key=lambda p:p['candidate_id']) for w in windows]
        queues[name]=[p for row in zip_longest(*by_window) for p in row if p is not None]
    quotas={name:limit*weight//100 for name,weight in FAMILY_WEIGHTS.items()}
    counts={name:min(quotas[name],len(queues[name])) for name in queues}
    remaining=limit-sum(counts.values())
    for name in queues:
        extra=min(remaining,len(queues[name])-counts[name]);counts[name]+=extra;remaining-=extra
    selected=[p for name in queues for p in queues[name][:counts[name]]]
    excluded=[p for name in queues for p in queues[name][counts[name]:]]
    return selected,excluded,{'weights':FAMILY_WEIGHTS,'initial_quotas':quotas,
                              'allocated':counts,'unused':remaining,
                              'available':{k:len(v) for k,v in queues.items()}}
