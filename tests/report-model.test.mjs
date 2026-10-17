import test from 'node:test';
import assert from 'node:assert/strict';
import {decodeReport,fetchReport} from '../web/src/report-model.ts';

const model=()=>({schema_version:'1.0',run_id:'run',dataset_id:'dataset',synthetic:true,analysis_status:'diagnostic_only',candidates:[],summary:{candidate_count:0,historically_validated_count:0,searched_candidate_count:null,reasons:[],data_profile:null,targets:null,quality:{}},audit:{}});
test('segment display validates metrics and binds names to matching immutable specs',()=>{
  const report=model();report.summary.segment={segment:{field:'country',value:'US'},evidence_status:'exploratory',reasons:[],split_id:'split',field_known_users:2,field_unknown_users:0,cohorts:{},candidates:[{candidate_id:'c',split:'holdout',users:2,metrics:null,evidence_status:'exploratory',reasons:[]}],event_specs:[{candidate_id:'c',event_spec:{event_name:'ac_c',window_hours:3,predicate:{op:'count',threshold:5}}}]};
  assert.equal(decodeReport(report,'run','dataset').summary.segment.candidates[0].metrics,null);
  const invalid=structuredClone(report);invalid.summary.segment.candidates[0].metrics={groups:{},coverage:.5};
  assert.throws(()=>decodeReport(invalid,'run','dataset'),/SCHEMA_INVALID/);
  const wrong=structuredClone(report);wrong.summary.segment.event_specs[0].candidate_id='other';
  assert.throws(()=>decodeReport(wrong,'run','dataset'),/SCHEMA_INVALID/);
  delete report.summary.segment.event_specs;assert.doesNotThrow(()=>decodeReport(report,'run','dataset'));
});
test('unknown stays null; identity and malformed counts are rejected',()=>{
  const report=model();assert.equal(decodeReport(report,'run','dataset').summary.searched_candidate_count,null);
  assert.throws(()=>decodeReport(report,'other','dataset'),/IDENTITY_MISMATCH/);
  assert.throws(()=>decodeReport({...report,summary:{...report.summary,candidate_count:1}},'run','dataset'),/SCHEMA_INVALID/);
  assert.throws(()=>decodeReport({...report,audit:{invalid:Infinity}},'run','dataset'),/SCHEMA_INVALID/);
});
test('reader verifies bytes before decoding; missing or wrong checksum rejected',async()=>{
  const original=globalThis.fetch;
  const body=JSON.stringify(model());
  const bytes=new TextEncoder().encode(body);
  const sha=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex');
  try{
    globalThis.fetch=async()=>new Response(body,{headers:{etag:`"${sha}"`}});
    assert.equal((await fetchReport('run','dataset',1,new AbortController().signal)).sha256,sha);
    globalThis.fetch=async()=>new Response(body,{headers:{etag:`W/"${sha}"`}});
    assert.equal((await fetchReport('run','dataset',1,new AbortController().signal)).sha256,sha);
    globalThis.fetch=async()=>new Response(body+' ',{headers:{etag:`W/"${sha}"`}});
    await assert.rejects(fetchReport('run','dataset',1,new AbortController().signal),/CHECKSUM_MISMATCH/);
    globalThis.fetch=async()=>new Response(body);
    await assert.rejects(fetchReport('run','dataset',1,new AbortController().signal),/CHECKSUM_MISMATCH/);
    globalThis.fetch=async()=>new Response(body,{headers:{etag:'"wrong"'}});
    await assert.rejects(fetchReport('run','dataset',1,new AbortController().signal),/CHECKSUM_MISMATCH/);
    globalThis.fetch=async()=>new Response(new Uint8Array(16*1024**2+1));
    await assert.rejects(fetchReport('run','dataset',1,new AbortController().signal),/TOO_LARGE/);
  }finally{globalThis.fetch=original;}
});
test('v3 72h value map rejects late or null points marked as plotted',()=>{
  const report={...model(),schema_version:'3.0',analysis_version:'3.0-casual-game',catalog:{sha256:'a'.repeat(64),evaluated_count:1,priority_ids:[]},value_map:{schema_version:'3.0',analysis_version:'3.0-casual-game',chart_type:'candidate_value_map_72h',run_id:'run',dataset_id:'dataset',plotted_count:1,total_count:1,points:[{candidate_id:'c'.repeat(64),category:'iaa',decision_time_hours:72,x_early_72h_difference_usd:1,y_remaining_72_168h_difference_usd:2,triggered_users:10,untriggered_users:10,unknown_users:0,coverage:.5,evidence_status:'not_supported',detail_sha256:'d'.repeat(64),chart_status:'PLOTTED'}]}};
  assert.equal(decodeReport(report,'run','dataset').value_map.plotted_count,1);
  for(const patch of [{decision_time_hours:96},{x_early_72h_difference_usd:null},{chart_status:'LATE_INDICATOR_NOT_PLOTTED'}]){
    const invalid=structuredClone(report);Object.assign(invalid.value_map.points[0],patch);
    assert.throws(()=>decodeReport(invalid,'run','dataset'),/SCHEMA_INVALID/);
  }
});

test('V4 explicitly inapplicable first-day comparisons accept null, never unknown population counts',()=>{
 const group={users:1,arpu_usd:1,unknown_revenue_users:0};
 const groups=Object.fromEntries(['all','triggered','untriggered','unknown','added','added_since_24h','exited'].map(k=>[k,{...group}]));
 const points=[24,48,72,96,120,144].map(hours=>({hours,baseline_24h_applicable:false,groups:{...groups,added_since_24h:{...group,users:null,arpu_usd:null}}}));
 const row={candidate_id:'c',event_spec:{event_name:'test',window_hours:144,predicate:{}},evidence_status:'exploratory',reasons:[],evidence:{},metrics:{groups,coverage:.1,delay_seconds:{median:null,p90:null}},time_analysis:{observation:points,exploration:points,holdout:points}};
 const r={...model(),schema_version:'4.0',analysis_version:'4.0-time-aware',catalog:{sha256:'a'.repeat(64),evaluated_count:1,priority_ids:['c']},candidates:[row]};r.summary.candidate_count=1;
 assert.doesNotThrow(()=>decodeReport(r,'run','dataset'));
 const bad=structuredClone(r);bad.candidates[0].time_analysis.exploration[0].groups.all.users=null;
 assert.throws(()=>decodeReport(bad,'run','dataset'),/SCHEMA_INVALID/);
 const unexplained=structuredClone(r);delete unexplained.candidates[0].time_analysis.observation[0].baseline_24h_applicable;
 assert.throws(()=>decodeReport(unexplained,'run','dataset'),/SCHEMA_INVALID/);
});
