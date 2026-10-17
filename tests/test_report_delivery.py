import csv
import json
import subprocess
import tempfile
from pathlib import Path
import pytest
from server.agent_queue import AgentQueue
from server.worker import Worker
from tests.test_jobs import jobdb
from tests.test_upload_api import api
from tests.test_pipeline import create_run,configure_worker
from tests.browser_runtime import live_web


@pytest.mark.parametrize('kind',['rerun','segment','positive_segment'])
def test_selected_parent_child_download_then_api_offline_reopen(api,jobdb,tmp_path,monkeypatch,kind):
    client,engine,storage=api
    from tests.test_ingest import HAND,write_source
    def private_sources(directory,extras=None):
        users=json.loads((HAND/'users.json').read_text())
        events=json.loads((HAND/'events.json').read_text())+(extras or [])
        if kind=='positive_segment':
            users=[];events=[]
            for day in range(1,5):
                for i in range(100):
                    identity=f'{day}-{i}';hour=1 if i<50 else 4
                    users.append(dict(app_id='synthetic',user_id=identity,platform='android',country='US',
                                      installed_at=f'2026-01-{day:02}T00:00:00Z',acquisition_source='A' if i%2 else 'B'))
                    events.append(dict(app_id='synthetic',user_id=identity,event_id=identity,event_name='ad_impression',
                                       event_time=f'2026-01-{day:02}T0{hour}:00:00Z',available_at=f'2026-01-{day:02}T0{hour}:00:00Z',
                                       ad_format='rewarded',revenue_usd=(2 if i<50 else .1)+(i%7)*.001))
        for row in users:row['user_id']='private-delivery-user-'+row['user_id']
        for row in events:
            row['user_id']='private-delivery-user-'+row['user_id']
            row['event_id']='private-delivery-event-'+row['event_id']
        return [write_source(directory,'users',users),write_source(directory,'events',events)]
    monkeypatch.setattr('tests.test_pipeline.sources',private_sources)
    if kind=='positive_segment':
        from tests.test_quality import EXPORT
        monkeypatch.setattr('tests.test_pipeline.EXPORT',{**EXPORT,'complete_through':'2026-01-20T00:00:00Z','exported_at':'2026-01-21T00:00:00Z'})
        monkeypatch.setattr('tests.test_pipeline.CONFIG',{**json.loads(Path('contracts/defaults.json').read_text()),'analysis_version':'2.0'})
    parent=create_run(jobdb,storage,tmp_path/'source');rid=str(parent['id'])
    configure_worker(engine,storage,monkeypatch);assert Worker(engine,task_timeout=120).run_once()
    original=client.get(f'/api/runs/{rid}/reports/1/json').content
    if kind=='positive_segment':
        assert json.loads(original)['candidates'], 'Positive parent must exercise nonempty delivery'
    cid=client.post(f'/api/runs/{rid}/conversations',headers={'Idempotency-Key':'delivery'}).json()['id']
    tid=client.post(f'/api/conversations/{cid}/messages',headers={'Idempotency-Key':'q'},
        json={'content':'合成客戶交付驗收','selected_run_id':rid}).json()['turn_id']
    claim=AgentQueue(engine).claim('delivery')
    monkeypatch.setenv('AGENT_INTERNAL_TOKEN','synthetic-delivery-token')
    tool='rerun_analysis' if kind=='rerun' else 'analyze_segment'
    arguments={'windows_hours':[3]} if kind=='rerun' else {'field':'country','value':'US'}
    created=client.post('/internal/tools/'+tool,headers={'Authorization':'Bearer synthetic-delivery-token'},json={
        'turn_id':tid,'parent_run_id':rid,'worker_id':claim['worker_id'],'fence':claim['fence'],
        'tool_call_id':'delivery-branch','arguments':arguments})
    assert created.status_code==200,created.text
    child=created.json()['child_run_id'];assert Worker(engine,task_timeout=120).run_once()
    assert client.get(f'/api/runs/{child}/reports/1/json').status_code==200
    if kind=='positive_segment':
        segment_report=client.get(f'/api/runs/{child}/reports/1/json').json()
        assert segment_report['summary']['segment']['event_specs']
        assert segment_report['summary']['segment']['candidates'], 'Segment UI must exercise actual candidate rows'
    root=Path(tempfile.mkdtemp(prefix='report-delivery-',dir=Path('.runtime').resolve()))
    with live_web(engine,storage,root) as base:
        for run in [rid,child]:
            checked=subprocess.run(['node','scripts/offline_report_qa.cjs','download',base,run,str(root/run)],capture_output=True,text=True,timeout=30)
            assert checked.returncode==0,checked.stdout+checked.stderr
    # API and Vite are now stopped. A separate offline browser opens only the downloaded files.
    for run in [rid,child]:
        checked=subprocess.run(['node','scripts/offline_report_qa.cjs','offline','unused',run,str(root/run)],capture_output=True,text=True,timeout=30)
        assert checked.returncode==0,checked.stdout+checked.stderr
        report=json.loads((root/run/'report.json').read_text())
        with (root/run/'report.csv').open() as stream:rows=list(csv.DictReader(stream))
        assert rows and all(row['run_id']==run for row in rows)
        for row in rows:
            assert json.loads(row['data_scope_json'])==report['summary']['data_scope']
            if row['record_type']=='candidate':
                segment=report['summary'].get('segment')
                if segment:
                    candidate=next(c for c in segment['event_specs'] if c['candidate_id']==row['candidate_id'])
                    assert row['evidence_status']=='exploratory'
                else:
                    candidate=next(c for c in report['candidates'] if c['candidate_id']==row['candidate_id'])
                    assert row['evidence_status']==candidate['evidence_status']
                assert json.loads(row['event_spec_json'])==candidate['event_spec']
        def no_identifiers(value):
            if isinstance(value,dict):
                assert not set(value)&{'user_id','event_id','object_key','source_path'}
                for child_value in value.values():no_identifiers(child_value)
            elif isinstance(value,list):
                for child_value in value:no_identifiers(child_value)
        no_identifiers(report)
        for suffix in ['json','html','csv']:
            content=(root/run/f'report.{suffix}').read_text()
            assert 'private-delivery-user-' not in content and 'private-delivery-event-' not in content
        assert 'X-Amz-Signature' not in (root/run/'report.html').read_text()
    assert (root/rid/'report.json').read_bytes()==original
    assert client.get(f'/api/runs/{rid}/reports/1/json').content==original
    print(f'Offline report evidence: {root}')
