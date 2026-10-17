"""Quality diagnostics and capability decisions derived from normalized evidence, never model guesses."""
import json
import os
from pathlib import Path

from server.analysis.connection import connect
from jsonschema import Draft202012Validator, FormatChecker

from server.analysis.ingest import IngestError, file_hash


def build_quality(normalized_dir, export_metadata, destination):
    normalized_dir, destination = Path(normalized_dir), Path(destination)
    schema = json.loads((Path(__file__).resolve().parents[2]/"contracts/schema.json").read_text())
    validator = Draft202012Validator({**schema, "$ref": "#/$defs/export"}, format_checker=FormatChecker())
    if not validator.is_valid(export_metadata):
        raise IngestError("INVALID_EXPORT_METADATA")
    try:
        manifest = json.loads((normalized_dir/"manifest.json").read_text())
        artifacts = manifest["artifacts"]
        names = [item["name"] for item in artifacts]
        if len(names) != len(set(names)) or not {"users", "events"}.issubset(names):
            raise ValueError("Missing canonical artifacts")
        for artifact in artifacts:
            path = normalized_dir/artifact["path"]
            if artifact["name"] in ("users", "events") and artifact["path"] != artifact["name"]+".parquet":
                raise ValueError("Invalid canonical path")
            if path.resolve().parent != normalized_dir.resolve() or file_hash(path) != artifact["sha256"]:
                raise IngestError("NORMALIZED_CHECKSUM_MISMATCH")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise IngestError("NORMALIZED_MANIFEST_INVALID") from error
    with connect(config={"memory_limit": "256MB", "threads": 2}) as c:
        for table in ("users", "events"):
            c.read_parquet(str(normalized_dir/f"{table}.parquet")).create_view(table)
        def number(sql):
            return c.execute(sql).fetchone()[0]
        zero_events = number("SELECT count(*) FROM users u ANTI JOIN events e USING(app_id,user_id)")
        missing_revenue = number("SELECT count(*) FROM events WHERE event_name='ad_impression' AND revenue_usd IS NULL")
        negative_revenue = number("SELECT count(*) FROM events WHERE event_name='ad_impression' AND revenue_usd<0")
        missing_available = number("SELECT count(*) FROM events WHERE event_name='ad_impression' AND available_at IS NULL")
        session_starts = number("SELECT count(*) FROM events WHERE event_name='session_start'")
        missing_start_ids = number("SELECT count(*) FROM events WHERE event_name='session_start' AND session_id IS NULL")
        session_ends = number("SELECT count(*) FROM events WHERE event_name='session_end'")
        bad_ends = number("SELECT count(*) FROM events WHERE event_name='session_end' AND (session_id IS NULL OR engaged_seconds IS NULL)")
        repeated_ends = number("SELECT count(*) FROM (SELECT app_id,user_id,session_id FROM events WHERE event_name='session_end' AND session_id IS NOT NULL GROUP BY ALL HAVING count(*)>1)")
        invalid_duration_bounds = number("""SELECT count(*) FROM events e LEFT JOIN
            (SELECT app_id,user_id,session_id,min(event_time) started_at FROM events
             WHERE event_name='session_start' GROUP BY ALL) s USING(app_id,user_id,session_id)
            WHERE e.event_name='session_end' AND (s.started_at IS NULL
                OR e.engaged_seconds>epoch(e.event_time-s.started_at) OR e.event_time<s.started_at)""")
        apps = [row[0] for row in c.execute("SELECT DISTINCT app_id FROM users ORDER BY app_id").fetchall()]
        distributions = {field: [{"value": row[0], "users": row[1]} for row in c.execute(
            f"SELECT {field},count(*) FROM users GROUP BY {field} ORDER BY count(*) DESC,{field} LIMIT 100").fetchall()]
            for field in ("platform", "country", "acquisition_source")}
        missing_dimensions = {field: number(f"SELECT count(*) FROM users WHERE {field} IS NULL")
                              for field in ("country", "acquisition_source")}
        distribution_coverage = {field: {
            "total_groups": number(f"SELECT count(*) FROM (SELECT {field} FROM users GROUP BY {field})"),
            "omitted_users": number("SELECT count(*) FROM users")-sum(row["users"] for row in rows),
        } for field, rows in distributions.items()}
        unknown_format = number("SELECT count(*) FROM events WHERE event_name='ad_impression' AND (ad_format IS NULL OR ad_format='unknown')")
    counts = manifest["counts"]
    blockers = []
    if len(apps) != 1:
        blockers.append("SINGLE_APP_REQUIRED")
    if counts["users"]["retained_rows"] == 0:
        blockers.append("NO_VALID_USERS")
    if any(counts[role]["quarantined_keys"] for role in ("users", "events")):
        blockers.append("QUARANTINED_IDENTITIES")
    if counts["events"]["link_rejections"]:
        blockers.append("UNRECONCILED_EVENTS")
    if missing_revenue:
        blockers.append("MISSING_AD_REVENUE")
    if negative_revenue:
        blockers.append("CORRECTION_UNSUPPORTED")
    timing = export_metadata["revenue_timing"]
    revenue_timing_known = timing == "immediate" or (timing == "available_at" and missing_available == 0)
    capabilities = {
        "revenue_analysis": {"enabled": not blockers, "reasons": blockers},
        "revenue_trigger": {"enabled": not blockers and revenue_timing_known,
                            "reasons": blockers+([] if revenue_timing_known else ["REVENUE_AVAILABILITY_UNKNOWN"])},
        "ad_frequency": {"enabled": True, "reasons": []},
        "session_count": {"enabled": session_starts > 0 and missing_start_ids == 0,
                          "reasons": (["SESSION_STARTS_ABSENT"] if not session_starts else [])+(["SESSION_ID_MISSING"] if missing_start_ids else [])},
        "engaged_seconds": {"enabled": session_ends > 0 and not bad_ends and not repeated_ends and not invalid_duration_bounds,
                            "reasons": (["SESSION_ENDS_ABSENT"] if not session_ends else [])+(["SESSION_DURATION_INCOMPLETE"] if bad_ends else [])+(["SESSION_END_DUPLICATED"] if repeated_ends else [])+(["SESSION_DURATION_UNVERIFIABLE"] if invalid_duration_bounds else [])},
    }
    quality = {"schema_version": "1.0", "synthetic": export_metadata["synthetic"],
               "counts": counts, "zero_event_users": zero_events,
               "excluded_input_rows": {role: counts[role]["input_rows"]-counts[role]["retained_rows"] for role in ("users", "events")},
               "missing": {"ad_revenue": missing_revenue, "ad_available_at": missing_available,
                           "session_start_id": missing_start_ids, "session_end_data": bad_ends, **missing_dimensions},
               "negative_revenue_events": negative_revenue, "unknown_ad_format_events": unknown_format,
               "capabilities": capabilities, "normal_recommendations_allowed": not blockers,
               "warnings": ["Historical association is not campaign uplift.", "Reason counts may overlap; excluded_input_rows includes duplicate input rows."]}
    profile = {"schema_version": "1.0", "synthetic": export_metadata["synthetic"], "apps": apps,
               "complete_through": export_metadata["complete_through"], "distributions": distributions,
               "distribution_limit": 100, "distribution_coverage": distribution_coverage,
               "missing_dimensions": missing_dimensions,
               "users": counts["users"]["retained_rows"], "events": counts["events"]["retained_rows"],
               "capabilities": capabilities}
    destination.mkdir(parents=True, exist_ok=False)
    outputs = []
    for name, value in (("quality", quality), ("dataset_profile", profile)):
        path = destination/f"{name}.json"
        with path.open("x") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        outputs.append({"name": name, "path": path.name, "sha256": file_hash(path), "size_bytes": path.stat().st_size})
    partial = destination/"manifest.partial.json"
    with partial.open("x") as stream:
        json.dump({"schema_version": "1.0", "stage": "quality", "artifacts": outputs}, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(partial, destination/"manifest.json")
    partial.unlink()
    return quality, profile


def build_casual_quality(normalized_dir, export_metadata, destination):
    """Build V3 metric-level capabilities without changing legacy quality output."""
    normalized_dir, destination = Path(normalized_dir), Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    base_quality, base_profile = build_quality(normalized_dir, export_metadata, destination/"base")
    with connect(config={"memory_limit": "256MB", "threads": 2}) as c:
        c.read_parquet(str(normalized_dir/"events.parquet")).create_view("events")
        def number(sql):
            return c.execute(sql).fetchone()[0]
        level_events = number("SELECT count(*) FROM events WHERE event_name LIKE 'level_%'")
        missing_level_id = number("SELECT count(*) FROM events WHERE event_name LIKE 'level_%' AND level_id IS NULL")
        missing_level_index = number("SELECT count(*) FROM events WHERE event_name LIKE 'level_%' AND level_index IS NULL")
        missing_attempt_id = number("SELECT count(*) FROM events WHERE event_name LIKE 'level_%' AND attempt_id IS NULL")
        level_index_conflicts = number("""SELECT count(*) FROM (
            SELECT app_id,level_id FROM events WHERE event_name LIKE 'level_%' AND level_id IS NOT NULL
            GROUP BY app_id,level_id HAVING count(DISTINCT level_index) FILTER(WHERE level_index IS NOT NULL)>1)""")
        terminal_conflicts = number("""SELECT count(*) FROM (
            SELECT app_id,user_id,level_id,attempt_id,
              count(*) FILTER(WHERE event_name='level_complete') complete_count,
              count(*) FILTER(WHERE event_name='level_fail') fail_count
            FROM events WHERE event_name LIKE 'level_%' AND level_id IS NOT NULL AND attempt_id IS NOT NULL
            GROUP BY ALL HAVING complete_count>1 OR (complete_count>0 AND fail_count>0))""")
        session_starts = number("SELECT count(*) FROM events WHERE event_name='session_start'")
        missing_cross_session = number("""SELECT count(*) FROM events
            WHERE event_name IN ('session_start','session_end','ad_impression','level_start','level_complete','level_fail')
              AND session_id IS NULL""")
    def capability(enabled, *reasons):
        return {"enabled": bool(enabled), "reasons": [reason for condition, reason in reasons if condition]}
    has_level = level_events > 0
    level_identity = has_level and missing_level_id == 0
    level_progress = level_identity and missing_level_index == 0 and level_index_conflicts == 0
    attempt_pairing = level_identity and missing_attempt_id == 0 and terminal_conflicts == 0
    session_return = session_starts > 0
    capabilities = {
        **base_quality["capabilities"],
        "level_event_counts": capability(has_level, (not has_level, "LEVEL_EVENTS_ABSENT")),
        "level_identity": capability(level_identity,
            (not has_level, "LEVEL_EVENTS_ABSENT"), (missing_level_id > 0, "LEVEL_ID_MISSING")),
        "level_progress": capability(level_progress,
            (not has_level, "LEVEL_EVENTS_ABSENT"), (missing_level_id > 0, "LEVEL_ID_MISSING"),
            (missing_level_index > 0, "LEVEL_INDEX_MISSING"),
            (level_index_conflicts > 0, "LEVEL_INDEX_CONFLICT")),
        "attempt_pairing": capability(attempt_pairing,
            (not has_level, "LEVEL_EVENTS_ABSENT"), (missing_level_id > 0, "LEVEL_ID_MISSING"),
            (missing_attempt_id > 0, "ATTEMPT_ID_MISSING"),
            (terminal_conflicts > 0, "ATTEMPT_TERMINAL_CONFLICT")),
        "session_return": capability(session_return, (not session_return, "SESSION_STARTS_ABSENT")),
        "distinct_session_count": base_quality["capabilities"]["session_count"],
        "session_duration": base_quality["capabilities"]["engaged_seconds"],
        "same_session_cross": capability(session_return and missing_cross_session == 0,
            (not session_return, "SESSION_STARTS_ABSENT"),
            (missing_cross_session > 0, "SESSION_ID_MISSING_FOR_CROSS")),
    }
    casual_counts = {
        "level_events": level_events,
        "missing_level_id": missing_level_id,
        "missing_level_index": missing_level_index,
        "missing_attempt_id": missing_attempt_id,
        "level_index_conflicts": level_index_conflicts,
        "terminal_conflicts": terminal_conflicts,
        "missing_cross_session": missing_cross_session,
    }
    quality = {**base_quality, "schema_version": "3.0", "analysis_version": "3.0-casual-game",
               "casual_counts": casual_counts, "capabilities": capabilities}
    profile = {**base_profile, "schema_version": "3.0", "analysis_version": "3.0-casual-game",
               "casual_counts": casual_counts, "capabilities": capabilities}
    outputs = []
    for name, value in (("quality_v3", quality), ("dataset_profile_v3", profile)):
        path = destination/f"{name}.json"
        with path.open("x") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.flush(); os.fsync(stream.fileno())
        outputs.append({"name": name, "path": path.name, "sha256": file_hash(path),
                        "size_bytes": path.stat().st_size})
    partial = destination/"manifest.partial.json"
    with partial.open("x") as stream:
        json.dump({"schema_version":"3.0", "analysis_version":"3.0-casual-game",
                   "stage":"quality_v3", "artifacts":outputs}, stream, sort_keys=True, indent=2)
        stream.flush(); os.fsync(stream.fileno())
    os.link(partial, destination/"manifest.json"); partial.unlink()
    return quality, profile
