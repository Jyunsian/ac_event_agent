import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {api,requestIdentity} from './upload-client';
import type {RunView} from './run-page';
import './chat-panel.css';
import {errorText} from './language';
import {AssistantMessage} from './assistant-message';
import {referenceBinding} from './message-references';

type Context={selected_run_id:string;selected_candidate_id:string|null;report_version:number};
type Event={seq:number;turn_id:string;kind:string;payload:{role?:string;content?:string;context?:Context;code?:string;tool?:string;tool_call_id?:string;fence?:number;run_id?:string;report_version?:number;references?:{evidence_id:string;run_id:string;report_version?:number}[]}};
type Turn={id:string;status:string;error:{code:string}|null};
const labels:Record<string,string>={queued:'排隊中',running:'分析助理處理中',succeeded:'已完成',failed:'回覆失敗',cancelled:'已取消'};
const availability:Record<string,string>={OPENROUTER_NOT_CONFIGURED:'分析助理目前尚未啟用，暫時無法回覆問題。',AGENT_WORKER_DISCONNECTED:'分析助理暫時未連線，請稍後再試。',AGENT_WORKER_UNAVAILABLE:'分析助理暫時無法使用，請稍後再試。'};
const toolLabels:Record<string,string>={profile_dataset:'檢查資料品質',get_baseline_report:'讀取候選報告',compare_candidates:'比較現有候選',search_candidates:'搜尋全部候選',rerun_analysis:'建立新的分析',analyze_segment:'分析指定玩家群',evaluate_analysis:'讀取分析結果',get_exploration_budget:'檢查分析額度',finalize_candidates:'保存候選結果',load_app_findings:'讀取過往發現',save_findings:'保存本次發現'};

export function ChatPanel({run,candidate,onReference,reportView}:{reportView?:{hours:number;cohort:string};run:RunView;candidate:string|null;onReference:(context:Context,reference:string)=>void}){
  const [cid,setCid]=useState<string|null>(null),[initialized,setInitialized]=useState(false);
  const [events,setEvents]=useState<Event[]>([]),[turns,setTurns]=useState<Turn[]>([]);
  const [draft,setDraft]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [provider,setProvider]=useState({available:false,code:'CHECKING'});
  const [newMessages,setNewMessages]=useState(false);
  const scroll=useRef<HTMLDivElement>(null),atBottom=useRef(true),composing=useRef(false);
  const input=useRef<HTMLTextAreaElement>(null);
  const pending=useRef<{serialized:string;key:string}|null>(null),locked=useRef(false);
  const active=useRef(true);
  useEffect(()=>{active.current=true;return()=>{active.current=false;};},[]);
  function bind(id:string){const url=new URL(location.href);url.searchParams.set('conversation',id);history.replaceState(null,'',url);setCid(id);}
  useEffect(()=>{
    let current=true;const controller=new AbortController();
    void (async()=>{try{
      const chosen=new URLSearchParams(location.search).get('conversation');
      if(chosen){
        const state=await api<{baseline_run_id:string}>(`/api/conversations/${encodeURIComponent(chosen)}`,'GET',undefined,controller.signal);
        if(state.baseline_run_id!==run.root_run_id)throw new Error('CONVERSATION_RUN_MISMATCH');
        if(current)bind(chosen);
      }else{
        const result=await api<{conversations:{id:string}[]}>(`/api/runs/${run.root_run_id}/conversations`,'GET',undefined,controller.signal);
        if(current&&result.conversations[0])bind(result.conversations[0].id);
      }
      if(current)setInitialized(true);
    }catch(e){if(current)setError(e instanceof Error?e.message:'對話讀取失敗');}})();
    return()=>{current=false;controller.abort();};
  },[run.run_id]);
  useEffect(()=>{
    let current=true;const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      try{const status=await api<typeof provider>('/api/agent/status','GET',undefined,controller.signal);if(current)setProvider(status);}
      catch{if(current)setProvider({available:false,code:'AGENT_WORKER_UNAVAILABLE'});}
      if(current)timer=setTimeout(poll,3000);
    };void poll();return()=>{current=false;controller.abort();clearTimeout(timer);};
  },[]);
  useEffect(()=>{
    if(!cid)return;
    let current=true,cursor=0;let timer:ReturnType<typeof setTimeout>;const controller=new AbortController();
    setEvents([]);setTurns([]);
    const poll=async()=>{
      try{
        const page=await api<{events:Event[];next_after:number;has_more:boolean}>(`/api/conversations/${cid}/events?after=${cursor}`,'GET',undefined,controller.signal);
        if(!current)return;
        if(page.events.length){setEvents(previous=>[...previous,...page.events]);cursor=page.next_after;}
        const state=await api<{turns:Turn[]}>(`/api/conversations/${cid}`,'GET',undefined,controller.signal);
        if(!current)return;setTurns(state.turns);
        timer=setTimeout(poll,page.has_more?0:1000);
      }catch(e){if(current){setError(e instanceof Error?e.message:'對話同步失敗');timer=setTimeout(poll,2000);}}
    };void poll();return()=>{current=false;controller.abort();clearTimeout(timer);};
  },[cid]);
  useLayoutEffect(()=>{
    if(!events.length)return;
    if(atBottom.current&&scroll.current)scroll.current.scrollTop=scroll.current.scrollHeight;
    else setNewMessages(true);
  },[events]);
  useLayoutEffect(()=>{const el=input.current;if(!el)return;el.style.height='0px';el.style.height=`${Math.min(160,Math.max(44,el.scrollHeight))}px`;},[draft]);
  async function send(){
    if(locked.current||!provider.available||!initialized||!draft.trim()||composing.current)return;
    locked.current=true;setBusy(true);setError('');
    const content=draft;const body={content,selected_run_id:run.run_id,selected_candidate_id:candidate,report_version:run.report_version,report_view:reportView};
    const serialized=JSON.stringify(body);
    if(pending.current?.serialized!==serialized)pending.current={serialized,key:crypto.randomUUID()};
    try{
      let id=cid;
      if(!id){id=(await api<{id:string}>(`/api/runs/${run.root_run_id}/conversations`,'POST',{},undefined,requestIdentity(`workspace:${run.root_run_id}`))).id;if(active.current)bind(id);}
      await api(`/api/conversations/${id}/messages`,'POST',body,undefined,pending.current.key);
      if(active.current){setDraft(previous=>previous===content?'':previous);pending.current=null;}
    }catch(e){if(active.current)setError(e instanceof Error?e.message:'送出失敗；原問題已保留，可重試送出。');}
    finally{locked.current=false;if(active.current)setBusy(false);}
  }
  async function action(turn:Turn,operation:'cancel'|'retry'){
    if(locked.current)return;locked.current=true;setBusy(true);setError('');
    try{await api(`/api/turns/${turn.id}/${operation}`,'POST',{},undefined,requestIdentity(`${operation}:${turn.id}`));}
    catch(e){if(active.current)setError(e instanceof Error?e.message:'操作失敗');}
    finally{locked.current=false;if(active.current)setBusy(false);}
  }
  const messages=events.filter(event=>event.kind==='message_created');
  const tools=new Map<string,Event>();
  events.filter(event=>event.kind.startsWith('tool_')).forEach(event=>tools.set(`${event.turn_id}:${event.payload.fence}:${event.payload.tool_call_id}`,event));
  function referenceContext(event:Event,reference:string){
    return referenceBinding(events,event.turn_id,reference,event.seq);
  }
  return <>
    <div className="panel-heading"><h1>分析助理</h1><span className={`status assistant-status ${provider.available?'online':'offline'}`}>{provider.available?'可提問':'暫時無法提問'}</span></div>
    <div ref={scroll} className="chat-scroll" tabIndex={0} aria-label="對話內容" onScroll={()=>{const el=scroll.current!;atBottom.current=el.scrollHeight-el.scrollTop-el.clientHeight<48;if(atBottom.current)setNewMessages(false);}}>
      {!provider.available&&<div className="assistant-unavailable" role="status"><h2>助理尚未啟用</h2><p>{availability[provider.code]||'正在確認助理狀態。'} 報告仍可正常查看。</p></div>}
      {provider.available&&messages.length===0&&<div className="chat-empty"><h2>這份報告想先看什麼？</h2><p>我會先讀取報告證據，再用白話回答。</p><div className="prompt-list">{[
        '這份報告最值得注意的三個行為是什麼？','哪些事件的收益差異最大？','哪些結果目前還不能下結論？'
      ].map(prompt=><button key={prompt} onClick={()=>setDraft(prompt)}>{prompt}</button>)}</div></div>}
      {messages.map(event=>{const payload=event.payload;const turn=turns.find(t=>t.id===event.turn_id);
        const turnTools=[...tools.entries()].filter(([,entry])=>entry.turn_id===event.turn_id);
        const activityState=turn?.status==='succeeded'?'已完成':turn?.status==='failed'?'未完成':turn?.status==='cancelled'?'已取消':'處理中';
        return <article className={`chat-message chat-message-${payload.role||'assistant'}`} key={event.seq} data-turn-id={event.turn_id}>
          <div className="message-shell"><h3 className="message-author">{payload.role==='user'?'你':'分析助理'}</h3>{payload.role==='assistant'?<AssistantMessage content={payload.content||''} canReference={ref=>referenceContext(event,ref)!==null} onReference={ref=>{const context=referenceContext(event,ref);if(context)onReference(context,ref);}}/>:<p className="message-content">{payload.content}</p>}</div>
          {payload.context&&<span className="message-context">第 {payload.context.report_version} 版 · {payload.context.selected_candidate_id?'已選事件':'完整報告'}</span>}
          {payload.role==='user'&&turnTools.length>0&&<details className="tool-activity" open={turn?['queued','running'].includes(turn.status):false}><summary><span>分析過程</span><span>{turnTools.length} 個步驟 · {activityState}</span></summary><div className="tool-steps">{turnTools.map(([key,entry])=><div className="tool-step" key={key}>
            <span className={`tool-step-dot ${entry.kind==='tool_completed'?'complete':entry.kind==='tool_failed'?'failed':'running'}`} aria-hidden="true"/><span>{toolLabels[entry.payload.tool||'']||'讀取分析證據'}</span><span className="tool-step-state">{entry.kind==='tool_completed'?'完成':entry.kind==='tool_failed'?'失敗':turn&&['failed','cancelled'].includes(turn.status)?'中斷':'處理中'}</span>
            {entry.kind==='tool_completed'&&entry.payload.run_id&&entry.payload.report_version&&entry.payload.references?.filter(ref=>ref.run_id===entry.payload.run_id&&/^report:[0-9a-f-]{36}#\/summary$/.test(ref.evidence_id)).slice(0,1).map(ref=><button key={ref.evidence_id} className="tool-result-button" onClick={()=>onReference({selected_run_id:entry.payload.run_id!,selected_candidate_id:null,report_version:entry.payload.report_version!},ref.evidence_id)}>查看結果</button>)}
          </div>)}</div></details>}
          {payload.role==='user'&&turn&&turn.status!=='succeeded'&&<div className={`turn-status turn-${turn.status}`}><span>{labels[turn.status]||'狀態待確認'}{turn.error?` · ${errorText(turn.error.code)}`:''}</span>
            {turn.error&&<details><summary>錯誤詳細資料</summary>{turn.error.code}</details>}
            {['queued','running'].includes(turn.status)&&<button disabled={busy} onClick={()=>void action(turn,'cancel')}>取消</button>}
            {['failed','cancelled'].includes(turn.status)&&<button disabled={busy||!provider.available} onClick={()=>void action(turn,'retry')}>重試原問題</button>}
          </div>}
        </article>;
      })}
    </div>
    {newMessages&&<button className="new-messages" onClick={()=>{atBottom.current=true;setNewMessages(false);if(scroll.current)scroll.current.scrollTop=scroll.current.scrollHeight;}}>有新訊息，移至底部</button>}
    <p className="context-line" style={{padding:'0 16px',fontSize:12}}>目前查看：第 {run.report_version} 版{reportView?` · ${reportView.hours} 小時 · ${{observation:'全量玩家',exploration:'找規律',holdout:'Holdout'}[reportView.cohort]??reportView.cohort}`:''}</p>
    {provider.available?<div className="composer">
      {error&&<div role="alert"><p>{errorText(error)}。未清除草稿或既有報告。</p><details><summary>錯誤詳細資料</summary>{error}</details></div>}
      <div className="composer-box"><label className="composer-label" htmlFor="question">詢問分析助理</label><textarea ref={input} id="question" rows={1} maxLength={20000} value={draft} placeholder="問這份報告…" onChange={event=>setDraft(event.target.value)}
        onCompositionStart={()=>{composing.current=true;}} onCompositionEnd={()=>{composing.current=false;}}
        onKeyDown={event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.nativeEvent.isComposing&&!composing.current&&event.keyCode!==229){event.preventDefault();void send();}}}/>
      <div className="composer-footer"><span className="context-chip">第 {run.report_version} 版 · {candidate?'已選事件':'完整報告'}</span><span className="composer-shortcut">Enter 送出</span><button disabled={busy||!initialized||!provider.available||!draft.trim()} onClick={()=>void send()}>{busy?'處理中…':'送出'}</button></div></div>
    </div>:<div className="composer unavailable-composer"><div className="composer-box"><p>助理啟用後，可在這裡詢問報告。</p></div></div>}
  </>;
}
