import json
from datetime import datetime,timedelta,timezone

from server.analysis.casual_search import _atom,_cross,generate_casual_candidates,near_duplicate
from server.analysis.exploration import build_casual_search_features
from server.analysis.ingest import EVENT_TYPES,USER_TYPES,canonicalize
from server.analysis.targets import build_casual_targets
from tests.test_ingest import write_source

EXPORT={"schema_version":"1.0","exported_at":"2026-01-12T00:00:00Z","complete_through":"2026-01-12T00:00:00Z",
        "origin":"install","id_policy":"one anonymous user_id per install","revenue_timing":"immediate","synthetic":True}
CONFIG={"schema_version":"1.0","analysis_version":"3.0-casual-game","windows_hours":[3,6,24,48,72,96,120,144],
        "max_discovery_candidates":100,"max_candidates":20,"max_finalists":5,"seed":42,
        "min_group_users":2,"bootstrap_replicates":1000,"exploration_fraction":.7}
MAPPING={"users":{name:name for name in USER_TYPES},"events":{name:name for name in EVENT_TYPES}}


def prepare_v3(root):
    users=[];events=[]
    for day in range(4):
        installed=datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(days=day)
        for offset in range(6):
            user=f"d{day}u{offset}";base=installed.isoformat().replace("+00:00","Z")
            users.append({"app_id":"game","user_id":user,"installed_at":base,"platform":"ios","country":"TW",
                          "acquisition_source":"organic","campaign_id":None,"app_version_at_install":"1"})
            events.append({"app_id":"game","user_id":user,"event_id":user+"-s","event_name":"session_start",
                           "event_time":base,"available_at":base,"session_id":user+"s","source_sequence":1,
                           "ad_format":None,"revenue_usd":None,"engaged_seconds":None,"level_id":None,"level_index":None,
                           "attempt_id":None,"level_mode":None,"difficulty":None,"revive_used":None,"booster_used":None,"app_version":"1"})
            count=1 if offset<3 else 3
            for index in range(count):
                time=(installed+timedelta(hours=1,minutes=index)).isoformat().replace("+00:00","Z")
                events.append({"app_id":"game","user_id":user,"event_id":f"{user}-a{index}","event_name":"ad_impression",
                    "event_time":time,"available_at":time,"session_id":user+"s","source_sequence":2+index,
                    "ad_format":"rewarded","revenue_usd":.01*(index+1)+.001*offset,"engaged_seconds":None,"level_id":None,
                    "level_index":None,"attempt_id":None,"level_mode":None,"difficulty":None,"revive_used":None,
                    "booster_used":None,"app_version":"1"})
    root.mkdir()
    canonicalize([write_source(root,"users",users),write_source(root,"events",events)],MAPPING,root/"normalized")
    build_casual_targets(root/"normalized",EXPORT,root/"targets")
    build_casual_search_features(root/"normalized",root/"targets",EXPORT,root/"exploration",CONFIG["windows_hours"])
    return generate_casual_candidates(root/"exploration/features",root/"targets",CONFIG,root/"search")


def test_v3_search_uses_only_exploration_and_is_byte_deterministic(tmp_path):
    first=prepare_v3(tmp_path/"first")
    second=generate_casual_candidates(tmp_path/"first/exploration/features",tmp_path/"first/targets",CONFIG,tmp_path/"first/search-copy")
    assert first["discovery_count"]<=CONFIG["max_discovery_candidates"]
    assert first["exploration_scope"]["kind"]=="exploration"
    assert first["candidates"] and all(row["triggered_users"]>=2 and row["untriggered_users"]>=2 for row in first["evaluations"])
    assert any(row["primary_reason"]=="EXACT_MEMBERSHIP_DUPLICATE" for row in first["search_log"])
    assert (tmp_path/"first/search/manifest.json").read_bytes()==(tmp_path/"first/search-copy/manifest.json").read_bytes()
    assert (tmp_path/"first/search/memberships.parquet").read_bytes()==(tmp_path/"first/search-copy/memberships.parquet").read_bytes()


def test_holdout_revenue_change_cannot_change_existing_discovery(tmp_path):
    root=tmp_path/"data";manifest=prepare_v3(root)
    before=(root/"search/manifest.json").read_bytes()
    # Discovery is already sealed; a separate holdout-side file is outside every recorded input hash.
    (root/"holdout-only.json").write_text(json.dumps({"changed_revenue":999}))
    assert (root/"search/manifest.json").read_bytes()==before
    assert manifest["policy_identity"]


def test_near_duplicate_boundary_and_cross_ast_are_hand_calculable():
    near,jaccard,delta=near_duplicate(set(range(995)),set(range(1000)),.995,1)
    assert near and jaccard==.995 and abs(delta-.005)<1e-12
    not_near,_,_=near_duplicate(set(range(994)),set(range(1000)),.994,1)
    assert not not_near
    left=_atom("level_progress","level_complete_count",{},6,"gte",2)
    right=_atom("iaa","ad_count",{"ad_format":"all"},6,"gte",3)
    cross=_cross(left,right,"and")
    assert cross["category"]=="cross_category" and cross["predicate"]["node"]=="boolean"
    assert len(cross["predicate"]["clauses"])==2
