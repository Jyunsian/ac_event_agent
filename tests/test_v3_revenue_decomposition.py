import json

import duckdb

from server.analysis.casual_validation import _checkpoint
from server.analysis.ingest import EVENT_TYPES,USER_TYPES,canonicalize
from server.analysis.targets import build_casual_targets
from tests.test_ingest import write_source
from tests.test_v3_validation import prepare_validation


def test_d2_d3_d7_each_sum_to_d7_and_late_indicator_is_not_early(tmp_path):
    output=prepare_validation(tmp_path/"data")
    for result in output["results"]:
        for name in ("d2","d3","d7"):
            checkpoint=result["checkpoints"][name]
            if checkpoint["groups"] is None:continue
            for group in checkpoint["groups"].values():
                if group["d7"]["revenue_usd"] is not None:
                    assert abs(group["early"]["revenue_usd"]+group["remaining"]["revenue_usd"]-group["d7"]["revenue_usd"])<1e-12
    late=_checkpoint([{"status":"triggered","early":1,"remaining":2,"d7":3}],72,96)
    assert late["comparison_status"]=="LATE_INDICATOR_NOT_DECIDABLE" and late["groups"] is None


def test_delayed_revenue_after_cutoff_propagates_unknown(tmp_path):
    user={"app_id":"game","user_id":"u","installed_at":"2026-01-01T00:00:00Z","platform":"ios","country":"TW",
          "acquisition_source":"organic","campaign_id":None,"app_version_at_install":"1"}
    event={"app_id":"game","user_id":"u","event_id":"e","event_name":"ad_impression","event_time":"2026-01-02T00:00:00Z",
           "available_at":"2026-01-20T00:00:00Z","session_id":None,"source_sequence":1,"ad_format":"rewarded","revenue_usd":1,
           "engaged_seconds":None,"level_id":None,"level_index":None,"attempt_id":None,"level_mode":None,"difficulty":None,
           "revive_used":None,"booster_used":None,"app_version":"1"}
    mapping={"users":{name:name for name in USER_TYPES},"events":{name:name for name in EVENT_TYPES}}
    canonicalize([write_source(tmp_path,"users",[user]),write_source(tmp_path,"events",[event])],mapping,tmp_path/"normalized")
    export={"schema_version":"1.0","complete_through":"2026-01-10T00:00:00Z","exported_at":"2026-01-10T00:00:00Z",
            "origin":"install","id_policy":"anonymous install","revenue_timing":"available_at","synthetic":True}
    build_casual_targets(tmp_path/"normalized",export,tmp_path/"targets")
    with duckdb.connect() as c:
        value=c.execute("SELECT d7_revenue_usd FROM read_parquet(?)",[str(tmp_path/"targets/targets.parquet")]).fetchone()[0]
    assert value is None
