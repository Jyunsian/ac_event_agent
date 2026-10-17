"""Immutable V3 catalog, candidate details and the exact 72h value map."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

from server.analysis.ingest import IngestError,file_hash
from server.analysis.v3_contract import ANALYSIS_VERSION,POLICY_IDENTITY,validate_candidate


def event_spec_v3(candidate,origin="install"):
    return {"analysis_version":ANALYSIS_VERSION,"event_name":"ac3_"+candidate["candidate_id"][:24],
        "origin":origin,"window_hours":candidate["observation_end_hours"],
        "observation_start_hours":candidate["observation_start_hours"],
        "observation_end_hours":candidate["observation_end_hours"],"decision_time_hours":candidate["decision_time_hours"],
        "trigger_mode":candidate["trigger_mode"],"predicate":candidate["predicate"],
        "dependencies":candidate["dependencies"],"per_user_limit":1,
        "expired_policy":"do_not_emit_after_observation_end"}


def _all_group(groups):
    users=sum(group["users"] for group in groups.values())
    unknown=sum(group["unknown_revenue_users"] for group in groups.values())
    values=[group["d7"]["revenue_usd"] for group in groups.values()]
    revenue=sum(values) if values and all(value is not None for value in values) else None
    return {"users":users,"unknown_revenue_users":unknown,"revenue_usd":revenue,
            "arpu_usd":revenue/users if revenue is not None and users else None}


def metrics_projection(result):
    # The customer-facing comparison answers the descriptive product question
    # with every mature user. Holdout remains attached as a separate replication
    # badge and must not erase a usable same-batch observation when it is small.
    observation=result.get("observation") or {"checkpoints":result["checkpoints"],"membership":result["membership"]}
    checkpoint=observation["checkpoints"]["d7"];groups=checkpoint["groups"] or {}
    hit=groups.get("triggered",{});miss=groups.get("untriggered",{});unknown=groups.get("unknown",{})
    flat={}
    for name,group in (("triggered",hit),("untriggered",miss),("unknown",unknown)):
        flat[name]={"users":group.get("users",0),"unknown_revenue_users":group.get("unknown_revenue_users",0),
                    "revenue_usd":group.get("d7",{}).get("revenue_usd"),"arpu_usd":group.get("d7",{}).get("arpu_usd")}
    flat["all"]=_all_group(groups) if groups else {"users":0,"unknown_revenue_users":0,"revenue_usd":None,"arpu_usd":None}
    decided=flat["triggered"]["users"]+flat["untriggered"]["users"]
    return {"groups":flat,"coverage":flat["triggered"]["users"]/decided if decided else None,
        "delay_seconds":observation["membership"]["delay_seconds"],
        "comparisons":{"triggered_minus_untriggered":checkpoint.get("comparisons",{}).get("d7",{}).get("difference_usd")},
        "observation_scope":"all_mature_users","holdout_evidence_status":result["evidence_status"],
        "bootstrap":result.get("bootstrap"),"checkpoints":observation["checkpoints"],
        "holdout_checkpoints":result["checkpoints"]}


def validate_catalog_v3(catalog):
    if catalog.get("schema_version")!="3.0" or catalog.get("analysis_version")!=ANALYSIS_VERSION:raise IngestError("INVALID_V3_CATALOG")
    try:UUID(catalog["run_id"]);UUID(catalog["dataset_id"])
    except (KeyError,ValueError,TypeError):raise IngestError("INVALID_V3_CATALOG") from None
    entries=catalog.get("entries",[]);ids=[entry.get("candidate_id") for entry in entries]
    if (catalog.get("evaluated_count")!=len(entries) or len(entries)>2000 or len(ids)!=len(set(ids))
            or not set(catalog.get("priority_ids",[]))<=set(ids) or len(catalog.get("priority_ids",[]))>10):
        raise IngestError("INVALID_V3_CATALOG")
    return catalog


def build_catalog_v3(search_dir,selection_dir,validation_dir,run_id,dataset_id,destination,*,origin="install"):
    roots=list(map(Path,(search_dir,selection_dir,validation_dir)));destination=Path(destination)
    hashes=[file_hash(root/"manifest.json") for root in roots]
    search,selection,validation=[json.loads((root/"manifest.json").read_text()) for root in roots]
    ids=selection["candidate_ids"]
    if (validation.get("stage")!="validation_v3" or not validation.get("family_correction_complete")
            or [row["candidate_id"] for row in validation["results"]]!=ids
            or validation["family_size"]!=len(ids) or validation["priority_ids"]!=selection["priority_ids"]
            or len({search["policy_identity"],selection["policy_identity"],validation["policy_identity"]})!=1):
        raise IngestError("V3_CATALOG_FAMILY_MISMATCH")
    candidates={candidate["candidate_id"]:validate_candidate(candidate) for candidate in selection["candidates"]}
    exploration={row["candidate_id"]:row for row in selection["evaluations"]}
    diagnostic_path=validation_dir/"diagnostics/diagnostics.json"
    diagnostics=json.loads(diagnostic_path.read_text())
    by_candidate={identity:[row for row in diagnostics["rows"] if row["candidate_id"]==identity] for identity in ids}
    destination.mkdir(parents=True,exist_ok=False);details_dir=destination/"details";details_dir.mkdir()
    entries=[];detail_hashes={}
    for result in validation["results"]:
        identity=result["candidate_id"];candidate=candidates[identity];metrics=metrics_projection(result)
        detail={"schema_version":"3.0","analysis_version":ANALYSIS_VERSION,"run_id":str(run_id),"dataset_id":str(dataset_id),
            "candidate_id":identity,"frozen_sha256":validation["frozen_sha256"],"policy_identity":POLICY_IDENTITY,
            "event_spec":event_spec_v3(candidate,origin),"candidate":candidate,"exploration":exploration[identity],
            "validation":{**result,"metrics":metrics},"selection":{"priority":identity in selection["priority_ids"],
                "priority_index":selection["priority_ids"].index(identity) if identity in selection["priority_ids"] else None},
            "diagnostics":by_candidate[identity],"timing_status":"observed"}
        path=details_dir/f"{identity}.json"
        with path.open("x") as stream:json.dump(detail,stream,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False);stream.flush();os.fsync(stream.fileno())
        digest=file_hash(path);detail_hashes[identity]=digest
        entries.append({"candidate_id":identity,"category":candidate["category"],"indicator_type":candidate["indicator_type"],
            "window_hours":candidate["observation_end_hours"],"observation_start_hours":candidate["observation_start_hours"],
            "observation_end_hours":candidate["observation_end_hours"],"decision_time_hours":candidate["decision_time_hours"],
            "trigger_mode":candidate["trigger_mode"],"evidence_status":result["evidence_status"],"reasons":result["reasons"],
            "detail_sha256":digest,"summary":{"event_spec":detail["event_spec"],"family":"compound" if candidate["category"]=="cross_category" else "sequence" if candidate["category"]=="sequence" else "atom",
                "category":candidate["category"],"indicator_type":candidate["indicator_type"],"ad_formats":sorted({clause.get("scope",{}).get("ad_format") for clause in candidate["predicate"].get("clauses",[candidate["predicate"]]) if clause.get("scope",{}).get("ad_format")}),
                "role":None,"selection":detail["selection"],"timing_status":"observed",
                "triggered_users":metrics["groups"]["triggered"]["users"],"untriggered_users":metrics["groups"]["untriggered"]["users"],
                "triggered_arpu_usd":metrics["groups"]["triggered"]["arpu_usd"],"untriggered_arpu_usd":metrics["groups"]["untriggered"]["arpu_usd"],
                "all_arpu_usd":metrics["groups"]["all"]["arpu_usd"],"difference_usd":metrics["comparisons"]["triggered_minus_untriggered"],
                "coverage":metrics["coverage"],"median_seconds":metrics["delay_seconds"]["median"],"p90_seconds":metrics["delay_seconds"]["p90"]}})
    catalog={"schema_version":"3.0","analysis_version":ANALYSIS_VERSION,"run_id":str(run_id),"dataset_id":str(dataset_id),
        "frozen_sha256":validation["frozen_sha256"],"policy_identity":POLICY_IDENTITY,"synthetic":validation["synthetic"],"priority_ids":selection["priority_ids"],
        "entries":entries,"evaluated_count":len(entries),"source_hashes":{"search":hashes[0],"selection":hashes[1],"validation":hashes[2]}}
    validate_catalog_v3(catalog)
    catalog_path=destination/"catalog.json"
    with catalog_path.open("x") as stream:json.dump(catalog,stream,sort_keys=True,indent=2,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    search_log={"schema_version":"3.0","analysis_version":ANALYSIS_VERSION,"discovery_count":search["discovery_count"],
        "validation_count":len(entries),"budget":search["budget"],"thresholds":search["thresholds"],"search_log":search["search_log"],
        "warning":"Discovery results are exploratory and entries outside the frozen Validation Family are not validated."}
    search_path=destination/"search.json"
    with search_path.open("x") as stream:json.dump(search_log,stream,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    points=[]
    for entry,result in zip(entries,validation["results"]):
        observation=result.get("observation") or {"checkpoints":result["checkpoints"]}
        d3=observation["checkpoints"]["d3"];counts=d3["membership_counts"]
        x=d3["comparisons"]["early"]["difference_usd"] if d3["comparisons"] else None
        y=d3["comparisons"]["remaining"]["difference_usd"] if d3["comparisons"] else None
        status="PLOTTED" if entry["decision_time_hours"]<=72 and x is not None and y is not None else ("LATE_INDICATOR_NOT_PLOTTED" if entry["decision_time_hours"]>72 else "NULL_VALUE_NOT_PLOTTED")
        decided=counts["triggered"]+counts["untriggered"]
        points.append({"candidate_id":entry["candidate_id"],"category":entry["category"],"decision_time_hours":entry["decision_time_hours"],
            "x_early_72h_difference_usd":x,"y_remaining_72_168h_difference_usd":y,"triggered_users":counts["triggered"],
            "untriggered_users":counts["untriggered"],"unknown_users":counts["unknown"],"coverage":counts["triggered"]/decided if decided else None,
            "evidence_status":entry["evidence_status"],"detail_sha256":entry["detail_sha256"],"chart_status":status})
    value_map={"schema_version":"3.0","analysis_version":ANALYSIS_VERSION,"chart_type":"candidate_value_map_72h",
        "run_id":str(run_id),"dataset_id":str(dataset_id),"x_interval_hours":[0,72],"y_interval_hours":[72,168],
        "point_encoding":{"color":"single_accent","size":"constant","shape":"circle"},"points":points,
        "plotted_count":sum(p["chart_status"]=="PLOTTED" for p in points),"total_count":len(points),
        "validation_manifest_sha256":hashes[2]}
    value_path=destination/"candidate_value_map_v3.json"
    with value_path.open("x") as stream:json.dump(value_map,stream,sort_keys=True,indent=2,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    if [file_hash(root/"manifest.json") for root in roots]!=hashes:raise IngestError("V3_CATALOG_SOURCE_CHANGED")
    artifacts=[]
    for path in sorted(destination.rglob("*.json")):
        artifacts.append({"name":"candidate_detail" if path.parent==details_dir else path.stem,
            "path":path.relative_to(destination).as_posix(),"sha256":file_hash(path),"size_bytes":path.stat().st_size})
    partial=destination/"manifest.partial.json"
    with partial.open("x") as stream:
        json.dump({"schema_version":"3.0","analysis_version":ANALYSIS_VERSION,"stage":"catalog_v3",
            "run_id":str(run_id),"dataset_id":str(dataset_id),"policy_identity":POLICY_IDENTITY,
            "source_hashes":{"search":hashes[0],"selection":hashes[1],"validation":hashes[2]},
            "evaluated_count":len(entries),"priority_ids":selection["priority_ids"],"artifacts":artifacts},
            stream,sort_keys=True,indent=2,allow_nan=False)
        stream.flush();os.fsync(stream.fileno())
    os.link(partial,destination/"manifest.json");partial.unlink()
    return catalog,value_map
