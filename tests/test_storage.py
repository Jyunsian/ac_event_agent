import hashlib
from dataclasses import replace

import pytest

from scripts.local_s3 import LocalS3
from server.storage import ObjectManifest, S3Storage, StorageError


@pytest.fixture(scope="module")
def storage():
    with LocalS3() as server:
        adapter = S3Storage("ac-synthetic", server.endpoint, server.access_key,
                            server.secret_key, timeout=1)
        adapter.create_bucket()
        print(f"\nReal S3 test evidence retained: {server.root}")
        yield server, adapter


def test_put_head_get_restart(storage, tmp_path):
    server, adapter = storage
    data = b"synthetic event data\n"*1000
    key = adapter.new_key("runs/synthetic", "csv")
    manifest = adapter.put_bytes(key, data, "text/csv")
    assert manifest.sha256 == hashlib.sha256(data).hexdigest()
    assert adapter.head(key) == manifest.to_dict()
    assert adapter.get_bytes(manifest) == data
    server.restart()
    assert adapter.get_bytes(manifest) == data
    target = tmp_path/"download.csv"
    adapter.download_file(manifest, target)
    assert target.read_bytes() == data
    with pytest.raises(FileExistsError):
        adapter.download_file(manifest, target)
    assert target.read_bytes() == data


def test_immutable_versions_and_checksum(storage, tmp_path):
    _, adapter = storage
    key = adapter.new_key("source/synthetic")
    original = adapter.put_bytes(key, b"original")
    with pytest.raises(StorageError, match="OBJECT_ALREADY_EXISTS"):
        adapter.put_bytes(key, b"replacement")
    assert adapter.get_bytes(original) == b"original"
    source = tmp_path/"new-version"
    source.write_bytes(b"new version")
    version = adapter.put_file(adapter.new_key("source/synthetic"), source)
    assert version.object_key != original.object_key
    assert adapter.get_bytes(version) == b"new version"
    with pytest.raises(StorageError, match="CHECKSUM_MISMATCH"):
        adapter.get_bytes(replace(version, sha256="0"*64))
    with pytest.raises(StorageError, match="CHECKSUM_MISMATCH"):
        adapter.download_file(replace(version, sha256="0"*64), tmp_path/"invalid")
    assert not (tmp_path/"invalid").exists()
    with pytest.raises(StorageError, match="OBJECT_TOO_LARGE_FOR_MEMORY"):
        adapter.get_bytes(version, max_bytes=1)


def test_missing_and_disconnected(storage):
    server, adapter = storage
    with pytest.raises(StorageError, match="OBJECT_NOT_FOUND") as missing:
        adapter.head("missing/object")
    assert missing.value.retryable is False
    with pytest.raises(StorageError, match="OBJECT_NOT_FOUND"):
        adapter.get_bytes(ObjectManifest("missing/object", "0"*64, 0, "application/octet-stream"))
    server.stop()
    try:
        with pytest.raises(StorageError, match="STORAGE_UNAVAILABLE") as disconnected:
            adapter.head("missing/object")
        assert disconnected.value.retryable is True
    finally:
        server.start()


def test_invalid_key_before_request(storage):
    _, adapter = storage
    for key in ("../source", "/source", "source/../secret", "https://example.com"):
        with pytest.raises(StorageError, match="INVALID_OBJECT_KEY"):
            adapter.put_bytes(key, b"test")


def test_multipart_etag_is_not_content_checksum(storage):
    _, adapter = storage
    key = adapter.new_key("multipart/synthetic")
    chunks = [b"a" * (5*1024*1024), b"b" * 1024]
    client = adapter.client
    upload = client.create_multipart_upload(Bucket=adapter.bucket, Key=key)
    parts = []
    try:
        for number, chunk in enumerate(chunks, 1):
            result = client.upload_part(Bucket=adapter.bucket, Key=key,
                                        UploadId=upload["UploadId"], PartNumber=number, Body=chunk)
            parts.append({"PartNumber": number, "ETag": result["ETag"]})
        result = client.complete_multipart_upload(Bucket=adapter.bucket, Key=key,
                    UploadId=upload["UploadId"], MultipartUpload={"Parts": parts})
    except Exception:
        client.abort_multipart_upload(Bucket=adapter.bucket, Key=key, UploadId=upload["UploadId"])
        raise
    content = b"".join(chunks)
    assert "-2" in result["ETag"]
    assert result["ETag"].strip('"') != hashlib.md5(content).hexdigest()
    manifest = ObjectManifest(key, hashlib.sha256(content).hexdigest(), len(content), "application/octet-stream")
    assert adapter.get_bytes(manifest) == content


def test_concurrent_writers_cannot_overwrite(storage):
    from concurrent.futures import ThreadPoolExecutor
    _, adapter = storage
    key = adapter.new_key("concurrent/synthetic")

    def write(value):
        try:
            return adapter.put_bytes(key, value), value
        except StorageError as error:
            assert error.code == "OBJECT_ALREADY_EXISTS"
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [b"writer-a", b"writer-b"]))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert adapter.get_bytes(winners[0][0]) == winners[0][1]


def test_denied_credentials_are_sanitized(storage):
    server, adapter = storage
    denied = S3Storage(adapter.bucket, server.endpoint, "invalid-synthetic-id",
                       "invalid-synthetic-password", timeout=1)
    with pytest.raises(StorageError, match="STORAGE_ACCESS_DENIED") as error:
        denied.head("missing/object")
    assert error.value.retryable is False
    assert "password" not in str(error.value)
