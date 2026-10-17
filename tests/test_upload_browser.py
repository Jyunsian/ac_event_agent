import json
import os
from pathlib import Path
import socket
import shutil
import tempfile
import subprocess
import threading
import time
import urllib.request

import uvicorn
from sqlalchemy import text
from server.api.main import create_app
from tests.test_ingest import sources
from tests.test_jobs import jobdb
from tests.test_upload_api import api


def test_real_browser_upload_resume_mapping_and_queue(api, jobdb, tmp_path):
    _, engine, storage = api
    files = sources(tmp_path)
    events = [Path(f['path']) for f in files if f['role']=='events']
    # Real multipart bytes: repeat a valid synthetic event row beyond 5 MiB.
    first = events[0].read_bytes()
    repeat = first.splitlines(keepends=True)[1]
    with events[0].open('ab') as stream:
        for _ in range((6*1024**2)//len(repeat)):
            stream.write(repeat)
    manifest = tmp_path/'browser-input.json'
    manifest.write_text(json.dumps({'users':str(next(f['path'] for f in files if f['role']=='users')),
                                    'events':list(map(str,events))}))
    listener = socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
    api_url = f'http://127.0.0.1:{listener.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(create_app(engine,storage,part_size=5*1024**2),log_level='warning',access_log=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    with socket.socket() as port_socket:
        port_socket.bind(('127.0.0.1',0));port=port_socket.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    project=Path(__file__).resolve().parents[1]
    with (tmp_path/'vite.log').open('w') as log:
        vite=subprocess.Popen(['node',str(project/'node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port',str(port),'--strictPort'],
            cwd=project/'web',env={**os.environ,'API_PROXY_TARGET':api_url},stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                assert vite.poll() is None
                try:
                    with urllib.request.urlopen(url+'/api/health',timeout=.5) as response:
                        if response.status==200:break
                except OSError:pass
                time.sleep(.1)
            else:raise AssertionError('Isolated Vite/API did not become ready')
            result=subprocess.run(['node','scripts/upload_browser_qa.cjs',url,str(manifest),str(tmp_path/'visual')],cwd=project,
                capture_output=True,text=True,timeout=120)
            assert result.returncode==0,result.stdout+result.stderr
            evidence=json.loads((tmp_path/'visual/checks.json').read_text())
            with engine.connect() as c:
                assert c.execute(text('SELECT count(*) FROM runs WHERE dataset_id=:id AND status=\'queued\''),{'id':evidence['datasetId']}).scalar_one()==1
            assert len(evidence['storageResponses'])==4  # users + two event parts + second event file
            retained=Path(tempfile.mkdtemp(prefix='upload-ui-',dir=project/'.runtime'))
            shutil.copytree(tmp_path/'visual',retained/'visual')
            print(f'Browser evidence retained: {retained}')
        finally:
            vite.terminate();vite.wait(timeout=10)
            server.should_exit=True;thread.join(10);listener.close()
