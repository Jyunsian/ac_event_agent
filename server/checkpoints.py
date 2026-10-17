"""Persist verified stage trees to S3; publish metadata only under a current lease."""
import json
import re
import tempfile
from pathlib import Path, PurePosixPath

from sqlalchemy import text

from server.jobs import JobQueue
from server.db import fingerprint
from server.storage import ObjectManifest


class CheckpointError(Exception):
    pass


def release_stage_scratch(directory,published):
    """Release closed work databases only after durable stage publication.

    Downstream and recovery consume the same published artifact tree, never
    these transient databases. Failed builders/publications retain diagnostics.
    Unknown files, declared artifacts, original data and manifests stay intact.
    """
    directory=Path(directory)
    protected={entry['path'] for entry in published['files']}
    candidates=[]
    for path in directory.rglob('*'):
        if path.is_symlink() or not path.is_file():continue
        relative=path.relative_to(directory).as_posix()
        if relative in protected:continue
        database=path.name in {'work.duckdb','work.duckdb.wal','scope.duckdb','scope.duckdb.wal'}
        spill=(re.fullmatch(r'duckdb_temp_storage_(?:DEFAULT|S\d+K)-\d+\.tmp',path.name) is not None
               and path.parent.name in {'work.duckdb.tmp','scope.duckdb.tmp'})
        if not database and not spill:continue
        parent=path.parent.parent if spill else path.parent
        manifest=parent/'manifest.json'
        if not manifest.is_file() or manifest.is_symlink():continue
        data=json.loads(manifest.read_text())
        declared={a.get('path') for a in data.get('artifacts',[])}
        owner=path.name.removesuffix('.wal') if database else path.parent.name.removesuffix('.tmp')
        if (path.relative_to(parent).as_posix() in declared or owner in declared
                or (parent/owner).relative_to(directory).as_posix() in protected):continue
        # Never traverse a symlinked ancestor to remove files outside this stage.
        if path.resolve()!=directory.resolve()/path.relative_to(directory):continue
        candidates.append(path)
    for path in candidates:path.unlink()


class CheckpointStore:
    def __init__(self, engine, storage, lease):
        self.engine, self.storage, self.lease = engine, storage, lease
        self.queue = JobQueue(engine)

    def _identity(self, stage, version, input_sha256):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", stage) or not version or not re.fullmatch(r"[0-9a-f]{64}", input_sha256):
            raise CheckpointError("INVALID_CHECKPOINT_IDENTITY")
        return {"run": self.lease.run_id, "stage": stage, "version": version, "input": input_sha256}

    def lookup(self, stage, version, input_sha256):
        params = self._identity(stage, version, input_sha256)
        with self.engine.connect() as c:
            return c.execute(text("""SELECT manifest FROM stage_checkpoints WHERE run_id=:run
                AND stage=:stage AND stage_version=:version AND input_sha256=:input"""), params).scalar_one_or_none()

    def publish(self, stage, version, input_sha256, directory):
        params = self._identity(stage, version, input_sha256)
        directory = Path(directory)
        if not (directory/"manifest.json").is_file():
            raise CheckpointError("STAGE_MANIFEST_REQUIRED")
        # Check ownership before network work, but never hold a DB transaction while uploading.
        with self.engine.begin() as c:
            self.queue._owned(c, self.lease)
        files = []
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise CheckpointError("CHECKPOINT_SYMLINK_FORBIDDEN")
            if not path.is_file() or path.suffix not in (".json", ".parquet", ".html", ".csv"):
                continue  # DuckDB work databases, spill files, and temporary locks are not checkpoints.
            relative = path.relative_to(directory).as_posix()
            if ".partial." in path.name:
                raise CheckpointError("STAGE_HAS_PARTIAL_ARTIFACT")
            manifest = self.storage.put_file(self.storage.new_key("checkpoints", path.suffix[1:]), path)
            files.append({"path": relative, "object": manifest.to_dict()})
        manifest = {"schema_version": "1.0", "stage": stage, "stage_version": version,
                    "input_sha256": input_sha256, "files": files}
        params.update({"attempt": self.lease.attempt_id, "fence": self.lease.fence,
                       "manifest": json.dumps(manifest, allow_nan=False)})
        with self.engine.begin() as c:
            self.queue._owned(c, self.lease)
            c.execute(text("""INSERT INTO stage_checkpoints(run_id,stage,stage_version,input_sha256,attempt_id,fence,manifest)
                VALUES (:run,:stage,:version,:input,:attempt,:fence,CAST(:manifest AS jsonb))
                ON CONFLICT (run_id,stage,stage_version,input_sha256) DO NOTHING"""), params)
            # Existing immutable checkpoint wins; uploading alone never makes a stage visible.
            saved = c.execute(text("""SELECT manifest FROM stage_checkpoints WHERE run_id=:run
                AND stage=:stage AND stage_version=:version AND input_sha256=:input"""), params).scalar_one()
            self.queue._owned(c, self.lease)
            c.execute(text("""UPDATE runs SET progress=jsonb_build_object('stage',CAST(:stage AS text),
                'completed_stages',(SELECT jsonb_agg(stage ORDER BY created_at) FROM stage_checkpoints WHERE run_id=:run))
                WHERE id=:run"""), params)
        return saved

    def restore(self, manifest, destination):
        destination = Path(destination)
        paths = [entry["path"] for entry in manifest["files"]]
        if len(paths) != len(set(paths)) or "manifest.json" not in paths:
            raise CheckpointError("INVALID_CHECKPOINT_FILES")
        for relative in paths:
            path = PurePosixPath(relative)
            if path.is_absolute() or ".." in path.parts or "\\" in relative or str(path) != relative:
                raise CheckpointError("INVALID_CHECKPOINT_PATH")
        destination.mkdir(parents=True, exist_ok=False)
        # Root manifest is the local commit marker: restore it only after all other files verify.
        for entry in sorted(manifest["files"], key=lambda entry: entry["path"] == "manifest.json"):
            path = destination/entry["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            self.storage.download_file(ObjectManifest(**entry["object"]), path)
        return destination


class StageRunner:
    """Versioned stage execution with fresh local directories and durable cache lookup."""
    def __init__(self, store, workspace, pipeline_version, dataset_fingerprint, config):
        self.store, self.workspace = store, Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.identity = {"pipeline_version": pipeline_version, "dataset_fingerprint": dataset_fingerprint, "config": config}

    def run(self, stage, version, builder, *, upstream=None):
        input_hash = fingerprint({**self.identity, "stage": stage, "version": version, "upstream": upstream or {}})
        saved = self.store.lookup(stage, version, input_hash)  # Also validates stage before use as a path prefix.
        parent = Path(tempfile.mkdtemp(prefix=stage+"-", dir=self.workspace))
        output = parent/"result"
        if saved is not None:
            self.store.restore(saved, output)
            return output, saved, "restored"
        builder(output)
        saved = self.store.publish(stage, version, input_hash, output)
        release_stage_scratch(output,saved)
        return output, saved, "computed"
