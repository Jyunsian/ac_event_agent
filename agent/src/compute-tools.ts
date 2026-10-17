import {tool} from 'ai';
import {z} from 'zod';
import {setTimeout as delay} from 'node:timers/promises';

type Scope={turn_id:string;parent_run_id:string;worker_id:string;fence:number};
const countGrid=z.array(z.number().int().min(1).max(1000000)).min(1).max(20).refine(v=>new Set(v).size===v.length);
const valueGrid=z.array(z.number().positive().max(1000000)).min(1).max(20).refine(v=>new Set(v).size===v.length);
const thresholds=z.object({count:countGrid.optional(),session_count:countGrid.optional(),revenue_sum:valueGrid.optional(),engaged_seconds:valueGrid.optional(),ad_count:valueGrid.optional(),ad_revenue_sum:valueGrid.optional(),first_return_delay_seconds:valueGrid.optional(),return_in_interval:valueGrid.optional(),return_interval_count:valueGrid.optional(),consecutive_return_days:valueGrid.optional(),post_return_session_count:valueGrid.optional(),post_return_engaged_seconds:valueGrid.optional(),level_start_count:valueGrid.optional(),level_complete_count:valueGrid.optional(),distinct_completed_levels:valueGrid.optional(),max_completed_level_index:valueGrid.optional(),completed_level:valueGrid.optional(),reached_level:valueGrid.optional(),level_time_to_reach_seconds:valueGrid.optional(),completes_per_session:valueGrid.optional(),level_fail_count:valueGrid.optional(),retry_same_level:valueGrid.optional(),complete_after_fail:valueGrid.optional(),session_after_fail:valueGrid.optional(),attempts_per_level:valueGrid.optional(),complete_start_ratio:valueGrid.optional(),fail_start_ratio:valueGrid.optional(),completion_duration_seconds:valueGrid.optional(),consecutive_failures:valueGrid.optional(),level_start_to_complete:countGrid.optional(),level_fail_to_start:countGrid.optional(),level_fail_to_complete:countGrid.optional(),level_fail_to_session_end:countGrid.optional(),session_start_to_level_complete:countGrid.optional(),level_complete_to_ad_impression:countGrid.optional(),rewarded_ad_to_level_complete:countGrid.optional()}).strict().refine(v=>Object.keys(v).length>0);
const rerunSchema=z.object({windows_hours:z.array(z.number().positive().max(168)).min(1).max(10)
  .refine(v=>new Set(v).size===v.length).optional(),thresholds:thresholds.optional(),
  max_candidates:z.number().int().min(1).max(2000).optional(),
  hypothesis:z.string().min(1).max(1000).refine(v=>v.trim().length>0).optional(),
  based_on:z.array(z.string().min(1).max(500)).max(10).refine(v=>new Set(v).size===v.length).optional()
}).strict().refine(v=>v.windows_hours!==undefined||v.thresholds!==undefined||v.max_candidates!==undefined);
const statuses=new Set(['queued','running','succeeded','failed','cancelled']);
const businessErrors=new Set(['EXPLORATION_FINALIZED','EXPLORATION_TIME_LIMIT','EXPLORATION_ROUND_LIMIT',
  'EXPLORATION_CANDIDATE_LIMIT','TOOL_CANDIDATE_BUDGET_EXCEEDED','TOOL_ARGUMENTS_INVALID','V4_SEGMENT_NOT_SUPPORTED',
  'FINALIZE_REPORT_NOT_READY','FINALIZE_SEGMENT_DIAGNOSTIC','CANDIDATE_NOT_IN_REPORT','ROUND_EVIDENCE_NOT_DELIVERED']);
class BusinessError extends Error{}
const failure=(error:unknown,fallback:string)=>({available:false,error_code:error instanceof BusinessError?error.message:fallback});

export function computeTools(scope:Scope,config:{baseUrl:string;token:string},references:Set<string>){
  const call=async(name:string,args:Record<string,unknown>,options:{toolCallId:string;abortSignal?:AbortSignal})=>{
    if(!config.token)throw new Error('unconfigured');
    const signal=options.abortSignal?AbortSignal.any([options.abortSignal,AbortSignal.timeout(10000)]):AbortSignal.timeout(10000);
    const response=await fetch(new URL(`/internal/tools/${name}`,config.baseUrl),{method:'POST',
      headers:{'Content-Type':'application/json',Authorization:`Bearer ${config.token}`},
      body:JSON.stringify({...scope,tool_call_id:options.toolCallId,arguments:args}),signal});
    const reader=response.body?.getReader();if(!reader)throw new Error('empty');
    let size=0;const chunks:Uint8Array[]=[];
    try{for(;;){const part=await reader.read();if(part.done)break;size+=part.value.length;
      if(size>128*1024)throw new Error('limit');chunks.push(part.value);}}
    catch(error){await reader.cancel();throw error;}finally{reader.releaseLock();}
    const data=JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if(!response.ok){if(businessErrors.has(data.error_code))throw new BusinessError(data.error_code);throw new Error('rejected');}
    if(data.tool!==name||data.parent_run_id!==scope.parent_run_id||!Array.isArray(data.references))throw new Error('scope');
    if(name==='get_exploration_budget'){
      const b=data.budget;
      if(!b||b.turn_id!==scope.turn_id||!Array.isArray(data.rounds)||data.rounds.length>20||data.references.length||
        !['max_rounds','max_candidates','rounds_used','candidates_used'].every(k=>Number.isInteger(b[k])&&b[k]>=0)||
        typeof b.finalized!=='boolean'||typeof b.expired!=='boolean')throw new Error('budget');
      return data;
    }
    if(name==='finalize_candidates'?data.status!=='finalized':!statuses.has(data.status))throw new Error('status');
    if(name==='rerun_analysis'||name==='analyze_segment'){
      if(!z.uuid().safeParse(data.child_run_id).success||!z.uuid().safeParse(data.job_id).success||data.references.length)throw new Error('branch');
    }else{
      if(data.run_id!==args.child_run_id)throw new Error('child');
      const complete=data.status==='succeeded'||data.status==='finalized';
      if(!complete&&data.references.length)throw new Error('premature');
      if(complete&&(!Number.isInteger(data.report_version)||data.report_version<1||!data.references.length))throw new Error('report');
      if(name==='finalize_candidates'&&(data.evidence_status!=='exploratory'||!Array.isArray(data.candidate_ids)||
        JSON.stringify([...data.candidate_ids].sort())!==JSON.stringify([...(args.candidate_ids as string[])].sort())))throw new Error('finalization');
      for(const ref of data.references){
        if(ref.run_id!==data.run_id||!z.uuid().safeParse(ref.artifact_id).success||
          ref.evidence_id!==`report:${ref.artifact_id}#${ref.json_pointer}`||
          !/^\/summary$|^\/candidates\/\d+$/.test(ref.json_pointer)||!/^[a-f0-9]{64}$/.test(ref.sha256))throw new Error('reference');
      }
      for(const ref of data.references)references.add(ref.evidence_id);
    }
    return data;
  };
  return {
    get_exploration_budget:tool({description:'Read durable round/candidate budgets, deadline, finalized state and prior child runs. These are execution limits, not evidence of analytical results.',
      inputSchema:z.object({}).strict(),execute:async(args,options)=>{try{return await call('get_exploration_budget',args,options);}
        catch(error){return failure(error,'TOOL_BUDGET_FAILED');}}}),
    finalize_candidates:tool({description:'Freeze a selection from an already completed owned child report and close this turn to new compute branches. IDs must exist in that report; empty selection is allowed. Remains exploratory, never grants fresh validation.',
      inputSchema:z.object({child_run_id:z.uuid(),candidate_ids:z.array(z.string().min(1).max(256)).max(10).refine(v=>new Set(v).size===v.length)}).strict(),
      execute:async(args,options)=>{try{return await call('finalize_candidates',args,options);}
        catch(error){return failure(error,'TOOL_FINALIZE_FAILED');}}}),
    analyze_segment:tool({description:'Create an exploratory country/platform/acquisition-source diagnostic child using the parent fixed candidates and original mature-user split. Missing fields or small groups return explicit limitations, not invented revenue. Use evaluate_analysis for its result.',
      inputSchema:z.object({field:z.enum(['country','platform','acquisition_source']),value:z.string().min(1).max(200).refine(v=>v.trim().length>0)}).strict(),
      execute:async(args,options)=>{try{return await call('analyze_segment',args,options);}
        catch(error){return failure(error,'TOOL_SEGMENT_FAILED');}}}),
    rerun_analysis:tool({description:'Create a durable exploratory child analysis with changed windows or threshold grids. Preserves parent data, split and report. Budget may only be reduced. Returns child_run_id, not completed results; then use evaluate_analysis.',
      inputSchema:rerunSchema,execute:async(args,options)=>{
        try{return await call('rerun_analysis',args,options);}
        catch(error){return failure(error,'TOOL_RERUN_FAILED');}
      }}),
    evaluate_analysis:tool({description:'Wait up to 30 seconds for an owned child analysis, returning progress or actual aggregate report evidence. If queued/running, it is not complete: call again or report that it is still processing. No fabricated metrics.',
      inputSchema:z.object({child_run_id:z.uuid()}).strict(),execute:async(args,options)=>{
        const deadline=Date.now()+30000;
        try{for(;;){
          options.abortSignal?.throwIfAborted();
          const result=await call('evaluate_analysis',args,options);
          if(!['queued','running'].includes(result.status)||Date.now()>=deadline)return result;
          await delay(1000,undefined,{signal:options.abortSignal});
        }}catch(error){return failure(error,'TOOL_EVALUATE_FAILED');}
      }}),
  };
}
