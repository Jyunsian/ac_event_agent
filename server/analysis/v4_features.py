"""V4 event-time features. Legacy snapshots are reused, first-hit times are not."""
import bisect
import csv
import json
import math
import numpy as np
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from server.analysis.casual_features import build_casual_features, AD_FORMATS, _utc, _scope
from server.analysis.casual_sequences import strictly_after
from server.analysis.v4_sequences import match_sequence
from server.analysis.connection import connect
from server.analysis.ingest import file_hash
from server.analysis.v4_contract import ANALYSIS_VERSION, CHECKPOINTS, POLICY_IDENTITY


def write_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:json.dump(value,stream,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':'))


def repair_timeline(events,installed,base,timing):
    """Return exact missing/incorrect timeline dimensions; no last-event fallback."""
    fixed={}
    for fmt in AD_FORMATS:
        rows=[];total=0.;bad=False
        ads=[e for e in events if e['event_name']=='ad_impression' and (fmt=='all' or (e.get('ad_format') or 'unknown')==fmt)]
        available=[]
        for e in ads:
            at=e.get('available_at') if timing=='available_at' else e['event_time']
            # Unknown arrival cannot invalidate an earlier, already observed hit.
            if at is None:
                available.append((e['event_time'],{**e,'revenue_usd':None}));continue
            available.append((max(at,e['event_time']),e))
        for at,e in sorted(available,key=lambda pair:(pair[0],pair[1]['event_id'])):
            value=e.get('revenue_usd')
            if value is None or value<0:bad=True
            if not bad:total+=value
            rows.append(((at-installed).total_seconds(),None if bad else total))
        fixed[('ad_revenue_sum',_scope({'ad_format':fmt}))]=rows
    for metric,template,gap in [('retry_same_level','level_fail_to_start',7200),('complete_after_fail','level_fail_to_complete',86400)]:
        matches=match_sequence(events,template,gap)
        fixed[(metric,_scope('all'))]=[((m['matched_at']-installed).total_seconds(),float(i+1)) for i,m in enumerate(matches)]
    starts=[e for e in events if e['event_name']=='session_start']
    failures=[e for e in events if e['event_name']=='level_fail'];used=set();times=[]
    for failed in failures:
        for start in starts:
            if start['event_id'] not in used and start.get('session_id')!=failed.get('session_id') and strictly_after(failed,start):
                used.add(start['event_id']);times.append((start['event_time']-installed).total_seconds());break
    fixed[('session_after_fail',_scope('all'))]=[(t,float(i+1)) for i,t in enumerate(sorted(times))]
    streak=defaultdict(int);best=0;rows=[]
    for e in events:
        if not e.get('level_id'):continue
        if e['event_name']=='level_fail':
            streak[e['level_id']]+=1;best=max(best,streak[e['level_id']]);rows.append(((e['event_time']-installed).total_seconds(),float(best)))
        elif e['event_name']=='level_complete':streak[e['level_id']]=0
    fixed[('consecutive_failures',_scope('all'))]=rows
    returns=[e for e in starts if e['event_time']>installed]
    first=returns[0] if returns else None
    seen=set();sessions=[];duration=[];seconds=0.
    for e in events:
        if first is None or e['event_time']<first['event_time']:continue
        t=(e['event_time']-installed).total_seconds()
        if e['event_name']=='session_start' and e.get('session_id') and e['session_id'] not in seen:
            seen.add(e['session_id']);sessions.append((t,float(len(seen))))
        if e['event_name']=='session_end' and e.get('engaged_seconds') is not None:
            seconds+=e['engaged_seconds'];duration.append((t,float(seconds)))
    fixed[('post_return_session_count',_scope('all'))]=sessions
    fixed[('post_return_engaged_seconds',_scope('all'))]=duration
    interval_times=[]
    for left,right in ((24,48),(48,72),(72,96)):
        hits=[e for e in starts if left*3600 <= (e['event_time']-installed).total_seconds()<right*3600]
        rows=[((hits[0]['event_time']-installed).total_seconds(),1.)] if hits else []
        fixed[('return_in_interval',_scope({'start_hours':left,'end_hours':right}))]=rows
        if hits:interval_times.append((left,(hits[0]['event_time']-installed).total_seconds()))
    fixed[('return_interval_count',_scope('all'))]=[(t,float(i+1)) for i,(_,t) in enumerate(interval_times)]
    rows=[];previous=None;streak=0;best=0
    for left,t in interval_times:
        streak=streak+1 if previous is not None and left==previous+24 else 1
        best=max(best,streak);rows.append((t,float(best)));previous=left
    fixed[('consecutive_return_days',_scope('all'))]=rows
    return fixed


def build_features_v4(normalized,export,destination,scope=None):
    normalized,destination=Path(normalized),Path(destination)
    destination.mkdir(parents=True,exist_ok=False)
    legacy=destination/'snapshots'
    build_casual_features(normalized,export,legacy,CHECKPOINTS,scope=scope,sequence_matcher=match_sequence)
    with connect(config={'memory_limit':'256MB','threads':2}) as c:
        columns=[r[0] for r in c.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(normalized/'events.parquet')]).fetchall()]
        by_user=defaultdict(list)
        for row in c.execute('SELECT * FROM read_parquet(?) ORDER BY app_id,user_id,event_time,source_sequence NULLS LAST,event_id',[str(normalized/'events.parquet')]).fetchall():
            e=dict(zip(columns,row));by_user[(e['app_id'],e['user_id'])].append(e)
        users=c.execute('SELECT app_id,user_id,installed_at FROM read_parquet(?) ORDER BY ALL',[str(normalized/'users.parquet')]).fetchall()
        timelines=defaultdict(dict)
        for app,user,category,metric,scope_json,at,value,denominator in c.execute('SELECT * FROM read_parquet(?)',[str(legacy/'timeline.parquet')]).fetchall():
            timelines[(app,user)].setdefault((app,user,metric,scope_json),[]).append((at,value))
    rolling_revenue=[]
    fixes={};output=[]
    for app,user,installed in users:
        events=[e for e in by_user[(app,user)] if installed<=e['event_time']<installed+timedelta(hours=168) and e['event_time']<=_utc(export['exported_at'])]
        for e in events:
            if e['event_name']=='ad_impression':
                available=e.get('available_at') if export['revenue_timing']=='available_at' else e['event_time']
                rolling_revenue.append((app,user,e.get('ad_format') or 'unknown',(e['event_time']-installed).total_seconds(),
                                       (max(available,e['event_time'])-installed).total_seconds() if available else None,e.get('revenue_usd')))
        for (metric,scope_json),rows in repair_timeline(events,installed,{},export['revenue_timing']).items():
            fixes[(app,user,metric,scope_json)]=rows
        for key,rows in timelines[(app,user)].items():
            if key not in fixes:fixes[key]=[((at-installed).total_seconds(),value) for at,value in rows if installed<=at<installed+timedelta(hours=168)]
    transfer=destination/'timeline.csv'
    with transfer.open('x',newline='') as stream:
        w=csv.writer(stream);w.writerow(['app_id','user_id','metric','scope_json','seconds','value'])
        for key,rows in sorted(fixes.items()):
            for seconds,value in sorted(rows,key=lambda r:r[0]):w.writerow([*key,seconds,value])
    revenue_transfer=destination/'rolling_revenue.csv'
    with revenue_transfer.open('x',newline='') as stream:
        w=csv.writer(stream);w.writerow(['app_id','user_id','ad_format','event_seconds','available_seconds','amount']);w.writerows(rolling_revenue)
    with connect(config={'memory_limit':'256MB','threads':2}) as c:
        c.execute("CREATE TABLE timeline AS SELECT app_id::VARCHAR app_id,user_id::VARCHAR user_id,metric::VARCHAR metric,scope_json::VARCHAR scope_json,seconds::DOUBLE AS delay_seconds,value::DOUBLE AS amount FROM read_csv(?,all_varchar=true,nullstr='')",[str(transfer)])
        c.execute("COPY (SELECT * FROM timeline ORDER BY ALL) TO ? (FORMAT PARQUET)",[str(destination/'timeline.parquet')])
        c.execute('CREATE TABLE rolling_revenue AS SELECT app_id::VARCHAR app_id,user_id::VARCHAR user_id,ad_format::VARCHAR ad_format,event_seconds::DOUBLE event_seconds,available_seconds::DOUBLE available_seconds,amount::DOUBLE amount FROM read_csv(?,all_varchar=true)',[str(revenue_transfer)])
        c.execute('COPY rolling_revenue TO ? (FORMAT PARQUET)',[str(destination/'rolling_revenue.parquet')])
    transfer.unlink();revenue_transfer.unlink()
    manifest={'schema_version':'4.0','analysis_version':ANALYSIS_VERSION,'stage':'features_v4','policy_identity':POLICY_IDENTITY,
              'source_manifest_sha256':file_hash(normalized/'manifest.json'),'scope':scope,'export_metadata':export,'revenue_snapshot_policy':'per_user_available_timeline',
              'rolling_revenue_sha256':file_hash(destination/'rolling_revenue.parquet'),'timeline_sha256':file_hash(destination/'timeline.parquet'),'snapshots_sha256':file_hash(legacy/'snapshots.parquet'),
              'quality_sha256':file_hash(legacy/'quality/quality_v3.json')}
    write_json(destination/'manifest.json',manifest)
    return manifest


class FeatureIndex:
    def __init__(self,directory):
        root=Path(directory);self.manifest=json.loads((root/'manifest.json').read_text())
        if self.manifest['analysis_version']!=ANALYSIS_VERSION:raise ValueError('V4_FEATURE_VERSION')
        for relative,key in [('rolling_revenue.parquet','rolling_revenue_sha256'),('timeline.parquet','timeline_sha256'),('snapshots/snapshots.parquet','snapshots_sha256'),('snapshots/quality/quality_v3.json','quality_sha256')]:
            if file_hash(root/relative)!=self.manifest[key]:raise ValueError('V4_FEATURE_CHECKSUM')
        self.quality=json.loads((root/'snapshots/quality/quality_v3.json').read_text())
        per_user_revenue=self.manifest.get('revenue_snapshot_policy')=='per_user_available_timeline'
        revenue_enabled=self.manifest['export_metadata']['revenue_timing'] in ('immediate','available_at') and not set(self.quality['capabilities']['revenue_trigger']['reasons']).intersection({'SINGLE_APP_REQUIRED','NO_VALID_USERS','QUARANTINED_IDENTITIES','UNRECONCILED_EVENTS'})
        self.snapshots=defaultdict(dict);self.timelines=defaultdict(dict);self.users=set();self.cache={};self.rolling_revenue=defaultdict(list)
        with connect(config={'memory_limit':'256MB','threads':2}) as c:
            for app,user,fmt,t,at,v in c.execute('SELECT * FROM read_parquet(?)',[str(root/'rolling_revenue.parquet')]).fetchall():
                self.rolling_revenue[(app,user,fmt)].append((t,at,v))
                self.rolling_revenue[(app,user,'all')].append((t,at,v))
            for app,user,h,cat,metric,scope,value,denom,complete,enabled,first,mode in c.execute('SELECT * FROM read_parquet(?)',[str(root/'snapshots/snapshots.parquet')]).fetchall():
                key=(metric,scope);identity=(app,user);self.users.add(identity)
                self.snapshots[(key,h)][identity]=(value,denom,complete and (revenue_enabled if per_user_revenue and metric=='ad_revenue_sum' else enabled))
            raw=defaultdict(list)
            for app,user,metric,scope,t,v in c.execute('SELECT * FROM read_parquet(?) ORDER BY ALL',[str(root/'timeline.parquet')]).fetchall():raw[(metric,scope,app,user)].append((t,v))
        for (metric,scope,app,user),rows in raw.items():
            # Simultaneous arrivals are one observable batch; retain its final cumulative value.
            collapsed={}
            for t,v in rows:collapsed[t]=None if v is None or (t in collapsed and collapsed[t] is None) else max(v,collapsed.get(t,v))
            self.timelines[(metric,scope)][(app,user)]=sorted(collapsed.items())

        if per_user_revenue:
            # V3's dataset-wide missing-revenue gate must not erase reliable
            # V4 evidence for other players or an earlier observation time.
            for (key,h),records in self.snapshots.items():
                if key[0]!='ad_revenue_sum':continue
                for user,(_,denom,enabled) in records.items():
                    rows=self.timelines.get(key,{}).get(user,[])
                    last=bisect.bisect_left([t for t,v in rows],h*3600)-1
                    value=rows[last][1] if last>=0 else 0.
                    records[user]=(value if enabled else None,denom,enabled)

    def array_atom(self,clause,h,mode):
        # Compact arrays retain shared parents without thousands of Python dictionaries.
        if not hasattr(self,'array_cache'):
            self.array_cache={};self.first_cache={};self.ordered_users=sorted(self.users);self.snapshot_arrays={}
        encoded=json.dumps(clause,sort_keys=True);cachekey=(encoded,h,mode)
        if cachekey in self.array_cache:return self.array_cache[cachekey]
        metric=clause['metric'];key=(metric,_scope(clause['scope'] or 'all'))
        decision=clause['scope']['end_hours'] if metric=='return_in_interval' else h
        sk=(key,decision)
        if sk not in self.snapshot_arrays:
            records=self.snapshots.get(sk,{})
            rows=[records.get(u,(None,None,False)) for u in self.ordered_users]
            self.snapshot_arrays[sk]=(np.array([v if v is not None else np.nan for v,d,e in rows]),
                                     np.array([d if d is not None else np.nan for v,d,e in rows]),np.array([e for v,d,e in rows]))
        values,denom,enabled=self.snapshot_arrays[sk];valid=enabled.copy()
        if h<decision:valid[:]=False
        if clause['minimum_denominator']:valid &= denom>=clause['minimum_denominator']
        status=np.full(len(values),-1,dtype=np.int8);delay=np.full(len(values),np.nan)
        if mode=='snapshot':
            valid &= np.isfinite(values);hit=values>=clause['threshold'] if clause['comparator']=='gte' else values<=clause['threshold']
            status[valid]=hit[valid];delay[valid&hit]=h*3600
        else:
            fk=(encoded,mode,24 if mode=='rolling' and h==24 else 144)
            if fk not in self.first_cache:
                first=[];bad=[]
                for u in self.ordered_users:
                    timeline=self.timelines.get(key,{}).get(u,[])
                    invalid=min((t for t,v in timeline if v is None),default=np.inf)
                    if mode=='rolling':
                        deadline=86400 if h==24 else 518400
                        if metric=='ad_revenue_sum':
                            events=self.rolling_revenue.get((*u,clause['scope']['ad_format']),[])
                            invalid=revenue_unknown_at(events)
                            reached=rolling_available_first_hit(known_revenue(events),clause['threshold'],min(deadline,invalid))
                        else:
                            events=[];previous=0.
                            for t,v in timeline:
                                if v is not None:events.append((t,max(0.,v-previous)));previous=v
                            reached=rolling_first_hit(events,clause['threshold'],deadline,None if invalid==np.inf else invalid)
                    else:reached=next((t for t,v in timeline if v is not None and v>=clause['threshold']),None)
                    first.append(np.inf if reached is None else reached);bad.append(invalid)
                self.first_cache[fk]=(np.array(first),np.array(bad))
            first,bad=self.first_cache[fk];hit=first<h*3600
            if mode=='rolling' and h==24:hit=first<=86400
            known=valid & ((np.isfinite(values)&(bad>=h*3600)&((values<clause['threshold']) if mode=='cumulative' else True))|hit)
            status[known]=hit[known];delay[known&hit]=first[known&hit]
        if len(self.array_cache)>=8192:self.array_cache.pop(next(iter(self.array_cache)))
        self.array_cache[cachekey]=(status,delay)
        return status,delay

    def evaluate_array(self,rule,h):
        p=rule['predicate'];mode=rule['mode']
        if p['node']=='sequence':p={'metric':p['template'],'scope':{'max_gap_seconds':p['max_gap_seconds']},'comparator':'gte','threshold':p['repeats'],'minimum_denominator':0}
        if p.get('node')!='boolean':return self.array_atom(p,h,mode)
        (a,ta),(b,tb)=[self.array_atom(c,h,mode) for c in p['clauses']]
        if p['operator']=='and':
            result=np.where((a==0)|(b==0),0,np.where((a==1)&(b==1),1,-1)).astype(np.int8);times=np.maximum(ta,tb)
        else:
            result=np.where((a==1)|(b==1),1,np.where((a==0)&(b==0),0,-1)).astype(np.int8);times=np.fmin(ta,tb)
        return result,np.where(result==1,times,np.nan)

    def atom(self,clause,h,mode='cumulative'):
        scope=_scope(clause['scope'] or 'all');key=(clause['metric'],scope)
        cachekey=(json.dumps(clause,sort_keys=True),h,mode)
        if cachekey in self.cache:return self.cache[cachekey]
        result={}
        for identity in sorted(self.users):
            value,denom,enabled=self.snapshots.get((key,h),{}).get(identity,(None,None,False))
            if clause['metric']=='return_in_interval':
                interval=clause['scope'];end=interval['end_hours']
                value,denom,enabled=self.snapshots.get((key,end),{}).get(identity,(None,None,False))
                if h<end:result[identity]=('unknown',None);continue
            if not enabled or (clause['minimum_denominator'] and (denom is None or denom<clause['minimum_denominator'])):
                result[identity]=('unknown',None);continue
            if mode=='snapshot':
                hit=None if value is None else (value>=clause['threshold'] if clause['comparator']=='gte' else value<=clause['threshold'])
                result[identity]=('unknown' if hit is None else 'triggered' if hit else 'untriggered',h*3600 if hit else None);continue
            rows=self.timelines.get(key,{}).get(identity,[])
            eligible=[(t,v) for t,v in rows if t<h*3600]
            unknown=any(v is None for _,v in eligible)
            hits=[t for t,v in eligible if v is not None and v>=clause['threshold']]
            if hits:result[identity]=('triggered',min(hits))
            elif unknown or value is None or value>=clause['threshold']:result[identity]=('unknown',None)
            else:result[identity]=('untriggered',None)
        if len(self.cache)>=32:self.cache.pop(next(iter(self.cache)))
        self.cache[cachekey]=result
        return result

    def evaluate(self,rule,h):
        p=rule['predicate']
        if rule['mode']=='rolling':return self.rolling(p,h)
        if p['node']=='sequence':
            p={'metric':p['template'],'scope':{'max_gap_seconds':p['max_gap_seconds']},'comparator':'gte','threshold':p['repeats'],'minimum_denominator':0}
            return self.atom(p,h)
        if p['node']=='atom':return self.atom(p,h,rule['mode'])
        parts=[self.atom(c,h,rule['mode']) for c in p['clauses']];result={}
        for user in sorted(self.users):
            a,b=[part[user] for part in parts]
            if p['operator']=='and':
                status='untriggered' if 'untriggered' in (a[0],b[0]) else 'triggered' if a[0]==b[0]=='triggered' else 'unknown'
                delay=max(a[1],b[1]) if status=='triggered' else None
            else:
                status='triggered' if 'triggered' in (a[0],b[0]) else 'untriggered' if a[0]==b[0]=='untriggered' else 'unknown'
                delay=min(r[1] for r in (a,b) if r[0]=='triggered') if status=='triggered' else None
            result[user]=(status,delay)
        return result

    def rolling(self,clause,h):
        key=(clause['metric'],_scope(clause['scope'] or 'all'))
        cachekey=(json.dumps(clause,sort_keys=True),h,'rolling')
        if cachekey in self.cache:return self.cache[cachekey]
        result={}
        for identity in sorted(self.users):
            value,denom,enabled=self.snapshots.get((key,h),{}).get(identity,(None,None,False))
            if not enabled or h<24:result[identity]=('unknown',None);continue
            if clause['metric']=='ad_revenue_sum':
                rows=self.rolling_revenue.get((*identity,clause['scope']['ad_format']),[])
                invalid=revenue_unknown_at(rows)
                first=rolling_available_first_hit(known_revenue(rows),clause['threshold'],min(h*3600,invalid))
                result[identity]=('triggered',first) if first is not None else ('unknown',None) if invalid<h*3600 or value is None else ('untriggered',None)
                continue
            timeline=self.timelines.get(key,{}).get(identity,[])
            events=[];previous=0.;bad=None
            for t,v in timeline:
                if v is None:bad=t if bad is None else min(bad,t);continue
                events.append((t,max(0.,v-previous)));previous=v
            first=rolling_first_hit(events,clause['threshold'],h*3600,bad)
            result[identity]=('triggered',first) if first is not None else ('unknown',None) if (bad is not None and bad<h*3600) or value is None else ('untriggered',None)
        if len(self.cache)>=32:self.cache.pop(next(iter(self.cache)))
        self.cache[cachekey]=result
        return result


def rolling_first_hit(events,threshold,deadline,unknown_at=None):
    """Full [t-24h,t) warmup; subsequent right limits include simultaneous arrivals.

    First warmup excludes its endpoint. Later event batches are evaluated after
    arrival, expiring the left endpoint. Reporting deadlines exclude new events.
    """
    from collections import deque
    width=86400.;queue=deque();total=0.;ordered=sorted(events);i=0
    while i<len(ordered) and ordered[i][0]<width:
        t,v=ordered[i];queue.append((t,v));total+=v;i+=1
    if deadline>=width and (unknown_at is None or unknown_at>=width) and total>=threshold:return width
    while i<len(ordered):
        t=ordered[i][0]
        if t>=deadline:break
        if unknown_at is not None and unknown_at<=t:break
        while queue and queue[0][0]<=t-width:total-=queue.popleft()[1]
        while i<len(ordered) and ordered[i][0]==t:
            queue.append(ordered[i]);total+=ordered[i][1];i+=1
        if total+1e-12>=threshold:return t
    return None


def revenue_unknown_at(events):
    # Occurrence is the earliest possible availability when arrival is missing.
    # Remain conservative from there onward without erasing earlier evidence.
    return min((max(t,at) if at is not None else t for t,at,v in events
                if at is None or v is None or v<0),default=math.inf)


def known_revenue(events):
    return [(t,max(t,at),v) for t,at,v in events if at is not None and v is not None and v>=0]


def rolling_available_first_hit(events,threshold,deadline):
    """Window membership uses occurrence; eligibility uses arrival. Never backdate."""
    import heapq
    width=86400.;ordered=sorted(events,key=lambda r:(r[1],r[0]));heap=[];total=0.;i=0
    while i<len(ordered) and ordered[i][1]<width:
        occurred,available,value=ordered[i];i+=1
        if 0<=occurred<width:heapq.heappush(heap,(occurred,value));total+=value
    if deadline>=width and total>=threshold:return width
    while i<len(ordered):
        now=ordered[i][1]
        if now>=deadline:break
        while heap and heap[0][0]<=now-width:total-=heapq.heappop(heap)[1]
        while i<len(ordered) and ordered[i][1]==now:
            occurred,available,value=ordered[i];i+=1
            if now-width<occurred<=now:heapq.heappush(heap,(occurred,value));total+=value
        if total>=threshold:return now
    return None
