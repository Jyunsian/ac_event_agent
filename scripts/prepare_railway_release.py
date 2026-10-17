"""Create an allowlisted deployment directory without local data or credentials."""
import argparse,hashlib,json,shutil
from pathlib import Path

def prepare(destination):
    root=Path(__file__).resolve().parents[1];dest=Path(destination).resolve();dest.mkdir(parents=True,exist_ok=False)
    singles=['package.json','package-lock.json','pyproject.toml','uv.lock','alembic.ini','.dockerignore','agent/package.json','agent/tsconfig.json','web/package.json','web/tsconfig.json','web/vite.config.ts','web/index.html','tests/fixtures/hand/expected.json','tests/fixtures/hand/export.json']
    for name in singles:
        target=dest/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,target)
    for name in ['server','migrations','contracts','agent/src','web/src','web/public','deploy']:
        shutil.copytree(root/name,dest/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.env*'))
    manifest={str(p.relative_to(dest)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(dest.rglob('*')) if p.is_file()}
    (dest.parent/(dest.name+'-manifest.json')).write_text(json.dumps(manifest,indent=2)+'\n')
    return {'files':len(manifest),'bytes':sum(p.stat().st_size for p in dest.rglob('*') if p.is_file())}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('destination',type=Path);a=p.parse_args();print(json.dumps(prepare(a.destination)))
