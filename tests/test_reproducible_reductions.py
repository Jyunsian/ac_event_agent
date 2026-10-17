"""Floating reductions must not depend on parallel partition arrival order."""
import csv
import json
import math
from scripts.generate_fixture import generate
from server.analysis.ingest import canonicalize,file_hash
from server.analysis.targets import build_targets
from server.analysis.features import build_features
from server.analysis.connection import connect


def test_large_skewed_targets_and_feature_bytes_repeat_exactly(tmp_path,monkeypatch):
    # More than two Parquet row groups, with half the events on one user and
    # repeated timestamps/decimal revenues. This is not a capacity benchmark.
    source=generate(tmp_path/'source',1000,300000)
    export=json.loads((source/'export.json').read_text())
    inputs=[];mapping={}
    for role in ['users','events']:
        path=source/f'{role}.csv'
        with path.open() as stream:mapping[role]={name:name for name in next(csv.reader(stream))}
        inputs.append({'role':role,'path':str(path),'format':'csv','sha256':file_hash(path)})
    normalized=tmp_path/'normalized'
    canonicalize(inputs,mapping,normalized)
    outputs=[]
    for index,threads in enumerate([2,2,1]):
        monkeypatch.setenv('WORKER_THREADS',str(threads))
        targets=build_targets(normalized,export,tmp_path/f'targets-{index}')
        features=build_features(normalized,export,tmp_path/f'features-{index}',windows_hours=[3,144])
        outputs.append((targets,features))
    # Includes summary values AND Parquet SHA/size, not approximate comparison.
    assert outputs[0]==outputs[1]==outputs[2]
    assert outputs[0][0]['calculation_version']=='1.1_ordered_revenue_reduction'
    assert outputs[0][1]['definition']['version']=='1.2'
    for entry in inputs:assert file_hash(entry['path'])==entry['sha256']
    # The versioned per-dimension window plan changes floating reduction grouping.
    # Identity, timestamp and counts stay exact; only floating cumulative revenue
    # can differ at the last bits from the legacy global plan. Above, the entire
    # NEW version still must repeat byte-for-byte across threads, no tolerance.
    with connect(str(tmp_path/'features-0/work.duckdb')) as c:
        expected=c.execute('''SELECT app_id,user_id,metric,ad_format,available_at,
            sum(sum(delta ORDER BY delta)) OVER (
                PARTITION BY app_id,user_id,metric,ad_format ORDER BY available_at
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS value
            FROM deltas JOIN users USING(app_id,user_id)
            WHERE available_at>=installed_at AND available_at<installed_at+144*INTERVAL '1 hour'
              AND available_at<=CAST(? AS TIMESTAMPTZ)
            GROUP BY app_id,user_id,metric,ad_format,available_at ORDER BY ALL''',
            [export['exported_at']]).fetchall()
        actual=c.execute('SELECT * FROM timeline ORDER BY ALL').fetchall()
    assert len(actual)==len(expected)
    for actual_row,expected_row in zip(actual,expected,strict=True):
        assert actual_row[:-1]==expected_row[:-1]
        if actual_row[2]=='revenue_sum':
            assert math.isclose(actual_row[-1],expected_row[-1],rel_tol=1e-14,abs_tol=1e-15)
        else:
            assert actual_row[-1]==expected_row[-1]
