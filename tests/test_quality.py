import json
from pathlib import Path
import pytest

from server.analysis.ingest import IngestError, canonicalize
from server.analysis.quality import build_quality
from tests.test_ingest import HAND, MAPPING, sources, write_source

EXPORT = json.loads((HAND/"export.json").read_text())


def test_hand_quality_counts_and_capabilities(tmp_path):
    canonicalize(sources(tmp_path), MAPPING, tmp_path/"normalized")
    quality, profile = build_quality(tmp_path/"normalized", EXPORT, tmp_path/"quality")
    assert quality["zero_event_users"] == 1
    assert quality["counts"]["users"]["retained_rows"] == 6
    assert quality["excluded_input_rows"] == {"users": 0, "events": 1}
    assert quality["missing"]["ad_revenue"] == 0
    assert quality["normal_recommendations_allowed"] is True
    assert all(flag["enabled"] for flag in quality["capabilities"].values())
    assert quality["capabilities"] == profile["capabilities"]


def test_missing_session_only_disables_related_capabilities(tmp_path):
    users = json.loads((HAND/"users.json").read_text())
    events = json.loads((HAND/"events.json").read_text())
    for event in events:
        if event["event_name"] == "session_start":
            event["session_id"] = None
    data = [write_source(tmp_path, "users", users), write_source(tmp_path, "events", events)]
    canonicalize(data, MAPPING, tmp_path/"normalized")
    quality, _ = build_quality(tmp_path/"normalized", EXPORT, tmp_path/"quality")
    assert quality["normal_recommendations_allowed"] is True
    assert quality["capabilities"]["session_count"]["enabled"] is False
    assert quality["capabilities"]["engaged_seconds"]["enabled"] is False
    assert quality["capabilities"]["revenue_analysis"]["enabled"] is True


def test_null_revenue_blocks_recommendations_and_unknown_timing_blocks_trigger(tmp_path):
    edge = json.loads((HAND/"edge_cases.json").read_text())[0]["event"]
    canonicalize(sources(tmp_path, extras=[edge]), MAPPING, tmp_path/"normalized")
    quality, _ = build_quality(tmp_path/"normalized", {**EXPORT, "revenue_timing": "unknown"}, tmp_path/"quality")
    assert quality["missing"]["ad_revenue"] == 1
    assert quality["normal_recommendations_allowed"] is False
    assert "MISSING_AD_REVENUE" in quality["capabilities"]["revenue_analysis"]["reasons"]
    assert "REVENUE_AVAILABILITY_UNKNOWN" in quality["capabilities"]["revenue_trigger"]["reasons"]


@pytest.mark.parametrize("index,reason", [(1, "CORRECTION_UNSUPPORTED"), (2, "QUARANTINED_IDENTITIES")])
def test_correction_and_conflict_block_normal_recommendations(tmp_path, index, reason):
    edge = json.loads((HAND/"edge_cases.json").read_text())[index]["event"]
    canonicalize(sources(tmp_path, extras=[edge]), MAPPING, tmp_path/"normalized")
    quality, _ = build_quality(tmp_path/"normalized", EXPORT, tmp_path/"quality")
    assert not quality["normal_recommendations_allowed"]
    assert reason in quality["capabilities"]["revenue_analysis"]["reasons"]
    if index == 1:
        assert quality["negative_revenue_events"] == 1


@pytest.mark.parametrize("fault", ["missing", "incomplete", "checksum"])
def test_reject_unpublished_or_corrupt_normalized_artifacts(tmp_path, fault):
    normalized = tmp_path/"normalized"
    canonicalize(sources(tmp_path), MAPPING, normalized)
    path = normalized/"manifest.json"
    if fault == "missing":
        path.rename(normalized/"manifest.partial.json")
    elif fault == "incomplete":
        manifest = json.loads(path.read_text())
        manifest["artifacts"] = []
        path.write_text(json.dumps(manifest))
    else:
        (normalized/"events.parquet").write_bytes(b"corrupt synthetic test")
    with pytest.raises(IngestError, match="NORMALIZED_"):
        build_quality(normalized, EXPORT, tmp_path/"quality")
    assert not (tmp_path/"quality").exists()


def test_profile_discloses_distribution_truncation(tmp_path):
    template = json.loads((HAND/"users.json").read_text())[0]
    users = [{**template, "user_id": f"profile-{i}", "acquisition_source": f"source-{i}"} for i in range(105)]
    users += json.loads((HAND/"users.json").read_text())
    events = json.loads((HAND/"events.json").read_text())
    canonicalize([write_source(tmp_path, "users", users), write_source(tmp_path, "events", events)],
                 MAPPING, tmp_path/"normalized")
    quality, profile = build_quality(tmp_path/"normalized", EXPORT, tmp_path/"quality")
    assert quality["zero_event_users"] == 106
    rows = profile["distributions"]["acquisition_source"]
    coverage = profile["distribution_coverage"]["acquisition_source"]
    assert len(rows) == 100 and coverage["total_groups"] > 100
    assert coverage["omitted_users"] > 0
    assert sum(row["users"] for row in rows)+coverage["omitted_users"] == 111
