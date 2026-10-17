"""Generate an exact-size, multi-category Casual Game V3 CSV fixture."""
from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import datetime,timedelta,timezone
from pathlib import Path

from server.analysis.ingest import EVENT_TYPES,USER_TYPES


def generate(destination:Path,users:int,events:int,seed:int=42):
    if type(users) is not int or type(events) is not int or users<400 or events<users*20:
        raise ValueError("CASUAL_V3_FIXTURE_REQUIRES_USERS_GE_400_AND_EVENTS_GE_20X_USERS")
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    origin=datetime(2026,1,1,tzinfo=timezone.utc);rng=random.Random(seed);rows=[];sequence=0
    def stamp(value):return value.isoformat().replace("+00:00","Z")
    def add(user,name,when,**fields):
        nonlocal sequence
        sequence+=1
        row={name:None for name in EVENT_TYPES}
        row.update({"app_id":"casual-capacity","user_id":user,"event_id":f"e{sequence:09d}",
            "event_name":name,"event_time":stamp(when),"available_at":stamp(when),**fields})
        rows.append(row)
    user_rows=[]
    session_slots=(.1,4,8,18,30,42,60,84,110,138)
    level_slots=(.3,2,4,8,16,30,45,65,90,115)
    formats=("rewarded","interstitial","banner","app_open","native","other")
    for index in range(users):
        installed=origin+timedelta(days=index%10);user=f"u{index:06d}";local=random.Random((seed<<32)^index)
        user_rows.append({"app_id":"casual-capacity","user_id":user,"installed_at":stamp(installed),
            "platform":"ios" if index%2==0 else "android","country":("TW","US","JP","DE")[index%4],
            "acquisition_source":("organic","video","social","cross_promo")[index%4],
            "campaign_id":f"c{index%12}","app_version_at_install":f"1.{index%5}"})
        sessions=[]
        for slot,hours in enumerate(session_slots):
            count=(1+local.randrange(25)) if slot==0 else local.randrange(2)
            for occurrence in range(count):
                session=f"{user}-s{slot}-{occurrence}";started=installed+timedelta(hours=hours,minutes=occurrence*7+local.randrange(6))
                sessions.append((started,session))
                add(user,"session_start",started,session_id=session,source_sequence=1+occurrence,app_version=f"1.{index%5}")
        # One fully paired, differently timed session end per user enables the
        # post-return engagement metric without manufacturing duplicate ends.
        ended_at,ended_session=sessions[local.randrange(len(sessions))]
        engaged=60+local.randrange(3541)
        add(user,"session_end",ended_at+timedelta(seconds=engaged),session_id=ended_session,
            source_sequence=9,engaged_seconds=engaged,app_version=f"1.{index%5}")
        speed=.5+local.random()*.7
        # Sequential progress of different lengths yields realistic nested
        # reached/completed-level memberships, while the per-user speed keeps
        # their time-window memberships from collapsing into the same hashes.
        played=range(1,4+max(local.randrange(8),local.randrange(8)))
        for level in played:
            attempts=2 if local.randrange(3)==0 else 1;base=installed+timedelta(hours=level_slots[level-1]*speed)
            session=min(sessions,key=lambda value:abs((value[0]-base).total_seconds()))[1]
            for attempt in range(1,attempts+1):
                attempt_id=f"{user}-l{level}-a{attempt}";started=base+timedelta(minutes=attempt*4)
                common={"session_id":session,"level_id":f"L{level:03d}","level_index":level,
                    "attempt_id":attempt_id,"level_mode":"main","difficulty":("easy","normal","hard")[level%3],
                    "revive_used":attempt>1,"booster_used":bool((index+level)%3==0),"app_version":f"1.{index%5}"}
                add(user,"level_start",started,source_sequence=10+attempt*2,**common)
                terminal=started+timedelta(seconds=45+local.randrange(240))
                add(user,"level_complete" if attempt==attempts else "level_fail",terminal,
                    source_sequence=11+attempt*2,**common)
        ad_count=3+local.randrange(4);early_ads=local.randrange(ad_count+1)
        for number in range(ad_count):
            delay_minutes=(5+number*3+local.randrange(3)) if number<early_ads else 60+local.randrange(143*60)
            when=installed+timedelta(minutes=delay_minutes)
            ad_format=formats[(index+number+local.randrange(len(formats)))%len(formats)]
            revenue=(1+((index*17+number*13+local.randrange(97))%200))/10000
            session=min(sessions,key=lambda value:abs((value[0]-when).total_seconds()))[1]
            add(user,"ad_impression",when,session_id=session,source_sequence=100+number,
                ad_format=ad_format,revenue_usd=revenue,app_version=f"1.{index%5}")
    if len(rows)>events:raise ValueError(f"CASUAL_V3_CORE_EXCEEDS_EVENT_BUDGET:{len(rows)}")
    # Fill to the exact requested event count with additional varied ad events.
    while len(rows)<events:
        number=len(rows);index=number%users;user=f"u{index:06d}";installed=origin+timedelta(days=index%10)
        when=installed+timedelta(minutes=15+(number*7919)%(144*60-15));ad_format=formats[(number//users+index)%len(formats)]
        add(user,"ad_impression",when,session_id=f"{user}-s0",source_sequence=100000+number,
            ad_format=ad_format,revenue_usd=(1+(number*37+index*11)%250)/10000,app_version=f"1.{index%5}")
    with (destination/"users.csv").open("x",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(USER_TYPES));writer.writeheader();writer.writerows(user_rows)
    with (destination/"events.csv").open("x",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(EVENT_TYPES));writer.writeheader();writer.writerows(rows)
    complete=origin+timedelta(days=20)
    (destination/"export.json").write_text(json.dumps({"schema_version":"1.0","complete_through":stamp(complete),
        "exported_at":stamp(complete+timedelta(days=1)),"origin":"install",
        "id_policy":"one synthetic anonymous user per install","revenue_timing":"immediate","synthetic":True},
        sort_keys=True,indent=2))
    (destination/"generator.json").write_text(json.dumps({"schema_version":"3.0","synthetic":True,
        "users":users,"events":len(rows),"seed":seed,"categories":["iaa","session_retention",
        "level_progress","level_friction","cross_category","sequence"]},sort_keys=True,indent=2))
    return destination


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--users",type=int,default=2200);parser.add_argument("--events",type=int,default=100000)
    parser.add_argument("--seed",type=int,default=42);args=parser.parse_args()
    generate(args.output,args.users,args.events,args.seed)
    print(json.dumps({"status":"generated","users":args.users,"events":args.events,"path":str(args.output)}))
