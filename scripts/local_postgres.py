"""Isolated real PostgreSQL cluster for integration tests; retains files, never touches other services."""
import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path


class LocalPostgres:
    def __init__(self):
        candidate = os.environ.get("AC_POSTGRES_BIN")
        if not candidate:
            executable = shutil.which("initdb")
            candidate = str(Path(executable).parent) if executable else "/opt/homebrew/opt/postgresql@15/bin"
        self.bin = Path(candidate)
        if not (self.bin / "initdb").is_file():
            raise RuntimeError("Install PostgreSQL and set AC_POSTGRES_BIN to its bin directory")
        runtime = Path(__file__).resolve().parents[1] / ".runtime"
        runtime.mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="pg-test-", dir=runtime))
        self.data = self.root / "data"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.url = f"postgresql+psycopg://ac_test@127.0.0.1:{self.port}/postgres"
        self.running = False

    def command(self, executable, *args):
        return subprocess.run([str(self.bin/executable), *map(str, args)],
                              capture_output=True, text=True, check=True, timeout=45)

    def start(self):
        if not (self.data / "PG_VERSION").exists():
            self.command("initdb", "-D", self.data, "-U", "ac_test", "--auth=trust",
                         "--encoding=UTF8", "--locale=C")
        self.command("pg_ctl", "-D", self.data, "-l", self.root/"postgres.log",
                     "-o", f"-h 127.0.0.1 -p {self.port} -k {self.root} -c max_connections=30",
                     "-w", "start")
        self.running = True
        return self

    def stop(self):
        if self.running:
            self.command("pg_ctl", "-D", self.data, "-m", "fast", "-w", "stop")
            self.running = False

    def restart(self):
        self.stop()
        self.start()

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()


if __name__ == "__main__":
    import time
    with LocalPostgres() as server:
        print(f"Isolated PostgreSQL ready: {server.url}", flush=True)
        print(f"Retained data/log directory: {server.root}", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
