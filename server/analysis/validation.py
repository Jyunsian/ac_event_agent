"""Frozen-only holdout validation, backed by verified canonical/target artifacts."""
import json
import os
from pathlib import Path

from server.analysis.connection import connect

from server.analysis.freeze import load_frozen
from server.analysis.ingest import IngestError, file_hash
from server.analysis.metrics import summarize_users, percentile
from server.analysis.evidence_memo import MembershipEvidenceMemo
from server.analysis.predicates import CAPABILITIES, evaluate_candidates, validate_candidate


def verified_artifact(root, manifest, name):
    root = Path(root)
    matches = [a for a in manifest["artifacts"] if a["name"] == name]
    if len(matches) != 1:
        raise IngestError("VALIDATION_ARTIFACT_INVALID")
    record = matches[0]
    path = root/record["path"]
    if path.resolve().parent != root.resolve() or file_hash(path) != record["sha256"]:
        raise IngestError("VALIDATION_CHECKSUM_MISMATCH")
    return path, record["sha256"]


def validate_frozen(normalized_dir, feature_dir, target_dir, frozen_dir, expected_sha256, destination,*,validation_policy=None,batch_store=None):
    normalized_dir, feature_dir, target_dir, frozen_dir, destination = map(Path,
        (normalized_dir, feature_dir, target_dir, frozen_dir, destination))
    manifest_hashes = [(root/"manifest.json", file_hash(root/"manifest.json"))
                       for root in (normalized_dir, feature_dir, target_dir, feature_dir/"quality")]
    contract = load_frozen(frozen_dir, expected_sha256)
    whole_family = contract['freeze_version']=='2.0'
    if batch_store is not None and (not whole_family or batch_store.frozen_sha256!=expected_sha256
            or batch_store.candidate_ids!=[c['candidate_id'] for c in contract['candidates']]):
        raise IngestError('VALIDATION_BATCH_SCOPE_MISMATCH')
    if whole_family:
        from server.analysis.statistics_v2 import welch_greater, holm_family
        expected={'test':'welch_one_sided_greater','multiplicity':'holm','alpha':.05,
                  'untestable_p':1,'family_scope':'all_frozen_candidates'}
        if any(contract['rules'].get(k)!=v for k,v in expected.items()):
            raise IngestError('VALIDATION_RULES_UNSUPPORTED')
    if validation_policy is not None and (validation_policy.get('frozen_sha256')!=expected_sha256 or validation_policy.get('split_id')!=contract['split_id']):
        raise IngestError('VALIDATION_POLICY_MISMATCH')
    targets = json.loads((target_dir/"manifest.json").read_text())
    features = json.loads((feature_dir/"manifest.json").read_text())
    source_hash = file_hash(normalized_dir/"manifest.json")
    if (contract["source_manifest_sha256"] != source_hash or targets["source_manifest_sha256"] != source_hash
            or features["definition"]["source_manifest_sha256"] != source_hash
            or features["definition"]["export_metadata"] != contract["export_metadata"]
            or features["definition"]["export_metadata"]["complete_through"] != targets["split_definition"]["complete_through"]
            or contract["split_id"] != targets["split_id"] or features["definition"].get("scope") is not None):
        raise IngestError("VALIDATION_SOURCE_OR_SPLIT_MISMATCH")
    rules = contract["rules"]
    if (rules["min_validation_days"] != 2 or rules["min_group_users_per_day"] != 20
            or rules["confidence_level"] != .95 or rules["daily_difference"] != "positive_on_all_observed_days"
            or rules["difference_interval_lower"] != "strictly_positive"):
        raise IngestError("VALIDATION_RULES_UNSUPPORTED")
    quality_root = feature_dir/"quality"
    if file_hash(quality_root/"manifest.json") != features["quality_manifest_sha256"]:
        raise IngestError("VALIDATION_QUALITY_MISMATCH")
    quality_manifest = json.loads((quality_root/"manifest.json").read_text())
    quality_path, quality_hash = verified_artifact(quality_root, quality_manifest, "quality")
    quality = json.loads(quality_path.read_text())
    if quality["capabilities"] != features["capabilities"]:
        raise IngestError("VALIDATION_CAPABILITIES_MISMATCH")
    target_path, target_hash = verified_artifact(target_dir, targets, "targets")
    source_users={}
    user_path=user_hash=None
    if whole_family:
        from server.analysis.source_diagnostics import summarize_sources
        from server.analysis.revenue_diagnostics import decompose_prepared_membership,prepare_revenue_windows
        user_path,user_hash=verified_artifact(normalized_dir,json.loads((normalized_dir/'manifest.json').read_text()),'users')
        event_path,event_hash=verified_artifact(normalized_dir,json.loads((normalized_dir/'manifest.json').read_text()),'events')
    supported, disabled = [], {}
    for candidate in contract["candidates"]:
        atoms = validate_candidate(candidate)
        reasons = [CAPABILITIES[atom["op"]] for atom in atoms if not features["capabilities"][CAPABILITIES[atom["op"]]]["enabled"]]
        if reasons:
            disabled[candidate["candidate_id"]] = sorted(set(reasons))
        else:
            supported.append(candidate)
    destination.mkdir(parents=True, exist_ok=False)
    triggers = None
    if supported:
        triggers = evaluate_candidates(normalized_dir, feature_dir, supported, destination/"triggers",
                                       holdout_targets=target_dir)
    results = []
    tests = {}
    with connect(str(destination/'work.duckdb'),config={"memory_limit": "256MB", "threads": 2}) as c:
        c.execute("SET TimeZone='UTC'")
        c.read_parquet(str(target_path)).create_view("targets")
        if whole_family:
            c.read_parquet(str(event_path)).create_view('events')
            c.read_parquet(str(user_path)).create_view('source_users')
            source_users={(a,u):s for a,u,s in c.execute('SELECT app_id,user_id,acquisition_source FROM source_users').fetchall()}
        if triggers:
            trigger_path, _ = verified_artifact(destination/"triggers", triggers, "triggers")
            c.read_parquet(str(trigger_path)).create_view("triggers")
        c.execute("""CREATE TEMP TABLE validation_users AS SELECT *,
            row_number() OVER (ORDER BY app_id,user_id)-1 validation_index
            FROM targets WHERE split='holdout' AND is_mature""")
        if triggers:
            c.execute('''CREATE TABLE indexed_triggers AS
                SELECT r.candidate_id,t.validation_index,epoch(r.triggered_at-t.installed_at) delay_seconds
                FROM validation_users t JOIN triggers r USING(app_id,user_id)
                WHERE r.triggered_at IS NOT NULL ORDER BY r.candidate_id,t.validation_index''')
        base_query=c.execute('''SELECT app_id,user_id,d7_revenue_usd revenue_usd,install_day
            FROM validation_users ORDER BY validation_index''')
        base_names=[column[0] for column in base_query.description]
        base_rows=[dict(zip(base_names,values)) for values in base_query.fetchall()]
        if whole_family:
            for row in base_rows:row['acquisition_source']=source_users[(row['app_id'],row['user_id'])]
        if whole_family and supported:
            windows={candidate['window_hours'] for candidate in supported}
            if any(candidate['candidate_id'] in contract['priority_ids'] for candidate in supported):
                windows.update(contract['diagnostic_windows_hours'])
            revenue_windows=prepare_revenue_windows(c,windows)
            identities=[(row['app_id'],row['user_id']) for row in base_rows]
            if any([(r[0],r[1]) for r in values]!=identities for values in revenue_windows.values()):
                raise IngestError('REVENUE_MEMBERSHIP_ALIGNMENT_MISMATCH')
        evidence_memo=MembershipEvidenceMemo(len(base_rows))
        revenue_memo=MembershipEvidenceMemo(len(base_rows))
        cached=None; pending=[]
        def checkpoint(position):
            if batch_store is None:return
            row=results[-1]
            if row['evidence_status']=='historically_validated':
                row['evidence_status']='exploratory'
                if row['metrics'] is not None: row['metrics']['evidence_status']='exploratory'
            pending.append({'row':row,'test':tests[row['candidate_id']]})
            if len(pending)==batch_store.size or position==len(contract['candidates'])-1:
                batch_store.save(position//batch_store.size,pending)
                pending.clear()
        for position,candidate in enumerate(contract["candidates"]):
            identity = candidate["candidate_id"]
            if batch_store is not None:
                if position%batch_store.size==0:cached=batch_store.load(position//batch_store.size)
                if cached is not None:
                    entry=cached[position%batch_store.size]
                    if entry['row']['candidate_id']!=identity:raise IngestError('VALIDATION_BATCH_ID_MISMATCH')
                    results.append(entry['row']);tests[identity]=entry['test']
                    continue
            if identity in disabled:
                if whole_family:
                    tests[identity]={'testable':False,'p_value':1.0,'statistic':None,
                                     'reasons':['FEATURE_CAPABILITY_DISABLED']}
                results.append({"candidate_id": identity, "metrics": None, "evidence_status": "insufficient_data",
                                "reasons": ["FEATURE_CAPABILITY_DISABLED"], "disabled_capabilities": disabled[identity]})
                if whole_family:
                    results[-1].update(source_diagnostics=None,revenue_decomposition=None,
                        diagnostic_unavailable_reason='TRIGGER_MEMBERSHIP_UNAVAILABLE')
                checkpoint(position)
                continue
            delays=dict(c.execute('''SELECT validation_index,delay_seconds FROM indexed_triggers
                WHERE candidate_id=?''',[identity]).fetchall())
            key=evidence_memo.key(delays)
            common=evidence_memo.get(key) if whole_family else None
            if common is None:
                rows=[{**row,'triggered':index in delays,'delay_seconds':delays.get(index)}
                      for index,row in enumerate(base_rows)]
                metrics = summarize_users(rows, seed=rules["seed"], bootstrap_replicates=rules["bootstrap_replicates"],
                    min_group_users=rules["min_group_users"], frozen=True, split="holdout",
                    quality_allowed=quality["normal_recommendations_allowed"])
                if whole_family:
                    common={'metrics':metrics,
                        'test':welch_greater([r['revenue_usd'] for r in rows if r['triggered']],
                                             [r['revenue_usd'] for r in rows if not r['triggered']]),
                        'source':summarize_sources(rows)}
                    evidence_memo.put(key,common)
            else:
                metrics=common['metrics']
                # Same users can reach distinct rules at different times.
                # Never reuse delay percentiles merely because membership matches.
                values=list(delays.values())
                metrics['delay_seconds']={'median':percentile(values,.5),'p90':percentile(values,.9)}
            if whole_family:tests[identity]=common['test']
            results.append({"candidate_id": identity, "metrics": metrics,
                            "evidence_status": metrics["evidence_status"], "reasons": metrics["reasons"]})
            if whole_family:
                results[-1]['source_diagnostics']=common['source']
                revenue_key=revenue_memo.window_key(candidate['window_hours'],key)
                decomposition=revenue_memo.get(revenue_key)
                if decomposition is None:
                    decomposition=decompose_prepared_membership(
                        revenue_windows[candidate['window_hours']],delays,candidate['window_hours'])
                    revenue_memo.put(revenue_key,decomposition)
                results[-1]['revenue_decomposition']=decomposition
                if identity in contract['priority_ids']:
                    results[-1]['landmarks']=[decompose_prepared_membership(revenue_windows[h],delays,h,landmark=True)
                        for h in contract['diagnostic_windows_hours']]
            checkpoint(position)
    if whole_family:
        corrected=holm_family(tests,[c['candidate_id'] for c in contract['candidates']])
        for row in results:
            inference=corrected[row['candidate_id']]
            row['inference']=inference
            if not inference['testable']:
                row['evidence_status']='insufficient_data'
                row['reasons']=sorted(set(row['reasons']+inference['reasons']))
            elif not inference['passed']:
                if row['evidence_status']=='historically_validated': row['evidence_status']='exploratory'
                row['reasons']=sorted(set(row['reasons']+['HOLM_NOT_SIGNIFICANT']))
            elif not row['reasons']:
                row['evidence_status']='historically_validated'
            if row['metrics'] is not None:
                row['metrics'].update(evidence_status=row['evidence_status'],reasons=row['reasons'])
    load_frozen(frozen_dir, expected_sha256, candidates=contract["candidates"])
    if whole_family and (file_hash(user_path)!=user_hash or file_hash(event_path)!=event_hash):
        raise IngestError('VALIDATION_SOURCE_CHANGED')
    if file_hash(target_path) != target_hash or file_hash(quality_path) != quality_hash:
        raise IngestError("VALIDATION_SOURCE_CHANGED")
    if any(file_hash(path) != digest for path, digest in manifest_hashes):
        raise IngestError("VALIDATION_SOURCE_CHANGED")
    output = {"schema_version": "1.0", "stage": "validation", "synthetic": contract["synthetic"],
              "frozen_sha256": expected_sha256, "split_id": targets["split_id"], "rules": rules,
              "target_sha256": target_hash, "quality_sha256": quality_hash, "results": results,
              "warnings": ["Historical association is not campaign uplift.", "Descriptive intervals are not multiple-comparison corrected."]}
    if whole_family:
        output.update(validation_version='2.0',family_size=contract['family_size'],
                      priority_ids=contract['priority_ids'],family_correction_complete=True)
    if validation_policy is not None:
        output['validation_policy']=validation_policy
        if not validation_policy['eligible']:
            for row in results:
                row['evidence_status']='exploratory'
                row['reasons']=sorted(set(row['reasons']+validation_policy['reasons']))
                if row['metrics'] is not None:
                    row['metrics']['evidence_status']='exploratory'
                    row['metrics']['reasons']=sorted(set(row['metrics']['reasons']+validation_policy['reasons']))
    partial = destination/"manifest.partial.json"
    with partial.open("x") as stream:
        json.dump(output, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(partial, destination/"manifest.json")
    partial.unlink()
    return output
