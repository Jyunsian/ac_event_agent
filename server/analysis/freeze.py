"""Immutable candidate/rule contract, created without reading holdout targets."""
import json
import os
from pathlib import Path

from server.analysis.ingest import IngestError, file_hash
from server.analysis.predicates import validate_candidate


def freeze_candidates(search_dir, candidate_ids, destination, *, full_family=False):
    search_dir, destination = Path(search_dir), Path(destination)
    source = search_dir/"manifest.json"
    digest = file_hash(source)
    search = json.loads(source.read_text())
    if (not isinstance(candidate_ids, list) or not all(isinstance(identity, str) for identity in candidate_ids)
            or len(candidate_ids) != len(set(candidate_ids))
            or len(candidate_ids) > search["config"]["max_finalists"]):
        raise IngestError("INVALID_FINALIST_SELECTION")
    available = {candidate["candidate_id"]: candidate for candidate in search["candidates"]}
    if len(available) != len(search["candidates"]) or any(identity not in available for identity in candidate_ids):
        raise IngestError("FINALIST_NOT_IN_SEARCH")
    if full_family and (len(available)>min(2000,search['config']['max_candidates'])
                        or any(available[i]['window_hours']>=168 for i in candidate_ids)):
        raise IngestError('INVALID_FROZEN_FAMILY')
    selected = list(available.values()) if full_family else [available[identity] for identity in candidate_ids]
    for candidate in selected:
        validate_candidate(candidate)
    config = search["config"]
    contract = {"schema_version": "1.0", "stage": "frozen_candidates", "freeze_version": "1.0",
                "synthetic": search["synthetic"], "search_manifest_sha256": digest,
                "feature_id": search["feature_id"], "split_id": search["split_id"],
                "source_manifest_sha256": search["source_manifest_sha256"],
                "export_metadata": search["export_metadata"],
                "candidates": selected,
                "rules": {"seed": config["seed"], "bootstrap_replicates": config["bootstrap_replicates"],
                          "min_group_users": config["min_group_users"], "min_validation_days": 2,
                          "min_group_users_per_day": 20, "confidence_level": .95,
                          "daily_difference": "positive_on_all_observed_days",
                          "difference_interval_lower": "strictly_positive",
                          "interpretation": "descriptive_historical_association_not_causal_or_multiplicity_corrected"}}
    if full_family:
        contract.update(freeze_version='2.0',priority_ids=list(candidate_ids),family_size=len(selected),
                        diagnostic_windows_hours=[24,72,144])
        contract['rules'].update(test='welch_one_sided_greater',multiplicity='holm',alpha=.05,
                                 untestable_p=1,interpretation='historical_association_not_causal',
                                 family_scope='all_frozen_candidates')
    if file_hash(source) != digest:
        raise IngestError("SEARCH_CHANGED_DURING_FREEZE")
    destination.mkdir(parents=True, exist_ok=False)
    partial = destination/"frozen.partial.json"
    with partial.open("x") as stream:
        json.dump(contract, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    path = destination/"frozen.json"
    os.link(partial, path)
    partial.unlink()
    return {"path": path.name, "sha256": file_hash(path), "size_bytes": path.stat().st_size}


def load_frozen(directory, expected_sha256, *, candidates=None):
    path = Path(directory)/"frozen.json"
    if file_hash(path) != expected_sha256:
        raise IngestError("FROZEN_CONTRACT_CHANGED")
    contract = json.loads(path.read_text())
    if contract.get("stage") != "frozen_candidates" or contract.get("freeze_version") not in ('1.0','2.0'):
        raise IngestError("INVALID_FROZEN_CONTRACT")
    if contract['freeze_version']=='2.0':
        rules=contract.get('rules',{})
        if any(rules.get(k)!=v for k,v in {'test':'welch_one_sided_greater','multiplicity':'holm',
               'alpha':.05,'untestable_p':1,'family_scope':'all_frozen_candidates'}.items()):
            raise IngestError('INVALID_FROZEN_RULES')
        ids=[c['candidate_id'] for c in contract['candidates']]
        priority=contract.get('priority_ids')
        if (len(set(ids))!=len(ids) or contract.get('family_size')!=len(ids) or len(ids)>2000
                or not isinstance(priority,list) or len(priority)>10 or len(set(priority))!=len(priority)
                or not set(priority)<=set(ids) or contract.get('diagnostic_windows_hours')!=[24,72,144]):
            raise IngestError('INVALID_FROZEN_FAMILY')
        for candidate in contract['candidates']:
            validate_candidate(candidate)
            if candidate['candidate_id'] in priority and candidate['window_hours']>=168:
                raise IngestError('INVALID_FROZEN_FAMILY')
    if candidates is not None and candidates != contract["candidates"]:
        raise IngestError("FROZEN_CANDIDATES_MISMATCH")
    return contract
