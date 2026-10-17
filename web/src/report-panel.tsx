import {ReportV4} from './report-v4';
import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react';
import { fetchReport, type Candidate, type Report, type Segment } from './report-model';
import type { RunView } from './run-page';
import './report-panel.css';
import {candidateName,evidenceLabel} from './candidate-language';
import {reasonsText,displayNumber} from './report-language';
import {errorText,dateText} from './language';
import {CandidateCatalog} from './candidate-catalog';
import {CandidateEvidence} from './candidate-evidence';
import {CandidateSearchRecord} from './candidate-search';
import {PriorityTable} from './priority-table';
import {sortPriority} from './priority-sort';
const ReportCharts=lazy(()=>import('./report-charts'));

function value(v:unknown,unit='') {return typeof v==='number' ? <span title={`原始值：${v}`} data-value={v}>{displayNumber(v,unit)}</span> : '未知';}
const status=evidenceLabel;
const json=(v:unknown)=>JSON.stringify(v,null,2);
function Raw({title,data}:{title:string;data:unknown}){return <details className="evidence-details"><summary>{title}</summary><pre>{json(data)}</pre></details>;}

export function ReportPanel({run,tab,selected:externalSelected,onSelect,onNavigateTab,onViewChange}:{onViewChange?:(view:{hours:number;cohort:string})=>void;run:RunView;tab:string;selected?:string|null;onSelect?:(id:string|null)=>void;onNavigateTab?:(tab:string)=>void}){
  const [saved,setSaved]=useState<{report:Report;sha256:string;version:number}|null>(null);
  const [loading,setLoading]=useState(false),[error,setError]=useState(''),[revision,setRevision]=useState(0);
  const [localSelected,setLocalSelected]=useState<string|null>(null);
  const selected=externalSelected===undefined?localSelected:externalSelected;
  const setSelected=(id:string|null)=>{setLocalSelected(id);onSelect?.(id);
    if(id&&id===selected){const card=document.querySelector<HTMLElement>('[data-selected-candidate]');
      if(card?.dataset.selectedCandidate===id){card.scrollIntoView({block:'start'});card.focus({preventScroll:true});}}
  };
  const [sort,setSort]=useState('original');
  const [candidateView,setCandidateView]=useState<'priority'|'all'|'search'>('priority');
  const binding=useRef<{key:string;hash:string}|null>(null);
  useEffect(()=>{
    const controller=new AbortController();let current=true;setLoading(true);setError('');
    const version=run.report_version!;const key=`${run.run_id}:${version}`;
    fetchReport(run.run_id,run.dataset_id,version,controller.signal).then(result=>{
      if(!current)return;
      if(binding.current?.key===key && binding.current.hash!==result.sha256)throw new Error('REPORT_VERSION_CHANGED');
      binding.current={key,hash:result.sha256};setSaved({...result,version});
    }).catch(e=>{if(current)setError(e instanceof Error?e.message:'REPORT_READ_FAILED');}).finally(()=>{if(current)setLoading(false);});
    return ()=>{current=false;controller.abort();};
  },[run.run_id,run.dataset_id,run.report_version,revision]);
  const report=saved?.report.run_id===run.run_id&&saved.report.dataset_id===run.dataset_id&&saved.version===run.report_version?saved.report:null;
  const rows=sortPriority(report?.candidates||[],sort,!!report?.catalog);
  const chosen=report?.candidates.find(row=>row.candidate_id===selected);
  const strongest=report?.candidates.filter(row=>typeof (row.metrics?.comparisons as Record<string,unknown>|undefined)?.triggered_minus_untriggered==='number')
    .sort((a,b)=>Number((b.metrics?.comparisons as Record<string,unknown>).triggered_minus_untriggered)-Number((a.metrics?.comparisons as Record<string,unknown>).triggered_minus_untriggered))[0];
  const strongestDifference=(strongest?.metrics?.comparisons as Record<string,unknown>|undefined)?.triggered_minus_untriggered;
  if(report?.schema_version==='4.0'&&report.catalog&&saved)return <ReportV4 tab={tab} onViewChange={onViewChange} report={report} scope={{runId:run.run_id,version:saved.version,reportSha:saved.sha256,catalogSha:report.catalog.sha256}} selected={selected} onSelect={setSelected}/>;
  return <div className="report-panel" data-run-id={run.run_id}>
    {error&&<div role="alert" className="error-message"><p>{errorText(error)} {report?'下方保留先前讀取成功的同一份報告。':'暫時無法顯示這份報告。'}</p><details><summary>錯誤詳細資料</summary>{error}</details></div>}
    {loading&&!report&&<div className="report-loading" role="status"><span/><span/><span/></div>}
    {report&&<>
      {report.summary.finding_recheck&&tab==='概覽'&&<section aria-label="固定舊規則重驗"><h3>之前找到的事件，這次仍適用嗎？</h3>
        <p>使用之前保存的條件檢查這批資料，不重新尋找或調整條件。這次結果仍不是投放成效，之後還需用新資料確認。</p>
        {report.summary.finding_recheck.assessments.map(row=><div key={row.finding_id}><h4>{report.candidates.find(c=>c.candidate_id===row.candidate_id)?candidateName(report.candidates.find(c=>c.candidate_id===row.candidate_id)!.event_spec):'先前保存的事件條件（這次未能產生完整比較）'}</h4><p>{({reusable_evidence:'可重用歷史證據',exploratory_only:'僅探索性結果',insufficient_evidence:'證據不足',not_supported:'本批未支持',not_evaluated:'未完成評估'} as Record<string,string>)[row.status]}</p>
          <Raw title="這項檢查的來源識別資料" data={{finding_id:row.finding_id,candidate_id:row.candidate_id}}/><p>{reasonsText(row.reasons)}</p></div>)}
        <Raw title="重驗來源快照" data={report.summary.finding_recheck}/></section>}
      {report.summary.segment&&['概覽','候選事件','圖表'].includes(tab)&&<SegmentReport segment={report.summary.segment} parent={report.audit.parent_run_id}/>}
      {tab==='概覽'&&!report.summary.segment&&<div className="overview">
        <header className="overview-hero"><p className="overview-kicker">本批分析完成</p><h2>高收益玩家更常做了什麼？</h2><p>從 {value(report.summary.targets?.mature_users)} 位完整觀察 7 天的玩家中，挑出 {value(report.summary.candidate_count)} 個值得先看的行為。</p></header>
        <div className="overview-grid"><div className="overview-primary"><span>值得先看的行為</span><strong>{value(report.summary.candidate_count)}</strong><small>從 {value(report.summary.searched_candidate_count)} 個條件中選出</small></div><div className="overview-stat"><span>完整觀察玩家</span><strong>{value(report.summary.targets?.mature_users)}</strong><small>用於本批收益比較</small></div><div className="overview-stat"><span>新用戶確認</span><strong>{report.summary.historically_validated_count>0?value(report.summary.historically_validated_count):'等待中'}</strong><small>{report.summary.historically_validated_count>0?'已出現相同趨勢':'需要下一批新用戶'}</small></div></div>
        {strongest&&<section className="top-finding"><div><span>本批收益差最明顯</span><h3>{candidateName(strongest.event_spec)}</h3></div><div className="top-finding-number"><strong>{value(strongestDifference,'USD')}</strong><span>符合者平均多賺</span></div><div className="top-finding-stats"><span>{value(strongest.metrics?.coverage,'%')} 玩家符合</span><span>{value(strongest.metrics?.groups.triggered.users)} 人符合</span></div><button className="primary-action" onClick={()=>{setSelected(strongest.candidate_id);onNavigateTab?.('候選事件');}}>查看這個行為</button></section>}
        <div className="overview-action"><div><h3>接下來看什麼</h3><p>比較符合人數、收益差和達標時間，選出值得產品團隊繼續追蹤的事件。</p></div><button onClick={()=>onNavigateTab?.('候選事件')}>查看候選事件</button></div>
      </div>}
      {tab==='候選事件'&&!report.summary.segment&&<header className="page-intro"><div><h2>{candidateView==='priority'?'優先關注的玩家行為':candidateView==='all'?'全部分析結果':'分析範圍'}</h2><p>{candidateView==='priority'?`從 ${report.catalog?.evaluated_count??report.summary.searched_candidate_count} 個條件中，先看這 ${report.candidates.length} 個結果。`:candidateView==='all'?'搜尋、篩選所有已分析的條件。':'查看系統分析過哪些條件，以及哪些條件沒有進入結果。'}</p></div></header>}
      {tab==='候選事件'&&report.catalog&&!report.summary.segment&&<><nav className="view-switcher" aria-label="候選清單模式"><button aria-pressed={candidateView==='priority'} onClick={()=>setCandidateView('priority')}>優先結果 <span>{report.candidates.length}</span></button><button aria-pressed={candidateView==='all'} onClick={()=>setCandidateView('all')}>全部結果 <span>{report.catalog.evaluated_count}</span></button><button aria-pressed={candidateView==='search'} onClick={()=>setCandidateView('search')}>分析紀錄</button></nav>
        {candidateView==='search'&&<CandidateSearchRecord key={`${run.run_id}:${saved!.version}`} scope={{runId:run.run_id,version:saved!.version,reportSha:saved!.sha256,catalogSha:report.catalog.sha256}}/>}
        {candidateView==='all'&&<CandidateCatalog key={`${run.run_id}:${saved!.version}`} scope={{runId:run.run_id,version:saved!.version,reportSha:saved!.sha256,catalogSha:report.catalog.sha256}} onSelect={setSelected}/>}</>}
      {tab==='候選事件'&&!report.summary.segment&&(!report.catalog||candidateView==='priority')&&<><div className="list-toolbar"><span>{rows.length} 個結果</span><label>排序<select value={sort} onChange={e=>setSort(e.target.value)}><option value="original">推薦順序</option><option value="coverage">符合比例最高</option><option value="revenue">收益差最大</option>{report.catalog&&<option value="speed">大多數人最快達標</option>}</select></label></div>
        {rows.length===0?<p>{report.catalog?'這次沒有符合優先選擇條件的候選。全部結果仍保留已評估條件與不足原因，請切換查看。':'沒有可靠候選可展示；請查看品質及限制。'}</p>:report.catalog?<PriorityTable rows={rows} onSelect={setSelected}/>:<div className="data-table" tabIndex={0} role="region" aria-label="候選比較"><table><thead><tr><th>事件條件</th><th>符合／比較用戶數</th><th>符合比例</th><th>符合者前 7 天平均廣告收益</th><th>符合條件所需時間（中位數）</th><th>證據</th></tr></thead><tbody>{rows.map((row,index)=><tr key={row.candidate_id} data-candidate-id={row.candidate_id}><td><button className="text-button" onClick={()=>setSelected(row.candidate_id)}>{candidateName(row.event_spec)}</button></td><td>{value(row.metrics?.groups.triggered.users)} / {value(row.metrics?.groups.all.users)}</td><td>{value(row.metrics?.coverage,'%')}</td><td>{value(row.metrics?.groups.triggered.arpu_usd,'USD')}</td><td>{value(row.metrics?.delay_seconds.median,'h')}</td><td>{status[row.evidence_status]||'結果尚待確認'}</td></tr>)}</tbody></table></div>}
        {chosen&&!report.catalog&&<CandidateDetails candidate={chosen}/>}
      </>}
      {tab==='候選事件'&&report.catalog&&selected&&!report.summary.segment&&<CandidateDrawer onClose={()=>setSelected(null)}><CandidateEvidence scope={{runId:run.run_id,version:saved!.version,reportSha:saved!.sha256,catalogSha:report.catalog.sha256}} id={selected} datasetId={report.dataset_id} onSelect={id=>setSelected(id)}/></CandidateDrawer>}
      {tab==='資料品質'&&<><header className="page-intro"><h2>資料品質</h2><p>確認這份報告用了多少有效資料。</p></header><dl className="facts"><div><dt>資料完整至</dt><dd>{dateText(String(report.summary.data_profile?.complete_through||''))}</dd></div><div><dt>可用的用戶／行為紀錄</dt><dd>{value(report.summary.data_profile?.users)} / {value(report.summary.data_profile?.events)}</dd></div><div><dt>沒有行為紀錄的用戶</dt><dd>{value(report.summary.quality.zero_event_users)}</dd></div><div><dt>還未完整觀察 7 天的用戶</dt><dd>{value(report.summary.targets?.immature_users)}</dd></div></dl><QualityCapabilities quality={report.summary.quality}/><Raw title="分析能力、缺失與排除明細" data={report.summary.quality}/><Raw title="資料分布與完整期" data={report.summary.data_profile}/></>}
      {tab==='圖表'&&!report.summary.segment&&<><header className="page-intro"><h2>行為比較圖</h2><p>用圖表查看人數、收益差與事件之間的關係。</p></header><Suspense fallback={<p role="status">載入圖表元件…</p>}><ReportCharts report={report} onSelect={setSelected}/></Suspense></>}
      <details className="report-meta"><summary>報告資訊與計算方式</summary><div className="report-meta-content"><p>第 {run.report_version} 版，{run.synthetic?'合成資料':'歷史觀察資料'}。收益計算到安裝後第 7 天；未滿 7 天或缺少收益的用戶不會被當成零。</p><button disabled={loading} onClick={()=>setRevision(n=>n+1)}>重新讀取報告</button><p className="dataset-identity">Run：{report.run_id}<br/>SHA256：{saved!.sha256}</p><Raw title="成熟用戶與資料切分" data={report.summary.targets}/><Raw title="計算版本與來源" data={report.audit}/></div></details>
    </>}
  </div>;
}

function CandidateDrawer({children,onClose}:{children:ReactNode;onClose:()=>void}){
  const panel=useRef<HTMLElement>(null);
  const closeButton=useRef<HTMLButtonElement>(null);
  useEffect(()=>{const previous=document.activeElement instanceof HTMLElement?document.activeElement:null;
    const handleKey=(event:KeyboardEvent)=>{if(event.key==='Escape'){onClose();return;}if(event.key!=='Tab'||!panel.current)return;
      const items=[...panel.current.querySelectorAll<HTMLElement>('button,a,select,input,textarea,[tabindex]:not([tabindex="-1"])')].filter(item=>!item.hasAttribute('disabled'));
      if(!items.length){event.preventDefault();panel.current.focus();return;}const first=items[0],last=items[items.length-1];
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
    };document.addEventListener('keydown',handleKey);closeButton.current?.focus();
    return()=>{document.removeEventListener('keydown',handleKey);previous?.focus();};
  },[onClose]);
  return <div className="candidate-drawer-layer"><button className="candidate-drawer-backdrop" aria-label="關閉事件詳情" onClick={onClose}/><aside ref={panel} className="candidate-drawer" role="dialog" aria-modal="true" aria-label="事件詳情"><header><strong>事件詳情</strong><button ref={closeButton} onClick={onClose}>關閉</button></header><div className="candidate-drawer-scroll">{children}</div></aside></div>;
}

function SegmentReport({segment,parent}:{segment:Segment;parent:unknown}){
  const specs=new Map(segment.event_specs?.map(row=>[row.candidate_id,row.event_spec])||[]);
  return <section aria-label="分群診斷"><h3>{{country:'國家',platform:'手機系統',acquisition_source:'用戶來源'}[segment.segment.field]}：{segment.segment.value} 的用戶分析</h3>
    <p>使用原本的事件條件比較這群用戶，不重新挑選條件。這是同批資料的進一步觀察，仍需新資料確認。</p>
    <Raw title="這次人群比較的來源" data={{parent,split:segment.split_id}}/>
    <p>選中用戶：{value(segment.selected_users)}；還未完整觀察 7 天：{value(segment.immature_users)}；欄位未知：{value(segment.field_unknown_users)}。</p>
    <p>限制：{reasonsText(segment.reasons)}。小樣本收益不顯示；未知不等於零。</p>
    <div className="data-table" role="region" aria-label="分群分母與收益" tabIndex={0}><table><thead><tr><th>比較用戶</th><th>已有完整 7 天資料的用戶</th><th>前 7 天廣告收益總額</th><th>前 7 天平均廣告收益</th><th>限制</th></tr></thead><tbody>
      {Object.entries(segment.cohorts).map(([split,cohort])=><tr key={split}><td>{{exploration:'尋找條件的用戶',holdout:'留出來檢查的用戶',immature:'還未完整觀察的用戶'}[split]||'其他用戶組'}</td><td>{value(cohort.users)}</td><td>{value(cohort.revenue_usd,'USD')}</td><td>{value(cohort.arpu_usd,'USD')}</td><td>{reasonsText(cohort.reasons)||'無額外限制'}</td></tr>)}
    </tbody></table></div>
    <h4>這群用戶符合哪些事件？</h4><p>兩組用戶分開比較，不把人數混在一起。數字較好仍不代表投放改善；未知值不當作零。</p>
    {segment.candidates.length===0?<p>這次沒有可比較的事件條件。請查看上述資料限制。</p>:<div className="data-table" role="region" aria-label="分群事件比較" tabIndex={0}><table><thead><tr><th>事件條件</th><th>比較用戶</th><th>符合／比較人數</th><th>符合比例</th><th>符合者前 7 天平均廣告收益</th><th>一半符合者的達標時間</th><th>限制</th></tr></thead><tbody>{segment.candidates.map(row=><tr key={`${row.split}:${row.candidate_id}`} data-segment-candidate={row.candidate_id} data-split={row.split}>
      <td>{specs.has(row.candidate_id)?candidateName(specs.get(row.candidate_id)!):'先前的事件條件（此報告未附完整設定）'}</td><td>{row.split==='holdout'?'留出來檢查的用戶':'尋找條件的用戶'}</td><td>{value(row.metrics?.groups.triggered.users)} / {value(row.users)}</td><td>{value(row.metrics?.coverage,'%')}</td><td>{value(row.metrics?.groups.triggered.arpu_usd,'USD')}</td><td>{value(row.metrics?.delay_seconds.median,'h')}</td><td>{reasonsText(row.reasons)||'仍需新資料確認'}</td>
    </tr>)}</tbody></table></div>}
    <Raw title="固定候選的分群指標與限制" data={segment.candidates}/><Raw title="給工程師的分群事件設定" data={segment.event_specs}/>
  </section>;
}

function CandidateDetails({candidate}:{candidate:Candidate}){return <section aria-label="候選證據詳情" data-selected-candidate={candidate.candidate_id}><h3>{candidateName(candidate.event_spec)}</h3><p>{status[candidate.evidence_status]||'結果尚待確認'}：{reasonsText(candidate.reasons)||'請結合人數、收益差異及下方詳細比較一起判斷。'}</p>
  <div className="data-table"><table><thead><tr><th>比較用戶</th><th>用戶</th><th>前 7 天平均廣告收益</th><th>未知收益用戶</th></tr></thead><tbody>{(['all','triggered','untriggered'] as const).map(key=><tr key={key}><td>{{all:'全部比較用戶',triggered:'符合條件',untriggered:'不符合條件'}[key]}</td><td>{value(candidate.metrics?.groups[key].users)}</td><td>{value(candidate.metrics?.groups[key].arpu_usd,'USD')}</td><td>{value(candidate.metrics?.groups[key].unknown_revenue_users)}</td></tr>)}</tbody></table></div>
  <h4>如何使用這個事件？</h4><p>在上述時間範圍內第一次符合條件時回傳，每位用戶只回傳一次。時間到期後不補發；精確時間邊界和事件名稱可交由工程師查看下方設定。</p><Raw title="給工程師的完整事件設定" data={candidate.event_spec}/>
  <Raw title="差值、信賴區間、逐日穩定性與觸發延遲" data={candidate.metrics}/><Raw title="計算來源與引用" data={candidate.evidence}/><p>過去收益較高，不代表投放一定更有效。同時嘗試很多條件可能偶然找到好結果；下方區間並未排除這種影響。</p></section>;}

function QualityCapabilities({quality}:{quality:Report['summary']['quality']}){
  const capabilities=quality.capabilities;
  if(!capabilities||typeof capabilities!=='object'||Array.isArray(capabilities))return <p>尚未提供可分析行為的完整檢查結果。請查看資料明細，不將缺少的結果當作可用。</p>;
  const labels:Record<string,string>={revenue_analysis:'前 7 天廣告收益',revenue_trigger:'收益達標的事件',ad_frequency:'廣告展示次數',session_count:'使用 App 的次數',engaged_seconds:'有效使用時間'};
  return <section aria-label="目前可分析的行為"><h4>這份資料能分析什麼？</h4>{Object.entries(capabilities).map(([key,raw])=>{
    if(!raw||typeof raw!=='object'||Array.isArray(raw))return <p key={key}>{labels[key]||'其他分析'}：檢查結果不完整。</p>;
    const reasons=Array.isArray(raw.reasons)?raw.reasons.filter((v):v is string=>typeof v==='string'):[];
    return <p key={key}>{labels[key]||'其他分析'}：{raw.enabled===true?'可以分析':raw.enabled===false?'目前無法分析':'尚未確認'}。{reasonsText(reasons)}</p>;
  })}<p>若缺少必要欄位，請補齊來源資料後建立新的分析；原報告仍會保留。</p></section>;
}
