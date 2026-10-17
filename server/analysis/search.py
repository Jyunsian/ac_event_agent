"""Finite, auditable candidate generation using exploration-only aggregates."""
import hashlib
import json
import math
import os
from itertools import combinations, product, zip_longest
from pathlib import Path

from server.analysis.connection import connect
from jsonschema import Draft202012Validator

from server.analysis.ingest import IngestError, file_hash
from server.analysis.predicates import validate_candidate
from server.analysis.search_policy import threshold_grid, allocate_candidates
from server.analysis.v2_contract import QUANTILES as V2_QUANTILES
from server.analysis.priority import choose_priority

GRIDS = {"count": [1, 2, 3, 5, 8, 10, 20], "session_count": [2, 3, 5],
         "engaged_seconds": [60, 180, 600, 1800]}
QUANTILES = [.25, .5, .75, .9]


def candidate_for(window, predicate):
    if predicate["op"] in ("and", "or"):
        predicate = {**predicate, "clauses": sorted(predicate["clauses"], key=lambda p: json.dumps(p, sort_keys=True))}
    definition = {"window_hours": float(window), "predicate": predicate}
    identity = hashlib.sha256(json.dumps(definition, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return {"schema_version": "1.0", "candidate_id": identity, **definition,
            "trigger_policy": "first_match_once", "dependencies": []}


def generate_candidates(feature_dir, target_dir, config, destination):
    feature_dir, target_dir, destination = map(Path, (feature_dir, target_dir, destination))
    schema = json.loads((Path(__file__).resolve().parents[2]/"contracts/schema.json").read_text())
    if not Draft202012Validator({**schema, "$ref": "#/$defs/config"}).is_valid(config):
        raise IngestError("INVALID_SEARCH_CONFIG")
    if any(not math.isfinite(w) for w in config["windows_hours"]):
        raise IngestError("INVALID_SEARCH_CONFIG")
    features = json.loads((feature_dir/"manifest.json").read_text())
    targets = json.loads((target_dir/"manifest.json").read_text())
    scope = features["definition"].get("scope")
    if not scope or scope.get("kind") != "exploration":
        raise IngestError("EXPLORATION_SCOPED_FEATURES_REQUIRED")
    if (scope["parent_source_manifest_sha256"] != targets["source_manifest_sha256"]
            or scope["target_manifest_sha256"] != file_hash(target_dir/"manifest.json")
            or scope["split_id"] != targets["split_id"]):
        raise IngestError("SEARCH_SOURCE_MISMATCH")
    if config["exploration_fraction"] != targets["split_definition"]["exploration_fraction"]:
        raise IngestError("SEARCH_SPLIT_CONFIG_MISMATCH")
    windows = sorted(config["windows_hours"])
    if not set(windows).issubset(features["definition"]["windows_hours"]):
        raise IngestError("SEARCH_WINDOWS_NOT_MATERIALIZED")
    inputs = []
    for root, manifest, name in ((feature_dir, features, "snapshots"), (target_dir, targets, "targets"),
                                  (feature_dir, features, "timeline"), (target_dir, targets, "cohorts")):
        matched = [a for a in manifest["artifacts"] if a["name"] == name]
        if len(matched) != 1 or matched[0]["path"] != name+".parquet":
            raise IngestError("SEARCH_ARTIFACT_INVALID")
        path = root/matched[0]["path"]
        if path.resolve().parent != root.resolve() or file_hash(path) != matched[0]["sha256"]:
            raise IngestError("SEARCH_CHECKSUM_MISMATCH")
        inputs.append((path, matched[0]["sha256"]))
    destination.mkdir(parents=True, exist_ok=False)
    pruned, atoms, thresholds = [], [], []
    seen, pool = set(), []
    enumerated = 0
    def add(candidate, origin):
        nonlocal enumerated
        enumerated += 1
        validate_candidate(candidate)
        identity = candidate["candidate_id"]
        if identity in seen:
            pruned.append({"candidate_id": identity, "origin": origin, "reason": "EQUIVALENT_PREDICATE"})
            return
        seen.add(identity)
        pool.append(candidate)
    with connect(str(destination/"work.duckdb"), config={"memory_limit": "256MB", "threads": 2}) as c:
        c.read_parquet(str(inputs[0][0])).create_view("snapshots")
        c.read_parquet(str(inputs[1][0])).create_view("targets")
        c.read_parquet(str(inputs[2][0])).create_view("timeline")
        c.read_parquet(str(inputs[3][0])).create_view("cohorts")
        # Materialize only exploration before any threshold, support, or ranking query.
        c.execute("""CREATE TABLE exploration AS SELECT s.*,t.d7_revenue_usd
            FROM snapshots s JOIN targets t USING(app_id,user_id)
            WHERE t.split='exploration' AND t.is_mature""")
        unknown = c.execute("SELECT count(*) FROM targets WHERE split='exploration' AND d7_revenue_usd IS NULL").fetchone()[0]
        if unknown:
            raise IngestError("EXPLORATION_TARGETS_UNKNOWN")
        dimensions = c.execute("""SELECT DISTINCT window_hours,metric,ad_format FROM exploration
            WHERE enabled AND window_complete AND (ad_format='all' OR ad_format IN
                (SELECT DISTINCT ad_format FROM timeline)) ORDER BY ALL""").fetchall()
        for window, metric, ad_format in dimensions:
            if window not in windows:
                continue
            params = [window, metric, ad_format]
            # Bound repeated threshold scans to this dimension. The input remains
            # exploration-only; no holdout values participate in this materialization.
            c.execute('''CREATE OR REPLACE TEMP TABLE dimension_values AS
                SELECT app_id,user_id,value,d7_revenue_usd,
                    row_number() OVER (ORDER BY app_id,user_id)-1 AS membership_index FROM exploration
                WHERE window_hours=? AND metric=? AND ad_format=?''',params)
            total=c.execute('SELECT count(*) FROM dimension_values').fetchone()[0]
            c.execute('''CREATE OR REPLACE TEMP TABLE dimension_timeline AS
                SELECT l.app_id,l.user_id,l.available_at,l.value,t.installed_at
                FROM timeline l JOIN cohorts t USING(app_id,user_id)
                WHERE t.split='exploration' AND t.is_mature AND l.metric=? AND l.ad_format=?
                  AND l.available_at<t.installed_at+?*INTERVAL '1 hour' ''',[metric,ad_format,window])
            custom = config.get("thresholds", {}).get(metric)
            if custom is not None:
                grid = sorted(custom)
            else:
                quantiles, minimum, maximum = c.execute("""SELECT quantile_cont(value, ?),min(value),max(value)
                    FROM dimension_values WHERE value>0""", [list(V2_QUANTILES)]).fetchone()
                grid = threshold_grid(metric, quantiles, minimum, maximum, GRIDS.get(metric, ()))
            thresholds.append({"window_hours": window, "metric": metric, "ad_format": ad_format,
                               "values": sorted(set(grid)), "source": "configured_grid" if custom is not None else "exploration_positive_quantiles_and_fixed_grid",
                               "quantiles":list(V2_QUANTILES) if custom is None else []})
            for threshold in grid:
                predicate = {"op": metric, "threshold": threshold}
                if ad_format != "all":
                    predicate["ad_format"] = ad_format
                candidate = candidate_for(window, predicate)
                hits, hit_mean, miss_mean = c.execute("""SELECT count(*) FILTER (WHERE value>=?),
                    avg(d7_revenue_usd ORDER BY membership_index) FILTER (WHERE value>=?),
                    avg(d7_revenue_usd ORDER BY membership_index) FILTER (WHERE value<?)
                    FROM dimension_values""", [threshold, threshold, threshold]).fetchone()
                # A tested zero-support condition is still a client-visible result.
                if candidate["candidate_id"] not in seen:
                    p90 = c.execute("""SELECT quantile_cont(delay_seconds,.9) FROM (
                        SELECT epoch(min(available_at)-min(installed_at)) delay_seconds
                        FROM dimension_timeline WHERE value>=?
                        GROUP BY app_id,user_id)""",[threshold]).fetchone()[0]
                    atoms.append({"candidate": candidate, "support": hits,
                                  "difference": hit_mean-miss_mean if hits and miss_mean is not None else None,
                                  "candidate_id":candidate['candidate_id'], 'window_hours':window,
                                  'complexity':0,'triggered_users':hits,'untriggered_users':total-hits,
                                  'difference_usd':hit_mean-miss_mean if hits and miss_mean is not None else None,
                                  'coverage':hits/total if total else None,'p90_seconds':p90})
                add(candidate, "atom")
        atoms.sort(key=lambda a: (a["difference"] is None, -(a["difference"] or 0), a["candidate"]["candidate_id"]))
        parents = {}
        by_id = {a['candidate_id']:a for a in atoms}
        for window in windows:
            parents[str(window)] = choose_priority([a for a in atoms if a['window_hours']==window], {},
                limit=20, min_group_users=config['min_group_users'], deduplicate=False)
        pairs = [pair for selection in parents.values()
                 for pair in combinations([by_id[i] for i in selection['priority_ids']],2)]
        for left, right in pairs:
            a, b = left["candidate"], right["candidate"]
            if a["window_hours"] != b["window_hours"]:
                pruned.append({"parents": [a["candidate_id"], b["candidate_id"]], "reason": "DIFFERENT_WINDOWS_NOT_COMPOSABLE"})
                continue
            for op in ("and", "or"):
                p, q = a["predicate"], b["predicate"]
                if p["op"] == q["op"] and p.get("ad_format") == q.get("ad_format"):
                    threshold = (max if op == "and" else min)(p["threshold"], q["threshold"])
                    add(candidate_for(a["window_hours"], {**p, "threshold": threshold}), "simplified_"+op)
                else:
                    add(candidate_for(a["window_hours"], {"op": op, "clauses": [p, q]}), op)
        # Bounded event-type templates; no holdout-derived gap or repetition tuning.
        for window, first, second, gap, repeats in product(windows,
                ["ad_impression", "session_start", "session_end"],
                ["ad_impression", "session_start", "session_end"], [60, 600, 3600], [1, 2, 3]):
            add(candidate_for(window, {"op": "sequence", "steps": [first, second],
                "max_gap_seconds": gap, "repeats": repeats, "matching": "non_overlapping"}), "sequence")
    # Round-robin across windows ensures a tight cap does not silently favor one horizon.
    selected, excluded, budget = allocate_candidates(pool, windows, config['max_candidates'])
    pruned.extend({"candidate_id": p["candidate_id"], "candidate":p, "reason": "MAX_CANDIDATES_LIMIT", "evaluation_status":"not_evaluated"} for p in excluded)
    output = {"schema_version": "1.0", "stage": "search", "search_version": "2.0", "synthetic": features["synthetic"],
              "budget":budget,
              "compound_parents":parents,
              "config": config, "feature_id": features["feature_id"], "split_id": targets["split_id"],
              "source_manifest_sha256": targets["source_manifest_sha256"],
              "export_metadata": features["definition"]["export_metadata"],
              "searched_windows": windows, "enumerated": enumerated, "unique_before_cap": len(pool),
              "selected_count": len(selected), "truncated": len(selected)<len(pool),
              "candidates": selected, "thresholds": thresholds, "atom_ranking": atoms,
              "pruning": pruned, "ranking_note": "Exploration descriptive mean difference; not validation or causal uplift."}
    for path, digest in inputs:
        if file_hash(path) != digest:
            raise IngestError("SEARCH_SOURCE_CHANGED")
    partial = destination/"manifest.partial.json"
    with partial.open("x") as stream:
        json.dump(output, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(partial, destination/"manifest.json")
    partial.unlink()
    return output
