import pytest
import json
from server.analysis.segments import build_segment,validate_segment
from server.analysis.ingest import IngestError
from tests.test_search import prepare,CONFIG
from tests.test_predicates import candidate


def test_us_cohort_keeps_original_split_and_reports_small_cells(tmp_path):
    root=tmp_path/'data';prepare(root)
    candidates=[candidate('revenue',{'op':'revenue_sum','threshold':.05},6)]
    report=build_segment(root/'normalized',root/'targets',root/'features',candidates,
        {'field':'country','value':'US'},{**CONFIG,'min_group_users':2},tmp_path/'us')
    assert report['selected_users']==3 and report['immature_users']==0
    assert report['cohorts']['exploration']['users']==2
    assert report['cohorts']['exploration']['revenue_usd']==pytest.approx(.2)
    assert report['cohorts']['exploration']['arpu_usd']==pytest.approx(.1)
    assert report['cohorts']['holdout']['users']==1
    assert report['cohorts']['holdout']['revenue_usd'] is None
    assert report['cohorts']['holdout']['reasons']==['SEGMENT_TOO_SMALL']
    assert report['candidates'][0]['metrics']['groups']['triggered']['users']==2
    assert report['candidates'][1]['metrics'] is None
    assert all(row['evidence_status']=='exploratory' for row in report['candidates'])
    missing=build_segment(root/'normalized',root/'targets',root/'features',candidates,
        {'field':'acquisition_source','value':'paid'},CONFIG,tmp_path/'missing')
    assert 'SEGMENT_FIELD_UNAVAILABLE' in missing['reasons'] and missing['candidates']==[]
    assert missing['field_unknown_users']==6


@pytest.mark.parametrize('segment',[{}, {'field':'country; DROP TABLE users','value':'US'},
    {'field':'country','value':''},{'field':'country','value':['US']},{'field':'country','value':'US','sql':'select 1'}])
def test_segment_selector_rejects_code_and_unknown_fields(segment):
    with pytest.raises(IngestError,match='SEGMENT_INVALID'):validate_segment(segment)


def test_missing_capability_returns_denominator_and_no_fake_metrics(tmp_path):
    root=tmp_path/'data';prepare(root,missing_holdout_session=True)
    report=build_segment(root/'normalized',root/'targets',root/'features',
        [candidate('session',{'op':'session_count','threshold':2},6)],
        {'field':'country','value':'US'},{**CONFIG,'min_group_users':2},tmp_path/'segment')
    assert report['selected_users']==3
    assert all(row['metrics'] is None and 'FEATURE_CAPABILITY_DISABLED' in row['reasons'] for row in report['candidates'])
    assert not (tmp_path/'segment/triggers').exists()


def test_segment_rejects_feature_source_and_split_drift(tmp_path):
    root=tmp_path/'data';prepare(root)
    args=(root/'normalized',root/'targets',root/'features',
        [candidate('count',{'op':'count','threshold':1})],{'field':'country','value':'US'})
    with pytest.raises(IngestError,match='SEGMENT_SOURCE_OR_SPLIT_MISMATCH'):
        build_segment(*args,{**CONFIG,'exploration_fraction':.5},tmp_path/'wrong-split')
    path=root/'features/manifest.json';manifest=json.loads(path.read_text())
    manifest['definition']['source_manifest_sha256']='0'*64;path.write_text(json.dumps(manifest))
    with pytest.raises(IngestError,match='SEGMENT_SOURCE_OR_SPLIT_MISMATCH'):
        build_segment(*args,CONFIG,tmp_path/'wrong-source')
    assert not (tmp_path/'wrong-split').exists() and not (tmp_path/'wrong-source').exists()


def test_platform_maturity_and_bound_value_filter(tmp_path):
    root=tmp_path/'data';prepare(root)
    args=(root/'normalized',root/'targets',root/'features',[candidate('count',{'op':'count','threshold':1})])
    ios=build_segment(*args,{'field':'platform','value':'ios'},CONFIG,tmp_path/'ios')
    assert ios['selected_users']==3 and ios['immature_users']==1
    assert ios['cohorts']['exploration']['users']==ios['cohorts']['holdout']['users']==1
    empty=build_segment(*args,{'field':'country','value':"US' OR 1=1 --"},CONFIG,tmp_path/'literal')
    assert empty['selected_users']==0 and 'SEGMENT_EMPTY' in empty['reasons']
