"""README startup commands through persistent service CLI, not in-process API fixtures."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from uuid import uuid4

from sqlalchemy import text
from scripts.local_workspace import initialize, environment, free_port
from server.db import database_engine
from tests.test_ingest import sources, MAPPING


def test_cli_workspace_product_and_reopen(tmp_path, monkeypatch):
    name = 'flow-' + uuid4().hex[:8]
    root = initialize(name)
    ports = set()
    while len(ports) < 3:
        ports.add(free_port())
    api_port, agent_port, web_port = sorted(ports)
    monkeypatch.setenv('AC_LOCAL_API_PORT', str(api_port))
    monkeypatch.setenv('AGENT_PORT', str(agent_port))
    monkeypatch.setenv('API_PROXY_TARGET', f'http://127.0.0.1:{api_port}')
    monkeypatch.setenv('AC_TEST_HEALTH_PORT', str(agent_port))
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.delenv('OPENROUTER_MODEL', raising=False)
    env = environment(name)
    base = f'http://127.0.0.1:{web_port}'
    endpoint = f'http://127.0.0.1:{api_port}'
    processes = []
    logs = []
    cli = [sys.executable, '-m', 'scripts.local_workspace']
    def launch(label, command, wrapped=True):
        log = (root / (label + '.log')).open('wb'); logs.append(log)
        args = cli + ['exec', '--name', name, '--'] + command if wrapped else command
        process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, env=env)
        processes.append(process)
        return process
    def wait_url(url):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            assert all(p.poll() is None for p in processes), f'Service exited; inspect {root}'
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    if response.status == 200:
                        return response.read()
            except OSError:
                pass
            time.sleep(.1)
        raise AssertionError(f'Startup timeout; inspect {root}')
    def stop(process):
        if process.poll() is None:
            process.terminate(); process.wait(timeout=30)
        processes.remove(process)
    def start_services(label):
        process = launch(label, cli + ['serve', '--name', name], wrapped=False)
        wait_url(env['S3_ENDPOINT_URL'] + '/minio/health/live')
        return process
    try:
        services = start_services('services-first')
        migrated = subprocess.run(cli + ['exec', '--name', name, '--', sys.executable, '-m',
            'alembic', 'upgrade', 'head'], env=env, capture_output=True, timeout=30)
        assert migrated.returncode == 0, 'Migration failed'
        subprocess.run(['npm', 'run', 'build', '--workspace', 'agent'], check=True, capture_output=True, timeout=60)
        api = launch('api-first', [sys.executable, '-m', 'uvicorn', 'server.api.main:app',
            '--host', '127.0.0.1', '--port', str(api_port)])
        wait_url(endpoint + '/api/health')
        worker = launch('worker-first', [sys.executable, '-m', 'server.worker'])
        formal = launch('formal-agent', ['node', 'agent/dist/index.js'])
        health = json.loads(wait_url(f'http://127.0.0.1:{agent_port}/health'))
        assert health['provider'] == {'available': False, 'code': 'OPENROUTER_NOT_CONFIGURED'}
        stop(formal)
        # Explicit test-only model injection after checking the real no-key entry.
        agent = launch('synthetic-agent', ['node', 'agent/product-browser-worker.mjs', endpoint])
        wait_url(f'http://127.0.0.1:{agent_port}/health')
        web = launch('web-first', ['node', 'node_modules/vite/bin/vite.js', '--config', 'web/vite.config.ts',
            '--host', '127.0.0.1', '--port', str(web_port), '--strictPort', 'web'])
        wait_url(base)
        (root / 'inputs').mkdir()
        files = sources(root / 'inputs')
        manifest = root / 'inputs.json'
        manifest.write_text(json.dumps({'users': next(f['path'] for f in files if f['role'] == 'users'),
            'events': [f['path'] for f in files if f['role'] == 'events'], 'mapping': MAPPING}))
        browser = subprocess.run(['node', 'scripts/product_browser_qa.cjs', base, str(manifest),
            str(root / 'visual')], env=env, capture_output=True, text=True, timeout=240)
        assert browser.returncode == 0, browser.stdout + browser.stderr + str(root)
        checks = json.loads((root / 'visual/checks.json').read_text())
        urls = [f"{endpoint}/api/runs/{checks[which]}/reports/1/{fmt}"
                for which in ('parent', 'child') for fmt in ('json', 'html', 'csv')]
        def hashes():
            return [hashlib.sha256(urllib.request.urlopen(url, timeout=10).read()).hexdigest() for url in urls]
        before = hashes()
        for process in (web, agent, worker, api, services):
            stop(process)
        services = start_services('services-reopened')
        api = launch('api-reopened', [sys.executable, '-m', 'uvicorn', 'server.api.main:app',
            '--host', '127.0.0.1', '--port', str(api_port)])
        wait_url(endpoint + '/api/health')
        assert hashes() == before
        engine = database_engine(env['DATABASE_URL'])
        try:
            with engine.connect() as connection:
                assert connection.execute(text("SELECT count(*) FROM agent_turns WHERE status='succeeded'")).scalar_one() == 4
                assert connection.execute(text('SELECT count(*) FROM analysis_branches')).scalar_one() == 3
                assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '0017'
        finally:
            engine.dispose()
        (root / 'product-acceptance.json').write_text(json.dumps({'status': 'passed', 'synthetic': True,
            'test_model': True, 'formal_no_key_verified': True, 'parent': checks['parent'],
            'child': checks['child'], 'reopened_report_hashes': before, 'questions': 4}))
        print(f'Persistent product evidence: {root}')
    finally:
        for process in list(reversed(processes)):
            stop(process)
        for log in logs:
            log.close()
