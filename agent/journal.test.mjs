import test from 'node:test';
import assert from 'node:assert/strict';
import {tool} from 'ai';
import {z} from 'zod';
import {ToolJournal} from './dist/tool-journal.js';
import {runAgent} from './dist/runtime.js';
import {MockLanguageModelV4} from 'ai/test';

// In-memory fault fixture for wrapper ordering only; PostgreSQL/HTTP is tested separately.
function store(fault){
 const calls=[];let fail=true;
 return async(operation,body)=>{
  if(operation==='load')return {calls:structuredClone(calls)};
  let call=calls.find(c=>c.tool_call_id===body.tool_call_id);
  if(operation==='begin'){
   if(!call){call={tool_call_id:body.tool_call_id,ordinal:calls.length+1,tool_name:body.tool_name,
    arguments:body.arguments,input_sha256:'a'.repeat(64),output:null,output_sha256:null};calls.push(call);}
   if(fault==='after-intent'&&fail){fail=false;throw new Error('synthetic-response-loss');}
  }else{
   call.output=body.output;call.output_sha256='b'.repeat(64);
   if(fault==='after-result'&&fail){fail=false;throw new Error('synthetic-response-loss');}
  }
  return {tool_call_id:call.tool_call_id,state:call.output===null?'pending':'completed',output:call.output};
 };
}

for(const fault of ['after-intent','after-result'])test(`journal restores ${fault} using original tool identity`,async()=>{
 const request=store(fault);let executed=0;const identities=[];
 const ref={artifact_id:'synthetic-artifact',json_pointer:'/summary',evidence_id:'report:synthetic-artifact#/summary'};
 const tools={evidence:tool({inputSchema:z.object({n:z.number()}).strict(),execute:async({n},options)=>{
  executed++;identities.push(options.toolCallId);return {value:n,references:[ref]};}})};
 const old=new ToolJournal(request,new Set());const wrapped=old.wrap(tools);
 await assert.rejects(wrapped.evidence.execute({n:3},{toolCallId:'original',messages:[],context:undefined}),{code:'AGENT_RECOVERY_REQUIRED'});
 assert.equal(old.controller.signal.aborted,true);
 assert.equal(executed,fault==='after-intent'?0:1);
 const allowed=new Set();const replacement=new ToolJournal(request,allowed);
 const messages=await replacement.recover(replacement.wrap(tools),[]);
 assert.equal(executed,1);assert.deepEqual(identities,['original']);assert(allowed.has(ref.evidence_id));
 assert.equal(messages[0].content[0].toolCallId,messages[1].content[0].toolCallId);
 const model=new MockLanguageModelV4({doGenerate:async({prompt})=>{
  assert.match(JSON.stringify(prompt),/original/);assert.match(JSON.stringify(prompt),/"value":3/);
  return {content:[{type:'text',text:ref.evidence_id}],finishReason:{unified:'stop',raw:'stop'},
   usage:{inputTokens:{total:1},outputTokens:{total:1}},warnings:[]};}});
 const result=await runAgent({messages:[{role:'user',content:'synthetic recovery'},...messages],model,tools:replacement.wrap(tools)});
 assert.equal(result.text,ref.evidence_id);assert.equal(executed,1);
});

test('ambiguous tool transport failure leaves original intent pending',async()=>{
 const request=store();const journal=new ToolJournal(request,new Set());
 const tools=journal.wrap({evidence:tool({inputSchema:z.object({}),execute:async()=>({available:false,error_code:'TOOL_RERUN_FAILED'})})});
 await assert.rejects(tools.evidence.execute({},{toolCallId:'pending',messages:[],context:undefined}),{code:'AGENT_RECOVERY_REQUIRED'});
 assert.equal((await request('load',{})).calls[0].output,null);
});

test('recovery rejects persisted arguments before executing incompatible tool',async()=>{
 const request=store();await request('begin',{tool_call_id:'bad',tool_name:'evidence',arguments:{n:'not-a-number'}});
 let executed=0;const journal=new ToolJournal(request,new Set());
 const tools=journal.wrap({evidence:tool({inputSchema:z.object({n:z.number()}),execute:async()=>{executed++;return {};}})});
 await assert.rejects(journal.recover(tools,[]),{code:'AGENT_RECOVERY_REQUIRED'});assert.equal(executed,0);
});
