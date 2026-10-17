"""Candidate V3 user-level feature snapshots and event-resolution timelines."""
from __future__ import annotations

import hashlib
import csv
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from server.analysis.casual_sequences import match_sequence, strictly_after
from server.analysis.connection import connect
from server.analysis.ingest import IngestError, file_hash
from server.analysis.quality import build_casual_quality
from server.analysis.v3_contract import ANALYSIS_VERSION, MINIMUM_DENOMINATORS, POLICY_IDENTITY, SEQUENCE_RULES

FEATURE_VERSION = "3.0"
AD_FORMATS = ("all", "rewarded", "interstitial", "banner", "app_open", "native", "other", "unknown")
SEQUENCE_GAPS = {
    template: ((300, 1800, 7200, 86400) if template == "level_fail_to_complete" else (300, 1800, 7200))
    for template in SEQUENCE_RULES
}


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _scope(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _max_consecutive_failures(events: list[dict]) -> int:
    current, maximum = defaultdict(int), 0
    for event in events:
        level = event.get("level_id")
        if not level:
            continue
        if event["event_name"] == "level_fail":
            current[level] += 1
            maximum = max(maximum, current[level])
        elif event["event_name"] == "level_complete":
            current[level] = 0
    return maximum


def _completion_durations(events: list[dict]) -> list[tuple[datetime, float]]:
    starts = {(e.get("level_id"), e.get("attempt_id")):e for e in events
              if e["event_name"] == "level_start" and e.get("level_id") and e.get("attempt_id")}
    values = []
    for event in events:
        if event["event_name"] != "level_complete":
            continue
        start = starts.get((event.get("level_id"), event.get("attempt_id")))
        if start and event["event_time"] > start["event_time"]:
            values.append((event["event_time"], (event["event_time"]-start["event_time"]).total_seconds()))
    return values


def build_casual_features(normalized_dir, export_metadata, destination, windows_hours=(1,3,6,12,24,48,72,96,120,144), *, scope=None, sequence_matcher=None):
    normalized_dir, destination = Path(normalized_dir), Path(destination)
    if not windows_hours or len(set(windows_hours)) != len(windows_hours) or any(
            type(w) not in (int,float) or not math.isfinite(w) or not 0 < w <= 144 for w in windows_hours):
        raise IngestError("INVALID_V3_FEATURE_WINDOWS")
    windows = sorted(windows_hours)
    source_manifest = json.loads((normalized_dir/"manifest.json").read_text())
    source_hash = file_hash(normalized_dir/"manifest.json")
    destination.mkdir(parents=True, exist_ok=False)
    quality, _ = build_casual_quality(normalized_dir, export_metadata, destination/"quality")
    caps = quality["capabilities"]
    with connect(config={"memory_limit":"512MB", "threads":2}) as c:
        c.execute("SET TimeZone='UTC'")
        c.read_parquet(str(normalized_dir/"users.parquet")).create_view("users")
        c.read_parquet(str(normalized_dir/"events.parquet")).create_view("events")
        user_rows = c.execute("SELECT app_id,user_id,installed_at FROM users ORDER BY app_id,user_id").fetchall()
        columns = [row[0] for row in c.execute("DESCRIBE events").fetchall()]
        event_rows = c.execute("SELECT * FROM events ORDER BY app_id,user_id,event_time,source_sequence NULLS LAST,event_id").fetchall()
    by_user = defaultdict(list)
    for raw in event_rows:
        event = dict(zip(columns, raw))
        by_user[(event["app_id"],event["user_id"])].append(event)
    complete_through, exported_at = _utc(export_metadata["complete_through"]), _utc(export_metadata["exported_at"])
    snapshots, timeline = [], []
    for app_id,user_id,installed_at in user_rows:
        installed_at = installed_at.astimezone(timezone.utc)
        events = [event for event in by_user[(app_id,user_id)] if event["event_time"] <= exported_at]
        sequence_cache = {(template,gap):(sequence_matcher or match_sequence)(events,template,gap)
                          for template,gaps in SEQUENCE_GAPS.items() for gap in gaps}
        # Event-resolution timelines support exact first-threshold evaluation later.
        for event_name,metric,category in (("level_start","level_start_count","level_progress"),
                                           ("level_complete","level_complete_count","level_progress"),
                                           ("level_fail","level_fail_count","level_friction")):
            count=0
            for event in (e for e in events if e["event_name"]==event_name):
                count+=1
                timeline.append((app_id,user_id,category,metric,_scope("all"),event["event_time"],float(count),None))
        seen_sessions=set()
        for event in (e for e in events if e["event_name"]=="session_start" and e.get("session_id")):
            if event["session_id"] in seen_sessions:continue
            seen_sessions.add(event["session_id"])
            timeline.append((app_id,user_id,"session_retention","session_count",_scope("all"),
                             event["event_time"],float(len(seen_sessions)),None))
        for ad_format in AD_FORMATS:
            count=0;revenue=0.0
            for event in (e for e in events if e["event_name"]=="ad_impression" and
                          (ad_format=="all" or (e.get("ad_format") or "unknown")==ad_format)):
                count+=1
                timeline.append((app_id,user_id,"iaa","ad_count",_scope({"ad_format":ad_format}),
                                 event["event_time"],float(count),None))
                available=event["available_at"] if export_metadata["revenue_timing"]=="available_at" else event["event_time"]
                if event.get("revenue_usd") is not None and available is not None:
                    revenue+=event["revenue_usd"]
                    timeline.append((app_id,user_id,"iaa","ad_revenue_sum",_scope({"ad_format":ad_format}),
                                     available,float(revenue),None))
        distinct_levels=set();maximum_index=None
        for event in (e for e in events if e["event_name"]=="level_complete"):
            if event.get("level_id") and event["level_id"] not in distinct_levels:
                distinct_levels.add(event["level_id"])
                timeline.append((app_id,user_id,"level_progress","distinct_completed_levels",_scope("all"),
                                 event["event_time"],float(len(distinct_levels)),None))
            if event.get("level_index") is not None and (maximum_index is None or event["level_index"]>maximum_index):
                maximum_index=event["level_index"]
                for metric in ("max_completed_level_index","completed_level","reached_level"):
                    timeline.append((app_id,user_id,"level_progress",metric,_scope("all"),event["event_time"],float(maximum_index),None))
        for template_gap,matches in sequence_cache.items():
            template,gap=template_gap
            for index,match in enumerate(matches,1):
                timeline.append((app_id,user_id,"sequence",template,_scope({"max_gap_seconds":gap}),
                                 match["matched_at"],float(index),None))
        for hours in windows:
            end = installed_at + timedelta(hours=hours)
            complete = end <= complete_through
            observed = [e for e in events if installed_at <= e["event_time"] < end]
            def add(category,metric,value,denominator=None,first=None,scope="all",enabled=True,mode="first_match_once"):
                snapshots.append((app_id,user_id,float(hours),category,metric,_scope(scope),
                                  value if complete and enabled else None,
                                  denominator if complete and enabled else None,complete,enabled,
                                  first if complete and enabled else None,mode))
            names = defaultdict(list)
            for event in observed:
                names[event["event_name"]].append(event)
            for ad_format in AD_FORMATS:
                ads = [e for e in names["ad_impression"] if ad_format == "all" or (e.get("ad_format") or "unknown") == ad_format]
                add("iaa","ad_count",float(len(ads)),first=ads[-1]["event_time"] if ads else None,
                    scope={"ad_format":ad_format},enabled=caps["ad_frequency"]["enabled"])
                revenue_events=[]
                for event in ads:
                    available = event["available_at"] if export_metadata["revenue_timing"] == "available_at" else event["event_time"]
                    if available is not None and available < end:
                        revenue_events.append((available,event["revenue_usd"]))
                revenue = sum(value for _,value in revenue_events) if revenue_events and all(value is not None for _,value in revenue_events) else (0.0 if not revenue_events else None)
                add("iaa","ad_revenue_sum",revenue,first=max((time for time,_ in revenue_events),default=None),
                    scope={"ad_format":ad_format},enabled=caps["revenue_trigger"]["enabled"])
            starts = names["session_start"]
            session_ids = {e["session_id"] for e in starts if e.get("session_id")}
            add("session_retention","session_count",float(len(session_ids)),first=starts[-1]["event_time"] if starts else None,
                enabled=caps["distinct_session_count"]["enabled"])
            returns=[e for e in starts if e["event_time"]>installed_at]
            first_return=returns[0] if returns else None
            add("session_retention","first_return_delay_seconds",
                (first_return["event_time"]-installed_at).total_seconds() if first_return else None,
                first=first_return["event_time"] if first_return else end,
                enabled=caps["session_return"]["enabled"],mode="checkpoint_snapshot")
            finished_intervals=[(left,right) for left,right in ((24,48),(48,72),(72,96)) if right<=hours]
            interval_hits=[]
            for left,right in finished_intervals:
                interval_hits.append(any(installed_at+timedelta(hours=left)<=e["event_time"]<installed_at+timedelta(hours=right) for e in starts))
            streak=best=0
            for hit in interval_hits:
                streak=streak+1 if hit else 0;best=max(best,streak)
            add("session_retention","return_interval_count",float(sum(interval_hits)),
                first=returns[-1]["event_time"] if returns else None,enabled=caps["session_return"]["enabled"])
            add("session_retention","consecutive_return_days",float(best),
                first=returns[-1]["event_time"] if returns else None,enabled=caps["session_return"]["enabled"])
            post_sessions=[e for e in starts if first_return and e["event_time"]>=first_return["event_time"]]
            add("session_retention","post_return_session_count",float(len({e.get('session_id') or e['event_id'] for e in post_sessions})),
                first=post_sessions[-1]["event_time"] if post_sessions else None,enabled=caps["session_return"]["enabled"])
            post_ends=[e for e in names["session_end"] if first_return and e["event_time"]>=first_return["event_time"]]
            add("session_retention","post_return_engaged_seconds",sum(e["engaged_seconds"] for e in post_ends if e.get("engaged_seconds") is not None),
                first=post_ends[-1]["event_time"] if post_ends else None,enabled=caps["session_duration"]["enabled"])
            level_starts,level_completes,level_fails=(names[name] for name in ("level_start","level_complete","level_fail"))
            for metric,items in (("level_start_count",level_starts),("level_complete_count",level_completes),("level_fail_count",level_fails)):
                category="level_friction" if metric=="level_fail_count" else "level_progress"
                add(category,metric,float(len(items)),first=items[-1]["event_time"] if items else None,
                    enabled=caps["level_event_counts"]["enabled"])
            completed_levels={e["level_id"] for e in level_completes if e.get("level_id")}
            add("level_progress","distinct_completed_levels",float(len(completed_levels)),
                first=level_completes[-1]["event_time"] if level_completes else None,
                enabled=caps["level_identity"]["enabled"])
            indexed=[e for e in level_completes if e.get("level_index") is not None]
            maximum=max((e["level_index"] for e in indexed),default=0)
            max_event=next((e for e in reversed(indexed) if e["level_index"]==maximum),None)
            for metric in ("max_completed_level_index","completed_level","reached_level"):
                add("level_progress",metric,float(maximum),first=max_event["event_time"] if max_event else None,
                    enabled=caps["level_progress"]["enabled"])
            for level_index in sorted({e["level_index"] for e in indexed}):
                reached=next(e for e in indexed if e["level_index"]==level_index)
                add("level_progress","level_time_to_reach_seconds",
                    (reached["event_time"]-installed_at).total_seconds(),first=end,
                    scope={"level_index":level_index},enabled=caps["level_progress"]["enabled"],mode="checkpoint_snapshot")
            attempt_enabled=caps["attempt_pairing"]["enabled"]
            starts_by_attempt={(e.get("level_id"),e.get("attempt_id")):e for e in level_starts if e.get("level_id") and e.get("attempt_id")}
            completed_attempts={(e.get("level_id"),e.get("attempt_id")) for e in level_completes
                                if (e.get("level_id"),e.get("attempt_id")) in starts_by_attempt}
            failed_attempts={(e.get("level_id"),e.get("attempt_id")) for e in level_fails
                             if (e.get("level_id"),e.get("attempt_id")) in starts_by_attempt}
            valid_starts=len(starts_by_attempt)
            for metric,numerator in (("complete_start_ratio",len(completed_attempts)),("fail_start_ratio",len(failed_attempts))):
                add("level_friction",metric,numerator/valid_starts if valid_starts else None,valid_starts,
                    first=end,enabled=attempt_enabled,mode="checkpoint_snapshot")
            distinct_started={key[0] for key in starts_by_attempt}
            add("level_friction","attempts_per_level",valid_starts/len(distinct_started) if distinct_started else None,
                len(distinct_started),first=end,enabled=attempt_enabled,mode="checkpoint_snapshot")
            durations=[value for time,value in _completion_durations(observed)]
            add("level_friction","completion_duration_seconds",median(durations) if durations else None,len(durations),
                first=end,enabled=attempt_enabled,mode="checkpoint_snapshot")
            add("level_friction","consecutive_failures",float(_max_consecutive_failures(observed)),
                first=level_fails[-1]["event_time"] if level_fails else None,enabled=attempt_enabled)
            complete_sessions={e["session_id"] for e in level_completes if e.get("session_id")}
            add("level_progress","completes_per_session",len(level_completes)/len(session_ids) if session_ids else None,
                len(session_ids),first=end,enabled=caps["same_session_cross"]["enabled"],mode="checkpoint_snapshot")
            for template,gaps in SEQUENCE_GAPS.items():
                for gap in gaps:
                    matches=[m for m in sequence_cache[(template,gap)] if m["matched_at"] < end]
                    enabled = attempt_enabled if template.startswith("level_start") or template.startswith("level_fail_to_start") or template.startswith("level_fail_to_complete") else caps["same_session_cross"]["enabled"]
                    add("sequence",template,float(len(matches)),first=matches[-1]["matched_at"] if matches else None,
                        scope={"max_gap_seconds":gap},enabled=enabled)
            retry_matches=[m for m in sequence_cache[("level_fail_to_start",7200)] if m["matched_at"]<end]
            complete_after=[m for m in sequence_cache[("level_fail_to_complete",86400)] if m["matched_at"]<end]
            session_after=[];used_starts=set()
            for failed in level_fails:
                for started in starts:
                    if started["event_id"] in used_starts or started.get("session_id")==failed.get("session_id"):
                        continue
                    if strictly_after(failed,started):
                        used_starts.add(started["event_id"]);session_after.append({"matched_at":started["event_time"]});break
            for metric,matches,enabled in (("retry_same_level",retry_matches,attempt_enabled),
                                           ("complete_after_fail",complete_after,attempt_enabled),
                                           ("session_after_fail",session_after,caps["same_session_cross"]["enabled"])):
                add("level_friction",metric,float(len(matches)),first=matches[-1]["matched_at"] if matches else None,enabled=enabled)
        for start_hour,end_hour in ((24,48),(48,72),(72,96)):
            end = installed_at+timedelta(hours=end_hour); complete=end<=complete_through
            hits=[e for e in events if e["event_name"]=="session_start" and installed_at+timedelta(hours=start_hour)<=e["event_time"]<end]
            snapshots.append((app_id,user_id,float(end_hour),"session_retention","return_in_interval",
                              _scope({"start_hours":start_hour,"end_hours":end_hour}),
                              (1.0 if hits else 0.0) if complete and caps["session_return"]["enabled"] else None,
                              None,complete,caps["session_return"]["enabled"],hits[0]["event_time"] if hits and complete else None,
                              "first_match_once"))
    definition={"analysis_version":ANALYSIS_VERSION,"feature_version":FEATURE_VERSION,"windows_hours":windows,
                "source_manifest_sha256":source_hash,"quality_manifest_sha256":file_hash(destination/"quality/manifest.json"),
                "policy_identity":POLICY_IDENTITY,"interval":"[install,install+observation_end)","scope":scope,
                "export_metadata":export_metadata}
    feature_id=hashlib.sha256(json.dumps(definition,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    # DuckDB executemany is prohibitively expensive for the ~1M deterministic
    # feature rows produced by the 100k-event contract.  A private typed CSV
    # handoff preserves exact values and lets DuckDB vectorize parsing/COPY.
    definitions={
        "snapshots":(("app_id","user_id","window_hours","category","metric","scope_json","value","denominator",
                      "window_complete","enabled","first_observed_at","trigger_mode"),
                     ("VARCHAR","VARCHAR","DOUBLE","VARCHAR","VARCHAR","VARCHAR","DOUBLE","BIGINT","BOOLEAN","BOOLEAN","TIMESTAMPTZ","VARCHAR"),snapshots),
        "timeline":(("app_id","user_id","category","metric","scope_json","observed_at","value","denominator"),
                    ("VARCHAR","VARCHAR","VARCHAR","VARCHAR","VARCHAR","TIMESTAMPTZ","DOUBLE","BIGINT"),timeline)}
    with connect(str(destination/"work.duckdb"),config={"memory_limit":"512MB","threads":2}) as c:
        outputs=[]
        for name,(columns,types,rows) in definitions.items():
            transfer=destination/f".{name}.transfer.csv"
            with transfer.open("x",newline="") as stream:
                writer=csv.writer(stream);writer.writerow(columns);writer.writerows(rows);stream.flush();os.fsync(stream.fileno())
            projections=",".join(f'CAST("{column}" AS {kind}) AS "{column}"' for column,kind in zip(columns,types))
            c.execute(f"CREATE TABLE {name} AS SELECT {projections} FROM read_csv(?,all_varchar=true,header=true,nullstr='')",[str(transfer)])
            path=destination/f"{name}.parquet"
            c.execute(f"COPY (SELECT * FROM {name} ORDER BY ALL) TO ? (FORMAT PARQUET,COMPRESSION ZSTD)",[str(path)])
            transfer.unlink()
            outputs.append({"name":name,"path":path.name,"sha256":file_hash(path),"size_bytes":path.stat().st_size,
                            "rows":len(rows)})
    if file_hash(normalized_dir/"manifest.json")!=source_hash:
        raise IngestError("SOURCE_CHANGED_DURING_V3_FEATURES")
    for artifact in source_manifest["artifacts"]:
        if file_hash(normalized_dir/artifact["path"])!=artifact["sha256"]:
            raise IngestError("SOURCE_CHANGED_DURING_V3_FEATURES")
    manifest={"schema_version":"3.0","analysis_version":ANALYSIS_VERSION,"stage":"features_v3",
              "feature_id":feature_id,"definition":definition,"capabilities":caps,"artifacts":outputs}
    partial=destination/"manifest.partial.json"
    with partial.open("x") as stream:
        json.dump(manifest,stream,sort_keys=True,indent=2,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    os.link(partial,destination/"manifest.json");partial.unlink()
    return manifest
