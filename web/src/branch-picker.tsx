import {useRef,useState} from 'react';
import {fetchReport} from './report-model';
import {api} from './upload-client';
import type {RunView} from './run-page';
import {dateText,errorText} from './language';

type Entry={run_id:string;parent_run_id:string|null;kind:string;created_at:string;report_version:number;artifact_id:string;windows_hours?:number[];segment?:{field:string;value:string};thresholds?:Record<string,number[]>};
type Page={root_run_id:string;items:Entry[];next_cursor:string|null};
export function ReportExports({run}:{run:RunView}){
  const path=`/api/runs/${run.run_id}/reports/${run.report_version}`;
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  async function download(){if(run.report_version===null)return;const version=run.report_version;setBusy(true);setError('');try{const {report,sha256}=await fetchReport(run.run_id,run.dataset_id,version,new AbortController().signal);if(report.schema_version==='4.0'&&report.catalog){const {downloadV4Html}=await import('./v4-export');await downloadV4Html(report,{runId:run.run_id,version,reportSha:sha256,catalogSha:report.catalog.sha256});}else location.assign(`${path}/html`);}catch(e){setError(errorText(e));}finally{setBusy(false);}}
  return <><button disabled={busy} onClick={()=>void download()}>{busy?'匯出中…':'匯出'}</button>{error&&<span role="alert">{error}</span>}<details className="report-version-control">
    <summary aria-label="更多匯出格式">格式</summary><div aria-label="報告匯出格式">
      <p>目前報告第 {run.report_version} 版</p><p>「匯出」下載分析閱讀版。以下保留原始報告與完整計算資料。</p><details><summary>報告識別資料</summary><p className="dataset-identity">{run.run_id}</p></details>
      <ul className="branch-list">{['html','csv','json'].map(format=><li key={format}><a href={`${path}/${format}`}>{format==='html'?'原始封存 HTML':`完整計算 ${format.toUpperCase()}`}</a></li>)}</ul>
    </div></details></>;
}
export function BranchPicker({run}:{run:RunView}){
  const [items,setItems]=useState<Entry[]>([]),[cursor,setCursor]=useState<string|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const serial=useRef(0);
  async function read(next?:string){
    const request=++serial.current;setBusy(true);setError('');
    try{
      const page=await api<Page>(`/api/runs/${run.run_id}/branch-reports?limit=25${next?'&cursor='+encodeURIComponent(next):''}`);
      if(request!==serial.current)return;
      if(page.root_run_id!==run.root_run_id)throw new Error('BRANCH_ROOT_MISMATCH');
      setItems(old=>next?[...old,...page.items]:page.items);setCursor(page.next_cursor);
    }catch(e){if(request===serial.current)setError(errorText(e));}
    finally{if(request===serial.current)setBusy(false);}
  }
  function target(item:Entry){
    const url=new URL(location.href);url.pathname='/workspace';
    url.searchParams.set('run',item.run_id);url.searchParams.set('version',String(item.report_version));
    url.searchParams.set('artifact',item.artifact_id);url.searchParams.delete('candidate');
    return url.pathname+url.search;
  }
  return <details className="report-version-control" onToggle={event=>{if(event.currentTarget.open)void read();}}>
    <summary aria-label={`檢視報告版本 v${run.report_version}`}>切換分析結果</summary>
    <div aria-label="已發布分析分支"><p>目前報告第 {run.report_version} 版</p>
      <p>選擇已發布結果，不會重算。新結果不會自動切換畫面。</p>
      {error&&<p role="alert">{error}</p>}
      <button disabled={busy} onClick={()=>void read()}>重新整理結果清單</button>
      <ul className="branch-list">{items.map(item=><li key={`${item.run_id}:${item.report_version}`}>
        <a href={target(item)} aria-current={item.run_id===run.run_id&&item.report_version===run.report_version?'page':undefined}>
          {item.kind==='baseline'?'首次分析':'調整條件的分析'} · 第 {item.report_version} 版
          <small>{item.windows_hours?.length?`前 ${item.windows_hours.join('、')} 小時`:'時間條件未提供'}{item.segment?`・${({country:'國家',platform:'手機系統',acquisition_source:'用戶來源'} as Record<string,string>)[item.segment.field]||'人群'}：${item.segment.value}`:''}</small>
          {item.thresholds&&<small>{Object.entries(item.thresholds).map(([key,values])=>`${({count:'廣告次數',session_count:'使用次數',revenue_sum:'收益（美元）',engaged_seconds:'有效使用（秒）'} as Record<string,string>)[key]||'條件'}：${values.join('、')}`).join('；')}</small>}
          <small>{dateText(item.created_at)}</small>
        </a></li>)}</ul>
      {busy&&<p role="status">正在讀取已完成的分析…</p>}{cursor&&<button disabled={busy} onClick={()=>void read(cursor)}>載入較早的分析</button>}
    </div>
  </details>;
}
