import json

import pytest

from server.analysis.freeze import freeze_candidates
from server.analysis.features import build_features
from server.analysis.ingest import IngestError, canonicalize
from server.analysis.exploration import build_search_features
from server.analysis.targets import build_targets
from server.analysis.search import generate_candidates
from server.analysis.validation import validate_frozen
from tests.test_search import CONFIG, prepare
from tests.test_quality import EXPORT
from tests.test_ingest import MAPPING, write_source


def setup_case(root, missing=False):
    prepare(root, missing_holdout_revenue=missing)
    search = generate_candidates(root/"exploration/features", root/"targets", CONFIG, root/"search")
    candidate = next(p for p in search["candidates"] if p["window_hours"] == 3 and
                     p["predicate"] == {"op": "count", "threshold": 1})
    receipt = freeze_candidates(root/"search", [candidate["candidate_id"]], root/"freeze")
    return receipt, candidate


def test_frozen_holdout_real_parquet_readback_and_tamper_rejection(tmp_path):
    root = tmp_path/"case"
    receipt, candidate = setup_case(root)
    result = validate_frozen(root/"normalized", root/"features", root/"targets", root/"freeze", receipt["sha256"], root/"validation")
    entry = result["results"][0]
    assert entry["candidate_id"] == candidate["candidate_id"]
    assert entry["metrics"]["groups"]["all"]["users"] == 2
    assert entry["metrics"]["groups"]["all"]["arpu_usd"] == pytest.approx(.06)
    assert entry["metrics"]["coverage"] == 1
    assert entry["metrics"]["delay_seconds"]["median"] == 5400
    assert entry["evidence_status"] == "insufficient_data"
    assert result == json.loads((root/"validation/manifest.json").read_text())
    (root/"freeze/frozen.json").write_text("{}")
    with pytest.raises(IngestError, match="FROZEN_CONTRACT_CHANGED"):
        validate_frozen(root/"normalized", root/"features", root/"targets", root/"freeze", receipt["sha256"], root/"bad")
    assert not (root/"bad").exists()


def test_holdout_missing_revenue_never_validates(tmp_path):
    root = tmp_path/"case"
    receipt, _ = setup_case(root, missing=True)
    result = validate_frozen(root/"normalized", root/"features", root/"targets", root/"freeze", receipt["sha256"], root/"validation")
    metrics = result["results"][0]["metrics"]
    assert metrics["groups"]["all"]["users"] == 2
    assert metrics["groups"]["all"]["arpu_usd"] is None
    assert "QUALITY_GATE_FAILED" in metrics["reasons"]
    assert "UNKNOWN_REVENUE" in metrics["reasons"]
    family_receipt=freeze_candidates(root/'search',[],root/'family-freeze',full_family=True)
    family=validate_frozen(root/'normalized',root/'features',root/'targets',root/'family-freeze',
                           family_receipt['sha256'],root/'family-validation')
    assert family['family_correction_complete'] and family['priority_ids']==[]
    disabled=[r for r in family['results'] if 'FEATURE_CAPABILITY_DISABLED' in r['reasons']]
    assert disabled
    for row in disabled:
        assert row['source_diagnostics'] is None and row['revenue_decomposition'] is None
        assert row['diagnostic_unavailable_reason']=='TRIGGER_MEMBERSHIP_UNAVAILABLE'
        assert row['inference']['p_value']==1 and not row['inference']['passed']


def test_changed_revenue_timing_and_corrupt_target_are_rejected(tmp_path):
    root = tmp_path/"case"
    receipt, _ = setup_case(root)
    build_features(root/"normalized", {**EXPORT, "revenue_timing": "immediate"}, root/"different_features")
    with pytest.raises(IngestError, match="VALIDATION_SOURCE_OR_SPLIT_MISMATCH"):
        validate_frozen(root/"normalized", root/"different_features", root/"targets", root/"freeze", receipt["sha256"], root/"wrong")
    (root/"targets/targets.parquet").write_bytes(b"synthetic corrupted target")
    with pytest.raises(IngestError, match="VALIDATION_CHECKSUM_MISMATCH"):
        validate_frozen(root/"normalized", root/"features", root/"targets", root/"freeze", receipt["sha256"], root/"bad")
    assert not (root/"wrong").exists() and not (root/"bad").exists()


@pytest.mark.parametrize("days,expected", [(4, "historically_validated"), (2, "insufficient_data")])
def test_full_parquet_sufficient_sample_or_no_holdout(tmp_path, days, expected):
    users, events = [], []
    export = {**EXPORT, "complete_through": "2026-01-20T00:00:00Z", "exported_at": "2026-01-21T00:00:00Z"}
    for day in range(1, days+1):
        for i in range(100):
            identity = f"day{day}-{i}"
            users.append({"app_id": "synthetic", "user_id": identity,
                          "installed_at": f"2026-01-{day:02}T00:00:00Z", "platform": "android"})
            if i<50:
                events.append({"app_id": "synthetic", "user_id": identity, "event_id": identity+"-ad",
                               "event_name": "ad_impression", "event_time": f"2026-01-{day:02}T01:00:00Z",
                               "available_at": f"2026-01-{day:02}T01:00:00Z", "revenue_usd": 2, "ad_format": "rewarded"})
    canonicalize([write_source(tmp_path, "users", users), write_source(tmp_path, "events", events)], MAPPING, tmp_path/"normalized")
    build_features(tmp_path/"normalized", export, tmp_path/"features")
    build_targets(tmp_path/"normalized", export, tmp_path/"targets")
    build_search_features(tmp_path/"normalized", tmp_path/"targets", export, tmp_path/"exploration")
    search = generate_candidates(tmp_path/"exploration/features", tmp_path/"targets", CONFIG, tmp_path/"search")
    chosen = next(p for p in search["candidates"] if p["window_hours"] == 3 and p["predicate"] == {"op": "count", "threshold": 1})
    receipt = freeze_candidates(tmp_path/"search", [chosen["candidate_id"]], tmp_path/"freeze")
    result = validate_frozen(tmp_path/"normalized", tmp_path/"features", tmp_path/"targets", tmp_path/"freeze", receipt["sha256"], tmp_path/"validation")
    metrics = result["results"][0]["metrics"]
    assert metrics["evidence_status"] == expected
    if days == 4:
        assert metrics["groups"]["all"]["users"] == 200
        assert metrics["groups"]["triggered"]["users"] == metrics["groups"]["untriggered"]["users"] == 100
        assert metrics["groups"]["all"]["arpu_usd"] == 1
        assert metrics["bootstrap"]["intervals"]["triggered_minus_untriggered"]["lower"] == 2
        assert len(metrics["days"]) == 2
    else:
        assert metrics["groups"]["all"]["users"] == 0
        assert metrics["coverage"] is None
        assert metrics["groups"]["all"]["arpu_usd"] is None


def test_manifest_changed_during_validation_is_not_published(tmp_path, monkeypatch):
    import server.analysis.validation as module
    root = tmp_path/"case"
    receipt, _ = setup_case(root)
    original = module.summarize_users
    def change_metadata(*args, **kwargs):
        result = original(*args, **kwargs)
        path = root/"targets/manifest.json"
        manifest = json.loads(path.read_text())
        manifest["unexpected_mutation"] = True
        path.write_text(json.dumps(manifest))
        return result
    monkeypatch.setattr(module, "summarize_users", change_metadata)
    with pytest.raises(IngestError, match="VALIDATION_SOURCE_CHANGED"):
        validate_frozen(root/"normalized", root/"features", root/"targets", root/"freeze", receipt["sha256"], root/"result")
    assert not (root/"result/manifest.json").exists()


def test_family_membership_memo_matches_uncached_all_evidence(tmp_path,monkeypatch):
    import server.analysis.validation as module
    import server.analysis.revenue_diagnostics as revenue_module
    original_decomposition=revenue_module.decompose_prepared_membership
    decomposition_calls=[]
    def observed_decomposition(*args,**kwargs):
        decomposition_calls.append(1)
        return original_decomposition(*args,**kwargs)
    monkeypatch.setattr(revenue_module,'decompose_prepared_membership',observed_decomposition)
    root=tmp_path/'case';prepare(root)
    search=generate_candidates(root/'exploration/features',root/'targets',CONFIG,root/'search')
    receipt=freeze_candidates(root/'search',[search['candidates'][0]['candidate_id']],root/'freeze',full_family=True)
    original=module.summarize_users;calls=[]
    def observed(*args,**kwargs):
        calls.append(1)
        return original(*args,**kwargs)
    monkeypatch.setattr(module,'summarize_users',observed)
    args=(root/'normalized',root/'features',root/'targets',root/'freeze',receipt['sha256'])
    cached=validate_frozen(*args,root/'cached')
    cached_calls=len(calls);calls.clear()
    cached_decompositions=len(decomposition_calls);decomposition_calls.clear()
    memo=module.MembershipEvidenceMemo
    monkeypatch.setattr(module,'MembershipEvidenceMemo',lambda n:memo(n,max_entries=0))
    uncached=validate_frozen(*args,root/'uncached')
    assert cached_calls<len(calls)
    assert cached_decompositions<len(decomposition_calls)
    assert cached==uncached  # Includes source, days, delay, windows, landmarks and Holm.
    assert len(cached['results'])==len(search['candidates'])
    # Same membership counts must not force shared trigger timing.
    from collections import defaultdict
    delay_sets=defaultdict(set)
    for row in cached['results']:
        if row['metrics']:
            metric=row['metrics']
            delay_sets[metric['groups']['triggered']['users']].add(
                json.dumps(metric['delay_seconds'],sort_keys=True))
    assert any(len(values)>1 for values in delay_sets.values())
