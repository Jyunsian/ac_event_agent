"""Upload preserved synthetic hand fixtures to a NEW persistent V2 dataset."""
import json
import csv
import io
import sys
from pathlib import Path
import httpx
from tests.test_upload_api import request, begin, put, finish
from tests.test_ingest import MAPPING


def main():
    base='http://127.0.0.1:8096'
    with httpx.Client(base_url=base,timeout=30) as client:
        project=request(client,'POST','/api/projects',{'app_id':'synthetic','name':'Candidate V2 UI 本地驗收'})
        project.raise_for_status()
        dataset=request(client,'POST','/api/datasets',{'project_id':project.json()['id']})
        dataset.raise_for_status();identity=dataset.json()['id']
        root=Path('.runtime/local-workspace-flow-8ba3cf75/inputs')
        positive='--positive' in sys.argv
        sources=[]
        if positive:
            users=[];events=[]
            for day in range(1,5):
                for i in range(100):
                    uid=f'{day}-{i}';hour=1 if i<50 else 4
                    users.append(dict(app_id='synthetic',user_id=uid,platform='android',installed_at=f'2026-01-{day:02}T00:00:00Z',acquisition_source='A' if i%2 else 'B'))
                    events.append(dict(app_id='synthetic',user_id=uid,event_id=uid,event_name='ad_impression',event_time=f'2026-01-{day:02}T0{hour}:00:00Z',available_at=f'2026-01-{day:02}T0{hour}:00:00Z',ad_format='rewarded',revenue_usd=(2 if i<50 else .1)+(i%7)*.001))
            for role,rows in [('users',users),('events',events)]:
                stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
                sources.append((role,stream.getvalue().encode()))
        else:
            sources=[(role,(root/name).read_bytes()) for role,name in [('users','users.csv'),('events','eventsa.csv'),('events','eventsb.csv')]]
        for role,data in sources:
            upload,fingerprint=begin(client,identity,data,role=role)
            put(client,upload,fingerprint,1,data);finish(client,upload,fingerprint)
        export=json.loads(Path('tests/fixtures/hand/export.json').read_text())
        if positive:export={**export,'complete_through':'2026-01-20T00:00:00Z','exported_at':'2026-01-21T00:00:00Z'}
        mapping={role:{key:value for key,value in MAPPING[role].items() if key in rows[0]} for role,rows in [('users',users),('events',events)]} if positive else MAPPING
        mapped=request(client,'PUT',f'/api/datasets/{identity}/mapping',{'mapping':mapping,'export_metadata':export})
        mapped.raise_for_status()
        config=json.loads(Path('contracts/defaults.json').read_text())
        result=request(client,'POST',f'/api/datasets/{identity}/baseline',config)
        result.raise_for_status();print(json.dumps({'dataset_id':identity,**result.json()}))


if __name__=='__main__':main()
