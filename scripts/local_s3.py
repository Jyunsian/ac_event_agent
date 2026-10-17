"""Real disk-backed MinIO for local synthetic integration only."""
import os
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


class LocalS3:
    def __init__(self):
        project = Path(__file__).resolve().parents[1]
        self.binary = Path(os.environ.get("AC_MINIO_BIN", project/".runtime/bin/minio"))
        if not self.binary.is_file():
            raise RuntimeError("Install local MinIO binary; see README. Missing real S3 runtime is not skipped.")
        runtime = project/".runtime"
        runtime.mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="s3-test-", dir=runtime))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.endpoint = f"http://127.0.0.1:{self.port}"
        self.access_key = "ac-synthetic-test"
        self.secret_key = secrets.token_urlsafe(32)
        self.process = None

    def start(self):
        self.log = (self.root/"minio.log").open("ab")
        self.process = subprocess.Popen([
            str(self.binary), "server", str(self.root/"data"),
            "--address", f"127.0.0.1:{self.port}", "--console-address", "127.0.0.1:0"
        ], env={**os.environ, "MINIO_ROOT_USER": self.access_key,
                "MINIO_ROOT_PASSWORD": self.secret_key, "MINIO_BROWSER": "off",
                "MINIO_UPDATE": "off"}, stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(100):
            if self.process.poll() is not None:
                self.log.close()
                raise RuntimeError(f"Local S3 exited; inspect {self.root/'minio.log'}")
            try:
                with urllib.request.urlopen(self.endpoint+"/minio/health/live", timeout=.3) as response:
                    if response.status == 200:
                        return self
            except OSError:
                pass
            time.sleep(.1)
        self.stop()
        raise RuntimeError("Local S3 did not become ready")

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if hasattr(self, "log"):
            self.log.close()

    def restart(self):
        self.stop()
        self.start()

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()
