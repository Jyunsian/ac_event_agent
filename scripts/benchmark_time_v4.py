"""Reproducible 100k/20k/2k Time V4 full-pipeline benchmark."""
from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from uuid import uuid4

if __package__ in (None,""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from scripts.generate_casual_v3_fixture import generate
from scripts.local_postgres import LocalPostgres
from scripts.local_s3 import LocalS3
from server.candidate_reader import candidate_context
from server.db import Repository,database_engine
from server.pipeline import pipeline_version
from server.resources import Limits,directory_bytes
from server.storage import ObjectManifest,S3Storage
from server.uploads import UploadService
from server.worker import Worker,baseline_handler


REQUIRED_STAGES=frozenset({'normalized','quality_v4','targets_v4','exploration_features_v4','discovery_v4','full_features_v4','validation_v4','report_v4','cache_audit_v4'})
from server.analysis.v4_contract import defaults
CONFIG=defaults()



@contextmanager
def environment(values):
    previous={key:os.environ.get(key) for key in values};os.environ.update(values)
    try:yield
    finally:
        for key,value in previous.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


@contextmanager
def stage_timings(path):
    """Record actual immutable-stage builder and restore timings."""
    from server.checkpoints import StageRunner
    original=StageRunner.run
    with Path(path).open("x") as stream:
        def measured(self,stage,*args,**kwargs):
            started=time.monotonic();cpu=time.process_time();completed=False;builder_wall=None;builder_cpu=None
            if len(args)>=2 and callable(args[1]):
                builder=args[1]
                def wrapped(*inputs,**options):
                    nonlocal builder_wall,builder_cpu
                    wall=time.monotonic();inner_cpu=time.process_time()
                    try:return builder(*inputs,**options)
                    finally:builder_wall=time.monotonic()-wall;builder_cpu=time.process_time()-inner_cpu
                args=(args[0],wrapped,*args[2:])
            try:
                result=original(self,stage,*args,**kwargs);completed=True;return result
            finally:
                row={"stage":stage,"completed":completed,"builder_wall_seconds":builder_wall,
                    "builder_cpu_seconds":builder_cpu,"inclusive_wall_seconds":time.monotonic()-started,
                    "inclusive_cpu_seconds":time.process_time()-cpu}
                stream.write(json.dumps(row,sort_keys=True)+"\n");stream.flush();os.fsync(stream.fileno())
        StageRunner.run=measured
        try:yield
        finally:StageRunner.run=original


def benchmark_handler(payload):
    with stage_timings(os.environ["TIME_V4_BENCHMARK_TIMINGS"]):
        return baseline_handler(payload)


def independent_truth(source):
    """Independent CSV/Decimal truth; imports no production calculation code."""
    with (source/"users.csv").open(newline="") as stream:
        installs={(row["app_id"],row["user_id"]):datetime.fromisoformat(row["installed_at"])
                  for row in csv.DictReader(stream)}
    seen={};event_users=set();revenue=Decimal("0");events=0
    with (source/"events.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            identity=(row["app_id"],row["event_id"]);digest=hashlib.sha256(
                json.dumps(row,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            if identity in seen:
                if seen[identity]!=digest:raise ValueError("CONFLICTING_REFERENCE_EVENT")
                continue
            seen[identity]=digest;events+=1;user=(row["app_id"],row["user_id"]);event_users.add(user)
            elapsed=(datetime.fromisoformat(row["event_time"])-installs[user]).total_seconds()
            if row["event_name"]=="ad_impression" and row["revenue_usd"] and 0<=elapsed<168*3600:
                revenue+=Decimal(row["revenue_usd"])
    return {"users":len(installs),"events":events,"zero_event_users":len(set(installs)-event_users),
            "mature_users":len(installs),"d7_revenue_usd":str(revenue)}


def _mapping(source):
    value={}
    for role in ("users","events"):
        with (source/f"{role}.csv").open(newline="") as stream:value[role]={name:name for name in next(csv.reader(stream))}
    return value


def _download_kind(connection,storage,run_id,kind,destination):
    row=connection.execute(text("SELECT object_key,sha256,size_bytes FROM artifacts WHERE run_id=:run AND kind=:kind"),
                           {"run":run_id,"kind":kind}).mappings().one()
    manifest=ObjectManifest(row["object_key"],row["sha256"],row["size_bytes"],"application/octet-stream")
    storage.download_file(manifest,destination)
    return {"sha256":row["sha256"],"size_bytes":row["size_bytes"]}


def run_benchmark(directory:Path,users=2200,events=100000,seed=42,concentrated=False):
    directory=Path(directory).absolute();Limits.from_environment().preflight(events*320+users*160,directory)
    directory.mkdir(mode=0o700)
    record={"schema_version":"4.0","analysis_version":"4.0-time-aware","synthetic":True,
        "status":"running","users":users,"events":events,"seed":seed,"config":{**CONFIG,"seed":seed},
        "pipeline_version":pipeline_version(),"python":sys.version,
        "hardware":{"system":platform.platform(),"machine":platform.machine(),"logical_cpus":os.cpu_count()},
        "ram_scope":"compute child resource monitor plus retained local PG/S3 disk"}
    started=time.monotonic()
    try:
        source=generate(directory/"source",users,events,seed)
        if concentrated:
            with (source/'users.csv').open() as stream:ur=list(csv.DictReader(stream))
            installs={r['user_id']:datetime.fromisoformat(r['installed_at']) for r in ur}
            with (source/'events.csv').open() as stream:
                reader=csv.DictReader(stream);fields=reader.fieldnames;rows=list(reader)
            positions={r['user_id']:i for i,r in enumerate(ur)}
            for row in rows:
                i=positions[row['user_id']]
                if i%5:
                    old=row['user_id'];new=ur[i%20]['user_id'];shift=installs[new]-installs[old]
                    row['user_id']=new
                    for field in ('event_time','available_at'):
                        if row[field]:row[field]=(datetime.fromisoformat(row[field])+shift).isoformat()
            with (source/'events.csv').open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
        record['concentrated']=concentrated
        expected=independent_truth(source);record["expected"]=expected
        export=json.loads((source/"export.json").read_text());mapping=_mapping(source)
        record["source_hashes"]={name:hashlib.sha256((source/f"{name}.csv").read_bytes()).hexdigest() for name in ("users","events")}
        with LocalPostgres() as pg,LocalS3() as s3:
            record["retained_services"]={"postgres":str(pg.root),"s3":str(s3.root)}
            subprocess.run([sys.executable,"-m","alembic","upgrade","head"],check=True,capture_output=True,timeout=30,
                           env={**os.environ,"DATABASE_URL":pg.url})
            engine=database_engine(pg.url)
            try:
                storage=S3Storage("time-v4-capacity",s3.endpoint,s3.access_key,s3.secret_key);storage.create_bucket()
                sources=[]
                for role in ("users","events"):
                    item=storage.put_file(storage.new_key("time-v4-input","csv"),source/f"{role}.csv","text/csv")
                    sources.append({**item.to_dict(),"role":role,"format":"csv"})
                repo=Repository(engine)
                with engine.begin() as connection:
                    project=repo.create_project(connection,"casual-capacity","Time V4 capacity")
                    dataset=repo.create_dataset(connection,project["id"]);repo.seal_dataset(connection,dataset["id"],sources,mapping,export)
                    run=repo.create_run(connection,dataset["id"],record["config"],str(uuid4()),calculation_version="4.0-time-aware")
                run_id=str(run["id"]);record["run_id"]=run_id
                variables={"DATABASE_URL":pg.url,"S3_ENDPOINT_URL":s3.endpoint,"S3_BUCKET":storage.bucket,
                    "AWS_ACCESS_KEY_ID":s3.access_key,"AWS_SECRET_ACCESS_KEY":s3.secret_key,
                    "WORKER_WORK_ROOT":str(directory/"work"),
                    "TIME_V4_BENCHMARK_TIMINGS":str(directory/"stage_timings.jsonl")}
                compute=time.monotonic()
                with environment(variables):
                    if not Worker(engine,handler=benchmark_handler,task_timeout=7200).run_once():raise RuntimeError("JOB_NOT_CLAIMED")
                record["compute_wall_seconds"]=time.monotonic()-compute
                with engine.connect() as connection:
                    saved=repo.get_run(connection,run_id);record["run_status"]=saved["status"]
                    record["progress"]=saved["progress"];record["error"]=saved["error"]
                    if saved["status"]!="succeeded":raise RuntimeError("BENCHMARK_COMPUTE_FAILED")
                    downloaded={kind:_download_kind(connection,storage,run_id,kind,directory/f"{kind}.json")
                                for kind in ("quality","dataset_profile","targets","search")}
                    report_meta={kind:_download_kind(connection,storage,run_id,kind,directory/f"{kind}.{kind.split('_')[-1]}")
                                 for kind in ("report_json","report_csv","report_html")}
                quality=json.loads((directory/"quality.json").read_text());profile=json.loads((directory/"dataset_profile.json").read_text())
                targets=json.loads((directory/"targets.json").read_text())
                baseline={"counts": saved["progress"]["counts"]};report=json.loads((directory/"report_json.json").read_text())
                target_revenue=sum(Decimal(str(row["revenue_usd"])) for row in targets["summary"].values())
                report_model,_,catalog,files=candidate_context(UploadService(engine,storage),run_id,1)
                details=[path for path in files if path.startswith("catalog/details/")]
                completed=set(saved["progress"].get("completed_stages",[]))
                checks={"events":profile["events"]==expected["events"],"users":profile["users"]==expected["users"],
                    "zero_event_users":quality["zero_event_users"]==expected["zero_event_users"],
                    "mature_users":targets["mature_users"]==expected["mature_users"],
                    "d7_revenue":math.isclose(float(target_revenue),float(expected["d7_revenue_usd"]),rel_tol=1e-12,abs_tol=1e-9),
                    "all_stages":REQUIRED_STAGES==completed,"discovery_20000":baseline["counts"]["discovery"]==20_000,
                    "validation_2000":baseline["counts"]["validation"]==2_000,
                    "catalog_consistent":catalog["evaluated_count"]==len(catalog["entries"])==len(details)==baseline["counts"]["rules"],
                    "priority_bound":len(catalog["priority_ids"])<=10,"report_identity":report_model==report and report["run_id"]==run_id,
                    "report_v4":report["schema_version"]=="4.0"}
                record.update({"checks":checks,"counts":baseline["counts"],"stage_timings":str(directory/"stage_timings.jsonl"),
                    "artifact_bytes":{**downloaded,**report_meta,"candidate_catalog":files["catalog/catalog.json"]},
                    "catalog_detail_bytes":sum(files[path]["size_bytes"] for path in details),
                    "storage_disk_bytes":directory_bytes(s3.root),"database_disk_bytes":directory_bytes(pg.root),
                    "work_disk_bytes":directory_bytes(directory/"work")})
                if not all(checks.values()):raise RuntimeError("BENCHMARK_TRUTH_OR_CAPACITY_MISMATCH")
                record["status"]="passed"
            finally:engine.dispose()
    except Exception as error:
        record["status"]="failed";record["failure_type"]=type(error).__name__
        if isinstance(error,RuntimeError):record["failure_code"]=str(error)
        raise
    finally:
        record["total_wall_seconds"]=time.monotonic()-started
        record["retained_benchmark_bytes"]=directory_bytes(directory)
        with (directory/"result.json").open("x") as stream:json.dump(record,stream,sort_keys=True,indent=2,allow_nan=False)
    return record


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--directory",type=Path,required=True)
    parser.add_argument("--users",type=int,default=2200);parser.add_argument("--events",type=int,default=100000)
    parser.add_argument("--concentrated",action="store_true");parser.add_argument("--seed",type=int,default=42);parser.add_argument("--run",action="store_true");args=parser.parse_args()
    if not args.run:
        print(json.dumps(Limits.from_environment().preflight(args.events*320+args.users*160,args.directory),sort_keys=True))
    else:
        try:result=run_benchmark(args.directory,args.users,args.events,args.seed,args.concentrated);print(json.dumps({"status":result["status"],"run_id":result["run_id"]}))
        except Exception as error:
            print(json.dumps({"status":"failed","error_type":type(error).__name__,"detail":"See retained result.json"}));raise SystemExit(1) from None
