from server.analysis.v4_metrics import describe,choose_revenue_controls,Targets
from server.analysis.v4_contract import CHECKPOINTS

class Index:
    def evaluate(self,rule,h):
        times={'a':3600,'b':86400,'c':200000}
        return {u:('triggered',t) if t<h*3600 else ('untriggered',None) for u,t in times.items()}

def test_daily_additions_partition_users_and_revenue():
    t=Targets.__new__(Targets)
    t.users={u:{'revenue':r,'split':'exploration'} for u,r in [('a',1.),('b',2.),('c',3.)]}
    t.early={h:{u:0.5 for u in t.users} for h in CHECKPOINTS}
    rows=describe({'mode':'cumulative'},Index(),t)
    assert rows[0]['delay_seconds']['mean']==3600
    assert rows[1]['delay_seconds']['mean']==45000
    assert [r['groups']['added']['users'] for r in rows]==[1,1,1,0,0,0]
    assert sum(r['groups']['added']['revenue_usd'] or 0 for r in rows)==6
    for row in rows:
        for group in row['groups'].values():
            if group['revenue_usd'] is not None:assert group['before_revenue_usd']+group['remaining_revenue_usd']==group['revenue_usd']

def test_controls_fixed_tie_break_and_missing():
    observations=[{'hours':24,'coverage':.5}]
    controls={'b':[{'hours':24,'coverage':.6}],'a':[{'hours':24,'coverage':.4}]}
    assert choose_revenue_controls({},observations,controls)['24']['rule_id']=='a'
    assert choose_revenue_controls({},observations,{})['24']['rule_id'] is None

def test_snapshot_decrease_shows_exit_not_sticky_hit():
    class Changing:
        def evaluate(self,rule,h):return {'a':('triggered',h*3600) if h in (24,72) else ('untriggered',None)}
    t=Targets.__new__(Targets);t.users={'a':{'revenue':1.,'split':'exploration'}};t.early={h:{'a':.1} for h in CHECKPOINTS}
    rows=describe({'mode':'snapshot'},Changing(),t)
    assert rows[1]['groups']['exited']['users']==1
    assert rows[1]['groups']['triggered']['users']==0
    assert rows[2]['groups']['added']['users']==1
    assert all(p['delay_seconds']['mean'] is None for p in rows)
    assert all(p['transition_kind']=='entered_exited' for p in rows)

def test_control_tie_is_not_decided_by_binary_float_noise():
    controls={'a':[{'hours':24,'coverage':.3}],'b':[{'hours':24,'coverage':.5}]}
    assert choose_revenue_controls({},[{'hours':24,'coverage':.4}],controls)['24']['rule_id']=='a'
