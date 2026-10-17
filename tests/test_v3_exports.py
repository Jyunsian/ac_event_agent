import csv

from server.analysis.report_v3 import build_report_v3
from tests.test_v3_catalog import prepare_catalog


def test_json_csv_html_cover_the_complete_validation_family(tmp_path):
    _,catalog,value_map=prepare_catalog(tmp_path/"data")
    report=build_report_v3(tmp_path/"data/catalog",tmp_path/"data/validation",tmp_path/"data/report")
    with (tmp_path/"data/report/report_v3.csv").open() as stream:rows=list(csv.DictReader(stream))
    assert len(rows)==catalog["evaluated_count"]
    assert {row["candidate_id"] for row in rows}=={entry["candidate_id"] for entry in catalog["entries"]}
    assert len(report["validation_results"])==catalog["evaluated_count"]
    assert report["value_map"]==value_map
    html=(tmp_path/"data/report/report_v3.html").read_text()
    assert "connect-src 'none'" in html and "candidate_value_map_72h" in html
    assert "完整 Discovery 搜尋紀錄" in html and "aria-label=\"72 小時候選價值散點圖\"" in html
    assert "r','7'" in html and "單一" not in html  # equal radius is code-enforced, not a visual legend.
