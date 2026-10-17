// Called by pytest with an actual isolated HTTP API + PostgreSQL + S3 report.
import assert from 'node:assert/strict';
import {MockLanguageModelV4} from 'ai/test';
import {runReadonlyAgent} from './dist/readonly-agent.js';
const [url,scopeJSON,candidateJSON]=process.argv.slice(2);
const scope=JSON.parse(scopeJSON),ids=JSON.parse(candidateJSON);
const usage={inputTokens:{total:10,noCache:10,cacheRead:0,cacheWrite:0},outputTokens:{total:5,text:5,reasoning:0}};
const response=(content,reason='stop')=>({content,finishReason:{unified:reason,raw:reason},usage,warnings:[]});
const call=(name,input,n)=>response([{type:'tool-call',toolCallId:`call-${n}`,toolName:name,input:JSON.stringify(input)}],'tool-calls');
let step=0;const seen=[];
const model=new MockLanguageModelV4({doGenerate:async({prompt})=>{
 const toolMessages=prompt.filter(m=>m.role==='tool');
 if(step===0){step++;return call('profile_dataset',{},step);}
 const last=toolMessages.at(-1).content[0].output.value;
 assert.equal(last.run_id,scope.parent_run_id);assert(last.references.length>0);seen.push(last.tool);
 if(step===1){step++;return call('get_baseline_report',{},step);}
 if(step===2){step++;return call('compare_candidates',{candidate_ids:ids},step);}
 assert.deepEqual(last.content.candidates.map(c=>c.candidate_id),ids);
 return response([{type:'text',text:`合成測試模型：只描述已讀報告。${last.references[0].evidence_id}`}]);
}});
const config={baseUrl:url,token:process.env.AGENT_INTERNAL_TOKEN};
const result=await runReadonlyAgent({scope,config,model,messages:[{role:'user',content:'Synthetic integration: compare existing candidates only.'}]});
assert.deepEqual(seen,['profile_dataset','get_baseline_report','compare_candidates']);
assert.equal(result.steps.length,4);assert.equal(result.citations.length,1);
const invalid=new MockLanguageModelV4({doGenerate:async()=>response([{type:'text',text:'Fabricated report:foreign#/summary'}])});
await assert.rejects(runReadonlyAgent({scope,config,model:invalid,messages:[{role:'user',content:'Synthetic invalid citation'}]}),{code:'AGENT_REFERENCE_INVALID'});
let repairStep=0;
const repairModel=new MockLanguageModelV4({doGenerate:async({prompt})=>{
 if(repairStep++===0)return call('get_baseline_report',{},'repair-read');
 if(repairStep===2)return response([{type:'text',text:'合成模型漏附引用的草稿。'}]);
 const last=prompt.filter(m=>m.role==='tool').at(-1).content[0].output.value;
 return response([{type:'text',text:`合成模型補正引用。${last.references[0].evidence_id}`}]);
}});
let savedConfig;
const stepRequest=async(operation,body)=>{
 if(operation==='init')savedConfig=body.config;
 const response=await fetch(`${url}/internal/agent/steps/${operation}`,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${config.token}`},body:JSON.stringify({turn_id:scope.turn_id,worker_id:scope.worker_id,fence:scope.fence,...body})});
 assert.equal(response.status,200);return response.json();
};
const journalRequest=async(operation,body)=>{
 const response=await fetch(`${url}/internal/agent/journal/${operation}`,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${config.token}`},body:JSON.stringify({turn_id:scope.turn_id,worker_id:scope.worker_id,fence:scope.fence,...body})});
 assert.equal(response.status,200);return response.json();
};
const repaired=await runReadonlyAgent({scope,config,model:repairModel,messages:[{role:'user',content:'Synthetic citation correction'}],stepRequest,journalRequest});
assert.equal(repaired.steps.length,3);assert.equal(repairStep,3);assert.equal(repaired.citations.length,1);
assert.equal(repairModel.doGenerateCalls[2].tools?.length??0,0);
const persisted=await stepRequest('init',{config:savedConfig});
assert.equal(persisted.steps.length,3);assert.equal(persisted.checkpoint.finish_reason,'stop');
assert(persisted.checkpoint.messages.every(m=>['assistant','tool'].includes(m.role)));
assert(persisted.checkpoint.messages.at(-1).content.some(p=>p.type==='text'&&p.text.includes(repaired.citations[0])));
const reopened=await runReadonlyAgent({scope,config,model:repairModel,messages:[{role:'user',content:'Synthetic citation correction'}],stepRequest,journalRequest});
assert.equal(reopened.recovered,true);assert.equal(reopened.text,repaired.text);assert.equal(repairStep,3);
for(const scenario of ['foreign','missing','budget']){
 let calls=0;
 const stubborn=new MockLanguageModelV4({doGenerate:async()=>{
  if(calls++===0)return call('get_baseline_report',{},`check-${scenario}`);
  return response([{type:'text',text:scenario==='foreign'?'Fabricated report:foreign#/summary':'Still no citation'}]);
 }});
 await assert.rejects(runReadonlyAgent({scope,config,model:stubborn,messages:[{role:'user',content:'Synthetic bounded correction'}],limits:scenario==='budget'?{maxSteps:2}:undefined}),
  {code:scenario==='budget'?'AGENT_STEP_LIMIT':'AGENT_REFERENCE_INVALID'});
 assert.equal(calls,scenario==='missing'?3:2);
}
console.log(JSON.stringify({synthetic:true,steps:result.steps.length,tools:seen,citations:result.citations,invalidReferenceRejected:true}));
