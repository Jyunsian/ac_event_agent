import json

import pytest

from server.analysis.diagnostics import build_diagnostics
from server.analysis.features import build_features
from server.analysis.ingest import IngestError, canonicalize
from server.analysis.predicates import evaluate_candidates
from server.analysis.targets import build_targets
from tests.test_ingest import MAPPING, sources
from tests.test_predicates import candidate
from tests.test_quality import EXPORT


def prepare(root, extras=None):
    canonicalize(sources(root, extras=extras), MAPPING, root/"normalized")
    build_features(root/"normalized", EXPORT, root/"features")
    build_targets(root/"normalized", EXPORT, root/"targets")
    candidates = [candidate(f"count{n}", {"op": "count", "threshold": n}) for n in (1, 3, 5, 20)]
    evaluate_candidates(root/"normalized", root/"features", candidates, root/"triggers")


def read(root, name):
    return json.loads((root/f"{name}.json").read_text())


def test_overlap_curve_and_revenue_hand_truth(tmp_path):
    prepare(tmp_path)
    result = build_diagnostics(tmp_path/"normalized", tmp_path/"features", tmp_path/"targets", tmp_path/"triggers",
                               tmp_path/"diagnostics", split="all_mature", landmarks=(3, 24, 72))
    overlap = read(tmp_path/"diagnostics", "overlap")
    pairs = {(row["a"],row["b"]): row for row in overlap["pairs"]}
    pair = pairs["count1","count5"]
    assert pair["intersection"] == 1 and pair["union"] == 4
    assert pair["jaccard"] == .25 and pair["fraction_a_in_b"] == .25 and pair["fraction_b_in_a"] == 1
    assert pairs["count3","count5"]["same_observed_users"]
    assert pairs["count20","count20"]["jaccard"] is None
    assert pairs["count20","count20"]["empty_union"]
    points = read(tmp_path/"diagnostics", "sensitivity")["points"]
    assert [p["coverage"] for p in points] == [.8, .2, .2, 0]
    assert {p["cohort_users"] for p in points} == {5}
    assert {p["cohort_id"] for p in points} == {result["cohort_id"]}
    assert points[2]["triggered_arpu_usd"] == pytest.approx(.15)
    data = read(tmp_path/"diagnostics", "landmark")
    post = {p["candidate_id"]: p for p in data["post_trigger"]}
    assert post["count5"]["revenue_usd"] == pytest.approx(.1)
    assert post["count1"]["revenue_usd"] == pytest.approx(.17)
    lm = {(p["candidate_id"],p["landmark_hours"]): p for p in data["landmarks"]}
    assert lm["count1",24]["triggered"]["users"] == 4
    assert lm["count1",24]["triggered"]["arpu_usd"] == pytest.approx(.025)
    # count3 hits exactly at 3h: not known strictly before the 3h landmark.
    assert lm["count3",3]["triggered"]["users"] == 0
    assert lm["count5",3]["untriggered"]["users"] == 5
    assert lm["count5",3]["untriggered"]["revenue_usd"] == pytest.approx(.13)
    assert data["evidence_status"] == "exploratory"


def test_missing_post_trigger_revenue_is_not_zero(tmp_path):
    extra = {"app_id": "synthetic", "user_id": "u1", "event_id": "unknown-later",
             "event_name": "ad_impression", "event_time": "2026-01-01T06:00:00Z",
             "available_at": "2026-01-01T06:00:00Z", "revenue_usd": None, "ad_format": "rewarded"}
    prepare(tmp_path, [extra])
    build_diagnostics(tmp_path/"normalized", tmp_path/"features", tmp_path/"targets", tmp_path/"triggers",
                      tmp_path/"diagnostics", split="all_mature")
    post = {p["candidate_id"]: p for p in read(tmp_path/"diagnostics", "landmark")["post_trigger"]}
    assert post["count5"]["unknown_revenue_users"] == 1
    assert post["count5"]["revenue_usd"] is None
    points = read(tmp_path/"diagnostics", "sensitivity")["points"]
    assert points[2]["triggered_arpu_usd"] is None


def test_reproducible_holdout_denominators_and_corruption_rejected(tmp_path):
    prepare(tmp_path)
    arguments = (tmp_path/"normalized", tmp_path/"features", tmp_path/"targets", tmp_path/"triggers")
    first = build_diagnostics(*arguments, tmp_path/"first")
    second = build_diagnostics(*arguments, tmp_path/"second")
    assert first == second
    assert first["cohort_users"] == 2
    pairs = read(tmp_path/"first", "overlap")["pairs"]
    assert pairs[0]["a_users"] == 2
    (tmp_path/"triggers/triggers.parquet").write_bytes(b"corrupt synthetic triggers")
    with pytest.raises(IngestError, match="CHECKSUM_MISMATCH"):
        build_diagnostics(*arguments, tmp_path/"bad")
    assert not (tmp_path/"bad").exists()


def test_source_change_during_diagnostics_prevents_publication(tmp_path, monkeypatch):
    import server.analysis.diagnostics as module
    prepare(tmp_path)
    real_hash = module.file_hash
    calls = 0
    def modified(path):
        nonlocal calls
        if path == tmp_path/"targets/manifest.json":
            calls += 1
            if calls == 2:
                path.write_text(path.read_text()+"\n")
        return real_hash(path)
    monkeypatch.setattr(module, "file_hash", modified)
    with pytest.raises(IngestError, match="DIAGNOSTIC_SOURCE_CHANGED"):
        build_diagnostics(tmp_path/"normalized", tmp_path/"features", tmp_path/"targets", tmp_path/"triggers", tmp_path/"bad")
    assert not (tmp_path/"bad/manifest.json").exists()
