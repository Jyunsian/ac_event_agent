import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import pytest
from sqlalchemy import text
from scripts.local_workspace import initialize, load, location, environment
from server.db import database_engine
from server.storage import S3Storage


def test_name_rejects_paths():
    for name in ('../x', '/tmp/x', '', 'A', 'x' * 41):
        with pytest.raises(ValueError):
            location(name)


def test_real_persistent_services_restart_and_exclusive_supervisor():
    name = 'qa-' + uuid4().hex[:8]
    root = initialize(name)
    with pytest.raises(FileExistsError):
        initialize(name)
    _, config = load(name)
    assert (root / 'config.json').stat().st_mode & 0o077 == 0
    env = environment(name)
    storage = S3Storage(config['bucket'], env['S3_ENDPOINT_URL'], env['AWS_ACCESS_KEY_ID'], env['AWS_SECRET_ACCESS_KEY'])
    manifest = None
    for round_number in (1, 2):
        log_path = root / f'acceptance-{round_number}.log'
        with log_path.open('wb') as log:
            process = subprocess.Popen([sys.executable, '-m', 'scripts.local_workspace', 'serve', '--name', name],
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while 'Local synthetic services ready' not in log_path.read_text():
                    assert process.poll() is None, log_path.read_text()
                    assert time.monotonic() < deadline, log_path.read_text()
                    time.sleep(.1)
                second = subprocess.run([sys.executable, '-m', 'scripts.local_workspace', 'serve', '--name', name],
                                        capture_output=True, text=True, timeout=10)
                assert second.returncode != 0 and 'already supervised' in second.stderr
                engine = database_engine(env['DATABASE_URL'])
                try:
                    with engine.begin() as connection:
                        if round_number == 1:
                            connection.execute(text('CREATE TABLE local_workspace_probe(value text NOT NULL)'))
                            connection.execute(text("INSERT INTO local_workspace_probe VALUES ('synthetic durable value')"))
                            manifest = storage.put_bytes(storage.new_key('synthetic-local-workspace'), b'durable synthetic object')
                        assert connection.execute(text('SELECT value FROM local_workspace_probe')).scalar_one() == 'synthetic durable value'
                    assert storage.get_bytes(manifest) == b'durable synthetic object'
                finally:
                    engine.dispose()
                check = subprocess.run([sys.executable, '-m', 'scripts.local_workspace', 'exec', '--name', name,
                    '--', sys.executable, '-c', "import os; assert os.environ['S3_BUCKET']=='ac-local-synthetic'; print('environment accepted')"],
                    capture_output=True, text=True, timeout=10)
                assert check.returncode == 0 and check.stdout.strip() == 'environment accepted'
            finally:
                process.terminate()
                process.wait(timeout=30)
            assert process.returncode == 0, log_path.read_text()
        assert not (root / 'postgres/data/postmaster.pid').exists()
        output = log_path.read_text()
        assert config['secret_key'] not in output and config['internal_token'] not in output
    (root / 'acceptance.json').write_text(json.dumps({'status': 'passed', 'synthetic': True,
        'restart_rounds': 2, 'database_value_retained': True, 'object_bytes_retained': True,
        'duplicate_supervisor_rejected': True, 'manifest': manifest.to_dict()}))
    print(f'Persistent workspace evidence: {root}')
