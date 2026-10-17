"""Offline deterministic report exports; calculations are never performed by a model."""
import csv
import hashlib
import json
import os
from pathlib import Path

from server.analysis.ingest import IngestError, file_hash
from server.analysis.report_html import render_report
from server.analysis.finding_assessment import assess_recheck

CSV_COLUMNS = ["candidate_id", "event_name", "window_hours", "evidence_status", "users", "coverage",
               "triggered_arpu_usd", "all_arpu_usd", "untriggered_arpu_usd", "delay_median_seconds", "predicate_json"]
CSV_CONTEXT_COLUMNS=['csv_schema_version','run_id','dataset_id','parent_run_id','synthetic','analysis_status',
                     'target','data_scope_json','pipeline_version','event_spec_json','limitations_json']


def csv_context(model,spec=None):
    def packed(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False)
    return ['2.0',model['run_id'],model['dataset_id'],model['audit'].get('parent_run_id'),model['synthetic'],
        model['analysis_status'],model['summary']['target'],packed(model['summary']['data_scope']),
        model['audit']['pipeline_version'],packed(spec) if spec is not None else '',
        packed({'report':model['limitations'],'reasons':model['summary']['reasons'],
                'validation_policy':model['audit']['validation_policy']})]


def csv_safe(value):
    text = "" if value is None else str(value)
    return "'"+text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")) or text.startswith(("\t", "\r", "\n")) else text


def candidate_cells(row):
    metrics = row["metrics"] or {}
    groups = metrics.get("groups", {})
    return [row["candidate_id"], row["event_spec"]["event_name"], row["event_spec"]["window_hours"],
            row["evidence_status"], groups.get("all", {}).get("users"), metrics.get("coverage"),
            groups.get("triggered", {}).get("arpu_usd"), groups.get("all", {}).get("arpu_usd"),
            groups.get("untriggered", {}).get("arpu_usd"), metrics.get("delay_seconds", {}).get("median"),
            json.dumps(row["event_spec"]["predicate"], sort_keys=True, ensure_ascii=False)]


def event_spec(candidate,metadata):
    return {'event_name':'ac_'+hashlib.sha256(candidate['candidate_id'].encode()).hexdigest()[:24],
        'origin':metadata['origin'],'window_hours':candidate['window_hours'],
        'interval':'[install,install+window)','predicate':candidate['predicate'],
        'trigger_policy':candidate['trigger_policy'],'per_user_limit':1,
        'expired_policy':'do_not_emit_after_window','dependencies':candidate['dependencies'],
        'revenue_timing':metadata['revenue_timing']}


def build_report(sources, destination, *, title="IAA D7 候選事件分析"):
    """sources maps artifact name to {path,sha256}; caller must supply published stage evidence."""
    data, provenance = {}, {}
    for name, source in sources.items():
        path = Path(source["path"])
        if file_hash(path) != source["sha256"]:
            raise IngestError("REPORT_SOURCE_CHECKSUM_MISMATCH")
        data[name] = json.loads(path.read_text())
        provenance[name] = {"sha256": source["sha256"]}
        # Customer exports need source fingerprints, never internal bucket keys or local paths.
    if not {"baseline", "quality"}.issubset(data):
        raise IngestError("REPORT_REQUIRED_SOURCE_MISSING")
    baseline, quality = data["baseline"], data["quality"]
    identities = baseline["finalist_ids"]
    rows = []
    ranking = {r["candidate_id"]: r for r in data.get("selection", {}).get("ranking", [])}
    family_validation=data.get('validation',{}).get('validation_version')=='2.0'
    if identities or family_validation:
        if not {"search", "selection", "validation", "overlap", "sensitivity", "landmark"}.issubset(data):
            raise IngestError("REPORT_CANDIDATE_EVIDENCE_MISSING")
        expected_ids=[c['candidate_id'] for c in data['search']['candidates']] if family_validation else identities
        if data["selection"]["selected_ids"] != identities or [r["candidate_id"] for r in data["validation"]["results"]] != expected_ids:
            raise IngestError("REPORT_CANDIDATE_VERSION_MISMATCH")
        if family_validation and (not data['validation'].get('family_correction_complete')
                or data['validation'].get('priority_ids')!=identities
                or data['validation'].get('family_size')!=len(expected_ids)):
            raise IngestError('REPORT_INCOMPLETE_FAMILY_VALIDATION')
        if (baseline["validation"] != data["validation"]["results"]
                or data["selection"]['family_frozen' if family_validation else 'frozen']["sha256"] != data["validation"]["frozen_sha256"]
                or data["search"]["split_id"] != data["validation"]["split_id"]):
            raise IngestError("REPORT_EVIDENCE_VERSION_MISMATCH")
        available = {c["candidate_id"]: c for c in data["search"]["candidates"]}
        indexed={r['candidate_id']:(i,r) for i,r in enumerate(data['validation']['results'])}
        for index, entry in (indexed[identity] for identity in identities):
            identity = entry["candidate_id"]
            if identity not in available:
                raise IngestError("REPORT_CANDIDATE_SPEC_MISSING")
            candidate = available[identity]
            rows.append({"candidate_id": identity, "metrics": entry["metrics"],
                "evidence_status": entry["evidence_status"], "reasons": entry["reasons"],
                "event_spec": event_spec(candidate,data['search']['export_metadata']),
                "selection_evidence": ranking.get(identity),
                "evidence": {"artifact": "validation", "sha256": provenance["validation"]["sha256"], "json_pointer": f"/results/{index}"}})
    segment=data.get('segment')
    if segment:
        if segment.get('candidate_specs') and not segment.get('event_context'):
            raise IngestError('REPORT_SEGMENT_EVENT_CONTEXT_MISSING')
        segment['event_specs']=[{'candidate_id':candidate['candidate_id'],
            'event_spec':event_spec(candidate,segment['event_context'])} for candidate in segment.get('candidate_specs',[])]
    model = {"schema_version": "1.0", "title": title, "synthetic": baseline["synthetic"],
        "run_id": baseline["run_id"], "dataset_id": baseline["dataset_id"], "analysis_status": baseline["status"],
        "summary": {"target": "D7 ad revenue [install,install+168h)", "candidate_count": len(rows),
                    "searched_candidate_count": len(data["search"]["candidates"]) if "search" in data else None,
                    "historically_validated_count": sum(r["evidence_status"] == "historically_validated" for r in rows),
                    "data_profile": data.get("dataset_profile"), "quality": quality, "reasons": baseline["reasons"],
                    "targets": data.get("targets"),"segment":data.get('segment'),
                    "finding_recheck":assess_recheck(baseline.get('finding_recheck'),data.get('validation'),baseline['reasons'])},
        "candidates": rows, "diagnostics": {name: data.get(name) for name in ("overlap", "sensitivity", "landmark")},
        "test_guidance": "先考慮歷史證據、覆蓋與觸發速度，再檢查人群重疊；以目前優化事件為對照追蹤D7。這不是已驗證的投放提升或完整實驗設計。",
        "limitations": ["歷史關聯不等於投放因果效果。", "描述性區間未做多重搜尋校正。",
                        "缺少數值顯示為未知，不補零。", "探索診斷與holdout驗證使用不同人群，不能混用分母。"],
        "audit": {"pipeline_version": baseline["pipeline_version"], "sources": provenance,
                  'parent_run_id':baseline.get('parent_run_id'),
                  "selection_rule": data.get("selection", {}).get("selection_rule"),
                  "validation_rules": data.get("validation", {}).get("rules"),
                  "validation_policy": data.get("validation", {}).get("validation_policy"),
                  "cache":data.get('cache_audit'),
                  "search_config": data.get("search", {}).get("config"), "split_id": data.get("validation", {}).get("split_id"),
                  "frozen_sha256": data.get("validation", {}).get("frozen_sha256")}}
    profile=data.get('dataset_profile') or {};targets=data.get('targets') or {}
    days=[row['day'] for row in targets.get('install_days',[])]
    model['summary']['data_scope']={'apps':profile.get('apps',[]),'users':profile.get('users'),
        'events':profile.get('events'),'complete_through':profile.get('complete_through'),
        'install_day_from':min(days) if days else None,'install_day_to':max(days) if days else None,
        'split_id':targets.get('split_id'),'scope_note':'Counts describe the source dataset; segment denominators are separate.'}
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    if family_validation:
        from server.analysis.catalog import build_catalog
        catalog=build_catalog(data['search'],data['selection'],data['validation'],baseline['run_id'],baseline['dataset_id'],destination/'catalog',event_spec)
        model['schema_version']='2.0'
        model['catalog']={'sha256':file_hash(destination/'catalog/catalog.json'),
                          'evaluated_count':catalog['evaluated_count'],'priority_ids':catalog['priority_ids']}
    model_path = destination/"report.json"
    with model_path.open("x") as stream:
        json.dump(model, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    with (destination/"report.csv").open("x", newline="") as stream:
        writer = csv.writer(stream)
        segment=data.get('segment')
        if segment:
            writer.writerow(['record_type','segment_field','segment_value','split','candidate_id','users','revenue_usd','arpu_usd','evidence_status','reasons','metrics_json',*CSV_CONTEXT_COLUMNS])
            common=[segment['segment']['field'],segment['segment']['value']]
            specs={row['candidate_id']:row['event_spec'] for row in segment.get('event_specs',[])}
            if not segment['cohorts']:
                writer.writerow([csv_safe(v) for v in ['limitation',*common,'','','','','','exploratory',';'.join(segment['reasons']),'',*csv_context(model)]])
            for split,group in segment['cohorts'].items():
                writer.writerow([csv_safe(v) for v in ['cohort',*common,split,'',group['users'],group['revenue_usd'],group['arpu_usd'],'exploratory',';'.join(group['reasons']+segment['reasons']),'',*csv_context(model)]])
            for row in segment['candidates']:
                writer.writerow([csv_safe(v) for v in ['candidate',*common,row['split'],row['candidate_id'],row['users'],None,None,'exploratory',';'.join(row['reasons']),json.dumps(row['metrics'],ensure_ascii=False,allow_nan=False),*csv_context(model,specs.get(row['candidate_id']))]])
        else:
            writer.writerow(['record_type',*CSV_COLUMNS,*CSV_CONTEXT_COLUMNS])
            for row in rows:
                writer.writerow([csv_safe(value) for value in ['candidate',*candidate_cells(row),*csv_context(model,row['event_spec'])]])
            if not rows:
                empty=[None]*len(CSV_COLUMNS)
                empty[CSV_COLUMNS.index('evidence_status')]='not_evaluated'
                writer.writerow([csv_safe(value) for value in ['limitation',*empty,*csv_context(model)]])
    (destination/"report.html").write_text(render_report(model))
    artifacts = []
    if family_validation:
        for path in sorted((destination/'catalog').rglob('*.json')):
            relative=path.relative_to(destination).as_posix()
            artifacts.append({'name':'candidate_detail_'+path.stem if path.parent.name=='details' else 'candidate_'+path.stem,
                              'path':relative,'sha256':file_hash(path),'size_bytes':path.stat().st_size})
    for suffix in ("json", "csv", "html"):
        path = destination/f"report.{suffix}"
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
        artifacts.append({"name": "report_"+suffix, "path": path.name, "sha256": file_hash(path), "size_bytes": path.stat().st_size})
    for source in sources.values():
        if file_hash(source["path"]) != source["sha256"]:
            raise IngestError("REPORT_SOURCE_CHANGED")
    partial = destination/"manifest.partial.json"
    with partial.open("x") as stream:
        json.dump({"schema_version": "1.0", "stage": "report", "artifacts": artifacts}, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(partial, destination/"manifest.json")
    partial.unlink()
    return model
