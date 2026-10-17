"""Reproducible synthetic full-pipeline benchmark against isolated real PG/S3 services."""
import argparse
from contextlib import contextmanager
import csv
from datetime import datetime
from decimal import Decimal
import json
import hashlib
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sqlite3
import sys
import time
from uuid import uuid4

from sqlalchemy import text
from scripts.generate_fixture import generate
from scripts.local_postgres import LocalPostgres
from scripts.local_s3 import LocalS3
from server.db import Repository,database_engine
from server.resources import Limits,directory_bytes,ResourceLimitError
from server.storage import S3Storage,ObjectManifest
from server.worker import Worker, baseline_handler
from server.pipeline import pipeline_version

REQUIRED_STAGES=frozenset(['normalized','quality','targets','exploration','search',
    'exploration_triggers','selection','features','validation','diagnostics','cache_audit','baseline','report'])


@contextmanager
def stage_timings(output_path=None):
    """Synthetic benchmark-only inclusive stage timings, without payload data."""
    from server.checkpoints import StageRunner
    original=StageRunner.run
    stream=Path(output_path).open('x') if output_path is not None else None
    def measured(self,stage,*args,**kwargs):
        wall=time.monotonic();cpu=time.process_time();completed=False
        builder_cpu=builder_wall=None
        if len(args)>=2 and callable(args[1]):
            builder=args[1]
            def measured_builder(*inputs,**options):
                nonlocal builder_cpu,builder_wall
                start_wall=time.monotonic();start_cpu=time.process_time()
                try:return builder(*inputs,**options)
                finally:
                    builder_cpu=time.process_time()-start_cpu
                    builder_wall=time.monotonic()-start_wall
            args=(args[0],measured_builder,*args[2:])
        try:
            result=original(self,stage,*args,**kwargs);completed=True
            return result
        finally:
            label=stage if isinstance(stage,str) and (stage in REQUIRED_STAGES or
                re.fullmatch(r'validation_batch_[0-9]{4}',stage)) else 'other'
            encoded=json.dumps({'benchmark_stage':label,'completed':completed,
                'builder_cpu_seconds':builder_cpu,'builder_wall_seconds':builder_wall,
                'inclusive_cpu_seconds':time.process_time()-cpu,
                'inclusive_wall_seconds':time.monotonic()-wall})
            print(encoded,flush=True)
            if stream is not None:
                stream.write(encoded+'\n');stream.flush();os.fsync(stream.fileno())
    StageRunner.run=measured
    try:yield
    finally:
        StageRunner.run=original
        if stream is not None:stream.close()


def benchmark_handler(payload):
    """Expose exception location for synthetic runs, never messages or locals.

    Keep the normal handler, resource monitor and Worker error handling intact.
    Exception messages can contain source data or credentials, so omit them.
    """
    try:
        with stage_timings(os.environ.get('SYNTHETIC_BENCHMARK_TIMINGS_PATH')):
            return baseline_handler(payload)
    except Exception as error:
        import traceback
        frames=[{'file':Path(frame.filename).name,'line':frame.lineno,'function':frame.name}
                for frame in traceback.extract_tb(error.__traceback__)]
        print(json.dumps({'benchmark_exception_type':type(error).__name__,'frames':frames}),
              file=sys.stderr,flush=True)
        raise


def full_pipeline_completed(progress):
    return REQUIRED_STAGES.issubset(progress.get('completed_stages',[]))


@contextmanager
def reference_index(index_path=None):
    """Optional disk-backed identity index; no DuckDB or production analysis code."""
    if index_path is None:
        entries={}
        def repeated(identity,digest):
            if identity in entries:
                if entries[identity]!=digest:raise ValueError('CONFLICTING_REFERENCE_EVENT')
                return True
            entries[identity]=digest
            return False
        yield repeated
        return
    # Independent derived artifact, not written into immutable source data. Never overwrite.
    descriptor=os.open(index_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(descriptor)
    db=sqlite3.connect(index_path)
    try:
        db.execute('PRAGMA cache_size=-16384')
        db.execute('PRAGMA mmap_size=0')
        db.execute('CREATE TABLE seen(app TEXT NOT NULL,event TEXT NOT NULL,digest BLOB NOT NULL,PRIMARY KEY(app,event)) WITHOUT ROWID')
        def repeated(identity,digest):
            key=(identity[0] or '',identity[1])
            existing=db.execute('SELECT digest FROM seen WHERE app=? AND event=?',key).fetchone()
            if existing is not None:
                if existing[0]!=digest:raise ValueError('CONFLICTING_REFERENCE_EVENT')
                return True
            db.execute('INSERT INTO seen VALUES(?,?,?)',(*key,digest))
            return False
        yield repeated
        db.commit()
    finally:db.close()


def independent_truth(directory,index_path=None):
    """CSV/Decimal reference; does not import any pipeline calculation implementation."""
    with (directory/'users.csv').open() as stream:
        installs={row['user_id']:datetime.fromisoformat(row['installed_at']) for row in csv.DictReader(stream)}
    seen=set();events=0;raw_events=0;revenue=Decimal(0)
    with (directory/'events.csv').open() as stream,reference_index(index_path) as repeated:
        for row in csv.DictReader(stream):
            raw_events+=1
            identity=(row.get('app_id'),row.get('event_id',str(raw_events)))
            digest=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).digest()
            if repeated(identity,digest):continue
            events+=1;seen.add(row['user_id'])
            elapsed=(datetime.fromisoformat(row['event_time'])-installs[row['user_id']]).total_seconds()
            if 0<=elapsed<168*3600:revenue+=Decimal(row['revenue_usd'])
    return {'users':len(installs),'events':events,'raw_events':raw_events,'duplicate_events':raw_events-events,'zero_event_users':len(installs)-len(seen),
            'mature_users':len(installs),'d7_revenue_usd':str(revenue)}


@contextmanager
def environment(values):
    previous={key:os.environ.get(key) for key in values}
    os.environ.update(values)
    try:yield
    finally:
        for key,value in previous.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


def capacity_preflight(directory,users,events,id_padding=0,duplicate_every=0):
    if type(users) is not int or type(events) is not int or users<1 or events<1:raise ValueError('INVALID_BENCHMARK_COUNTS')
    # Deliberately conservative generated CSV estimate. Actual sizes replace it before compute.
    if type(id_padding) is not int or not 0<=id_padding<=4096 or type(duplicate_every) is not int or duplicate_every<0 or duplicate_every==1:raise ValueError('INVALID_STRESS_PROFILE')
    estimated_source_bytes=events*(192+2*id_padding)+users*(128+id_padding)+1024
    result=Limits.from_environment().preflight(estimated_source_bytes,directory)
    return {**result,'users':users,'events':events,'source_size_is_estimate':True}


def run_benchmark(directory,users,events,seed=42,id_padding=0,duplicate_every=0):
    directory=Path(directory).absolute()
    preflight=capacity_preflight(directory,users,events,id_padding,duplicate_every)  # Before data generation or service creation.
    directory.mkdir(mode=0o700)
    record={'schema_version':'1.0','synthetic':True,'status':'running','users':users,'events':events,'seed':seed,
        'stress_profile':{'id_padding':id_padding,'duplicate_every':duplicate_every},
        'preflight':preflight,'hardware':{'system':platform.platform(),'machine':platform.machine(),'logical_cpus':os.cpu_count()},
        'python':sys.version,'pipeline_version':pipeline_version(),
        'limits':{k:v for k,v in Limits.from_environment().describe().items() if k!='work_root'},
        'ram_scope':'compute child peak RSS from getrusage; excludes PostgreSQL/S3 and benchmark controller'}
    if sys.platform=='darwin':
        record['hardware']['physical_memory_bytes']=int(subprocess.check_output(['sysctl','-n','hw.memsize'],text=True))
    else:record['hardware']['physical_memory_bytes']=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')
    started=time.monotonic()
    try:
        source=generate(directory/'source',users,events,seed,id_padding=id_padding,duplicate_every=duplicate_every)
        expected=independent_truth(source,directory/'reference.sqlite');record['expected']=expected
        record['reference_index']={'backend':'sqlite','cache_kib':16384,'path':'reference.sqlite',
            'scope':'identity/digest only; CSV/Decimal independently calculates D7; user install map remains in memory'}
        record['generation_and_truth_seconds']=time.monotonic()-started
        config=json.loads(Path('contracts/defaults.json').read_text());record['config']=config
        export=json.loads((source/'export.json').read_text())
        mapping={}
        for role in ['users','events']:
            with (source/f'{role}.csv').open() as stream:mapping[role]={name:name for name in next(csv.reader(stream))}
        with LocalPostgres() as pg,LocalS3() as s3:
            record['retained_services']={'postgres':str(pg.root),'s3':str(s3.root)}
            subprocess.run([sys.executable,'-m','alembic','upgrade','head'],check=True,capture_output=True,timeout=30,
                env={**os.environ,'DATABASE_URL':pg.url})
            engine=database_engine(pg.url)
            try:
                storage=S3Storage('benchmark-synthetic',s3.endpoint,s3.access_key,s3.secret_key);storage.create_bucket()
                sources=[]
                for role in ['users','events']:
                    obj=storage.put_file(storage.new_key('benchmark-input','csv'),source/f'{role}.csv','text/csv')
                    sources.append({**obj.to_dict(),'role':role,'format':'csv'})
                record['source_bytes']=sum(item['size_bytes'] for item in sources)
                record['source_hashes']={item['role']:item['sha256'] for item in sources}
                repo=Repository(engine)
                with engine.begin() as c:
                    project=repo.create_project(c,'synthetic',f'Benchmark {events} events')
                    dataset=repo.create_dataset(c,project['id']);repo.seal_dataset(c,dataset['id'],sources,mapping,export)
                    run=repo.create_run(c,dataset['id'],config,str(uuid4()));rid=str(run['id'])
                record['run_id']=rid
                print(json.dumps({'status':'compute_started','synthetic':True,'run_id':rid,'events':events}),flush=True)
                variables={'DATABASE_URL':pg.url,'S3_ENDPOINT_URL':s3.endpoint,'S3_BUCKET':storage.bucket,
                    'AWS_ACCESS_KEY_ID':s3.access_key,'AWS_SECRET_ACCESS_KEY':s3.secret_key,'WORKER_WORK_ROOT':str(directory/'work'),
                    'SYNTHETIC_BENCHMARK_TIMINGS_PATH':str(directory/'stage_timings.jsonl')}
                begin=time.monotonic()
                with environment(variables):
                    if not Worker(engine,handler=benchmark_handler).run_once():raise RuntimeError('BENCHMARK_JOB_NOT_CLAIMED')
                record['compute_wall_seconds']=time.monotonic()-begin
                with engine.connect() as c:
                    saved=repo.get_run(c,rid)
                    record['run_status']=saved['status'];record['progress']=saved['progress'];record['error']=saved['error']
                    if saved['status']!='succeeded':raise RuntimeError('BENCHMARK_COMPUTE_FAILED')
                    artifacts=c.execute(text("SELECT * FROM artifacts WHERE run_id=:id AND kind IN ('report_json','report_html','report_csv')"),{'id':rid}).mappings().all()
                if len(artifacts)!=3:raise RuntimeError('BENCHMARK_REPORT_INCOMPLETE')
                record['report_hashes']={}
                for item in artifacts:
                    manifest=ObjectManifest(item['object_key'],item['sha256'],item['size_bytes'],'application/octet-stream')
                    destination=directory/(item['kind']+'.'+item['kind'].split('_')[-1])
                    storage.download_file(manifest,destination);record['report_hashes'][item['kind']]=item['sha256']
                report=json.loads((directory/'report_json.json').read_text());summary=report['summary']
                actual_revenue=sum(Decimal(str(group['revenue_usd'])) for group in summary['targets']['summary'].values())
                checks={
                    'users':summary['data_profile']['users']==expected['users'],
                    'events':summary['data_profile']['events']==expected['events'],
                    'zero_event_users':summary['quality']['zero_event_users']==expected['zero_event_users'],
                    'mature_users':summary['targets']['mature_users']==expected['mature_users'],
                    'd7_revenue':math.isclose(float(actual_revenue),float(expected['d7_revenue_usd']),rel_tol=1e-10,abs_tol=1e-8),
                    'run_identity':report['run_id']==rid,
                    'synthetic':report['synthetic'] is True,
                    'full_pipeline':full_pipeline_completed(saved['progress']),
                }
                record.update(checks=checks,searched_candidates=summary['searched_candidate_count'],finalists=summary['candidate_count'])
                # V2 capacity must verify the whole evaluated family, not the <=10 priority report.
                from server.candidate_reader import candidate_context
                from server.uploads import UploadService
                _,_,catalog,files=candidate_context(UploadService(engine,storage),rid,1)
                detail_paths=[path for path in files if path.startswith('catalog/details/')]
                checks.update(v2_report=report['schema_version']=='2.0',
                    full_catalog=catalog['evaluated_count']==summary['searched_candidate_count']==len(catalog['entries'])==len(detail_paths),
                    priority_bound=len(catalog['priority_ids'])<=10,
                    candidate_budget=catalog['evaluated_count']<=2000)
                record['evaluated_candidates']=catalog['evaluated_count']
                record['reached_2000_candidates']=catalog['evaluated_count']==2000
                record['catalog_bytes']=files['catalog/catalog.json']['size_bytes']
                record['all_detail_bytes']=sum(files[path]['size_bytes'] for path in detail_paths)
                record['report_bytes']={item['kind']:item['size_bytes'] for item in artifacts}
                if not all(checks.values()):raise RuntimeError('BENCHMARK_TRUTH_MISMATCH')
                record['storage_disk_bytes']=directory_bytes(s3.root)
                record['database_disk_bytes']=directory_bytes(pg.root)
                record['status']='passed'
            finally:engine.dispose()
    except Exception as error:
        record['status']='failed';record['failure_type']=type(error).__name__
        if isinstance(error,RuntimeError):record['failure_code']=str(error)
        raise
    finally:
        record['total_wall_seconds']=time.monotonic()-started
        record['retained_benchmark_bytes']=directory_bytes(directory)
        with (directory/'result.json').open('x') as stream:json.dump(record,stream,sort_keys=True,indent=2,allow_nan=False)
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--users',type=int,required=True)
    parser.add_argument('--events',type=int,required=True)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--id-padding',type=int,default=0,help='Extra ASCII bytes on both user/event IDs, 0..4096')
    parser.add_argument('--duplicate-every',type=int,default=0,help='Replace every Nth raw row with previous row; 0 disables, N>=2')
    parser.add_argument('--run',action='store_true',help='Actually generate and run; omitted means read-only preflight')
    args=parser.parse_args()
    try:
        result=run_benchmark(args.directory,args.users,args.events,args.seed,args.id_padding,args.duplicate_every) if args.run else capacity_preflight(args.directory,args.users,args.events,args.id_padding,args.duplicate_every)
        print(json.dumps({k:v for k,v in result.items() if k in ['status','users','events','run_id','compute_wall_seconds','disk_free_bytes','estimated_work_bytes']},sort_keys=True))
    except Exception as error:
        print(json.dumps({'status':'failed','error_type':type(error).__name__,
            'error_code':str(error) if isinstance(error,ResourceLimitError) else 'BENCHMARK_FAILED',
            'detail':'Check retained result.json if run directory was created.'}))
        raise SystemExit(1) from None
