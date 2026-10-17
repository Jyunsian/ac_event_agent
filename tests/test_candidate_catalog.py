import json
import pytest
from server.analysis.catalog import build_catalog
from server.analysis.report import event_spec
from server.analysis.search import candidate_for
from server.analysis.ingest import file_hash,IngestError
from tests.test_quality import EXPORT


def test_complete_catalog_keeps_unavailable_items_and_exact_detail_hashes(tmp_path):
    candidates=[candidate_for(144,{'op':'count','threshold':i}) for i in range(1,21)]
    ids=[c['candidate_id'] for c in candidates]
    search={'candidates':candidates,'export_metadata':EXPORT,'search_version':'2.0'}
    selection={'selected_ids':[],'family_frozen':{'sha256':'a'*64},'ranking':[
        {'candidate_id':i,'triggered_users':0,'untriggered_users':100,'eligible':False,
         'reasons':['NO_SUPPORT']} for i in ids]}
    validation={'validation_version':'2.0','family_correction_complete':True,'family_size':20,
        'priority_ids':[],'frozen_sha256':'a'*64,'results':[
            {'candidate_id':i,'metrics':None,'evidence_status':'insufficient_data',
             'reasons':['FEATURE_CAPABILITY_DISABLED']} for i in ids]}
    context=('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002')
    catalog=build_catalog(search,selection,validation,*context,tmp_path/'catalog',event_spec)
    assert catalog['evaluated_count']==20 and catalog['priority_ids']==[]
    for entry in catalog['entries']:
        path=tmp_path/'catalog/details'/f"{entry['candidate_id']}.json"
        assert file_hash(path)==entry['detail_sha256']
        detail=json.loads(path.read_text())
        assert detail['validation']['metrics'] is None
        assert detail['candidate_id']==entry['candidate_id']
        assert entry['summary']['event_spec'] == detail['event_spec']
        assert entry['summary']['family'] == 'atom'
        assert entry['summary']['ad_formats'] == ['all']
        assert entry['summary']['triggered_users'] is None
        assert entry['summary']['difference_usd'] is None
    assert (tmp_path/'catalog/search.json').is_file()
    from copy import deepcopy
    from server.candidate_reader import verified_detail
    from server.uploads import APIError
    # Local artifact unit test, not a substitute for the pending PG/S3 rerun.
    class LocalEvidence:
        def get_bytes(self, manifest):
            path=tmp_path/'catalog/details'/manifest.object_key
            assert file_hash(path)==manifest.sha256
            return path.read_bytes()
    entry=catalog['entries'][0]
    filename=f"{entry['candidate_id']}.json"
    path=tmp_path/'catalog/details'/filename
    files={f'catalog/details/{filename}':{'object_key':filename,'sha256':entry['detail_sha256'],
        'size_bytes':path.stat().st_size,'content_type':'application/json'}}
    assert verified_detail(LocalEvidence(),catalog,files,entry)['candidate_id']==entry['candidate_id']
    for key,value in [('window_hours',6),('reasons',['DIFFERENT']),('detail_sha256','b'*64)]:
        altered={**entry,key:value}
        with pytest.raises(APIError,match='CANDIDATE_DETAIL_INVALID'):
            verified_detail(LocalEvidence(),catalog,files,altered)
    altered=deepcopy(entry);altered['summary']['triggered_users']=0
    with pytest.raises(APIError,match='CANDIDATE_DETAIL_INVALID'):
        verified_detail(LocalEvidence(),catalog,files,altered)
    wrong_scope={**catalog,'dataset_id':'00000000-0000-0000-0000-000000000003'}
    with pytest.raises(APIError,match='CANDIDATE_DETAIL_INVALID'):
        verified_detail(LocalEvidence(),wrong_scope,files,entry)
    from server.analysis.v2_contract import validate_catalog
    for key, value in [('coverage', 1.1), ('triggered_users', 1.5), ('p90_seconds', -1),
                       ('difference_usd', float('nan'))]:
        invalid = deepcopy(catalog)
        invalid['entries'][0]['summary'][key] = value
        with pytest.raises(ValueError):
            validate_catalog(invalid)
    validation['family_size']=19
    with pytest.raises(IngestError,match='CATALOG_FAMILY_MISMATCH'):
        build_catalog(search,selection,validation,*context,tmp_path/'wrong',event_spec)
    assert not (tmp_path/'wrong').exists()
