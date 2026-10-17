"""D7 targets and chronological, whole-install-day cohorts. No revenue-driven splitting."""
import hashlib
import json
import os
from pathlib import Path

from server.analysis.connection import connect
from jsonschema import Draft202012Validator, FormatChecker

from server.analysis.ingest import IngestError, file_hash


def build_targets(normalized_dir, export_metadata, destination, exploration_fraction=0.7, *, revenue_availability=False):
    normalized_dir, destination = Path(normalized_dir), Path(destination)
    schema = json.loads((Path(__file__).resolve().parents[2]/"contracts/schema.json").read_text())
    if not Draft202012Validator({**schema, "$ref": "#/$defs/export"},
                               format_checker=FormatChecker()).is_valid(export_metadata):
        raise IngestError("INVALID_EXPORT_METADATA")
    if isinstance(exploration_fraction, bool) or not isinstance(exploration_fraction, (int, float)) or not 0 < exploration_fraction < 1:
        raise IngestError("INVALID_EXPLORATION_FRACTION")
    try:
        source_manifest = json.loads((normalized_dir/"manifest.json").read_text())
        for name in ("users", "events"):
            records = [a for a in source_manifest["artifacts"] if a["name"] == name]
            if len(records) != 1 or records[0]["path"] != name+".parquet":
                raise ValueError("Canonical artifact missing")
            path = normalized_dir/records[0]["path"]
            if path.resolve().parent != normalized_dir.resolve() or file_hash(path) != records[0]["sha256"]:
                raise IngestError("NORMALIZED_CHECKSUM_MISMATCH")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise IngestError("NORMALIZED_MANIFEST_INVALID") from error
    destination.mkdir(parents=True, exist_ok=False)
    with connect(str(destination/"work.duckdb"), config={
        "memory_limit": "256MB", "threads": 2, "autoload_known_extensions": False,
        "autoinstall_known_extensions": False}) as c:
        c.execute("SET TimeZone='UTC'")
        for name in ("users", "events"):
            c.read_parquet(str(normalized_dir/f"{name}.parquet")).create_view(name)
        c.execute("""CREATE TABLE cohorts AS SELECT app_id,user_id,installed_at,
            CAST(installed_at AS DATE) install_day,
            installed_at+INTERVAL '168 hours' <= CAST(? AS TIMESTAMPTZ) is_mature,
            'excluded_immature'::VARCHAR split FROM users""", [export_metadata["complete_through"]])
        days = c.execute("SELECT install_day,count(*) FROM cohorts WHERE is_mature GROUP BY install_day ORDER BY install_day").fetchall()
        mature_count = sum(row[1] for row in days)
        boundary = None
        if len(days) >= 4:
            cumulative, choices = 0, []
            for i, (_, count) in enumerate(days):
                cumulative += count
                if 2 <= i+1 <= len(days)-2:
                    choices.append((abs(cumulative/mature_count-exploration_fraction), days[i+1][0]))
            boundary = min(choices)[1]
        c.execute("UPDATE cohorts SET split='exploration' WHERE is_mature")
        if boundary is not None:
            c.execute("UPDATE cohorts SET split='holdout' WHERE is_mature AND install_day>=?", [boundary])
        unavailable="e.revenue_usd IS NULL OR e.revenue_usd<0"
        if revenue_availability and export_metadata["revenue_timing"]=="available_at":
            unavailable+=" OR e.available_at IS NULL OR e.available_at>CAST(? AS TIMESTAMPTZ)"
        c.execute(f"""CREATE TABLE targets AS
            SELECT u.*,count(e.event_id) d7_ad_events,
                count(e.event_id) FILTER (WHERE {unavailable}) missing_revenue_events,
                count(e.event_id) FILTER (WHERE e.revenue_usd<0) negative_revenue_events,
                CASE WHEN NOT u.is_mature THEN NULL
                     WHEN count(e.event_id) FILTER (WHERE {unavailable})>0 THEN NULL
                     ELSE coalesce(sum(e.revenue_usd ORDER BY e.revenue_usd),0) END d7_revenue_usd
            FROM cohorts u LEFT JOIN events e ON u.app_id=e.app_id AND u.user_id=e.user_id
                AND e.event_name='ad_impression' AND e.event_time>=u.installed_at
                AND e.event_time<u.installed_at+INTERVAL '168 hours'
            GROUP BY u.app_id,u.user_id,u.installed_at,u.install_day,u.is_mature,u.split""",
            [export_metadata["complete_through"]]*2 if "?" in unavailable else [])
        outputs = []
        for name in ("cohorts", "targets"):
            path = destination/f"{name}.parquet"
            c.execute(f"COPY (SELECT * FROM {name} ORDER BY app_id,user_id) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(path)])
            outputs.append({"name": name, "path": path.name, "sha256": file_hash(path), "size_bytes": path.stat().st_size})
        summary = {}
        for split in ("exploration", "holdout"):
            count, missing, total, arpu = c.execute("""SELECT count(*),count(*) FILTER (WHERE d7_revenue_usd IS NULL),
                sum(d7_revenue_usd ORDER BY app_id,user_id),avg(d7_revenue_usd ORDER BY app_id,user_id)
                FROM targets WHERE split=?""", [split]).fetchone()
            summary[split] = {"users": count, "unknown_targets": missing,
                              "revenue_usd": total if not missing else None, "arpu_usd": arpu if not missing else None}
        immature_count = c.execute("SELECT count(*) FROM cohorts WHERE NOT is_mature").fetchone()[0]
    split_definition = {"version": "1.0", "cohort_sha256": outputs[0]["sha256"],
                        "exploration_fraction": exploration_fraction,
                        "holdout_start_day": str(boundary) if boundary else None,
                        "complete_through": export_metadata["complete_through"]}
    split_id = hashlib.sha256(json.dumps(split_definition, sort_keys=True).encode()).hexdigest()
    manifest = {"schema_version": "1.0", "stage": "targets", "synthetic": export_metadata["synthetic"],
                "calculation_version":"3.0_availability_aware" if revenue_availability else "1.1_ordered_revenue_reduction",
                "source_manifest_sha256": file_hash(normalized_dir/"manifest.json"),
                "split_id": split_id, "split_definition": split_definition,
                "split_status": "holdout_available" if boundary else "exploratory_only",
                "split_reason": None if boundary else "INSUFFICIENT_INSTALL_DAYS",
                "mature_users": mature_count, "immature_users": immature_count,
                "install_days": [{"day": str(day), "users": count} for day, count in days],
                "summary": summary, "artifacts": outputs}
    if revenue_availability:manifest["analysis_version"]="3.0-casual-game"
    partial = destination/"manifest.partial.json"
    with partial.open("x") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(partial, destination/"manifest.json")
    partial.unlink()
    return manifest


def build_casual_targets(normalized_dir,export_metadata,destination,exploration_fraction=.7):
    """V3 D7 targets propagate delayed/unavailable revenue as unknown."""
    return build_targets(normalized_dir,export_metadata,destination,exploration_fraction,revenue_availability=True)
