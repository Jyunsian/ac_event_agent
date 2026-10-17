"""Cohort-bound overlap, threshold tradeoffs and observational revenue diagnostics."""
import hashlib
import json
import math
import os
from itertools import combinations_with_replacement
from pathlib import Path

from server.analysis.connection import connect

from server.analysis.ingest import IngestError, file_hash
from server.analysis.validation import verified_artifact


def build_diagnostics(normalized_dir, feature_dir, target_dir, trigger_dir, destination,
                      *, split="holdout", comparison_ids=None, landmarks=(24, 72)):
    roots = list(map(Path, (normalized_dir, feature_dir, target_dir, trigger_dir)))
    normalized_dir, feature_dir, target_dir, trigger_dir = roots
    destination = Path(destination)
    if split not in ("exploration", "holdout", "all_mature"):
        raise IngestError("INVALID_DIAGNOSTIC_SPLIT")
    if not landmarks or any(type(h) not in (int, float) or not math.isfinite(h) or not 0<h<168 for h in landmarks):
        raise IngestError("INVALID_LANDMARK")
    hashes = [(root/"manifest.json", file_hash(root/"manifest.json")) for root in roots]
    normalized, features, targets, triggers = [json.loads((root/"manifest.json").read_text()) for root in roots]
    scope = features["definition"].get("scope")
    feature_source = scope["parent_source_manifest_sha256"] if scope else features["definition"]["source_manifest_sha256"]
    if (hashes[0][1] != targets["source_manifest_sha256"] or feature_source != hashes[0][1]
            or features["feature_id"] != triggers["feature_id"]
            or features["definition"]["export_metadata"]["complete_through"] != targets["split_definition"]["complete_through"]):
        raise IngestError("DIAGNOSTIC_SOURCE_MISMATCH")
    if scope and (scope["split_id"] != targets["split_id"] or split != "exploration"):
        raise IngestError("DIAGNOSTIC_SCOPE_MISMATCH")
    candidates = triggers["candidates"]
    identities = [candidate["candidate_id"] for candidate in candidates]
    if len(set(identities)) != len(identities):
        raise IngestError("DUPLICATE_DIAGNOSTIC_CANDIDATE")
    selected = identities if comparison_ids is None else comparison_ids
    if len(selected)>10 or len(set(selected)) != len(selected) or not set(selected).issubset(identities):
        raise IngestError("DIAGNOSTIC_COMPARISON_SELECTION_REQUIRED")
    inputs = [verified_artifact(root, manifest, name) for root, manifest, name in
              ((normalized_dir, normalized, "events"), (target_dir, targets, "targets"), (trigger_dir, triggers, "triggers"))]
    cohort_id = hashlib.sha256((inputs[1][1]+":"+split).encode()).hexdigest()
    destination.mkdir(parents=True, exist_ok=False)
    overlap, sensitivity, post_trigger, landmark_results = [], [], [], []
    with connect(str(destination/"work.duckdb"), config={"memory_limit": "256MB", "threads": 2}) as c:
        c.execute("SET TimeZone='UTC'")
        for (path, _), name in zip(inputs, ("events", "targets", "triggers")):
            c.read_parquet(str(path)).create_view(name)
        c.execute("CREATE TABLE cohort AS SELECT * FROM targets WHERE is_mature AND (?='all_mature' OR split=?)", [split, split])
        c.execute("CREATE TABLE hits AS SELECT r.* FROM triggers r JOIN cohort t USING(app_id,user_id)")
        if c.execute("SELECT count(*) FROM (SELECT candidate_id,app_id,user_id FROM hits GROUP BY ALL HAVING count(*)>1)").fetchone()[0]:
            raise IngestError("DUPLICATE_DIAGNOSTIC_TRIGGER")
        population = c.execute("SELECT count(*) FROM cohort").fetchone()[0]
        sizes = {identity: c.execute("SELECT count(*) FROM hits WHERE candidate_id=?", [identity]).fetchone()[0] for identity in selected}
        for a, b in combinations_with_replacement(selected, 2):
            common = c.execute("""SELECT count(*) FROM hits a JOIN hits b USING(app_id,user_id)
                WHERE a.candidate_id=? AND b.candidate_id=?""", [a, b]).fetchone()[0]
            union = sizes[a]+sizes[b]-common
            overlap.append({"a": a, "b": b, "a_users": sizes[a], "b_users": sizes[b],
                            "intersection": common, "union": union, "jaccard": common/union if union else None,
                            "fraction_a_in_b": common/sizes[a] if sizes[a] else None,
                            "fraction_b_in_a": common/sizes[b] if sizes[b] else None,
                            "same_observed_users": sizes[a] == sizes[b] == common,
                            "empty_union": union == 0})
        for candidate in candidates:
            identity, predicate = candidate["candidate_id"], candidate["predicate"]
            n, unknown, mean, p99 = c.execute("""SELECT count(*),count(*) FILTER (WHERE d7_revenue_usd IS NULL),
                avg(d7_revenue_usd ORDER BY app_id,user_id),quantile_cont(d7_revenue_usd,.99) FROM cohort JOIN hits USING(app_id,user_id)
                WHERE candidate_id=?""", [identity]).fetchone()
            atom = predicate["op"] not in ("and", "or", "sequence")
            family = {"op": predicate["op"], "ad_format": predicate.get("ad_format", "all"),
                      "window_hours": candidate["window_hours"]} if atom else None
            sensitivity.append({"candidate_id": identity, "family": family,
                                "threshold": predicate.get("threshold"), "cohort_id": cohort_id,
                                "cohort_users": population, "triggered_users": n, "unknown_targets": unknown,
                                "coverage": n/population if population else None,
                                "triggered_arpu_usd": mean if not unknown else None,
                                "triggered_revenue_p99_usd": p99 if not unknown else None})
        def revenue_summary(table, filter_sql="TRUE", params=()):
            n, unknown, total, mean = c.execute(f"""SELECT count(*),count(*) FILTER (WHERE revenue IS NULL),
                sum(revenue ORDER BY app_id,user_id),avg(revenue ORDER BY app_id,user_id) FROM {table} WHERE {filter_sql}""", params).fetchone()
            return {"users": n, "unknown_revenue_users": unknown,
                    "revenue_usd": total if not unknown else None, "arpu_usd": mean if not unknown else None}
        for identity in selected:
            c.execute("""CREATE OR REPLACE TEMP TABLE post AS SELECT t.app_id,t.user_id,
                CASE WHEN count(e.event_id) FILTER (WHERE e.revenue_usd IS NULL OR e.revenue_usd<0)>0 THEN NULL
                     ELSE coalesce(sum(e.revenue_usd ORDER BY e.revenue_usd),0) END revenue
                FROM cohort t JOIN hits r USING(app_id,user_id) LEFT JOIN events e
                    ON t.app_id=e.app_id AND t.user_id=e.user_id AND e.event_name='ad_impression'
                    AND e.event_time>r.triggered_at AND e.event_time<t.installed_at+INTERVAL '168 hours'
                WHERE r.candidate_id=? GROUP BY t.app_id,t.user_id""", [identity])
            post_trigger.append({"candidate_id": identity, **revenue_summary("post")})
            for hours in sorted(set(landmarks)):
                c.execute("""CREATE OR REPLACE TEMP TABLE landmark AS SELECT t.app_id,t.user_id,
                    coalesce(r.triggered_at<t.installed_at+?*INTERVAL '1 hour',false) triggered_before_landmark,
                    CASE WHEN count(e.event_id) FILTER (WHERE e.revenue_usd IS NULL OR e.revenue_usd<0)>0 THEN NULL
                         ELSE coalesce(sum(e.revenue_usd ORDER BY e.revenue_usd),0) END revenue
                    FROM cohort t LEFT JOIN hits r ON t.app_id=r.app_id AND t.user_id=r.user_id AND r.candidate_id=?
                    LEFT JOIN events e ON t.app_id=e.app_id AND t.user_id=e.user_id AND e.event_name='ad_impression'
                        AND e.event_time>=t.installed_at+?*INTERVAL '1 hour' AND e.event_time<t.installed_at+INTERVAL '168 hours'
                    GROUP BY t.app_id,t.user_id,t.installed_at,r.triggered_at""", [hours, identity, hours])
                landmark_results.append({"candidate_id": identity, "landmark_hours": hours,
                    "cohort_id": cohort_id, "triggered": revenue_summary("landmark", "triggered_before_landmark"),
                    "untriggered": revenue_summary("landmark", "NOT triggered_before_landmark")})
    for path, digest in hashes+inputs:
        if file_hash(path) != digest:
            raise IngestError("DIAGNOSTIC_SOURCE_CHANGED")
    common = {"schema_version": "1.0", "synthetic": features["synthetic"], "cohort_id": cohort_id,
              "split": split, "cohort_users": population, "evidence_status": "exploratory",
              "warnings": ["Observational diagnostics, not causal uplift.",
                           "Post-trigger revenue excludes every event at the trigger timestamp; main ARPU is not trimmed."]}
    outputs = []
    for name, content in (("overlap", {"comparison_ids": selected, "pairs": overlap, "empty_set_policy": "undefined fractions are null"}),
                          ("sensitivity", {"points": sensitivity}),
                          ("landmark", {"post_trigger": post_trigger, "landmarks": landmark_results,
                                        "grouping": "trigger strictly before landmark; revenue [landmark,168h)"})):
        path = destination/f"{name}.json"
        with path.open("x") as stream:
            json.dump({**common, **content}, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        outputs.append({"name": name, "path": path.name, "sha256": file_hash(path), "size_bytes": path.stat().st_size})
    manifest = {**common, "stage": "diagnostics", "artifacts": outputs,
                "source_manifest_hashes": [digest for _, digest in hashes]}
    partial = destination/"manifest.partial.json"
    with partial.open("x") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(partial, destination/"manifest.json")
    partial.unlink()
    return manifest
