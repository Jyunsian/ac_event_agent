import json
import pytest
from server.analysis.freeze import freeze_candidates,load_frozen
from server.analysis.search import candidate_for
from server.analysis.ingest import IngestError,file_hash
from tests.test_search import CONFIG
from tests.test_quality import EXPORT


def test_full_family_rule_changes_cannot_hide_behind_a_new_hash(tmp_path):
    search=tmp_path/'search';search.mkdir()
    candidates=[candidate_for(144,{'op':'count','threshold':i}) for i in range(1,21)]
    (search/'manifest.json').write_text(json.dumps({'config':CONFIG,'candidates':candidates,
        'synthetic':True,'feature_id':'synthetic','split_id':'synthetic',
        'source_manifest_sha256':'a'*64,'export_metadata':EXPORT}))
    receipt=freeze_candidates(search,[candidates[0]['candidate_id']],tmp_path/'freeze',full_family=True)
    contract=load_frozen(tmp_path/'freeze',receipt['sha256'])
    assert contract['family_size']==20 and len(contract['priority_ids'])==1
    path=tmp_path/'freeze/frozen.json'
    original=path.read_bytes()
    for field,value in [('alpha',.5),('multiplicity','none'),('untestable_p',0),('family_scope','priority_only')]:
        changed=json.loads(original);changed['rules'][field]=value
        path.write_text(json.dumps(changed))
        with pytest.raises(IngestError,match='INVALID_FROZEN_RULES'):
            load_frozen(path.parent,file_hash(path))
    path.write_bytes(original)
    with pytest.raises(FileExistsError):
        freeze_candidates(search,[],path.parent,full_family=True)
    assert path.read_bytes()==original
