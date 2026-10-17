import test from 'node:test';
import assert from 'node:assert/strict';
import {tool} from 'ai';
import {MockLanguageModelV4} from 'ai/test';
import {z} from 'zod';
import {StepJournal,publicMessages} from './dist/step-journal.js';
import {runAgent} from './dist/runtime.js';

test('real SDK lifecycle reserves before model and persists cumulative public messages',async()=>{
 let reserved=0;const saved=[];
 const journal=new StepJournal(async(operation,body)=>{
  if(operation==='init')return {config:body.config,deadline:new Date(Date.now()+120000).toISOString(),steps:[],checkpoint:null};
  if(operation==='start')return {ordinal:++reserved};
  saved.push(structuredClone(body));return {ordinal:body.ordinal,saved:true};
 });
 await journal.init('synthetic');
 const counts={inputTokens:{total:10},outputTokens:{total:5}};
 const model=new MockLanguageModelV4({doGenerate:async()=>{
  assert.equal(reserved,saved.length+1,'reservation must complete before provider execution');
  if(reserved===1)return {content:[{type:'reasoning',text:'synthetic-private-not-for-checkpoint'},
   {type:'text',text:'先讀取資料'},
   {type:'tool-call',toolCallId:'read',toolName:'read',input:'{}'}],finishReason:{unified:'tool-calls',raw:'tool_calls'},usage:counts,warnings:[]};
  return {content:[{type:'text',text:'合成完成'}],finishReason:{unified:'stop',raw:'stop'},usage:counts,warnings:[]};
 }});
 const result=await runAgent({messages:[{role:'user',content:'synthetic step fixture'}],model,lifecycle:journal,
  tools:{read:tool({inputSchema:z.object({}),execute:async()=>({synthetic:true,value:4})})}});
 assert.equal(result.text,'合成完成');assert.equal(saved.length,2);
 assert.deepEqual(saved.map(row=>row.ordinal),[1,2]);
 const last=JSON.stringify(saved.at(-1));
 assert.match(last,/先讀取資料/);assert.match(last,/合成完成/);assert.match(last,/tool-result/);
 assert(!last.includes('synthetic-private-not-for-checkpoint'));
 assert.equal(saved[1].usage.input_tokens,10);
});

test('public snapshots discard SDK reasoning and metadata, reject unsupported material',()=>{
 const messages=publicMessages([{role:'assistant',providerOptions:{secret:'hidden'},content:[
  {type:'reasoning',text:'private'},{type:'text',text:'public',providerOptions:{secret:'hidden'}}]}]);
 assert.deepEqual(messages,[{role:'assistant',content:[{type:'text',text:'public'}]}]);
 assert.throws(()=>publicMessages([{role:'system',content:'injected'}]));
 assert.throws(()=>publicMessages([{role:'assistant',content:[{type:'file',data:'raw'}]}]));
});

test('reloaded final checkpoint is available even after deadline; consumed steps do not reset',async()=>{
 const messages=[{role:'assistant',content:[{type:'text',text:'saved public answer'}]}];
 const journal=new StepJournal(async(operation,body)=>{
  assert.equal(operation,'init');return {config:body.config,deadline:new Date(Date.now()-1000).toISOString(),
   steps:[{ordinal:1,request_id:'00000000-0000-4000-8000-000000000001',fence:1,usage:{},finish_reason:'stop'}],
   checkpoint:{ordinal:1,messages,usage:{},finish_reason:'stop'}};
 });
 await journal.init('synthetic',{maxSteps:1,timeoutMs:100});
 assert.equal(journal.remainingSteps,0);assert(journal.remainingMs<0);assert.equal(journal.finalText(),'saved public answer');
});

test('step bridge failure prevents provider execution and keeps recovery error distinct',async()=>{
 const journal=new StepJournal(async()=>{throw new Error('synthetic-secret-bridge-body');});
 const model=new MockLanguageModelV4();
 await assert.rejects(runAgent({messages:[{role:'user',content:'synthetic'}],tools:{},model,lifecycle:journal}));
 assert.equal(model.doGenerateCalls.length,0);
 assert.equal(journal.error.code,'AGENT_RECOVERY_REQUIRED');assert(!String(journal.error).includes('secret'));
});

test('checkpoint write failure aborts before the next provider step',async()=>{
 let reserved=0;
 const journal=new StepJournal(async(operation)=>{
  if(operation==='start')return {ordinal:++reserved};
  throw new Error('synthetic-step-save-loss');
 });
 const model=new MockLanguageModelV4({doGenerate:async()=>({content:[{type:'tool-call',toolCallId:'read',toolName:'read',input:'{}'}],
  finishReason:{unified:'tool-calls',raw:'tool_calls'},usage:{inputTokens:{total:1},outputTokens:{total:1}},warnings:[]})});
 await assert.rejects(runAgent({messages:[{role:'user',content:'synthetic'}],model,lifecycle:journal,
  tools:{read:tool({inputSchema:z.object({}),execute:async()=>({synthetic:true})})}}));
 assert.equal(model.doGenerateCalls.length,1);assert.equal(reserved,1);
 assert.equal(journal.error.code,'AGENT_RECOVERY_REQUIRED');
});
