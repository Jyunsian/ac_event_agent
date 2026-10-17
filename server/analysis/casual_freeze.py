"""Immutable V3 Validation Family receipt created before holdout is read."""
from __future__ import annotations

import json
import os
from pathlib import Path

from server.analysis.ingest import IngestError, file_hash
from server.analysis.v3_contract import (
    ANALYSIS_VERSION, BOOTSTRAP_REPLICATES, MAX_PRIORITY, POLICY_IDENTITY,
    VALIDATION_LIMIT, validate_candidate,
)

FREEZE_VERSION="3.0"


def freeze_casual_family(selection_dir,destination):
    selection_dir,destination=map(Path,(selection_dir,destination))
    source=selection_dir/"manifest.json";source_hash=file_hash(source)
    try: selection=json.loads(source.read_text())
    except (OSError,json.JSONDecodeError) as error:raise IngestError("V3_SELECTION_MANIFEST_INVALID") from error
    candidates=selection.get("candidates",[]);ids=[candidate.get("candidate_id") for candidate in candidates]
    priority=selection.get("priority_ids",[])
    if (selection.get("stage")!="selection_v3" or selection.get("analysis_version")!=ANALYSIS_VERSION
            or selection.get("policy_identity")!=POLICY_IDENTITY or selection.get("candidate_ids")!=ids
            or selection.get("family_size")!=len(ids) or len(ids)>VALIDATION_LIMIT or len(ids)!=len(set(ids))
            or not isinstance(priority,list) or len(priority)>MAX_PRIORITY or len(priority)!=len(set(priority))
            or not set(priority)<=set(ids)):
        raise IngestError("INVALID_V3_SELECTION")
    for candidate in candidates:validate_candidate(candidate)
    receipt={"schema_version":"3.0","analysis_version":ANALYSIS_VERSION,"stage":"validation_freeze_v3",
        "freeze_version":FREEZE_VERSION,"selection_manifest_sha256":source_hash,
        "search_manifest_sha256":selection["search_manifest_sha256"],"membership_sha256":selection["membership_sha256"],
        "feature_id":selection["feature_id"],"split_id":selection["split_id"],
        "exploration_scope":selection["exploration_scope"],"policy_identity":POLICY_IDENTITY,
        "family_size":len(candidates),"candidate_ids":ids,"priority_ids":priority,"candidates":candidates,
        "rules":{"bootstrap_replicates":BOOTSTRAP_REPLICATES,"test":"welch_one_sided_greater",
                 "multiplicity":"holm_full_frozen_family","untestable_p":1,"alpha":.05,
                 "seed":selection["seed"],"min_group_users":selection["min_group_users"],
                 "diagnostic_windows_hours":[48,72,168],
                 "interpretation":"historical_association_not_causal"}}
    if file_hash(source)!=source_hash:raise IngestError("V3_SELECTION_CHANGED_DURING_FREEZE")
    destination.mkdir(parents=True,exist_ok=False)
    partial=destination/"frozen.partial.json"
    with partial.open("x") as stream:
        json.dump(receipt,stream,sort_keys=True,indent=2,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    os.link(partial,destination/"frozen.json");partial.unlink()
    return {"path":"frozen.json","sha256":file_hash(destination/"frozen.json"),"size_bytes":(destination/"frozen.json").stat().st_size}


def load_casual_freeze(directory,expected_sha256):
    path=Path(directory)/"frozen.json"
    if file_hash(path)!=expected_sha256:raise IngestError("V3_FROZEN_CONTRACT_CHANGED")
    value=json.loads(path.read_text())
    ids=[candidate.get("candidate_id") for candidate in value.get("candidates",[])]
    if (value.get("stage")!="validation_freeze_v3" or value.get("freeze_version")!=FREEZE_VERSION
            or value.get("analysis_version")!=ANALYSIS_VERSION or value.get("policy_identity")!=POLICY_IDENTITY
            or value.get("candidate_ids")!=ids or value.get("family_size")!=len(ids) or len(ids)>VALIDATION_LIMIT
            or len(set(ids))!=len(ids) or len(value.get("priority_ids",[]))>MAX_PRIORITY
            or not set(value.get("priority_ids",[]))<=set(ids)):
        raise IngestError("INVALID_V3_FROZEN_CONTRACT")
    rules=value.get("rules",{})
    expected={"bootstrap_replicates":1000,"test":"welch_one_sided_greater","multiplicity":"holm_full_frozen_family",
              "untestable_p":1,"alpha":.05,"diagnostic_windows_hours":[48,72,168],
              "interpretation":"historical_association_not_causal"}
    if any(rules.get(key)!=expected_value for key,expected_value in expected.items()) or type(rules.get("seed")) is not int or type(rules.get("min_group_users")) is not int or rules["min_group_users"]<2:
        raise IngestError("INVALID_V3_FROZEN_RULES")
    for candidate in value["candidates"]:validate_candidate(candidate)
    return value
