"""S3 storage with conditional immutable writes and content-based manifests."""
import base64
import hashlib
import io
import os
import re
import tempfile
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


class StorageError(Exception):
    def __init__(self, code, retryable=False):
        self.code, self.retryable = code, retryable
        super().__init__(code)


@dataclass(frozen=True)
class ObjectManifest:
    object_key: str
    sha256: str
    size_bytes: int
    content_type: str

    def __post_init__(self):
        valid_key(self.object_key)
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise StorageError("INVALID_MANIFEST")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise StorageError("INVALID_MANIFEST")
        if not isinstance(self.content_type, str) or not self.content_type or any(
                ord(character) < 32 for character in self.content_type):
            raise StorageError("INVALID_MANIFEST")

    def to_dict(self):
        return asdict(self)


def valid_key(key):
    if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_./-]{0,1023}", key) or ".." in key:
        raise StorageError("INVALID_OBJECT_KEY")
    return key


@contextmanager
def storage_errors():
    try:
        yield
    except ClientError as error:
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        code = error.response.get("Error", {}).get("Code", "")
        if status == 404 or code in ("NoSuchKey", "NoSuchBucket"):
            raise StorageError("OBJECT_NOT_FOUND") from None
        if status in (409, 412):
            raise StorageError("OBJECT_ALREADY_EXISTS") from None
        if status in (401, 403):
            raise StorageError("STORAGE_ACCESS_DENIED") from None
        raise StorageError("STORAGE_SERVICE_ERROR", status >= 500 or status == 429) from None
    except BotoCoreError:
        raise StorageError("STORAGE_UNAVAILABLE", True) from None


class S3Storage:
    def __init__(self, bucket, endpoint_url=None, access_key=None, secret_key=None,
                 region="us-east-1", timeout=10):
        self.bucket = bucket
        self.client = boto3.client(
            "s3", endpoint_url=endpoint_url, aws_access_key_id=access_key,
            aws_secret_access_key=secret_key, region_name=region,
            config=Config(signature_version="s3v4", connect_timeout=timeout, read_timeout=timeout,
                          retries={"mode": "standard", "total_max_attempts": 2},
                          s3={"addressing_style": "path"}))

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("S3_BUCKET", "ac-event"),
                   os.environ.get("S3_ENDPOINT_URL") or None,
                   os.environ.get("AWS_ACCESS_KEY_ID") or None,
                   os.environ.get("AWS_SECRET_ACCESS_KEY") or None,
                   os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

    @staticmethod
    def new_key(namespace, suffix="bin"):
        return valid_key(f"{namespace}/{uuid4()}.{suffix}")

    def create_bucket(self):
        # Explicit provisioning only; never silently create a production bucket on reads.
        params = {"Bucket": self.bucket}
        region = self.client.meta.region_name
        if region != "us-east-1":
            params["CreateBucketConfiguration"] = {"LocationConstraint": region}
        with storage_errors():
            self.client.create_bucket(**params)

    def _put(self, key, stream, size, digest, content_type):
        valid_key(key)
        if size > 5 * 1024**3:
            raise StorageError("SINGLE_PUT_TOO_LARGE")
        with storage_errors():
            self.client.put_object(
                Bucket=self.bucket, Key=key, Body=stream, ContentLength=size,
                ContentType=content_type, IfNoneMatch="*",
                ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode(),
                Metadata={"sha256": digest})
        return ObjectManifest(key, digest, size, content_type)

    def put_bytes(self, key, data, content_type="application/octet-stream"):
        return self._put(key, io.BytesIO(data), len(data), hashlib.sha256(data).hexdigest(), content_type)

    def put_file(self, key, source, content_type="application/octet-stream"):
        digest = hashlib.sha256()
        size = 0
        with Path(source).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b""):
                digest.update(chunk)
                size += len(chunk)
            stream.seek(0)
            return self._put(key, stream, size, digest.hexdigest(), content_type)

    def head(self, key):
        with storage_errors():
            result = self.client.head_object(Bucket=self.bucket, Key=valid_key(key))
        return {"object_key": key, "size_bytes": result["ContentLength"],
                "sha256": result.get("Metadata", {}).get("sha256"),
                "content_type": result.get("ContentType", "application/octet-stream")}

    def start_multipart(self, key, content_type="application/octet-stream"):
        with storage_errors():
            result = self.client.create_multipart_upload(
                Bucket=self.bucket, Key=valid_key(key), ContentType=content_type)
        return result["UploadId"]

    def find_multipart(self, key):
        with storage_errors():
            pages = self.client.get_paginator("list_multipart_uploads").paginate(
                Bucket=self.bucket, Prefix=valid_key(key))
            return [upload["UploadId"] for page in pages for upload in page.get("Uploads", [])
                    if upload["Key"] == key]

    def list_parts(self, key, upload_id):
        parts = []
        with storage_errors():
            paginator = self.client.get_paginator("list_parts")
            for page in paginator.paginate(Bucket=self.bucket, Key=valid_key(key), UploadId=upload_id):
                parts.extend({"part_number": part["PartNumber"], "etag": part["ETag"],
                              "size_bytes": part["Size"]} for part in page.get("Parts", []))
        return parts

    def presign_part(self, key, upload_id, part_number, size_bytes, expires=900):
        if not 1 <= part_number <= 10000 or not 0 < size_bytes <= 5*1024**3 or not 1 <= expires <= 3600:
            raise StorageError("INVALID_MULTIPART_REQUEST")
        with storage_errors():
            return self.client.generate_presigned_url("upload_part", Params={
                "Bucket": self.bucket, "Key": valid_key(key), "UploadId": upload_id,
                "PartNumber": part_number, "ContentLength": size_bytes}, ExpiresIn=expires)

    def complete_multipart(self, key, upload_id, parts):
        if not parts:
            raise StorageError("MISSING_PARTS")
        with storage_errors():
            self.client.complete_multipart_upload(Bucket=self.bucket, Key=valid_key(key),
                UploadId=upload_id, IfNoneMatch="*", MultipartUpload={"Parts": [
                    {"PartNumber": part["part_number"], "ETag": part["etag"]} for part in parts]})

    def abort_multipart(self, key, upload_id):
        with storage_errors():
            self.client.abort_multipart_upload(Bucket=self.bucket, Key=valid_key(key), UploadId=upload_id)

    def verify_object(self, key, expected_size, expected_sha256):
        """Read bounded chunks, not the entire log in memory; never equate ETag with a file hash."""
        metadata = self.head(key)
        if metadata["size_bytes"] != expected_size:
            raise StorageError("UPLOAD_SIZE_MISMATCH")
        digest, size = hashlib.sha256(), 0
        with storage_errors():
            response = self.client.get_object(Bucket=self.bucket, Key=valid_key(key))
            with closing(response["Body"]) as body:
                for chunk in body.iter_chunks(1024*1024):
                    size += len(chunk)
                    if size > expected_size:
                        raise StorageError("UPLOAD_SIZE_MISMATCH")
                    digest.update(chunk)
        if size != expected_size:
            raise StorageError("UPLOAD_SIZE_MISMATCH")
        if digest.hexdigest() != expected_sha256:
            raise StorageError("CHECKSUM_MISMATCH")
        return ObjectManifest(key, digest.hexdigest(), size, metadata["content_type"])

    def get_bytes(self, manifest, max_bytes=16*1024*1024):
        if manifest.size_bytes > max_bytes:
            raise StorageError("OBJECT_TOO_LARGE_FOR_MEMORY")
        with storage_errors():
            response = self.client.get_object(Bucket=self.bucket, Key=valid_key(manifest.object_key))
            with closing(response["Body"]) as body:
                data = body.read(max_bytes+1)
        if len(data) != manifest.size_bytes or hashlib.sha256(data).hexdigest() != manifest.sha256:
            raise StorageError("CHECKSUM_MISMATCH")
        return data

    def download_file(self, manifest, destination):
        destination = Path(destination)
        # Write own temporary file then exclusive hard-link publication; source is never overwritten.
        fd, temp_name = tempfile.mkstemp(prefix=".ac-download-", dir=destination.parent)
        try:
            digest, size = hashlib.sha256(), 0
            with os.fdopen(fd, "wb") as output, storage_errors():
                response = self.client.get_object(Bucket=self.bucket, Key=valid_key(manifest.object_key))
                with closing(response["Body"]) as body:
                    for chunk in body.iter_chunks(1024*1024):
                        size += len(chunk)
                        if size > manifest.size_bytes:
                            raise StorageError("CHECKSUM_MISMATCH")
                        digest.update(chunk)
                        output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if size != manifest.size_bytes or digest.hexdigest() != manifest.sha256:
                raise StorageError("CHECKSUM_MISMATCH")
            os.link(temp_name, destination)
        finally:
            os.unlink(temp_name)
