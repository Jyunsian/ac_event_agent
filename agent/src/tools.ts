import {tool} from 'ai';
import {z} from 'zod';

type Scope={turn_id:string;parent_run_id:string;worker_id:string;fence:number};
export function readTools(scope:Scope,config:{baseUrl:string;token:string},references:Set<string>){
  const call=async(name:string,args:unknown,options:{toolCallId:string;abortSignal?:AbortSignal})=>{
    try{
      if(!config.token)throw new Error('unconfigured');
      const response=await fetch(new URL(`/internal/tools/${name}`,config.baseUrl),{method:'POST',
        headers:{'Content-Type':'application/json',Authorization:`Bearer ${config.token}`},
        body:JSON.stringify({...scope,tool_call_id:options.toolCallId,arguments:args}),signal:options.abortSignal});
      if(!response.ok)return {error_code:`TOOL_HTTP_${response.status}`,available:false};
      const reader=response.body?.getReader();if(!reader)throw new Error('empty');
      let size=0;const chunks:Uint8Array[]=[];
      try{for(;;){const part=await reader.read();if(part.done)break;size+=part.value.length;if(size>128*1024)throw new Error('limit');chunks.push(part.value);}}
      catch(error){await reader.cancel();throw error;}finally{reader.releaseLock();}
      const body=Buffer.concat(chunks).toString('utf8');const data=JSON.parse(body);
      if(data.run_id!==scope.parent_run_id||data.tool!==name||!Array.isArray(data.references))throw new Error('scope');
      for(const ref of data.references){
        if(ref.run_id!==scope.parent_run_id||typeof ref.evidence_id!=='string'||ref.evidence_id!==`report:${ref.artifact_id}#${ref.json_pointer}`||!/^\/summary$|^\/candidates\/\d+$|^\/entries\/\d+$|^\/diagnostics\/overlap$/.test(ref.json_pointer)||!/^[a-f0-9]{64}$/.test(ref.sha256))throw new Error('reference');
      }
      for(const ref of data.references)references.add(ref.evidence_id);
      return data;
    }catch{return {error_code:'TOOL_READ_FAILED',available:false};}
  };
  return {
    profile_dataset:tool({description:'Read current turn dataset aggregate quality and bounded distributions. Omitted cells are not zero.',inputSchema:z.object({}).strict(),execute:(args,options)=>call('profile_dataset',args,options)}),
    get_baseline_report:tool({description:'Read the published report bound to this turn, with exact evidence IDs. V4 returns all three cohorts at window_hours (default 24); read another clock explicitly. No calculation is started.',inputSchema:z.object({window_hours:z.union([z.literal(24),z.literal(48),z.literal(72),z.literal(96),z.literal(120),z.literal(144)]).optional()}).strict(),execute:(args,options)=>call('get_baseline_report',args,options)}),
    compare_candidates:tool({description:'Compare existing candidate IDs in this turn report; distinguish holdout metrics from exploratory overlap.',inputSchema:z.object({window_hours:z.union([z.literal(24),z.literal(48),z.literal(72),z.literal(96),z.literal(120),z.literal(144)]).optional(),candidate_ids:z.array(z.string().min(1).max(256)).min(1).max(10)}).strict(),execute:(args,options)=>call('compare_candidates',args,options)}),
    search_candidates:tool({description:'Search all evaluated candidates in the current report, including insufficient and unselected alternatives. Returns at most 50 per page; no new calculation. Baseline summary contains only priority candidates.',inputSchema:z.object({
      page:z.number().int().min(1).max(40).optional(),window_hours:z.number().int().optional(),
      family:z.enum(['atom','compound','sequence']).optional(),ad_format:z.string().max(100).optional(),
      evidence_status:z.enum(['historically_validated','historically_supported','not_supported','exploratory','insufficient_data']).optional(),
      role:z.enum(['價值差較大','覆蓋較廣','達標較快','unselected']).optional(),
      sort:z.enum(['candidate_id','difference_usd','coverage','p90_seconds']).optional(),descending:z.boolean().optional()
    }).strict(),execute:(args,options)=>call('search_candidates',args,options)}),
  };
}

export function validateReferences(text:string,allowed:Set<string>){
  const cited=(text.match(/report:[^\s<>"'`()[\]，。；（）、]+/g)||[]).map(id=>id.replace(/[.,;]+$/,''));
  return {valid:cited.length>0&&cited.every(id=>allowed.has(id)),cited};
}
