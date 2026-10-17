"""Opt-in isolated production-image rehearsal. Retains evidence/data; never deletes volumes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
from urllib.request import urlopen
from urllib.error import HTTPError
from sqlalchemy import text
from scripts.local_postgres import LocalPostgres
from scripts.local_s3 import LocalS3
from server.db import database_engine
from server.storage import S3Storage
from scripts.backup_restore import backup,restore
from tests.test_ingest import sources,MAPPING


def disk_preflight(path):
    # This small hand-fixture rehearsal needs room beyond the 2GiB host reserve.
    # Docker VM free-space readings alone do not protect the macOS backing disk.
    free=shutil.disk_usage(path).free
    if free<3*1024**3:raise RuntimeError('DEPLOYMENT_HOST_DISK_PREFLIGHT_LIMIT')
    return {'host_free_bytes':free,'minimum_free_bytes':3*1024**3,
            'policy':'2GiB reserve plus 1GiB rehearsal allowance; not a measured upper bound'}


def private_env(path,values):
    if any('\n' in value or '\r' in value for value in values.values()):raise ValueError('INVALID_ENV_VALUE')
    with open(path,'x',opener=lambda name,flags:os.open(name,flags,0o600)) as stream:
        for key,value in values.items():
            stream.write(f'{key}={value}\n')


def container_boundary(service,inspection):
    """Validate inspect data without recording environment values or credentials."""
    config=inspection['Config'];host=inspection['HostConfig']
    assert config['User'] not in ('','0','root','0:0'), 'ROOT_CONTAINER'
    assert host['ReadonlyRootfs'] and 'ALL' in host['CapDrop'], 'CONTAINER_HARDENING'
    assert 'no-new-privileges:true' in host['SecurityOpt'], 'PRIVILEGE_ESCALATION'
    published=[binding for values in (host.get('PortBindings') or {}).values() for binding in (values or [])]
    if service=='web':
        assert len(published)==1 and published[0]['HostIp']=='127.0.0.1', 'PUBLIC_BIND'
    else:assert not published, 'INTERNAL_SERVICE_PUBLISHED'
    return {'nonroot':True,'readonly':True,'capabilities_dropped':True,
            'loopback_only' if service=='web' else 'no_published_ports':True}


def run(tag):
    preflight=disk_preflight(Path.cwd())
    # Images must have been built, not implicitly pulled/built by this acceptance run.
    image_ids={}
    for service in ['python','agent','web']:
        image_ids[service]=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',
            f'ac-event-{service}:{tag}'],stderr=subprocess.DEVNULL,text=True,timeout=10).strip()
    root=Path(tempfile.mkdtemp(prefix='deployment-e2e-',dir=Path('.runtime').resolve()))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    project='ac-acceptance-'+secrets.token_hex(5)
    token=secrets.token_urlsafe(32)
    record={'synthetic':True,'status':'running','project':project,'tag':tag,'image_ids':image_ids,'preflight':preflight,
            'model':'explicit SDK test model; not OpenRouter verification'}
    env={**os.environ,'RELEASE_TAG':tag,'AC_HTTP_PORT':str(port),'AC_BIND_ADDRESS':'127.0.0.1',
         'AC_SERVER_ENV_FILE':str(root/'server.env'),'AC_AGENT_ENV_FILE':str(root/'agent.env')}
    compose=['docker','compose','-p',project,'-f','deploy/compose.yaml']
    def command(args,timeout=180):
        with (root/'compose.log').open('ab') as log:
            subprocess.run(compose+args,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=timeout)
    base=f'http://127.0.0.1:{port}'
    def reports(ids):
        hashes={}
        for rid in ids:
            for kind in ['json','html','csv']:
                with urlopen(f'{base}/api/runs/{rid}/reports/1/{kind}',timeout=20) as response:
                    assert response.status==200
                    hashes[f'{rid}/{kind}']=hashlib.sha256(response.read()).hexdigest()
        return hashes
    with LocalPostgres() as pg,LocalS3() as s3:
        storage=S3Storage('deployment-synthetic',s3.endpoint,s3.access_key,s3.secret_key)
        storage.create_bucket()
        record['retained_services']={'postgres':str(pg.root),'s3':str(s3.root)}
        def configure_target(path,db,objects,bucket):
            private_env(path,{'DATABASE_URL':db.url.replace('127.0.0.1','host.docker.internal'),
                'S3_ENDPOINT_URL':objects.endpoint.replace('127.0.0.1','host.docker.internal'),
                'S3_BUCKET':bucket,'AWS_ACCESS_KEY_ID':objects.access_key,'AWS_SECRET_ACCESS_KEY':objects.secret_key,
                'AGENT_INTERNAL_TOKEN':token})
            env['AC_SERVER_ENV_FILE']=str(path)
        configure_target(root/'server.env',pg,s3,storage.bucket)
        private_env(root/'agent.env',{'AGENT_INTERNAL_TOKEN':token})
        try:
            command(['up','-d','--no-build','--wait'],240)
            boundaries={}
            for service in ['api','worker','agent','web']:
                cid=subprocess.check_output(compose+['ps','-q',service],env=env,text=True,timeout=10).strip()
                inspected=json.loads(subprocess.check_output(['docker','inspect',cid],text=True,timeout=10))[0]
                boundaries[service]=container_boundary(service,inspected)
            record['runtime_boundaries']=boundaries
            for route in ['/internal','/internal/tools/get_baseline_report','/%69nternal/agent/claim',
                          '/api/../internal/tools/get_baseline_report','//internal/agent/claim']:
                try:
                    urlopen(base+route,timeout=5)
                    raise AssertionError('INTERNAL_ROUTE_PUBLIC')
                except HTTPError as error:assert error.code==404
            # Production entrypoint was started first without a key. Only decisions are then
            # replaced by the explicitly labelled existing acceptance model, same image/SDK/tools.
            override={'services':{'agent':{
                'command':['node','agent/product-browser-worker.mjs','http://api:8080'],
                'environment':{'AC_TEST_HEALTH_PORT':'8081','AC_TEST_HEALTH_HOST':'0.0.0.0'},
                'volumes':[str(Path('agent/product-browser-worker.mjs').resolve())+':/app/agent/product-browser-worker.mjs:ro']}}}
            (root/'test-model.json').write_text(json.dumps(override))
            compose.extend(['-f',str(root/'test-model.json')])
            command(['up','-d','--no-build','--wait','agent'])
            inputs=root/'inputs';inputs.mkdir()
            files=sources(inputs)
            manifest=root/'inputs.json'
            manifest.write_text(json.dumps({'users':files[0]['path'],'events':[f['path'] for f in files[1:]],'mapping':MAPPING}))
            with (root/'browser.log').open('w') as log:
                subprocess.run(['node','scripts/product_browser_qa.cjs',base,str(manifest),str(root/'visual')],
                    env={**os.environ,'AC_TEST_DOCKER_HOST':'1'},stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
            checks=json.loads((root/'visual/checks.json').read_text())
            before=reports([checks['parent'],checks['child']])
            command(['up','-d','--no-build','--force-recreate','--wait'],240)
            assert reports([checks['parent'],checks['child']])==before
            engine=database_engine(pg.url)
            try:
                with engine.connect() as connection:
                    assert connection.execute(text("SELECT count(*) FROM agent_turns WHERE status='succeeded'")).scalar_one()==4
                    record['migration']=connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
                # A genuine maintenance-window backup, then restore into new persistent services.
                command(['stop'],60)
                backup(engine,storage,root/'backup',pg.bin)
            finally:engine.dispose()
            with LocalPostgres() as restored_pg,LocalS3() as restored_s3:
                restored_storage=S3Storage('deployment-restored',restored_s3.endpoint,restored_s3.access_key,restored_s3.secret_key)
                restored_storage.create_bucket()
                restored_engine=database_engine(restored_pg.url)
                try:
                    outcome=restore(restored_engine,restored_storage,root/'backup',restored_pg.bin)
                finally:restored_engine.dispose()
                configure_target(root/'restored-server.env',restored_pg,restored_s3,restored_storage.bucket)
                record['restored_services']={'postgres':str(restored_pg.root),'s3':str(restored_s3.root)}
                try:
                    command(['up','-d','--no-build','--force-recreate','--wait'],240)
                    assert reports([checks['parent'],checks['child']])==before
                    record.update(status='passed',report_hashes=before,browser=checks,restore=outcome)
                finally:command(['stop'],60)
        except Exception as error:
            record.update(status='failed',error_type=type(error).__name__)
            raise
        finally:
            # Stop only our unique Compose project. Keep containers, volumes and source evidence.
            try:command(['stop'],60)
            finally:
                (root/'result.json').write_text(json.dumps(record,indent=2,sort_keys=True))
                print(f'Deployment evidence: {root}',flush=True)
    return root


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag',default='ph41-local')
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    if not args.run:parser.error('--run is required to create isolated services and containers')
    run(args.tag)
