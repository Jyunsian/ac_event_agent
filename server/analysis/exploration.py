"""Derive exploration-only inputs before quality decisions, not after global flags."""
import json
from pathlib import Path

from server.analysis.connection import connect

from server.analysis.features import build_features
from server.analysis.casual_features import build_casual_features
from server.analysis.v2_contract import WINDOWS
from server.analysis.ingest import EVENT_TYPES, USER_TYPES, IngestError, canonicalize, file_hash


def build_search_features(normalized_dir, target_dir, export_metadata, destination, windows_hours=WINDOWS):
    normalized_dir, target_dir, destination = map(Path, (normalized_dir, target_dir, destination))
    original = json.loads((normalized_dir/"manifest.json").read_text())
    targets = json.loads((target_dir/"manifest.json").read_text())
    original_hash = file_hash(normalized_dir/"manifest.json")
    target_hash = file_hash(target_dir/"manifest.json")
    if original_hash != targets["source_manifest_sha256"]:
        raise IngestError("EXPLORATION_SOURCE_MISMATCH")
    if export_metadata["complete_through"] != targets["split_definition"]["complete_through"]:
        raise IngestError("EXPLORATION_CUTOFF_MISMATCH")
    verified = []
    for root, manifest, name in ((normalized_dir, original, "users"), (normalized_dir, original, "events"),
                                 (target_dir, targets, "cohorts")):
        records = [a for a in manifest["artifacts"] if a["name"] == name]
        if len(records) != 1 or records[0]["path"] != name+".parquet":
            raise IngestError("EXPLORATION_ARTIFACT_INVALID")
        path = root/records[0]["path"]
        if path.resolve().parent != root.resolve() or file_hash(path) != records[0]["sha256"]:
            raise IngestError("EXPLORATION_CHECKSUM_MISMATCH")
        verified.append((path, records[0]["sha256"]))
    destination.mkdir(parents=True, exist_ok=False)
    sources = []
    with connect(str(destination/"scope.duckdb"), config={"memory_limit": "256MB", "threads": 2}) as c:
        c.execute("SET TimeZone='UTC'")
        c.read_parquet(str(target_dir/"cohorts.parquet")).create_view("cohorts")
        for name in ("users", "events"):
            c.read_parquet(str(normalized_dir/f"{name}.parquet")).create_view(name)
            path = destination/f"exploration_{name}.parquet"
            c.execute(f"""COPY (SELECT s.* FROM {name} s SEMI JOIN cohorts t
                ON s.app_id=t.app_id AND s.user_id=t.user_id AND t.split='exploration' AND t.is_mature
                ORDER BY ALL) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)""", [str(path)])
            sources.append({"role": name, "format": "parquet", "path": path, "sha256": file_hash(path)})
    for path, digest in verified:
        if file_hash(path) != digest:
            raise IngestError("EXPLORATION_SOURCE_CHANGED")
    if file_hash(normalized_dir/"manifest.json") != original_hash or file_hash(target_dir/"manifest.json") != target_hash:
        raise IngestError("EXPLORATION_SOURCE_CHANGED")
    canonicalize(sources, {"users": {k: k for k in USER_TYPES}, "events": {k: k for k in EVENT_TYPES}},
                 destination/"normalized")
    return build_features(destination/"normalized", export_metadata, destination/"features", windows_hours,
                          scope={"kind": "exploration", "parent_source_manifest_sha256": original_hash,
                                 "target_manifest_sha256": target_hash, "split_id": targets["split_id"]})


def build_casual_search_features(normalized_dir, target_dir, export_metadata, destination, windows_hours=WINDOWS):
    """Materialize V3 features from mature exploration users only."""
    normalized_dir, target_dir, destination = map(Path,(normalized_dir,target_dir,destination))
    original=json.loads((normalized_dir/"manifest.json").read_text())
    targets=json.loads((target_dir/"manifest.json").read_text())
    original_hash=file_hash(normalized_dir/"manifest.json");target_hash=file_hash(target_dir/"manifest.json")
    if original_hash!=targets["source_manifest_sha256"]:
        raise IngestError("V3_EXPLORATION_SOURCE_MISMATCH")
    if export_metadata["complete_through"]!=targets["split_definition"]["complete_through"]:
        raise IngestError("V3_EXPLORATION_CUTOFF_MISMATCH")
    verified=[]
    for root,manifest,name in ((normalized_dir,original,"users"),(normalized_dir,original,"events"),(target_dir,targets,"cohorts")):
        records=[item for item in manifest["artifacts"] if item["name"]==name]
        if len(records)!=1 or records[0]["path"]!=name+".parquet":raise IngestError("V3_EXPLORATION_ARTIFACT_INVALID")
        path=root/records[0]["path"]
        if path.resolve().parent!=root.resolve() or file_hash(path)!=records[0]["sha256"]:
            raise IngestError("V3_EXPLORATION_CHECKSUM_MISMATCH")
        verified.append((path,records[0]["sha256"]))
    destination.mkdir(parents=True,exist_ok=False)
    with connect(str(destination/"scope.duckdb"),config={"memory_limit":"256MB","threads":2}) as c:
        c.execute("SET TimeZone='UTC'")
        c.read_parquet(str(target_dir/"cohorts.parquet")).create_view("cohorts")
        sources=[]
        for name in ("users","events"):
            c.read_parquet(str(normalized_dir/f"{name}.parquet")).create_view(name)
            path=destination/f"exploration_{name}.parquet"
            c.execute(f"""COPY (SELECT s.* FROM {name} s SEMI JOIN cohorts t
              ON s.app_id=t.app_id AND s.user_id=t.user_id AND t.split='exploration' AND t.is_mature
              ORDER BY ALL)
              TO ? (FORMAT PARQUET,COMPRESSION ZSTD)""",[str(path)])
            sources.append({"role":name,"format":"parquet","path":path,"sha256":file_hash(path)})
    for path,digest in verified:
        if file_hash(path)!=digest:raise IngestError("V3_EXPLORATION_SOURCE_CHANGED")
    if file_hash(normalized_dir/"manifest.json")!=original_hash or file_hash(target_dir/"manifest.json")!=target_hash:
        raise IngestError("V3_EXPLORATION_SOURCE_CHANGED")
    canonicalize(sources,{"users":{k:k for k in USER_TYPES},"events":{k:k for k in EVENT_TYPES}},destination/"normalized")
    return build_casual_features(destination/"normalized",export_metadata,destination/"features",windows_hours,
        scope={"kind":"exploration","parent_source_manifest_sha256":original_hash,
               "target_manifest_sha256":target_hash,"split_id":targets["split_id"]})
