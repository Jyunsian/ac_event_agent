from server.analysis.casual_selection import select_casual_family
from server.analysis.v3_policy import allocate_by_category
from tests.test_v3_search import prepare_v3


def _item(category,index):
    return {"candidate_id":f"{index:064x}","category":category,"observation_end_hours":6,
            "indicator_type":"ad_count","predicate":{"threshold":index}}


def test_exact_20k_and_2k_category_budget_boundaries():
    categories=("iaa","session_retention","level_progress","level_friction","cross_category","sequence")
    pool=[_item(category,index*10000+offset) for index,category in enumerate(categories) for offset in range(5000)]
    discovery,_,audit=allocate_by_category(pool,"discovery",20000)
    validation,_,small=allocate_by_category(pool,"validation",2000)
    assert len(discovery)==20000 and audit["allocated"]=={"iaa":3500,"session_retention":3000,"level_progress":4500,"level_friction":3000,"cross_category":4000,"sequence":2000}
    assert len(validation)==2000 and small["allocated"]=={"iaa":350,"session_retention":300,"level_progress":450,"level_friction":300,"cross_category":400,"sequence":200}


def test_selection_respects_family_and_priority_caps(tmp_path):
    prepare_v3(tmp_path/"data")
    selected=select_casual_family(tmp_path/"data/search",tmp_path/"data/selection")
    assert 0<selected["family_size"]<=20
    assert len(selected["priority_ids"])<=5
    assert set(selected["priority_ids"])<=set(selected["candidate_ids"])
