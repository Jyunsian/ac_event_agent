"""Run browser filtering between real PG snapshots without logging credentials."""
import json
import os
import subprocess
from pathlib import Path
from sqlalchemy import text
from server.db import database_engine


def main():
    engine=database_engine(os.environ['DATABASE_URL'])
    def snapshot():
        with engine.connect() as connection:
            return {table:[str(value) for value in connection.execute(text(f'SELECT id FROM {table} ORDER BY id')).scalars()]
                    for table in ('runs','jobs')}
    before=snapshot()
    result=subprocess.run(['node','scripts/candidate_filter_live_qa.mjs'],capture_output=True,text=True,timeout=180)
    after=snapshot()
    evidence={'before':before,'after':after,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    Path('evidence/CV04-readonly-db.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
    assert result.returncode==0,result.stdout+result.stderr
    assert before==after,'Browser reading created runs/jobs'
    print(json.dumps({'runs':len(after['runs']),'jobs':len(after['jobs']),'unchanged':True}))
    engine.dispose()


if __name__=='__main__':main()
