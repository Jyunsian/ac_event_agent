"""Rank all evaluated candidate families on exploration only, then freeze."""
import json
import os
from collections import OrderedDict
from tempfile import TemporaryDirectory
from pathlib import Path

from server.analysis.connection import connect

from server.analysis.freeze import freeze_candidates
from server.analysis.ingest import IngestError, file_hash
from server.analysis.validation import verified_artifact
from server.analysis.priority import choose_priority

_GROUP_MEMO_ENTRIES = 256


def _descriptive_groups(c):
    return c.execute("""SELECT count(*) FILTER (WHERE r.membership_index IS NOT NULL),
        count(*) FILTER (WHERE r.membership_index IS NULL),
        avg(t.d7_revenue_usd ORDER BY t.membership_index) FILTER (WHERE r.membership_index IS NOT NULL),
        avg(t.d7_revenue_usd ORDER BY t.membership_index) FILTER (WHERE r.membership_index IS NULL),
        quantile_cont(r.delay_seconds,.9) FILTER (WHERE r.membership_index IS NOT NULL),
        quantile_cont(r.delay_seconds,.5) FILTER (WHERE r.membership_index IS NOT NULL)
        FROM exploration t LEFT JOIN current_triggers r USING(membership_index)""").fetchone()


def select_and_freeze(search_dir, trigger_dir, target_dir, destination):
    search_dir, trigger_dir, target_dir, destination = map(Path, (search_dir, trigger_dir, target_dir, destination))
    manifest_hashes = [(root/"manifest.json", file_hash(root/"manifest.json")) for root in (search_dir, trigger_dir, target_dir)]
    search = json.loads((search_dir/"manifest.json").read_text())
    triggers = json.loads((trigger_dir/"manifest.json").read_text())
    targets = json.loads((target_dir/"manifest.json").read_text())
    if (triggers["feature_id"] != search["feature_id"] or triggers["candidates"] != search["candidates"]
            or targets["split_id"] != search["split_id"]
            or targets["source_manifest_sha256"] != search["source_manifest_sha256"]):
        raise IngestError("FINALIST_INPUT_MISMATCH")
    target_path, target_hash = verified_artifact(target_dir, targets, "targets")
    trigger_path, trigger_hash = verified_artifact(trigger_dir, triggers, "triggers")
    destination.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='finalist-scratch-',dir=destination.parent) as scratch, connect(
            str(Path(scratch)/'work.duckdb'),config={"memory_limit": "256MB", "threads": 2}) as c:
        c.read_parquet(str(target_path)).create_view("targets")
        c.read_parquet(str(trigger_path)).create_view("triggers")
        c.execute("CREATE TABLE exploration AS SELECT *,row_number() OVER (ORDER BY app_id,user_id)-1 membership_index FROM targets WHERE split='exploration' AND is_mature")
        population=c.execute('SELECT count(*) FROM exploration').fetchone()[0]
        outside = c.execute("SELECT count(*) FROM triggers ANTI JOIN exploration USING(app_id,user_id)").fetchone()[0]
        if outside:
            raise IngestError("FINALIST_TRIGGERS_NOT_EXPLORATION_ONLY")
        if c.execute("SELECT count(*) FROM exploration WHERE d7_revenue_usd IS NULL").fetchone()[0]:
            raise IngestError("EXPLORATION_TARGETS_UNKNOWN")
        # Every empty-trigger candidate has the exact same full exploration
        # control group. Compute its ordered mean once, without dropping any
        # candidate, inventing zero revenue, or changing the sample gate.
        empty_result=(0,population,None,c.execute(
            'SELECT avg(d7_revenue_usd ORDER BY membership_index) FROM exploration').fetchone()[0],None,None)
        known=[row['candidate_id'] for row in search['candidates']]
        if c.execute('SELECT count(*) FROM triggers ANTI JOIN (SELECT unnest(?) candidate_id) known USING(candidate_id)',[known]).fetchone()[0]:
            raise IngestError('FINALIST_UNKNOWN_CANDIDATE')
        # Resolve long user identities once. Numeric joins and ordered candidate
        # blocks avoid re-decoding unrelated Parquet groups for every candidate.
        c.execute('''CREATE TABLE indexed_triggers AS
            SELECT r.candidate_id,t.membership_index,epoch(r.triggered_at-t.installed_at) delay_seconds
            FROM triggers r JOIN exploration t USING(app_id,user_id)
            ORDER BY r.candidate_id,t.membership_index''')
        ranking = []
        hit_sets = {}
        # One immutable exploration population per invocation. Full bitmap keys,
        # not digests; cache counts/means only, never candidate-specific delays.
        group_memo = OrderedDict()
        for candidate in search["candidates"]:
            c.execute('CREATE OR REPLACE TEMP TABLE current_triggers AS SELECT membership_index,delay_seconds FROM indexed_triggers WHERE candidate_id=?',
                      [candidate['candidate_id']])
            # Bound the duplicate aggregation to one candidate, not the full family.
            if c.execute('SELECT count(*) FROM (SELECT membership_index FROM current_triggers GROUP BY ALL HAVING count(*)>1)').fetchone()[0]:
                raise IngestError('DUPLICATE_CANDIDATE_TRIGGER')
            empty=not c.execute('SELECT EXISTS(SELECT 1 FROM current_triggers)').fetchone()[0]
            # Exact membership, one bit per stable exploration identity. No sketches.
            bits=bytearray((population+7)//8)
            indices=[] if empty else c.execute('SELECT membership_index FROM current_triggers').fetchall()
            for (index,) in indices:
                bits[index//8]|=1<<(index%8)
            membership=int.from_bytes(bits,'little')
            hit_sets[candidate['candidate_id']]=membership
            if empty:
                result=empty_result
            elif membership in group_memo:
                groups=group_memo[membership]
                group_memo.move_to_end(membership)
                delays=c.execute('SELECT quantile_cont(delay_seconds,.9),quantile_cont(delay_seconds,.5) '
                                 'FROM current_triggers').fetchone()
                result=(*groups,*delays)
            else:
                result=_descriptive_groups(c)
                if _GROUP_MEMO_ENTRIES>0:
                    group_memo[membership]=result[:4]
                    if len(group_memo)>_GROUP_MEMO_ENTRIES:group_memo.popitem(last=False)
            hits, misses, hit_mean, miss_mean, p90, median = result
            difference = hit_mean-miss_mean if hits and misses else None
            ranking.append({"candidate_id": candidate["candidate_id"], "triggered_users": hits,
                            "untriggered_users": misses, "difference_usd": difference,
                            'triggered_arpu_usd':hit_mean,'untriggered_arpu_usd':miss_mean,
                            'window_hours':candidate['window_hours'],
                            'coverage':hits/(hits+misses) if hits+misses else None,
                            'p90_seconds':p90,
                            'median_seconds':median,
                            'complexity':2 if candidate['predicate']['op']=='sequence' else
                                1 if candidate['predicate']['op'] in ('and','or') else 0})
    selection = choose_priority(ranking, hit_sets, limit=search['config']['max_finalists'],
                                min_group_users=search['config']['min_group_users'])
    selected = selection['priority_ids']
    for row in ranking:
        row.update(selection['selection'][row['candidate_id']])
    if file_hash(target_path) != target_hash or file_hash(trigger_path) != trigger_hash:
        raise IngestError("FINALIST_SOURCE_CHANGED")
    if any(file_hash(path) != digest for path, digest in manifest_hashes):
        raise IngestError("FINALIST_SOURCE_CHANGED")
    destination.mkdir(parents=True, exist_ok=False)
    receipt = freeze_candidates(search_dir, selected, destination/"freeze")
    family_receipt = freeze_candidates(search_dir, selected, destination/'family_freeze', full_family=True)
    if any(file_hash(path) != digest for path, digest in manifest_hashes):
        raise IngestError("FINALIST_SOURCE_CHANGED")
    output = {"schema_version": "1.0", "stage": "finalist_selection", "synthetic": search["synthetic"],
              "split_id": search["split_id"], "ranking": ranking, "selected_ids": selected,
              "frozen": receipt, "target_sha256": target_hash, "trigger_sha256": trigger_hash,
              'family_frozen':family_receipt,
              'selection_version':'2.0',
              "selection_rule": "Exploration sample gate; Pareto difference/coverage/P90 layers; alternating roles; Jaccard>=.90 alternatives. Not validation."}
    partial = destination/"manifest.partial.json"
    with partial.open("x") as stream:
        json.dump(output, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(partial, destination/"manifest.json")
    partial.unlink()
    return output
