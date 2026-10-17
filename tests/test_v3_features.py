import json
from pathlib import Path

import duckdb

from server.analysis.casual_features import build_casual_features
from server.analysis.ingest import EVENT_TYPES,USER_TYPES,canonicalize
from tests.test_ingest import write_source

FIXTURE=Path("tests/fixtures/casual_v3")
EXPORT=json.loads((FIXTURE/"export.json").read_text())
MAPPING={"users":{name:name for name in USER_TYPES},"events":{name:name for name in EVENT_TYPES}}


def build(tmp_path,event_limit=9,windows=(6,24,48,72,96)):
    tmp_path.mkdir(parents=True,exist_ok=True)
    users=json.loads((FIXTURE/"users.json").read_text())[:1]
    events=json.loads((FIXTURE/"events.json").read_text())[:event_limit]
    canonicalize([write_source(tmp_path,"users",users),write_source(tmp_path,"events",events)],MAPPING,tmp_path/"normalized")
    manifest=build_casual_features(tmp_path/"normalized",EXPORT,tmp_path/"features",windows)
    return manifest,tmp_path/"features/snapshots.parquet"


def value(path,metric,hours,scope=None):
    sql="SELECT value,denominator,window_complete,enabled,trigger_mode FROM read_parquet(?) WHERE user_id='u1' AND metric=? AND window_hours=?"
    params=[str(path),metric,float(hours)]
    if scope is not None:
        sql+=" AND scope_json=?";params.append(json.dumps(scope,sort_keys=True,separators=(",",":")))
    with duckdb.connect() as c:
        rows=c.execute(sql,params).fetchall()
    assert len(rows)==1,rows
    return rows[0]


def test_level_friction_progress_and_sequence_features_match_hand_values(tmp_path):
    manifest,path=build(tmp_path)
    assert manifest["analysis_version"]=="3.0-casual-game"
    assert value(path,"level_start_count",6)[0]==2
    assert value(path,"level_complete_count",6)[0]==1
    assert value(path,"max_completed_level_index",6)[0]==1
    assert value(path,"complete_start_ratio",6)==(.5,2,True,True,"checkpoint_snapshot")
    assert value(path,"fail_start_ratio",6)[0]==.5
    assert value(path,"attempts_per_level",6)==(2.0,1,True,True,"checkpoint_snapshot")
    assert value(path,"completion_duration_seconds",6)[0]==600
    assert value(path,"retry_same_level",6)[0]==1
    assert value(path,"level_fail_to_start",6,{"max_gap_seconds":1800})[0]==1
    assert value(path,"level_start_to_complete",6,{"max_gap_seconds":1800})[0]==1
    assert value(path,"level_complete_to_ad_impression",6,{"max_gap_seconds":300})[0]==1
    assert value(path,"level_time_to_reach_seconds",6,{"level_index":1})[0]==4800


def test_return_half_open_boundaries_are_exact(tmp_path):
    _,path=build(tmp_path)
    assert value(path,"return_in_interval",48,{"start_hours":24,"end_hours":48})[0]==1
    assert value(path,"return_in_interval",72,{"start_hours":48,"end_hours":72})[0]==1
    assert value(path,"return_in_interval",96,{"start_hours":72,"end_hours":96})[0]==1
    assert value(path,"return_interval_count",72)[0]==2
    assert value(path,"consecutive_return_days",72)[0]==2
    assert value(path,"first_return_delay_seconds",48)[0]==86400
    assert value(path,"post_return_session_count",72)[0]==2


def test_future_events_do_not_change_past_snapshot(tmp_path):
    _,short=build(tmp_path/"short",event_limit=6,windows=(6,))
    _,long=build(tmp_path/"long",event_limit=9,windows=(6,))
    for metric in ("level_start_count","level_complete_count","retry_same_level","complete_start_ratio"):
        assert value(short,metric,6)==value(long,metric,6)


def test_incomplete_window_is_null_not_zero(tmp_path):
    export={**EXPORT,"complete_through":"2026-01-01T12:00:00Z"}
    users=json.loads((FIXTURE/"users.json").read_text())[:1]
    events=json.loads((FIXTURE/"events.json").read_text())[:6]
    canonicalize([write_source(tmp_path,"users",users),write_source(tmp_path,"events",events)],MAPPING,tmp_path/"normalized")
    build_casual_features(tmp_path/"normalized",export,tmp_path/"features",(24,))
    assert value(tmp_path/"features/snapshots.parquet","level_start_count",24)==(None,None,False,True,"first_match_once")
    assert value(tmp_path/"features/snapshots.parquet","return_in_interval",48,{"start_hours":24,"end_hours":48})==(None,None,False,True,"first_match_once")


def test_zero_event_mature_user_is_present_with_observed_zero(tmp_path):
    user={**json.loads((FIXTURE/"users.json").read_text())[3],"installed_at":"2026-01-01T00:00:00Z"}
    canonicalize([write_source(tmp_path,"users",[user]),write_source(tmp_path,"events",[])],MAPPING,tmp_path/"normalized")
    build_casual_features(tmp_path/"normalized",EXPORT,tmp_path/"features",(6,))
    with duckdb.connect() as c:
        rows=c.execute("SELECT metric,value FROM read_parquet(?) WHERE user_id='u4' AND metric IN ('ad_count','session_count') ORDER BY metric",
                       [str(tmp_path/"features/snapshots.parquet")]).fetchall()
    assert ("ad_count",0.0) in rows
    assert ("session_count",None) in rows  # Session capability is unavailable, not observed zero.
