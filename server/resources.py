"""Server-owned analysis limits; never supplied by model tool arguments."""
from dataclasses import asdict,dataclass
from contextlib import contextmanager
import os
from pathlib import Path
import resource
import shutil
import sys
import tempfile
import threading
import time


class ResourceLimitError(Exception):
    pass


RESOURCE_EXIT_CODES={71:'MEMORY_LIMIT',72:'DISK_RESERVE_LOW',73:'WORKDIR_LIMIT',74:'CPU_LIMIT',75:'RESOURCE_MONITOR_FAILED'}


def setting(name,default,minimum=1,maximum=2**63-1):
    try:value=int(os.environ.get(name,str(default)))
    except ValueError:raise ResourceLimitError('RESOURCE_CONFIG_INVALID') from None
    if not minimum<=value<=maximum:raise ResourceLimitError('RESOURCE_CONFIG_INVALID')
    return value


@dataclass(frozen=True)
class Limits:
    rss_mb:int
    duckdb_mb:int
    threads:int
    disk_reserve_bytes:int
    workdir_bytes:int
    timeout_seconds:int
    cpu_seconds:int
    work_root:Path

    @classmethod
    def from_environment(cls):
        rss=setting('WORKER_RSS_MB',1536,64,1048576)
        return cls(rss,setting('DUCKDB_MEMORY_MB',256,16,rss),setting('WORKER_THREADS',2,1,64),
            setting('DISK_RESERVE_BYTES',2*1024**3),setting('MAX_WORKDIR_BYTES',4*1024**3),
            setting('WORKER_TASK_TIMEOUT_SECONDS',900),setting('WORKER_CPU_SECONDS',600),
            Path(os.environ.get('WORKER_WORK_ROOT',str(Path(tempfile.gettempdir())/'ac-event-work'))).absolute())

    def describe(self):
        return {**asdict(self),'work_root':str(self.work_root)}

    def preflight(self,input_bytes,path):
        if type(input_bytes) is not int or input_bytes<0:raise ResourceLimitError('RESOURCE_INPUT_INVALID')
        existing=Path(path).absolute()
        while not existing.exists():existing=existing.parent
        free=shutil.disk_usage(existing).free
        # Conservative initial planning estimate, NOT an empirically proven upper bound.
        # Raw download, canonical tables, checkpoints and scratch can coexist. Actual watchdog
        # and measurements must also bound execution; this estimate alone is not a capacity claim.
        estimated=input_bytes*12
        if estimated>self.workdir_bytes:raise ResourceLimitError('WORKDIR_PREFLIGHT_LIMIT')
        if free<self.disk_reserve_bytes+estimated:raise ResourceLimitError('DISK_PREFLIGHT_LIMIT')
        return {'input_bytes':input_bytes,'estimated_work_bytes':estimated,'disk_free_bytes':free,
                'disk_reserve_bytes':self.disk_reserve_bytes,'estimate_policy':'conservative_input_times_12_not_capacity_proof'}


def duck_config(config=None):
    limits=Limits.from_environment()
    return {**(config or {}),'memory_limit':f'{limits.duckdb_mb}MB','threads':limits.threads,
            'autoload_known_extensions':False,'autoinstall_known_extensions':False}


def directory_bytes(directory):
    size=0
    for root,dirs,files in os.walk(directory,followlinks=False):
        for name in files:
            try:size+=os.stat(Path(root)/name,follow_symlinks=False).st_size
            except FileNotFoundError:pass  # Atomic stage publication may rename during sampling.
    return size


@contextmanager
def monitor(limits,directory):
    """Compute-child-only watchdog. Samples RSS/free disk every .25s, workspace every second.

    os._exit stops a stuck native computation; the supervising Worker maps dedicated exit
    codes to a terminal failure. This is sampled protection, not an OS cgroup hard quota.
    """
    stopped=threading.Event();start=time.monotonic()
    first=resource.getrusage(resource.RUSAGE_SELF);cpu_start=first.ru_utime+first.ru_stime
    observed={'peak_rss_bytes':0,'peak_workdir_bytes':0,'cpu_seconds':0.0,'wall_seconds':0.0}
    last_scan=0.0
    def sample(force=False):
        nonlocal last_scan
        now=time.monotonic();usage=resource.getrusage(resource.RUSAGE_SELF)
        rss=int(usage.ru_maxrss)*(1 if sys.platform=='darwin' else 1024)
        cpu=usage.ru_utime+usage.ru_stime-cpu_start
        observed.update(peak_rss_bytes=max(observed['peak_rss_bytes'],rss),cpu_seconds=cpu,wall_seconds=now-start)
        if rss>limits.rss_mb*1024**2:return 71
        if shutil.disk_usage(directory).free<limits.disk_reserve_bytes:return 72
        if cpu>limits.cpu_seconds:return 74
        if force or now-last_scan>=1:
            observed['peak_workdir_bytes']=max(observed['peak_workdir_bytes'],directory_bytes(directory));last_scan=now
            if observed['peak_workdir_bytes']>limits.workdir_bytes:return 73
        return None
    def guard():
        while not stopped.wait(.25):
            try:code=sample()
            except Exception:code=75
            if code:os._exit(code)
    code=sample(True)
    if code:raise ResourceLimitError(RESOURCE_EXIT_CODES[code])
    thread=threading.Thread(target=guard,daemon=True);thread.start()
    try:
        yield observed
        code=sample(True)
        if code:raise ResourceLimitError(RESOURCE_EXIT_CODES[code])
    finally:
        stopped.set();thread.join(2)
