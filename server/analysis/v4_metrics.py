"""Same-clock descriptive comparisons, never causal revenue increments."""
import json
import math
from collections import defaultdict
from pathlib import Path
from server.analysis.connection import connect
from server.analysis.ingest import file_hash
from server.analysis.v4_contract import CHECKPOINTS

class Targets:
    def __init__(self,normalized,directory):
        directory=Path(directory);normalized=Path(normalized)
        self.manifest=json.loads((directory/'manifest.json').read_text())
        if self.manifest['source_manifest_sha256']!=file_hash(normalized/'manifest.json'):raise ValueError('V4_TARGET_SOURCE')
        self.users={};self.early=defaultdict(dict)
        with connect(config={'memory_limit':'256MB','threads':2}) as c:
            for app,user,installed,revenue,split in c.execute('SELECT app_id,user_id,installed_at,d7_revenue_usd,split FROM read_parquet(?) WHERE is_mature ORDER BY app_id,user_id',[str(directory/'targets.parquet')]).fetchall():
                self.users[(app,user)]={'installed':installed,'revenue':float(revenue) if revenue is not None else None,'split':split}
            events=defaultdict(list)
            for app,user,t,revenue in c.execute("SELECT app_id,user_id,event_time,revenue_usd FROM read_parquet(?) WHERE event_name='ad_impression' ORDER BY app_id,user_id,event_time,event_id",[str(normalized/'events.parquet')]).fetchall():
                events[(app,user)].append((t,revenue))
        for user,record in self.users.items():
            for h in CHECKPOINTS:
                self.early[h][user]=None if record['revenue'] is None else math.fsum(float(v) for t,v in events[user] if v is not None and 0<=(t-record['installed']).total_seconds()<h*3600)
    def scope(self,kind):return {u for u,r in self.users.items() if kind=='all' or r['split']==kind}
    def group(self,users,h,denominator=None):
        users=sorted(users);unknown=sum(self.users[u]['revenue'] is None for u in users)
        total=math.fsum(self.users[u]['revenue'] for u in users) if users and not unknown else None
        before=math.fsum(self.early[h][u] for u in users) if total is not None else None
        denominator_total=None
        if denominator is not None:
            values=[self.users[u]['revenue'] for u in denominator]
            if values and all(v is not None for v in values):denominator_total=math.fsum(values)
        return {'users':len(users),'unknown_revenue_users':unknown,'revenue_usd':total,'arpu_usd':total/len(users) if total is not None else None,
                'before_revenue_usd':before,'remaining_revenue_usd':total-before if total is not None else None,
                'remaining_arpu_usd':(total-before)/len(users) if total is not None else None,
                'share_of_total_d7':total/denominator_total if total is not None and denominator_total else None}

def describe(rule,index,targets,kind='all'):
    users=targets.scope(kind);rows=[];previous=set();previous_known=set();first=set();ever=set();baseline_known=set()
    for h in CHECKPOINTS:
        statuses=index.evaluate(rule,h)
        hit={u for u in users if statuses.get(u,('unknown',None))[0]=='triggered'}
        miss={u for u in users if statuses.get(u,('unknown',None))[0]=='untriggered'}
        unknown=users-hit-miss
        if h==24:
            first=hit.copy();baseline_known=hit|miss
        applicable=bool(hit or miss)
        if rule['mode']=='snapshot':
            added=hit-previous;exited=previous & miss
        else:
            # Exact first-hit time partitions players even if a prior snapshot was unavailable.
            added={u for u in hit if statuses[u][1] is not None and (h-24)*3600<=statuses[u][1]<h*3600}
            # At 24h the rolling warmup decision is observable, unlike endpoint events.
            if h==24 and rule['mode']=='rolling':added|={u for u in hit if statuses[u][1]==86400}
            if h==48 and rule['mode']=='rolling':added-=previous
            exited=set()
        groups={name:targets.group(group,h,users) for name,group in [('triggered',hit),('untriggered',miss),('unknown',unknown),('added',added),('added_since_24h',(hit-first)&baseline_known),('exited',exited),('all',users)]}
        baseline_applicable=bool(baseline_known)
        if not baseline_applicable:
            groups['added_since_24h']={key:None for key in groups['added_since_24h']}
        a=groups['triggered']['arpu_usd'];b=groups['untriggered']['arpu_usd']
        delays=[statuses[u][1] for u in sorted(hit) if statuses[u][1] is not None] if rule['mode']!='snapshot' else []
        delays.sort()
        def quantile(q):
            if not delays:return None
            p=(len(delays)-1)*q;l=int(p);r=min(l+1,len(delays)-1)
            return delays[l]+(delays[r]-delays[l])*(p-l)
        rows.append({'hours':h,'applicable':applicable,'baseline_24h_applicable':baseline_applicable,'baseline_24h_unknown_users':len(users-baseline_known),'groups':groups,'coverage':len(hit)/(len(hit)+len(miss)) if hit or miss else None,
                     'difference_usd':a-b if a is not None and b is not None else None,
                     'delay_seconds':{'mean':math.fsum(delays)/len(delays) if delays else None,'median':quantile(.5),'p90':quantile(.9),'known_users':len(delays),'unknown_users':len(hit)-len(delays)},
                     'transition_kind':'entered_exited' if rule['mode']=='snapshot' else 'first_reached',
                     'previous_unknown_now_triggered':len(hit-previous_known) if h>24 else 0})
        previous=hit;previous_known=hit|miss;ever|=hit
    return rows

def choose_revenue_controls(rule,observations,controls):
    """controls contains exploration observations only; deterministic frozen pairing."""
    pairs={}
    for row in observations:
        h=row['hours'];coverage=row['coverage']
        choices=[(abs(point['coverage']-coverage),identity,point['coverage']) for identity,points in controls.items()
                 for point in points if point['hours']==h and point['coverage'] is not None and coverage is not None]
        if choices:
            nearest=min(c[0] for c in choices)
            distance,identity,actual=min((c for c in choices if math.isclose(c[0],nearest,rel_tol=0,abs_tol=1e-12)),key=lambda c:c[1])
            pairs[str(h)]={'rule_id':identity,'exploration_coverage':actual,'coverage_gap':distance}
        else:pairs[str(h)]={'rule_id':None,'reason':'RELIABLE_REVENUE_CONTROL_UNAVAILABLE'}
    return pairs

def compact_evidence(row):
    """Bounded aggregate projection for Agent and catalog; values are copied, not recomputed."""
    def point(p):
        g=p['groups']
        return {'hours':p['hours'],'applicable':p['applicable'],'baseline_24h_applicable':p.get('baseline_24h_applicable'),'coverage':p['coverage'],
                'users':g['triggered']['users'],'cohort_users':g['all']['users'],'baseline_24h_unknown_users':p.get('baseline_24h_unknown_users'),'unknown_users':g['unknown']['users'],
                'd7_arpu':g['triggered']['arpu_usd'],'remaining_arpu':g['triggered']['remaining_arpu_usd'],
                'added_users':g['added']['users'],'added_d7_arpu':g['added']['arpu_usd'],
                'added_d7_revenue':g['added']['revenue_usd'],'added_d7_share':g['added']['share_of_total_d7'],
                'since_24h_users':g['added_since_24h']['users'],'exited_users':g['exited']['users'],
                'delay_seconds':p['delay_seconds']}
    result={**{scope:[point(p) for p in row[scope]] for scope in ('observation','exploration','holdout') if scope in row},
            'controls':{h:{'rule_id':c['rule_id'],'threshold_usd':c['rule']['predicate']['threshold'],**{scope:{k:v for k,v in point(c[scope]).items() if k in ('coverage','users','d7_arpu','remaining_arpu')} for scope in ('observation','exploration','holdout') if scope in c}} for h,c in row['controls'].items()},
            'inference':[{k:t.get(k) for k in ('hours','question','claim_allowed','testable','difference_usd','adjusted_p_value','reasons')} for t in row['inference']],
            'existing':row['existing']}
    if 'cumulative_comparison' in row:
        result['cumulative_comparison']={scope:[{k:v for k,v in point(p).items() if k in ('hours','coverage','users','d7_arpu')} for p in row['cumulative_comparison'][scope]] for scope in ('observation','exploration','holdout') if scope in row['cumulative_comparison']}
    return result
