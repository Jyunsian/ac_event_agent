from server.jobs import JobQueue
from tests.test_jobs import jobdb, submit
from tests.test_upload_api import api
import json
import pytest


@pytest.mark.parametrize('version', ['1.0', '2.0', '3.0'])
def test_versioned_report_reader_preserves_bytes(api, jobdb, version):
    client, engine, storage = api
    _, repo, _ = jobdb
    run = submit(jobdb)
    lease = JobQueue(engine).claim('synthetic-version-reader')
    payload = {'schema_version': version, 'run_id': str(run['id']),
               'dataset_id': str(run['dataset_id']), 'candidates': [],
               'summary': {'candidate_count': 0}, 'audit': {}}
    if version == '2.0':
        payload['catalog'] = {'sha256': 'a'*64, 'evaluated_count': 0, 'priority_ids': []}
    original = json.dumps(payload, indent=2).encode()
    obj = storage.put_bytes(storage.new_key('synthetic-version-test', 'json'), original)
    def publish(c):
        artifact = repo.add_artifact(c, run['id'], lease.attempt_id, 'report_json',
                                    obj.object_key, obj.sha256, obj.size_bytes)
        repo.add_report(c, run['id'], artifact['id'])
    JobQueue(engine).finish(lease, publish)
    response = client.get(f'/api/runs/{run["id"]}/reports/1/json')
    if version == '3.0':
        assert response.status_code == 409
        assert response.json()['error_code'] == 'REPORT_SCHEMA_INVALID'
    else:
        assert response.status_code == 200
        assert response.content == original


def test_report_corruption_and_missing_export_fail_closed(api, jobdb):
    client, engine, storage = api
    _, repo, _ = jobdb
    run = submit(jobdb)
    lease = JobQueue(engine).claim("synthetic-report-corruption")
    obj = storage.put_bytes(storage.new_key("synthetic-report-test", "json"), b'{}')
    def publish(c):
        artifact = repo.add_artifact(c, run["id"], lease.attempt_id, "report_json", obj.object_key, "0"*64, obj.size_bytes)
        repo.add_report(c, run["id"], artifact["id"])
    # Deliberate corrupted DB fixture; normal Worker would reject incomplete exports.
    JobQueue(engine).finish(lease, publish)
    base = f'/api/runs/{run["id"]}/reports/1/'
    response = client.get(base+"json")
    assert response.status_code == 409
    assert response.json()["error_code"] == "CHECKSUM_MISMATCH"
    assert "content" not in response.json()
    assert client.get(base+"html").json()["error_code"] == "REPORT_EXPORT_AMBIGUOUS"
    assert client.get(base+"exe").status_code == 422
    assert client.get(f'/api/runs/{run["id"]}/reports/0/json').status_code == 422


def test_large_exports_download_verified_without_memory_read(api, jobdb, monkeypatch, tmp_path):
    import hashlib
    import server.artifact_reader as reader
    import tempfile
    client, engine, storage = api
    _, repo, _ = jobdb
    run = submit(jobdb)
    lease = JobQueue(engine).claim('large-export-reader')
    payload = b'x'*(16*1024**2+1)
    model = storage.put_bytes(storage.new_key('export-test', 'json'), json.dumps({'schema_version':'1.0','run_id':str(run['id']),'dataset_id':str(run['dataset_id']),'candidates':[],'summary':{'candidate_count':0},'audit':{}}).encode())
    export = storage.put_bytes(storage.new_key('export-test', 'csv'), payload)
    bad = storage.put_bytes(storage.new_key('export-test', 'html'), payload)
    def publish(c):
        a=repo.add_artifact(c,run['id'],lease.attempt_id,'report_json',model.object_key,model.sha256,model.size_bytes)
        repo.add_report(c,run['id'],a['id'])
        repo.add_artifact(c,run['id'],lease.attempt_id,'report_csv',export.object_key,export.sha256,export.size_bytes)
        repo.add_artifact(c,run['id'],lease.attempt_id,'report_html',bad.object_key,'0'*64,bad.size_bytes)
    JobQueue(engine).finish(lease,publish)
    original=tempfile.TemporaryDirectory
    monkeypatch.setattr(tempfile,'TemporaryDirectory',lambda **kw:original(dir=tmp_path,**kw))
    original_read=storage.get_bytes
    def guarded_read(manifest, **kw):
        assert manifest.size_bytes<=16*1024**2, 'Export loaded entirely into memory'
        return original_read(manifest, **kw)
    monkeypatch.setattr(storage,'get_bytes',guarded_read)
    base=f'/api/runs/{run["id"]}/reports/1/'
    response=client.get(base+'csv')
    assert response.status_code==200
    assert response.content==payload
    assert response.headers['etag']=='"'+hashlib.sha256(payload).hexdigest()+'"'
    assert list(tmp_path.iterdir())==[]
    corrupt=client.get(base+'html')
    assert corrupt.status_code==409
    assert corrupt.json()['error_code']=='CHECKSUM_MISMATCH'
    assert list(tmp_path.iterdir())==[]
