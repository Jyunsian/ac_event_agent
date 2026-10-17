from datetime import datetime,timedelta,timezone
import random
from server.analysis.v4_sequences import match_sequence
from server.analysis.casual_sequences import match_sequence as reference
from server.analysis.v3_contract import SEQUENCE_RULES


def test_indexed_pairs_match_reference_with_ties_missing_keys_and_reused_events():
    rng=random.Random(42);origin=datetime(2026,1,1,tzinfo=timezone.utc)
    names=['session_start','session_end','level_start','level_fail','level_complete','ad_impression']
    for trial in range(12):
        events=[{'event_id':str(i),'event_time':origin+timedelta(seconds=rng.randrange(0,100)*60),
                 'source_sequence':rng.choice([None,1,2,3]),'event_name':rng.choice(names),
                 'level_id':rng.choice([None,'a','b']),'attempt_id':rng.choice([None,'1','2','3']),
                 'session_id':rng.choice([None,'s1','s2','s3']),'ad_format':rng.choice(['rewarded','banner'])} for i in range(90)]
        for template in SEQUENCE_RULES:
            for gap in [300,1800,7200]+([86400] if template=='level_fail_to_complete' else []):
                assert match_sequence(events,template,gap)==sorted(reference(events,template,gap),key=lambda m:m['matched_at'])


def test_count_timeline_uses_completion_order_not_first_step_order():
    origin=datetime(2026,1,1,tzinfo=timezone.utc)
    events=[{'event_id':str(i),'event_time':origin+timedelta(seconds=t),'event_name':name,'level_id':level,'attempt_id':level,'source_sequence':i} for i,(t,name,level) in enumerate([(0,'level_start','a'),(1,'level_start','b'),(2,'level_complete','b'),(100,'level_complete','a')])]
    matches=match_sequence(events,'level_start_to_complete',300)
    assert [int((m['matched_at']-origin).total_seconds()) for m in matches]==[2,100]
