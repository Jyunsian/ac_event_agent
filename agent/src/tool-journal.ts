import {asSchema,type ModelMessage,type ToolSet,type ToolExecutionOptions,type JSONValue} from 'ai';
import {z} from 'zod';
import {AgentRuntimeError} from './runtime.js';

const object=z.record(z.string(),z.json());
const savedCall=z.object({tool_call_id:z.string().min(1).max(200),ordinal:z.number().int().positive().max(100),
  tool_name:z.string().min(1).max(100),arguments:object,input_sha256:z.string().regex(/^[a-f0-9]{64}$/),
  output:object.nullable(),output_sha256:z.string().regex(/^[a-f0-9]{64}$/).nullable()}).strict();
const reply=z.object({tool_call_id:z.string(),state:z.enum(['pending','completed']),output:object.nullable()}).strict();
export type JournalRequest=(operation:'load'|'begin'|'complete',body:object)=>Promise<unknown>;

/** The SDK still owns model decisions; this layer commits side effects before returning them. */
export class ToolJournal{
  readonly controller=new AbortController();
  failed=false;
  constructor(private readonly request:JournalRequest,private readonly allowed:Set<string>){}
  private fail():never{
    this.failed=true;this.controller.abort();throw new AgentRuntimeError('AGENT_RECOVERY_REQUIRED');
  }
  private references(output:Record<string,JSONValue>){
    const refs=output.references;
    if(refs===undefined)return;
    if(!Array.isArray(refs))this.fail();
    for(const ref of refs){
      if(!ref||typeof ref!=='object'||Array.isArray(ref)||typeof ref.evidence_id!=='string'||
        ref.evidence_id!==`report:${ref.artifact_id}#${ref.json_pointer}`)this.fail();
    }
    for(const ref of refs)this.allowed.add((ref as Record<string,JSONValue>).evidence_id as string);
  }
  wrap(tools:ToolSet):ToolSet{
    return Object.fromEntries(Object.entries(tools).map(([name,definition])=>{
      const execute=definition.execute;
      if(!execute)throw new AgentRuntimeError('AGENT_RECOVERY_REQUIRED');
      return [name,{...definition,execute:async(input:unknown,options:ToolExecutionOptions<unknown>)=>{
        try{
          options.abortSignal?.throwIfAborted();
          const begin=reply.parse(await this.request('begin',{tool_call_id:options.toolCallId,tool_name:name,arguments:input}));
          if(begin.tool_call_id!==options.toolCallId||(begin.state==='completed')!==(begin.output!==null))this.fail();
          if(begin.output!==null){this.references(begin.output);return begin.output;}
          const output=object.parse(await execute(input,options));
          options.abortSignal?.throwIfAborted();
          // An ambiguous transport failure can hide a committed child run. Keep its original intent pending.
          if(typeof output.error_code==='string'&&/^TOOL_.*(?:FAILED|HTTP_\d+)$/.test(output.error_code))this.fail();
          const completed=reply.parse(await this.request('complete',{tool_call_id:options.toolCallId,output}));
          if(completed.tool_call_id!==options.toolCallId||completed.state!=='completed'||completed.output===null)this.fail();
          this.references(completed.output);return completed.output;
        }catch{return this.fail();}
      }}];
    }));
  }
  async recover(tools:ToolSet,messages:ModelMessage[],signal?:AbortSignal,checkpoint:ModelMessage[]=[]):Promise<ModelMessage[]>{
    try{
      const {calls}=z.object({calls:z.array(savedCall).max(100)}).strict().parse(await this.request('load',{}));
      const restored:ModelMessage[]=[];const ids=new Set<string>();
      const included=new Set(checkpoint.flatMap(message=>message.role==='assistant'&&Array.isArray(message.content)?
        message.content.flatMap(part=>part.type==='tool-call'?[part.toolCallId]:[]):[]));
      for(const [index,call] of calls.entries()){
        if(call.ordinal!==index+1||ids.has(call.tool_call_id)||(call.output===null)!==(call.output_sha256===null))this.fail();
        ids.add(call.tool_call_id);
        const definition=tools[call.tool_name];if(!definition?.execute)this.fail();
        const schema=asSchema<unknown>(definition.inputSchema);
        const validation=await schema.validate?.(call.arguments);
        if(!validation?.success)this.fail();
        // The wrapper first checks completed output. Pending calls execute with the SAME identity;
        // the existing backend tool idempotency resolves an already committed branch/job.
        const execute=definition.execute as (input:unknown,options:ToolExecutionOptions<unknown>)=>unknown;
        const output=object.parse(await execute(call.arguments,
          {toolCallId:call.tool_call_id,messages:[...messages,...restored],abortSignal:signal,context:undefined}));
        if(!included.has(call.tool_call_id))restored.push({role:'assistant',content:[{type:'tool-call',toolCallId:call.tool_call_id,toolName:call.tool_name,input:call.arguments}]},
          {role:'tool',content:[{type:'tool-result',toolCallId:call.tool_call_id,toolName:call.tool_name,output:{type:'json',value:output}}]});
      }
      return restored;
    }catch{return this.fail();}
  }
}
