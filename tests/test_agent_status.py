"""Real HTTP health boundary; no model/provider calls."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import os
import socket
import subprocess
import time
from fastapi.testclient import TestClient
from server.api.main import create_app
from server.agent_status import agent_status


def test_worker_status_is_bounded_and_fail_closed(monkeypatch):
    payload={'service':'agent','status':'alive','provider':{'available':False},'workerConnected':False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps(payload).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv('AGENT_HEALTH_URL',f'http://127.0.0.1:{server.server_port}/health')
    try:
        assert agent_status()=={'available':False,'code':'OPENROUTER_NOT_CONFIGURED'}
        payload['provider']['available']=True
        assert agent_status()=={'available':False,'code':'AGENT_WORKER_DISCONNECTED'}
        payload['workerConnected']=True;payload['private_sentinel']='must not leave server'
        assert agent_status()=={'available':True,'code':'CONFIGURED_NOT_VERIFIED'}
        payload['private_sentinel']='x'*8193
        assert agent_status()=={'available':False,'code':'AGENT_WORKER_UNAVAILABLE'}
    finally:
        server.shutdown();thread.join(5);server.server_close()
    assert agent_status()=={'available':False,'code':'AGENT_WORKER_UNAVAILABLE'}


def test_actual_node_without_model_is_unavailable_and_stops(monkeypatch):
    subprocess.run(['npm','run','build','--workspace','agent'],check=True,capture_output=True,timeout=30)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    monkeypatch.setenv('AGENT_HEALTH_URL',f'http://127.0.0.1:{port}/health')
    process=subprocess.Popen(['node','agent/dist/index.js'],env={**os.environ,'AGENT_PORT':str(port),
        'OPENROUTER_API_KEY':'','OPENROUTER_MODEL':'','AGENT_INTERNAL_TOKEN':'','AGENT_API_BASE_URL':''},
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+5
        with TestClient(create_app()) as client:
            while time.monotonic()<deadline:
                assert process.poll() is None
                result=client.get('/api/agent/status')
                if result.json()['code']=='OPENROUTER_NOT_CONFIGURED':break
                time.sleep(.05)
            assert result.status_code==200
            assert result.json()=={'available':False,'code':'OPENROUTER_NOT_CONFIGURED'}
    finally:
        process.terminate();process.wait(timeout=5)
    assert process.returncode==0
