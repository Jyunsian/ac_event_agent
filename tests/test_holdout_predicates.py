import json
import shutil
import pytest
from server.analysis.connection import connect
from server.analysis.ingest import IngestError
from server.analysis.predicates import evaluate_candidates
from server.analysis.search import generate_candidates
from tests.test_search import CONFIG,prepare


def test_scoped_triggers_equal_full_evaluation_filtered_to_mature_holdout(tmp_path):
    root=tmp_path/'case';prepare(root)
    search=generate_candidates(root/'exploration/features',root/'targets',
                               {**CONFIG,'max_candidates':40},root/'search')
    candidates=search['candidates']
    assert any(c['predicate']['op']=='sequence' for c in candidates)
    full=evaluate_candidates(root/'normalized',root/'features',candidates,root/'full')
    scoped=evaluate_candidates(root/'normalized',root/'features',candidates,root/'scoped',
                               holdout_targets=root/'targets')
    assert scoped['candidates']==full['candidates']
    assert scoped['evaluation_scope']['split']=='holdout'
    with connect() as c:
        for name,path in [('full_triggers',root/'full/triggers.parquet'),('scoped',root/'scoped/triggers.parquet'),
                          ('targets',root/'targets/targets.parquet')]:
            c.read_parquet(str(path)).create_view(name)
        c.execute("CREATE VIEW expected AS SELECT f.* FROM full_triggers f JOIN targets t USING(app_id,user_id) WHERE t.split='holdout' AND t.is_mature")
        assert c.execute('SELECT count(*) FROM scoped').fetchone()[0]>0
        assert c.execute('SELECT count(*) FROM full_triggers').fetchone()[0]>c.execute('SELECT count(*) FROM scoped').fetchone()[0]
        assert c.execute('SELECT count(*) FROM (SELECT * FROM scoped EXCEPT ALL SELECT * FROM expected)').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM (SELECT * FROM expected EXCEPT ALL SELECT * FROM scoped)').fetchone()[0]==0
    foreign=root/'foreign-targets';shutil.copytree(root/'targets',foreign)
    manifest=json.loads((foreign/'manifest.json').read_text())
    manifest['source_manifest_sha256']='0'*64
    (foreign/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(IngestError,match='PREDICATE_SCOPE_SOURCE_MISMATCH'):
        evaluate_candidates(root/'normalized',root/'features',candidates,root/'bad',holdout_targets=foreign)
    assert not (root/'bad').exists()
