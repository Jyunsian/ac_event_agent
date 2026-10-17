import json
import os
import time
from server.worker_health import pulse,healthy


def test_fresh_atomic_pulse_and_stale_rejection(tmp_path,monkeypatch):
    path=tmp_path/'health.json'
    monkeypatch.setenv('WORKER_HEALTH_FILE',str(path))
    assert not healthy(path)
    pulse()
    assert healthy(path)
    assert json.loads(path.read_text())['pid']==os.getpid()
    assert path.stat().st_mode&0o777==0o600
    path.write_text(json.dumps({'pid':os.getpid(),'monotonic':time.monotonic()-46}))
    assert not healthy(path)
    pulse()
    assert healthy(path) and list(tmp_path.iterdir())==[path]


def test_bad_or_dead_pulses_are_not_healthy(tmp_path,monkeypatch):
    path=tmp_path/'health.json'
    for data in ['{}','broken','x'*1025,json.dumps({'pid':0,'monotonic':time.monotonic()})]:
        path.write_text(data)
        assert not healthy(path)
    monkeypatch.setenv('WORKER_HEALTH_FILE',str(path))
    pulse()
    def dead(*args):raise ProcessLookupError()
    monkeypatch.setattr('server.worker_health.os.kill',dead)
    assert not healthy(path)


def test_unconfigured_pulse_is_noop(monkeypatch):
    monkeypatch.delenv('WORKER_HEALTH_FILE',raising=False)
    def forbidden(*args,**kwargs):raise AssertionError('unexpected write')
    monkeypatch.setattr('server.worker_health.tempfile.mkstemp',forbidden)
    pulse()
