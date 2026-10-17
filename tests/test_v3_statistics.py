from server.analysis.bootstrap import bootstrap_differences
from server.analysis.statistics_v2 import holm_family,welch_greater


def test_no_signal_true_signal_heavy_tail_and_degenerate_family():
    no_signal=welch_greater([1,2,3,4],[1,2,3,4])
    signal=welch_greater([10,11,12,50],[1,2,3,4])
    degenerate=welch_greater([1,1,1],[0,1,2])
    assert no_signal["testable"] and no_signal["p_value"]==.5
    assert signal["testable"] and signal["p_value"]<.1
    assert degenerate=={"test":"welch_one_sided_greater","testable":False,"p_value":1.0,"statistic":None,"reasons":["ZERO_VARIANCE"]}
    family=holm_family({"a":signal,"b":no_signal,"c":degenerate},["a","b","c"])
    assert all(row["family_size"]==3 for row in family.values()) and family["c"]["p_value"]==1


def test_user_bootstrap_is_seeded_and_exactly_1000_draws():
    first,_=bootstrap_differences([1,2,100],[0,1,2],seed=42,replicates=1000)
    second,_=bootstrap_differences([1,2,100],[0,1,2],seed=42,replicates=1000)
    assert len(first)==1000 and first==second and max(first)>30
