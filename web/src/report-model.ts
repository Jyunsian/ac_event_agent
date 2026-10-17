type Json = null | boolean | number | string | Json[] | {[key:string]:Json};
export type Group = {users:number;arpu_usd:number|null;unknown_revenue_users:number};
export type Segment = {segment:{field:string;value:string};evidence_status:'exploratory';reasons:string[];
  event_specs?:{candidate_id:string;event_spec:Candidate['event_spec']}[];
  selected_users?:number;immature_users?:number;field_known_users:number;field_unknown_users:number;split_id:string;
  cohorts:Record<string,{users:number;unknown_revenue_users:number;arpu_usd:number|null;revenue_usd:number|null;reasons:string[]}>;
  candidates:{candidate_id:string;split:string;users:number;metrics:Candidate['metrics'];reasons:string[];evidence_status:string}[]};
export type Candidate = {candidate_id:string;evidence_status:string;reasons:string[];selection_evidence?:{role?:string|null}|null;
  metrics:null|{groups:{all:Group;triggered:Group;untriggered:Group;unknown?:Group};coverage:number|null;delay_seconds:{median:number|null;p90:number|null};[key:string]:unknown};
  event_spec:{event_name:string;window_hours:number;predicate:Record<string,Json>;[key:string]:Json};evidence:Record<string,Json>};
export type Report = {schema_version:string;run_id:string;dataset_id:string;synthetic:boolean;analysis_status:string;
  catalog?:{sha256:string;evaluated_count:number;priority_ids:string[]};
  value_map?:{schema_version:'3.0';analysis_version:string;chart_type:'candidate_value_map_72h';run_id:string;dataset_id:string;plotted_count:number;total_count:number;points:ValuePoint[]};
  diagnostics?:Record<string,unknown>;candidates:Candidate[];summary:{candidate_count:number;historically_validated_count:number;searched_candidate_count:number|null;
    reasons:string[];segment?:Segment|null;finding_recheck?:{assessments:{finding_id:string;candidate_id:string;source_run_id:string;status:string;reasons:string[];reusable:boolean;independent_batch_eligible:boolean}[];[key:string]:unknown}|null;data_profile:Record<string,Json>|null;targets:Record<string,Json>|null;quality:Record<string,Json>};audit:Record<string,Json>};
export type ValuePoint={candidate_id:string;category:string;decision_time_hours:number;x_early_72h_difference_usd:number|null;y_remaining_72_168h_difference_usd:number|null;triggered_users:number;untriggered_users:number;unknown_users:number;coverage:number|null;evidence_status:string;detail_sha256:string;chart_status:'PLOTTED'|'LATE_INDICATOR_NOT_PLOTTED'|'NULL_VALUE_NOT_PLOTTED'};

function fail():never {throw new Error('REPORT_SCHEMA_INVALID');}
function record(v:unknown):asserts v is Record<string,any> {if(!v||typeof v!=='object'||Array.isArray(v))fail();}
function strings(v:unknown):asserts v is string[] {if(!Array.isArray(v)||!v.every(x=>typeof x==='string'))fail();}
function number(v:unknown,nullable=false){if(nullable&&v===null)return;if(typeof v!=='number'||!Number.isFinite(v))fail();}
function metric(v:unknown){
  if(v===null)return;record(v);record(v.groups);record(v.delay_seconds);
  number(v.coverage,true);for(const key of ['median','p90'])number(v.delay_seconds[key],true);
  for(const key of ['all','triggered','untriggered']){const group=v.groups[key];record(group);number(group.users);number(group.arpu_usd,true);number(group.unknown_revenue_users);}
}
export function decodeReport(value:unknown,runId:string,datasetId:string):Report {
  record(value);
  if(value.run_id!==runId||value.dataset_id!==datasetId)throw new Error('REPORT_IDENTITY_MISMATCH');
  let nodes=0;
  // A V3 catalog can legitimately contain 2,000 value-map points plus their
  // traceable candidate details. Keep the depth/array/body-size guards, while
  // allowing the largest valid 16 MiB report to pass structural validation.
  function bounded(v:unknown,depth=0){if(++nodes>1000000||depth>30)fail();if(typeof v==='number')number(v);else if(Array.isArray(v)){if(v.length>20000)fail();v.forEach(x=>bounded(x,depth+1));}else if(v&&typeof v==='object')Object.values(v).forEach(x=>bounded(x,depth+1));}
  bounded(value);
  if(!['1.0','2.0','3.0','4.0'].includes(value.schema_version)||typeof value.synthetic!=='boolean'||typeof value.analysis_status!=='string')fail();
  if(value.schema_version==='2.0'||value.schema_version==='3.0'||value.schema_version==='4.0'){
    record(value.catalog);strings(value.catalog.priority_ids);number(value.catalog.evaluated_count);
    if(!/^[a-f0-9]{64}$/.test(value.catalog.sha256)||!Number.isInteger(value.catalog.evaluated_count)||
       value.catalog.evaluated_count<0||value.catalog.evaluated_count>2000||value.catalog.priority_ids.length>10)fail();
  }
  if(value.schema_version==='4.0'&&value.analysis_version!=='4.0-time-aware')fail();
  if(value.schema_version==='3.0'){
    if(value.analysis_version!=='3.0-casual-game')fail();record(value.value_map);
    const map=value.value_map;if(map.schema_version!=='3.0'||map.analysis_version!==value.analysis_version||map.chart_type!=='candidate_value_map_72h'||map.run_id!==runId||map.dataset_id!==datasetId||!Array.isArray(map.points)||map.points.length>2000)fail();
    number(map.plotted_count);number(map.total_count);if(map.total_count!==map.points.length)fail();let plotted=0;const pointIds=new Set<string>();
    for(const point of map.points){record(point);if(typeof point.candidate_id!=='string'||pointIds.has(point.candidate_id)||typeof point.category!=='string'||!/^[a-f0-9]{64}$/.test(point.detail_sha256))fail();pointIds.add(point.candidate_id);
      for(const key of ['decision_time_hours','triggered_users','untriggered_users','unknown_users'])number(point[key]);number(point.coverage,true);number(point.x_early_72h_difference_usd,true);number(point.y_remaining_72_168h_difference_usd,true);
      if(!['PLOTTED','LATE_INDICATOR_NOT_PLOTTED','NULL_VALUE_NOT_PLOTTED'].includes(point.chart_status))fail();if(point.chart_status==='PLOTTED'){plotted++;if(point.decision_time_hours>72||point.x_early_72h_difference_usd===null||point.y_remaining_72_168h_difference_usd===null)fail();}}
    if(plotted!==map.plotted_count)fail();
  }
  record(value.summary);record(value.audit);record(value.summary.quality);strings(value.summary.reasons);
  for(const key of ['candidate_count','historically_validated_count'])number(value.summary[key]);
  number(value.summary.searched_candidate_count,true);
  const segment=value.summary.segment;
  const recheck=value.summary.finding_recheck;
  if(recheck!=null){
    record(recheck);if(!Array.isArray(recheck.assessments)||recheck.assessments.length>10)fail();
    for(const row of recheck.assessments){record(row);strings(row.reasons);
      for(const key of ['finding_id','candidate_id','source_run_id'])if(typeof row[key]!=='string'||!row[key])fail();
      if(!['reusable_evidence','exploratory_only','insufficient_evidence','not_supported','not_evaluated'].includes(row.status)||
        typeof row.reusable!=='boolean'||typeof row.independent_batch_eligible!=='boolean'||
        row.reusable!==(row.status==='reusable_evidence')||(row.reusable&&!row.independent_batch_eligible))fail();
    }
  }
  if(segment!=null){
    record(segment);record(segment.segment);record(segment.cohorts);strings(segment.reasons);
    if(segment.evidence_status!=='exploratory'||typeof segment.split_id!=='string'||
      !['country','platform','acquisition_source'].includes(segment.segment.field)||typeof segment.segment.value!=='string')fail();
    for(const key of ['field_known_users','field_unknown_users'])number(segment[key]);
    for(const key of ['selected_users','immature_users'])if(segment[key]!==undefined)number(segment[key]);
    for(const [split,cohort] of Object.entries(segment.cohorts)){
      if(!['exploration','holdout'].includes(split))fail();record(cohort);strings(cohort.reasons);
      number(cohort.users);number(cohort.unknown_revenue_users);number(cohort.arpu_usd,true);number(cohort.revenue_usd,true);
    }
    if(!Array.isArray(segment.candidates)||segment.candidates.length>20)fail();
    for(const row of segment.candidates){record(row);strings(row.reasons);number(row.users);
      if(typeof row.candidate_id!=='string'||!['exploration','holdout'].includes(row.split)||row.evidence_status!=='exploratory')fail();metric(row.metrics);}
    if(segment.event_specs!==undefined){
      if(!Array.isArray(segment.event_specs)||segment.event_specs.length>10)fail();
      const specIds=new Set<string>();
      for(const row of segment.event_specs){record(row);record(row.event_spec);record(row.event_spec.predicate);
        if(typeof row.candidate_id!=='string'||specIds.has(row.candidate_id)||typeof row.event_spec.event_name!=='string')fail();
        number(row.event_spec.window_hours);specIds.add(row.candidate_id);}
      if(segment.candidates.some((row:any)=>!specIds.has(row.candidate_id)))fail();
    }
  }
  for(const key of ['targets','data_profile'])if(value.summary[key]!==null)record(value.summary[key]);
  if(!Array.isArray(value.candidates)||value.candidates.length>10||value.summary.candidate_count!==value.candidates.length)fail();
  const ids=new Set<string>();
  for(const row of value.candidates){
    record(row);if(typeof row.candidate_id!=='string'||ids.has(row.candidate_id)||typeof row.evidence_status!=='string')fail();ids.add(row.candidate_id);
    strings(row.reasons);record(row.event_spec);record(row.event_spec.predicate);record(row.evidence);
    if(typeof row.event_spec.event_name!=='string')fail();number(row.event_spec.window_hours);
    metric(row.metrics);
    if(value.schema_version==='4.0'){
      record(row.time_analysis);
      for(const scope of ['observation','holdout',...(row.time_analysis.exploration?['exploration']:[])]){
        const points=row.time_analysis[scope];
        if(!Array.isArray(points)||JSON.stringify(points.map((p:any)=>p.hours))!==JSON.stringify([24,48,72,96,120,144]))fail();
        for(const p of points){record(p.groups);for(const key of ['triggered','untriggered','unknown','added','added_since_24h','exited','all']){record(p.groups[key]);number(p.groups[key].users,key==='added_since_24h'&&p.baseline_24h_applicable===false);number(p.groups[key].arpu_usd,true);}}
      }
    }
    if(row.selection_evidence!=null){record(row.selection_evidence);
      if(row.selection_evidence.role!=null&&!['價值差較大','覆蓋較廣','達標較快'].includes(row.selection_evidence.role))fail();}
  }
  if((value.schema_version==='2.0'||value.schema_version==='3.0'||value.schema_version==='4.0')&&(value.catalog.evaluated_count<ids.size||
      JSON.stringify(value.catalog.priority_ids)!==JSON.stringify(value.candidates.map((row:Candidate)=>row.candidate_id))))fail();
  return value as Report;
}

export async function fetchReport(runId:string,datasetId:string,version:number,signal:AbortSignal):Promise<{report:Report;sha256:string}> {
  const response=await fetch(`/api/runs/${encodeURIComponent(runId)}/reports/${version}/json`,{signal});
  if(!response.ok)throw new Error(`REPORT_READ_FAILED_${response.status}`);
  const reader=response.body?.getReader();if(!reader)throw new Error('REPORT_BODY_MISSING');
  const chunks:Uint8Array[]=[];let size=0;
  try{for(;;){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>16*1024**2)throw new Error('REPORT_TOO_LARGE');chunks.push(value);}}
  catch(error){await reader.cancel();throw error;}finally{reader.releaseLock();}
  const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
  // Proxies may weaken the ETag when compressing the response. The browser
  // decodes that transport encoding; still verify its bytes against the hash.
  const etag=response.headers.get('etag');
  if(etag!==`"${digest}"`&&etag!==`W/"${digest}"`)throw new Error('REPORT_CHECKSUM_MISMATCH');
  return {report:decodeReport(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes)),runId,datasetId),sha256:digest};
}
