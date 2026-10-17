from uuid import UUID

from server.analysis.catalog_v3 import build_catalog_v3
from tests.test_v3_validation import prepare_validation

RUN=UUID("11111111-1111-4111-8111-111111111111")
DATASET=UUID("22222222-2222-4222-8222-222222222222")


def prepare_catalog(root):
    validation=prepare_validation(root)
    catalog,value_map=build_catalog_v3(root/"search",root/"selection",root/"validation",RUN,DATASET,root/"catalog")
    return validation,catalog,value_map


def test_catalog_has_one_hashed_detail_per_validation_result(tmp_path):
    validation,catalog,value_map=prepare_catalog(tmp_path/"data")
    assert catalog["evaluated_count"]==validation["family_size"]==len(catalog["entries"])
    assert catalog["priority_ids"]==validation["priority_ids"]
    assert all((tmp_path/"data/catalog/details"/f'{entry["candidate_id"]}.json').is_file() for entry in catalog["entries"])
    assert value_map["total_count"]==catalog["evaluated_count"]


def test_72h_value_map_is_exact_projection_not_recalculation(tmp_path):
    validation,catalog,value_map=prepare_catalog(tmp_path/"data")
    results={row["candidate_id"]:row for row in validation["results"]}
    details={row["candidate_id"]:row["detail_sha256"] for row in catalog["entries"]}
    for point in value_map["points"]:
        source=results[point["candidate_id"]]["checkpoints"]["d3"]
        expected_x=source["comparisons"]["early"]["difference_usd"] if source["comparisons"] else None
        expected_y=source["comparisons"]["remaining"]["difference_usd"] if source["comparisons"] else None
        assert point["x_early_72h_difference_usd"]==expected_x
        assert point["y_remaining_72_168h_difference_usd"]==expected_y
        assert point["detail_sha256"]==details[point["candidate_id"]]
        assert (point["chart_status"]=="PLOTTED")==(point["decision_time_hours"]<=72 and expected_x is not None and expected_y is not None)
