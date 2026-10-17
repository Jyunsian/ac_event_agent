"""Deterministic exploration-only V3 Validation Family and priority selection."""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from pathlib import Path

from server.analysis.connection import connect
from server.analysis.ingest import IngestError, file_hash
from server.analysis.v3_contract import ANALYSIS_VERSION, MAX_PRIORITY, POLICY_IDENTITY, VALIDATION_LIMIT, validate_candidate
from server.analysis.v3_policy import CATEGORY_ORDER, allocate_by_category

SELECTION_VERSION="3.0"


def _jaccard(left,right):
    union=left|right
    if isinstance(union,int):return (left&right).bit_count()/union.bit_count() if union else 1.0
    return len(left&right)/len(union) if union else 1.0


def _diverse_order(rows,hit_sets,limit=None):
    """Pareto layer first, then exact incremental maximum-overlap ordering."""
    result=[]
    for layer in sorted({row["pareto_layer"] for row in rows}):
        remaining=[row for row in rows if row["pareto_layer"]==layer]
        # Recomputing overlap against every selected row inside the sort key is
        # O(n*k^2) and makes a real 20k Discovery pool impractical.  The maximum
        # overlap is monotone: initialize it once from prior layers, then update
        # it only with the newly selected row.  This is the identical greedy
        # policy in O(n*k), with the same deterministic tie-breaks.
        overlap={row["candidate_id"]:max((_jaccard(hit_sets[row["candidate_id"]],hit_sets[prior["candidate_id"]])
                                           for prior in result),default=0) for row in remaining}
        while remaining and (limit is None or len(result)<limit):
            def key(row):
                return (overlap[row["candidate_id"]],-row["difference_usd"],-row["coverage"],row["p90_seconds"],row["candidate_id"])
            chosen=min(remaining,key=key);result.append(chosen);remaining.remove(chosen)
            chosen_hits=hit_sets[chosen["candidate_id"]]
            for row in remaining:
                identity=row["candidate_id"]
                overlap[identity]=max(overlap[identity],_jaccard(hit_sets[identity],chosen_hits))
        if limit is not None and len(result)>=limit:break
    return result


def select_casual_family(search_dir,destination,*,validation_limit=None,priority_limit=None):
    search_dir,destination=map(Path,(search_dir,destination))
    source=search_dir/"manifest.json";source_hash=file_hash(source)
    try: search=json.loads(source.read_text())
    except (OSError,json.JSONDecodeError) as error:raise IngestError("V3_SEARCH_MANIFEST_INVALID") from error
    if search.get("stage")!="search_v3" or search.get("analysis_version")!=ANALYSIS_VERSION:
        raise IngestError("V3_SEARCH_REQUIRED")
    if search.get("policy_identity")!=POLICY_IDENTITY:raise IngestError("V3_SEARCH_POLICY_MISMATCH")
    membership=search_dir/"memberships.parquet";membership_users=search_dir/"membership_users.parquet"
    artifact=next((item for item in search.get("artifacts",[]) if item.get("name")=="memberships"),None)
    users_artifact=next((item for item in search.get("artifacts",[]) if item.get("name")=="membership_users"),None)
    if (not artifact or artifact.get("path")!="memberships.parquet" or artifact.get("encoding")!="indexed_bitset_v1"
            or file_hash(membership)!=artifact.get("sha256") or not users_artifact
            or users_artifact.get("path")!="membership_users.parquet" or file_hash(membership_users)!=users_artifact.get("sha256")):
        raise IngestError("V3_MEMBERSHIP_CHECKSUM_MISMATCH")
    candidates={candidate["candidate_id"]:validate_candidate(candidate) for candidate in search["candidates"]}
    evaluations={row["candidate_id"]:row for row in search["evaluations"]}
    if set(candidates)!=set(evaluations):raise IngestError("V3_SEARCH_EVALUATION_MISMATCH")
    hit_sets={}
    with connect(config={"memory_limit":"256MB","threads":2}) as c:
        users=c.execute("SELECT bit_index,app_id,user_id FROM read_parquet(?) ORDER BY bit_index",[str(membership_users)]).fetchall()
        if [row[0] for row in users]!=list(range(len(users))) or len(users)!=artifact.get("user_count"):
            raise IngestError("V3_MEMBERSHIP_INDEX_INVALID")
        for identity,bits in c.execute("SELECT candidate_id,triggered_bits FROM read_parquet(?) ORDER BY candidate_id",[str(membership)]).fetchall():
            hit_sets[identity]=int.from_bytes(bits,"little")
    if set(hit_sets)!=set(candidates):raise IngestError("V3_MEMBERSHIP_CANDIDATE_MISMATCH")
    limit=search["config"]["max_candidates"] if validation_limit is None else validation_limit
    if type(limit) is not int or not 0<limit<=VALIDATION_LIMIT:raise IngestError("INVALID_V3_VALIDATION_LIMIT")
    ordered=[]
    for category in CATEGORY_ORDER:
        rows=[]
        for identity,candidate in candidates.items():
            if candidate["category"]!=category:continue
            row=evaluations[identity]
            if any(row.get(key) is None or not math.isfinite(row[key]) for key in ("difference_usd","coverage","p90_seconds")):
                continue
            rows.append(row)
        for rank,row in enumerate(_diverse_order(rows,hit_sets,limit)):
            ordered.append({"candidate_id":row["candidate_id"],"category":category,
                            "_selection_rank":rank,"candidate":candidates[row["candidate_id"]],"evaluation":row})
    family,_excluded,budget=allocate_by_category(ordered,"validation",limit)
    family.sort(key=lambda row:(CATEGORY_ORDER.index(row["category"]),row["_selection_rank"],row["candidate_id"]))
    selected_ids={row["candidate_id"] for row in family}
    selection_log=[{"candidate_id":identity,"primary_reason":"VALIDATION_CATEGORY_BUDGET"}
                   for identity in sorted(set(candidates)-selected_ids)]
    # First cover categories, then fill by diversity across the full selected set.
    requested=search["config"]["max_finalists"] if priority_limit is None else priority_limit
    if type(requested) is not int or not 0<=requested<=MAX_PRIORITY:raise IngestError("INVALID_V3_PRIORITY_LIMIT")
    priority=[]
    for category in CATEGORY_ORDER:
        candidate=next((row for row in family if row["category"]==category),None)
        if candidate and len(priority)<requested:priority.append(candidate["candidate_id"])
    remaining=[row for row in family if row["candidate_id"] not in priority]
    while remaining and len(priority)<requested:
        def key(row):
            overlap=max((_jaccard(hit_sets[row["candidate_id"]],hit_sets[identity]) for identity in priority),default=0)
            evaluation=row["evaluation"]
            return (overlap,evaluation.get("pareto_layer",math.inf),evaluation["p90_seconds"],row["candidate_id"])
        chosen=min(remaining,key=key);priority.append(chosen["candidate_id"]);remaining.remove(chosen)
    output={"schema_version":"3.0","analysis_version":ANALYSIS_VERSION,"stage":"selection_v3",
        "selection_version":SELECTION_VERSION,"search_manifest_sha256":source_hash,
        "membership_sha256":artifact["sha256"],"feature_id":search["feature_id"],"split_id":search["split_id"],
        "exploration_scope":search["exploration_scope"],"policy_identity":POLICY_IDENTITY,
        "min_group_users":search["config"]["min_group_users"],"seed":search["config"]["seed"],
        "family_size":len(family),"budget":budget,"candidate_ids":[row["candidate_id"] for row in family],
        "priority_ids":priority,"candidates":[row["candidate"] for row in family],
        "evaluations":[row["evaluation"] for row in family],"selection_log":selection_log,
        "ranking_note":"Exploration-only Pareto layers and membership diversity; not validation or causal uplift."}
    if file_hash(source)!=source_hash or file_hash(membership)!=artifact["sha256"]:
        raise IngestError("V3_SEARCH_CHANGED_DURING_SELECTION")
    destination.mkdir(parents=True,exist_ok=False)
    partial=destination/"manifest.partial.json"
    with partial.open("x") as stream:
        json.dump(output,stream,sort_keys=True,indent=2,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    os.link(partial,destination/"manifest.json");partial.unlink()
    return output
