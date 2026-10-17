// Fault barrier in test harness only; production Worker, SDK and HTTP remain real.
import {MockLanguageModelV4} from 'ai/test';
import {AgentWorker} from './dist/worker.js';
const [base,mode]=process.argv.slice(2);
const originalFetch=globalThis.fetch;
let intercepted=false,generations=0;
const pause=async()=>{console.log(JSON.stringify({barrier:mode}));await new Promise(()=>{});};
globalThis.fetch=async(input,init)=>{
 const url=String(input);
 if(!intercepted&&((url.endsWith('/internal/tools/rerun_analysis')&&['before','after'].includes(mode))||
   (url.endsWith('/internal/agent/finish')&&mode==='finish'))){
  intercepted=true;
  if(mode!=='after')await pause();
  const response=await originalFetch(input,init);
  if(mode==='after'){if(response.status!==200)throw new Error('synthetic barrier tool did not commit');await pause();}
  return response;
 }
 return originalFetch(input,init);
};
const usage={inputTokens:{total:10},outputTokens:{total:5}};
const answer=(content,reason='stop')=>({content,finishReason:{unified:reason,raw:reason},usage,warnings:[]});
const call=(id,name,args)=>answer([{type:'tool-call',toolCallId:id,toolName:name,input:JSON.stringify(args)}],'tool-calls');
const model=new MockLanguageModelV4({doGenerate:async({prompt})=>{
 generations++;
 const results=prompt.filter(row=>row.role==='tool').flatMap(row=>row.content)
  .filter(part=>part.type==='tool-result'&&part.output.type==='json').map(part=>part.output.value);
 if(!results.some(row=>row.tool==='get_baseline_report'))return call('read','get_baseline_report',{});
 const branch=results.find(row=>row.tool==='rerun_analysis');
 if(!branch)return call('rerun','rerun_analysis',{windows_hours:[3],hypothesis:'合成恢復測試，不代表投放成效'});
 const result=results.filter(row=>row.tool==='evaluate_analysis').at(-1);
 if(!result||result.status==='queued'||result.status==='running')return call(`evaluate-${results.length}`,'evaluate_analysis',{child_run_id:branch.child_run_id});
 if(mode==='compute-failure'&&result.status==='failed')return answer([{type:'text',text:
  `合成計算失敗測試；基礎報告仍可閱讀。 ${results.find(row=>row.tool==='get_baseline_report').references[0].evidence_id}`}]);
 if(result.status!=='succeeded'||!result.references?.length)throw new Error('synthetic recovery child failed');
 if(mode==='model-failure')throw new Error('synthetic model failure after a published child');
 return answer([{type:'text',text:`合成恢復驗收；歷史相關性不代表投放提升。 ${result.references[0].evidence_id}`}]);
}});
await new AgentWorker({baseUrl:base,token:process.env.AGENT_INTERNAL_TOKEN,heartbeatMs:100},model).runOnce();
console.log(JSON.stringify({finished:true,generations}));
