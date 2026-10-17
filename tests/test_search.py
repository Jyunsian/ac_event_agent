import json
from pathlib import Path
import pytest

from server.analysis.features import build_features
from server.analysis.exploration import build_search_features
from server.analysis.ingest import IngestError, canonicalize
from server.analysis.search import generate_candidates
from server.analysis.targets import build_targets
from tests.test_ingest import HAND, MAPPING, write_source
from tests.test_quality import EXPORT

# This module is the explicit V2 regression fixture. Product defaults can move
# forward without silently changing the historical pipeline under test.
CONFIG = {**json.loads(Path("contracts/defaults.json").read_text()), "analysis_version":"2.0"}


def prepare(root, holdout_revenue=None, missing_holdout_revenue=False, missing_holdout_session=False):
    root.mkdir()
    users = json.loads((HAND/"users.json").read_text())
    events = json.loads((HAND/"events.json").read_text())
    if holdout_revenue is not None or missing_holdout_revenue:
        events = [{**event, "revenue_usd": holdout_revenue} if event["user_id"] in ("u4", "u5")
                  and event["event_name"] == "ad_impression" else event for event in events]
    if missing_holdout_session:
        events = [{**event, "session_id": None} if event["user_id"] == "u5"
                  and event["event_name"] == "session_start" else event for event in events]
    canonicalize([write_source(root, "users", users), write_source(root, "events", events)], MAPPING, root/"normalized")
    build_features(root/"normalized", EXPORT, root/"features")
    build_targets(root/"normalized", EXPORT, root/"targets")
    build_search_features(root/"normalized", root/"targets", EXPORT, root/"exploration")


def test_search_all_windows_stable_ids_and_explicit_cap(tmp_path):
    prepare(tmp_path/"data")
    root = tmp_path/"data"
    first = generate_candidates(root/"exploration/features", root/"targets", CONFIG, tmp_path/"first")
    second = generate_candidates(root/"exploration/features", root/"targets", CONFIG, tmp_path/"second")
    assert first == second
    assert first["searched_windows"] == [1, 3, 6, 12, 24, 48, 72, 96, 120, 144]
    assert {p["window_hours"] for p in first["candidates"]} == set(CONFIG['windows_hours'])
    assert first["selected_count"] <= 2000
    assert len({p["candidate_id"] for p in first["candidates"]}) == first["selected_count"]
    # Tiny fixture cannot satisfy the new parent sample gate; no forced compounds.
    assert all(not entry['priority_ids'] for entry in first['compound_parents'].values())
    assert any(a['support']==0 for a in first['atom_ranking'])
    capped = generate_candidates(root/"exploration/features", root/"targets", {**CONFIG, "max_candidates": 5}, tmp_path/"capped")
    assert capped["selected_count"] == 5 and capped["truncated"]
    # Round-robin is within each family; tiny budgets no longer imply one per window globally.
    assert capped['budget']['allocated']=={'atom':4,'compound':0,'sequence':1}
    assert sum(p["reason"] == "MAX_CANDIDATES_LIMIT" for p in capped["pruning"]) == capped["unique_before_cap"]-5


def test_configured_thresholds_are_materialized_without_holdout_tuning(tmp_path):
    outputs=[]
    for name,revenue in (("normal",None),("changed",999)):
        root=tmp_path/name;prepare(root,revenue)
        outputs.append(generate_candidates(root/"exploration/features",root/"targets",
            {**CONFIG,'windows_hours':[3],'thresholds':{'count':[2],'revenue_sum':[.02]}},root/'search'))
    assert outputs[0]['candidates']==outputs[1]['candidates']
    assert outputs[0]['thresholds']==outputs[1]['thresholds']
    grids=outputs[0]['thresholds']
    assert all(row['values']==[2] and row['source']=='configured_grid' for row in grids if row['metric']=='count')
    assert all(row['values']==[.02] and row['source']=='configured_grid' for row in grids if row['metric']=='revenue_sum')
    # Hand fixture has supported count and revenue predicates in the 3h window.
    assert any(c['predicate']=={'op':'count','threshold':2} for c in outputs[0]['candidates'])
    assert any(c['predicate']=={'op':'revenue_sum','threshold':.02} for c in outputs[0]['candidates'])


def test_holdout_revenue_cannot_change_candidates_thresholds_or_ranking(tmp_path):
    results = []
    for name, revenue in (("base", None), ("changed", 999)):
        root = tmp_path/name
        prepare(root, revenue)
        results.append(generate_candidates(root/"exploration/features", root/"targets", CONFIG, root/"search"))
    for key in ("candidates", "thresholds", "atom_ranking", "pruning"):
        assert results[0][key] == results[1][key]
    revenue_grids = [row for row in results[1]["thresholds"] if row["metric"] == "revenue_sum"]
    # Preserve the raw quantile precision; binary interpolation can exceed .05 by one ULP.
    assert revenue_grids and max(v for row in revenue_grids for v in row["values"]) <= .05+1e-15


def test_holdout_missingness_cannot_change_exploration_search(tmp_path):
    results = []
    for name, missing in (("base", False), ("missing", True)):
        root = tmp_path/name
        prepare(root, missing_holdout_revenue=missing)
        results.append(generate_candidates(root/"exploration/features", root/"targets", CONFIG, root/"search"))
    assert results[0]["thresholds"] == results[1]["thresholds"]
    assert results[0]["candidates"] == results[1]["candidates"]


def test_holdout_session_missingness_does_not_disable_exploration(tmp_path):
    results = []
    for name, missing in (("base", False), ("missing", True)):
        root = tmp_path/name
        prepare(root, missing_holdout_session=missing)
        results.append(generate_candidates(root/"exploration/features", root/"targets", CONFIG, root/"search"))
    for key in ("thresholds", "candidates", "atom_ranking", "pruning"):
        assert results[0][key] == results[1][key]
    global_flags = json.loads((tmp_path/"missing/features/manifest.json").read_text())["capabilities"]
    scoped_flags = json.loads((tmp_path/"missing/exploration/features/manifest.json").read_text())["capabilities"]
    assert not global_flags["session_count"]["enabled"]
    assert scoped_flags["session_count"]["enabled"]


def test_search_rejects_global_features_and_corrupt_scoped_inputs(tmp_path):
    root = tmp_path/"data"
    prepare(root)
    with pytest.raises(IngestError, match="EXPLORATION_SCOPED_FEATURES_REQUIRED"):
        generate_candidates(root/"features", root/"targets", CONFIG, tmp_path/"global")
    (root/"exploration/features/snapshots.parquet").write_bytes(b"corrupted synthetic snapshots")
    with pytest.raises(IngestError, match="SEARCH_CHECKSUM_MISMATCH"):
        generate_candidates(root/"exploration/features", root/"targets", CONFIG, tmp_path/"corrupt")
    assert not (tmp_path/"corrupt").exists()
