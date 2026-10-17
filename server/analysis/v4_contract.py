"""Independent V4 rules: identity excludes reporting deadlines, never semantics."""
import copy
import json
import math
from pathlib import Path
from jsonschema import Draft202012Validator
from server.analysis.v3_contract import digest, make_candidate, SNAPSHOT_METRICS

ANALYSIS_VERSION = '4.0-time-aware'
CHECKPOINTS = (24,48,72,96,120,144)
ROLLING_METRICS = {'ad_count','ad_revenue_sum','session_count','level_start_count','level_complete_count','level_fail_count'}
POLICY = {'calculation_revision':'2026-09-17-time-evidence-2','version':ANALYSIS_VERSION,'checkpoints':CHECKPOINTS,'rolling_hours':24,
          'rolling_revenue':'event_time_in_window_and_available_by_decision','rolling_interval':'[t-24h,t)','warmup_hours':24,'deadline_exclusive':144,
          'replicates':1000,'max_discovery':20000,'max_tests':2000}
POLICY_IDENTITY = digest(POLICY)

class V4ContractError(ValueError): pass

def validate_rule(rule):
    if set(rule) != {'rule_id','analysis_version','category','indicator_type','mode','predicate','dependencies','rolling_hours'}:
        raise V4ContractError('INVALID_V4_RULE_FIELDS')
    if rule['analysis_version'] != ANALYSIS_VERSION or rule['mode'] not in ('cumulative','snapshot','rolling'):
        raise V4ContractError('INVALID_V4_RULE_VERSION_OR_MODE')
    if rule['rule_id'] != digest({k:v for k,v in rule.items() if k!='rule_id'}):
        raise V4ContractError('V4_RULE_IDENTITY_MISMATCH')
    predicate=rule['predicate']
    if rule['mode']=='rolling':
        if predicate.get('node')!='atom' or predicate.get('metric') not in ROLLING_METRICS or predicate.get('comparator')!='gte' or rule['rolling_hours']!=24:
            raise V4ContractError('INVALID_V4_ROLLING_RULE')
    elif rule['rolling_hours'] is not None: raise V4ContractError('UNEXPECTED_ROLLING_HOURS')
    clauses=predicate.get('clauses',[predicate])
    snapshot=any(c.get('metric') in SNAPSHOT_METRICS or c.get('comparator')=='lte' for c in clauses)
    if rule['mode']!='rolling' and (rule['mode']=='snapshot')!=snapshot:
        raise V4ContractError('INVALID_V4_SNAPSHOT_MODE')
    try:
        make_candidate(category=rule['category'],indicator_type=rule['indicator_type'],
            observation_start_hours=0,observation_end_hours=144,decision_time_hours=144,
            trigger_mode='checkpoint_snapshot' if snapshot else 'first_match_once',
            predicate=predicate,dependencies=rule['dependencies'])
    except ValueError as error: raise V4ContractError(str(error)) from error
    for clause in clauses:
        threshold=clause.get('threshold',clause.get('repeats',1))
        if not math.isfinite(threshold) or threshold<=0: raise V4ContractError('INVALID_V4_THRESHOLD')
    return rule

def rule_from_candidate(candidate,mode=None):
    rule={k:copy.deepcopy(candidate[k]) for k in ('category','indicator_type','predicate','dependencies')}
    rule.update(analysis_version=ANALYSIS_VERSION,mode=mode or ('snapshot' if candidate['trigger_mode']=='checkpoint_snapshot' else 'cumulative'))
    rule['rolling_hours']=24 if rule['mode']=='rolling' else None
    rule['rule_id']=digest(rule)
    return validate_rule(rule)

def validate_config(value):
    schema=json.loads((Path(__file__).parents[2]/'contracts/casual_game_v4.schema.json').read_text())
    if not Draft202012Validator(schema).is_valid(value):raise V4ContractError('INVALID_V4_CONFIG')
    from server.analysis.v3_contract import METRIC_CATEGORIES,SEQUENCE_RULES
    if set(value.get('thresholds',{}))-(set(METRIC_CATEGORIES)|set(SEQUENCE_RULES)):raise V4ContractError('INVALID_V4_THRESHOLD_METRIC')
    for metric,thresholds in value.get('thresholds',{}).items():
        if any(not math.isfinite(v) or v<=0 or (metric in SEQUENCE_RULES and (int(v)!=v or v>3)) for v in thresholds):raise V4ContractError('INVALID_V4_THRESHOLD')
    for item in value.get('existing_rules',[]):validate_rule(item['rule'])
    return value

def defaults():
    return {'schema_version':'1.0','analysis_version':ANALYSIS_VERSION,'windows_hours':list(CHECKPOINTS),
            'max_discovery_candidates':20000,'max_candidates':2000,'max_finalists':10,
            'seed':42,'min_group_users':100,'bootstrap_replicates':1000,'exploration_fraction':.7,'existing_rules':[]}
