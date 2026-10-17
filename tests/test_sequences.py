from datetime import datetime, timedelta, timezone

import pytest
import duckdb

from server.analysis.features import build_features
from server.analysis.ingest import canonicalize
from server.analysis.predicates import evaluate_candidates
from tests.test_ingest import MAPPING, sources
from tests.test_predicates import candidate
from tests.test_quality import EXPORT

from server.analysis.sequences import first_sequence_trigger

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def events(rows):
    return [(BASE+timedelta(seconds=seconds), sequence, name, f"id-{i}")
            for i, (seconds, sequence, name) in enumerate(rows)]


@pytest.mark.parametrize("rows,gap,repeats,expected", [
    ([(1,None,"A"),(3,None,"B")], 2, 1, 3),
    ([(1,None,"A"),(4,None,"B")], 2, 1, None),
    ([(1,None,"A"),(2,None,"A"),(4,None,"B")], 2, 1, 4),
    ([(1,None,"A"),(2,None,"A"),(3,None,"B"),(4,None,"B")], 10, 2, None),
    ([(1,None,"A"),(2,None,"B"),(3,None,"A"),(4,None,"B")], 10, 2, 4),
    ([(1,None,"B"),(2,None,"A")], 10, 1, None),
    ([(1,None,"A"),(1,None,"B")], 10, 1, None),
    ([(1,1,"A"),(1,2,"B")], 10, 1, 1),
    ([(1,2,"A"),(1,1,"B")], 10, 1, None),
    ([(1,1,"A"),(1,1,"B")], 10, 1, None),
    ([(1,1,"A"),(1,None,"B")], 10, 1, None),
    ([(1,None,"A"),(2,None,"B"),(2,None,"A"),(3,None,"B")], 10, 2, None),
])
def test_independent_sequence_truth(rows, gap, repeats, expected):
    actual = first_sequence_trigger(events(rows), ["A", "B"], gap, repeats)
    assert actual == (BASE+timedelta(seconds=expected) if expected is not None else None)


def test_same_event_kind_no_reuse_and_future_cannot_change_trigger():
    rows = [(i,None,"A") for i in range(1,7)]
    assert first_sequence_trigger(events(rows[:3]), ["A","A"], 10, 2) is None
    assert first_sequence_trigger(events(rows), ["A","A"], 10, 3) == BASE+timedelta(seconds=6)
    assert first_sequence_trigger(events(rows[:4]), ["A","A"], 10, 2) == first_sequence_trigger(events(rows), ["A","A"], 10, 2)


def test_same_time_ids_never_create_order():
    rows = events([(1,None,"A"),(1,None,"B")])
    assert first_sequence_trigger(rows, ["A","B"], 10, 1) is None
    assert first_sequence_trigger(list(reversed(rows)), ["A","B"], 10, 1) is None


def test_canonical_parquet_sequence_triggers(tmp_path):
    canonicalize(sources(tmp_path), MAPPING, tmp_path/"normalized")
    build_features(tmp_path/"normalized", EXPORT, tmp_path/"features")
    def sequence(identity, steps, gap=3600, repeats=1, window=6):
        return candidate(identity, {"op": "sequence", "steps": steps, "max_gap_seconds": gap,
                                    "repeats": repeats, "matching": "non_overlapping"}, window)
    configs = [sequence("sessions_ads_twice", ["session_start", "ad_impression"], repeats=2),
               sequence("same_time_end_ad", ["session_end", "ad_impression"]),
               sequence("ads_three_pairs", ["ad_impression", "ad_impression"], repeats=3),
               sequence("ads_two_pairs", ["ad_impression", "ad_impression"], repeats=2),
               sequence("boundary", ["ad_impression", "ad_impression"], window=2)]
    result = evaluate_candidates(tmp_path/"normalized", tmp_path/"features", configs, tmp_path/"result")
    with duckdb.connect() as c:
        c.execute("SET TimeZone='UTC'")
        rows = c.execute("SELECT candidate_id,user_id,strftime(triggered_at,'%H:%M:%S') FROM read_parquet(?) ORDER BY ALL",
                         [str(tmp_path/"result/triggers.parquet")]).fetchall()
    assert rows == [("ads_two_pairs", "u1", "04:00:00"), ("sessions_ads_twice", "u3", "02:30:00")]
    assert result["artifacts"][0]["rows"] == 2
