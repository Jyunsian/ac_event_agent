"""All frozen tests corrected together; observations never inherit holdout CIs."""
import json
import math
from pathlib import Path
import numpy as np
from scipy.stats import t as student_t
from server.analysis.v4_features import FeatureIndex,write_json
from server.analysis.v4_metrics import Targets,describe
from server.analysis.v4_search import load_frozen
from server.analysis.v4_contract import ANALYSIS_VERSION,CHECKPOINTS
from server.analysis.v3_contract import digest
from server.analysis.statistics_v2 import holm_family,welch_greater
from server.analysis.ingest import file_hash


def test_comparison(values,a,b,*,paired,minimum,seed):
    values=np.asarray(values,dtype=float);a=np.asarray(a,dtype=bool);b=np.asarray(b,dtype=bool)
    base={'test':'paired_user_influence_t' if paired else 'welch_one_sided_greater','testable':False,'p_value':1.,'statistic':None,'reasons':[],'bootstrap':None,'difference_usd':None}
    if min(a.sum(),b.sum())<minimum or len(values)<2:return {**base,'reasons':['INSUFFICIENT_GROUP_USERS']}
    if not np.isfinite(values).all() or (values<0).any():return {**base,'reasons':['UNKNOWN_REVENUE']}
    observed=float(values[a].mean()-values[b].mean());base['difference_usd']=observed
    if paired:
        influence=a*(values-values[a].mean())/a.mean()-b*(values-values[b].mean())/b.mean()
        se=float(influence.std(ddof=1)/math.sqrt(len(values)))
        if se<=0:return {**base,'reasons':['IDENTICAL_OR_ZERO_VARIANCE_GROUPS']}
        stat=observed/se
        base.update(testable=True,p_value=float(student_t.sf(stat,len(values)-1)),statistic=stat)
    else:base.update(welch_greater(values[a].tolist(),values[b].tolist()))
    rng=np.random.default_rng(seed);draws=[]
    # Same user indices for both groups, preserving overlap for the control test.
    for _ in range(1000):
        idx=rng.integers(0,len(values),len(values))
        aa=a[idx];bb=b[idx]
        if not aa.any() or not bb.any():continue
        vv=values[idx];draws.append(float(vv[aa].mean()-vv[bb].mean()))
    base['bootstrap']={'method':'paired_user_percentile' if paired else 'user_percentile','replicates':1000,'valid_replicates':len(draws),
                       'difference_ci95_usd':np.quantile(draws,[.025,.975]).tolist() if len(draws)>=950 else None,'scope':'holdout'}
    if len(draws)<950:base.update(testable=False,p_value=1.,reasons=['INSUFFICIENT_VALID_BOOTSTRAP_REPLICATES'])
    return base

# Prevent pytest from treating the public statistical helper as a test fixture.
test_comparison.__test__=False


def validate(normalized,feature_dir,target_dir,frozen_dir,sha,destination,policy=None,batch_store=None):
    frozen=load_frozen(frozen_dir,sha);index=FeatureIndex(feature_dir);targets=Targets(normalized,target_dir)
    if index.manifest.get('scope') is not None or frozen['split_id']!=targets.manifest['split_id']:raise ValueError('V4_VALIDATION_SCOPE')
    root=Path(destination);root.mkdir(parents=True,exist_ok=False)
    results=[];tests={};pending=[];cached=None;control_descriptions={}
    all_rules={r['rule_id']:r for r in frozen['rules']}|frozen['control_rules']
    holdout=sorted(targets.scope('holdout'));minimum=frozen['config']['min_group_users']
    for pos,rule in enumerate(frozen['rules']):
        rid=rule['rule_id']
        if batch_store is not None and pos%batch_store.size==0:cached=batch_store.load(pos//batch_store.size)
        if cached is not None:
            entry=cached[pos%batch_store.size]
            if entry['row']['candidate_id']!=rid:raise ValueError('V4_BATCH_RULE_MISMATCH')
            row=entry['row'];rule_tests=entry['tests']
        else:
            row={'candidate_id':rid,'rule':rule,'origin':index.manifest['export_metadata']['origin'],'observation':describe(rule,index,targets,'all'),
                 'exploration':describe(rule,index,targets,'exploration'),'holdout':describe(rule,index,targets,'holdout'),'evidence_status':'pending_family_correction','reasons':[],
                 'controls':{},'existing':frozen['existing_rules'].get(rid,[])}
            if rule['mode']=='rolling':
                cumulative={**rule,'mode':'cumulative','rolling_hours':None}
                cumulative['rule_id']=digest({k:v for k,v in cumulative.items() if k!='rule_id'})
                row['cumulative_comparison']={'rule':cumulative,'observation':describe(cumulative,index,targets,'all'),
                                              'exploration':describe(cumulative,index,targets,'exploration'),'holdout':describe(cumulative,index,targets,'holdout'),'interpretation':'descriptive_only'}
            rule_tests={}
            for unit in (u for u in frozen['units'] if u['rule_id']==rid):
                h=unit['hours'];statuses=index.evaluate(rule,h);control_id=unit['control_id']
                other=index.evaluate(all_rules[control_id],h) if control_id else None
                common=[u for u in holdout if statuses.get(u,('unknown',None))[0]!='unknown' and (other is None or other.get(u,('unknown',None))[0]!='unknown')]
                values=[targets.users[u]['revenue'] if targets.users[u]['revenue'] is not None else math.nan for u in common]
                a=[statuses[u][0]=='triggered' for u in common]
                b=[other[u][0]=='triggered' if other is not None else statuses[u][0]=='untriggered' for u in common]
                test=test_comparison(values,a,b,paired=other is not None,minimum=minimum,seed=frozen['config']['seed'])
                test.update(rule_id=rid,hours=h,question=unit['question'],control_id=control_id,common_users=len(common),candidate_users=sum(a),comparison_users=sum(b))
                rule_tests[unit['test_id']]=test
                if control_id:
                    if control_id not in control_descriptions:
                        control_descriptions[control_id]={scope:describe(all_rules[control_id],index,targets,kind) for scope,kind in [('observation','all'),('exploration','exploration'),('holdout','holdout')]}
                    control_all=next(r for r in control_descriptions[control_id]['observation'] if r['hours']==h)
                    control_holdout=next(r for r in control_descriptions[control_id]['holdout'] if r['hours']==h)
                    row['controls'][str(h)]={'rule_id':control_id,'rule':all_rules[control_id],
                        'observation':control_all,'holdout':control_holdout,'exploration':next(p for p in control_descriptions[control_id]['exploration'] if p['hours']==h),'pairing':frozen['comparisons'][rid][str(h)]}
            if batch_store is not None:
                pending.append({'row':row,'tests':rule_tests})
                if len(pending)==batch_store.size or pos==len(frozen['rules'])-1:
                    batch_store.save(pos//batch_store.size,pending);pending=[]
        results.append(row);tests.update(rule_tests)
    ids=[u['test_id'] for u in frozen['units']]
    corrected=holm_family(tests,ids)
    eligible=bool(holdout) and (policy is None or policy.get('eligible',False))
    for row in results:
        row['inference']=[{'test_id':tid,**result} for tid,result in corrected.items() if result['rule_id']==row['candidate_id']]
        if not eligible:
            row['evidence_status']='exploratory';row['reasons']=list((policy or {}).get('reasons',[]))+([] if holdout else ['NO_HOLDOUT'])
        elif any(r['passed'] for r in row['inference']):row['evidence_status']='historically_supported'
        elif not any(r['testable'] for r in row['inference']):row['evidence_status']='insufficient_data'
        else:row['evidence_status']='not_supported'
        for test in row['inference']:test['claim_allowed']=eligible and test['passed']
        write_json(root/'details'/f"{row['candidate_id']}.json",row)
    summary={'schema_version':'4.0','analysis_version':ANALYSIS_VERSION,'stage':'validation_v4','frozen_sha256':sha,
             'family_size':len(ids),'family_correction_complete':True,'priority_ids':frozen['priority_ids'],
             'rule_ids':frozen['rule_ids'],'synthetic':index.manifest['export_metadata']['synthetic'],
             'targets':targets.manifest,'quality':index.quality,'validation_policy':policy,
             'results':[{'candidate_id':r['candidate_id'],'evidence_status':r['evidence_status'],'reasons':r['reasons'],
                         'path':f"details/{r['candidate_id']}.json",'sha256':file_hash(root/'details'/f"{r['candidate_id']}.json")} for r in results]}
    load_frozen(frozen_dir,sha)
    write_json(root/'manifest.json',summary)
    return summary
