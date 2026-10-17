import hashlib
import urllib.request

import pytest

from server.storage import StorageError
from tests.test_storage import storage


def test_presigned_parts_resume_complete_and_verify(storage):
    _, adapter = storage
    chunks = [b"synthetic,"*(600*1024), b"tail"]
    data = b"".join(chunks)
    key = adapter.new_key("source/synthetic", "csv")
    upload_id = adapter.start_multipart(key, "text/csv")
    assert adapter.list_parts(key, upload_id) == []
    first_url = adapter.presign_part(key, upload_id, 1, len(chunks[0]))
    with urllib.request.urlopen(urllib.request.Request(first_url, method="PUT", data=chunks[0]), timeout=10) as response:
        assert response.status == 200
    after_interrupt = adapter.list_parts(key, upload_id)
    assert [part["part_number"] for part in after_interrupt] == [1]
    # New signed URL after interruption only for absent part 2; part 1 is retained on server.
    second_url = adapter.presign_part(key, upload_id, 2, len(chunks[1]))
    with urllib.request.urlopen(urllib.request.Request(second_url, method="PUT", data=chunks[1]), timeout=10) as response:
        assert response.status == 200
    parts = adapter.list_parts(key, upload_id)
    assert parts[0] == after_interrupt[0]
    adapter.complete_multipart(key, upload_id, parts)
    manifest = adapter.verify_object(key, len(data), hashlib.sha256(data).hexdigest())
    assert adapter.get_bytes(manifest) == data
    with pytest.raises(StorageError, match="UPLOAD_SIZE_MISMATCH"):
        adapter.verify_object(key, len(data)+1, manifest.sha256)
    with pytest.raises(StorageError, match="CHECKSUM_MISMATCH"):
        adapter.verify_object(key, len(data), "0"*64)


def test_multipart_invalid_parts_and_abort(storage):
    _, adapter = storage
    key = adapter.new_key("source/synthetic")
    upload_id = adapter.start_multipart(key)
    with pytest.raises(StorageError, match="MISSING_PARTS"):
        adapter.complete_multipart(key, upload_id, [])
    with pytest.raises(StorageError, match="INVALID_MULTIPART_REQUEST"):
        adapter.presign_part(key, upload_id, 0, 100)
    adapter.abort_multipart(key, upload_id)
    with pytest.raises(StorageError):
        adapter.list_parts(key, upload_id)
    with pytest.raises(StorageError, match="OBJECT_NOT_FOUND"):
        adapter.head(key)
