import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';
import truth from '../../tests/fixtures/hand/expected.json';
import type { RunView } from './run-page';
import { ReportPanel } from './report-panel';
import {ChatPanel} from './chat-panel';
import {api} from './upload-client';
import {BranchPicker,ReportExports} from './branch-picker';
import './accessibility.css';

const tabs = ['概覽', '候選事件', '圖表', '資料品質'] as const;
type Tab = typeof tabs[number];
function preference(key: string) { try { return localStorage.getItem(key); } catch { return null; } }
function remember(key: string, value: string) { try { localStorage.setItem(key, value); } catch { /* Optional preference. */ } }
const clamp = (width: number) => Math.min(480, Math.max(320, width));
const fixtureConditions = [
  ['rewarded_count_5_in_6h', '6 小時內累積 5 次激勵廣告'], ['sessions_2_in_24h', '24 小時內第 2 次開啟 App'],
  ['revenue_005_in_6h', '6 小時內廣告收益達 0.05 美元'], ['revenue_005_in_24h', '24 小時內廣告收益達 0.05 美元'],
  ['engaged_120_in_6h', '6 小時內有效互動達 120 秒'],
] as const;

export function Workspace({run}:{run?:RunView}) {
  const fixture = !run && new URLSearchParams(window.location.search).get('demo') === 'hand';
  const [width, setWidth] = useState(() => { const saved = Number(preference('ac.chatWidth')); return Number.isFinite(saved) && saved >= 320 ? clamp(saved) : 360; });
  const [tab, setTab] = useState<Tab>(() => { const saved = new URLSearchParams(location.search).get('tab')||preference('ac.resultTab'); return tabs.includes(saved as Tab) ? saved as Tab : '概覽'; });
  const [mobilePanel, setMobilePanel] = useState<'results' | 'chat'>('results');
  const [selected, setSelected] = useState<string | null>(()=>new URLSearchParams(location.search).get('candidate'));
  const [reportView,setReportView]=useState<{hours:number;cohort:string}|undefined>();
  useEffect(()=>setReportView(undefined),[run?.run_id,run?.report_version]);
  const [referenceError,setReferenceError]=useState('');
  async function openReference(context:{selected_run_id:string;report_version:number},reference:string){
    setReferenceError('');
    try{
      const match=/^report:([0-9a-f-]{36})#(\/(?:summary|candidates\/\d+|diagnostics\/overlap))$/.exec(reference);
      if(!match)throw new Error('REFERENCE_INVALID');
      const result=await api<{run_id:string;root_run_id:string;artifact_id:string;report_version:number;candidate_id:string|null;tab:Tab}>(`/api/runs/${context.selected_run_id}/references/${match[1]}?version=${context.report_version}&pointer=${encodeURIComponent(match[2])}`);
      const url=new URL(location.href);url.searchParams.set('run',result.run_id);url.searchParams.set('artifact',result.artifact_id);url.searchParams.set('tab',result.tab);
      url.searchParams.set('version',String(result.report_version));
      if(result.root_run_id!==run?.root_run_id)url.searchParams.delete('conversation');
      if(result.candidate_id)url.searchParams.set('candidate',result.candidate_id);else url.searchParams.delete('candidate');
      if(result.run_id!==run?.run_id||result.report_version!==run?.report_version){location.assign(url);return;}
      history.replaceState(null,'',url);setSelected(result.candidate_id);setTab(result.tab);setMobilePanel('results');
    }catch(e){setReferenceError(e instanceof Error?e.message:'引用讀取失敗');}
  }
  const drag = useRef<{start: number; width: number} | null>(null);
  useEffect(() => remember('ac.chatWidth', String(width)), [width]);
  useEffect(() => remember('ac.resultTab', tab), [tab]);
  useEffect(()=>{
    if(!run)return;
    const url=new URL(location.href);url.searchParams.set('tab',tab);
    if(selected)url.searchParams.set('candidate',selected);else url.searchParams.delete('candidate');
    history.replaceState(null,'',url);
  },[run?.run_id,tab,selected]);
  function tabKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = event.key === 'ArrowRight' ? (index+1)%tabs.length : event.key === 'ArrowLeft' ? (index+tabs.length-1)%tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length-1 : null;
    if (next === null) return;
    event.preventDefault(); setTab(tabs[next]); document.getElementById(`tab-${next}`)?.focus();
  }
  return <div className="workspace" style={{'--chat-width': `${width}px`} as CSSProperties}>
    <header className="toolbar"><a className="wordmark" href="/">AC Event Agent</a><span className="toolbar-divider"/>
      <span className="project-name">{run?.name || (fixture ? '範例資料分析' : '分析工作區')}</span>
      <div className="toolbar-actions">{run?<BranchPicker run={run}/>:<span className="version">{fixture ? '範例資料' : '尚未選擇資料'}</span>}<a href="/history">歷史</a>{run ? <ReportExports run={run}/> : <button disabled title="選取已發布的分析版本後可匯出">匯出</button>}</div>
    </header>
    <div className="mobile-switch" role="group" aria-label="工作區面板"><button aria-pressed={mobilePanel === 'results'} onClick={() => setMobilePanel('results')}>結果</button><button aria-pressed={mobilePanel === 'chat'} onClick={() => setMobilePanel('chat')}>對話</button></div>
    <div className="panels" data-mobile-panel={mobilePanel}>
      <aside className="chat-panel" aria-label="Agent 對話">
        {run?<ChatPanel key={run.run_id} run={run} candidate={selected} reportView={reportView} onReference={(context,reference)=>void openReference(context,reference)}/>:<>
        <div className="panel-heading"><h1>分析助理</h1><span className="status">{fixture?'示範模式':'等待資料'}</span></div>
        <div className="chat-scroll pre-upload-scroll" tabIndex={0} aria-label="對話內容">
          <div className="pre-upload-empty"><p className="pre-upload-eyebrow">{fixture?'示範資料不啟用助理':'尚未連接資料'}</p><h2>{fixture?'上傳資料後再開始提問':'先上傳資料，再開始對話'}</h2><p>{fixture?'目前範例只用來查看介面與手算結果。':'分析完成後，我會根據報告回答，並帶你查看對應證據。'}</p><a className="pre-upload-action" href="/upload">上傳資料</a></div>
        </div>
        <div className="composer pre-upload-composer"><div className="composer-box"><label className="composer-label" htmlFor="question">詢問分析助理</label><textarea id="question" disabled placeholder="分析完成後即可提問" rows={1}/><div className="composer-footer"><span className="context-chip">等待資料</span><button disabled>送出</button></div></div></div>
        </>}
      </aside>
      <div className="splitter" role="separator" aria-label="調整對話欄寬度" aria-orientation="vertical" aria-valuemin={320} aria-valuemax={480} aria-valuenow={width} tabIndex={0}
        onKeyDown={event => { const delta = event.key === 'ArrowLeft' ? -10 : event.key === 'ArrowRight' ? 10 : 0; if (delta || event.key === 'Home' || event.key === 'End') { event.preventDefault(); setWidth(event.key === 'Home' ? 320 : event.key === 'End' ? 480 : clamp(width+delta)); } }}
        onPointerDown={event => { if (event.button !== 0) return; drag.current = {start: event.clientX, width}; event.currentTarget.setPointerCapture(event.pointerId); }}
        onPointerMove={event => { if (drag.current) setWidth(clamp(drag.current.width+event.clientX-drag.current.start)); }}
        onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }} />
      <main className="results-panel" aria-label="分析結果">
        {referenceError&&<div role="alert"><p>目前無法開啟這項證據，因為來源或版本未通過檢查。原本的報告仍保留，你可以重新讀取頁面再試。</p><details><summary>引用錯誤詳細資料</summary>{referenceError}</details></div>}
        <div className="result-tabs" role="tablist" aria-label="結果內容">{tabs.map((name,index) => <button key={name} role="tab" id={`tab-${index}`} aria-selected={tab === name} aria-controls="result-content" tabIndex={tab === name ? 0 : -1} onClick={() => setTab(name)} onKeyDown={event => tabKey(event,index)}>{name}</button>)}</div>
        <div className="result-scroll" id="result-content" role="tabpanel" aria-labelledby={`tab-${tabs.indexOf(tab)}`} tabIndex={0}>
          {fixture && <div className="fixture-notice">這是示範資料，不是真實客戶分析，也不是投放建議。</div>}
          {!run&&<div className="result-heading"><div><p className="eyebrow">{fixture ? '範例資料' : '前 7 天廣告收益分析'}</p><h2>{tab}</h2></div><span className="status">{fixture ? '資料不足以判斷' : '尚無分析'}</span></div>}
          {run ? <ReportPanel run={run} tab={tab} onViewChange={setReportView} selected={selected} onSelect={setSelected} onNavigateTab={next=>setTab(next as Tab)}/> : !fixture ? <section className="empty-state"><h3>從一份用戶資料開始</h3><p>準備一份用戶表與用戶行為紀錄，開始建立分析資料。</p><a className="button-link" href="/upload">上傳資料</a><p><a href="?demo=hand">檢視合成資料範例</a></p><p className="muted">範例僅供了解操作，不會啟動分析。</p></section> : <>
            {tab === '概覽' && <><p className="lead">這份樣本適合核對計算，不適合做投放決策。</p><div className="metrics-strip"><div><span>已有完整 7 天資料的用戶</span><strong>{truth.mature_users.length}<small> 人</small></strong></div><div><span>前 7 天廣告總收益</span><strong>{truth.mature_revenue_usd.toFixed(2)}<small> USD</small></strong></div><div><span>每位用戶平均廣告收益</span><strong>{truth.mature_arpu_usd.toFixed(3)}<small> USD</small></strong></div></div>
              <section><h3>先確認分析邊界</h3><p>平均收益包含沒有行為紀錄的用戶。這份範例人數太少，不能用來判斷哪些條件更有效。</p><dl className="facts"><div><dt>資料完整至</dt><dd>2026-01-14 00:00 UTC</dd></div><div><dt>計算期間</dt><dd>從安裝起，至滿 7 天之前</dd></div><div><dt>尚未完整觀察 7 天的用戶</dt><dd>{truth.immature_users.length} 人，目標值未知</dd></div><div><dt>資料來源</dt><dd>人工建立的範例資料</dd></div></dl></section>
              <section><h3>候選打點樣例</h3><p className="muted">以下用於核對首次觸發，不是系統推薦。</p><FixtureTable onSelect={setSelected}/></section>
              <section><h3>為什麼不能直接拿來投放？</h3><p>樣本人數太少，暫時無法比較條件的好壞。正式分析會另外留一批用戶檢查找到的條件。</p><p>收益可能延遲取得，打點只能在資料已可用時發生。此範例刻意包含延遲、重複、零事件與未成熟用戶。</p><p>報告數字來自資料計算。沒有資料時會說明原因，不會自行填入數字。</p></section></>}
            {tab === '候選事件' && <><p>手算候選條件與首次觸發人數；不代表推薦清單。</p><FixtureTable onSelect={setSelected}/></>}
            {tab === '圖表' && <section className="empty-state"><h3>這份範例沒有分析圖表</h3><p>上傳資料完成分析後，可查看符合條件的人數、收益與不同條件的比較。</p></section>}
            {tab === '資料品質' && <><p>以下是範例資料的完整性檢查。</p><dl className="facts"><div><dt>輸入用戶</dt><dd>{truth.input_users}</dd></div><div><dt>輸入事件</dt><dd>{truth.input_events}</dd></div><div><dt>去重後事件</dt><dd>{truth.unique_events}</dd></div><div><dt>重複事件</dt><dd>{truth.duplicate_events}</dd></div><div><dt>證據狀態</dt><dd>人數不足，暫時無法判斷</dd></div></dl></>}
            {selected && <section className="selected-detail" aria-label="範例事件詳情"><button className="close-detail" onClick={() => setSelected(null)}>收起詳情</button><h3>用戶何時首次符合條件？</h3><p>下方紀錄用來核對範例的計算結果，不是真實用戶資料，也不是投放建議。</p><details><summary>查看範例用戶與精確時間</summary><pre>{JSON.stringify(truth.triggers[selected as keyof typeof truth.triggers], null, 2)}</pre></details></section>}
          </>}
        </div>
      </main>
    </div>
  </div>;
}
function FixtureTable({onSelect}: {onSelect: (key: string) => void}) {
  return <div className="data-table" tabIndex={0} role="region" aria-label="手算候選條件"><table><thead><tr><th scope="col">候選條件</th><th scope="col">觸發人數</th><th scope="col">狀態</th></tr></thead><tbody>{fixtureConditions.map(([key,name]) => <tr key={key}><td><button className="text-button" onClick={() => onSelect(key)}>{name}</button></td><td>{Object.keys(truth.triggers[key]).length}</td><td><span className="status">手算範例</span></td></tr>)}</tbody></table></div>;
}
