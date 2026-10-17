"""Read worker liveness/configuration without sending secrets to the browser."""
import json
import os
from urllib.request import urlopen


def agent_status():
    endpoint=os.environ.get('AGENT_HEALTH_URL','http://127.0.0.1:8081/health')
    try:
        with urlopen(endpoint,timeout=1) as response:
            body=response.read(8193)
            if len(body)>8192:raise ValueError('oversized health')
            data=json.loads(body)
        if data.get('service')!='agent' or data.get('status')!='alive':raise ValueError('wrong service')
        provider=data.get('provider',{})
        if provider.get('available') is not True:
            return {'available':False,'code':'OPENROUTER_NOT_CONFIGURED'}
        if data.get('workerConnected') is not True:
            return {'available':False,'code':'AGENT_WORKER_DISCONNECTED'}
        return {'available':True,'code':'CONFIGURED_NOT_VERIFIED'}
    except Exception:
        # Health payloads, URLs and network exception bodies are server-private.
        return {'available':False,'code':'AGENT_WORKER_UNAVAILABLE'}
