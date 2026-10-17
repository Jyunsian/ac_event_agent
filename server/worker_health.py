"""Local supervisor/DB-contact pulse, not proof of a successful analysis or S3 readiness."""
import json
import os
from pathlib import Path
import tempfile
import time


def pulse():
    configured=os.environ.get('WORKER_HEALTH_FILE')
    if not configured:return
    path=Path(configured)
    temporary=None
    try:
        descriptor,temporary=tempfile.mkstemp(prefix='.worker-health-',dir=path.parent)
        with os.fdopen(descriptor,'w') as stream:
            json.dump({'pid':os.getpid(),'monotonic':time.monotonic()},stream)
        os.replace(temporary,path)
    except OSError:
        # Failure to publish must result in stale/unhealthy, not a fabricated fresh pulse.
        pass
    finally:
        if temporary:
            try:Path(temporary).unlink(missing_ok=True)
            except OSError:pass


def healthy(path,max_age=45):
    try:
        with Path(path).open() as stream:
            raw=stream.read(1025)
        if len(raw)>1024:return False
        data=json.loads(raw)
        if type(data['pid']) is not int or data['pid']<=0:return False
        if not 0<=time.monotonic()-data['monotonic']<=max_age:return False
        os.kill(data['pid'],0)
        return True
    except (OSError,ValueError,TypeError,KeyError):return False


if __name__=='__main__':
    raise SystemExit(0 if healthy(os.environ.get('WORKER_HEALTH_FILE','/tmp/worker-health.json')) else 1)
