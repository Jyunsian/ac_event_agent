"""Auxiliary within-source comparisons; never a pooled selection/status gate."""
from collections import defaultdict
from statistics import fmean


def summarize_sources(rows, min_group_users=20):
    grouped=defaultdict(list)
    for row in rows:
        source=row.get('acquisition_source')
        grouped[source if source else 'unknown'].append(row)
    output=[]
    for source, users in sorted(grouped.items()):
        hits=[r['revenue_usd'] for r in users if r['triggered']]
        misses=[r['revenue_usd'] for r in users if not r['triggered']]
        reasons=[]
        if min(len(hits),len(misses))<min_group_users: reasons.append('INSUFFICIENT_SOURCE_GROUP_USERS')
        if any(v is None for v in hits+misses): reasons.append('UNKNOWN_SOURCE_REVENUE')
        a=fmean(hits) if not reasons else None
        b=fmean(misses) if not reasons else None
        difference=a-b if a is not None and b is not None else None
        output.append({'acquisition_source':source,'triggered_users':len(hits),
                       'untriggered_users':len(misses),'triggered_arpu_usd':a,
                       'untriggered_arpu_usd':b,'difference_usd':difference,
                       'direction':None if difference is None else 'positive' if difference>0 else 'negative' if difference<0 else 'equal',
                       'reasons':reasons,'interpretation':'auxiliary_not_confounding_adjusted'})
    return output
