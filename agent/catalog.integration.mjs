// Synthetic model, real SDK tool loop and HTTP/PG/S3 evidence.
import assert from 'node:assert/strict';
import {MockLanguageModelV4} from 'ai/test';
import {runReadonlyAgent} from './dist/readonly-agent.js';
import {findingTools} from './dist/finding-tools.js';
const [baseUrl, scopeJSON] = process.argv.slice(2);
const scope = JSON.parse(scopeJSON);
const usage = {inputTokens:{total:10,noCache:10,cacheRead:0,cacheWrite:0},outputTokens:{total:5,text:5,reasoning:0}};
const response = (content, reason='stop') => ({content, finishReason:{unified:reason,raw:reason},usage,warnings:[]});
const call = (name, input) => response([{type:'tool-call',toolCallId:name,toolName:name,input:JSON.stringify(input)}],'tool-calls');
let identity;
const model = new MockLanguageModelV4({doGenerate:async({prompt})=>{
  const outputs = prompt.filter(m=>m.role==='tool');
  if (!outputs.length) return call('search_candidates',{page:1,role:'unselected'});
  const last = outputs.at(-1).content[0].output.value;
  assert.equal(last.run_id,scope.parent_run_id);
  if (last.tool==='search_candidates') {
    assert(last.content.items.length>0 && last.content.items.length<=50);
    identity = last.content.items[0].candidate_id;
    return call('compare_candidates',{candidate_ids:[identity]});
  }
  assert.equal(last.tool,'compare_candidates');
  assert.equal(last.content.candidates[0].candidate_id,identity);
  assert.match(last.references[0].json_pointer,/^\/entries\/\d+$/);
  return response([{type:'text',text:`合成模型：非優先候選的歷史證據，不代表投放效果。${last.references[0].evidence_id}`}]);
}});
const config={baseUrl,token:process.env.AGENT_INTERNAL_TOKEN};
const journalRequest=async(operation,body)=>{
  const result=await fetch(`${baseUrl}/internal/agent/journal/${operation}`,{method:'POST',
    headers:{'Content-Type':'application/json',Authorization:`Bearer ${config.token}`},
    body:JSON.stringify({turn_id:scope.turn_id,worker_id:scope.worker_id,fence:scope.fence,...body})});
  assert.equal(result.status,200,await result.clone().text());
  return result.json();
};
const result = await runReadonlyAgent({scope,config,model,journalRequest,
  messages:[{role:'user',content:'查看非優先候選並比較證據'}]});
assert.equal(result.steps.length,3);
assert.equal(result.citations.length,1);
const resumed = await runReadonlyAgent({scope,config,model,journalRequest,
  messages:[{role:'user',content:'查看非優先候選並比較證據'}]});
assert.equal(resumed.citations[0],result.citations[0]);
const findingRefs=new Set();
const findings=findingTools(scope,config,findingRefs);
const saved=await findings.save_findings.execute({candidate_id:identity,hypothesis:'合成Node測試：保存完整清單候選',
  limitations:['不足以证明投放收益'],counterexamples:[]},{toolCallId:'node-save-catalog',messages:[]});
assert(saved.finding_id);
assert.match(saved.references[0].json_pointer,/^\/entries\/\d+$/);
assert(findingRefs.has(saved.references[0].evidence_id));
const loaded=await findings.load_app_findings.execute({limit:5},{toolCallId:'node-load-catalog',messages:[]});
assert(loaded.items.some(item=>item.candidate_id===identity));
console.log(JSON.stringify({steps:result.steps.length,candidate_id:identity,citation:result.citations[0]}));
