"""Quiescent workspace backup and non-overwriting isolated restore. Never deletes source data."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from sqlalchemy import text
from server.db import database_engine
from server.storage import ObjectManifest, S3Storage, storage_errors


class BackupError(Exception):
    pass


def fingerprint(path):
    digest=hashlib.sha256();size=0
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk);size+=len(chunk)
    return {'sha256':digest.hexdigest(),'size_bytes':size}


def durable_write(path,data):
    with path.open('xb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())


def sync_directory(path):
    handle=os.open(path,os.O_RDONLY)
    try:os.fsync(handle)
    finally:os.close(handle)


def pg_command(engine,pg_bin,tool,args):
    executable=Path(pg_bin)/tool if pg_bin else shutil.which(tool)
    if not executable or not Path(executable).is_file():raise BackupError('POSTGRES_TOOL_MISSING')
    url=engine.url
    env={k:v for k,v in os.environ.items() if not k.startswith('PG')}
    env.update(PGHOST=url.host or 'localhost',PGPORT=str(url.port or 5432),PGUSER=url.username or '',
               PGPASSWORD=url.password or '',PGDATABASE=url.database or 'postgres',PGCONNECT_TIMEOUT='10')
    for option in ['sslmode','sslrootcert','sslcert','sslkey','channel_binding']:
        if option in url.query:env['PG'+option.upper()]=str(url.query[option])
    result=subprocess.run([str(executable),*args],env=env,capture_output=True,timeout=600)
    if result.returncode:raise BackupError(tool.upper()+'_FAILED')  # Do not print credentials or raw database content.


def inventory(storage):
    with storage_errors():
        for page in storage.client.get_paginator('list_objects_v2').paginate(Bucket=storage.bucket):
            for item in page.get('Contents',[]):yield item['Key']


def referenced_objects(value):
    if isinstance(value,dict):
        if {'object_key','sha256','size_bytes'}<=value.keys():
            yield {k:value[k] for k in ['object_key','sha256','size_bytes']}
        for child in value.values():yield from referenced_objects(child)
    elif isinstance(value,list):
        for child in value:yield from referenced_objects(child)


def backup(engine,storage,output,pg_bin=None):
    output=Path(output).absolute()
    output.mkdir(mode=0o700)  # A pre-existing directory is never overwritten or cleaned.
    (output/'objects').mkdir(mode=0o700)
    # Maintenance window: block new DB writes throughout dump and object copy. Immutable S3
    # objects can still be read. Refuse unsettled work rather than exporting nonportable leases/uploads.
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c, c.begin():
        c.execute(text("SET LOCAL lock_timeout='5s'"))
        tables=c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all()
        if not {'datasets','artifacts','jobs','agent_turns','uploads'}<=set(tables):raise BackupError('SCHEMA_NOT_READY')
        quote=engine.dialect.identifier_preparer.quote
        c.execute(text('LOCK TABLE '+','.join('public.'+quote(t) for t in tables)+' IN SHARE MODE'))
        for table,predicate in [('jobs',"status IN ('queued','running')"),('agent_turns',"status IN ('queued','running')"),('uploads',"status='uploading'")]:
            if c.execute(text(f'SELECT count(*) FROM {table} WHERE {predicate}')).scalar_one():raise BackupError('WORKSPACE_NOT_QUIESCENT')
        snapshot=c.execute(text('SELECT pg_export_snapshot()')).scalar_one()
        pg_command(engine,pg_bin,'pg_dump',['--format=custom','--no-owner','--no-privileges',
            '--snapshot='+snapshot,'--lock-wait-timeout=5s','--file='+str(output/'database.dump')])
        objects=[]
        for index,key in enumerate(inventory(storage)):
            metadata=storage.head(key)
            local=f'objects/{index:08d}.bin';dest=output/local
            with storage_errors():
                response=storage.client.get_object(Bucket=storage.bucket,Key=key)
                with closing(response['Body']) as body, dest.open('xb') as stream:
                    for chunk in body.iter_chunks(1024*1024):stream.write(chunk)
                    stream.flush();os.fsync(stream.fileno())
            actual=fingerprint(dest)
            if actual['size_bytes']!=metadata['size_bytes'] or (metadata['sha256'] and actual['sha256']!=metadata['sha256']):
                raise BackupError('SOURCE_OBJECT_CHANGED')
            objects.append({**ObjectManifest(key,actual['sha256'],actual['size_bytes'],metadata['content_type']).to_dict(),'file':local})
        by_key={item['object_key']:item for item in objects}
        for table in tables:
            for row in c.execution_options(stream_results=True).execute(text('SELECT row_to_json(t) FROM public.'+quote(table)+' t')).scalars():
                for ref in referenced_objects(row):
                    actual=by_key.get(ref['object_key'])
                    if not actual or any(actual[k]!=ref[k] for k in ['sha256','size_bytes']):raise BackupError('REFERENCED_OBJECT_MISSING_OR_CHANGED')
        c.execution_options(stream_results=False)
        manifest={'schema_version':'1.0','backup_id':str(uuid4()),'created_at':datetime.now(timezone.utc).isoformat(),
            'database':{'file':'database.dump',**fingerprint(output/'database.dump')},'objects':objects,
            'alembic':list(c.execute(text('SELECT version_num FROM alembic_version')).scalars()),
            'table_counts':{t:c.execute(text('SELECT count(*) FROM public.'+quote(t))).scalar_one() for t in tables}}
        # Completion marker is written only after the complete inventory and database exist.
        encoded=json.dumps(manifest,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()
        durable_write(output/'manifest.json',encoded)
        sync_directory(output/'objects');sync_directory(output)
        durable_write(output/'COMPLETE',hashlib.sha256(encoded).hexdigest().encode())
        sync_directory(output);sync_directory(output.parent)
    return manifest


def verify_bundle(directory):
    directory=Path(directory).resolve(strict=True)
    if any((directory/name).is_symlink() for name in ['manifest.json','COMPLETE']):raise BackupError('UNSAFE_BACKUP_PATH')
    if (directory/'manifest.json').stat().st_size>16*1024**2:raise BackupError('MANIFEST_TOO_LARGE')
    raw=(directory/'manifest.json').read_bytes()
    if len(raw)>16*1024**2:raise BackupError('MANIFEST_TOO_LARGE')
    if (directory/'COMPLETE').read_text()!=hashlib.sha256(raw).hexdigest():raise BackupError('MANIFEST_CHECKSUM_MISMATCH')
    manifest=json.loads(raw)
    if manifest.get('schema_version')!='1.0' or manifest['database']['file']!='database.dump':raise BackupError('INVALID_BACKUP')
    seen=set()
    for index,item in enumerate([manifest['database'],*manifest['objects']]):
        if index:
            ObjectManifest(**{k:item[k] for k in ['object_key','sha256','size_bytes','content_type']})
            if item['object_key'] in seen or item['file']!=f'objects/{index-1:08d}.bin':raise BackupError('INVALID_BACKUP')
            if item['size_bytes']>5*1024**3:raise BackupError('RESTORE_SINGLE_OBJECT_LIMIT')
            seen.add(item['object_key'])
        path=directory/item['file']
        if path.is_symlink() or not path.resolve().is_relative_to(directory):raise BackupError('UNSAFE_BACKUP_PATH')
        if fingerprint(path)!={k:item[k] for k in ['sha256','size_bytes']}:raise BackupError('BACKUP_CHECKSUM_MISMATCH')
    return manifest


def restore(engine,storage,directory,pg_bin=None):
    directory=Path(directory).resolve(strict=True)
    manifest=verify_bundle(directory)  # Verify every byte before any target mutation.
    with engine.connect() as c:
        relations=c.execute(text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'")).scalar_one()
        functions=c.execute(text("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'")).scalar_one()
        if relations or functions:raise BackupError('RESTORE_DATABASE_NOT_EMPTY')
    if next(inventory(storage),None) is not None:raise BackupError('RESTORE_BUCKET_NOT_EMPTY')
    with storage_errors():
        if storage.client.list_multipart_uploads(Bucket=storage.bucket,MaxUploads=1).get('Uploads'):raise BackupError('RESTORE_BUCKET_NOT_EMPTY')
    for item in manifest['objects']:
        result=storage.put_file(item['object_key'],directory/item['file'],item['content_type'])
        storage.verify_object(result.object_key,item['size_bytes'],item['sha256'])
    # No --clean or --create. Restore schema/data/constraints atomically into a pre-provisioned
    # empty DB. On failure retain partial target objects for audit; never delete automatically.
    pg_command(engine,pg_bin,'pg_restore',['--dbname='+str(engine.url.database or 'postgres'),'--single-transaction',
        '--exit-on-error','--no-owner','--no-privileges',str(directory/'database.dump')])
    with engine.connect() as c:
        if list(c.execute(text('SELECT version_num FROM alembic_version')).scalars())!=manifest['alembic']:raise BackupError('RESTORE_SCHEMA_MISMATCH')
        quote=engine.dialect.identifier_preparer.quote
        for table,expected in manifest['table_counts'].items():
            if c.execute(text('SELECT count(*) FROM public.'+quote(table))).scalar_one()!=expected:raise BackupError('RESTORE_ROW_COUNT_MISMATCH')
    return {'backup_id':manifest['backup_id'],'objects':len(manifest['objects']),'status':'restored'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['backup','verify','restore'])
    parser.add_argument('--directory',required=True)
    parser.add_argument('--pg-bin',default=os.environ.get('AC_POSTGRES_BIN'))
    parser.add_argument('--maintenance-confirmed',action='store_true')
    parser.add_argument('--trusted-backup',action='store_true')
    args=parser.parse_args()
    engine=None
    try:
        if args.operation=='verify':result={'status':'verified','backup_id':verify_bundle(args.directory)['backup_id']}
        else:
            if not args.maintenance_confirmed:raise BackupError('MAINTENANCE_CONFIRMATION_REQUIRED')
            if args.operation=='restore' and not args.trusted_backup:raise BackupError('TRUSTED_BACKUP_REQUIRED')
            engine=database_engine();storage=S3Storage.from_environment()
            result=(backup if args.operation=='backup' else restore)(engine,storage,args.directory,args.pg_bin)
            result={k:result[k] for k in ['backup_id']}
            result['status']=args.operation+'-completed'
        print(json.dumps(result))
    except Exception as error:
        print(json.dumps({'status':'failed','error_code':str(error) if isinstance(error,BackupError) else 'BACKUP_OPERATION_FAILED'}))
        raise SystemExit(1) from None
    finally:
        if engine:engine.dispose()


if __name__=='__main__':main()
