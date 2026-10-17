"""Event-resolution monotone feature timelines and half-open window snapshots."""
import hashlib
import json
import math
import os
from pathlib import Path

from server.analysis.connection import connect

from server.analysis.ingest import IngestError, file_hash
from server.analysis.quality import build_quality
from server.analysis.v2_contract import WINDOWS

FEATURE_VERSION = "1.2"


def build_features(normalized_dir, export_metadata, destination, windows_hours=WINDOWS, *, scope=None):
    normalized_dir, destination = Path(normalized_dir), Path(destination)
    if not windows_hours or any(type(w) not in (int, float) or not math.isfinite(w) or not 0 < w <= 168 for w in windows_hours) or len(set(windows_hours)) != len(windows_hours):
        raise IngestError("INVALID_FEATURE_WINDOWS")
    windows = sorted(windows_hours)
    source_digest = file_hash(normalized_dir/"manifest.json")
    source_manifest = json.loads((normalized_dir/"manifest.json").read_text())
    destination.mkdir(parents=True, exist_ok=False)
    # Keep the exact quality evidence used to decide which features are trustworthy.
    quality, _ = build_quality(normalized_dir, export_metadata, destination/"quality")
    caps = quality["capabilities"]
    definition = {"version": FEATURE_VERSION, "windows_hours": windows,
                  "export_metadata": export_metadata,
                  "source_manifest_sha256": source_digest,
                  "interval": "[install,install+window)", "same_time": "aggregate_deltas",
                  "session_count": "distinct_session_id_first_start", "scope": scope}
    feature_id = hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()
    with connect(str(destination/"work.duckdb"), config={
        "memory_limit": "256MB", "threads": 2, "autoload_known_extensions": False,
        "autoinstall_known_extensions": False}) as c:
        c.execute("SET TimeZone='UTC'")
        for name in ("users", "events"):
            c.read_parquet(str(normalized_dir/f"{name}.parquet")).create_view(name)
        c.execute("""CREATE TABLE deltas(app_id VARCHAR,user_id VARCHAR,metric VARCHAR,
            ad_format VARCHAR,available_at TIMESTAMPTZ,delta DOUBLE)""")
        c.execute("CREATE TABLE dimensions(metric VARCHAR,ad_format VARCHAR,enabled BOOLEAN)")
        formats = ["all", "rewarded", "interstitial", "banner", "native", "app_open", "other", "unknown"]
        for metric, capability in (("count", "ad_frequency"), ("revenue_sum", "revenue_trigger"),
                                    ("session_count", "session_count"), ("engaged_seconds", "engaged_seconds")):
            scopes = formats if metric in ("count", "revenue_sum") else ["all"]
            for scope in scopes:
                c.execute("INSERT INTO dimensions VALUES (?,?,?)", [metric, scope, caps[capability]["enabled"]])
            if not caps[capability]["enabled"]:
                continue
            if metric in ("count", "revenue_sum"):
                time_column = "available_at" if metric == "revenue_sum" and export_metadata["revenue_timing"] == "available_at" else "event_time"
                delta = "1.0" if metric == "count" else "revenue_usd"
                c.execute(f"""INSERT INTO deltas SELECT app_id,user_id,?,scope,{time_column},{delta}
                    FROM events CROSS JOIN LATERAL (VALUES ('all'),(coalesce(ad_format,'unknown'))) f(scope)
                    WHERE event_name='ad_impression'""", [metric])
            elif metric == "session_count":
                c.execute("""INSERT INTO deltas SELECT app_id,user_id,'session_count','all',min(event_time),1.0
                    FROM events WHERE event_name='session_start' GROUP BY app_id,user_id,session_id""")
            else:
                c.execute("""INSERT INTO deltas SELECT app_id,user_id,'engaged_seconds','all',event_time,engaged_seconds
                    FROM events WHERE event_name='session_end'""")
        # Same timestamp events contribute together; no invented intra-timestamp ordering.
        # Ordered aggregates retain per-group state. Evaluate disjoint dimensions
        # separately so all metric/format groups do not coexist in the hash table.
        c.execute('''CREATE TABLE timeline(app_id VARCHAR,user_id VARCHAR,metric VARCHAR,
            ad_format VARCHAR,available_at TIMESTAMPTZ,value DOUBLE)''')
        for metric, ad_format in c.execute('SELECT DISTINCT metric,ad_format FROM deltas ORDER BY ALL').fetchall():
            c.execute("""INSERT INTO timeline SELECT app_id,user_id,metric,ad_format,available_at,
            sum(sum(delta ORDER BY delta)) OVER (PARTITION BY app_id,user_id,metric,ad_format ORDER BY available_at
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS value
            FROM deltas d JOIN users u USING(app_id,user_id)
            WHERE metric=? AND ad_format=? AND available_at>=installed_at AND available_at<installed_at+?*INTERVAL '1 hour'
                AND available_at<=CAST(? AS TIMESTAMPTZ)
            GROUP BY app_id,user_id,metric,ad_format,available_at""",
            [metric, ad_format, max(windows), export_metadata["exported_at"]])
        c.execute("CREATE TABLE windows(hours DOUBLE)")
        c.executemany("INSERT INTO windows VALUES (?)", [(w,) for w in windows])
        # Aggregate only observed timeline groups, then restore the complete
        # user/window/dimension grid. Zero-event users still get every snapshot;
        # disabled and incomplete values retain their original null semantics.
        c.execute("""CREATE TABLE observed_snapshots AS
            SELECT t.app_id,t.user_id,w.hours window_hours,t.metric,t.ad_format,max(t.value) observed_value
            FROM timeline t JOIN users u USING(app_id,user_id) CROSS JOIN windows w
            WHERE t.available_at<u.installed_at+w.hours*INTERVAL '1 hour'
            GROUP BY t.app_id,t.user_id,w.hours,t.metric,t.ad_format""")
        c.execute("""CREATE TABLE snapshots AS SELECT u.app_id,u.user_id,w.hours window_hours,
            d.metric,d.ad_format,d.enabled,
            u.installed_at+w.hours*INTERVAL '1 hour'<=CAST(? AS TIMESTAMPTZ) window_complete,
            CASE WHEN d.enabled THEN coalesce(t.observed_value,0) ELSE NULL END observed_value,
            CASE WHEN d.enabled AND u.installed_at+w.hours*INTERVAL '1 hour'<=CAST(? AS TIMESTAMPTZ)
                 THEN coalesce(t.observed_value,0) ELSE NULL END AS value
            FROM users u CROSS JOIN windows w CROSS JOIN dimensions d LEFT JOIN observed_snapshots t
                ON t.app_id=u.app_id AND t.user_id=u.user_id AND t.metric=d.metric AND t.ad_format=d.ad_format
                AND t.window_hours=w.hours""",
            [export_metadata["complete_through"], export_metadata["complete_through"]])
        outputs = []
        for name in ("timeline", "snapshots"):
            path = destination/f"{name}.parquet"
            c.execute(f"COPY (SELECT * FROM {name} ORDER BY ALL) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(path)])
            outputs.append({"name": name, "path": path.name, "sha256": file_hash(path),
                            "size_bytes": path.stat().st_size,
                            "rows": c.execute(f"SELECT count(*) FROM {name}").fetchone()[0]})
    if file_hash(normalized_dir/"manifest.json") != definition["source_manifest_sha256"]:
        raise IngestError("SOURCE_CHANGED_DURING_FEATURES")
    for artifact in source_manifest["artifacts"]:
        if file_hash(normalized_dir/artifact["path"]) != artifact["sha256"]:
            raise IngestError("SOURCE_CHANGED_DURING_FEATURES")
    manifest = {"schema_version": "1.0", "stage": "features", "feature_id": feature_id,
                "definition": definition, "capabilities": caps, "synthetic": export_metadata["synthetic"],
                "artifacts": outputs, "quality_manifest_sha256": file_hash(destination/"quality/manifest.json")}
    partial = destination/"manifest.partial.json"
    with partial.open("x") as stream:
        json.dump(manifest, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(partial, destination/"manifest.json")
    partial.unlink()
    return manifest
