import json
import duckdb
import pytest

from server.analysis.features import build_features
from server.analysis.ingest import IngestError, canonicalize
from server.analysis.predicates import evaluate_candidates, validate_candidate
from tests.test_ingest import HAND, MAPPING, sources
from tests.test_quality import EXPORT


def candidate(identity, predicate, window=6):
    return {"schema_version": "1.0", "candidate_id": identity, "window_hours": window,
            "predicate": predicate, "trigger_policy": "first_match_once", "dependencies": []}


def test_all_atoms_and_boolean_first_match(tmp_path):
    canonicalize(sources(tmp_path), MAPPING, tmp_path/"normalized")
    build_features(tmp_path/"normalized", EXPORT, tmp_path/"features")
    count = {"op": "count", "threshold": 5, "ad_format": "rewarded"}
    revenue = {"op": "revenue_sum", "threshold": .05}
    configs = [candidate("count", count), candidate("revenue", revenue),
               candidate("sessions", {"op": "session_count", "threshold": 2}, 24),
               candidate("duration", {"op": "engaged_seconds", "threshold": 120}),
               candidate("and", {"op": "and", "clauses": [count, revenue]}),
               candidate("or", {"op": "or", "clauses": [count, revenue]}),
               candidate("boundary", {"op": "count", "threshold": 1}, 1)]
    evaluate_candidates(tmp_path/"normalized", tmp_path/"features", configs, tmp_path/"results")
    with duckdb.connect() as c:
        c.execute("SET TimeZone='UTC'")
        rows = c.execute("SELECT candidate_id,user_id,strftime(triggered_at,'%H:%M:%S') FROM read_parquet(?) ORDER BY ALL",
                         [str(tmp_path/"results/triggers.parquet")]).fetchall()
    assert rows == [("and", "u1", "05:00:00"), ("count", "u1", "05:00:00"),
                    ("duration", "u5", "02:00:00"), ("or", "u1", "05:00:00"),
                    ("or", "u3", "02:30:00"), ("or", "u6", "01:00:00"),
                    ("revenue", "u1", "05:00:00"), ("revenue", "u3", "02:30:00"),
                    ("revenue", "u6", "01:00:00"), ("sessions", "u3", "02:00:00")]
    # Trigger existence and D7 target maturity are separate: u6 has a valid early
    # trigger, but remains excluded from D7 metrics by its PH10 cohort membership.


@pytest.mark.parametrize("predicate", [
    {"op": "python", "threshold": 1}, {"op": "count", "threshold": "1"},
    {"op": "count", "threshold": .5}, {"op": "count", "threshold": float('inf')},
    {"op": "count", "threshold": 1, "event_name": "session_end"},
    {"op": "session_count", "threshold": 1, "ad_format": "rewarded"},
    {"op": "and", "clauses": [{"op": "and", "clauses": []}, {"op": "count", "threshold": 1}]}])
def test_invalid_ast_rejected(predicate):
    with pytest.raises(IngestError):
        validate_candidate(candidate("invalid", predicate))


def test_delayed_and_uses_later_time_or_uses_earlier_time(tmp_path):
    canonicalize(sources(tmp_path), MAPPING, tmp_path/"normalized")
    build_features(tmp_path/"normalized", EXPORT, tmp_path/"features")
    clauses = [{"op": "count", "threshold": 1}, {"op": "revenue_sum", "threshold": .05}]
    configs = [candidate(op, {"op": op, "clauses": clauses}, 24) for op in ("and", "or")]
    evaluate_candidates(tmp_path/"normalized", tmp_path/"features", configs, tmp_path/"result")
    with duckdb.connect() as c:
        c.execute("SET TimeZone='UTC'")
        rows = c.execute("SELECT candidate_id,extract(hour FROM triggered_at) FROM read_parquet(?) WHERE user_id='u4' ORDER BY candidate_id",
                         [str(tmp_path/"result/triggers.parquet")]).fetchall()
        assert rows == [("and", 7), ("or", 1)]


def test_reused_atoms_match_isolated_evaluation_across_windows_and_order(tmp_path):
    canonicalize(sources(tmp_path),MAPPING,tmp_path/'normalized')
    build_features(tmp_path/'normalized',EXPORT,tmp_path/'features')
    count={'op':'count','threshold':1}
    revenue={'op':'revenue_sum','threshold':.05}
    configs=[candidate('early',count,1),candidate('late',count,24),
             candidate('both',{'op':'and','clauses':[count,revenue]},24),
             candidate('either',{'op':'or','clauses':[revenue,count]},24),
             candidate('same',{'op':'and','clauses':[count,count]},24),
             candidate('rewarded',{'op':'count','threshold':1,'ad_format':'rewarded'},24)]
    def read(directory):
        with duckdb.connect() as c:
            return c.execute('SELECT * FROM read_parquet(?) ORDER BY ALL',[str(directory/'triggers.parquet')]).fetchall()
    expected=[]
    for index,config in enumerate(configs):
        output=tmp_path/f'isolated-{index}'
        evaluate_candidates(tmp_path/'normalized',tmp_path/'features',[config],output)
        expected.extend(read(output))
    for index,order in enumerate([configs,list(reversed(configs))]):
        output=tmp_path/f'batch-{index}'
        evaluate_candidates(tmp_path/'normalized',tmp_path/'features',order,output)
        assert read(output)==sorted(expected)
        with duckdb.connect() as c:
            physical=c.execute('SELECT * FROM read_parquet(?)',
                               [str(output/'triggers.parquet')]).fetchall()
        assert physical==sorted(expected)
        assert not list(output.glob('trigger-parts-*'))
    assert (tmp_path/'batch-0/triggers.parquet').read_bytes()==(tmp_path/'batch-1/triggers.parquet').read_bytes()


def test_future_log_preserves_prior_trigger_and_negative_correction_refuses(tmp_path):
    configs = [candidate("count", {"op": "count", "threshold": 5}),
               candidate("revenue", {"op": "revenue_sum", "threshold": .05})]
    earlier = []
    for variant in ("base", "future", "negative"):
        root = tmp_path/variant
        root.mkdir()
        future = {"app_id": "synthetic", "user_id": "u1", "event_id": "later-ad",
                  "event_name": "ad_impression", "event_time": "2026-01-01T05:30:00Z",
                  "available_at": "2026-01-01T05:30:00Z", "ad_format": "rewarded", "revenue_usd": .1}
        negative = json.loads((HAND/"edge_cases.json").read_text())[1]["event"]
        canonicalize(sources(root, extras={"base": [], "future": [future], "negative": [negative]}[variant]), MAPPING, root/"normalized")
        build_features(root/"normalized", EXPORT, root/"features")
        if variant == "negative":
            with pytest.raises(IngestError, match="FEATURE_CAPABILITY_DISABLED"):
                evaluate_candidates(root/"normalized", root/"features", configs, root/"result")
            assert not (root/"result").exists()
        else:
            evaluate_candidates(root/"normalized", root/"features", configs, root/"result")
            with duckdb.connect() as c:
                earlier.append(c.execute("SELECT * FROM read_parquet(?) ORDER BY ALL", [str(root/"result/triggers.parquet")]).fetchall())
    assert earlier[0] == earlier[1]


def test_empty_parts_and_sequence_results_do_not_leak_previous_candidate(tmp_path):
    canonicalize(sources(tmp_path), MAPPING, tmp_path/'normalized')
    build_features(tmp_path/'normalized', EXPORT, tmp_path/'features')
    empty=candidate('empty',{'op':'count','threshold':10000})
    sequence=candidate('sequence',{'op':'sequence','steps':['ad_impression','ad_impression'],
        'max_gap_seconds':3600,'repeats':2,'matching':'non_overlapping'})
    configs=[candidate('z',{'op':'count','threshold':1}),empty,sequence]
    expected=[]
    for index,config in enumerate(configs):
        output=tmp_path/f'one-{index}'
        result=evaluate_candidates(tmp_path/'normalized',tmp_path/'features',[config],output)
        with duckdb.connect() as c:
            rows=c.execute('SELECT * FROM read_parquet(?)',[str(output/'triggers.parquet')]).fetchall()
        assert result['artifacts'][0]['rows']==len(rows)
        expected.extend(rows)
    output=tmp_path/'mixed'
    result=evaluate_candidates(tmp_path/'normalized',tmp_path/'features',configs,output)
    with duckdb.connect() as c:
        rows=c.execute('SELECT * FROM read_parquet(?)',[str(output/'triggers.parquet')]).fetchall()
    assert rows==sorted(expected)
    assert result['artifacts'][0]['rows']==len(expected)
    assert not list(output.glob('trigger-parts-*'))
