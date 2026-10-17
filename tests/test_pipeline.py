import json
import csv
import io
import hashlib
import multiprocessing as mp
import time
import pytest
from uuid import uuid4
from sqlalchemy import text
from server.db import database_engine

from server.jobs import JobQueue
from server.pipeline import run_baseline
from server.storage import ObjectManifest
from server.worker import Worker
from server.api.main import create_app
from fastapi.testclient import TestClient
from tests.test_ingest import MAPPING, sources
from tests.test_ingest import HAND
from tests.test_jobs import jobdb
from tests.test_quality import EXPORT
from tests.test_search import CONFIG
from tests.test_upload_api import api, begin, dataset, finish, put, request


def configure_worker(engine, storage, monkeypatch):
    credentials = storage.client._request_signer._credentials.get_frozen_credentials()
    for name, value in {"DATABASE_URL": engine.url.render_as_string(hide_password=False),
                        "S3_ENDPOINT_URL": storage.client.meta.endpoint_url, "S3_BUCKET": storage.bucket,
                        "AWS_ACCESS_KEY_ID": credentials.access_key, "AWS_SECRET_ACCESS_KEY": credentials.secret_key}.items():
        monkeypatch.setenv(name, value)


def run_actual_worker(url):
    engine = database_engine(url)
    try:
        Worker(engine, lease_seconds=3, heartbeat_seconds=.3, task_timeout=120).run_once()
    finally:
        engine.dispose()


def create_run(jobdb, storage, directory, extras=None):
    engine, repo, _ = jobdb
    directory.mkdir()
    manifest = []
    for source in sources(directory, extras=extras):
        saved = storage.put_file(storage.new_key("baseline-input", source["format"]), source["path"])
        manifest.append({**saved.to_dict(), "role": source["role"], "format": source["format"]})
    with engine.begin() as c:
        project = repo.create_project(c, "synthetic", "Baseline integration")
        dataset = repo.create_dataset(c, project["id"])
        repo.seal_dataset(c, dataset["id"], manifest, MAPPING, EXPORT)
        return repo.create_run(c, dataset["id"], CONFIG, str(uuid4()))


def test_real_storage_baseline_and_new_attempt_resume(api, jobdb, tmp_path):
    _, engine, storage = api
    create_run(jobdb, storage, tmp_path/"source")
    queue = JobQueue(engine, lease_seconds=120)
    lease = queue.claim("baseline-one")
    result = run_baseline(engine, storage, lease, tmp_path/"work-one")
    assert result["summary"]["analysis_status"] == "analyzed"
    assert set(result["summary"]["stage_modes"].values()) == {"computed"}
    baseline = next(a for a in result["artifacts"] if a["kind"] == "baseline")
    content = json.loads(storage.get_bytes(ObjectManifest(baseline["object_key"], baseline["sha256"], baseline["size_bytes"], "application/json")))
    assert content["synthetic"] and content["finalist_ids"]==[]
    assert len(content['validation'])>10  # Small exploration group does not erase the frozen family.
    assert all(entry['inference']['family_size']==len(content['validation']) for entry in content['validation'])
    assert all(entry["evidence_status"] != "historically_validated" for entry in content["validation"])
    queue.fail(lease, "SYNTHETIC_RESTART", retryable=True, retry_delay=0)
    again = queue.claim("baseline-two")
    restored = run_baseline(engine, storage, again, tmp_path/"work-two")
    assert set(restored["summary"]["stage_modes"].values()) == {"restored"}
    assert restored["artifacts"] == result["artifacts"]


def test_upload_202_disconnect_then_real_worker_publishes(api, jobdb, tmp_path, monkeypatch):
    client, engine, storage = api
    ds = dataset(client)
    source_dir = tmp_path/"sources"
    source_dir.mkdir()
    from pathlib import Path
    for source in sources(source_dir):
        data = Path(source["path"]).read_bytes()
        upload, fingerprint = begin(client, ds["id"], data, role=source["role"])
        put(client, upload, fingerprint, 1, data)
        finish(client, upload, fingerprint)
    mapped = request(client, "PUT", f"/api/datasets/{ds['id']}/mapping", {"mapping": MAPPING, "export_metadata": EXPORT})
    assert mapped.status_code == 200
    queued = request(client, "POST", f"/api/datasets/{ds['id']}/baseline", CONFIG)
    assert queued.status_code == 202
    run_id = queued.json()["run_id"]
    assert client.get(f"/api/runs/{run_id}/reports/1/json").status_code == 409
    client.close()
    configure_worker(engine, storage, monkeypatch)
    assert Worker(engine, task_timeout=120).run_once()
    with TestClient(create_app(engine, storage)) as reopened:
        saved = reopened.get(f"/api/runs/{run_id}")
        assert saved.status_code == 200
        with engine.connect() as c:
            job_diagnostics=c.execute(text('SELECT status,error FROM jobs WHERE run_id=:run'),{'run':run_id}).mappings().all()
        assert saved.json()["status"] == "succeeded", (saved.json().get("error"),job_diagnostics)
        assert saved.json()["progress"]["analysis_status"] == "analyzed"
        quality = reopened.get(f"/api/runs/{run_id}/quality")
        assert quality.status_code == 200
        assert quality.json()["content"]["zero_event_users"] == 1
        exports = {suffix: reopened.get(f"/api/runs/{run_id}/reports/1/{suffix}") for suffix in ("json", "html", "csv")}
        for response in exports.values():
            assert response.status_code == 200
            assert response.headers["etag"] == '"'+hashlib.sha256(response.content).hexdigest()+'"'
            assert response.headers["content-disposition"].startswith("attachment;")
        report = exports["json"].json()
        assert report["synthetic"] and report["summary"]["candidate_count"] == 0
        assert report['summary']['searched_candidate_count']>10
        csv_rows = list(csv.DictReader(io.StringIO(exports["csv"].text)))
        assert len(csv_rows)==1 and csv_rows[0]['record_type']=='limitation'
        from server.analysis.report import candidate_cells, csv_safe, CSV_COLUMNS, CSV_CONTEXT_COLUMNS, csv_context
        for row, candidate in zip(csv_rows, report["candidates"]):
            assert row == dict(zip(['record_type',*CSV_COLUMNS,*CSV_CONTEXT_COLUMNS],
                map(csv_safe,['candidate',*candidate_cells(candidate),*csv_context(report,candidate['event_spec'])])))
            assert candidate["candidate_id"] in exports["html"].text
            assert candidate["metrics"]["groups"]["all"]["users"] == 2
        assert reopened.get(f"/api/runs/{run_id}/reports/2/json").status_code == 409
        assert reopened.get(f"/api/runs/{uuid4()}/reports/1/json").status_code == 404
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM report_versions WHERE run_id=:id"), {"id": run_id}).scalar_one() == 1
            catalog_row=c.execute(text("SELECT object_key,sha256,size_bytes FROM artifacts WHERE run_id=:id AND kind='candidate_catalog'"),{'id':run_id}).mappings().one()
            checkpoint=c.execute(text("SELECT manifest FROM stage_checkpoints WHERE run_id=:id AND stage='report'"),{'id':run_id}).scalar_one()
            details=[entry for entry in checkpoint['files'] if entry['path'].startswith('catalog/details/')]
        catalog=json.loads(storage.get_bytes(ObjectManifest(catalog_row['object_key'],catalog_row['sha256'],catalog_row['size_bytes'],'application/json')))
        assert report['schema_version']=='2.0' and report['catalog']['sha256']==catalog_row['sha256']
        assert len(details)==catalog['evaluated_count']==report['summary']['searched_candidate_count']
        by_path={d['path']:d['object']['sha256'] for d in details}
        assert all(by_path['catalog/details/'+entry['candidate_id']+'.json']==entry['detail_sha256'] for entry in catalog['entries'])
        list_url = f'/api/runs/{run_id}/reports/1/candidates'
        with engine.connect() as connection:
            checkpoints_before = connection.execute(text(
                'SELECT count(*) FROM stage_checkpoints WHERE run_id=:run'), {'run': run_id}).scalar_one()
        collected = []
        for page in range(1, (catalog['evaluated_count']+49)//50+1):
            response = reopened.get(list_url, params={'page': page})
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload['page_size'] == 50 and len(payload['items']) <= 50
            assert payload['filtered_count'] == payload['evaluated_count'] == catalog['evaluated_count']
            collected.extend(payload['items'])
        assert collected == sorted(catalog['entries'], key=lambda item: item['candidate_id'])
        export_url=f'/api/runs/{run_id}/reports/1/candidate-exports'
        complete=reopened.get(export_url+'/json')
        assert complete.status_code==200,complete.text
        exported=complete.json()
        assert exported['entries']==catalog['entries']
        assert len(exported['details'])==catalog['evaluated_count']
        assert exported['export']['export_scope']=='complete'
        assert exported['report']==report
        assert 'search' in exported and 'object_key' not in complete.text
        html_export=reopened.get(export_url+'/html')
        assert html_export.status_code==200,html_export.text
        assert html_export.headers['content-type'].startswith('text/html')
        embedded=json.loads(html_export.text.split('<script id="evidence" type="application/json">')[1].split('</script>')[0])
        for key in exported:
            assert embedded[key]==exported[key],key
        assert set(embedded['names'])=={d['candidate_id'] for d in exported['details']}
        assert "connect-src 'none'" in html_export.text
        import subprocess
        html_path=tmp_path/'candidate-complete.html'
        json_path=tmp_path/'candidate-complete.json'
        html_path.write_bytes(html_export.content)
        json_path.write_bytes(complete.content)
        browser_check=subprocess.run(['node','scripts/verify_candidate_offline.mjs',str(html_path),str(json_path)],
                                     capture_output=True,text=True,timeout=120)
        assert browser_check.returncode==0,browser_check.stdout+browser_check.stderr
        assert json.loads(browser_check.stdout)['checked']==catalog['evaluated_count']
        income=reopened.get(f'/api/runs/{run_id}/reports/1/candidate-revenue-series')
        assert income.status_code==200,income.text
        income=income.json()
        assert income['report_sha256']==exported['export']['report_sha256']
        assert income['catalog_sha256']==exported['export']['catalog_sha256']
        assert income['run_id']==str(run_id) and income['report_version']==1
        expected_income={d['candidate_id']:d for d in exported['details']
                         if d['event_spec']['predicate']['op']=='revenue_sum'}
        assert expected_income, 'Income endpoint must be tested with actual evaluated thresholds'
        seen_income=set()
        from server.analysis.catalog import candidate_summary
        for group in income['groups']:
            assert group['points']==sorted(group['points'],key=lambda p:(p['threshold_usd'],p['candidate_id']))
            for point in group['points']:
                detail=expected_income[point['candidate_id']]
                assert point['candidate_id'] not in seen_income
                seen_income.add(point['candidate_id'])
                spec=detail['event_spec'];summary=candidate_summary(detail)
                assert group['window_hours']==spec['window_hours']
                assert group['ad_format']==spec['predicate'].get('ad_format','all')
                assert point['threshold_usd']==spec['predicate']['threshold']
                assert point['coverage']==summary['coverage']
                assert point['difference_usd']==summary['difference_usd']
                hit,miss=summary['triggered_users'],summary['untriggered_users']
                assert point['sample_size']==(hit+miss if hit is not None and miss is not None else None)
                assert point['evidence_status']==detail['validation']['evidence_status']
                assert point['detail_sha256']==next(e['detail_sha256'] for e in exported['entries'] if e['candidate_id']==point['candidate_id'])
        assert seen_income==set(expected_income)
        search_page=reopened.get(f'/api/runs/{run_id}/reports/1/candidate-search')
        assert search_page.status_code==200,search_page.text
        assert search_page.json()['summary']=={key:value for key,value in exported['search'].items() if key!='pruning'}
        assert search_page.json()['items']==exported['search']['pruning'][:50]
        assert search_page.json()['pruning_count']==len(exported['search']['pruning'])
        assert reopened.get(f'/api/runs/{run_id}/reports/1/candidate-search?page=0').status_code==422
        full_csv=reopened.get(export_url+'/csv')
        assert full_csv.status_code==200
        full_rows=list(csv.DictReader(io.StringIO(full_csv.content.decode('utf-8-sig'))))
        assert len(full_rows)==catalog['evaluated_count']
        for row,detail in zip(full_rows,exported['details']):
            assert row['candidate_id']==detail['candidate_id']
            assert json.loads(row['evidence_json'])==detail
            assert row['report_sha256']==exported['export']['report_sha256']
        filtered=reopened.get(export_url+'/json',params={'scope':'filtered','window_hours':6})
        assert filtered.status_code==200,filtered.text
        expected=[entry for entry in catalog['entries'] if entry['window_hours']==6]
        assert set(entry['candidate_id'] for entry in filtered.json()['entries'])==set(entry['candidate_id'] for entry in expected)
        assert filtered.json()['export']['exported_count']==len(expected)
        assert filtered.json()['export']['evaluated_count']==catalog['evaluated_count']
        filtered_html=reopened.get(export_url+'/html',params={'scope':'filtered','window_hours':6})
        assert filtered_html.status_code==200,filtered_html.text
        embedded_filtered=json.loads(filtered_html.text.split('<script id="evidence" type="application/json">')[1].split('</script>')[0])
        for key in filtered.json():
            assert embedded_filtered[key]==filtered.json()[key],key
        assert reopened.get(export_url+'/csv',params={'window_hours':6}).status_code==422
        empty=reopened.get(export_url+'/csv',params={'scope':'filtered','ad_format':'never-observed'})
        empty_rows=list(csv.DictReader(io.StringIO(empty.content.decode('utf-8-sig'))))
        assert len(empty_rows)==1 and empty_rows[0]['record_type']=='export_metadata'
        assert empty_rows[0]['exported_count']=='0'
        response = reopened.get(list_url, params={'window_hours': 6, 'family': 'atom',
                                                 'sort': 'coverage', 'descending': True})
        assert response.status_code == 200
        assert all(item['window_hours'] == 6 and item['summary']['family'] == 'atom'
                   for item in response.json()['items'])
        assert reopened.get(list_url, params={'page': 0}).status_code == 422
        assert reopened.get(list_url, params={'sort': 'sql'}).status_code == 422
        assert reopened.get(list_url, params={'ad_format': 'never-observed'}).json()['filtered_count'] == 0
        with engine.connect() as connection:
            assert connection.execute(text('SELECT count(*) FROM stage_checkpoints WHERE run_id=:run'),
                                      {'run': run_id}).scalar_one() == checkpoints_before
        entry = catalog['entries'][0]
        detail_url = f"/api/runs/{run_id}/reports/1/candidates/{entry['candidate_id']}"
        response = reopened.get(detail_url)
        assert response.status_code == 200, response.text
        evidence = response.json()
        assert evidence['sha256'] == entry['detail_sha256']
        assert evidence['report_sha256'] == hashlib.sha256(exports['json'].content).hexdigest()
        assert evidence['content']['candidate_id'] == entry['candidate_id']
        assert evidence['content']['validation']['evidence_status'] == entry['evidence_status']
        from server.analysis.catalog import candidate_summary
        assert candidate_summary(evidence['content']) == entry['summary']
        assert reopened.get(detail_url.replace(entry['candidate_id'], 'f'*64)).status_code == 404
        assert reopened.get(detail_url.replace(entry['candidate_id'], 'invalid')).status_code == 422
        assert reopened.get(detail_url.replace('/reports/1/', '/reports/2/')).status_code == 409
        assert reopened.get(f"/api/runs/{run_id}/reports/1/json").content == exports['json'].content
        altered = json.loads(json.dumps(checkpoint))
        next(item for item in altered['files'] if item['path'] ==
             f"catalog/details/{entry['candidate_id']}.json")['object']['sha256'] = '0'*64
        from sqlalchemy.exc import ProgrammingError
        with pytest.raises(ProgrammingError, match='Stage checkpoints are immutable'):
            with engine.begin() as connection:
                connection.execute(text("UPDATE stage_checkpoints SET manifest=CAST(:manifest AS jsonb) "
                                        "WHERE run_id=:run AND stage='report'"),
                                   {'run': run_id, 'manifest': json.dumps(altered)})
        assert reopened.get(detail_url).status_code == 200


def test_unusable_exploration_revenue_produces_diagnostic_not_recommendations(api, jobdb, tmp_path):
    _, engine, storage = api
    missing = json.loads((HAND/"edge_cases.json").read_text())[0]["event"]
    create_run(jobdb, storage, tmp_path/"source", extras=[missing])
    lease = JobQueue(engine).claim("diagnostic-baseline")
    result = run_baseline(engine, storage, lease, tmp_path/"work")
    assert result["summary"]["analysis_status"] == "diagnostic_only"
    assert "MISSING_AD_REVENUE" in result["summary"]["reasons"]
    baseline = next(a for a in result["artifacts"] if a["kind"] == "baseline")
    saved = json.loads(storage.get_bytes(ObjectManifest(baseline["object_key"], baseline["sha256"], baseline["size_bytes"], "application/json")))
    assert saved["finalist_ids"] == [] and saved["validation"] == []


def test_killed_mid_pipeline_resumes_without_partial_publication(api, jobdb, tmp_path, monkeypatch):
    _, engine, storage = api
    run = create_run(jobdb, storage, tmp_path/"source")
    configure_worker(engine, storage, monkeypatch)
    process = mp.get_context("spawn").Process(target=run_actual_worker,
        args=(engine.url.render_as_string(hide_password=False),))
    process.start()
    try:
        deadline = time.monotonic()+30
        while time.monotonic()<deadline:
            with engine.connect() as c:
                count = c.execute(text("SELECT count(*) FROM stage_checkpoints WHERE run_id=:id"), {"id": run["id"]}).scalar_one()
            if count:
                break
            assert process.is_alive(), "Worker exited before first checkpoint"
            time.sleep(.02)
        else:
            raise AssertionError("No checkpoint observed from live Worker")
        process.kill()
        process.join(5)
        assert process.exitcode is not None and process.exitcode != 0
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM artifacts WHERE run_id=:id"), {"id": run["id"]}).scalar_one() == 0
            assert c.execute(text("SELECT count(*) FROM report_versions WHERE run_id=:id"), {"id": run["id"]}).scalar_one() == 0
            assert c.execute(text("SELECT status FROM runs WHERE id=:id"), {"id": run["id"]}).scalar_one() == "running"
        # Observe this exact persisted lease expiring; do not fabricate a retry state.
        deadline = time.monotonic()+6
        while time.monotonic()<deadline:
            with engine.connect() as c:
                expired = c.execute(text("SELECT lease_until<=clock_timestamp() FROM jobs WHERE run_id=:id"), {"id": run["id"]}).scalar_one()
            if expired:
                break
            time.sleep(.05)
        else:
            raise AssertionError("Killed Worker's lease did not expire")
        assert Worker(engine, lease_seconds=3, heartbeat_seconds=.3, task_timeout=120).run_once()
        with engine.connect() as c:
            saved = c.execute(text("SELECT status,progress FROM runs WHERE id=:id"), {"id": run["id"]}).mappings().one()
            assert saved["status"] == "succeeded"
            assert saved["progress"]["stage_modes"]["normalized"] == "restored"
            assert "computed" in saved["progress"]["stage_modes"].values()
            assert c.execute(text("SELECT attempt_number FROM jobs WHERE run_id=:id"), {"id": run["id"]}).scalar_one() == 2
    finally:
        if process.is_alive():
            process.kill()
        process.join(5)
        process.close()
