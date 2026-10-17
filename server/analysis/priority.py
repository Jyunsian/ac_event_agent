"""Deterministic exploration-only Pareto selection; never accepts holdout metrics."""
import math


def choose_priority(rows, hit_sets, *, limit=10, min_group_users=100, deduplicate=True):
    """Rows contain candidate_id, window_hours, complexity (0/1/2), group counts,
    difference_usd, coverage and p90_seconds. Similar rows remain in the audit.
    The caller must bind rows/hit_sets to exploration artifacts before calling.
    """
    if type(limit) is not int or limit < 0 or type(min_group_users) is not int or min_group_users < 2:
        raise ValueError('INVALID_PRIORITY_CONFIG')
    ids = [r['candidate_id'] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('DUPLICATE_PRIORITY_ID')
    audit = {}
    pool = []
    for row in rows:
        reasons = []
        if row['window_hours'] >= 168: reasons.append('BOUNDARY_NOT_PRIORITY')
        if min(row['triggered_users'], row['untriggered_users']) < min_group_users:
            reasons.append('INSUFFICIENT_EXPLORATION_GROUP_USERS')
        metrics = [row[k] for k in ('difference_usd', 'coverage', 'p90_seconds')]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in metrics):
            reasons.append('UNAVAILABLE_EXPLORATION_METRICS')
        elif row['difference_usd'] <= 0:
            reasons.append('NONPOSITIVE_EXPLORATION_DIFFERENCE')
        audit[row['candidate_id']] = {'eligible':not reasons, 'reasons':reasons,
                                     'pareto_layer':None, 'role':None,
                                     'similar_priority_id':None, 'jaccard':None}
        if not reasons: pool.append(row)
    def dominates(a, b):
        av=(a['difference_usd'],a['coverage'],-a['p90_seconds'])
        bv=(b['difference_usd'],b['coverage'],-b['p90_seconds'])
        return all(x >= y for x,y in zip(av,bv)) and any(x > y for x,y in zip(av,bv))
    ordered=[]; layer=0
    while pool:
        front=[r for r in pool if not any(dominates(other,r) for other in pool)]
        front_ids={r['candidate_id'] for r in front}
        for r in front: audit[r['candidate_id']]['pareto_layer']=layer
        criteria=(('difference_usd',-1,'價值差較大'),('coverage',-1,'覆蓋較廣'),('p90_seconds',1,'達標較快'))
        queues=[sorted(front,key=lambda r:(sign*r[key],r['complexity'],r['candidate_id'])) for key,sign,_ in criteria]
        used=set()
        while len(used)<len(front):
            for queue,(_,_,role) in zip(queues,criteria):
                while queue and queue[0]['candidate_id'] in used: queue.pop(0)
                if queue:
                    row=queue.pop(0);used.add(row['candidate_id']);ordered.append((row,role))
        pool=[r for r in pool if r['candidate_id'] not in front_ids];layer+=1
    selected=[]
    for row,role in ordered:
        identity=row['candidate_id']; most=None; overlap=None
        if deduplicate:
            hits=hit_sets[identity]
            for prior in selected:
                other=hit_sets[prior]
                # Dense identity bitmaps and reference sets represent the same exact sets.
                union=(hits|other).bit_count() if isinstance(hits,int) else len(hits|other)
                intersection=(hits&other).bit_count() if isinstance(hits,int) else len(hits&other)
                similarity=intersection/union if union else 0
                if overlap is None or similarity>overlap:
                    most,overlap=prior,similarity
        item=audit[identity]
        item.update(similar_priority_id=most,jaccard=overlap)
        if deduplicate and overlap is not None and overlap>=.9:
            item['reasons'].append('SIMILAR_ALTERNATIVE')
        elif len(selected)<limit:
            selected.append(identity);item['role']=role
        else:
            item['reasons'].append('PRIORITY_LIMIT')
    return {'priority_ids':selected,'selection':audit}
