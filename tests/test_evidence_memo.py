import pytest
from server.analysis.evidence_memo import MembershipEvidenceMemo


def test_exact_membership_not_delay_or_order_and_mutation_isolation():
    memo=MembershipEvidenceMemo(10)
    a=memo.key({0:1.0,9:2.0})
    assert a==memo.key({9:999.0,0:3.0})
    assert a!=memo.key({0:1.0,8:2.0})
    value={'metrics':{'reasons':[],'value':0.10000000000000002}}
    memo.put(a,value)
    value['metrics']['reasons'].append('changed')
    first=memo.get(a)
    assert first['metrics']=={'reasons':[],'value':0.10000000000000002}
    first['metrics']['reasons'].append('second mutation')
    assert memo.get(a)['metrics']['reasons']==[]
    assert MembershipEvidenceMemo(10).get(a) is None


def test_lru_byte_bound_and_oversized_bypass():
    memo=MembershipEvidenceMemo(10,max_entries=2,max_bytes=30)
    keys=[memo.key({i:0.0}) for i in range(3)]
    for key in keys[:2]:memo.put(key,{'a':1})
    assert memo.get(keys[0])=={'a':1}
    memo.put(keys[2],{'a':2})
    assert memo.get(keys[1]) is None
    assert memo.bytes<=30 and len(memo.entries)==2
    memo.put(keys[1],{'a':'x'*100})
    assert memo.get(keys[1]) is None and memo.bytes<=30
    disabled=MembershipEvidenceMemo(10,max_entries=0)
    disabled.put(keys[0],{})
    assert disabled.get(keys[0]) is None


@pytest.mark.parametrize('delays',[{10:1},{-1:0},{True:0},{0:None},{0:float('nan')},{0:-1}])
def test_invalid_membership_or_delay_is_not_hidden_by_cache(delays):
    with pytest.raises(ValueError):MembershipEvidenceMemo(10).key(delays)


def test_window_key_preserves_exact_window_and_membership():
    import math
    memo=MembershipEvidenceMemo(10)
    key=memo.key({0:1.0})
    assert memo.window_key(6,key)==memo.window_key(6.0,key)
    assert memo.window_key(6,key)!=memo.window_key(math.nextafter(6,7),key)
    assert memo.window_key(6,key)!=memo.window_key(144,key)
    assert memo.window_key(6,key)!=memo.window_key(6,memo.key({1:1.0}))
    assert memo.window_key(6,key)!=key
    for window in (True,0,-1,169,float('nan'),float('inf')):
        with pytest.raises(ValueError):memo.window_key(window,key)
    with pytest.raises(ValueError):memo.window_key(6,b'')
