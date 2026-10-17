import csv
import json

from scripts.benchmark_casual_v3 import independent_truth
from scripts.generate_casual_v3_fixture import generate
from server.analysis.casual_selection import _diverse_order,_jaccard


def _slow_order(rows,hit_sets,limit):
    result=[]
    for layer in sorted({row["pareto_layer"] for row in rows}):
        remaining=[row for row in rows if row["pareto_layer"]==layer]
        while remaining and len(result)<limit:
            chosen=min(remaining,key=lambda row:(
                max((_jaccard(hit_sets[row["candidate_id"]],hit_sets[prior["candidate_id"]]) for prior in result),default=0),
                -row["difference_usd"],-row["coverage"],row["p90_seconds"],row["candidate_id"]))
            result.append(chosen);remaining.remove(chosen)
        if len(result)>=limit:break
    return result


def test_capacity_fixture_is_exact_complete_and_independently_counted(tmp_path):
    source=generate(tmp_path/"casual",2200,100000,42)
    with (source/"events.csv").open(newline="") as stream:
        rows=list(csv.DictReader(stream))
    assert len(rows)==100000
    assert {row["event_name"] for row in rows}>={"ad_impression","session_start","session_end","level_start","level_complete","level_fail"}
    assert all(row["session_id"] and row["engaged_seconds"] for row in rows if row["event_name"]=="session_end")
    truth=independent_truth(source)
    assert truth["users"]==truth["mature_users"]==2200 and truth["events"]==100000
    assert truth["zero_event_users"]==0 and float(truth["d7_revenue_usd"])>0
    assert json.loads((source/"generator.json").read_text())["categories"]==[
        "iaa","session_retention","level_progress","level_friction","cross_category","sequence"]


def test_incremental_diversity_order_is_exactly_the_reference_policy():
    hit_sets={f"c{i}":mask for i,mask in enumerate((0b0011,0b0101,0b1001,0b1110,0b0110,0b1010))}
    rows=[{"candidate_id":identity,"pareto_layer":index//3,"difference_usd":1/(index+1),
           "coverage":hit_sets[identity].bit_count()/4,"p90_seconds":index+1}
          for index,identity in enumerate(hit_sets)]
    assert _diverse_order(rows,hit_sets,5)==_slow_order(rows,hit_sets,5)
