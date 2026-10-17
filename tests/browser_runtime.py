"""Isolated real HTTP API/Vite for browser acceptance; never routes fake success responses."""
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import urllib.request
import uvicorn
from server.api.main import create_app


@contextmanager
def live_web(engine, storage, directory, include_api=False):
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
    endpoint=f'http://127.0.0.1:{listener.getsockname()[1]}'
    server=uvicorn.Server(uvicorn.Config(create_app(engine,storage),log_level='warning',access_log=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    root=Path(__file__).resolve().parents[1]
    with (directory/'vite.log').open('w') as log:
        process=subprocess.Popen(['node',str(root/'node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port',str(port),'--strictPort'],
            cwd=root/'web',env={**os.environ,'API_PROXY_TARGET':endpoint},stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                assert process.poll() is None
                try:
                    with urllib.request.urlopen(url+'/api/health',timeout=.5) as response:
                        if response.status==200:break
                except OSError:pass
                time.sleep(.1)
            else:raise AssertionError('Isolated HTTP services failed startup')
            yield (url,endpoint) if include_api else url
        finally:
            process.terminate();process.wait(timeout=10)
            server.should_exit=True;thread.join(10);listener.close()
