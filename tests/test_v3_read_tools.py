import json

import pytest

from server.analysis.ingest import file_hash
from server.candidate_reader import filter_candidates,verified_detail
from server.uploads import APIError
from tests.test_v3_catalog import prepare_catalog


def test_v3_reader_filters_category_and_verifies_exact_detail_hash(tmp_path):
    _,catalog,_=prepare_catalog(tmp_path/"data")
    entry=catalog["entries"][0];path=tmp_path/"data/catalog/details"/f'{entry["candidate_id"]}.json'
    class LocalStorage:
        def get_bytes(self,manifest):
            assert manifest.sha256==file_hash(path)
            return path.read_bytes()
    files={f'catalog/details/{entry["candidate_id"]}.json':{"object_key":"local","sha256":entry["detail_sha256"],
        "size_bytes":path.stat().st_size,"content_type":"application/json"}}
    detail=verified_detail(LocalStorage(),catalog,files,entry)
    assert detail["analysis_version"]=="3.0-casual-game" and detail["candidate_id"]==entry["candidate_id"]
    assert filter_candidates(catalog,category=entry["category"])
    assert filter_candidates(catalog,category="sequence")==[]
    changed=json.loads(json.dumps(entry));changed["detail_sha256"]="f"*64
    with pytest.raises(APIError,match="CANDIDATE_DETAIL_INVALID"):verified_detail(LocalStorage(),catalog,files,changed)
