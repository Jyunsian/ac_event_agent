"""Exploration-only Candidate Event V3 discovery and membership materialization."""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections import defaultdict
from datetime import timezone
from itertools import combinations
from pathlib import Path

from server.analysis.connection import connect
from server.analysis.ingest import IngestError, file_hash
from server.analysis.v3_contract import (
    ALLOWED_CROSS_CATEGORY_PAIRS, ANALYSIS_VERSION, MINIMUM_DENOMINATORS,
    POLICY_IDENTITY, SEQUENCE_RULES, SNAPSHOT_METRICS, WINDOWS, make_candidate, validate_config,
)
from server.analysis.v3_policy import (
    CROSS_PARENT_COVERAGE_RANGE, IAA_QUANTILES, MAX_PARENTS_PER_CATEGORY_WINDOW, NEAR_DUPLICATE_COVERAGE_DELTA,
    NEAR_DUPLICATE_JACCARD, QUANTILES, allocate_by_category, finite_thresholds,
    pareto_layers, stable_candidate_key,
)

SEARCH_VERSION="3.0"
SEQUENCE_GAPS={name:((300,1800,7200,86400) if name=="level_fail_to_complete" else (300,1800,7200))
               for name in SEQUENCE_RULES}
DEPENDENCIES={
    "ad_count":["ad_impression"],"ad_revenue_sum":["ad_impression"],
    "session_count":["session_start"],"first_return_delay_seconds":["session_start"],
    "return_in_interval":["session_start"],"return_interval_count":["session_start"],
    "consecutive_return_days":["session_start"],"post_return_session_count":["session_start"],
    "post_return_engaged_seconds":["session_start","session_end"],
    "level_start_count":["level_start"],"level_complete_count":["level_complete"],
    "distinct_completed_levels":["level_complete"],"max_completed_level_index":["level_complete"],
    "completed_level":["level_complete"],"reached_level":["level_complete"],
    "level_time_to_reach_seconds":["level_complete"],"completes_per_session":["session_start","level_complete"],
    "level_fail_count":["level_fail"],"retry_same_level":["level_fail","level_start"],
    "complete_after_fail":["level_fail","level_complete"],"session_after_fail":["level_fail","session_start"],
    "attempts_per_level":["level_start"],"complete_start_ratio":["level_start","level_complete"],
    "fail_start_ratio":["level_start","level_fail"],
    "completion_duration_seconds":["level_start","level_complete"],
    "consecutive_failures":["level_fail","level_complete"],
}
SEQUENCE_DEPENDENCIES={
    "level_start_to_complete":["level_start","level_complete"],
    "level_fail_to_start":["level_fail","level_start"],
    "level_fail_to_complete":["level_fail","level_complete"],
    "level_fail_to_session_end":["level_fail","session_end"],
    "session_start_to_level_complete":["session_start","level_complete"],
    "level_complete_to_ad_impression":["level_complete","ad_impression"],
    "rewarded_ad_to_level_complete":["ad_impression","level_complete"],
}


def _read_manifest(directory:Path,stage:str):
    path=directory/"manifest.json"
    try: value=json.loads(path.read_text())
    except (OSError,json.JSONDecodeError) as error: raise IngestError("V3_SEARCH_MANIFEST_INVALID") from error
    if value.get("stage")!=stage: raise IngestError("V3_SEARCH_STAGE_MISMATCH")
    return value,file_hash(path)


def _artifact(root,manifest,name):
    records=[item for item in manifest.get("artifacts",[]) if item.get("name")==name]
    if len(records)!=1 or records[0].get("path")!=name+".parquet":
        raise IngestError("V3_SEARCH_ARTIFACT_INVALID")
    path=root/records[0]["path"]
    if path.resolve().parent!=root.resolve() or file_hash(path)!=records[0]["sha256"]:
        raise IngestError("V3_SEARCH_CHECKSUM_MISMATCH")
    return path,records[0]["sha256"]


def _allowed_window(category,metric,hours,scope):
    if category=="iaa": return hours in WINDOWS["iaa"]
    if category=="session_retention":
        if metric=="session_count": return hours in WINDOWS["session_count"]
        if metric=="return_in_interval": return (scope.get("start_hours"),scope.get("end_hours")) in WINDOWS["retention"]
        return hours in (48,72,96,144)
    if category=="level_progress":
        if metric in ("max_completed_level_index","completed_level","reached_level","level_time_to_reach_seconds"):
            return hours in WINDOWS["level_progress"]
        return hours in (1,3,6,12,24,48,72)
    if category=="level_friction": return hours in WINDOWS["level_friction"]
    return False


def _scope(scope_json):
    value=json.loads(scope_json)
    return {} if value=="all" else value


def _quantiles(values,points):
    values=sorted(values)
    if not values:return []
    result=[]
    for point in points:
        position=(len(values)-1)*point;lower=math.floor(position);upper=math.ceil(position)
        result.append(values[lower] if lower==upper else values[lower]+(values[upper]-values[lower])*(position-lower))
    return result


def _atom(category,metric,scope,hours,comparator,threshold):
    start=float(scope.get("start_hours",0));end=float(hours)
    mode="checkpoint_snapshot" if metric in SNAPSHOT_METRICS else "first_match_once"
    return make_candidate(category=category,indicator_type=metric,observation_start_hours=start,
        observation_end_hours=end,decision_time_hours=end,trigger_mode=mode,
        predicate={"node":"atom","metric":metric,"comparator":comparator,"threshold":threshold,
                   "minimum_denominator":MINIMUM_DENOMINATORS.get(metric,0),"scope":scope},
        dependencies=sorted(DEPENDENCIES[metric]))


def _sequence(template,gap,repeats,hours):
    return make_candidate(category="sequence",indicator_type=template,observation_start_hours=0,
        observation_end_hours=float(hours),decision_time_hours=float(hours),trigger_mode="first_match_once",
        predicate={"node":"sequence","template":template,"max_gap_seconds":gap,"repeats":repeats,
                   "matching":"non_overlapping","constraints":list(SEQUENCE_RULES[template])},
        dependencies=sorted(SEQUENCE_DEPENDENCIES[template]))


def _cross(left,right,operator):
    clauses=sorted((left["predicate"],right["predicate"]),key=lambda value:json.dumps(value,sort_keys=True,separators=(",",":")))
    mode="checkpoint_snapshot" if any(clause["metric"] in SNAPSHOT_METRICS or clause["comparator"]=="lte" for clause in clauses) else "first_match_once"
    return make_candidate(category="cross_category",indicator_type="cross_category",
        observation_start_hours=max(left["observation_start_hours"],right["observation_start_hours"]),
        observation_end_hours=left["observation_end_hours"],decision_time_hours=left["observation_end_hours"],
        trigger_mode=mode,predicate={"node":"boolean","operator":operator,"clauses":clauses},
        dependencies=sorted(set(left["dependencies"])|set(right["dependencies"])))


def _membership_digest(statuses):
    text="\n".join(f"{app}\t{user}\t{status}" for (app,user),status in sorted(statuses.items()))
    return hashlib.sha256(text.encode()).hexdigest()


def _membership_masks(statuses,identity_index):
    values={"triggered":0,"untriggered":0,"unknown":0}
    for identity,index in identity_index.items():
        values[statuses.get(identity,"unknown")]|=1<<index
    return values["triggered"],values["untriggered"],values["unknown"]


def _mask_digest(masks,identities):
    triggered,untriggered,_=masks
    rows=[]
    for index,(app,user) in enumerate(identities):
        bit=1<<index
        status="triggered" if triggered&bit else "untriggered" if untriggered&bit else "unknown"
        rows.append(f"{app}\t{user}\t{status}")
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def _mask_mean(mask,values):
    count=mask.bit_count()
    if not count:return None
    total=0.0
    while mask:
        bit=mask&-mask;total+=values[bit.bit_length()-1];mask^=bit
    return total/count


def near_duplicate(left_hits,right_hits,left_coverage,right_coverage):
    union=left_hits|right_hits
    jaccard=len(left_hits&right_hits)/len(union) if union else 1.0
    coverage_delta=abs(left_coverage-right_coverage)
    epsilon=1e-12
    return (jaccard+epsilon>=NEAR_DUPLICATE_JACCARD
            and coverage_delta<=NEAR_DUPLICATE_COVERAGE_DELTA+epsilon),jaccard,coverage_delta


def _evaluate(candidate,dimension_values,targets,timeline):
    predicate=candidate["predicate"]
    if predicate["node"]=="atom":
        key=(candidate["observation_end_hours"],predicate["metric"],json.dumps(predicate["scope"],sort_keys=True,separators=(",",":")))
        records=dimension_values.get(key,{})
        statuses={};times={}
        for identity,(value,denominator,first_at) in records.items():
            minimum=predicate["minimum_denominator"]
            if value is None or (minimum and (denominator is None or denominator<minimum)):
                statuses[identity]="unknown";continue
            hit=value>=predicate["threshold"] if predicate["comparator"]=="gte" else value<=predicate["threshold"]
            statuses[identity]="triggered" if hit else "untriggered"
            if hit:
                if candidate["trigger_mode"]=="checkpoint_snapshot":times[identity]=candidate["decision_time_hours"]*3600
                else:
                    observations=timeline.get((identity,predicate["metric"],json.dumps(predicate["scope"],sort_keys=True,separators=(",",":"))),())
                    matches=[delay for value_at,delay in observations if value_at>=predicate["threshold"]]
                    times[identity]=min(matches) if matches else (first_at or candidate["decision_time_hours"]*3600)
    else:
        key=(candidate["observation_end_hours"],predicate["template"],json.dumps({"max_gap_seconds":predicate["max_gap_seconds"]},sort_keys=True,separators=(",",":")))
        records=dimension_values.get(key,{})
        statuses={};times={}
        for identity,(value,_,first_at) in records.items():
            if value is None:statuses[identity]="unknown";continue
            hit=value>=predicate["repeats"];statuses[identity]="triggered" if hit else "untriggered"
            if hit:
                observations=timeline.get((identity,predicate["template"],key[2]),())
                matches=[delay for value_at,delay in observations if value_at>=predicate["repeats"]]
                times[identity]=min(matches) if matches else (first_at or candidate["decision_time_hours"]*3600)
    hits=[identity for identity,status in statuses.items() if status=="triggered" and identity in targets]
    misses=[identity for identity,status in statuses.items() if status=="untriggered" and identity in targets]
    hit_mean=sum(targets[i] for i in hits)/len(hits) if hits else None
    miss_mean=sum(targets[i] for i in misses)/len(misses) if misses else None
    p90=None
    if hits:
        delays=sorted(times.get(i,candidate["decision_time_hours"]*3600) for i in hits)
        p90=_quantiles(delays,(.9,))[0]
    return statuses,{"candidate_id":candidate["candidate_id"],"category":candidate["category"],
        "triggered_users":len(hits),"untriggered_users":len(misses),"unknown_users":sum(v=="unknown" for v in statuses.values()),
        "coverage":len(hits)/(len(hits)+len(misses)) if hits or misses else None,
        "difference_usd":hit_mean-miss_mean if hit_mean is not None and miss_mean is not None else None,
        "p90_seconds":p90,"membership_sha256":_membership_digest(statuses)}


def generate_casual_candidates(feature_dir,target_dir,config,destination):
    """Generate and evaluate the finite Discovery pool without reading holdout rows."""
    feature_dir,target_dir,destination=map(Path,(feature_dir,target_dir,destination))
    features,feature_manifest_hash=_read_manifest(feature_dir,"features_v3")
    targets,target_manifest_hash=_read_manifest(target_dir,"targets")
    try:validate_config(config)
    except ValueError as error:raise IngestError("INVALID_V3_SEARCH_CONFIG") from error
    scope=features.get("definition",{}).get("scope")
    if not isinstance(scope,dict) or scope.get("kind")!="exploration":raise IngestError("V3_EXPLORATION_FEATURES_REQUIRED")
    if (scope.get("target_manifest_sha256")!=target_manifest_hash or scope.get("split_id")!=targets.get("split_id")
            or scope.get("parent_source_manifest_sha256")!=targets.get("source_manifest_sha256")):
        raise IngestError("V3_SEARCH_SOURCE_MISMATCH")
    if config.get("analysis_version")!=ANALYSIS_VERSION:raise IngestError("INVALID_V3_SEARCH_CONFIG")
    snapshots_path,snap_hash=_artifact(feature_dir,features,"snapshots")
    timeline_path,timeline_hash=_artifact(feature_dir,features,"timeline")
    targets_path,target_hash=_artifact(target_dir,targets,"targets")
    destination.mkdir(parents=True,exist_ok=False)
    dimension_values=defaultdict(dict);dimension_category={};timeline=defaultdict(list);revenues={}
    with connect(str(destination/"work.duckdb"),config={"memory_limit":"512MB","threads":2}) as c:
        rows=c.execute("""SELECT app_id,user_id,window_hours,category,metric,scope_json,value,denominator,
          epoch(first_observed_at-installed_at) first_delay FROM read_parquet(?) s
          JOIN (SELECT app_id,user_id,installed_at FROM read_parquet(?)) t USING(app_id,user_id)
          WHERE enabled AND window_complete ORDER BY ALL""",[str(snapshots_path),str(targets_path)]).fetchall()
        for app,user,hours,category,metric,scope_json,value,denominator,first_delay in rows:
            normalized_scope=json.dumps(_scope(scope_json),sort_keys=True,separators=(",",":"))
            dimension_values[(float(hours),metric,normalized_scope)][(app,user)]=(value,denominator,first_delay)
            dimension_category[(float(hours),metric,normalized_scope)]=category
        installs={(app,user):installed for app,user,installed in c.execute("SELECT app_id,user_id,installed_at FROM read_parquet(?)",[str(targets_path)]).fetchall()}
        for app,user,metric,scope_json,observed,value in c.execute("SELECT app_id,user_id,metric,scope_json,observed_at,value FROM read_parquet(?) ORDER BY ALL",[str(timeline_path)]).fetchall():
            normalized_scope=json.dumps(_scope(scope_json),sort_keys=True,separators=(",",":"))
            delay=(observed.astimezone(timezone.utc)-installs[(app,user)].astimezone(timezone.utc)).total_seconds()
            timeline[((app,user),metric,normalized_scope)].append((value,delay))
        target_rows=c.execute("SELECT app_id,user_id,d7_revenue_usd FROM read_parquet(?) WHERE split='exploration' AND is_mature ORDER BY ALL",[str(targets_path)]).fetchall()
        if any(value is None for _,_,value in target_rows):raise IngestError("V3_EXPLORATION_TARGETS_UNKNOWN")
        revenues={(app,user):value for app,user,value in target_rows}
    identities=sorted(revenues);identity_index={identity:index for index,identity in enumerate(identities)}
    revenue_values=[revenues[identity] for identity in identities];full_mask=(1<<len(identities))-1
    generated=[];threshold_audit=[]
    custom=config.get("thresholds",{})
    for (hours,metric,scope_json),records in sorted(dimension_values.items()):
        category=dimension_category[(hours,metric,scope_json)];scope_value=json.loads(scope_json)
        if category=="sequence":continue
        if not _allowed_window(category,metric,hours,scope_value) or hours not in config["windows_hours"]:continue
        minimum_denominator=MINIMUM_DENOMINATORS.get(metric,0)
        positive=[value for value,denominator,_ in records.values() if value is not None and value>0 and (not minimum_denominator or (denominator or 0)>=minimum_denominator)]
        if not positive:continue
        points=IAA_QUANTILES if category=="iaa" else QUANTILES
        values=sorted(set(custom.get(metric,finite_thresholds(metric,_quantiles(positive,points),min(positive),max(positive)))))
        threshold_audit.append({"category":category,"metric":metric,"scope":scope_value,"observation_end_hours":hours,
                                "values":values,"source":"configured" if metric in custom else "exploration_quantiles_and_fixed_grid"})
        comparators=("gte","lte") if metric in SNAPSHOT_METRICS else ("gte",)
        for comparator in comparators:
            for threshold in values:generated.append(_atom(category,metric,scope_value,hours,comparator,threshold))
    for template,gaps in SEQUENCE_GAPS.items():
        for hours in WINDOWS["sequence"]:
            if hours not in config["windows_hours"]:continue
            for gap in gaps:
                key=(float(hours),template,json.dumps({"max_gap_seconds":gap},sort_keys=True,separators=(",",":")))
                if key not in dimension_values:continue
                for repeats in (1,2,3):generated.append(_sequence(template,gap,repeats,hours))
    canonical={};audit=[]
    for candidate in sorted(generated,key=stable_candidate_key):
        if candidate["candidate_id"] in canonical:
            audit.append({"candidate_id":candidate["candidate_id"],"stage":"canonical","primary_reason":"EQUIVALENT_CANONICAL_AST"})
        else:canonical[candidate["candidate_id"]]=candidate
    evaluations={};memberships={}
    for candidate in canonical.values():
        statuses,row=_evaluate(candidate,dimension_values,revenues,timeline)
        memberships[candidate["candidate_id"]]=_membership_masks(statuses,identity_index);evaluations[candidate["candidate_id"]]=row
    # Exact membership keeps the simplest, earliest and then smallest identity.
    membership_groups=defaultdict(list)
    for candidate in canonical.values():membership_groups[memberships[candidate["candidate_id"]]].append(candidate)
    atom_pool=[]
    for group in membership_groups.values():
        ordered=sorted(group,key=lambda c:(1 if c["predicate"]["node"]=="boolean" else 0,
                                          evaluations[c["candidate_id"]]["p90_seconds"] or math.inf,c["candidate_id"]))
        atom_pool.append(ordered[0])
        for dropped in ordered[1:]:audit.append({"candidate_id":dropped["candidate_id"],"stage":"membership","primary_reason":"EXACT_MEMBERSHIP_DUPLICATE","representative_id":ordered[0]["candidate_id"]})
    min_users=config["min_group_users"]
    eligible=[]
    for candidate in atom_pool:
        row=evaluations[candidate["candidate_id"]]
        if min(row["triggered_users"],row["untriggered_users"])<min_users:
            audit.append({"candidate_id":candidate["candidate_id"],"stage":"sample","primary_reason":"INSUFFICIENT_EXPLORATION_GROUP_USERS"})
        elif row["difference_usd"] is None or row["p90_seconds"] is None:
            audit.append({"candidate_id":candidate["candidate_id"],"stage":"sample","primary_reason":"UNAVAILABLE_EXPLORATION_METRICS"})
        else:eligible.append(candidate)
    # Adjacent points on one threshold curve are tested for the preregistered near-duplicate rule.
    curves=defaultdict(list)
    for candidate in eligible:
        predicate=candidate["predicate"]
        if predicate["node"]=="atom":curves[(candidate["category"],candidate["observation_end_hours"],predicate["metric"],
            json.dumps(predicate["scope"],sort_keys=True),predicate["comparator"])].append(candidate)
    near_dropped=set()
    for curve in curves.values():
        ordered=sorted(curve,key=lambda c:c["predicate"]["threshold"])
        for left,right in zip(ordered,ordered[1:]):
            left_hits=memberships[left["candidate_id"]][0];right_hits=memberships[right["candidate_id"]][0]
            union=(left_hits|right_hits).bit_count();jaccard=(left_hits&right_hits).bit_count()/union if union else 1.0
            coverage_delta=abs(evaluations[left["candidate_id"]]["coverage"]-evaluations[right["candidate_id"]]["coverage"])
            is_near=jaccard+1e-12>=NEAR_DUPLICATE_JACCARD and coverage_delta<=NEAR_DUPLICATE_COVERAGE_DELTA+1e-12
            if is_near:
                keep=max((left,right),key=lambda c:(evaluations[c["candidate_id"]]["coverage"],abs(evaluations[c["candidate_id"]]["difference_usd"]),-int(c["candidate_id"],16)))
                drop=right if keep is left else left
                if drop["candidate_id"] not in near_dropped:
                    near_dropped.add(drop["candidate_id"]);audit.append({"candidate_id":drop["candidate_id"],"stage":"near_duplicate","primary_reason":"NEAR_DUPLICATE_THRESHOLD","representative_id":keep["candidate_id"],"jaccard":jaccard,"coverage_delta":coverage_delta})
    eligible=[c for c in eligible if c["candidate_id"] not in near_dropped]
    ranked=[]
    for category in ("iaa","session_retention","level_progress","level_friction","sequence"):
        category_rows=[{**evaluations[c["candidate_id"]],"candidate":c} for c in eligible if c["category"]==category]
        for row in pareto_layers(category_rows):
            evaluations[row["candidate_id"]]["pareto_layer"]=row["pareto_layer"];ranked.append(row["candidate"])
    # Controlled cross-category parent pools; no all-pairs expansion.
    parent_candidates={}
    for category in ("iaa","session_retention","level_progress","level_friction"):
        for hours in sorted(config["windows_hours"]):
            candidates=[c for c in ranked if c["category"]==category and c["observation_end_hours"]==hours and c["predicate"]["node"]=="atom"]
            balanced=[c for c in candidates if CROSS_PARENT_COVERAGE_RANGE[0]<=evaluations[c["candidate_id"]]["coverage"]<=CROSS_PARENT_COVERAGE_RANGE[1]]
            if len(balanced)>=MAX_PARENTS_PER_CATEGORY_WINDOW:candidates=balanced
            parent_candidates[(category,float(hours))]=candidates
    parents={}
    for (category,hours),candidates in parent_candidates.items():
        partner_categories=sorted(next(iter(pair-{category})) for pair in ALLOWED_CROSS_CATEGORY_PAIRS if category in pair)
        def key(candidate,partner_source=parent_candidates):
            left=memberships[candidate["candidate_id"]];compatible=0
            for partner_category in partner_categories:
                for partner in partner_source.get((partner_category,hours),()):
                    right=memberships[partner["candidate_id"]]
                    and_hit=(left[0]&right[0]).bit_count();and_miss=(left[1]|right[1]).bit_count()
                    or_hit=(left[0]|right[0]).bit_count();or_miss=(left[1]&right[1]).bit_count()
                    compatible+=int(min(and_hit,and_miss)>=min_users)+int(min(or_hit,or_miss)>=min_users)
            row=evaluations[candidate["candidate_id"]]
            return (-compatible,row.get("pareto_layer",math.inf),abs(row["coverage"]-.5),-row["difference_usd"],candidate["candidate_id"])
        parents[(category,hours)]=sorted(candidates,key=key)[:MAX_PARENTS_PER_CATEGORY_WINDOW]
    # Make independently selected pools mutually compatible and membership-
    # diverse without exceeding the fixed 20-parent Category/window cap.  A
    # plain compatibility count can spend multiple slots on parents that create
    # the same boolean membership.  Greedy marginal mask coverage maximizes the
    # number of genuinely distinct, sample-valid crosses that each slot adds.
    # The iteration count is policy, not a data-dependent stopping rule.
    atom_masks={(value[0],value[1]) for value in memberships.values()}
    def valid_cross_masks(left,right):
        outputs=set()
        for triggered,untriggered in ((left[0]&right[0],left[1]|right[1]),
                                      (left[0]|right[0],left[1]&right[1])):
            if min(triggered.bit_count(),untriggered.bit_count())>=min_users:
                outputs.add((triggered,untriggered))
        return outputs
    def selected_cross_masks(selected,excluded=None):
        outputs=set(atom_masks)
        for pair in ALLOWED_CROSS_CATEGORY_PAIRS:
            left_category,right_category=sorted(pair)
            for selected_hours in sorted(config["windows_hours"]):
                left_key=(left_category,float(selected_hours));right_key=(right_category,float(selected_hours))
                if excluded in (left_key,right_key):continue
                for left in selected.get(left_key,()):
                    for right in selected.get(right_key,()):
                        outputs.update(valid_cross_masks(memberships[left["candidate_id"]],memberships[right["candidate_id"]]))
        return outputs
    for _ in range(3):
        refined={}
        for (category,hours),candidates in parent_candidates.items():
            partner_categories=sorted(next(iter(pair-{category})) for pair in ALLOWED_CROSS_CATEGORY_PAIRS if category in pair)
            def cross_masks(candidate):
                left=memberships[candidate["candidate_id"]];outputs=set()
                for partner_category in partner_categories:
                    for partner in parents.get((partner_category,hours),()):
                        outputs.update(valid_cross_masks(left,memberships[partner["candidate_id"]]))
                return outputs
            remaining=list(candidates);selected=[]
            # Crosses from atoms and all unaffected pools already consume exact-
            # membership identities. Score only the globally new masks added by
            # this Category/window pool, so duplicate windows cannot waste slots.
            covered=selected_cross_masks({**parents,**refined},(category,hours))
            while remaining and len(selected)<MAX_PARENTS_PER_CATEGORY_WINDOW:
                def refine_key(candidate):
                    masks=cross_masks(candidate);row=evaluations[candidate["candidate_id"]]
                    return (-len(masks-covered),-len(masks),row.get("pareto_layer",math.inf),
                            abs(row["coverage"]-.5),-row["difference_usd"],candidate["candidate_id"])
                chosen=min(remaining,key=refine_key)
                selected.append(chosen);covered.update(cross_masks(chosen));remaining.remove(chosen)
            refined[(category,hours)]=selected
        parents=refined
    crosses=[]
    for pair in sorted(ALLOWED_CROSS_CATEGORY_PAIRS,key=lambda p:sorted(p)):
        left_category,right_category=sorted(pair)
        for hours in sorted(config["windows_hours"]):
            for left,right in combinations(parents.get((left_category,float(hours)),[])+parents.get((right_category,float(hours)),[]),2):
                if left["category"]==right["category"]:continue
                for operator in ("and","or"):
                    candidate=_cross(left,right,operator)
                    left_status=memberships[left["candidate_id"]];right_status=memberships[right["candidate_id"]]
                    if operator=="and":
                        triggered=left_status[0]&right_status[0];untriggered=left_status[1]|right_status[1]
                    else:
                        triggered=left_status[0]|right_status[0];untriggered=left_status[1]&right_status[1]
                    unknown=full_mask&~(triggered|untriggered);masks=(triggered,untriggered,unknown)
                    hit_count=triggered.bit_count();miss_count=untriggered.bit_count()
                    hit_mean=_mask_mean(triggered,revenue_values);miss_mean=_mask_mean(untriggered,revenue_values)
                    p90=max(evaluations[left["candidate_id"]]["p90_seconds"],evaluations[right["candidate_id"]]["p90_seconds"])
                    memberships[candidate["candidate_id"]]=masks
                    evaluations[candidate["candidate_id"]]={"candidate_id":candidate["candidate_id"],"category":"cross_category",
                        "triggered_users":hit_count,"untriggered_users":miss_count,"unknown_users":unknown.bit_count(),
                        "coverage":hit_count/(hit_count+miss_count) if hit_count or miss_count else None,
                        "difference_usd":hit_mean-miss_mean if hit_mean is not None and miss_mean is not None else None,
                        "p90_seconds":p90,"membership_sha256":_mask_digest(masks,identities),
                        "parent_ids":[left["candidate_id"],right["candidate_id"]]}
                    if min(hit_count,miss_count)>=min_users and hit_mean is not None and miss_mean is not None:crosses.append(candidate)
                    else:audit.append({"candidate_id":candidate["candidate_id"],"stage":"cross_sample","primary_reason":"INSUFFICIENT_EXPLORATION_GROUP_USERS"})
    representatives={memberships[c["candidate_id"]]:c for c in ranked}
    unique_crosses=[]
    for candidate in sorted(crosses,key=stable_candidate_key):
        membership_key=memberships[candidate["candidate_id"]]
        representative=representatives.get(membership_key)
        if representative is not None:
            audit.append({"candidate_id":candidate["candidate_id"],"stage":"membership",
                          "primary_reason":"EXACT_MEMBERSHIP_DUPLICATE","representative_id":representative["candidate_id"]})
        else:
            representatives[membership_key]=candidate;unique_crosses.append(candidate)
    for row in pareto_layers([{**evaluations[c["candidate_id"]],"candidate":c} for c in unique_crosses]):
        evaluations[row["candidate_id"]]["pareto_layer"]=row["pareto_layer"];ranked.append(row["candidate"])
    discovery,over_cap,budget=allocate_by_category(ranked,"discovery",config["max_discovery_candidates"])
    for candidate in over_cap:audit.append({"candidate_id":candidate["candidate_id"],"stage":"discovery_budget","primary_reason":"DISCOVERY_CATEGORY_BUDGET"})
    byte_width=(len(identities)+7)//8
    membership_rows=[(candidate["candidate_id"],*(mask.to_bytes(byte_width,"little") for mask in memberships[candidate["candidate_id"]]))
                     for candidate in discovery]
    with connect(str(destination/"memberships.duckdb"),config={"memory_limit":"256MB","threads":2}) as c:
        c.execute("CREATE TABLE memberships(candidate_id VARCHAR,triggered_bits BLOB,untriggered_bits BLOB,unknown_bits BLOB)")
        if membership_rows:c.executemany("INSERT INTO memberships VALUES (?,?,?,?)",membership_rows)
        membership_path=destination/"memberships.parquet"
        c.execute("COPY (SELECT * FROM memberships ORDER BY ALL) TO ? (FORMAT PARQUET,COMPRESSION ZSTD)",[str(membership_path)])
        c.execute("CREATE TABLE membership_users(bit_index INTEGER,app_id VARCHAR,user_id VARCHAR)")
        c.executemany("INSERT INTO membership_users VALUES (?,?,?)",[(index,*identity) for index,identity in enumerate(identities)])
        users_path=destination/"membership_users.parquet"
        c.execute("COPY (SELECT * FROM membership_users ORDER BY bit_index) TO ? (FORMAT PARQUET,COMPRESSION ZSTD)",[str(users_path)])
    output={"schema_version":"3.0","analysis_version":ANALYSIS_VERSION,"stage":"search_v3","search_version":SEARCH_VERSION,
        "synthetic":features.get("synthetic",False),"feature_id":features["feature_id"],"feature_manifest_sha256":feature_manifest_hash,
        "split_id":targets["split_id"],"exploration_scope":scope,"policy_identity":POLICY_IDENTITY,
        "policy":{"near_duplicate_jaccard":NEAR_DUPLICATE_JACCARD,"near_duplicate_coverage_delta":NEAR_DUPLICATE_COVERAGE_DELTA,
                  "max_parents_per_category_window":MAX_PARENTS_PER_CATEGORY_WINDOW,
                  "cross_parent_coverage_range":list(CROSS_PARENT_COVERAGE_RANGE),
                  "cross_parent_selection":"greedy_global_distinct_valid_membership_then_pareto","cross_parent_refinement_rounds":3},
        "config":config,"generated_unique":len(canonical),"discovery_count":len(discovery),"budget":budget,
        "thresholds":threshold_audit,"candidates":discovery,
        "evaluations":[evaluations[c["candidate_id"]] for c in discovery],"search_log":sorted(audit,key=lambda row:(row["candidate_id"],row["stage"])),
        "artifacts":[{"name":"memberships","path":"memberships.parquet","sha256":file_hash(membership_path),"size_bytes":membership_path.stat().st_size,
                      "rows":len(membership_rows),"logical_rows":len(membership_rows)*len(identities),"encoding":"indexed_bitset_v1","user_count":len(identities)},
                     {"name":"membership_users","path":"membership_users.parquet","sha256":file_hash(users_path),"size_bytes":users_path.stat().st_size,"rows":len(identities)}],
        "source_hashes":{"snapshots":snap_hash,"timeline":timeline_hash,"targets":target_hash}}
    for path,digest in ((snapshots_path,snap_hash),(timeline_path,timeline_hash),(targets_path,target_hash)):
        if file_hash(path)!=digest:raise IngestError("V3_SEARCH_SOURCE_CHANGED")
    partial=destination/"manifest.partial.json"
    with partial.open("x") as stream:
        json.dump(output,stream,sort_keys=True,indent=2,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    os.link(partial,destination/"manifest.json");partial.unlink()
    return output
