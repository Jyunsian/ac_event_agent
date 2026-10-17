import json
import duckdb
import pytest

import server.analysis.features as feature_module
from server.analysis.ingest import IngestError

from server.analysis.features import build_features
from server.analysis.ingest import canonicalize
from tests.test_ingest import HAND, MAPPING, sources, write_source
from tests.test_quality import EXPORT


def value(root, user, metric, hours):
    with duckdb.connect() as c:
        return c.execute("SELECT value FROM read_parquet(?) WHERE user_id=? AND metric=? AND window_hours=? AND ad_format='all'",
                         [str(root/"snapshots.parquet"), user, metric, hours]).fetchone()[0]


def test_event_resolution_windows_and_delayed_income(tmp_path):
    canonicalize(sources(tmp_path), MAPPING, tmp_path/"normalized")
    result = build_features(tmp_path/"normalized", EXPORT, tmp_path/"features")
    root = tmp_path/"features"
    assert value(root, "u1", "count", 1) == 0
    assert value(root, "u1", "count", 3) == 2
    assert value(root, "u1", "count", 6) == 5
    assert value(root, "u2", "count", 72) == 0
    assert value(root, "u4", "revenue_sum", 6) == 0
    assert value(root, "u4", "revenue_sum", 24) == .1
    assert value(root, "u3", "session_count", 3) == 2
    assert value(root, "u5", "engaged_seconds", 1) == 0
    assert value(root, "u5", "engaged_seconds", 3) == 120
    assert result["definition"]["windows_hours"] == [1, 3, 6, 12, 24, 48, 72, 96, 120, 144]
    with duckdb.connect() as c:
        c.execute("SET TimeZone='UTC'")
        hour = c.execute("SELECT extract(hour FROM available_at) FROM read_parquet(?) WHERE user_id='u4' AND metric='revenue_sum' AND ad_format='all'",
                         [str(root/"timeline.parquet")]).fetchone()[0]
        assert hour == 7


def test_unknown_timing_is_null_not_zero_and_changes_identity(tmp_path):
    canonicalize(sources(tmp_path), MAPPING, tmp_path/"normalized")
    first = build_features(tmp_path/"normalized", EXPORT, tmp_path/"first")
    second = build_features(tmp_path/"normalized", {**EXPORT, "revenue_timing": "unknown"}, tmp_path/"second")
    assert first["feature_id"] != second["feature_id"]
    assert value(tmp_path/"second", "u4", "revenue_sum", 6) is None
    assert value(tmp_path/"second", "u4", "count", 6) == 1
    assert not second["capabilities"]["revenue_trigger"]["enabled"]


def test_duplicate_session_and_same_time_ads_are_deterministic(tmp_path):
    events = json.loads((HAND/"events.json").read_text())
    start = next(e for e in events if e["event_id"] == "u3-s1")
    ad = next(e for e in events if e["event_id"] == "u1-a1")
    events += [{**start, "event_id": "duplicate-session-start"}, {**ad, "event_id": "same-time-new-ad"}]
    users = json.loads((HAND/"users.json").read_text())
    canonicalize([write_source(tmp_path, "users", users), write_source(tmp_path, "events", events)], MAPPING, tmp_path/"normalized")
    first = build_features(tmp_path/"normalized", EXPORT, tmp_path/"first")
    second = build_features(tmp_path/"normalized", EXPORT, tmp_path/"second")
    assert first == second
    assert value(tmp_path/"first", "u3", "session_count", 3) == 2
    assert value(tmp_path/"first", "u1", "count", 3) == 3
    with duckdb.connect() as c:
        rows = c.execute("SELECT value FROM read_parquet(?) WHERE user_id='u1' AND metric='count' AND ad_format='all' ORDER BY available_at",
                         [str(tmp_path/"first/timeline.parquet")]).fetchall()
        assert rows[0] == (2,)


def test_incomplete_window_is_not_imputed_and_window_config_changes_hash(tmp_path):
    canonicalize(sources(tmp_path), MAPPING, tmp_path/"normalized")
    export = {**EXPORT, "complete_through": "2026-01-10T02:00:00Z"}
    first = build_features(tmp_path/"normalized", export, tmp_path/"first")
    second = build_features(tmp_path/"normalized", export, tmp_path/"second", [1, 6])
    assert first["feature_id"] != second["feature_id"]
    assert value(tmp_path/"first", "u6", "count", 6) is None
    with duckdb.connect() as c:
        row = c.execute("SELECT window_complete,observed_value FROM read_parquet(?) WHERE user_id='u6' AND metric='count' AND ad_format='all' AND window_hours=6",
                        [str(tmp_path/"first/snapshots.parquet")]).fetchone()
        assert row == (False, 1)


def test_future_events_leave_earlier_values_unchanged_and_source_changes_identity(tmp_path):
    results = []
    for future in (False, True):
        root = tmp_path/str(future)
        root.mkdir()
        extra = {"app_id": "synthetic", "user_id": "u1", "event_id": "future",
                 "event_name": "ad_impression", "event_time": "2026-01-02T06:00:00Z",
                 "available_at": "2026-01-02T07:00:00Z", "ad_format": "banner", "revenue_usd": 10}
        canonicalize(sources(root, extras=[extra] if future else None), MAPPING, root/"normalized")
        manifest = build_features(root/"normalized", EXPORT, root/"features")
        with duckdb.connect() as c:
            rows = c.execute("SELECT * FROM read_parquet(?) WHERE available_at<CAST('2026-01-02T00:00:00Z' AS TIMESTAMPTZ) ORDER BY ALL",
                             [str(root/"features/timeline.parquet")]).fetchall()
        results.append((manifest, rows))
    assert results[0][0]["feature_id"] != results[1][0]["feature_id"]
    assert results[0][1] == results[1][1]
    assert value(tmp_path/"True/features", "u1", "count", 72) == 6


def test_definition_version_changes_identity(tmp_path, monkeypatch):
    canonicalize(sources(tmp_path), MAPPING, tmp_path/"normalized")
    first = build_features(tmp_path/"normalized", EXPORT, tmp_path/"first")
    monkeypatch.setattr(feature_module, "FEATURE_VERSION", "test-definition-version")
    second = build_features(tmp_path/"normalized", EXPORT, tmp_path/"second")
    assert first["feature_id"] != second["feature_id"]


def test_changed_source_cannot_publish_feature_manifest(tmp_path, monkeypatch):
    canonicalize(sources(tmp_path), MAPPING, tmp_path/"normalized")
    real_hash = feature_module.file_hash
    def corrupt_after_compute(path):
        # Inject a physical source change after calculation, without mocking DuckDB.
        if path.name == "snapshots.parquet":
            (tmp_path/"normalized/events.parquet").write_bytes(b"corrupt synthetic source")
        return real_hash(path)
    monkeypatch.setattr(feature_module, "file_hash", corrupt_after_compute)
    with pytest.raises(IngestError, match="SOURCE_CHANGED_DURING_FEATURES"):
        build_features(tmp_path/"normalized", EXPORT, tmp_path/"features")
    assert not (tmp_path/"features/manifest.json").exists()


def test_fractional_windows_follow_config_contract(tmp_path):
    canonicalize(sources(tmp_path), MAPPING, tmp_path/"normalized")
    build_features(tmp_path/"normalized", EXPORT, tmp_path/"features", [.5, 1.5, 2.5])
    assert value(tmp_path/"features", "u1", "count", .5) == 0
    assert value(tmp_path/"features", "u1", "count", 1.5) == 1
    assert value(tmp_path/"features", "u1", "count", 2.5) == 2
