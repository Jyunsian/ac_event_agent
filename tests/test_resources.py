from collections import namedtuple
from dataclasses import replace
import subprocess
import sys
import pytest
from server.resources import Limits,ResourceLimitError,duck_config
from server.analysis.connection import connect


def test_limits_and_real_duckdb_settings(monkeypatch):
    monkeypatch.setenv('WORKER_THREADS','1');monkeypatch.setenv('DUCKDB_MEMORY_MB','64')
    monkeypatch.setenv('WORKER_RSS_MB','128')
    config=duck_config({'preserve_insertion_order':False,'memory_limit':'10GB','threads':8})
    assert config['memory_limit']=='64MB' and config['threads']==1
    with connect(config={'memory_limit':'10GB'}) as db:
        assert db.execute("SELECT current_setting('threads')").fetchone()[0]==1
        assert db.execute("SELECT current_setting('autoload_known_extensions')").fetchone()[0] is False
    monkeypatch.setenv('DUCKDB_MEMORY_MB','256')
    with pytest.raises(ResourceLimitError,match='RESOURCE_CONFIG_INVALID'):Limits.from_environment()
    monkeypatch.setenv('DUCKDB_MEMORY_MB','not-a-number')
    with pytest.raises(ResourceLimitError,match='RESOURCE_CONFIG_INVALID'):duck_config()


def test_preflight_does_not_allocate_or_delete_to_make_room(tmp_path,monkeypatch):
    sentinel=tmp_path/'preserve';sentinel.write_bytes(b'original')
    limits=replace(Limits.from_environment(),disk_reserve_bytes=100,workdir_bytes=1000)
    usage=namedtuple('usage','total used free')
    monkeypatch.setattr('server.resources.shutil.disk_usage',lambda path:usage(1000,900,100))
    with pytest.raises(ResourceLimitError,match='DISK_PREFLIGHT_LIMIT'):limits.preflight(1,tmp_path)
    monkeypatch.setattr('server.resources.shutil.disk_usage',lambda path:usage(10000,1000,9000))
    with pytest.raises(ResourceLimitError,match='WORKDIR_PREFLIGHT_LIMIT'):limits.preflight(100,tmp_path)
    assert limits.preflight(10,tmp_path)['estimated_work_bytes']==120
    assert limits.preflight(10,tmp_path/'not-created'/'work')['estimated_work_bytes']==120
    assert sentinel.read_bytes()==b'original' and list(tmp_path.iterdir())==[sentinel]


@pytest.mark.parametrize('kind,expected',[('workdir',73),('memory',71),('cpu',74)])
def test_real_child_watchdog_stops_resource_overrun(tmp_path,kind,expected):
    script='''
import sys,time
from pathlib import Path
from dataclasses import replace
from server.resources import Limits,monitor
directory=Path(sys.argv[1]);kind=sys.argv[2]
limits=replace(Limits.from_environment(),disk_reserve_bytes=1)
limits=replace(limits,**({'workdir_bytes':1} if kind=='workdir' else {'rss_mb':64} if kind=='memory' else {'cpu_seconds':1}))
with monitor(limits,directory):
    if kind=='workdir':(directory/'owned-test-file').write_bytes(b'12')
    if kind=='memory':allocation=bytearray(96*1024**2)
    if kind=='cpu':
        while True:pass
    time.sleep(5)
'''
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path),kind],capture_output=True,text=True,timeout=8)
    assert result.returncode==expected,result.stderr
    if kind=='workdir':assert (tmp_path/'owned-test-file').read_bytes()==b'12'
