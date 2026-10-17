"""Deterministic baseline orchestration. Every completed stage is recoverable from PG/S3."""
import json
import os
import shutil
import tempfile
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from server.analysis.diagnostics import build_diagnostics
from server.analysis.exploration import build_casual_search_features, build_search_features
from server.analysis.features import build_features
from server.analysis.finalists import select_and_freeze
from server.analysis.finding_recheck import prepare_fixed_recheck
from server.analysis.ingest import IngestError, canonicalize, file_hash
from server.analysis.predicates import evaluate_candidates
from server.analysis.quality import build_casual_quality, build_quality
from server.analysis.report import build_report
from server.analysis.search import generate_candidates
from server.analysis.casual_search import generate_casual_candidates
from server.analysis.casual_selection import select_casual_family
from server.analysis.casual_freeze import freeze_casual_family
from server.analysis.targets import build_casual_targets, build_targets
from server.analysis.segments import build_segment
from server.analysis.validation import validate_frozen
from server.analysis.casual_validation import validate_casual_family
from server.analysis.casual_features import build_casual_features
from server.analysis.catalog_v3 import build_catalog_v3
from server.analysis.report_v3 import build_report_v3
from server.analysis.casual_segment import build_casual_segment
from server.checkpoints import CheckpointStore, StageRunner
from server.db import Repository, database_engine, fingerprint
from server.jobs import Lease
from server.storage import ObjectManifest, S3Storage
from server.validation_policy import register_population,reserve_validation,backfill_exposed_populations
from server.stage_cache import StageCache
from server.validation_batches import ValidationBatches


def pipeline_version():
    root = Path(__file__).parent
    files = [Path(__file__), root/"pipeline_v4.py", root/"checkpoints.py", root/'validation_policy.py',root/'validation_batches.py',root/'stage_cache.py',root/'resources.py', *sorted((root/"analysis").glob("*.py"))]
    identities = {path.relative_to(root).as_posix(): file_hash(path) for path in files}
    identities.update({"contracts/"+path.name: file_hash(path) for path in sorted((root.parent/"contracts").glob("*.json"))})
    return fingerprint(identities)


def write_manifest(directory, value):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/"manifest.json").open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def build_v3_discovery_stages(normalized, targets, export, config, output_root):
    """Run the pre-holdout V3 boundary as one pipeline unit.

    Keeping this function free of validation inputs makes the CG03 freeze boundary
    explicit.  The persistent StageRunner integration is completed with the V3
    validation/report stages rather than publishing a partial baseline.
    """
    output_root=Path(output_root)
    output_root.mkdir(parents=True,exist_ok=False)
    feature=build_casual_search_features(normalized,targets,export,output_root/"exploration",config["windows_hours"])
    search=generate_casual_candidates(output_root/"exploration/features",targets,config,output_root/"search")
    selection=select_casual_family(output_root/"search",output_root/"selection")
    frozen=freeze_casual_family(output_root/"selection",output_root/"freeze")
    return {"feature_id":feature["feature_id"],"discovery_count":search["discovery_count"],
            "family_size":selection["family_size"],"priority_ids":selection["priority_ids"],"frozen":frozen}


def build_v3_validation_stage(normalized,targets,export,config,preholdout_root,output_root,*,batch_store=None):
    """Complete full-feature and frozen holdout validation after CG03 freeze."""
    preholdout_root,output_root=Path(preholdout_root),Path(output_root)
    output_root.mkdir(parents=True,exist_ok=False)
    full_features=build_casual_features(normalized,export,output_root/"full_features",config["windows_hours"])
    frozen_path=preholdout_root/"freeze/frozen.json"
    validation=validate_casual_family(normalized,output_root/"full_features",targets,preholdout_root/"freeze",
        file_hash(frozen_path),output_root/"validation",batch_store=batch_store)
    return {"feature_id":full_features["feature_id"],"family_size":validation["family_size"],
            "family_correction_complete":validation["family_correction_complete"],
            "validation_manifest_sha256":file_hash(output_root/"validation/manifest.json")}


def build_v3_report_stages(preholdout_root,validation_root,run_id,dataset_id,output_root):
    """Build catalog/details/value-map and all customer exports from validation truth."""
    preholdout_root,validation_root,output_root=map(Path,(preholdout_root,validation_root,output_root))
    output_root.mkdir(parents=True,exist_ok=False)
    catalog,value_map=build_catalog_v3(preholdout_root/"search",preholdout_root/"selection",
        validation_root/"validation",run_id,dataset_id,output_root/"catalog_source")
    report=build_report_v3(output_root/"catalog_source",validation_root/"validation",output_root/"report")
    return {"evaluated_count":catalog["evaluated_count"],"plotted_count":value_map["plotted_count"],
            "priority_count":len(report["candidates"]),"report_manifest_sha256":file_hash(output_root/"report/manifest.json")}


def _copy_checkpoint_tree(source,destination):
    """Copy a verified immutable stage tree into a separately keyed checkpoint."""
    source,destination=Path(source),Path(destination)
    before=file_hash(source/"manifest.json")
    shutil.copytree(source,destination)
    if file_hash(source/"manifest.json")!=before or file_hash(destination/"manifest.json")!=before:
        raise IngestError("V3_CHECKPOINT_COPY_MISMATCH")


def _run_v3_baseline(engine,storage,lease,run,ds,normalized,stage,paths,saved,modes,preflight):
    """Persistent Candidate Event V3 baseline or follow-up using PG/S3 StageRunner."""
    config,export=run["config"],ds["export_metadata"]
    quality_dir=stage("quality_v3",lambda output:build_casual_quality(normalized,export,output))
    quality=json.loads((quality_dir/"quality_v3.json").read_text())
    blockers=quality["capabilities"]["revenue_analysis"]["reasons"]
    structural={"SINGLE_APP_REQUIRED","NO_VALID_USERS","QUARANTINED_IDENTITIES","UNRECONCILED_EVENTS"}
    if structural.intersection(blockers):raise IngestError("V3_STRUCTURAL_QUALITY_BLOCKED")
    targets=stage("targets_v3",lambda output:build_casual_targets(
        normalized,export,output,config["exploration_fraction"]))
    segment=stage("segment_v3",lambda output:build_casual_segment(
        normalized,targets,config["segment"],config,output)) if config.get("segment") is not None else None
    analysis_config={key:value for key,value in config.items() if key!="segment"}
    def explore(output):
        feature=build_casual_search_features(normalized,targets,export,output,config["windows_hours"])
        write_manifest(output,{"schema_version":"3.0","analysis_version":"3.0-casual-game",
            "stage":"exploration_features_v3","feature_id":feature["feature_id"],
            "normalized_sha256":file_hash(output/"normalized/manifest.json"),
            "features_sha256":file_hash(output/"features/manifest.json"),
            "targets_sha256":file_hash(targets/"manifest.json")})
    exploration=stage("exploration_features_v3",explore)
    discovery=stage("discovery_v3",lambda output:generate_casual_candidates(
        exploration/"features",targets,analysis_config,output))
    discovery_membership=stage("discovery_membership_v3",lambda output:_copy_checkpoint_tree(discovery,output))
    def freeze(output):
        selection=select_casual_family(discovery_membership,output/"selection")
        receipt=freeze_casual_family(output/"selection",output/"freeze")
        write_manifest(output,{"schema_version":"3.0","analysis_version":"3.0-casual-game",
            "stage":"validation_freeze_v3","family_size":selection["family_size"],
            "priority_ids":selection["priority_ids"],"candidate_ids":selection["candidate_ids"],
            "selection_sha256":file_hash(output/"selection/manifest.json"),"frozen":receipt})
    frozen=stage("validation_freeze_v3",freeze)
    freeze_receipt=json.loads((frozen/"manifest.json").read_text())["frozen"]
    policy=reserve_validation(engine,lease,run["dataset_id"],frozen/"freeze",freeze_receipt["sha256"])
    full_features=stage("full_features_v3",lambda output:build_casual_features(
        normalized,export,output,config["windows_hours"]))
    candidate_ids=json.loads((frozen/"selection/manifest.json").read_text())["candidate_ids"]
    batches=ValidationBatches(
        StageRunner(CheckpointStore(engine,storage,lease),Path(full_features).parents[1],
                    pipeline_version(),ds["fingerprint"],config),
        freeze_receipt["sha256"],candidate_ids,version="3.0")
    holdout=stage("holdout_membership_v3",lambda output:validate_casual_family(
        normalized,full_features,targets,frozen/"freeze",freeze_receipt["sha256"],output,
        validation_policy=policy,batch_store=batches))
    validation=stage("validation_v3",lambda output:_copy_checkpoint_tree(holdout,output))
    validation_manifest=json.loads((validation/"manifest.json").read_text())
    def diagnostics(output):
        output.mkdir(parents=True,exist_ok=False)
        source=validation/"diagnostics/diagnostics.json";destination=output/"diagnostics.json"
        before=file_hash(source);shutil.copy2(source,destination)
        if file_hash(source)!=before or file_hash(destination)!=before:raise IngestError("V3_DIAGNOSTICS_COPY_MISMATCH")
        write_manifest(output,{"schema_version":"3.0","analysis_version":"3.0-casual-game",
            "stage":"diagnostics_v3","source_validation_sha256":file_hash(validation/"manifest.json"),
            "artifacts":[{"name":"diagnostics","path":"diagnostics.json","sha256":before,
                          "size_bytes":destination.stat().st_size}]})
    stage("diagnostics_v3",diagnostics)
    catalog=stage("catalog_v3",lambda output:build_catalog_v3(
        discovery,frozen/"selection",validation,run["id"],run["dataset_id"],output))
    report=stage("report_v3",lambda output:build_report_v3(catalog,validation,output,segment))
    report_model=json.loads((report/"report.json").read_text())
    result={"schema_version":"3.0","analysis_version":"3.0-casual-game","stage":"baseline_v3",
        "synthetic":export["synthetic"],"kind":run["kind"],
        "parent_run_id":str(run["parent_run_id"]) if run["parent_run_id"] else None,
        "run_id":str(lease.run_id),"dataset_id":str(run["dataset_id"]),"pipeline_version":pipeline_version(),
        "status":"analyzed","reasons":list(policy["reasons"]),
        "finalist_ids":validation_manifest["priority_ids"],"validation":validation_manifest["results"],
        "warnings":["Historical association is not campaign uplift."],
        "counts":{"discovery":json.loads((discovery/"manifest.json").read_text())["discovery_count"],
                  "validation":validation_manifest["family_size"],
                  "priority":len(validation_manifest["priority_ids"]),
                  "plotted":report_model["value_map"]["plotted_count"]}}
    stage("baseline_v3",lambda output:write_manifest(output,result))
    stage("cache_audit_v3",lambda output:write_manifest(output,{"schema_version":"3.0",
        "analysis_version":"3.0-casual-game","stage":"cache_audit_v3","run_id":str(run["id"]),
        "stage_modes":modes}))
    exported={
        "quality_v3":{"quality_v3.json":"quality","dataset_profile_v3.json":"dataset_profile"},
        "targets_v3":{"manifest.json":"targets"},
        "discovery_v3":{"manifest.json":"search"},
        "validation_freeze_v3":{"selection/manifest.json":"selection","freeze/frozen.json":"validation_freeze"},
        "validation_v3":{"manifest.json":"validation"},
        "diagnostics_v3":{"diagnostics.json":"casual_diagnostics"},
        "segment_v3":{"manifest.json":"segment"},
        "baseline_v3":{"manifest.json":"baseline"},
        "report_v3":{"report.json":"report_json","report.html":"report_html","report.csv":"report_csv",
                     "catalog/catalog.json":"candidate_catalog","catalog/search.json":"candidate_search",
                     "catalog/candidate_value_map_v3.json":"candidate_value_map_v3"}}
    artifacts=[]
    for name,entries in exported.items():
        if name not in saved:continue
        for entry in saved[name]["files"]:
            if entry["path"] in entries:
                obj=entry["object"]
                artifacts.append({"kind":entries[entry["path"]],**{key:obj[key] for key in ("object_key","sha256","size_bytes")}})
    return {"summary":{"stage":"baseline_v3","analysis_status":"analyzed",
        "completed_stages":list(saved),"stage_modes":modes,"reasons":result["reasons"],
        "counts":result["counts"],"resource_preflight":preflight},
        "artifacts":artifacts,"report_kind":"report_json"}


def run_baseline(engine, storage, lease, workspace):
    repo = Repository(engine)
    with engine.connect() as c:
        run = repo.get_run(c, lease.run_id)
        ds = c.execute(select(repo.tables["datasets"]).where(repo.tables["datasets"].c.id == run["dataset_id"])).mappings().one()
        rechecks=repo.tables.get('finding_rechecks')
        if rechecks is None:
            from sqlalchemy import text
            revision=c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
            if int(revision)>=15:raise IngestError('RECHECK_SCHEMA_MISSING')
            recheck=None  # Pre-feature databases cannot contain recheck requests; supports verified forward upgrades.
        else:
            recheck=c.execute(select(rechecks).where(rechecks.c.run_id==run['id'])).mappings().one_or_none()
    if run["kind"] not in ('baseline','followup') or ds["sealed_at"] is None:
        raise IngestError("INVALID_BASELINE_DATASET")
    from server.resources import Limits
    preflight=Limits.from_environment().preflight(sum(item['size_bytes'] for item in ds['manifest']),workspace)
    config, export = run["config"], ds["export_metadata"]
    if recheck and (run['kind']!='baseline' or fingerprint(recheck['sources'])!=recheck['snapshot_sha256']):
        raise IngestError('RECHECK_SNAPSHOT_MISMATCH')
    version = pipeline_version()
    branch=None
    if run['kind']=='followup':
        with engine.connect() as c:
            table=repo.tables['analysis_branches']
            branch=c.execute(select(table).where(table.c.run_id==run['id'])).mappings().one_or_none()
            if branch is None:raise IngestError('FOLLOWUP_PROVENANCE_REQUIRED')
            parent=repo.get_run(c,run['parent_run_id'])
            artifacts=repo.tables['artifacts']
            artifact=c.execute(select(artifacts).where(artifacts.c.id==branch['parent_report_artifact_id'])).mappings().one()
        context=branch['cache_context']
        if (parent['status']!='succeeded' or parent['dataset_id']!=run['dataset_id']
                or parent['config']['exploration_fraction']!=config['exploration_fraction']):
            raise IngestError('FOLLOWUP_PARENT_OR_SPLIT_INVALID')
        if (context['dataset_fingerprint']!=ds['fingerprint'] or context['mapping_sha256']!=fingerprint(ds['mapping'])
                or context['config_sha256']!=fingerprint(config)):
            raise IngestError('BRANCH_CACHE_CONTEXT_MISMATCH')
        if context['calculation_version']!=version or run['calculation_version']!=version:
            raise IngestError('BRANCH_CALCULATION_VERSION_CHANGED')
        parent_report=json.loads(storage.get_bytes(ObjectManifest(artifact['object_key'],branch['parent_report_sha256'],artifact['size_bytes'],'application/json')))
    runner = StageRunner(CheckpointStore(engine, storage, lease), workspace, version, ds["fingerprint"], config)
    cache=StageCache(engine,runner,ds,config,version,allow_reuse=branch is not None)
    paths, saved, modes = {}, {}, {}
    def stage(name, builder):
        upstream = {key: fingerprint(value) for key, value in saved.items()}
        path, checkpoint, mode = cache.run(name,builder,saved,upstream)
        paths[name], saved[name], modes[name] = path, checkpoint, mode
        return path
    def normalize(output):
        raw = output.parent/"raw"
        raw.mkdir()
        sources = []
        for index, entry in enumerate(ds["manifest"]):
            manifest = ObjectManifest(**{key: entry[key] for key in ("object_key", "sha256", "size_bytes", "content_type")})
            path = raw/f"{index}.{entry['format']}"
            storage.download_file(manifest, path)
            sources.append({"path": path, "role": entry["role"], "format": entry["format"], "sha256": entry["sha256"]})
        canonicalize(sources, ds["mapping"], output)
    normalized = stage("normalized", normalize)
    register_population(engine,run['dataset_id'],normalized)
    backfill_exposed_populations(engine,storage,workspace)
    if config.get("analysis_version")=="4.0-time-aware":
        if recheck is not None:raise IngestError("V4_RECHECK_NOT_SUPPORTED")
        from server.pipeline_v4 import run_v4
        return run_v4(engine,storage,lease,run,ds,normalized,stage,paths,saved,modes,preflight)
    if config.get("analysis_version")=="3.0-casual-game":
        if recheck is not None:raise IngestError("V3_RECHECK_NOT_SUPPORTED")
        return _run_v3_baseline(engine,storage,lease,run,ds,normalized,stage,paths,saved,modes,preflight)
    quality_dir = stage("quality", lambda output: build_quality(normalized, export, output))
    quality = json.loads((quality_dir/"quality.json").read_text())
    blockers = quality["capabilities"]["revenue_analysis"]["reasons"]
    result = {"schema_version": "1.0", "stage": "baseline", "synthetic": export["synthetic"],
              "kind":run['kind'],
              'parent_run_id':str(run['parent_run_id']) if run['parent_run_id'] else None,
              "run_id": str(lease.run_id), "dataset_id": str(run["dataset_id"]), "pipeline_version": version,
              "status": "diagnostic_only", "reasons": blockers, "finalist_ids": [], "validation": [],
              "warnings": ["Historical association is not campaign uplift."]}
    if recheck:result['finding_recheck']={'sources':recheck['sources'],'snapshot_sha256':recheck['snapshot_sha256'],
                                        'selection_policy':'fixed_prior_conditions_no_new_batch_ranking'}
    structural = {"SINGLE_APP_REQUIRED", "NO_VALID_USERS", "QUARANTINED_IDENTITIES", "UNRECONCILED_EVENTS"}
    if config.get('segment') is not None:
        if not branch:raise IngestError('SEGMENT_REQUIRES_BRANCH')
        targets=stage('targets',lambda output:build_targets(normalized,export,output,config['exploration_fraction']))
        if json.loads((targets/'manifest.json').read_text())['split_id']!=branch['cache_context']['parent_split_id']:
            raise IngestError('FOLLOWUP_SPLIT_CHANGED')
        full_features=stage('features',lambda output:build_features(normalized,export,output,config['windows_hours']))
        candidates=[{'schema_version':'1.0','candidate_id':row['candidate_id'],
            **{key:row['event_spec'][key] for key in ('window_hours','predicate','trigger_policy','dependencies')}}
            for row in parent_report['candidates']]
        if not candidates:
            candidates=(parent_report['summary'].get('segment') or {}).get('candidate_specs',[])
        def segment_builder(output):
            build_segment(normalized,targets,full_features,candidates,config['segment'],config,output)
        segment_dir=stage('segment',segment_builder)
        segment=json.loads((segment_dir/'manifest.json').read_text())
        result['reasons']=sorted(set(blockers+segment['reasons']))
    elif not structural.intersection(blockers):
        targets = stage("targets", lambda output: build_targets(normalized, export, output, config["exploration_fraction"]))
        if branch and branch['cache_context']['parent_split_id'] is not None:
            if json.loads((targets/'manifest.json').read_text())['split_id']!=branch['cache_context']['parent_split_id']:
                raise IngestError('FOLLOWUP_SPLIT_CHANGED')
        def explore(output):
            feature = build_search_features(normalized, targets, export, output, config["windows_hours"])
            write_manifest(output, {"schema_version": "1.0", "stage": "exploration", "feature_id": feature["feature_id"]})
        exploration = stage("exploration", explore)
        scoped_quality = json.loads((exploration/"features/quality/quality.json").read_text())
        if scoped_quality["normal_recommendations_allowed"]:
            fixed_dir=None
            if recheck:
                prior={source['candidate_id']:{'schema_version':'1.0','candidate_id':source['candidate_id'],
                    **{key:source['event_spec'][key] for key in ('window_hours','predicate','trigger_policy','dependencies')}} for source in recheck['sources']}
                fixed_dir=stage('fixed_recheck',lambda output:prepare_fixed_recheck(exploration/'features',targets,list(prior.values()),config,output))
                search_dir=fixed_dir/'search'
            else:
                search_dir = stage("search", lambda output: generate_candidates(exploration/"features", targets, config, output))
            search = json.loads((search_dir/"manifest.json").read_text())
            if search["candidates"]:
                trigger_dir = stage("exploration_triggers", lambda output: evaluate_candidates(
                    exploration/"normalized", exploration/"features", search["candidates"], output))
                selection_dir = fixed_dir/'selection' if fixed_dir else stage("selection", lambda output: select_and_freeze(search_dir, trigger_dir, targets, output))
                selection = json.loads((selection_dir/"manifest.json").read_text())
                freeze_name='family_freeze' if 'family_frozen' in selection else 'freeze'
                freeze_receipt=selection.get('family_frozen',selection['frozen'])
                policy=reserve_validation(engine,lease,run['dataset_id'],selection_dir/freeze_name,freeze_receipt['sha256'])
                full_features = stage("features", lambda output: build_features(normalized, export, output, config["windows_hours"]))
                batches=ValidationBatches(runner,freeze_receipt['sha256'],[c['candidate_id'] for c in search['candidates']]) if freeze_name=='family_freeze' else None
                validation_dir = stage("validation", lambda output: validate_frozen(normalized, full_features, targets,
                    selection_dir/freeze_name, freeze_receipt['sha256'], output,validation_policy=policy,batch_store=batches))
                validation = json.loads((validation_dir/"manifest.json").read_text())
                # Full exploration curves remain exploratory even after the frozen holdout check.
                stage("diagnostics", lambda output: build_diagnostics(normalized, exploration/"features", targets,
                    trigger_dir, output, split="exploration", comparison_ids=selection["selected_ids"]))
                result.update(status="analyzed" if quality["normal_recommendations_allowed"] else "diagnostic_only",
                              finalist_ids=selection["selected_ids"], validation=validation["results"])
                if not selection["selected_ids"]:
                    result["reasons"] = sorted(set(blockers+["NO_RELIABLE_CANDIDATES"]))
                elif not any(entry["evidence_status"] == "historically_validated" for entry in validation["results"]):
                    result["reasons"] = sorted(set(blockers+["NO_HISTORICALLY_VALIDATED_CANDIDATES"]))
            else:
                result["reasons"] = sorted(set(blockers+["NO_SEARCH_CANDIDATES"]))
        else:
            result["reasons"] = sorted(set(blockers+scoped_quality["capabilities"]["revenue_analysis"]["reasons"]))
    stage('cache_audit',lambda output:write_manifest(output,{'schema_version':'1.0','stage':'cache_audit','run_id':str(run['id']),'entries':cache.audit}))
    stage("baseline", lambda output: write_manifest(output, result))
    exported = {"quality": {"quality.json": "quality", "dataset_profile.json": "dataset_profile"},
                "baseline": {"manifest.json": "baseline"}, "validation": {"manifest.json": "validation"},
                "search": {"manifest.json": "search"}, "selection": {"manifest.json": "selection"},
                'fixed_recheck':{'search/manifest.json':'search','selection/manifest.json':'selection'},
                "targets": {"manifest.json": "targets"},'cache_audit':{'manifest.json':'cache_audit'},
                'segment':{'manifest.json':'segment'},
                "diagnostics": {f"{name}.json": name for name in ("overlap", "sensitivity", "landmark")}}
    sources = {}
    for name, entries in exported.items():
        if name in saved:
            for entry in saved[name]["files"]:
                if entry["path"] in entries:
                    sources[entries[entry["path"]]] = {"path": paths[name]/entry["path"],
                                                       "sha256": entry["object"]["sha256"],
                                                       "object_key": entry["object"]["object_key"]}
    stage("report", lambda output: build_report(sources, output))
    exported["report"] = {f"report.{suffix}": f"report_{suffix}" for suffix in ("json", "html", "csv")}
    for entry in saved['report']['files']:
        relative=entry['path']
        if relative=='catalog/catalog.json':exported['report'][relative]='candidate_catalog'
        elif relative=='catalog/search.json':exported['report'][relative]='candidate_search'
    # Return only compact object references through the bounded worker pipe.
    artifacts = []
    for name, entries in exported.items():
        if name not in saved:
            continue
        for entry in saved[name]["files"]:
            if entry["path"] in entries:
                obj = entry["object"]
                artifacts.append({"kind": entries[entry["path"]], **{key: obj[key] for key in ("object_key", "sha256", "size_bytes")}})
    return {"summary": {"stage": "baseline", "analysis_status": result["status"],
                        "completed_stages": list(saved), "stage_modes": modes, "reasons": result["reasons"],"resource_preflight":preflight},
            "artifacts": artifacts, "report_kind": "report_json"}


def baseline_from_environment(payload):
    from server.resources import Limits,monitor
    limits=Limits.from_environment()
    engine = database_engine()
    try:
        lease = Lease(UUID(payload["job_id"]), UUID(payload["run_id"]), UUID(payload["attempt_id"]),
                      payload["fence"], payload["worker_id"], payload["stage"])
        limits.work_root.mkdir(parents=True,exist_ok=True,mode=0o700)
        workspace = tempfile.mkdtemp(prefix="ac-baseline-",dir=limits.work_root)
        with monitor(limits,workspace) as observed:
            result=run_baseline(engine, S3Storage.from_environment(), lease, workspace)
        result['summary']['resource_usage']=dict(observed)
        result['summary']['resource_limits']={k:v for k,v in limits.describe().items() if k!='work_root'}
        return result
    finally:
        engine.dispose()
