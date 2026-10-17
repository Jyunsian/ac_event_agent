import {randomUUID} from 'node:crypto';
import type {LanguageModel,ModelMessage} from 'ai';
import {AgentRuntimeError,providerStatus} from './runtime.js';
import {runReadonlyAgent} from './readonly-agent.js';

type Claim={id:string;selected_run_id:string;fence:number};
type Context={report_view?:{hours:number;cohort:string}|null;messages:ModelMessage[];selected_run_id:string;selected_candidate_id:string|null;report_version:number};
class BridgeError extends Error{
  constructor(readonly status:number,readonly code:string){super(code);}
}
export class AgentWorker{
  readonly workerId:string;
  connected=false;
  constructor(readonly config:{baseUrl:string;token:string;workerId?:string;heartbeatMs?:number;runtimeLimits?:{maxSteps?:number;timeoutMs?:number}},
    private readonly model?:LanguageModel){
    this.workerId=config.workerId??`agent-${randomUUID()}`;
    if(!config.token.trim())throw new Error('AGENT_INTERNAL_NOT_CONFIGURED');
    if(config.heartbeatMs!==undefined&&(!Number.isInteger(config.heartbeatMs)||config.heartbeatMs<10||config.heartbeatMs>30000))throw new Error('INVALID_HEARTBEAT');
  }
  private async request<T>(operation:string,body:object,signal?:AbortSignal):Promise<T>{
    const response=await fetch(new URL(`/internal/agent/${operation}`,this.config.baseUrl),{
      method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${this.config.token}`},
      body:JSON.stringify({worker_id:this.workerId,...body}),
      signal:signal?AbortSignal.any([signal,AbortSignal.timeout(10000)]):AbortSignal.timeout(10000)});
    // Internal responses are bounded too; never surface their raw text in errors.
    const reader=response.body?.getReader();if(!reader)throw new BridgeError(502,'AGENT_BRIDGE_EMPTY');
    const chunks:Uint8Array[]=[];let size=0;
    try{for(;;){const part=await reader.read();if(part.done)break;size+=part.value.length;
      if(size>300000)throw new BridgeError(502,'AGENT_BRIDGE_LIMIT');chunks.push(part.value);}}
    catch(error){await reader.cancel();throw error;}finally{reader.releaseLock();}
    let data;try{data=JSON.parse(Buffer.concat(chunks).toString('utf8'));}catch{throw new BridgeError(502,'AGENT_BRIDGE_INVALID');}
    if(!response.ok)throw new BridgeError(response.status,['AGENT_CONTEXT_LIMIT','AGENT_STEP_LIMIT','AGENT_TIMEOUT','AGENT_RUNTIME_CONFIG_CHANGED'].includes(data?.error_code)?data.error_code:'AGENT_BRIDGE_REJECTED');
    this.connected=true;return data as T;
  }
  async runOnce(signal?:AbortSignal):Promise<boolean>{
    // Missing credentials must not drain queued work or fabricate responses.
    if(!this.model&&!providerStatus().available)return false;
    const {claim}=await this.request<{claim:Claim|null}>('claim',{},signal);
    if(!claim)return false;
    const envelope={turn_id:claim.id,fence:claim.fence};
    const controller=new AbortController();
    const combined=signal?AbortSignal.any([signal,controller.signal]):controller.signal;
    let renewal:Promise<void>|undefined,lost=false;
    const timer=setInterval(()=>{
      if(renewal)return;
      renewal=(async()=>{
        try{await this.request('heartbeat',envelope,combined);}
        catch{lost=true;this.connected=false;controller.abort();}
        finally{renewal=undefined;}
      })();
    },this.config.heartbeatMs??20000);
    try{
      const context=await this.request<Context>('context',envelope,combined);
      if(context.selected_run_id!==claim.selected_run_id)throw new AgentRuntimeError('AGENT_CONTEXT_LIMIT');
      const selection=JSON.stringify({
        selected_run_id:context.selected_run_id,selected_candidate_id:context.selected_candidate_id,
        report_version:context.report_version,report_view:context.report_view});
      // SDK owns the system instructions. Selection is bounded user context,
      // not another system message or a replacement for the original question.
      const messages:ModelMessage[]=[...context.messages,{role:'user',content:`目前介面引用（非計算證據；請先讀取工具）：${selection}`}];
      const result=await runReadonlyAgent({scope:{...envelope,parent_run_id:context.selected_run_id,worker_id:this.workerId},
        config:this.config,messages,model:this.model,signal:combined,limits:this.config.runtimeLimits,
        journalRequest:(operation,body)=>this.request(`journal/${operation}`,{...envelope,...body},combined),
        stepRequest:(operation,body)=>this.request(`steps/${operation}`,{...envelope,...body},combined)});
      clearInterval(timer);await renewal;combined.throwIfAborted();
      await this.request('finish',{...envelope,content:result.text},combined);
    }catch(error){
      // A failed/ambiguous finish is never retried as another message. The lease
      // and fence are authoritative; if committed, fail is rejected as stale.
      if(!lost&&!signal?.aborted&&!(error instanceof AgentRuntimeError&&error.code==='AGENT_RECOVERY_REQUIRED')){
        const code=error instanceof AgentRuntimeError?error.code:
          error instanceof BridgeError&&error.code==='AGENT_CONTEXT_LIMIT'?error.code:'AGENT_WORKER_FAILED';
        try{await this.request('fail',{...envelope,error_code:code});}catch{this.connected=false;}
      }
    }finally{clearInterval(timer);controller.abort();}
    return true;
  }
  async run(signal:AbortSignal):Promise<void>{
    while(!signal.aborted){
      try{if(await this.runOnce(signal))continue;}catch{this.connected=false;}
      await new Promise<void>(resolve=>{
        if(signal.aborted){resolve();return;}
        const done=()=>{clearTimeout(timer);signal.removeEventListener('abort',done);resolve();};
        const timer=setTimeout(done,1000);signal.addEventListener('abort',done,{once:true});
      });
    }
  }
}
