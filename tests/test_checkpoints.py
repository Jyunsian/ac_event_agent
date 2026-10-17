import json

import pytest
from sqlalchemy import text

from server.checkpoints import CheckpointStore, StageRunner
from server.jobs import JobQueue, LeaseLost
from server.storage import StorageError
from sqlalchemy.exc import DBAPIError
from tests.test_jobs import jobdb, submit
from tests.test_upload_api import api


def test_true_postgres_s3_checkpoint_restore_and_fencing(api, jobdb, tmp_path):
    _, engine, storage = api
    run = submit(jobdb)
    queue = JobQueue(engine)
    lease = queue.claim("checkpoint-test")
    store = CheckpointStore(engine, storage, lease)
    stage = tmp_path/"stage"
    stage.mkdir()
    (stage/"values.json").write_text(json.dumps({"synthetic": True, "value": 42}))
    (stage/"manifest.json").write_text(json.dumps({"schema_version": "1.0", "synthetic": True}))
    (stage/"work.duckdb").write_bytes(b"transient workfile")
    assert store.lookup("quality", "v1", "a"*64) is None
    saved = store.publish("quality", "v1", "a"*64, stage)
    assert {entry["path"] for entry in saved["files"]} == {"values.json", "manifest.json"}
    assert store.lookup("quality", "v1", "b"*64) is None
    # A fresh store, no reference to the original local directory, restores from durable metadata/S3.
    fresh = CheckpointStore(engine, storage, lease)
    fresh.restore(fresh.lookup("quality", "v1", "a"*64), tmp_path/"restored")
    assert json.loads((tmp_path/"restored/values.json").read_text())["value"] == 42
    assert not (tmp_path/"restored/work.duckdb").exists()
    assert store.publish("quality", "v1", "a"*64, stage) == saved
    with engine.connect() as c:
        progress = c.execute(text("SELECT progress FROM runs WHERE id=:id"), {"id": run["id"]}).scalar_one()
        assert progress["completed_stages"] == ["quality"]
    queue.cancel(lease.job_id)
    with pytest.raises(LeaseLost):
        store.publish("targets", "v1", "a"*64, stage)
    assert store.lookup("targets", "v1", "a"*64) is None


def test_new_attempt_restores_old_checkpoint_and_integrity_failure_is_not_ready(api, jobdb, tmp_path):
    _, engine, storage = api
    submit(jobdb)
    queue = JobQueue(engine)
    first = queue.claim("first-attempt")
    stage = tmp_path/"stage"
    stage.mkdir()
    (stage/"values.json").write_text('{"synthetic":true}')
    (stage/"manifest.json").write_text('{"schema_version":"1.0"}')
    original = CheckpointStore(engine, storage, first)
    saved = original.publish("normalized", "v1", "b"*64, stage)
    queue.fail(first, "SYNTHETIC_FAILURE", retryable=True, retry_delay=0)
    second = queue.claim("second-attempt")
    assert second.attempt_id != first.attempt_id and second.fence > first.fence
    restored = CheckpointStore(engine, storage, second)
    restored.restore(restored.lookup("normalized", "v1", "b"*64), tmp_path/"new-workdir")
    assert (tmp_path/"new-workdir/manifest.json").exists()
    with pytest.raises(DBAPIError), engine.begin() as c:
        c.execute(text("UPDATE stage_checkpoints SET stage_version='mutated' WHERE run_id=:id"), {"id": second.run_id})
    bad = json.loads(json.dumps(saved))
    next(entry for entry in bad["files"] if entry["path"] == "values.json")["object"]["sha256"] = "0"*64
    with pytest.raises(StorageError, match="CHECKSUM_MISMATCH"):
        restored.restore(bad, tmp_path/"bad-restore")
    assert not (tmp_path/"bad-restore/manifest.json").exists()


def test_lost_lease_after_real_upload_cannot_publish_metadata(api, jobdb, tmp_path, monkeypatch):
    _, engine, storage = api
    submit(jobdb)
    queue = JobQueue(engine)
    lease = queue.claim("upload-race")
    store = CheckpointStore(engine, storage, lease)
    stage = tmp_path/"stage"
    stage.mkdir()
    (stage/"manifest.json").write_text('{"synthetic":true}')
    real_put = storage.put_file
    def upload_then_cancel(*args, **kwargs):
        uploaded = real_put(*args, **kwargs)
        queue.cancel(lease.job_id)
        return uploaded
    monkeypatch.setattr(storage, "put_file", upload_then_cancel)
    with pytest.raises(LeaseLost):
        store.publish("quality", "v1", "c"*64, stage)
    assert store.lookup("quality", "v1", "c"*64) is None


def test_stage_runner_reuses_durable_output_not_local_directory(api, jobdb, tmp_path):
    _, engine, storage = api
    submit(jobdb)
    lease = JobQueue(engine).claim("stage-runner")
    store = CheckpointStore(engine, storage, lease)
    calls = []
    def build(directory):
        calls.append(directory)
        directory.mkdir()
        (directory/"manifest.json").write_text('{"synthetic":true}')
        (directory/'work.duckdb').write_bytes(b'closed temporary database')
    first = StageRunner(store, tmp_path/"work-a", "pipeline-v1", "dataset-hash", {"window": 6})
    original, saved, status = first.run("quality", "v1", build)
    assert status == "computed"
    assert not (original/'work.duckdb').exists()
    (original/"manifest.json").write_text("local file no longer usable")
    second = StageRunner(store, tmp_path/"work-b", "pipeline-v1", "dataset-hash", {"window": 6})
    restored, again, status = second.run("quality", "v1", build)
    assert status == "restored" and again == saved and len(calls) == 1
    assert json.loads((restored/"manifest.json").read_text())["synthetic"]
    third = StageRunner(store, tmp_path/"work-c", "pipeline-v2", "dataset-hash", {"window": 6})
    _, _, status = third.run("quality", "v1", build)
    assert status == "computed" and len(calls) == 2


def test_scratch_cleanup_preserves_artifacts_unknown_files_and_symlinks(tmp_path):
    from server.checkpoints import release_stage_scratch
    root=tmp_path/'stage';root.mkdir()
    (root/'manifest.json').write_text(json.dumps({'artifacts':[{'path':'scope.duckdb'}]}))
    for name in ['work.duckdb','work.duckdb.wal','scope.duckdb','scope.duckdb.wal','original.csv','unknown.tmp']:
        (root/name).write_bytes(b'unchanged')
    spill=root/'work.duckdb.tmp';spill.mkdir()
    (spill/'duckdb_temp_storage_DEFAULT-0.tmp').write_bytes(b'spill')
    (spill/'not-a-duckdb-spill.tmp').write_bytes(b'keep')
    outside=tmp_path/'outside';outside.mkdir()
    (outside/'work.duckdb').write_bytes(b'outside')
    (root/'linked').symlink_to(outside,target_is_directory=True)
    before={name:(root/name).read_bytes() for name in ['manifest.json','scope.duckdb','scope.duckdb.wal','original.csv','unknown.tmp']}
    release_stage_scratch(root,{'files':[{'path':'manifest.json'},{'path':'original.csv'}]})
    assert not (root/'work.duckdb').exists() and not (root/'work.duckdb.wal').exists()
    assert not (spill/'duckdb_temp_storage_DEFAULT-0.tmp').exists()
    assert (spill/'not-a-duckdb-spill.tmp').read_bytes()==b'keep'
    assert (outside/'work.duckdb').read_bytes()==b'outside'
    for name,content in before.items():assert (root/name).read_bytes()==content


def test_failed_publication_retains_scratch(api,jobdb,tmp_path,monkeypatch):
    _,engine,storage=api
    submit(jobdb);lease=JobQueue(engine).claim('scratch-publication-failure')
    store=CheckpointStore(engine,storage,lease)
    outputs=[]
    def build(directory):
        directory.mkdir();outputs.append(directory)
        (directory/'manifest.json').write_text('{"synthetic":true}')
        (directory/'work.duckdb').write_bytes(b'failure diagnostic')
    failure=RuntimeError('SYNTHETIC_PUBLICATION_FAILURE')
    def fail(*args,**kwargs):raise failure
    monkeypatch.setattr(store,'publish',fail)
    with pytest.raises(RuntimeError) as caught:
        StageRunner(store,tmp_path/'work','v2','synthetic',{}).run('quality','v1',build)
    assert caught.value is failure
    assert (outputs[0]/'work.duckdb').read_bytes()==b'failure diagnostic'
