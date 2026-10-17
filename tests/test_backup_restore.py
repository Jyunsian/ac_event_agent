import json
import hashlib
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from scripts.backup_restore import backup,restore,verify_bundle,BackupError
from scripts.local_postgres import LocalPostgres
from scripts.local_s3 import LocalS3
from server.db import database_engine
from server.storage import S3Storage
from server.api.main import create_app
from server.worker import Worker
from server.agent_queue import AgentQueue
from tests.test_jobs import jobdb
from tests.test_upload_api import api
from tests.test_pipeline import create_run,configure_worker


def test_real_database_and_objects_backup_restore_report_bytes(api,jobdb,tmp_path,monkeypatch):
    client,engine,storage=api
    run=create_run(jobdb,storage,tmp_path/'source');rid=str(run['id'])
    configure_worker(engine,storage,monkeypatch)
    discovered=shutil.which('pg_dump')
    pg_bin=Path(os.environ.get('AC_POSTGRES_BIN') or (str(Path(discovered).parent) if discovered else '/opt/homebrew/opt/postgresql@15/bin'))
    retained=Path(tempfile.mkdtemp(prefix='backup-acceptance-',dir=Path('.runtime').resolve()))
    bundle=retained/'backup'
    with pytest.raises(BackupError,match='WORKSPACE_NOT_QUIESCENT'):
        backup(engine,storage,tmp_path/'busy',pg_bin)
    assert not (tmp_path/'busy/COMPLETE').exists()
    assert Worker(engine,task_timeout=120).run_once()
    originals={fmt:client.get(f'/api/runs/{rid}/reports/1/{fmt}').content for fmt in ['html','json','csv']}
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'backup-conversation'}).json()['id']
    sent=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'backup-message'},json={
        'content':'合成備份還原測試','selected_run_id':rid});assert sent.status_code==202
    queue=AgentQueue(engine);queue.finish(queue.claim('backup-test'),'合成持久訊息測試；這不是模型生成的分析。')
    original_events=client.get(f'/api/conversations/{cid}/events').json()
    manifest=backup(engine,storage,bundle,pg_bin)
    assert manifest['objects'] and manifest==verify_bundle(bundle)
    checked=subprocess.run([sys.executable,'-m','scripts.backup_restore','verify','--directory',str(bundle)],capture_output=True,text=True,timeout=15)
    assert checked.returncode==0 and json.loads(checked.stdout)['status']=='verified'
    assert len(manifest['alembic'])==1
    with LocalPostgres() as pg,LocalS3() as s3:
        target=database_engine(pg.url)
        try:
            destination=S3Storage('restored-synthetic',s3.endpoint,s3.access_key,s3.secret_key);destination.create_bucket()
            guarded=S3Storage('guarded-synthetic',s3.endpoint,s3.access_key,s3.secret_key);guarded.create_bucket()
            sentinel=guarded.put_bytes('guard/original',b'preserve this object')
            with pytest.raises(BackupError,match='RESTORE_BUCKET_NOT_EMPTY'):restore(target,guarded,bundle,pg.bin)
            assert guarded.get_bytes(sentinel)==b'preserve this object'
            with target.connect() as c:assert c.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")).scalar_one()==0
            result=restore(target,destination,bundle,pg.bin)
            assert result['status']=='restored'
            with TestClient(create_app(target,destination)) as reopened:
                for fmt,expected in originals.items():
                    response=reopened.get(f'/api/runs/{rid}/reports/1/{fmt}')
                    assert response.status_code==200,response.text
                    assert response.content==expected
                assert reopened.get(f'/api/runs/{rid}/view').json()['ready']
                assert reopened.get(f'/api/conversations/{cid}/events').json()==original_events
            with pytest.raises(BackupError,match='RESTORE_DATABASE_NOT_EMPTY'):
                restore(target,destination,bundle,pg.bin)
            for fmt,expected in originals.items():assert client.get(f'/api/runs/{rid}/reports/1/{fmt}').content==expected
        finally:target.dispose()
    tampered=tmp_path/'tampered';shutil.copytree(bundle,tampered)
    with (tampered/manifest['objects'][0]['file']).open('ab') as stream:stream.write(b'corruption')
    with pytest.raises(BackupError,match='BACKUP_CHECKSUM_MISMATCH'):verify_bundle(tampered)
    print(f'Restored three report formats and conversation for synthetic run {rid}; {len(manifest["objects"])} objects verified; backup retained: {bundle}')


def test_incomplete_bundle_and_symlink_refused(tmp_path):
    directory=tmp_path/'incomplete';directory.mkdir()
    (directory/'manifest.json').write_text('{}')
    with pytest.raises(FileNotFoundError):verify_bundle(directory)
    linked=tmp_path/'linked';linked.mkdir()
    outside=tmp_path/'outside.dump';outside.write_bytes(b'synthetic')
    (linked/'database.dump').symlink_to(outside)
    raw=json.dumps({'schema_version':'1.0','database':{'file':'database.dump','sha256':hashlib.sha256(b'synthetic').hexdigest(),'size_bytes':9},'objects':[]}).encode()
    (linked/'manifest.json').write_bytes(raw);(linked/'COMPLETE').write_text(hashlib.sha256(raw).hexdigest())
    with pytest.raises(BackupError,match='UNSAFE_BACKUP_PATH'):verify_bundle(linked)


def test_cli_requires_maintenance_and_trusted_source_before_connecting(tmp_path):
    for flags,code in [([], 'MAINTENANCE_CONFIRMATION_REQUIRED'),(['--maintenance-confirmed'],'TRUSTED_BACKUP_REQUIRED')]:
        result=subprocess.run([sys.executable,'-m','scripts.backup_restore','restore','--directory',str(tmp_path/'absent'),*flags],capture_output=True,text=True,timeout=10)
        assert result.returncode==1 and json.loads(result.stdout)['error_code']==code
