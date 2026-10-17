import pytest
from server.analysis.v4_contract import *
from tests.test_v3_contract import candidate

def test_rule_identity_is_independent_of_deadline():
    assert rule_from_candidate(candidate())==rule_from_candidate(candidate(observation_end_hours=144,decision_time_hours=144))
    assert rule_from_candidate(candidate())!=rule_from_candidate(candidate(),mode='rolling')

def test_strict_config_and_rolling_contract():
    validate_config(defaults())
    for change in ({'bootstrap_replicates':100},{'windows_hours':[24]},{'max_candidates':2001}):
        with pytest.raises(ValueError):validate_config({**defaults(),**change})
    with pytest.raises(ValueError):rule_from_candidate(candidate(indicator_type='distinct_completed_levels',predicate={'node':'atom','metric':'distinct_completed_levels','comparator':'gte','threshold':2,'minimum_denominator':0,'scope':{}}),mode='rolling')

def test_threshold_override_rejects_unknown_nonpositive_and_unbounded_sequence():
    for overrides in ({'invented_metric':[1]},{'ad_count':[0]},{'ad_revenue_sum':[-.1]},{'level_fail_to_complete':[4]}):
        with pytest.raises(ValueError):validate_config({**defaults(),'thresholds':overrides})
    validate_config({**defaults(),'thresholds':{'ad_revenue_sum':[.01,.02],'level_fail_to_complete':[1,2]}})
