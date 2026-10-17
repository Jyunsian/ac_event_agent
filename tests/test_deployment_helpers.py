import os
import subprocess
import sys
import pytest
from scripts.deployment_acceptance import private_env,disk_preflight,container_boundary


def test_private_runtime_env_does_not_overwrite(tmp_path):
    path=tmp_path/'server.env'
    private_env(path,{'TEST_VALUE':'synthetic-only'})
    assert path.stat().st_mode&0o777==0o600
    assert path.read_text()=='TEST_VALUE=synthetic-only\n'
    with pytest.raises(FileExistsError):private_env(path,{'TEST_VALUE':'changed'})
    assert path.read_text()=='TEST_VALUE=synthetic-only\n'


def test_cli_requires_explicit_rehearsal_opt_in():
    result=subprocess.run([sys.executable,'-m','scripts.deployment_acceptance'],capture_output=True,text=True,timeout=10)
    assert result.returncode==2 and '--run is required' in result.stderr


def test_bad_env_value_rejected_before_file_creation(tmp_path):
    path=tmp_path/'absent.env'
    with pytest.raises(ValueError,match='INVALID_ENV_VALUE'):private_env(path,{'TEST_VALUE':'bad\nline'})
    assert not path.exists()


def test_low_host_disk_preflight_allocates_nothing(tmp_path,monkeypatch):
    from collections import namedtuple
    usage=namedtuple('usage','total used free')
    monkeypatch.setattr('scripts.deployment_acceptance.shutil.disk_usage',lambda path:usage(9,8,1))
    with pytest.raises(RuntimeError,match='DEPLOYMENT_HOST_DISK_PREFLIGHT_LIMIT'):disk_preflight(tmp_path)
    assert list(tmp_path.iterdir())==[]


def test_container_boundary_rejects_internal_port_and_public_web():
    config={'Config':{'User':'10001','Env':['SECRET=not-to-be-recorded']},'HostConfig':{
        'ReadonlyRootfs':True,'CapDrop':['ALL'],'SecurityOpt':['no-new-privileges:true'],'PortBindings':{}}}
    assert container_boundary('api',config)['no_published_ports']
    assert 'SECRET' not in str(container_boundary('api',config))
    config['HostConfig']['PortBindings']={'8080/tcp':[{'HostIp':'127.0.0.1','HostPort':'8090'}]}
    with pytest.raises(AssertionError,match='INTERNAL_SERVICE_PUBLISHED'):container_boundary('api',config)
    assert container_boundary('web',config)['loopback_only']
    config['HostConfig']['PortBindings']['8080/tcp'][0]['HostIp']='0.0.0.0'
    with pytest.raises(AssertionError,match='PUBLIC_BIND'):container_boundary('web',config)
