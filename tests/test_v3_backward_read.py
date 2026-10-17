import hashlib

from server.worker import Worker
from tests.test_jobs import jobdb
from tests.test_pipeline import configure_worker,create_run
from tests.test_upload_api import api
from tests.test_v3_pipeline import create_v3_run


def test_v3_run_does_not_change_prior_v2_report_bytes_or_etag(api,jobdb,tmp_path,monkeypatch):
    client,engine,storage=api
    old=create_run(jobdb,storage,tmp_path/"v2-source")
    configure_worker(engine,storage,monkeypatch)
    assert Worker(engine,task_timeout=180).run_once()
    path=f'/api/runs/{old["id"]}/reports/1/json'
    before=client.get(path);assert before.status_code==200 and before.json()["schema_version"]=="2.0"
    digest=hashlib.sha256(before.content).hexdigest();etag=before.headers["etag"]
    new=create_v3_run(jobdb,storage,tmp_path/"v3-source")
    assert Worker(engine,task_timeout=180).run_once()
    current=client.get(f'/api/runs/{new["id"]}/reports/1/json')
    assert current.status_code==200 and current.json()["schema_version"]=="3.0"
    after=client.get(path)
    assert after.content==before.content and hashlib.sha256(after.content).hexdigest()==digest
    assert after.headers["etag"]==etag
