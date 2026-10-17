import test from 'node:test';
import assert from 'node:assert/strict';
import {MockLanguageModelV4} from 'ai/test';
import {tool} from 'ai';
import {z} from 'zod';
import {runAgent,productionModel,providerStatus} from './dist/runtime.js';
const usage={inputTokens:{total:10,noCache:10,cacheRead:0,cacheWrite:0},outputTokens:{total:5,text:5,reasoning:0}};
const response=(content,reason='stop')=>({content,finishReason:{unified:reason,raw:reason},usage,warnings:[]});
const call=(id,n)=>response([{type:'tool-call',toolCallId:id,toolName:'evidence',input:JSON.stringify({n})}],'tool-calls');
const messages=[{role:'user',content:'Synthetic SDK integration test; no customer logs.'}];
test('truncated provider output is not a completed answer',async()=>{
 const model=new MockLanguageModelV4({doGenerate:response([{type:'text',text:'partial report:aaaa'}],'length')});
 const result=await runAgent({messages,model,tools:{}});
 assert.equal(result.status,'output_limit');
 assert.equal(model.doGenerateCalls[0].maxOutputTokens,8192);
});
test('real SDK executes two tool rounds and propagates each result',async()=>{
 const executed=[];
 const model=new MockLanguageModelV4({doGenerate:[call('one',1),call('two',2),response([{type:'text',text:'Synthetic final result'}])]});
 const result=await runAgent({messages,model,tools:{evidence:tool({inputSchema:z.object({n:z.number()}),execute:async({n})=>{executed.push(n);return {synthetic:true,value:n*2};}})}});
 assert.deepEqual(executed,[1,2]);assert.equal(result.steps.length,3);assert.equal(result.status,'completed');
 assert.equal(result.text,'Synthetic final result');assert.equal(result.usage.inputTokens,30);
 assert.match(JSON.stringify(model.doGenerateCalls[1].prompt),/"value":2/);
 assert.match(JSON.stringify(model.doGenerateCalls[2].prompt),/"value":4/);
});
test('SDK step limit bounds tool execution',async()=>{
 let executed=0;const model=new MockLanguageModelV4({doGenerate:async()=>call(`call-${executed}`,1)});
 const result=await runAgent({messages,model,maxSteps:2,tools:{evidence:tool({inputSchema:z.object({n:z.number()}),execute:async()=>++executed})}});
 assert.equal(executed,2);assert.equal(model.doGenerateCalls.length,2);assert.equal(result.status,'step_limit');
});
test('provider failure is sanitized and not retried',async()=>{
 const model=new MockLanguageModelV4({doGenerate:async()=>{throw new Error('secret-sentinel-provider-body');}});
 await assert.rejects(runAgent({messages,model,tools:{}}),e=>e.code==='AGENT_MODEL_FAILED'&&!String(e).includes('secret-sentinel'));
 assert.equal(model.doGenerateCalls.length,1);
});
test('pre-cancel and mid-call cancel propagate without success',async()=>{
 const before=new AbortController();before.abort();const unused=new MockLanguageModelV4();
 await assert.rejects(runAgent({messages,model:unused,tools:{},signal:before.signal}),{code:'AGENT_CANCELLED'});
 assert.equal(unused.doGenerateCalls.length,0);
 const controller=new AbortController();
 const model=new MockLanguageModelV4({doGenerate:async({abortSignal})=>{controller.abort();abortSignal.throwIfAborted();throw new Error('unreachable');}});
 await assert.rejects(runAgent({messages,model,tools:{},signal:controller.signal}),{code:'AGENT_CANCELLED'});
});
test('missing key is unavailable; configured provider constructs without calling network',()=>{
 assert.equal(providerStatus({}).available,false);
 assert.throws(()=>productionModel({}),{code:'OPENROUTER_NOT_CONFIGURED'});
 const model=productionModel({OPENROUTER_API_KEY:'synthetic-not-a-real-key',OPENROUTER_MODEL:'synthetic/model'});
 assert.equal(model.modelId,'synthetic/model');
});
test('timeout aborts an in-flight SDK model',async()=>{
 const model=new MockLanguageModelV4({doGenerate:async({abortSignal})=>new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>reject(new Error('test watchdog')),1000);
   abortSignal.addEventListener('abort',()=>{clearTimeout(timer);reject(abortSignal.reason);},{once:true});
 })});
 await assert.rejects(runAgent({messages,model,tools:{},timeoutMs:20}),{code:'AGENT_TIMEOUT'});
});
test('SDK exposes a tool failure to the next step instead of a fake result',async()=>{
 const model=new MockLanguageModelV4({doGenerate:[call('failure',1),response([{type:'text',text:'Synthetic: evidence unavailable.'}])]});
 const result=await runAgent({messages,model,tools:{evidence:tool({inputSchema:z.object({n:z.number()}),execute:async()=>{throw new Error('EVIDENCE_UNAVAILABLE');}})}});
 assert.match(JSON.stringify(model.doGenerateCalls[1].prompt),/EVIDENCE_UNAVAILABLE/);
 assert.equal(result.text,'Synthetic: evidence unavailable.');
});
