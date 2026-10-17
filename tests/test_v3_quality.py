import json
from pathlib import Path

from server.analysis.ingest import EVENT_TYPES, USER_TYPES, canonicalize
from server.analysis.quality import build_casual_quality
from tests.test_ingest import write_source

FIXTURE = Path("tests/fixtures/casual_v3")
EXPORT = json.loads((FIXTURE/"export.json").read_text())
MAPPING = {"users": {name:name for name in USER_TYPES}, "events": {name:name for name in EVENT_TYPES}}


def normalize(tmp_path, users, events):
    sources = [write_source(tmp_path,"users",users), write_source(tmp_path,"events",events)]
    canonicalize(sources,MAPPING,tmp_path/"normalized")
    return build_casual_quality(tmp_path/"normalized",EXPORT,tmp_path/"quality")[0]


def test_capabilities_are_metric_level_not_all_or_nothing(tmp_path):
    users = json.loads((FIXTURE/"users.json").read_text())
    events = json.loads((FIXTURE/"events.json").read_text())
    quality = normalize(tmp_path,users,events)
    caps = quality["capabilities"]
    assert caps["level_event_counts"]["enabled"] is True
    assert caps["level_identity"]["enabled"] is True
    assert caps["level_progress"] == {"enabled":False,"reasons":["LEVEL_INDEX_MISSING"]}
    assert caps["attempt_pairing"] == {"enabled":False,"reasons":["ATTEMPT_TERMINAL_CONFLICT"]}
    assert caps["session_return"]["enabled"] is True
    assert quality["casual_counts"]["terminal_conflicts"] == 1


def test_missing_session_id_does_not_disable_positive_return(tmp_path):
    users = json.loads((FIXTURE/"users.json").read_text())[:1]
    event = {**json.loads((FIXTURE/"events.json").read_text())[0],"session_id":None}
    quality = normalize(tmp_path,users,[event])
    caps = quality["capabilities"]
    assert caps["session_return"]["enabled"] is True
    assert caps["distinct_session_count"]["enabled"] is False
    assert caps["same_session_cross"]["enabled"] is False
    assert caps["revenue_analysis"]["enabled"] is True


def test_clean_level_subset_enables_pairing_and_progress(tmp_path):
    users = json.loads((FIXTURE/"users.json").read_text())[:1]
    events = json.loads((FIXTURE/"events.json").read_text())[:9]
    quality = normalize(tmp_path,users,events)
    assert quality["capabilities"]["level_progress"]["enabled"] is True
    assert quality["capabilities"]["attempt_pairing"]["enabled"] is True
    assert quality["capabilities"]["same_session_cross"]["enabled"] is True


def test_iaa_only_disables_only_casual_capabilities(tmp_path):
    hand = Path("tests/fixtures/hand")
    users = json.loads((hand/"users.json").read_text())
    events = json.loads((hand/"events.json").read_text())
    quality = normalize(tmp_path,users,events)
    assert quality["capabilities"]["level_event_counts"]["enabled"] is False
    assert quality["capabilities"]["revenue_analysis"]["enabled"] is True
    assert quality["capabilities"]["ad_frequency"]["enabled"] is True
