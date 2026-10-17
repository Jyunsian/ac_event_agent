import csv
import json
import pytest

from server.analysis.ingest import IngestError, file_hash
from server.analysis.report import build_report, csv_safe
from server.analysis.report_html import condition, render_report


def diagnostic_sources(tmp_path):
    values = {"baseline": {"synthetic": True, "run_id": "synthetic-run", "dataset_id": "synthetic-ds",
        "pipeline_version": "test", "status": "diagnostic_only", "finalist_ids": [],
        "reasons": ["MISSING_AD_REVENUE"]}, "quality": {"schema_version": "1.0", "note": "<script>alert(1)</script>"}}
    result = {}
    for name, data in values.items():
        path = tmp_path/(name+".json")
        path.write_text(json.dumps(data))
        result[name] = {"path": path, "sha256": file_hash(path)}
    return result


def test_offline_diagnostic_escape_and_manifest(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    sources = diagnostic_sources(tmp_path)
    for source in sources.values():source['object_key']='private-bucket/customer-source-key'
    model = build_report(sources, tmp_path/"report", title='<img src=x onerror="alert(1)">')
    assert model["candidates"] == []
    document = (tmp_path/"report/report.html").read_text()
    assert "<script>" not in document and "<img" not in document
    assert "&lt;script&gt;" in document and "&lt;img" in document
    assert model == json.loads((tmp_path/"report/report.json").read_text())
    with (tmp_path/'report/report.csv').open() as stream:rows=list(csv.DictReader(stream))
    assert len(rows)==1 and rows[0]['record_type']=='limitation'
    assert rows[0]['evidence_status']=='not_evaluated' and rows[0]['candidate_id']==''
    assert rows[0]['run_id']=='synthetic-run' and rows[0]['dataset_id']=='synthetic-ds'
    assert rows[0]['csv_schema_version']=='2.0'
    assert 'MISSING_AD_REVENUE' in rows[0]['limitations_json']
    assert json.loads(rows[0]['data_scope_json'])['complete_through'] is None
    for suffix in ['html','json','csv']:
        assert 'private-bucket/customer-source-key' not in (tmp_path/f'report/report.{suffix}').read_text()
    manifest = json.loads((tmp_path/"report/manifest.json").read_text())
    for artifact in manifest["artifacts"]:
        path = tmp_path/"report"/artifact["path"]
        assert file_hash(path) == artifact["sha256"]
        assert path.stat().st_size == artifact["size_bytes"]


@pytest.mark.parametrize("value", ['=1+1', '+cmd', '-cmd', '@sum(1)', '  =1', '\t=1', '\r=1', '\n=1'])
def test_csv_formula_protection(value):
    assert csv_safe(value) == "'"+value


def test_source_tamper_never_creates_committed_report(tmp_path):
    sources = diagnostic_sources(tmp_path)
    sources["quality"]["path"].write_text('{}')
    with pytest.raises(IngestError, match="REPORT_SOURCE_CHECKSUM_MISMATCH"):
        build_report(sources, tmp_path/"report")
    assert not (tmp_path/"report/manifest.json").exists()


def test_plain_language_conditions_and_nulls():
    atom = {"op": "count", "threshold": 5, "ad_format": "rewarded"}
    assert condition(atom) == "展示獎勵式廣告累積 5 次"
    assert "）且（" in condition({"op": "and", "clauses": [atom, {"op": "session_count", "threshold": 2}]})
    assert "完成 2 次不重疊的順序" in condition({"op": "sequence", "steps": ["session_start", "ad_impression"], "max_gap_seconds": 60, "repeats": 2})


def test_html_render_failure_has_no_commit_marker(tmp_path, monkeypatch):
    import server.analysis.report as report
    def fail(model):
        raise RuntimeError("synthetic renderer failure")
    monkeypatch.setattr(report, "render_report", fail)
    with pytest.raises(RuntimeError, match="synthetic renderer failure"):
        build_report(diagnostic_sources(tmp_path), tmp_path/"report")
    assert (tmp_path/"report/report.json").exists()
    assert not (tmp_path/"report/manifest.json").exists()


def test_empty_priority_still_requires_complete_family_correction(tmp_path):
    from server.analysis.search import candidate_for
    from tests.test_quality import EXPORT
    candidate=candidate_for(144,{'op':'count','threshold':1});identity=candidate['candidate_id']
    sources=diagnostic_sources(tmp_path)
    baseline=json.loads(sources['baseline']['path'].read_text())
    baseline.update(run_id='00000000-0000-0000-0000-000000000001',dataset_id='00000000-0000-0000-0000-000000000002')
    results=[{'candidate_id':identity,'metrics':None,
              'evidence_status':'insufficient_data','reasons':['INSUFFICIENT_GROUP_USERS']}]
    baseline['validation']=results
    data={'baseline':baseline,'search':{'candidates':[candidate], 'split_id':'split','export_metadata':EXPORT},
          'selection':{'selected_ids':[],'family_frozen':{'sha256':'a'*64},'ranking':[{'candidate_id':identity,'triggered_users':0,'untriggered_users':100}]},
          'validation':{'validation_version':'2.0','results':results,'family_size':1,
                        'priority_ids':[],'family_correction_complete':True,'frozen_sha256':'a'*64,'split_id':'split'},
          'overlap':{},'sensitivity':{},'landmark':{}}
    def save():
        for name,value in data.items():
            path=tmp_path/f'{name}.json';path.write_text(json.dumps(value))
            sources[name]={'path':path,'sha256':file_hash(path)}
    save()
    report=build_report(sources,tmp_path/'complete')
    assert report['candidates']==[] and report['summary']['searched_candidate_count']==1
    assert report['schema_version']=='2.0' and report['catalog']['evaluated_count']==1
    assert (tmp_path/'complete/catalog/details'/f'{identity}.json').is_file()
    data['validation']['family_correction_complete']=False;save()
    with pytest.raises(IngestError,match='REPORT_INCOMPLETE_FAMILY_VALIDATION'):
        build_report(sources,tmp_path/'incomplete')
    assert not (tmp_path/'incomplete/manifest.json').exists()
