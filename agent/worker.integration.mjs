// Actual HTTP bridge + SDK, synthetic model only. Started by pytest.
import assert from 'node:assert/strict';
import {MockLanguageModelV4} from 'ai/test';
import {AgentWorker} from './dist/worker.js';
const [baseUrl,selectedCandidate,mode='success',turnId]=process.argv.slice(2);
const usage={inputTokens:{total:10,noCache:10,cacheRead:0,cacheWrite:0},outputTokens:{total:5,text:5,reasoning:0}};
const response=(content,reason='stop')=>({content,finishReason:{unified:reason,raw:reason},usage,warnings:[]});
let steps=0;
const model=new MockLanguageModelV4({doGenerate:async({prompt,abortSignal})=>{
  assert(prompt.some(m=>m.role==='user'&&JSON.stringify(m.content).includes(selectedCandidate)));
  steps++;
  if(mode==='failure')throw new Error('synthetic-private-provider-body');
  if(mode==='cancel'){
    const result=await fetch(`${baseUrl}/api/turns/${turnId}/cancel`,{method:'POST',headers:{'Idempotency-Key':'integration-cancel'}});
    assert.equal(result.status,200);
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error('renewal did not observe cancellation')),2000);
      const aborted=()=>{clearTimeout(timer);reject(abortSignal.reason);};
      if(abortSignal.aborted)aborted();else abortSignal.addEventListener('abort',aborted,{once:true});
    });
  }
  if(!prompt.some(m=>m.role==='tool'))return response([{type:'tool-call',toolCallId:'worker-read',toolName:'get_baseline_report',input:'{}'}],'tool-calls');
  // Exercise renewal while the model is working rather than only quick calls.
  await new Promise(resolve=>setTimeout(resolve,120));
  const evidence=prompt.filter(m=>m.role==='tool').at(-1).content[0].output.value;
  return response([{type:'text',text:`合成測試模型：目前候選 ${selectedCandidate}。 ${evidence.references[0].evidence_id}`}]);
}});
const config={baseUrl,token:process.env.AGENT_INTERNAL_TOKEN,heartbeatMs:30};
const worker=new AgentWorker(config,model);
assert.equal(await worker.runOnce(),true);
assert.equal(await worker.runOnce(),false);
assert.equal(worker.connected,true);assert.equal(steps,mode==='success'?2:1);
console.log(JSON.stringify({synthetic:true,steps,workerId:worker.workerId,bridge:true}));
