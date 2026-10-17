import hashlib
import json
import urllib.request
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from scripts.local_s3 import LocalS3
from server.api.main import create_app
from server.storage import S3Storage
from tests.test_jobs import jobdb

DEFAULTS = json.loads(Path("contracts/defaults.json").read_text())
EXPORT = json.loads(Path("tests/fixtures/hand/export.json").read_text())
MAPPING = {"users": {name: name for name in ("app_id", "user_id", "installed_at", "platform")},
           "events": {name: name for name in ("app_id", "user_id", "event_id", "event_name", "event_time",
               "level_id", "level_index", "attempt_id", "level_mode", "difficulty", "revive_used",
               "booster_used", "app_version")}}


@pytest.fixture
def api(jobdb):
    engine, _, _ = jobdb
    with LocalS3() as s3:
        storage = S3Storage("upload-synthetic", s3.endpoint, s3.access_key, s3.secret_key)
        storage.create_bucket()
        with TestClient(create_app(engine, storage, max_upload_bytes=12*1024**2, part_size=5*1024**2)) as client:
            yield client, engine, storage


def request(client, method, path, body, key=None):
    return client.request(method, path, json=body, headers={"Idempotency-Key": key or str(uuid4())})


def dataset(client):
    project = request(client, "POST", "/api/projects", {"app_id": "synthetic", "name": "Upload test"})
    assert project.status_code == 201, project.text
    result = request(client, "POST", "/api/datasets", {"project_id": project.json()["id"]})
    assert result.status_code == 201, result.text
    return result.json()


def begin(client, dataset_id, data, role="users", digest=None):
    body = {"role": role, "filename": role+".csv", "format": "csv", "size_bytes": len(data),
            "sha256": digest or hashlib.sha256(data).hexdigest()}
    response = request(client, "POST", f"/api/datasets/{dataset_id}/uploads", body)
    assert response.status_code == 201, response.text
    return response.json()["upload_id"], {"size_bytes": len(data), "sha256": body["sha256"]}


def put(client, identity, fingerprint, number, data):
    signed = request(client, "POST", f"/api/uploads/{identity}/parts", {**fingerprint, "part_number": number})
    assert signed.status_code == 200, signed.text
    with urllib.request.urlopen(urllib.request.Request(signed.json()["url"], data=data, method="PUT"), timeout=10) as result:
        assert result.status == 200


def finish(client, identity, fingerprint):
    result = request(client, "POST", f"/api/uploads/{identity}/complete", fingerprint)
    assert result.status_code == 200, result.text
    return result.json()


def test_resume_seal_immutable_mapping_and_new_version(api):
    client, engine, storage = api
    ds = dataset(client)
    data = b"u"*(5*1024**2)+b"last"
    upload, fp = begin(client, ds["id"], data)
    put(client, upload, fp, 1, data[:5*1024**2])
    missing = request(client, "POST", f"/api/uploads/{upload}/resume", fp)
    assert missing.json()["missing_parts"] == [2]
    assert request(client, "POST", f"/api/uploads/{upload}/complete", fp).status_code == 409
    wrong = request(client, "POST", f"/api/uploads/{upload}/resume", {**fp, "sha256": "0"*64})
    assert wrong.status_code == 409 and wrong.json()["error_code"] == "FILE_FINGERPRINT_MISMATCH"
    put(client, upload, fp, 2, data[5*1024**2:])
    first_manifest = finish(client, upload, fp)["manifest"]
    events, events_fp = begin(client, ds["id"], b"event", "events")
    put(client, events, events_fp, 1, b"event")
    finish(client, events, events_fp)
    assert request(client, "PUT", f"/api/datasets/{ds['id']}/mapping", {"mapping": MAPPING, "export_metadata": EXPORT}).status_code == 200
    key = str(uuid4())
    baseline = request(client, "POST", f"/api/datasets/{ds['id']}/baseline", DEFAULTS, key)
    assert baseline.status_code == 202, baseline.text
    assert request(client, "POST", f"/api/datasets/{ds['id']}/baseline", DEFAULTS, key).json() == baseline.json()
    assert client.get(f"/api/runs/{baseline.json()['run_id']}").json()["status"] == "queued"
    with engine.connect() as c:
        saved = c.execute(text("SELECT calculation_version,config FROM runs WHERE id=:id"),
                          {"id": UUID(baseline.json()["run_id"])}).mappings().one()
    assert saved["calculation_version"] == "3.0-casual-game"
    assert saved["config"]["analysis_version"] == "3.0-casual-game"
    assert request(client, "PUT", f"/api/datasets/{ds['id']}/mapping", {"mapping": MAPPING, "export_metadata": EXPORT}).status_code == 409
    new_ds = request(client, "POST", "/api/datasets", {"project_id": ds["project_id"]})
    assert new_ds.status_code == 201 and new_ds.json()["id"] != ds["id"]
    assert client.get(f"/api/datasets/{ds['id']}").json()["status"] == "ready"
    assert storage.head(first_manifest["object_key"])["size_bytes"] == len(data)


def test_limits_unknown_missing_and_checksum(api):
    client, engine, storage = api
    ds = dataset(client)
    large = {"role": "events", "filename": "big.csv", "format": "csv", "size_bytes": 13*1024**2, "sha256": "a"*64}
    assert request(client, "POST", f"/api/datasets/{ds['id']}/uploads", large).status_code == 413
    assert request(client, "POST", f"/api/uploads/{uuid4()}/complete", {"size_bytes": 1, "sha256": "a"*64}).status_code == 404
    identity, fp = begin(client, ds["id"], b"data", digest="a"*64)
    assert request(client, "POST", f"/api/uploads/{identity}/complete", fp).json()["error_code"] == "MISSING_PARTS"
    put(client, identity, fp, 1, b"data")
    response = request(client, "POST", f"/api/uploads/{identity}/complete", fp)
    assert response.status_code == 409 and response.json()["error_code"] == "CHECKSUM_MISMATCH"
    with engine.connect() as c:
        assert c.execute(text("SELECT status FROM uploads WHERE id=:id"), {"id": UUID(identity)}).scalar() != "completed"
    assert request(client, "POST", f"/api/datasets/{ds['id']}/baseline", DEFAULTS).status_code == 409


def test_complete_response_loss_recovery_and_wrong_part_size(api):
    client, engine, storage = api
    ds = dataset(client)
    identity, fp = begin(client, ds["id"], b"valid")
    put(client, identity, fp, 1, b"valid")
    with engine.connect() as c:
        row = c.execute(text("SELECT * FROM uploads WHERE id=:id"), {"id": UUID(identity)}).mappings().one()
    # Actual remote completion before DB publication simulates a lost response, no storage mock.
    storage.complete_multipart(row["object_key"], row["multipart_id"], storage.list_parts(row["object_key"], row["multipart_id"]))
    recovered = request(client, "POST", f"/api/uploads/{identity}/resume", fp)
    assert recovered.status_code == 200 and recovered.json()["status"] == "completed", recovered.text
    assert finish(client, identity, fp)["status"] == "completed"
    bad, bad_fp = begin(client, ds["id"], b"123456")
    with engine.connect() as c:
        row = c.execute(text("SELECT * FROM uploads WHERE id=:id"), {"id": UUID(bad)}).mappings().one()
    storage.client.upload_part(Bucket=storage.bucket, Key=row["object_key"], UploadId=row["multipart_id"], PartNumber=1, Body=b"123")
    response = request(client, "POST", f"/api/uploads/{bad}/complete", bad_fp)
    assert response.status_code == 409 and response.json()["error_code"] == "UPLOAD_SIZE_MISMATCH"


def test_initiation_recovery_request_idempotency_and_no_key(api):
    client, engine, storage = api
    ds = dataset(client)
    key = str(uuid4())
    payload = {"role": "users", "filename": "users.csv", "format": "csv", "size_bytes": 4,
               "sha256": hashlib.sha256(b"data").hexdigest()}
    first = request(client, "POST", f"/api/datasets/{ds['id']}/uploads", payload, key)
    second = request(client, "POST", f"/api/datasets/{ds['id']}/uploads", payload, key)
    assert first.status_code == 201 and first.json() == second.json()
    mismatch = request(client, "POST", f"/api/datasets/{ds['id']}/uploads", {**payload, "size_bytes": 5}, key)
    assert mismatch.status_code == 409
    assert client.post("/api/projects", json={"app_id": "synthetic", "name": "missing-key"}).status_code == 422
    # Persist a draft, initiate at S3, lose response before DB stores multipart ID.
    from sqlalchemy import insert
    identity = uuid4()
    object_key = storage.new_key(f"source/{ds['id']}/{identity}", "csv")
    svc = client.app.state.upload_service
    with engine.begin() as c:
        c.execute(insert(svc.tables["uploads"]).values(id=identity, dataset_id=UUID(ds["id"]), role="events",
            filename="events.csv", format="csv", expected_size=4, expected_sha256=payload["sha256"],
            part_size=5*1024**2, part_count=1, object_key=object_key))
    mismatch_resume = request(client, "POST", f"/api/uploads/{identity}/resume", {"size_bytes": 4, "sha256": "0"*64})
    assert mismatch_resume.status_code == 409
    assert storage.find_multipart(object_key) == []  # Fingerprint is checked before even initiating S3.
    original_id = storage.start_multipart(object_key)
    resumed = request(client, "POST", f"/api/uploads/{identity}/resume", {"size_bytes": 4, "sha256": payload["sha256"]})
    assert resumed.status_code == 200 and resumed.json()["missing_parts"] == [1]
    assert storage.find_multipart(object_key) == [original_id]
    with engine.connect() as c:
        assert c.execute(text("SELECT multipart_id FROM uploads WHERE id=:id"), {"id": identity}).scalar() == original_id
