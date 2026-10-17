import pytest
from scipy.stats import ttest_ind
from server.analysis.statistics_v2 import welch_greater,holm_family


def test_welch_matches_raw_sample_reference_and_handles_degenerate():
    a=[1,2,3,10,100];b=[0,1,2,3,4]
    actual=welch_greater(a,b)
    expected=ttest_ind(a,b,equal_var=False,alternative='greater')
    assert actual['testable']
    assert actual['p_value']==pytest.approx(expected.pvalue)
    assert actual['statistic']==pytest.approx(expected.statistic)
    for hits,misses in (([],b),([1],b),([1]*5,b),(a,[0]*5),([None]*5,b),([float('nan')]*5,b)):
        result=welch_greater(hits,misses)
        assert not result['testable'] and result['p_value']==1 and result['reasons']


def test_holm_hand_values_monotonicity_and_full_family_required():
    tests={key:{'testable':True,'p_value':p} for key,p in [('a',.01),('b',.04),('c',.03)]}
    tests['missing']={'testable':False,'p_value':0}
    result=holm_family(tests,['a','b','c','missing'])
    assert [result[k]['adjusted_p_value'] for k in ('a','c','b','missing')]==pytest.approx([.04,.09,.09,1])
    assert result['a']['passed'] and not any(result[k]['passed'] for k in ('b','c','missing'))
    assert result['missing']['family_size']==4
    with pytest.raises(ValueError,match='INCOMPLETE'):
        holm_family(tests,['a','b','c'])
    assert holm_family({},[])=={}


def test_no_signal_and_few_true_signals_in_large_frozen_family():
    null=welch_greater([1,2,3,4],[1,2,3,4])
    assert null['p_value']==pytest.approx(.5)
    tests={str(i):null for i in range(2000)}
    assert not any(t['passed'] for t in holm_family(tests,list(tests)).values())
    tests['0']=welch_greater([100+i%3 for i in range(200)],[i%3 for i in range(200)])
    result=holm_family(tests,list(tests))
    assert [key for key,value in result.items() if value['passed']]==['0']
