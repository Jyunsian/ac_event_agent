"""Pinned macOS ARM64 test runtime installer. HTTPS ranges + whole-file SHA256 verification."""
import hashlib
import os
import platform
import shutil
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

URL = "https://github.com/minio/minio/releases/download/RELEASE.2025-09-07T16-13-09Z/minio.darwin-arm64.RELEASE.2025-09-07T16-13-09Z"
SIZE = 108218434
SHA256 = "7c3b3039b76e55a1b80935848ed83998d5e8d317374f87851f46a019ff5c0aa4"


def install():
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("This pinned installer is for macOS ARM64; set AC_MINIO_BIN for another platform")
    target_dir = Path(__file__).resolve().parents[1]/".runtime/bin"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir/"minio"
    if target.exists():
        with target.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() == SHA256:
                print("Pinned MinIO already installed and checksum verified", flush=True)
                return
        raise RuntimeError("Existing binary differs; refusing overwrite")
    parts_dir = Path(tempfile.mkdtemp(prefix="minio-parts-", dir=target_dir))
    chunk_size = (SIZE+7)//8

    def download(index):
        start, end = index*chunk_size, min(SIZE, (index+1)*chunk_size)-1
        request = urllib.request.Request(URL, headers={"Range": f"bytes={start}-{end}"})
        part = parts_dir/str(index)
        with urllib.request.urlopen(request, timeout=45) as response, part.open("xb") as output:
            if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{SIZE}":
                raise RuntimeError("Server did not honor the exact range")
            shutil.copyfileobj(response, output, 1024*1024)
        if part.stat().st_size != end-start+1:
            raise RuntimeError("Incomplete download")
        print(f"Verified part size {index+1}/8", flush=True)
        return part

    with ThreadPoolExecutor(max_workers=8) as executor:
        parts = list(executor.map(download, range(8)))
    assembled = parts_dir/"minio"
    digest = hashlib.sha256()
    with assembled.open("xb") as output:
        for part in parts:
            with part.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024*1024), b""):
                    output.write(chunk)
                    digest.update(chunk)
    if digest.hexdigest() != SHA256:
        raise RuntimeError("Whole binary SHA256 mismatch; not installed")
    assembled.chmod(0o755)
    os.link(assembled, target)  # Exclusive publication, never overwrite an existing file.
    print(f"Installed verified MinIO: {target}; download evidence retained: {parts_dir}", flush=True)


if __name__ == "__main__":
    install()
