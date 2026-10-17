"""Bounded exploration-only discovery and whole-rule comparison allocation."""
import json
import math
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from server.analysis.v3_contract import make_candidate,MINIMUM_DENOMINATORS,SNAPSHOT_METRICS,SEQUENCE_RULES,ALLOWED_CROSS_CATEGORY_PAIRS,CATEGORY_BUDGETS,digest
from server.analysis.casual_search import DEPENDENCIES,SEQUENCE_DEPENDENCIES
from server.analysis.v3_policy import finite_thresholds,CATEGORY_ORDER
from server.analysis.v4_contract import *
from server.analysis.v4_features import FeatureIndex,write_json
from server.analysis.v4_metrics import Targets,choose_revenue_controls
from server.analysis.ingest import file_hash
import numpy as np


def generated_rule(category,indicator_type,predicate,dependencies,mode='cumulative'):
    rule={'analysis_version':ANALYSIS_VERSION,'category':category,'indicator_type':indicator_type,
          'predicate':predicate,'dependencies':sorted(set(dependencies)),'mode':mode,
          'rolling_hours':24 if mode=='rolling' else None}
    rule['rule_id']=digest(rule)
    return validate_rule(rule)


def atom_rule(metric,scope,threshold,comparator='gte',mode=None):
    from server.analysis.v3_contract import METRIC_CATEGORIES
    predicate={'node':'atom','metric':metric,'scope':scope,'threshold':threshold,'comparator':comparator,'minimum_denominator':MINIMUM_DENOMINATORS.get(metric,0)}
    snapshot=metric in SNAPSHOT_METRICS or comparator=='lte'
    return generated_rule(METRIC_CATEGORIES[metric],metric,predicate,DEPENDENCIES[metric],mode or ('snapshot' if snapshot else 'cumulative'))


def brief(rule,index,targets):
    import hashlib
    if not hasattr(index,'search_revenue'):
        index.search_revenue=np.array([targets.users[u]['revenue'] if targets.users[u]['revenue'] is not None else np.nan for u in sorted(index.users)])
    values=index.search_revenue;rows=[]
    for h in CHECKPOINTS:
        statuses,delays=index.evaluate_array(rule,h);hits=statuses==1;misses=statuses==0
        a=float(values[hits].mean()) if hits.any() and np.isfinite(values[hits]).all() else None
        b=float(values[misses].mean()) if misses.any() and np.isfinite(values[misses]).all() else None
        nh=int(hits.sum());nm=int(misses.sum());valid=delays[hits];valid=valid[np.isfinite(valid)]
        rows.append({'hours':h,'coverage':nh/(nh+nm) if nh+nm else None,
                     'difference_usd':a-b if a is not None and b is not None else None,
                     'triggered_users':nh,'untriggered_users':nm,'unknown_users':len(values)-nh-nm,
                     'triggered_arpu_usd':a,'untriggered_arpu_usd':b,
                     'p90_seconds':float(np.quantile(valid,.9)) if len(valid) else None,
                     'membership_sha256':hashlib.sha256(statuses.tobytes()).hexdigest()})
    return rows


def generate_rules(index,config):
    grouped=defaultdict(list);seen=set()
    for ((metric,scope_json),h),records in index.snapshots.items():
        scope=json.loads(scope_json);scope={} if scope=='all' else scope
        if metric=='return_in_interval' and h!=scope.get('end_hours'):continue
        values=[v for v,d,enabled in records.values() if enabled and v is not None and v>0]
        if not values:continue
        quantiles=np.quantile(values,np.arange(.05,1,.05)).tolist()
        thresholds=config.get('thresholds',{}).get(metric,finite_thresholds(metric,quantiles,min(values),max(values)))
        if metric in SEQUENCE_RULES:thresholds=[int(v) for v in config.get('thresholds',{}).get(metric,[1,2,3])]
        for threshold in thresholds:
            identity=(metric,scope_json,threshold)
            if identity in seen:continue
            seen.add(identity)
            if metric in SEQUENCE_RULES:
                p={'node':'sequence','template':metric,'max_gap_seconds':scope['max_gap_seconds'],'repeats':threshold,
                   'matching':'non_overlapping','constraints':list(SEQUENCE_RULES[metric])}
                rule=generated_rule('sequence',metric,p,SEQUENCE_DEPENDENCIES[metric])
                grouped[rule['category']].append(rule)
            else:
                for comparator in (('gte','lte') if metric in SNAPSHOT_METRICS else ('gte',)):
                    rule=atom_rule(metric,scope,threshold,comparator);grouped[rule['category']].append(rule)
                    if metric in ROLLING_METRICS:grouped[rule['category']].append(atom_rule(metric,scope,threshold,mode='rolling'))
    return {category:{r['rule_id']:r for r in rules} for category,rules in grouped.items()}


def category_take(groups,limit,unit_cost=None):
    """V3 quota proportions, complete bundles only, deterministic round-robin refill."""
    allocations={c:[] for c in CATEGORY_ORDER};used=0
    quotas={c:math.floor(CATEGORY_BUDGETS[c][1]*limit/2000) for c in CATEGORY_ORDER}
    queues={c:list(groups.get(c,[])) for c in CATEGORY_ORDER}
    cost=unit_cost or (lambda _:1)
    for c in CATEGORY_ORDER:
        spent=0
        while queues[c] and spent+cost(queues[c][0])<=quotas[c]:
            row=queues[c].pop(0);allocations[c].append(row);spent+=cost(row);used+=cost(row)
    while any(queues.values()):
        progress=False
        for c in CATEGORY_ORDER:
            fitting=next((i for i,row in enumerate(queues[c]) if used+cost(row)<=limit),None)
            if fitting is not None:
                row=queues[c].pop(fitting);allocations[c].append(row);used+=cost(row);progress=True
        if not progress:break
    return [r for c in CATEGORY_ORDER for r in allocations[c]],used


def discover(feature_dir,normalized,target_dir,config,destination):
    validate_config(config);index=FeatureIndex(feature_dir)
    if (index.manifest.get('scope') or {}).get('kind')!='exploration':raise ValueError('V4_EXPLORATION_REQUIRED')
    targets=Targets(normalized,target_dir)
    if index.users-targets.scope('exploration'):raise ValueError('V4_EXPLORATION_USERS_MISMATCH')
    groups=generate_rules(index,config);pool={};evaluations={};excluded=[]
    # Reserve cross-category share; each parent is chosen on exploration at a particular clock.
    atomic_limit=config['max_discovery_candidates']-math.floor(config['max_discovery_candidates']*.2)
    selected,_=category_take({c:sorted(v.values(),key=lambda r:r['rule_id']) for c,v in groups.items()},atomic_limit)
    for rule in selected:pool[rule['rule_id']]=rule;evaluations[rule['rule_id']]=brief(rule,index,targets)
    parents={};parent_usage=defaultdict(int)
    for c in CATEGORY_ORDER:
        for h in CHECKPOINTS:
            choices=[r for r in selected if r['category']==c and r['mode']!='rolling' and r['predicate']['node']=='atom']
            def key(r):
                p=next(p for p in evaluations[r['rule_id']] if p['hours']==h)
                return (-(p['difference_usd'] if p['difference_usd'] is not None else -math.inf),r['rule_id'])
            # Preserve V3's bounded parent count and favor useful, different populations.
            ordered_parents=sorted(choices,key=lambda r:(parent_usage[(c,r['rule_id'])],key(r)));diverse=[];seen=set()
            for parent in ordered_parents:
                point=next(p for p in evaluations[parent['rule_id']] if p['hours']==h)
                if point['coverage'] is None or not .3<=point['coverage']<=.7:continue
                signature=point['membership_sha256']
                if signature not in seen:diverse.append(parent);seen.add(signature)
                if len(diverse)==20:break
            for parent in ordered_parents:
                if len(diverse)>=20:break
                if parent not in diverse:diverse.append(parent)
            parents[(c,h)]=diverse
            for r in diverse:parent_usage[(c,r['rule_id'])]+=1
    crosses={};seen_cross=set()
    for h in CHECKPOINTS:
        for a,b in combinations(CATEGORY_ORDER,2):
            if frozenset((a,b)) not in ALLOWED_CROSS_CATEGORY_PAIRS:continue
            for left in parents[(a,h)]:
                for right in parents[(b,h)]:
                    for op in ('and','or'):
                        p={'node':'boolean','operator':op,'clauses':[left['predicate'],right['predicate']]}
                        snap=left['mode']=='snapshot' or right['mode']=='snapshot'
                        identity=digest(p)
                        if identity in seen_cross:continue
                        seen_cross.add(identity)
                        r=generated_rule('cross_category','cross_category',p,left['dependencies']+right['dependencies'],'snapshot' if snap else 'cumulative')
                        crosses[r['rule_id']]=r
    groups['cross_category']=crosses
    # Stable round-robin fills unused category capacity; all discarded rule IDs are recorded.
    selected,_=category_take({c:sorted(v.values(),key=lambda r:r['rule_id']) for c,v in groups.items()},config['max_discovery_candidates'])
    pool={r['rule_id']:r for r in selected}
    for r in selected:
        if r['rule_id'] not in evaluations:evaluations[r['rule_id']]=brief(r,index,targets)
    existing={}
    for item in config.get('existing_rules',[]):
        r=item['rule'];existing.setdefault(r['rule_id'],[]).append({'name':item['name'],'deadline_hours':item['deadline_hours']})
        if r['rule_id'] not in pool:
            if len(pool)>=config['max_discovery_candidates']:
                victim=next((key for key in reversed(pool) if key not in existing),None)
                if victim is None:raise ValueError('V4_EXISTING_RULES_EXCEED_DISCOVERY_BUDGET')
                del pool[victim]
            pool[r['rule_id']]=r;evaluations[r['rule_id']]=brief(r,index,targets)
    for c,g in groups.items():
        for identity in g:
            if identity not in pool:excluded.append({'rule_id':identity,'category':c,'reason':'DISCOVERY_BUDGET_NOT_EVALUATED','evaluation_status':'not_evaluated'})
    controls={r['rule_id']:evaluations[r['rule_id']] for r in pool.values() if r['mode']=='cumulative' and r['predicate'].get('metric')=='ad_revenue_sum' and r['predicate']['scope']=={'ad_format':'all'}}
    candidates=[]
    for r in pool.values():
        rid=r['rule_id'];pairs=choose_revenue_controls(r,evaluations[rid],controls)
        units=[]
        for h in CHECKPOINTS:
            point=next(p for p in evaluations[rid] if p['hours']==h)
            if point['coverage'] is None:continue
            units.append({'rule_id':rid,'hours':h,'question':'d7_association','control_id':None})
            control=pairs[str(h)]['rule_id']
            if control is not None:units.append({'rule_id':rid,'hours':h,'question':'revenue_control','control_id':control})
        candidates.append({'rule':r,'observations':evaluations[rid],'controls':pairs,'units':units,'existing':existing.get(rid,[])})
    # Per-clock Pareto ranks; never rank 144h revenue directly against 24h revenue.
    from server.analysis.v3_policy import pareto_layers
    ranks=defaultdict(list)
    for category in CATEGORY_ORDER:
        for h in CHECKPOINTS:
            points=[]
            for row in candidates:
                if row['rule']['category']!=category:continue
                p=next(p for p in row['observations'] if p['hours']==h)
                if all(p[k] is not None for k in ('difference_usd','coverage','p90_seconds')):
                    points.append({**p,'candidate_id':row['rule']['rule_id']})
            for p in pareto_layers(points):ranks[p['candidate_id']].append(p['pareto_layer'])
    ordered=defaultdict(list)
    for row in candidates:
        if row['units']:ordered[row['rule']['category']].append(row)
    for c in ordered:ordered[c].sort(key=lambda row:(not bool(row['existing']),min(ranks[row['rule']['rule_id']],default=math.inf),row['rule']['rule_id']))
    chosen,used=category_take(ordered,config['max_candidates'],lambda row:len(row['units']))
    ids=[r['rule']['rule_id'] for r in chosen];priority=[];seen_memberships=set()
    def add_priority(row):
        rid=row['rule']['rule_id'];signature=tuple(p['membership_sha256'] for p in row['observations'])
        if len(priority)<config['max_finalists'] and rid not in priority and (row['existing'] or signature not in seen_memberships):
            priority.append(rid);seen_memberships.add(signature)
    for row in chosen:
        if row['existing']:add_priority(row)
    for c in CATEGORY_ORDER:
        for row in chosen:
            if row['rule']['category']==c and tuple(p['membership_sha256'] for p in row['observations']) not in seen_memberships:
                add_priority(row);break
    for row in chosen:add_priority(row)
    units=[]
    for row in chosen:
        for unit in row['units']:units.append({**unit,'test_id':digest(unit)})
    root=Path(destination);root.mkdir(parents=True,exist_ok=False)
    control_rules={identity:pool[identity] for identity in controls}
    frozen={'schema_version':'4.0','analysis_version':ANALYSIS_VERSION,'policy_identity':POLICY_IDENTITY,
            'split_id':targets.manifest['split_id'],'feature_sha256':file_hash(Path(feature_dir)/'manifest.json'),
            'config':config,'rules':[r['rule'] for r in chosen],'rule_ids':ids,'candidate_ids':ids,'priority_ids':priority,
            'family_size':len(units),'units':units,'control_rules':control_rules,
            'comparisons':{r['rule']['rule_id']:r['controls'] for r in chosen},'existing_rules':existing}
    write_json(root/'frozen.json',frozen)
    output={'schema_version':'4.0','analysis_version':ANALYSIS_VERSION,'stage':'discovery_v4','discovery_count':len(pool),
            'enumerated':sum(len(g) for g in groups.values()),'unique_before_cap':sum(len(g) for g in groups.values()),'searched_windows':list(CHECKPOINTS),
            'parent_policy':'at_most_20_per_category_clock_exploration_coverage_and_population_diversity_with_reuse_balance',
            'parent_ids':{f'{c}:{h}':[r['rule_id'] for r in rows] for (c,h),rows in parents.items()},
            'category_counts':{c:sum(r['category']==c for r in pool.values()) for c in CATEGORY_ORDER},'supported_modes':['cumulative','snapshot','rolling_24h'],
            'formal_comparison_count':used,'validated_rule_count':len(chosen),'frozen_sha256':file_hash(root/'frozen.json'),
            'priority_ids':priority,'search_log':excluded+[{'rule_id':r['rule']['rule_id'],'reason':'FULL_TIME_BUNDLE_OUTSIDE_VALIDATION_BUDGET','evaluation_status':'exploration_only'} for r in candidates if r['rule']['rule_id'] not in ids],
            'rules':[{**r,'validation_selected':r['rule']['rule_id'] in ids} for r in candidates]}
    write_json(root/'manifest.json',output)
    return output


def load_frozen(directory,sha):
    path=Path(directory)/'frozen.json'
    if file_hash(path)!=sha:raise ValueError('V4_FROZEN_CHECKSUM')
    value=json.loads(path.read_text())
    if value['analysis_version']!=ANALYSIS_VERSION or value['policy_identity']!=POLICY_IDENTITY:raise ValueError('V4_FREEZE_VERSION')
    validate_config(value['config'])
    if value['family_size']!=len(value['units']) or len(value['units'])>value['config']['max_candidates']:raise ValueError('V4_TEST_BUDGET')
    if len({u['test_id'] for u in value['units']})!=len(value['units']):raise ValueError('V4_DUPLICATE_TEST')
    for rule in value['rules']:validate_rule(rule)
    return value
