import json
from datetime import datetime,timedelta,timezone
from uuid import uuid4

from server.jobs import JobQueue
from server.pipeline import run_baseline
from server.uploads import UploadService
from server.candidate_reader import candidate_context
from server.worker import Worker
from tests.test_ingest import EVENT_TYPES,USER_TYPES,write_source
from tests.test_jobs import jobdb
from tests.test_pipeline import configure_worker
from tests.test_upload_api import api


CONFIG={"schema_version":"1.0","analysis_version":"3.0-casual-game",
    "windows_hours":[3,6,24,48,72,96,120,144],"max_discovery_candidates":100,
    "max_candidates":20,"max_finalists":5,"seed":42,"min_group_users":2,
    "bootstrap_replicates":1000,"exploration_fraction":.7}
EXPORT={"schema_version":"1.0","exported_at":"2026-01-12T00:00:00Z",
    "complete_through":"2026-01-12T00:00:00Z","origin":"install",
    "id_policy":"one anonymous user_id per install","revenue_timing":"immediate","synthetic":True}
MAPPING={"users":{name:name for name in USER_TYPES},"events":{name:name for name in EVENT_TYPES}}
EXPECTED_STAGES={"normalized","quality_v3","targets_v3","exploration_features_v3","discovery_v3",
    "discovery_membership_v3","validation_freeze_v3","full_features_v3","holdout_membership_v3",
    "validation_v3","diagnostics_v3","catalog_v3","report_v3","baseline_v3","cache_audit_v3"}


def v3_sources(directory):
    users=[];events=[]
    origin=datetime(2026,1,1,tzinfo=timezone.utc)
    def stamp(value):return value.isoformat().replace("+00:00","Z")
    for day in range(4):
        installed=origin+timedelta(days=day)
        for offset in range(8):
            user=f"d{day}u{offset}";session=user+"-s";base=stamp(installed)
            users.append({"app_id":"game","user_id":user,"installed_at":base,"platform":"ios","country":"TW",
                "acquisition_source":"organic","campaign_id":None,"app_version_at_install":"1"})
            events.append({"app_id":"game","user_id":user,"event_id":user+"-session","event_name":"session_start",
                "event_time":base,"available_at":base,"session_id":session,"source_sequence":1,"ad_format":None,
                "revenue_usd":None,"engaged_seconds":None,"level_id":None,"level_index":None,"attempt_id":None,
                "level_mode":None,"difficulty":None,"revive_used":None,"booster_used":None,"app_version":"1"})
            for index in range(1 if offset<4 else 3):
                when=installed+timedelta(hours=1,minutes=index)
                events.append({"app_id":"game","user_id":user,"event_id":f"{user}-ad-{index}","event_name":"ad_impression",
                    "event_time":stamp(when),"available_at":stamp(when),"session_id":session,"source_sequence":2+index,
                    "ad_format":"rewarded","revenue_usd":.01*(index+1)+.001*offset,"engaged_seconds":None,
                    "level_id":None,"level_index":None,"attempt_id":None,"level_mode":None,"difficulty":None,
                    "revive_used":None,"booster_used":None,"app_version":"1"})
    return [write_source(directory,"users",users),write_source(directory,"events",events)]


def create_v3_run(jobdb,storage,directory):
    engine,repo,_=jobdb;directory.mkdir()
    manifest=[]
    for source in v3_sources(directory):
        saved=storage.put_file(storage.new_key("v3-input",source["format"]),source["path"])
        manifest.append({**saved.to_dict(),"role":source["role"],"format":source["format"]})
    with engine.begin() as connection:
        project=repo.create_project(connection,"game","V3 pipeline")
        dataset=repo.create_dataset(connection,project["id"])
        repo.seal_dataset(connection,dataset["id"],manifest,MAPPING,EXPORT)
        return repo.create_run(connection,dataset["id"],CONFIG,str(uuid4()),calculation_version="3.0-casual-game")


def test_v3_real_pg_s3_worker_pipeline_and_readback(api,jobdb,tmp_path,monkeypatch):
    _,engine,storage=api
    run=create_v3_run(jobdb,storage,tmp_path/"source")
    configure_worker(engine,storage,monkeypatch)
    assert Worker(engine,task_timeout=180).run_once()
    with engine.connect() as connection:saved=jobdb[1].get_run(connection,run["id"])
    assert saved["status"]=="succeeded",saved["error"]
    assert EXPECTED_STAGES==set(saved["progress"]["completed_stages"])
    report,_,catalog,files=candidate_context(UploadService(engine,storage),run["id"],1)
    assert report["schema_version"]=="3.0"
    assert catalog["evaluated_count"]==saved["progress"]["counts"]["validation"]>0
    assert len([path for path in files if path.startswith("catalog/details/")])==catalog["evaluated_count"]


def test_v3_same_run_new_attempt_restores_all_outer_stages(api,jobdb,tmp_path):
    _,engine,storage=api
    create_v3_run(jobdb,storage,tmp_path/"source")
    queue=JobQueue(engine,lease_seconds=120);first=queue.claim("v3-one")
    original=run_baseline(engine,storage,first,tmp_path/"work-one")
    queue.fail(first,"SYNTHETIC_RESTART",retryable=True,retry_delay=0)
    second=queue.claim("v3-two");restored=run_baseline(engine,storage,second,tmp_path/"work-two")
    assert set(restored["summary"]["stage_modes"].values())=={"restored"}
    assert restored["artifacts"]==original["artifacts"]
