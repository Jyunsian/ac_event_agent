from server.analysis.finalists import select_and_freeze
from server.analysis.predicates import evaluate_candidates
from server.analysis.search import generate_candidates
from server.analysis.validation import validate_frozen
from tests.test_search import CONFIG, prepare
import pytest


@pytest.mark.parametrize('corruption,code',[
    ('duplicate','DUPLICATE_CANDIDATE_TRIGGER'),('unknown','FINALIST_UNKNOWN_CANDIDATE')])
def test_bounded_selection_rejects_corrupt_trigger_membership(tmp_path,corruption,code):
    import json
    from server.analysis.connection import connect
    from server.analysis.ingest import IngestError,file_hash
    root=tmp_path/'case';prepare(root)
    search=generate_candidates(root/'exploration/features',root/'targets',
                               {**CONFIG,'max_candidates':10},root/'search')
    trigger_dir=root/'triggers'
    manifest=evaluate_candidates(root/'exploration/normalized',root/'exploration/features',
                                 search['candidates'],trigger_dir)
    path=trigger_dir/'triggers.parquet'
    replacement=trigger_dir/'corrupt.parquet'
    with connect() as c:
        c.read_parquet(str(path)).create_view('original')
        assert c.execute('SELECT count(*) FROM original').fetchone()[0]>0
        appended=('SELECT * FROM original LIMIT 1' if corruption=='duplicate' else
                  "SELECT 'foreign-candidate' candidate_id,app_id,user_id,triggered_at FROM original LIMIT 1")
        c.execute('COPY (SELECT * FROM original UNION ALL ('+appended+')) TO ? (FORMAT PARQUET)',[str(replacement)])
    record=manifest['artifacts'][0]
    record.update(path=replacement.name,sha256=file_hash(replacement),
                  size_bytes=replacement.stat().st_size,rows=record['rows']+1)
    (trigger_dir/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(IngestError,match=code):
        select_and_freeze(root/'search',trigger_dir,root/'targets',root/'selection')
    assert not (root/'selection/manifest.json').exists()


def test_search_evaluate_all_families_select_freeze_and_validate(tmp_path,monkeypatch):
    import server.analysis.finalists as finalist_module
    original_groups=finalist_module._descriptive_groups
    calls=[]
    def observed(c):
        calls.append(1)
        return original_groups(c)
    monkeypatch.setattr(finalist_module,'_descriptive_groups',observed)
    root = tmp_path/"case"
    prepare(root)
    search = generate_candidates(root/"exploration/features", root/"targets", CONFIG, root/"search")
    assert {p["predicate"]["op"] for p in search["candidates"]} >= {"count", "sequence"}
    evaluate_candidates(root/"exploration/normalized", root/"exploration/features", search["candidates"], root/"exploration_triggers")
    result = select_and_freeze(root/"search", root/"exploration_triggers", root/"targets", root/"selection")
    cached_calls=len(calls)
    with monkeypatch.context() as context:
        context.setattr(finalist_module,'_GROUP_MEMO_ENTRIES',0)
        uncached=select_and_freeze(root/'search',root/'exploration_triggers',root/'targets',root/'uncached')
    assert result==uncached
    assert 0<cached_calls<len(calls)-cached_calls
    assert len(result["ranking"]) == len(search["candidates"])
    assert result['selected_ids']==[]  # Tiny cohort must not bypass the exploration sample gate.
    assert all('INSUFFICIENT_EXPLORATION_GROUP_USERS' in row['reasons'] for row in result['ranking'])
    from server.analysis.freeze import load_frozen
    family=load_frozen(root/'selection/family_freeze',result['family_frozen']['sha256'])
    assert family['candidates']==search['candidates']
    assert family['family_size']==len(search['candidates'])>10
    assert family['priority_ids']==[]
    assert family['rules']['multiplicity']=='holm' and family['rules']['untestable_p']==1
    import pytest
    from server.analysis.ingest import IngestError
    full_result=validate_frozen(root/'normalized',root/'features',root/'targets',root/'selection/family_freeze',
                               result['family_frozen']['sha256'],root/'family-validation')
    assert full_result['family_correction_complete']
    assert len(full_result['results'])==family['family_size']
    assert all(r['inference']['family_size']==family['family_size'] for r in full_result['results'])
    assert all(r['evidence_status']!='historically_validated' for r in full_result['results'])
    second = select_and_freeze(root/"search", root/"exploration_triggers", root/"targets", root/"repeat")
    assert result == second
    validated = validate_frozen(root/"normalized", root/"features", root/"targets", root/"selection/freeze",
                                result["frozen"]["sha256"], root/"validation")
    assert [entry["candidate_id"] for entry in validated["results"]] == result["selected_ids"]
    assert all(entry["evidence_status"] != "historically_validated" for entry in validated["results"])
    import json
    from server.analysis.ingest import file_hash
    family_path=root/'selection/family_freeze/frozen.json'
    original=family_path.read_bytes()
    family['family_size']+=1
    family_path.write_text(json.dumps(family))
    with pytest.raises(IngestError,match='FROZEN_CONTRACT_CHANGED'):
        load_frozen(family_path.parent,result['family_frozen']['sha256'])
    with pytest.raises(IngestError,match='INVALID_FROZEN_FAMILY'):
        load_frozen(family_path.parent,file_hash(family_path))
    family_path.write_bytes(original)
