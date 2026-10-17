"""Full frozen-family V3 holdout membership, decomposition and inference."""
from __future__ import annotations

import hashlib
import json
import math
import os
import csv
from collections import defaultdict
from datetime import timezone
from pathlib import Path

from server.analysis.bootstrap import bootstrap_differences
from server.analysis.casual_diagnostics import build_casual_diagnostics
from server.analysis.casual_freeze import load_casual_freeze
from server.analysis.connection import connect
from server.analysis.ingest import IngestError,file_hash
from server.analysis.statistics_v2 import holm_family,welch_greater
from server.analysis.v3_contract import ANALYSIS_VERSION,POLICY_IDENTITY,validate_candidate

VALIDATION_VERSION="3.0"


def _scope(value):
    parsed=json.loads(value)
    return {} if parsed=="all" else parsed


def _digest(statuses):
    content="\n".join(f"{a}\t{u}\t{s}" for (a,u),s in sorted(statuses.items()))
    return hashlib.sha256(content.encode()).hexdigest()


def _percentile(values,point):
    values=sorted(values)
    if not values:return None
    position=(len(values)-1)*point;low=math.floor(position);high=math.ceil(position)
    return values[low] if low==high else values[low]+(values[high]-values[low])*(position-low)


def _atom_membership(clause,hours,mode,dimensions,timeline):
    scope_json=json.dumps(clause["scope"],sort_keys=True,separators=(",",":"))
    records=dimensions.get((float(hours),clause["metric"],scope_json),{})
    statuses={};delays={}
    for identity,(value,denominator,first_delay) in records.items():
        minimum=clause["minimum_denominator"]
        if value is None or (minimum and (denominator is None or denominator<minimum)):
            statuses[identity]="unknown";continue
        hit=value>=clause["threshold"] if clause["comparator"]=="gte" else value<=clause["threshold"]
        statuses[identity]="triggered" if hit else "untriggered"
        if hit:
            if mode=="checkpoint_snapshot":delays[identity]=hours*3600
            else:
                matches=[delay for observed,delay in timeline.get((identity,clause["metric"],scope_json),()) if observed>=clause["threshold"]]
                delays[identity]=min(matches) if matches else (first_delay if first_delay is not None else hours*3600)
    return statuses,delays


def _membership(candidate,dimensions,timeline):
    predicate=candidate["predicate"];hours=candidate["observation_end_hours"]
    if predicate["node"]=="atom":return _atom_membership(predicate,hours,candidate["trigger_mode"],dimensions,timeline)
    if predicate["node"]=="sequence":
        clause={"metric":predicate["template"],"scope":{"max_gap_seconds":predicate["max_gap_seconds"]},
                "minimum_denominator":0,"threshold":predicate["repeats"],"comparator":"gte"}
        return _atom_membership(clause,hours,"first_match_once",dimensions,timeline)
    parts=[_atom_membership(clause,hours,"checkpoint_snapshot" if candidate["trigger_mode"]=="checkpoint_snapshot" else "first_match_once",dimensions,timeline)
           for clause in predicate["clauses"]]
    identities=set(parts[0][0])|set(parts[1][0]);statuses={};delays={}
    for identity in identities:
        a,b=parts[0][0].get(identity,"unknown"),parts[1][0].get(identity,"unknown")
        if predicate["operator"]=="and":status="untriggered" if "untriggered" in (a,b) else ("triggered" if a==b=="triggered" else "unknown")
        else:status="triggered" if "triggered" in (a,b) else ("untriggered" if a==b=="untriggered" else "unknown")
        statuses[identity]=status
        if status=="triggered":
            if candidate["trigger_mode"]=="checkpoint_snapshot":delays[identity]=hours*3600
            else:
                observed=[part[1][identity] for part in parts if identity in part[1]]
                delays[identity]=(max(observed) if predicate["operator"]=="and" else min(observed))
    return statuses,delays


def _group(records,status):
    subset=[row for row in records if row["status"]==status]
    unknown=sum(row["d7"] is None for row in subset)
    output={"users":len(subset),"unknown_revenue_users":unknown}
    for name in ("early","remaining","d7"):
        total=math.fsum(row[name] for row in subset) if subset and not unknown else None
        output[name]={"revenue_usd":total,"arpu_usd":total/len(subset) if total is not None else None}
    return output


def _checkpoint(records,hours,decision):
    counts={status:sum(row["status"]==status for row in records) for status in ("triggered","untriggered","unknown")}
    if decision>hours:
        return {"checkpoint_hours":hours,"comparison_status":"LATE_INDICATOR_NOT_DECIDABLE","membership_counts":counts,
                "groups":None,"comparisons":None}
    groups={status:_group(records,status) for status in ("triggered","untriggered","unknown")}
    comparisons={}
    for field in ("early","remaining","d7"):
        left=groups["triggered"][field]["arpu_usd"];right=groups["untriggered"][field]["arpu_usd"]
        comparisons[field]={"difference_usd":left-right if left is not None and right is not None else None}
    return {"checkpoint_hours":hours,"comparison_status":"descriptive_same_frozen_membership",
            "membership_counts":counts,"groups":groups,"comparisons":comparisons,
            "intervals":{"early":[0,hours],"remaining":[hours,168],"d7":[0,168]}}


def validate_casual_family(normalized_dir,feature_dir,target_dir,frozen_dir,expected_sha256,destination,*,validation_policy=None,batch_store=None):
    normalized_dir,feature_dir,target_dir,frozen_dir,destination=map(Path,(normalized_dir,feature_dir,target_dir,frozen_dir,destination))
    frozen=load_casual_freeze(frozen_dir,expected_sha256)
    manifests={name:json.loads((root/"manifest.json").read_text()) for name,root in
               (("normalized",normalized_dir),("features",feature_dir),("targets",target_dir))}
    manifest_hashes={name:file_hash(root/"manifest.json") for name,root in
                     (("normalized",normalized_dir),("features",feature_dir),("targets",target_dir))}
    features=manifests["features"];targets=manifests["targets"]
    if (features.get("stage")!="features_v3" or features.get("analysis_version")!=ANALYSIS_VERSION
            or features["definition"].get("scope") is not None or features["definition"].get("policy_identity")!=POLICY_IDENTITY
            or targets.get("split_id")!=frozen["split_id"] or targets.get("source_manifest_sha256")!=manifest_hashes["normalized"]
            or features["definition"].get("source_manifest_sha256")!=manifest_hashes["normalized"]):
        raise IngestError("V3_VALIDATION_SOURCE_OR_SPLIT_MISMATCH")
    def artifact(root,manifest,name):
        matches=[row for row in manifest["artifacts"] if row["name"]==name]
        if len(matches)!=1:raise IngestError("V3_VALIDATION_ARTIFACT_INVALID")
        path=root/matches[0]["path"]
        if path.resolve().parent!=root.resolve() or file_hash(path)!=matches[0]["sha256"]:raise IngestError("V3_VALIDATION_CHECKSUM_MISMATCH")
        return path,matches[0]["sha256"]
    snapshots,snapshot_hash=artifact(feature_dir,features,"snapshots");timeline_path,timeline_hash=artifact(feature_dir,features,"timeline")
    target_path,target_hash=artifact(target_dir,targets,"targets");events,event_hash=artifact(normalized_dir,manifests["normalized"],"events")
    users,user_hash=artifact(normalized_dir,manifests["normalized"],"users")
    dimensions=defaultdict(dict);timeline=defaultdict(list);mature={};holdout=set();revenue={48:{},72:{},168:{}}
    with connect(config={"memory_limit":"512MB","threads":2}) as c:
        mature_rows=c.execute("SELECT app_id,user_id,installed_at,d7_revenue_usd,split FROM read_parquet(?) WHERE is_mature ORDER BY app_id,user_id",[str(target_path)]).fetchall()
        mature={(app,user):{"installed_at":installed,"target_d7":d7,"split":split} for app,user,installed,d7,split in mature_rows}
        holdout={key for key,row in mature.items() if row["split"]=="holdout"}
        if not holdout:raise IngestError("V3_HOLDOUT_UNAVAILABLE")
        for app,user,hours,metric,scope_json,value,denominator,first_at in c.execute("""SELECT s.app_id,s.user_id,s.window_hours,s.metric,s.scope_json,s.value,s.denominator,
            epoch(s.first_observed_at-t.installed_at) FROM read_parquet(?) s JOIN read_parquet(?) t USING(app_id,user_id)
            WHERE t.is_mature AND s.enabled AND s.window_complete ORDER BY ALL""",[str(snapshots),str(target_path)]).fetchall():
            normalized_scope=json.dumps(_scope(scope_json),sort_keys=True,separators=(",",":"))
            dimensions[(float(hours),metric,normalized_scope)][(app,user)]=(value,denominator,first_at)
        for app,user,metric,scope_json,observed,value,installed in c.execute("""SELECT l.app_id,l.user_id,l.metric,l.scope_json,l.observed_at,l.value,t.installed_at
            FROM read_parquet(?) l JOIN read_parquet(?) t USING(app_id,user_id)
            WHERE t.is_mature ORDER BY ALL""",[str(timeline_path),str(target_path)]).fetchall():
            normalized_scope=json.dumps(_scope(scope_json),sort_keys=True,separators=(",",":"))
            timeline[((app,user),metric,normalized_scope)].append((value,(observed.astimezone(timezone.utc)-installed.astimezone(timezone.utc)).total_seconds()))
        timing=features["definition"]["export_metadata"]["revenue_timing"]
        complete_through=features["definition"]["export_metadata"]["complete_through"]
        values=c.execute("""SELECT t.app_id,t.user_id,t.d7_revenue_usd,
          count(e.event_id) FILTER (WHERE e.revenue_usd IS NULL OR e.revenue_usd<0 OR (?='available_at' AND (e.available_at IS NULL OR e.available_at>CAST(? AS TIMESTAMPTZ)))) unavailable,
          coalesce(sum(e.revenue_usd ORDER BY e.event_id) FILTER (WHERE e.event_time<t.installed_at+INTERVAL '48 hours'),0) d2,
          coalesce(sum(e.revenue_usd ORDER BY e.event_id) FILTER (WHERE e.event_time<t.installed_at+INTERVAL '72 hours'),0) d3,
          coalesce(sum(e.revenue_usd ORDER BY e.event_id),0) d7
          FROM read_parquet(?) t LEFT JOIN read_parquet(?) e ON t.app_id=e.app_id AND t.user_id=e.user_id
            AND e.event_name='ad_impression' AND e.event_time>=t.installed_at AND e.event_time<t.installed_at+INTERVAL '168 hours'
          WHERE t.is_mature GROUP BY t.app_id,t.user_id,t.d7_revenue_usd ORDER BY t.app_id,t.user_id""",
          [timing,complete_through,str(target_path),str(events)]).fetchall()
        for app,user,target_d7,unavailable,d2,d3,d7 in values:
            identity=(app,user)
            if unavailable:d2=d3=d7=None
            if ((target_d7 is None)!=(d7 is None)) or (target_d7 is not None and not math.isclose(float(target_d7),float(d7),rel_tol=1e-12,abs_tol=1e-12)):
                raise IngestError("V3_TARGET_REVENUE_MISMATCH")
            revenue[48][identity]=(d2,None if d7 is None else d7-d2,d7)
            revenue[72][identity]=(d3,None if d7 is None else d7-d3,d7)
            revenue[168][identity]=(d7,0 if d7 is not None else None,d7)
    destination.mkdir(parents=True,exist_ok=False)
    # A 2,000-candidate family can produce millions of holdout-membership rows.
    # Stream the deterministic rows to a private CSV handoff instead of retaining
    # the entire long table in Python and feeding DuckDB one INSERT at a time.
    transfer=destination/".holdout_membership.transfer.csv"
    results=[];tests={};pending=[];cached=None;membership_count=0
    with transfer.open("x",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(("candidate_id","app_id","user_id","status","delay_seconds"))
        for position,candidate in enumerate(frozen["candidates"]):
            identity=candidate["candidate_id"];validate_candidate(candidate)
            if batch_store is not None and position%batch_store.size==0:cached=batch_store.load(position//batch_store.size)
            if cached is not None:
                entry=cached[position%batch_store.size]
                candidate_memberships=entry.get("memberships",[])
                if entry.get("row",{}).get("candidate_id")!=identity or any(row[0]!=identity for row in candidate_memberships):
                    raise IngestError("V3_VALIDATION_BATCH_ID_MISMATCH")
                results.append(entry["row"]);tests[identity]=entry["test"]
                writer.writerows(candidate_memberships);membership_count+=len(candidate_memberships);continue
            all_statuses,all_delays=_membership(candidate,dimensions,timeline)
            all_statuses={key:all_statuses.get(key,"unknown") for key in mature}
            statuses={key:all_statuses[key] for key in holdout}
            delays={key:all_delays[key] for key in holdout if key in all_delays}
            candidate_memberships=[(identity,app,user,status,delays.get((app,user)))
                                   for (app,user),status in sorted(statuses.items())]
            writer.writerows(candidate_memberships);membership_count+=len(candidate_memberships)
            checkpoint_rows={}
            for hours in (48,72,168):
                rows=[]
                for key,status in statuses.items():
                    early,remaining,d7=revenue[hours][key]
                    rows.append({"status":status,"early":early,"remaining":remaining,"d7":d7})
                    if d7 is not None and not math.isclose(float(early+remaining),float(d7),rel_tol=1e-12,abs_tol=1e-12):
                        raise IngestError("V3_REVENUE_DECOMPOSITION_MISMATCH")
                checkpoint_rows[{48:"d2",72:"d3",168:"d7"}[hours]]=_checkpoint(rows,hours,candidate["decision_time_hours"])
            observation_checkpoints={}
            for hours in (48,72,168):
                rows=[]
                for key,status in all_statuses.items():
                    early,remaining,d7=revenue[hours][key]
                    rows.append({"status":status,"early":early,"remaining":remaining,"d7":d7})
                observation_checkpoints[{48:"d2",72:"d3",168:"d7"}[hours]]=_checkpoint(rows,hours,candidate["decision_time_hours"])
            hits=[revenue[168][key][2] for key,status in statuses.items() if status=="triggered"]
            misses=[revenue[168][key][2] for key,status in statuses.items() if status=="untriggered"]
            reasons=[]
            if min(len(hits),len(misses))<frozen["rules"]["min_group_users"]:reasons.append("INSUFFICIENT_HOLDOUT_GROUP_USERS")
            if any(value is None for value in hits+misses):reasons.append("UNKNOWN_HOLDOUT_REVENUE")
            if reasons:test={"test":"welch_one_sided_greater","testable":False,"p_value":1.0,"statistic":None,"reasons":reasons}
            else:test=welch_greater([float(value) for value in hits],[float(value) for value in misses])
            bootstrap=None
            if not reasons and hits and misses:
                draws,_=bootstrap_differences([float(v) for v in hits],[float(v) for v in misses],seed=frozen["rules"]["seed"],replicates=1000)
                bootstrap={"method":"user_level_percentile","replicates":1000,"difference_ci95_usd":[_percentile(draws,.025),_percentile(draws,.975)]}
            row={"candidate_id":identity,"category":candidate["category"],"decision_time_hours":candidate["decision_time_hours"],
                 "observation":{"scope":"all_mature_users","membership":{"triggered_users":sum(v=="triggered" for v in all_statuses.values()),
                               "untriggered_users":sum(v=="untriggered" for v in all_statuses.values()),
                               "unknown_users":sum(v=="unknown" for v in all_statuses.values()),"membership_sha256":_digest(all_statuses),
                               "delay_seconds":{"median":_percentile(list(all_delays.values()),.5),"p90":_percentile(list(all_delays.values()),.9)}},
                               "checkpoints":observation_checkpoints,
                               "interpretation":"descriptive_same_dataset_not_independent_validation"},
                 "membership":{"triggered_users":sum(v=="triggered" for v in statuses.values()),"untriggered_users":sum(v=="untriggered" for v in statuses.values()),
                               "unknown_users":sum(v=="unknown" for v in statuses.values()),"membership_sha256":_digest(statuses),
                               "delay_seconds":{"median":_percentile(list(delays.values()),.5),"p90":_percentile(list(delays.values()),.9)}},
                 "checkpoints":checkpoint_rows,"bootstrap":bootstrap,"evidence_status":"pending_family_correction","reasons":reasons}
            results.append(row);tests[identity]=test
            if batch_store is not None:
                pending.append({"row":row,"test":test,"memberships":candidate_memberships})
                if len(pending)==batch_store.size or position==len(frozen["candidates"])-1:
                    batch_store.save(position//batch_store.size,pending);pending=[]
        stream.flush();os.fsync(stream.fileno())
    corrected=holm_family(tests,frozen["candidate_ids"])
    for row in results:
        inference=corrected[row["candidate_id"]];row["inference"]=inference
        if validation_policy is not None and not validation_policy.get("eligible"):
            row["evidence_status"]="exploratory"
            row["reasons"]=sorted(set(row["reasons"]+validation_policy.get("reasons",[])))
        elif not inference["testable"]:row["evidence_status"]="insufficient_data"
        elif inference["passed"]:row["evidence_status"]="historically_supported"
        else:row["evidence_status"]="not_supported";row["reasons"]=sorted(set(row["reasons"]+["HOLM_NOT_SIGNIFICANT"]))
    membership_path=destination/"holdout_membership.parquet"
    with connect(config={"memory_limit":"256MB","threads":2}) as c:
        c.execute("""CREATE TABLE membership AS SELECT
          CAST(candidate_id AS VARCHAR) candidate_id,CAST(app_id AS VARCHAR) app_id,
          CAST(user_id AS VARCHAR) user_id,CAST(status AS VARCHAR) status,
          CAST(delay_seconds AS DOUBLE) delay_seconds
          FROM read_csv(?,all_varchar=true,header=true,nullstr='')""",[str(transfer)])
        c.execute("COPY (SELECT * FROM membership ORDER BY ALL) TO ? (FORMAT PARQUET,COMPRESSION ZSTD)",[str(membership_path)])
    transfer.unlink()
    diagnostics=build_casual_diagnostics(membership_path,target_path,users,destination/"diagnostics")
    if load_casual_freeze(frozen_dir,expected_sha256)["candidate_ids"]!=[row["candidate_id"] for row in results]:
        raise IngestError("V3_FROZEN_FAMILY_CHANGED")
    for name,root in (("normalized",normalized_dir),("features",feature_dir),("targets",target_dir)):
        if file_hash(root/"manifest.json")!=manifest_hashes[name]:raise IngestError("V3_VALIDATION_SOURCE_CHANGED")
    for path,digest in ((snapshots,snapshot_hash),(timeline_path,timeline_hash),(target_path,target_hash),(events,event_hash),(users,user_hash)):
        if file_hash(path)!=digest:raise IngestError("V3_VALIDATION_SOURCE_CHANGED")
    membership_artifact={"name":"holdout_membership","path":membership_path.name,"sha256":file_hash(membership_path),"size_bytes":membership_path.stat().st_size,"rows":membership_count}
    output={"schema_version":"3.0","analysis_version":ANALYSIS_VERSION,"stage":"validation_v3","validation_version":VALIDATION_VERSION,
        "synthetic":features["definition"]["export_metadata"]["synthetic"],
        "frozen_sha256":expected_sha256,"family_size":frozen["family_size"],"priority_ids":frozen["priority_ids"],
        "family_correction_complete":True,"split_id":frozen["split_id"],"policy_identity":POLICY_IDENTITY,
        "validation_policy":validation_policy,
        "rules":frozen["rules"],"source_hashes":{**manifest_hashes,"targets_parquet":target_hash,"events_parquet":event_hash},
        "results":results,"artifacts":[membership_artifact,{**diagnostics,"path":"diagnostics/"+diagnostics["path"]}],
        "warnings":["All-mature-user observations are descriptive associations, not independent validation or causal uplift.",
                    "Holdout status is an additional replication badge and never suppresses the all-mature-user observation.",
                    "Daily and acquisition-source views are diagnostic only."]}
    partial=destination/"manifest.partial.json"
    with partial.open("x") as stream:json.dump(output,stream,sort_keys=True,indent=2,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    os.link(partial,destination/"manifest.json");partial.unlink()
    return output
