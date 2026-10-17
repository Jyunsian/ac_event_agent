import json
import pytest
from server.analysis.finding_recheck import prepare_fixed_recheck
from server.analysis.freeze import load_frozen
from server.analysis.search import generate_candidates
from server.analysis.ingest import IngestError
from tests.test_search import prepare,CONFIG


def test_fixed_old_conditions_never_rerank_on_new_outcomes(tmp_path,monkeypatch):
    old=tmp_path/'old';new=tmp_path/'new'
    prepare(old);prepare(new,holdout_revenue=999)
    original=generate_candidates(old/'exploration/features',old/'targets',CONFIG,tmp_path/'original-search')
    candidates=original['candidates'][:3]
    def forbidden(*args,**kwargs):raise AssertionError('Fixed freeze must not query outcome rows')
    monkeypatch.setattr('duckdb.connect',forbidden)
    for root,label in ((old,'first-freeze'),(new,'second-freeze')):
        result=prepare_fixed_recheck(root/'exploration/features',root/'targets',candidates,CONFIG,tmp_path/label)
        frozen=load_frozen(tmp_path/label/'selection/freeze',result['frozen']['sha256'])
        assert frozen['candidates']==sorted(candidates,key=lambda r:r['candidate_id'])
        assert result['ranking']==[] and result['selected_ids']==sorted(r['candidate_id'] for r in candidates)
        assert frozen['rules']['min_group_users']==CONFIG['min_group_users']
        manifest=json.loads((tmp_path/label/'search/manifest.json').read_text())
        assert manifest['thresholds']==manifest['pruning']==[] and manifest['enumerated']==0
    with pytest.raises(IngestError,match='DUPLICATE_RECHECK_CANDIDATE'):
        prepare_fixed_recheck(old/'exploration/features',old/'targets',candidates[:1]*2,CONFIG,tmp_path/'duplicate')
    with pytest.raises(FileExistsError):
        prepare_fixed_recheck(old/'exploration/features',old/'targets',candidates,CONFIG,tmp_path/'first-freeze')
