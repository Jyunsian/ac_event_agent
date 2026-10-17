import json
from uuid import uuid4

from server.analysis.ingest import canonicalize
from server.analysis.quality import build_quality
from server.jobs import JobQueue
from tests.test_ingest import MAPPING, sources
from tests.test_jobs import jobdb, submit
from tests.test_quality import EXPORT
from tests.test_upload_api import api


def test_committed_quality_readback_and_run_isolation(api, jobdb, tmp_path):
    client, engine, storage = api
    _, repo, _ = jobdb
    run = submit(jobdb)
    other = submit(jobdb)
    path = f"/api/runs/{run['id']}"
    assert client.get(path+"/quality").json()["error_code"] == "ARTIFACT_NOT_READY"
    assert client.get(f"/api/runs/{uuid4()}/quality").status_code == 404
    canonicalize(sources(tmp_path), MAPPING, tmp_path/"normalized")
    quality, profile = build_quality(tmp_path/"normalized", EXPORT, tmp_path/"quality")
    queue = JobQueue(engine)
    lease = queue.claim("quality-publication-test")
    assert lease.run_id == run["id"]
    manifests = [(kind, storage.put_file(storage.new_key("quality-test", "json"),
                  tmp_path/"quality"/f"{kind}.json", "application/json"))
                 for kind in ("quality", "dataset_profile")]
    # Upload alone is not publication. Metadata commits with a valid fenced lease.
    assert client.get(path+"/quality").status_code == 409
    def publish(c):
        for kind, manifest in manifests:
            repo.add_artifact(c, run["id"], lease.attempt_id, kind, manifest.object_key,
                              manifest.sha256, manifest.size_bytes)
    queue.finish(lease, publish)
    for route, expected in (("quality", quality), ("profile", profile)):
        response = client.get(path+"/"+route)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["run_id"] == str(run["id"])
        assert body["content"] == expected
        assert body["content"]["capabilities"] == quality["capabilities"]
        assert body["artifact_id"] and len(body["sha256"]) == 64
    assert client.get(f"/api/runs/{other['id']}/quality").status_code == 409


def test_artifact_checksum_and_invalid_json_fail_closed(api, jobdb):
    client, engine, storage = api
    _, repo, _ = jobdb
    for data, checksum, error in ((b'{}', "0"*64, "CHECKSUM_MISMATCH"),
                                  (b'not-json', None, "ARTIFACT_INVALID")):
        run = submit(jobdb)
        queue = JobQueue(engine)
        lease = queue.claim("quality-corruption-test")
        manifest = storage.put_bytes(storage.new_key("quality-test", "json"), data)
        def publish(c):
            repo.add_artifact(c, run["id"], lease.attempt_id, "quality", manifest.object_key,
                              checksum or manifest.sha256, manifest.size_bytes)
        queue.finish(lease, publish)
        response = client.get(f"/api/runs/{run['id']}/quality")
        assert response.status_code == 409
        assert response.json()["error_code"] == error
        assert "content" not in response.json()
