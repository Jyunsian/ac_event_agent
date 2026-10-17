import type {LanguageModel,ModelMessage} from 'ai';
import {runAgent,AgentRuntimeError,productionModel} from './runtime.js';
import {readTools,validateReferences} from './tools.js';
import {computeTools} from './compute-tools.js';
import {findingTools} from './finding-tools.js';
import {ToolJournal,type JournalRequest} from './tool-journal.js';
import {StepJournal,type StepRequest} from './step-journal.js';

export async function runReadonlyAgent({scope,config,messages,model,signal,limits,journalRequest,stepRequest}:{
  scope:{turn_id:string;parent_run_id:string;worker_id:string;fence:number};
  config:{baseUrl:string;token:string};messages:ModelMessage[];model?:LanguageModel;signal?:AbortSignal;
  limits?:{maxSteps?:number;timeoutMs?:number};
  journalRequest?:JournalRequest;
  stepRequest?:StepRequest;
}){
  const startedAt=Date.now();
  const allowed=new Set<string>();
  const journal=journalRequest?new ToolJournal(journalRequest,allowed):undefined;
  const tools={...readTools(scope,config,allowed),...computeTools(scope,config,allowed),...findingTools(scope,config,allowed)};
  const combined=journal?AbortSignal.any([journal.controller.signal,...(signal?[signal]:[])]):signal;
  const wrapped=journal?journal.wrap(tools):tools;
  const steps=stepRequest?new StepJournal(stepRequest):undefined;
  if(steps){
    model=model??productionModel();
    await steps.init(typeof model==='string'?model:model.modelId,limits);
  }
  const checkpoint=steps?.prefix??[];
  const recovered=journal?await journal.recover(wrapped,[...messages,...checkpoint],combined,checkpoint):[];
  const finalText=recovered.length===0?steps?.finalText():null;
  if(finalText){
    const citations=validateReferences(finalText,allowed);
    if(!citations.valid)throw new AgentRuntimeError('AGENT_REFERENCE_INVALID');
    return {text:finalText,steps:[],usage:undefined,status:'completed',citations:citations.cited,recovered:true};
  }
  if(steps){
    if(steps.remainingSteps<=0)throw new AgentRuntimeError('AGENT_STEP_LIMIT');
    if(steps.remainingMs<=0)throw new AgentRuntimeError('AGENT_TIMEOUT');
    steps.prefix=[...checkpoint,...recovered];
  }
  let result;
  try{result=await runAgent({messages:[...messages,...checkpoint,...recovered],model,signal:combined,
    maxSteps:steps?.remainingSteps??limits?.maxSteps,timeoutMs:steps?.remainingMs??limits?.timeoutMs,tools:wrapped,lifecycle:steps});}
  catch(error){if(steps?.error)throw steps.error;if(journal?.failed)throw new AgentRuntimeError('AGENT_RECOVERY_REQUIRED');throw error;}
  if(result.status==='output_limit')throw new AgentRuntimeError('AGENT_OUTPUT_LIMIT');
  if(result.status!=='completed')throw new AgentRuntimeError('AGENT_STEP_LIMIT');
  let citations=validateReferences(result.text,allowed);
  // One bounded formatting correction only for omitted citations. Never repair
  // invented/foreign references by silently replacing them with allowed IDs.
  if(!citations.valid&&citations.cited.length===0&&allowed.size>0){
    const remaining=(steps?steps.remainingSteps:limits?.maxSteps??8)-result.steps.length;
    const remainingMs=steps?.remainingMs??((limits?.timeoutMs??120000)-(Date.now()-startedAt));
    if(remaining<1)throw new AgentRuntimeError('AGENT_STEP_LIMIT');
    if(remainingMs<1)throw new AgentRuntimeError('AGENT_TIMEOUT');
    const correction:ModelMessage={role:'user',content:'你的草稿沒有附上必要的來源，因此尚未發布。請只修正回覆文字，附上支持說法的完整 evidence_id；不能新增分析或捏造來源。若某說法沒有依據就刪掉。字數限制不包括引用。以下是本輪工具實際交付、可供核對的引用（仍須依其原始內容選擇）：\n'+[...allowed].join('\n')};
    const history:ModelMessage[]=steps?[...steps.prefix]:[...checkpoint,...recovered,...result.steps.flatMap(step=>step.response.messages)];
    // Checkpoints retain model/tool outputs only. The deterministic correction
    // instruction is runtime-owned, not a new user message or tool receipt.
    let repaired;
    try{repaired=await runAgent({messages:[...messages,...history,correction],model,signal:combined,
      maxSteps:1,timeoutMs:remainingMs,tools:{},lifecycle:steps});}
    catch(error){if(steps?.error)throw steps.error;throw error;}
    if(repaired.status==='output_limit')throw new AgentRuntimeError('AGENT_OUTPUT_LIMIT');
    if(repaired.status!=='completed')throw new AgentRuntimeError('AGENT_STEP_LIMIT');
    citations=validateReferences(repaired.text,allowed);
    if(!citations.valid)throw new AgentRuntimeError('AGENT_REFERENCE_INVALID');
    return {...result,text:repaired.text,steps:[...result.steps,...repaired.steps],citations:citations.cited,repairUsage:repaired.usage};
  }
  if(!citations.valid)throw new AgentRuntimeError('AGENT_REFERENCE_INVALID');
  return {...result,citations:citations.cited};
}
