import json
from datetime import datetime
from pathlib import Path

import pytest

from server.analysis.casual_sequences import match_sequence

FIXTURE=Path("tests/fixtures/casual_v3")


def events(limit=15):
    rows=json.loads((FIXTURE/"events.json").read_text())[:limit]
    for row in rows:row["event_time"]=datetime.fromisoformat(row["event_time"].replace("Z","+00:00"))
    return rows


def test_retry_and_completion_pairing_respects_attempt_identity():
    rows=events(9)
    retry=match_sequence(rows,"level_fail_to_start",1800)
    complete=match_sequence(rows,"level_start_to_complete",1800)
    recovered=match_sequence(rows,"level_fail_to_complete",1800)
    assert [(m["first_event_id"],m["second_event_id"]) for m in retry]==[("u1-l1-a1-fail","u1-l1-a2-start")]
    assert [(m["first_event_id"],m["second_event_id"]) for m in complete]==[("u1-l1-a2-start","u1-l1-a2-complete")]
    assert [(m["first_event_id"],m["second_event_id"]) for m in recovered]==[("u1-l1-a1-fail","u1-l1-a2-complete")]


def test_same_timestamp_without_source_sequence_never_pairs():
    assert match_sequence(events(),"level_start_to_complete",300)==[]


def test_same_session_and_gap_are_enforced():
    rows=events(9)
    pairs=match_sequence(rows,"level_complete_to_ad_impression",300)
    assert [(m["first_event_id"],m["second_event_id"]) for m in pairs]==[("u1-l1-a2-complete","u1-ad1")]
    changed=[{**row,"session_id":"other"} if row["event_id"]=="u1-ad1" else row for row in rows]
    assert match_sequence(changed,"level_complete_to_ad_impression",300)==[]


def test_only_fail_complete_accepts_24_hour_gap():
    with pytest.raises(ValueError,match="LONG_GAP_TEMPLATE_NOT_ALLOWED"):
        match_sequence(events(9),"level_fail_to_start",86400)


@pytest.mark.parametrize(("template","first_name","second_name","first_format"),[
    ("level_fail_to_session_end","level_fail","session_end",None),
    ("session_start_to_level_complete","session_start","level_complete",None),
    ("rewarded_ad_to_level_complete","ad_impression","level_complete","rewarded"),
])
def test_remaining_registered_templates_require_strict_order_and_same_session(template,first_name,second_name,first_format):
    base=datetime.fromisoformat("2026-01-01T00:00:00+00:00")
    first={"event_id":"a","event_name":first_name,"event_time":base,"source_sequence":1,
           "session_id":"s","level_id":"L","attempt_id":"a1","ad_format":first_format}
    second={"event_id":"b","event_name":second_name,"event_time":base.replace(minute=1),"source_sequence":2,
            "session_id":"s","level_id":"L","attempt_id":"a2","ad_format":None}
    assert len(match_sequence([first,second],template,300))==1
    assert match_sequence([first,{**second,"session_id":"other"}],template,300)==[]
