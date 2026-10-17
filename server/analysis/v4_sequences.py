"""Indexed V4 matching: preserve greedy pairs; emit them in observable time order."""
from bisect import bisect_left
from collections import defaultdict
from server.analysis.casual_sequences import _is_first,_is_second,_constraints_match,strictly_after
from server.analysis.v3_contract import SEQUENCE_RULES


def match_sequence(events,template,max_gap_seconds):
    if template not in SEQUENCE_RULES:raise ValueError('UNKNOWN_SEQUENCE_TEMPLATE')
    if max_gap_seconds not in (300,1800,7200,86400):raise ValueError('INVALID_SEQUENCE_GAP')
    if max_gap_seconds==86400 and template!='level_fail_to_complete':raise ValueError('LONG_GAP_TEMPLATE_NOT_ALLOWED')
    ordered=sorted(events,key=lambda e:(e['event_time'],e.get('source_sequence') is None,e.get('source_sequence') or 0,e['event_id']))
    constraints=SEQUENCE_RULES[template]
    fields=[field for constraint,field in [('same_level','level_id'),('same_attempt','attempt_id'),('same_session','session_id')] if constraint in constraints]
    buckets=defaultdict(list)
    for e in ordered:
        if _is_second(e,template) and all(e.get(f) for f in fields):buckets[tuple(e[f] for f in fields)].append(e)
    times={key:[e['event_time'] for e in rows] for key,rows in buckets.items()}
    used=set();matches=[]
    for first in ordered:
        if first['event_id'] in used or not _is_first(first,template) or not all(first.get(f) for f in fields):continue
        key=tuple(first[f] for f in fields);rows=buckets.get(key,[])
        start=bisect_left(times.get(key,[]),first['event_time'])
        for i in range(start,len(rows)):
            second=rows[i]
            if second['event_id'] in used or second['event_id']==first['event_id'] or not strictly_after(first,second):continue
            gap=(second['event_time']-first['event_time']).total_seconds()
            if gap>max_gap_seconds:break
            if not _constraints_match(first,second,template):continue
            used.update((first['event_id'],second['event_id']))
            matches.append({'template':template,'max_gap_seconds':max_gap_seconds,'first_event_id':first['event_id'],
                            'second_event_id':second['event_id'],'matched_at':second['event_time'],'gap_seconds':gap})
            break
    return sorted(matches,key=lambda m:m['matched_at'])
