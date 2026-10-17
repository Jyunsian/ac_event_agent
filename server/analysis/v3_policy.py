"""Deterministic Candidate V3 threshold grids, quotas and Pareto ordering."""
from __future__ import annotations

import math
from bisect import bisect_left,bisect_right
from collections import deque
from itertools import groupby

from server.analysis.v3_contract import CATEGORY_BUDGETS, DISCOVERY_LIMIT, VALIDATION_LIMIT

CATEGORY_ORDER=tuple(CATEGORY_BUDGETS)
QUANTILES=tuple(index/10 for index in range(1,10))
IAA_QUANTILES=tuple(index/20 for index in range(1,20))
NEAR_DUPLICATE_JACCARD=.995
NEAR_DUPLICATE_COVERAGE_DELTA=.005
MAX_PARENTS_PER_CATEGORY_WINDOW=20
CROSS_PARENT_COVERAGE_RANGE=(.3,.7)
COUNT_FIXED=(1,2,3,5,8,10,20)
LEVEL_FIXED=(1,2,3,5,10,20,50,100)
RATIO_FIXED=(.25,.5,.75)
ATTEMPT_FIXED=(1.5,2,3,5,8)
DURATION_FIXED=(60,300,900,1800,3600)


def finite_thresholds(metric,quantiles=(),minimum=None,maximum=None):
    fixed = (RATIO_FIXED if metric in ("complete_start_ratio","fail_start_ratio") else
             LEVEL_FIXED if metric in ("max_completed_level_index","completed_level","reached_level") else
             ATTEMPT_FIXED if metric=="attempts_per_level" else
             DURATION_FIXED if metric in ("completion_duration_seconds","first_return_delay_seconds","level_time_to_reach_seconds") else
             COUNT_FIXED)
    values=set(fixed);values.update(quantiles or ())
    if metric=="ad_revenue_sum" and minimum is not None and maximum is not None and minimum>0:
        for exponent in range(math.floor(math.log10(minimum))-1,math.ceil(math.log10(maximum))+1):
            for multiplier in (1,2,5):
                value=multiplier*10.0**exponent
                if minimum<=value<=maximum:values.add(value)
    if metric in ("ad_count","session_count","level_start_count","level_complete_count","level_fail_count",
                  "distinct_completed_levels","max_completed_level_index","completed_level","reached_level",
                  "retry_same_level","complete_after_fail","session_after_fail","return_interval_count",
                  "consecutive_return_days","post_return_session_count","consecutive_failures"):
        values={math.ceil(v) for v in values}
    return sorted(v for v in values if type(v) in (int,float) and math.isfinite(v) and v>0
                  and (minimum is None or v>=minimum) and (maximum is None or v<=maximum)
                  and (metric not in ("complete_start_ratio","fail_start_ratio") or v<=1))


def allocate_by_category(items,kind="validation",limit=None):
    index=0 if kind=="discovery" else 1
    cap=DISCOVERY_LIMIT if kind=="discovery" else VALIDATION_LIMIT
    if type(limit) is not int and limit is not None:
        raise ValueError("INVALID_CATEGORY_LIMIT")
    target=min(cap,limit if limit is not None else cap)
    if target<0:
        raise ValueError("INVALID_CATEGORY_LIMIT")
    base={category:CATEGORY_BUDGETS[category][index] for category in CATEGORY_ORDER}
    if target==cap:
        quotas=base
    else:
        raw={category:base[category]*target/cap for category in CATEGORY_ORDER}
        quotas={category:math.floor(raw[category]) for category in CATEGORY_ORDER}
        remaining=target-sum(quotas.values())
        for category in sorted(CATEGORY_ORDER,key=lambda c:(-(raw[c]-quotas[c]),CATEGORY_ORDER.index(c))):
            if remaining<=0:break
            quotas[category]+=1;remaining-=1
    queues={category:deque(sorted((item for item in items if item["category"]==category),
                                  key=stable_candidate_key)) for category in CATEGORY_ORDER}
    selected=[];allocated={category:0 for category in CATEGORY_ORDER}
    for category in CATEGORY_ORDER:
        take=min(quotas[category],len(queues[category]))
        for _ in range(take):selected.append(queues[category].popleft())
        allocated[category]+=take
    target=sum(quotas.values())
    while len(selected)<target and any(queues.values()):
        progressed=False
        for category in CATEGORY_ORDER:
            if len(selected)>=target:break
            if queues[category]:selected.append(queues[category].popleft());allocated[category]+=1;progressed=True
        if not progressed:break
    excluded=[item for category in CATEGORY_ORDER for item in queues[category]]
    return selected,excluded,{"kind":kind,"initial_quotas":quotas,"allocated":allocated,
                              "available":{category:allocated[category]+len(queues[category]) for category in CATEGORY_ORDER},
                              "unused":target-len(selected)}


def stable_candidate_key(item):
    candidate=item.get("candidate",item)
    return ((item.get("_selection_rank",math.inf) if isinstance(item,dict) else math.inf),
            candidate["observation_end_hours"],candidate["indicator_type"],
            __import__("json").dumps(candidate["predicate"],sort_keys=True,separators=(",",":")),
            candidate["candidate_id"])


def pareto_layers(rows):
    """Exact 3D Pareto peeling in O(n log² n), including equality semantics.

    A row's layer is one plus the maximum layer of its dominators. Sorting by
    descending difference/coverage and ascending delay turns dominance into a
    two-dimensional prefix maximum. Exact metric ties are queried together and
    updated together, so equal points never dominate each other.
    """
    rows=list(rows)
    if not rows:return []
    for row in rows:
        if any(type(row.get(key)) not in (int,float) or not math.isfinite(row[key])
               for key in ("difference_usd","coverage","p90_seconds")):
            raise ValueError("INVALID_PARETO_METRIC")
    coverages=sorted({row["coverage"] for row in rows},reverse=True)
    delays=sorted({row["p90_seconds"] for row in rows})
    coverage_rank={value:index+1 for index,value in enumerate(coverages)}
    delay_rank={value:index+1 for index,value in enumerate(delays)}
    outer=len(coverages);coordinates=[[] for _ in range(outer+1)]
    for row in rows:
        x=coverage_rank[row["coverage"]];y=delay_rank[row["p90_seconds"]]
        while x<=outer:coordinates[x].append(y);x+=x&-x
    coordinates=[sorted(set(values)) for values in coordinates]
    trees=[[ -1]*(len(values)+1) for values in coordinates]
    def update(x,y,value):
        while x<=outer:
            inner=bisect_left(coordinates[x],y)+1
            while inner<len(trees[x]):trees[x][inner]=max(trees[x][inner],value);inner+=inner&-inner
            x+=x&-x
    def query(x,y):
        value=-1
        while x:
            inner=bisect_right(coordinates[x],y)
            while inner:value=max(value,trees[x][inner]);inner-=inner&-inner
            x-=x&-x
        return value
    ordered=sorted(rows,key=lambda row:(-row["difference_usd"],-row["coverage"],row["p90_seconds"],row["candidate_id"]))
    layered=[]
    for metrics,group in groupby(ordered,key=lambda row:(row["difference_usd"],row["coverage"],row["p90_seconds"])):
        group=list(group);x=coverage_rank[metrics[1]];y=delay_rank[metrics[2]];layer=query(x,y)+1
        layered.extend({**row,"pareto_layer":layer} for row in group)
        update(x,y,layer)
    return sorted(layered,key=lambda row:(row["pareto_layer"],-row["difference_usd"],-row["coverage"],row["p90_seconds"],row["candidate_id"]))
