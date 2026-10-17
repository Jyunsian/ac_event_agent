"""Freeze prior rules before inspecting new-batch outcomes; never rerank them."""
import json
import os
from pathlib import Path
from jsonschema import Draft202012Validator
from server.analysis.freeze import freeze_candidates
from server.analysis.ingest import IngestError,file_hash
from server.analysis.predicates import validate_candidate


def write_manifest(directory,value):
    partial=directory/'manifest.partial.json'
    with partial.open('x') as stream:
        json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False)
        stream.flush();os.fsync(stream.fileno())
    os.link(partial,directory/'manifest.json');partial.unlink()


def prepare_fixed_recheck(feature_dir,target_dir,candidates,config,destination):
    feature_dir,target_dir,destination=map(Path,(feature_dir,target_dir,destination))
    schema=json.loads((Path(__file__).resolve().parents[2]/'contracts/schema.json').read_text())
    if not Draft202012Validator({**schema,'$ref':'#/$defs/config'}).is_valid(config):
        raise IngestError('INVALID_SEARCH_CONFIG')
    if (not isinstance(candidates,list) or not 1<=len(candidates)<=config['max_finalists']
            or len(candidates)>config['max_candidates']):raise IngestError('INVALID_RECHECK_CANDIDATES')
    for candidate in candidates:validate_candidate(candidate)
    if len({row['candidate_id'] for row in candidates})!=len(candidates):raise IngestError('DUPLICATE_RECHECK_CANDIDATE')
    features=json.loads((feature_dir/'manifest.json').read_text())
    targets=json.loads((target_dir/'manifest.json').read_text())
    scope=features['definition'].get('scope',{})
    if (scope.get('kind')!='exploration' or scope.get('split_id')!=targets['split_id']
            or scope.get('parent_source_manifest_sha256')!=targets['source_manifest_sha256']
            or scope.get('target_manifest_sha256')!=file_hash(target_dir/'manifest.json')):
        raise IngestError('RECHECK_SOURCE_MISMATCH')
    if targets['split_definition']['exploration_fraction']!=config['exploration_fraction']:
        raise IngestError('SEARCH_SPLIT_CONFIG_MISMATCH')
    windows={row['window_hours'] for row in candidates}
    if not windows<=set(features['definition']['windows_hours']) or not windows<=set(config['windows_hours']):
        raise IngestError('RECHECK_WINDOWS_NOT_MATERIALIZED')
    # No parquet/targets/metrics reads: even an apparently poor old rule remains in the freeze.
    destination.mkdir(parents=True,exist_ok=False)
    search_dir=destination/'search';search_dir.mkdir()
    ordered=sorted(candidates,key=lambda row:row['candidate_id'])
    search={'schema_version':'1.0','stage':'search','search_version':'1.0','synthetic':features['synthetic'],
            'config':config,'feature_id':features['feature_id'],'split_id':targets['split_id'],
            'source_manifest_sha256':targets['source_manifest_sha256'],'export_metadata':features['definition']['export_metadata'],
            'searched_windows':sorted(windows),'enumerated':0,'unique_before_cap':len(ordered),'selected_count':len(ordered),
            'truncated':False,'candidates':ordered,'thresholds':[],'atom_ranking':[],'pruning':[],
            'ranking_note':'Fixed prior finding conditions; no new-batch selection or threshold tuning.'}
    write_manifest(search_dir,search)
    selection_dir=destination/'selection';selection_dir.mkdir()
    selected=[row['candidate_id'] for row in ordered]
    receipt=freeze_candidates(search_dir,selected,selection_dir/'freeze')
    result={'schema_version':'1.0','stage':'finalist_selection','synthetic':features['synthetic'],
            'split_id':targets['split_id'],'ranking':[],'selected_ids':selected,'frozen':receipt,
            'selection_rule':'All supplied prior conditions frozen before any new-batch outcome inspection.'}
    write_manifest(selection_dir,result)
    write_manifest(destination,{'schema_version':'1.0','stage':'fixed_recheck','selected_ids':selected,
                                'search_sha256':file_hash(search_dir/'manifest.json'),
                                'selection_sha256':file_hash(selection_dir/'manifest.json')})
    return result
