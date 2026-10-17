"""Frozen-family inference, distinct from descriptive bootstrap intervals."""
import math
from statistics import fmean, stdev

from scipy.stats import ttest_ind_from_stats


def welch_greater(hits, misses):
    result={'test':'welch_one_sided_greater','testable':False,'p_value':1.0,
            'statistic':None,'reasons':[]}
    if len(hits)<2 or len(misses)<2:
        result['reasons']=['INSUFFICIENT_TEST_USERS'];return result
    if any(type(x) not in (int,float) or not math.isfinite(x) or x<0 for x in (*hits,*misses)):
        result['reasons']=['UNKNOWN_OR_INVALID_TEST_REVENUE'];return result
    a,b=stdev(hits),stdev(misses)
    if a==0 or b==0:
        result['reasons']=['ZERO_VARIANCE'];return result
    test=ttest_ind_from_stats(fmean(hits),a,len(hits),fmean(misses),b,len(misses),
                             equal_var=False,alternative='greater')
    if not math.isfinite(test.statistic) or not math.isfinite(test.pvalue):
        result['reasons']=['NONFINITE_TEST_RESULT'];return result
    return {**result,'testable':True,'p_value':float(test.pvalue),'statistic':float(test.statistic)}


def holm_family(tests, frozen_ids, *, alpha=.05):
    """Require exactly the frozen family, including untestable entries (p=1)."""
    if len(set(frozen_ids))!=len(frozen_ids) or set(tests)!=set(frozen_ids):
        raise ValueError('INCOMPLETE_FROZEN_TEST_FAMILY')
    if not 0<alpha<1: raise ValueError('INVALID_ALPHA')
    pvalues={}
    for identity in frozen_ids:
        test=tests[identity]
        p=test['p_value'] if test['testable'] else 1.0
        if type(p) not in (int,float) or not math.isfinite(p) or not 0<=p<=1:
            raise ValueError('INVALID_P_VALUE')
        pvalues[identity]=p
    ordered=sorted(frozen_ids,key=lambda identity:(pvalues[identity],identity))
    adjusted={}; running=0.0; size=len(ordered)
    for rank,identity in enumerate(ordered):
        running=max(running,min(1.0,(size-rank)*pvalues[identity]))
        adjusted[identity]={**tests[identity],'p_value':pvalues[identity],
                            'adjusted_p_value':running,'method':'holm','family_size':size,
                            'alpha':alpha,'passed':bool(tests[identity]['testable'] and running<=alpha)}
    return {identity:adjusted[identity] for identity in frozen_ids}
