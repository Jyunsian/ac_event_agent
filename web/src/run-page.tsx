import { useEffect, useRef, useState } from 'react';
import { api, APIError } from './upload-client';
import { Workspace } from './workspace';
import {runStatus as statuses,stageLabel as stageNames,errorText,dateText} from './language';

export type RunView = {run_id:string;root_run_id:string;parent_run_id:string|null;dataset_id:string;project_id:string;app_id:string;name:string;created_at:string;
  status:string;kind:string;ready:boolean;report_version:number|null;synthetic:boolean;can_retry:boolean;
  error:{code:string}|null;attempt_number:number|null;max_attempts:number|null;
  progress:{stage?:string;completed_stages?:string[];analysis_status?:string;retry_requested?:boolean;previous_error?:string}};
type HistoryItem = Pick<RunView,'run_id'|'dataset_id'|'status'|'kind'|'created_at'|'name'|'app_id'>;

function useRun(id:string) {
  const [run,setRun]=useState<RunView|null>(null),[error,setError]=useState('');
  const [refresh,setRefresh]=useState(0);
  useEffect(()=>{
    let current=true;let timer:ReturnType<typeof setTimeout>;const controller=new AbortController();
    const read=async()=>{
      let again=true;
      const selection=new URLSearchParams();const url=new URL(location.href);
      for(const key of ['version','artifact']){const value=url.searchParams.get(key);if(value!==null)selection.set(key,value);}
      try {const value=await api<RunView>(`/api/runs/${encodeURIComponent(id)}/view?${selection}`,'GET',undefined,controller.signal);
        if(!current)return;setRun(value);setError('');again=['queued','running'].includes(value.status);
      } catch(e) {if(current)setError(errorText(e));if(e instanceof APIError && [404,422].includes(e.status))again=false;}
      if(current && again)timer=setTimeout(read,2000);
    };
    void read();return ()=>{current=false;controller.abort();clearTimeout(timer);};
  },[id,refresh]);
  return {run,error,reload:()=>setRefresh(n=>n+1)};
}

export function RunPage({id,workspace=false}:{id:string;workspace?:boolean}) {
  const {run,error,reload}=useRun(id);const [retrying,setRetrying]=useState(false),[retryError,setRetryError]=useState('');
  if(workspace && run?.ready && !error)return <Workspace run={run}/>;
  return <div className="run-page"><header className="toolbar"><a className="wordmark" href="/">AC Event Agent</a><span>分析進度</span><a className="new-dataset" href="/history">分析歷史</a></header>
    <main className="upload-content"><h1>{run?.name || '正在讀取分析進度'}</h1><details><summary>分析識別資料</summary><p className="dataset-identity">{id}</p></details>
      {error && <div role="alert" className="error-message">{error} 分析是否完成，需連線後才能確認。<button onClick={reload}>重新讀取</button></div>}
      {run && <><p className="run-status" role="status">{run.ready?'基礎報告已發布':statuses[run.status] || '未知狀態'}</p>
        {run.synthetic && <p className="fixture-notice">合成資料分析，非客戶投放成效。</p>}
        {run.ready && !error && <a className="button-link" href={`/workspace?run=${id}`}>開啟分析工作區</a>}
        <dl className="facts"><div><dt>App</dt><dd>{run.app_id}</dd></div><div><dt>開始時間</dt><dd>{dateText(run.created_at)}</dd></div></dl>
        <details><summary>處理詳細資料</summary><p>資料版本：{run.dataset_id}</p><p>嘗試次數：{run.attempt_number ?? '未知'} / {run.max_attempts ?? '未知'}</p>{run.error&&<p>錯誤代碼：{run.error.code}</p>}</details>
        {!run.ready && ['queued','running'].includes(run.status) && <p>背景任務會持續執行，關閉頁面不會取消。以下只列出已完成階段，不推算剩餘時間或百分比。</p>}
        <section><h2>已完成階段</h2>{run.progress.completed_stages?.length ? <ol className="stage-list">{run.progress.completed_stages.map(stage=><li key={stage}>{stageNames[stage] || stage}<span>已保存</span></li>)}</ol> : <p className="muted">尚無本次已完成階段的紀錄。</p>}</section>
        {run.progress.retry_requested && <p>已安排重新嘗試，先前已完成的處理紀錄仍會保留。</p>}
        {run.error && <div className="error-message" role="alert">{errorText(run.error.code)}{run.status==='queued' ? ' 系統已安排再次嘗試，請稍候。' : !run.can_retry ? ' 若需修正來源資料，請上傳為一份新資料，不會取代原本的資料。' : ''}</div>}
        {retryError && <p role="alert">重試未提交：{retryError}</p>}
        {run.can_retry && <button disabled={retrying||Boolean(error)} onClick={async()=>{setRetrying(true);setRetryError('');try{await api(`/api/runs/${id}/retry`,'POST',{});reload();}catch(e){setRetryError(errorText(e));}finally{setRetrying(false);}}}>重新嘗試分析</button>}
        {run.status==='succeeded' && !run.ready && <p role="alert">資料已算完，但報告尚未準備好。請重新讀取狀態；若持續無法開啟，請聯絡維護人員。</p>}
        <section className="run-actions">{run.ready && !error ? <><p>報告已發布，可開啟工作區深入分析；Agent 是否可用會在工作區顯示，不影響閱讀與下載報告。</p><div>{['html','json','csv'].map(format=><a key={format} className="button-link" href={`/api/runs/${id}/reports/${run.report_version}/${format}`}>下載 {format.toUpperCase()}</a>)}</div></> : <button disabled>報告發布後開啟工作區</button>}
          <p><a href={`/upload?dataset=${run.dataset_id}`}>查看來源資料集</a> · <a href="/upload">建立新資料集</a></p></section>
      </>}
    </main></div>;
}

export function HistoryPage() {
  const [items,setItems]=useState<HistoryItem[]>([]),[cursor,setCursor]=useState<string|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const serial=useRef(0);
  const read=async(next?:string)=>{const request=++serial.current;setBusy(true);setError('');try{const result=await api<{items:HistoryItem[];next_cursor:string|null}>('/api/runs?limit=25'+(next?'&cursor='+encodeURIComponent(next):''));if(request!==serial.current)return;setItems(old=>next?[...old,...result.items]:result.items);setCursor(result.next_cursor);}catch(e){if(request===serial.current)setError(errorText(e));}finally{if(request===serial.current)setBusy(false);}};
  useEffect(()=>{void read();return ()=>{serial.current++;};},[]);
  return <div><header className="toolbar"><a className="wordmark" href="/">AC Event Agent</a><span>分析歷史</span><a className="new-dataset" href="/upload">上傳新資料</a></header><main className="upload-content"><h1>之前的分析</h1><p className="muted">重新開啟報告，或查看尚未完成的分析進度。</p><button onClick={()=>void read()} disabled={busy}>重新整理列表</button>
    {error && <p role="alert" className="error-message">無法讀取歷史：{error}</p>}
    {!items.length && !busy && !error && <p>尚無分析紀錄。<a href="/upload">上傳第一份資料</a></p>}
    <ul className="history-list">{items.map(item=><li key={item.run_id}><a href={`/runs/${item.run_id}`}><strong>{item.name}</strong><span>{item.app_id} · {statuses[item.status] || '狀態待確認'}</span><small>{dateText(item.created_at)}</small></a></li>)}</ul>
    {busy && <p role="status">正在讀取…</p>}{cursor && <button disabled={busy} onClick={()=>void read(cursor)}>載入較早分析</button>}
  </main></div>;
}
