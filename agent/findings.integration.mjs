// Synthetic model decisions; real SDK, tools, HTTP and persistent evidence.
import assert from 'node:assert/strict';
import {MockLanguageModelV4} from 'ai/test';
import {runReadonlyAgent} from './dist/readonly-agent.js';
const [baseUrl,turn_id,parent_run_id,worker_id,fence]=process.argv.slice(2);
const usage={inputTokens:{total:10,noCache:10,cacheRead:0,cacheWrite:0},outputTokens:{total:5,text:5,reasoning:0}};
const response=(content,reason='stop')=>({content,finishReason:{unified:reason,raw:reason},usage,warnings:[]});
const call=(toolName,args,toolCallId)=>response([{type:'tool-call',toolName,toolCallId,input:JSON.stringify(args)}],'tool-calls');
let steps=0,finding;
const model=new MockLanguageModelV4({doGenerate:async({prompt})=>{
 steps++;
 const outputs=prompt.filter(m=>m.role==='tool');
 if(!outputs.length)return call('get_baseline_report',{},'finding-report');
 const result=outputs.at(-1).content[0].output.value;
 assert.notEqual(result.available,false,JSON.stringify(result));
 if(result.tool==='get_baseline_report')return call('save_findings',{
  candidate_id:result.content.candidates[0].candidate_id,hypothesis:'SDK合成測試觀察',
  limitations:['小樣本，不代表投放成效'],counterexamples:[]},'sdk-save');
 if(result.tool==='save_findings'){
  finding=result.finding_id;assert.equal(result.requires_new_batch_validation,true);
  return call('load_app_findings',{limit:5},'sdk-load');
 }
 assert.equal(result.tool,'load_app_findings');
 const item=result.items.find(x=>x.id===finding);assert(item);
 assert.equal(item.requires_new_batch_validation,true);assert.equal(item.outcome,'observation');
 return response([{type:'text',text:`合成測試：已保存並讀回觀察，仍需新批次驗證。${item.evidence_id}`}]);
}});
const result=await runReadonlyAgent({scope:{turn_id,parent_run_id,worker_id,fence:Number(fence)},
 config:{baseUrl,token:process.env.AGENT_INTERNAL_TOKEN},messages:[{role:'user',content:'保存並讀回此App的候選觀察'}],model});
assert.equal(steps,4);assert.equal(result.status,'completed');assert(result.citations.length);
console.log(JSON.stringify({synthetic:true,steps,finding,citations:result.citations}));
