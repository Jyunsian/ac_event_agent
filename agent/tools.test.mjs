import test from 'node:test';
import assert from 'node:assert/strict';
import {validateReferences,readTools} from './dist/tools.js';
import {computeTools} from './dist/compute-tools.js';
const ref='report:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa#/summary';
test('Chinese citation punctuation preserves exact allowlisted IDs',()=>{
 assert.equal(validateReferences(`依據（${ref}、${ref}）。`,new Set([ref])).valid,true);
 assert.equal(validateReferences(`（${ref}evil）`,new Set([ref])).valid,false);
 assert.equal(validateReferences('report:aaaaaaaa',new Set([ref])).valid,false);
});
test('safe business errors remain actionable without exposing server text',async()=>{
 const previous=globalThis.fetch;
 const tools=computeTools({turn_id:'x',parent_run_id:'y',worker_id:'z',fence:1},{baseUrl:'http://127.0.0.1',token:'synthetic'},new Set());
 try{
   globalThis.fetch=async()=>Response.json({error_code:'EXPLORATION_FINALIZED',message:'private server diagnostic'},{status:409});
   assert.deepEqual(await tools.rerun_analysis.execute({windows_hours:[3]},{toolCallId:'x',messages:[]}),{available:false,error_code:'EXPLORATION_FINALIZED'});
   globalThis.fetch=async()=>Response.json({error_code:'private server diagnostic'},{status:500});
   assert.deepEqual(await tools.rerun_analysis.execute({windows_hours:[3]},{toolCallId:'x',messages:[]}),{available:false,error_code:'TOOL_RERUN_FAILED'});
 }finally{globalThis.fetch=previous;}
});
test('compute tools expose only bounded immutable branch patches',()=>{
 const tools=computeTools({turn_id:'x',parent_run_id:'y',worker_id:'z',fence:1},{baseUrl:'http://127.0.0.1',token:'synthetic'},new Set());
 assert.deepEqual(Object.keys(tools),['get_exploration_budget','finalize_candidates','analyze_segment','rerun_analysis','evaluate_analysis']);
 assert(tools.rerun_analysis.inputSchema.safeParse({windows_hours:[3],thresholds:{count:[2],revenue_sum:[.02]}}).success);
 for(const args of [{},{windows_hours:[169]},{windows_hours:[0]},{windows_hours:[3,3]},{max_candidates:2001},
   {seed:0},{code:'print(1)'},{thresholds:{count:[1.5]}},{thresholds:{count:Array(21).fill(1)}},{thresholds:{sql:[1]}}]){
   assert.equal(tools.rerun_analysis.inputSchema.safeParse(args).success,false,JSON.stringify(args));
 }
});
test('child result scope and size checks withhold invalid evidence',async()=>{
 const previous=globalThis.fetch;const refs=new Set();
 const child='12345678-1234-4234-8234-123456789abc';
 const tools=computeTools({turn_id:'x',parent_run_id:'parent',worker_id:'z',fence:1},{baseUrl:'http://127.0.0.1',token:'synthetic'},refs);
 const execute=()=>tools.evaluate_analysis.execute({child_run_id:child},{toolCallId:'evaluate',messages:[]});
 try{
   globalThis.fetch=async()=>new Response(new Uint8Array(128*1024+1));assert.equal((await execute()).available,false);
   globalThis.fetch=async()=>Response.json({tool:'evaluate_analysis',parent_run_id:'foreign',run_id:child,status:'succeeded',references:[]});
   assert.equal((await execute()).available,false);
   globalThis.fetch=async()=>Response.json({tool:'evaluate_analysis',parent_run_id:'parent',run_id:child,status:'succeeded',report_version:1,
    references:[{evidence_id:ref,artifact_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',run_id:'foreign',json_pointer:'/summary',sha256:'a'.repeat(64)}]});
   assert.equal((await execute()).available,false);assert.equal(refs.size,0);
 }finally{globalThis.fetch=previous;}
});
test('references reject foreign and malformed pointers, not just matching a prefix',()=>{
 const allowed=new Set([ref]);
 assert.equal(validateReferences(`依據 [報告](${ref})。`,allowed).valid,true);
 assert.equal(validateReferences('依據 `'+ref+'`。',allowed).valid,true);
 assert.equal(validateReferences('依據 `'+ref+'evil`。',allowed).valid,false);
 for(const answer of ['No evidence',ref+'evil',ref.replace('/summary','/private'),`${ref} report:foreign#/summary`])assert.equal(validateReferences(answer,allowed).valid,false);
});
test('four bounded readonly tools are registered',()=>{
 const tools=readTools({turn_id:'x',parent_run_id:'y',worker_id:'z',fence:1},{baseUrl:'http://127.0.0.1',token:'synthetic'},new Set());
 assert.deepEqual(Object.keys(tools),['profile_dataset','get_baseline_report','compare_candidates','search_candidates']);
 assert.equal(tools.search_candidates.inputSchema.safeParse({page:41}).success,false);
 assert.equal(tools.search_candidates.inputSchema.safeParse({run_id:'other'}).success,false);
 assert.equal(tools.get_baseline_report.inputSchema.safeParse({run_id:'other'}).success,false);
 assert.equal(tools.compare_candidates.inputSchema.safeParse({candidate_ids:Array(11).fill('x')}).success,false);
});
test('oversized, wrong scope and aborted tool responses never supply evidence',async()=>{
 const previous=globalThis.fetch;const refs=new Set();
 const tools=readTools({turn_id:'x',parent_run_id:'y',worker_id:'z',fence:1},{baseUrl:'http://127.0.0.1',token:'synthetic'},refs);
 const execute=signal=>tools.get_baseline_report.execute({}, {toolCallId:'test',messages:[],abortSignal:signal});
 try{
  globalThis.fetch=async()=>new Response(new Uint8Array(128*1024+1));
  assert.equal((await execute()).available,false);
  globalThis.fetch=async()=>Response.json({run_id:'other',tool:'get_baseline_report',references:[]});
  assert.equal((await execute()).available,false);
  globalThis.fetch=async(url,options)=>{options.signal.throwIfAborted();throw new Error('unreachable');};
  const controller=new AbortController();controller.abort();assert.equal((await execute(controller.signal)).available,false);
  assert.equal(refs.size,0);
 }finally{globalThis.fetch=previous;}
});
import {findingTools} from './dist/finding-tools.js';

test('findings tools reject scope, unbounded inputs and unverified evidence',async()=>{
 const refs=new Set();const previous=globalThis.fetch;
 const tools=findingTools({turn_id:'turn',parent_run_id:'parent',worker_id:'worker',fence:1},
  {baseUrl:'http://127.0.0.1',token:'synthetic'},refs);
 assert.deepEqual(Object.keys(tools),['load_app_findings','save_findings']);
 assert.equal(tools.load_app_findings.inputSchema.safeParse({app_id:'foreign'}).success,false);
 assert.equal(tools.load_app_findings.inputSchema.safeParse({limit:11}).success,false);
 const args={candidate_id:'candidate',hypothesis:'observation',limitations:['small sample'],counterexamples:[]};
 assert(tools.save_findings.inputSchema.safeParse(args).success);
 for(const patch of [{limitations:[]},{outcome:'supported'},{outcome:'historically_validated'},{metrics:{revenue:10}}])
  assert.equal(tools.save_findings.inputSchema.safeParse({...args,...patch}).success,false);
 try{
  const execute=()=>tools.load_app_findings.execute({},{toolCallId:'load',messages:[]});
  globalThis.fetch=async()=>Response.json({tool:'load_app_findings',parent_run_id:'foreign',items:[],references:[]});
  assert.equal((await execute()).available,false);
  globalThis.fetch=async()=>new Response(new Uint8Array(128*1024+1));
  assert.equal((await execute()).available,false);
  globalThis.fetch=async()=>Response.json({error_code:'private detail'},{status:500});
  assert.deepEqual(await execute(),{available:false,error_code:'TOOL_FINDINGS_FAILED'});
  globalThis.fetch=async()=>Response.json({tool:'load_app_findings',parent_run_id:'parent',app_id:'app',next_cursor:null,items:[],references:[]});
  assert.deepEqual((await execute()).items,[]);assert.equal(refs.size,0);
 }finally{globalThis.fetch=previous;}
});
