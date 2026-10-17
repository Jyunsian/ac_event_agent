import test from 'node:test';
import assert from 'node:assert/strict';
import {decodeCandidatePage,candidateExportUrl,decodeCandidateDetail,fetchRevenueGroups} from '../web/src/candidate-client.ts';
const scope={runId:'synthetic',version:1,reportSha:'a'.repeat(64),catalogSha:'b'.repeat(64)};
const page=()=>({run_id:scope.runId,report_version:1,report_sha256:scope.reportSha,catalog_sha256:scope.catalogSha,
  evaluated_count:1,comparison_users:2200,filtered_count:1,page:1,page_size:50,priority_ids:[],items:[{candidate_id:'c'.repeat(64),
    detail_sha256:'d'.repeat(64),window_hours:6,evidence_status:'insufficient_data',reasons:['SMALL_SAMPLE']}]});
test('income series reader binds immutable scope and rejects unsafe or duplicate points',async()=>{
  const point={candidate_id:'c'.repeat(64),detail_sha256:'d'.repeat(64),threshold_usd:.000000123,
    coverage:null,difference_usd:-2,sample_size:null,evidence_status:'insufficient_data'};
  const value={...page(),groups:[{window_hours:144,ad_format:'all',points:[point]}]};
  const original=globalThis.fetch;
  const read=async(v)=>{globalThis.fetch=async()=>new Response(JSON.stringify(v));return fetchRevenueGroups(scope,new AbortController().signal);};
  try{
    const groups=await read(value);assert.equal(groups[0].points[0].difference_usd,-2);
    assert.equal(groups[0].points[0].coverage,null);assert.equal(groups[0].points[0].threshold_usd,.000000123);
    for(const patch of [{report_version:2},{catalog_sha256:'f'.repeat(64)},{groups:[value.groups[0],value.groups[0]]}])
      await assert.rejects(read({...value,...patch}),/CANDIDATE_RESPONSE_INVALID/);
    for(const patch of [{threshold_usd:0},{threshold_usd:'1'},{coverage:1.1},{difference_usd:'2'},
      {sample_size:-1},{sample_size:1.5},{candidate_id:'bad'},{detail_sha256:'bad'},{evidence_status:'ROI_passed'}])
      await assert.rejects(read({...value,groups:[{...value.groups[0],points:[{...point,...patch}]}]}),/CANDIDATE_RESPONSE_INVALID/);
    await assert.rejects(read({...value,groups:[{...value.groups[0],points:[point,point]}]}));
  }finally{globalThis.fetch=original;}
});
test('candidate page binds report version and hashes without inventing missing summaries',()=>{
  const value=page();assert.equal(decodeCandidatePage(value,scope),value);
  assert.equal(value.items[0].summary,undefined);
  for(const patch of [{report_version:2},{catalog_sha256:'e'.repeat(64)},{page_size:100},{filtered_count:2},
    {items:[value.items[0],value.items[0]]},{priority_ids:['bad']}]){
    assert.throws(()=>decodeCandidatePage({...value,...patch},scope),/CANDIDATE_RESPONSE_INVALID/);
  }
});
test('complete and filtered export URLs are distinct and omit pagination',()=>{
  assert.match(candidateExportUrl(scope,'csv'),/scope=complete/);
  const url=candidateExportUrl(scope,'json',{page:2,window_hours:6,descending:false});
  assert.match(url,/scope=filtered/);assert.match(url,/window_hours=6/);assert.doesNotMatch(url,/page=/);
});
test('candidate detail rejects foreign versions, datasets, identities and hashes',()=>{
  const id='c'.repeat(64),dataset='synthetic-dataset';
  const value={run_id:scope.runId,report_version:1,report_sha256:scope.reportSha,catalog_sha256:scope.catalogSha,sha256:'d'.repeat(64),
    content:{schema_version:'2.0',run_id:scope.runId,dataset_id:dataset,candidate_id:id,frozen_sha256:'e'.repeat(64),
      event_spec:{predicate:{}},validation:{candidate_id:id,metrics:null,evidence_status:'insufficient_data',reasons:['UNAVAILABLE']},
      selection:{},exploration:{},source_diagnostics:null,revenue_decomposition:null,timing_status:'observed'}};
  assert.equal(decodeCandidateDetail(value,scope,id,dataset).validation.metrics,null);
  for(const patch of [{report_version:2},{sha256:'invalid'},{catalog_sha256:'f'.repeat(64)}])
    assert.throws(()=>decodeCandidateDetail({...value,...patch},scope,id,dataset));
  for(const patch of [{candidate_id:'f'.repeat(64)},{dataset_id:'other'},{timing_status:'guaranteed'}])
    assert.throws(()=>decodeCandidateDetail({...value,content:{...value.content,...patch}},scope,id,dataset));
});
