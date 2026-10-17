"""Persistent, loopback-only synthetic workspace; never adopts existing services.

Production continues to use external PostgreSQL/S3. No credentials are printed.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import threading
from botocore.exceptions import ClientError

from scripts.local_postgres import LocalPostgres
from scripts.local_s3 import LocalS3
from server.storage import S3Storage

PROJECT = Path(__file__).resolve().parents[1]


def location(name):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', name):
        raise ValueError('Use a lowercase workspace name, at most 40 characters')
    root = PROJECT / '.runtime' / ('local-workspace-' + name)
    if root.is_symlink():
        raise ValueError('Workspace symlinks are not accepted')
    return root


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def initialize(name):
    root = location(name)
    pg_bin = Path(os.environ.get('AC_POSTGRES_BIN') or
                  (str(Path(shutil.which('initdb')).parent) if shutil.which('initdb')
                   else '/opt/homebrew/opt/postgresql@15/bin')).resolve()
    minio = Path(os.environ.get('AC_MINIO_BIN', PROJECT / '.runtime/bin/minio')).resolve()
    if not all((pg_bin / exe).is_file() for exe in ('initdb', 'pg_ctl', 'postgres')) or not minio.is_file():
        raise RuntimeError('Install PostgreSQL and MinIO first; see README')
    root.parent.mkdir(exist_ok=True)
    root.mkdir(mode=0o700)  # Exclusive: no overwrite or implicit adoption.
    ports = [free_port(), free_port()]
    while ports[0] == ports[1]:
        ports[1] = free_port()
    config = {'version': 1, 'name': name, 'pg_bin': str(pg_bin), 'minio': str(minio),
              'pg_port': ports[0], 's3_port': ports[1], 'bucket': 'ac-local-synthetic',
              'access_key': 'ac-local-synthetic', 'secret_key': secrets.token_urlsafe(32),
              'internal_token': secrets.token_urlsafe(32)}
    with open(root / 'config.json', 'x', opener=lambda p, f: os.open(p, f, 0o600)) as out:
        json.dump(config, out)
    for child in ('postgres', 'objects', 'work'):
        (root / child).mkdir(mode=0o700)
    return root


def load(name):
    root = location(name)
    config_path = root / 'config.json'
    if config_path.is_symlink() or config_path.stat().st_mode & 0o077:
        raise ValueError('config.json must be a private regular file (chmod 600)')
    config = json.loads(config_path.read_text())
    if config['version'] != 1 or config['name'] != name:
        raise ValueError('Workspace identity/version mismatch')
    for key in ('pg_port', 's3_port'):
        if type(config[key]) is not int or not 1024 <= config[key] <= 65535:
            raise ValueError('Invalid workspace port')
    for child in ('postgres', 'objects', 'work'):
        if (root / child).is_symlink() or not (root / child).is_dir():
            raise ValueError('Workspace data directories must be real directories')
    return root, config


class PersistentPostgres(LocalPostgres):
    def __init__(self, root, config):
        self.root = root / 'postgres'
        self.data = self.root / 'data'
        self.bin = Path(config['pg_bin'])
        self.port = config['pg_port']
        self.url = f'postgresql+psycopg://ac_test@127.0.0.1:{self.port}/postgres'
        self.running = False

    def start(self):
        if not (self.data / 'PG_VERSION').exists():
            self.command('initdb', '-D', self.data, '-U', 'ac_test', '--auth=trust',
                         '--encoding=UTF8', '--locale=C')
        # All clients use TCP. Disable Unix sockets so long workspace paths do
        # not exceed macOS's socket pathname limit.
        self.command('pg_ctl', '-D', self.data, '-l', self.root / 'postgres.log',
                     '-o', f"-h 127.0.0.1 -p {self.port} -k '' -c max_connections=30",
                     '-w', 'start')
        self.running = True
        return self


class PersistentS3(LocalS3):
    def __init__(self, root, config):
        self.root = root / 'objects'
        self.binary = Path(config['minio'])
        self.port = config['s3_port']
        self.endpoint = f'http://127.0.0.1:{self.port}'
        self.access_key = config['access_key']
        self.secret_key = config['secret_key']
        self.process = None


def environment(name):
    root, config = load(name)
    pg = PersistentPostgres(root, config)
    objects = PersistentS3(root, config)
    api_port = int(os.environ.get('AC_LOCAL_API_PORT', '8080'))
    agent_port = int(os.environ.get('AGENT_PORT', '8081'))
    if not all(1024 <= port <= 65535 for port in (api_port, agent_port)):
        raise ValueError('Local API/Agent ports must be 1024..65535')
    return {**os.environ, 'DATABASE_URL': pg.url, 'S3_ENDPOINT_URL': objects.endpoint,
            'S3_BUCKET': config['bucket'], 'AWS_ACCESS_KEY_ID': objects.access_key,
            'AWS_SECRET_ACCESS_KEY': objects.secret_key, 'AWS_DEFAULT_REGION': 'us-east-1',
            'AGENT_INTERNAL_TOKEN': config['internal_token'], 'WORKER_WORK_ROOT': str(root / 'work'),
            'AGENT_API_BASE_URL': f'http://127.0.0.1:{api_port}',
            'AGENT_HEALTH_URL': f'http://127.0.0.1:{agent_port}/health'}


def serve(name):
    root, config = load(name)
    with open(root / 'serve.lock', 'a', opener=lambda p, f: os.open(p, f, 0o600)) as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Workspace is already supervised; do not start another copy') from None
        # Never signal a PG left by a hard-killed supervisor: fail and retain data.
        if (root / 'postgres/data/postmaster.pid').exists():
            raise RuntimeError('Retained PostgreSQL PID file: inspect postgres.log before recovery')
        stopped = threading.Event()
        previous = {s: signal.signal(s, lambda *_: stopped.set()) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            with PersistentPostgres(root, config) as pg, PersistentS3(root, config) as objects:
                storage = S3Storage(config['bucket'], objects.endpoint, objects.access_key, objects.secret_key)
                try:
                    storage.client.head_bucket(Bucket=config['bucket'])
                except ClientError as error:
                    if error.response.get('ResponseMetadata', {}).get('HTTPStatusCode') != 404:
                        raise
                    storage.create_bucket()
                print(f'Local synthetic services ready: {root}', flush=True)
                print('Keep this terminal open. Ctrl-C stops services; all data is retained.', flush=True)
                while not stopped.wait(1):
                    if objects.process.poll() is not None:
                        raise RuntimeError('Local S3 exited; inspect objects/minio.log')
                    pg.command('pg_ctl', '-D', pg.data, 'status')
        finally:
            for s, handler in previous.items():
                signal.signal(s, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('init', 'serve', 'exec'))
    parser.add_argument('--name', default='mvp')
    args, command = parser.parse_known_args()
    if command[:1] == ['--']:
        command = command[1:]
    if args.operation != 'exec' and command:
        parser.error('Unexpected command arguments')
    if args.operation == 'init':
        print(f'Created private synthetic workspace: {initialize(args.name)}')
    elif args.operation == 'serve':
        serve(args.name)
    else:
        if not command:
            parser.error('exec requires -- COMMAND ...')
        env = environment(args.name)
        os.chdir(PROJECT)
        os.execvpe(command[0], command, env)


if __name__ == '__main__':
    main()
