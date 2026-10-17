import pytest

from server.storage import ObjectManifest, S3Storage, StorageError


@pytest.mark.parametrize("override", [
    {"object_key": "../secret"}, {"sha256": "etag-is-not-sha256"},
    {"size_bytes": -1}, {"size_bytes": True}, {"content_type": "text/plain\r\ninjected: true"},
])
def test_invalid_manifest_rejected_without_network(override):
    values = dict(object_key="valid/object", sha256="a"*64, size_bytes=0, content_type="text/plain")
    with pytest.raises(StorageError):
        ObjectManifest(**{**values, **override})


def test_keys_unique_and_manifest_serializable():
    keys = {S3Storage.new_key("source/synthetic", "json") for _ in range(100)}
    assert len(keys) == 100
    manifest = ObjectManifest(next(iter(keys)), "a"*64, 0, "application/json")
    assert ObjectManifest(**manifest.to_dict()) == manifest
