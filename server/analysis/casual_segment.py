"""Cohort-only V3 segment diagnostics over the immutable target split."""
import json
import os
from pathlib import Path

from server.analysis.connection import connect
from server.analysis.ingest import IngestError, file_hash
from server.analysis.segments import validate_segment
from server.analysis.validation import verified_artifact


def build_casual_segment(normalized_dir, target_dir, segment, config, destination):
    validate_segment(segment)
    normalized_dir, target_dir, destination = map(Path, (normalized_dir, target_dir, destination))
    normalized = json.loads((normalized_dir / "manifest.json").read_text())
    targets = json.loads((target_dir / "manifest.json").read_text())
    users, users_hash = verified_artifact(normalized_dir, normalized, "users")
    target_path, target_hash = verified_artifact(target_dir, targets, "targets")
    if targets["source_manifest_sha256"] != file_hash(normalized_dir / "manifest.json"):
        raise IngestError("SEGMENT_SOURCE_OR_SPLIT_MISMATCH")
    destination.mkdir(parents=True, exist_ok=False)
    result = {
        "schema_version": "3.0", "analysis_version": "3.0-casual-game", "stage": "segment_v3",
        "segment": segment, "split_id": targets["split_id"], "split_definition": targets["split_definition"],
        "evidence_status": "exploratory", "reasons": ["SEGMENT_DIAGNOSTIC_NOT_NEW_VALIDATION"],
        "candidate_metrics_evaluated": False, "cohorts": {},
    }
    field = segment["field"]
    with connect(config={"memory_limit": "256MB", "threads": 2}) as c:
        c.read_parquet(str(users)).create_view("users")
        c.read_parquet(str(target_path)).create_view("targets")
        columns = {row[0] for row in c.execute("DESCRIBE users").fetchall()}
        total = c.execute("SELECT count(*) FROM users").fetchone()[0]
        known = c.execute(f'SELECT count(*) FROM users WHERE "{field}" IS NOT NULL').fetchone()[0] if field in columns else 0
        result["field_known_users"] = known
        result["field_unknown_users"] = total - known
        if not known:
            result["selected_users"] = 0
            result["immature_users"] = 0
            result["reasons"].append("SEGMENT_FIELD_UNAVAILABLE")
        else:
            c.execute(f'''CREATE TABLE selected AS SELECT t.* FROM targets t JOIN users u USING(app_id,user_id)
                WHERE u."{field}"=?''', [segment["value"]])
            result["selected_users"] = c.execute("SELECT count(*) FROM selected").fetchone()[0]
            result["immature_users"] = c.execute("SELECT count(*) FROM selected WHERE NOT is_mature").fetchone()[0]
            if not result["selected_users"]:
                result["reasons"].append("SEGMENT_EMPTY")
            for split in ("exploration", "holdout"):
                count, unknown, revenue = c.execute('''SELECT count(*),
                    count(*) FILTER (WHERE d7_revenue_usd IS NULL),
                    sum(d7_revenue_usd ORDER BY app_id,user_id)
                    FROM selected WHERE is_mature AND split=?''', [split]).fetchone()
                reasons = []
                if count < config["min_group_users"]:
                    reasons.append("SEGMENT_TOO_SMALL")
                if unknown:
                    reasons.append("UNKNOWN_REVENUE")
                publish = not reasons
                result["cohorts"][split] = {
                    "users": count, "unknown_revenue_users": unknown, "reasons": reasons,
                    "revenue_usd": revenue if publish else None,
                    "arpu_usd": revenue / count if publish and count else None,
                }
    result["reasons"] = sorted(set(result["reasons"]))
    partial = destination / "manifest.partial.json"
    with partial.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.flush(); os.fsync(stream.fileno())
    os.link(partial, destination / "manifest.json"); partial.unlink()
    if file_hash(users) != users_hash or file_hash(target_path) != target_hash:
        raise IngestError("SEGMENT_SOURCE_CHANGED")
    return result
