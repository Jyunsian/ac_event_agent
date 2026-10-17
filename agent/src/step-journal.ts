import {randomUUID} from 'node:crypto';
import type {ModelMessage} from 'ai';
import {z} from 'zod';
import {AgentRuntimeError,PROMPT_VERSION,type StepLifecycle} from './runtime.js';

export type StepRequest=(operation:'init'|'start'|'complete',body:object)=>Promise<unknown>;
const object=z.record(z.string(),z.json());
const usage=z.record(z.string(),z.number().int().nonnegative().nullable());
const stateSchema=z.object({config:object,deadline:z.string().datetime({offset:true}),
  steps:z.array(z.object({ordinal:z.number().int().positive(),request_id:z.uuid(),fence:z.number().int().positive(),usage:usage.nullable(),finish_reason:z.string().nullable()}).strict()).max(20),
  checkpoint:z.object({ordinal:z.number().int().positive(),messages:z.array(z.unknown()),usage,finish_reason:z.string()}).strict().nullable()}).strict();

/** Keep only public conversational material; never persist reasoning or provider payloads. */
export function publicMessages(value:unknown):ModelMessage[]{
  const messages=z.array(z.object({role:z.enum(['assistant','tool']),content:z.union([z.string(),z.array(z.unknown())])})).parse(value);
  return messages.map(message=>{
    const content=typeof message.content==='string'?[{type:'text',text:message.content}]:message.content;
    const parts=[];
    for(const input of content){
      const part=z.object({type:z.string()}).passthrough().parse(input);
      if(part.type==='reasoning')continue;
      if(part.type==='text'&&message.role==='assistant')parts.push({type:'text' as const,text:z.string().parse(part.text)});
      else if(part.type==='tool-call'&&message.role==='assistant')parts.push({type:'tool-call' as const,
        toolCallId:z.string().parse(part.toolCallId),toolName:z.string().parse(part.toolName),input:object.parse(part.input)});
      else if(part.type==='tool-result'&&message.role==='tool')parts.push({type:'tool-result' as const,
        toolCallId:z.string().parse(part.toolCallId),toolName:z.string().parse(part.toolName),
        output:z.object({type:z.literal('json'),value:object}).parse(part.output)});
      else throw new AgentRuntimeError('AGENT_CONTEXT_LIMIT');
    }
    // Roles and allowed content are checked above; SDK's union cannot retain that correlation through map.
    return {role:message.role,content:parts} as ModelMessage;
  });
}

export class StepJournal implements StepLifecycle{
  error:AgentRuntimeError|undefined;
  prefix:ModelMessage[]=[];
  remainingSteps=0;checkpointOrdinal=0;consumed=0;finishReason:string|null=null;
  private deadlineMs=0;private timeoutMs=0;
  get remainingMs(){return Math.min(this.timeoutMs,Math.floor(this.deadlineMs-Date.now()));}
  private ordinal=0;
  constructor(private readonly request:StepRequest){}
  private fail(error:unknown):never{
    const code=error&&typeof error==='object'&&'code' in error?String(error.code):'';
    this.error=new AgentRuntimeError(['AGENT_STEP_LIMIT','AGENT_TIMEOUT','AGENT_CONTEXT_LIMIT','AGENT_RUNTIME_CONFIG_CHANGED'].includes(code)?code:'AGENT_RECOVERY_REQUIRED');
    throw this.error;
  }
  async init(modelId:string,limits?:{maxSteps?:number;timeoutMs?:number}){
    try{
      const config={model_id:modelId,sdk_version:'7.0.94',prompt_version:PROMPT_VERSION,max_steps:limits?.maxSteps??8,timeout_ms:limits?.timeoutMs??120000};
      const state=stateSchema.parse(await this.request('init',{config}));
      if(Object.keys(config).some(key=>state.config[key]!==config[key as keyof typeof config]))throw new Error('config');
      if(state.steps.some((step,i)=>step.ordinal!==i+1))throw new Error('ordinals');
      this.consumed=state.steps.length;this.remainingSteps=config.max_steps-this.consumed;
      this.deadlineMs=Date.parse(state.deadline);this.timeoutMs=config.timeout_ms;
      if(state.checkpoint){
        const step=state.steps[state.checkpoint.ordinal-1];if(!step||step.finish_reason!==state.checkpoint.finish_reason)throw new Error('checkpoint');
        this.prefix=publicMessages(state.checkpoint.messages);this.checkpointOrdinal=state.checkpoint.ordinal;this.finishReason=state.checkpoint.finish_reason;
      }
    }catch(error){this.fail(error);}
  }
  finalText(){
    if(this.finishReason!=='stop'||this.checkpointOrdinal!==this.consumed)return null;
    const last=this.prefix.at(-1);
    if(last?.role!=='assistant')return null;
    return typeof last.content==='string'?last.content:last.content.filter(part=>part.type==='text').map(part=>part.text).join('');
  }
  async start(){
    try{
      const result=z.object({ordinal:z.number().int().positive()}).strict().parse(await this.request('start',{request_id:randomUUID()}));
      if(result.ordinal!==this.consumed+1)throw new Error('ordinal');
      this.ordinal=result.ordinal;this.consumed=result.ordinal;
    }catch(error){this.fail(error);}
  }
  async end(messages:unknown,counts:{inputTokens?:number;outputTokens?:number;totalTokens?:number},reason:string){
    try{
      const saved=[...this.prefix,...publicMessages(messages)];
      const result=z.object({ordinal:z.number().int().positive(),saved:z.literal(true)}).strict().parse(await this.request('complete',{
        ordinal:this.ordinal,messages:saved,usage:{input_tokens:counts.inputTokens??null,output_tokens:counts.outputTokens??null,total_tokens:counts.totalTokens??null},finish_reason:reason}));
      if(result.ordinal!==this.ordinal)throw new Error('ordinal');
      this.prefix=saved;
    }catch(error){this.fail(error);}
  }
}
