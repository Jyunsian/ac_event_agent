// Acceptance only: production Worker/SDK/tools; decisions explicitly synthetic, never a provider substitute.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {MockLanguageModelV4} from 'ai/test';
import {AgentWorker} from './dist/worker.js';
const usage={inputTokens:{total:10,noCache:10,cacheRead:0,cacheWrite:0},outputTokens:{total:5,text:5,reasoning:0}};
const response=(content,reason='stop')=>({content,finishReason:{unified:reason,raw:reason},usage,warnings:[]});
const call=(name,args,id)=>response([{type:'tool-call',toolName:name,toolCallId:id,input:JSON.stringify(args)}],'tool-calls');
const model=new MockLanguageModelV4({doGenerate:async({prompt})=>{
 const question=prompt.filter(m=>m.role==='user').map(m=>JSON.stringify(m.content)).filter(m=>!m.includes('目前介面引用')).at(-1)||'';
 const lastUser=prompt.findLastIndex(m=>m.role==='user');
 const outputs=prompt.slice(lastUser+1).filter(m=>m.role==='tool');
 if(!outputs.length)return call(question.includes('美國')?'profile_dataset':'get_baseline_report',{},'inspect');
 const last=outputs.at(-1).content[0].output.value;
 assert.notEqual(last.available,false,JSON.stringify(last));
 if(last.tool==='profile_dataset')return call('analyze_segment',{field:'country',value:'US'},'segment');
 if(last.tool==='get_baseline_report'){
  if(question.includes('重疊')){
   const ids=last.content.candidates.slice(0,3).map(c=>c.candidate_id);
   return ids.length===3?call('compare_candidates',{candidate_ids:ids},'compare'):
    call('search_candidates',{page:1},'search-all');
  }
  const args=question.includes('覆蓋率')?{thresholds:{count:[1,2],revenue_sum:[.01,.02]},hypothesis:'探索較低門檻的覆蓋率與收益取捨，尚未證明投放更好。'}:{windows_hours:[3]};
  return call('rerun_analysis',args,'rerun');
 }
 if(last.tool==='search_candidates'){
  const ids=last.content.items.slice(0,3).map(c=>c.candidate_id);
  if(ids.length<3)return response([{type:'text',text:`合成測試模型：這批資料沒有三個通過探索樣本門檻的實際候選，因此不能虛構人群重疊比較；請補足資料後再檢查。 ${last.content.report_evidence_id}`}]);
  return call('compare_candidates',{candidate_ids:ids},'compare');
 }
 if(['rerun_analysis','analyze_segment'].includes(last.tool))return call('evaluate_analysis',{child_run_id:last.child_run_id},'evaluate');
 if(last.tool==='evaluate_analysis')assert.equal(last.status,'succeeded');
 else assert.equal(last.tool,'compare_candidates');
 const explanation=question.includes('重疊')?'這是合成測試模型的長中文解釋，用來驗證閱讀、換行和引用，不代表真實模型能力或投放提升。\n'.repeat(40):'結果來自實際 Python 管線；小樣本和探索性限制仍保留，不代表投放提升。';
 return response([{type:'text',text:`合成測試模型：${explanation} ${last.references.at(-1).evidence_id}`}]);
}});
const shutdown=new AbortController();
const worker=new AgentWorker({baseUrl:process.argv[2],token:process.env.AGENT_INTERNAL_TOKEN,heartbeatMs:100},model);
const server=createServer((req,res)=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify({service:'agent',status:'alive',provider:{available:true},workerConnected:worker.connected,synthetic:true}));});
server.listen(Number(process.env.AC_TEST_HEALTH_PORT??0),process.env.AC_TEST_HEALTH_HOST??'127.0.0.1',()=>console.log(`http://127.0.0.1:${server.address().port}/health`));
void worker.run(shutdown.signal);
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>{shutdown.abort();server.close();});
