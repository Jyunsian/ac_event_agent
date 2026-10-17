// Real SDK + Node worker + HTTP + Python child; only model decisions are synthetic.
import assert from 'node:assert/strict';
import {MockLanguageModelV4} from 'ai/test';
import {AgentWorker} from './dist/worker.js';
const [baseUrl,mode='success']=process.argv.slice(2);
const usage={inputTokens:{total:10,noCache:10,cacheRead:0,cacheWrite:0},outputTokens:{total:5,text:5,reasoning:0}};
const response=(content,reason='stop')=>({content,finishReason:{unified:reason,raw:reason},usage,warnings:[]});
const call=(name,args,id)=>response([{type:'tool-call',toolName:name,toolCallId:id,input:JSON.stringify(args)}],'tool-calls');
let child,observed,steps=0;const children=[];let firstEvidence;
const model=new MockLanguageModelV4({doGenerate:async({prompt,abortSignal})=>{
  steps++;
  const outputs=prompt.filter(m=>m.role==='tool');
  if(!outputs.length){
    if(['adaptive','step_limit','timeout'].includes(mode))return call('get_exploration_budget',{},'budget');
    if(mode==='segment'){
      assert(prompt.some(m=>m.role==='user'&&JSON.stringify(m.content).includes('美國')));
      return call('analyze_segment',{field:'country',value:'US'},'segment-us');
    }
    assert(prompt.some(m=>m.role==='user'&&JSON.stringify(m.content).includes('前3小時')));
    return call('rerun_analysis',{windows_hours:[3],thresholds:{count:[2],revenue_sum:[.02]}},'rerun-3h');
  }
  const last=outputs.at(-1).content[0].output.value;
  assert.notEqual(last.available,false,JSON.stringify(last));
  if(['adaptive','step_limit','timeout'].includes(mode)&&last.tool==='get_exploration_budget'){
    assert.equal(last.budget.rounds_used,0);assert(last.budget.max_rounds>=2);
    return call('rerun_analysis',{windows_hours:[3],hypothesis:'先檢查較早窗口的覆蓋。'},'round-1');
  }
  if(mode==='adaptive'&&last.tool==='finalize_candidates'){
    assert.equal(last.status,'finalized');assert.equal(last.run_id,child);
    return response([{type:'text',text:`合成測試模型：根據第一輪低覆蓋結果擴大至24小時，已凍結探索候選，不是獨立驗證。${last.references[0].evidence_id}`}]);
  }
  if(last.tool==='rerun_analysis'||last.tool==='analyze_segment'){
    child=last.child_run_id;children.push(child);return call('evaluate_analysis',{child_run_id:child},`evaluate-${children.length}`);
  }
  assert.equal(last.tool,'evaluate_analysis');assert.equal(last.run_id,child);
  if(['queued','running'].includes(last.status))return call('evaluate_analysis',{child_run_id:child},`evaluate-${steps}`);
  assert.equal(last.status,'succeeded');
  if(mode==='timeout'){
    observed=last;
    await new Promise((resolve,reject)=>{
      if(abortSignal.aborted)reject(abortSignal.reason);
      else abortSignal.addEventListener('abort',()=>reject(abortSignal.reason),{once:true});
    });
  }
  if(mode==='adaptive'){
    if(children.length===1){
      const partialCoverage=last.content.candidates.some(c=>c.metrics?.coverage===.5);
      assert(partialCoverage,'First result must actually show half-cohort coverage before adapting');
      firstEvidence=last.references[0].evidence_id;
      return call('rerun_analysis',{windows_hours:[24],thresholds:{count:[1,2],revenue_sum:[3]},
        hypothesis:'第一輪優先候選只覆蓋半數用戶，擴大窗口檢查覆蓋與收益取捨。',based_on:[firstEvidence]},'round-2');
    }
    assert.equal(children.length,2);assert.deepEqual(last.content.config.windows_hours,[24]);observed=last;
    assert(last.content.candidates.length>=2,'The second round must have two actual distinct priority candidates to finalize');
    return call('finalize_candidates',{child_run_id:child,candidate_ids:last.content.candidates.slice(0,2).map(c=>c.candidate_id)},'finalize');
  }
  if(mode==='segment'){
    const segment=last.content.segment;
    assert.equal(segment.selected_users,3);assert.equal(segment.cohorts.exploration.users,2);
    assert.equal(segment.cohorts.holdout.users,1);assert.equal(segment.cohorts.holdout.arpu_usd,null);
    assert.equal(segment.evidence_status,'exploratory');observed=last;
    return response([{type:'text',text:`合成測試模型：美國子群已完成探索診斷，原切分保留，小樣本收益未顯示。${last.references[0].evidence_id}`}]);
  }
  assert.deepEqual(last.content.config.windows_hours,[3]);
  assert(last.content.candidates.length>0);
  assert(last.content.candidates.every(c=>c.event_spec.window_hours===3&&c.evidence_status==='exploratory'));
  observed=last;
  return response([{type:'text',text:`合成測試模型：已完成前3小時探索分支，非投放成效驗證。${last.references[0].evidence_id}`}]);
}});
const runtimeLimits=mode==='step_limit'?{maxSteps:3}:mode==='timeout'?{timeoutMs:20000}:undefined;
const worker=new AgentWorker({baseUrl,token:process.env.AGENT_INTERNAL_TOKEN,heartbeatMs:100,runtimeLimits},model);
assert.equal(await worker.runOnce(),true);
if(['step_limit','timeout'].includes(mode)){
  assert(child);if(mode==='timeout')assert(observed);
  console.log(JSON.stringify({synthetic:true,limited:mode,steps,child}));process.exit(0);
}
if(mode==='cancel'){
  assert.equal(observed,undefined);assert(child);
  console.log(JSON.stringify({synthetic:true,cancelled:true,steps,child}));
  process.exit(0);
}
assert(observed);assert(worker.connected);
console.log(JSON.stringify({synthetic:true,steps,child,result:observed,children,firstEvidence}));
