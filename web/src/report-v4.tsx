import {useEffect,useState} from 'react';
import type {Report} from './report-model';
import {fetchCandidateDetail,fetchCandidatePage,type CandidateScope} from './candidate-client';
import {CandidateSearchRecord} from './candidate-search';
import {reasonText} from './report-language';
import {evidenceLabel,incomeComparison,difference,overviewPoint,deadlineLabel,reportTotals,reportNumber,displayRuleName} from './v4-presentation';

import './v4-report.css';

type RecordData=Record<string,any>;
const capabilityLabels:RecordData={revenue_analysis:'廣告收入',session_analysis:'遊玩次數',level_analysis:'關卡行為',retention_analysis:'回訪行為',revenue_trigger:'收入達標時間',ad_frequency:'廣告頻次',session_count:'遊玩次數',engaged_seconds:'遊玩時間',level_event_counts:'關卡次數',level_identity:'關卡識別',level_progress:'關卡進度',attempt_pairing:'每次闖關結果',session_return:'回訪行為',distinct_session_count:'不同遊玩次數',session_duration:'遊玩時長',same_session_cross:'同一次遊玩內的行為組合'};
export const cohorts:Record<string,string>={observation:'全量',exploration:'找規律',holdout:'Holdout'};
export const checkpoints=[24,48,72,96,120,144];
export function TimeButtons({hours,onChange,label='觀察到'}:{hours:number;onChange:(h:number)=>void;label?:string}){return <div className="v4-time-controls"><span>{label}</span><nav aria-label={label}>{checkpoints.map(h=><button key={h} aria-pressed={hours===h} onClick={()=>onChange(h)}>{h}h</button>)}</nav></div>;}
export function OverviewCards({report}:{report:Report}){const r=report as unknown as RecordData,t=r.summary.targets;const group=reportTotals(r);return <div className="v4-metrics"><div><span>完整觀察七天的玩家</span><strong>{n(t?.mature_users)}</strong><small>未滿七天 {n(t?.immature_users)} 人不納入</small></div><div><span>七天累積廣告收入</span><strong>{n(group?.revenue_usd,'USD')}</strong><small>每位玩家平均 {n(group?.arpu_usd,'USD')}</small></div><div><span>已搜尋的基本規則</span><strong>{n(r.summary.searched_candidate_count)}</strong><small>6 個觀察時間點</small></div><div><span>正式比較問題</span><strong>{n(r.summary.formal_comparison_count)}</strong><small>時間點 × 規則 × 檢驗問題</small></div></div>;}
const scopeNote=(s:string)=>s==='observation'?'全量成熟玩家，用來描述整體行為。':s==='exploration'?'找規律的玩家，用來選條件與門檻；不代表獨立驗證。':'未參與找規律的玩家，條件固定後用來檢查是否仍成立。';
const n=(value:any,unit='')=>typeof value==='number'?reportNumber(value,unit):'尚無法判斷';
export function DecisionRow({row,hours,cohort,onSelect,selected=false}:{row:RecordData;hours:number;cohort:string;onSelect?:(id:string)=>void;selected?:boolean}){
  const d=overviewPoint(row,hours,cohort),p=d.point,g=p?.groups,hit=g?.triggered;
  const exploratory=row.evidence_status==='exploratory';
  const association=(d.tests??[]).find((t:RecordData)=>t.question==='d7_association');
  const spec=row.event_spec??row.summary?.event_spec;
  return <tr className={selected?'is-selected':''} onClick={()=>onSelect?.(row.candidate_id)}><td data-label="行為條件" title={String(row.name??spec?.name??'')}>{onSelect?<button className="v4-rule-button" aria-pressed={selected} onClick={e=>{e.stopPropagation();onSelect(row.candidate_id);}}>{displayRuleName(row.name??spec?.name)}</button>:<strong>{displayRuleName(row.name??spec?.name)}</strong>}<p>{deadlineLabel(spec,hours)}</p><small>{p?.applicable===false?'不適用／資料不足':exploratory?'僅供探索':''}</small></td>
    <td data-label="七天平均收入／人"><strong>{n(hit?.arpu_usd,'USD')}</strong><p>{incomeComparison(difference(hit?.arpu_usd,g?.untriggered?.arpu_usd),'未符合玩家')}</p><small>未符合玩家：{n(g?.untriggered?.arpu_usd,'USD')}／人</small></td>
    <td data-label="辨識規模"><strong>{n(hit?.users)} 人</strong><p>可判定玩家中 {n(p?.coverage,'%')}</p><small>無法判定 {n(g?.unknown?.users)} 人</small></td>
    <td data-label="達標時間">{d.mode==='snapshot'?<p>指定時間判斷，不推算首次達標</p>:<><strong>平均：{n(p?.delay_seconds?.mean,'h')}</strong><p>50%：{n(p?.delay_seconds?.median,'h')}</p><p>90%：{n(p?.delay_seconds?.p90,'h')}</p><small>截至目前已達標玩家 · 從{spec?.origin==='first_open'?'首次開啟':'安裝'}起算</small>{p?.delay_seconds?.unknown_users>0&&<small>其中 {n(p.delay_seconds.unknown_users)} 人達標時間未知，未納入</small>}</>}<small>之後至 D7 平均收入：{n(hit?.remaining_arpu_usd,'USD')}</small></td>
    <td data-label="Holdout 驗證"><p>{evidenceLabel(association,exploratory)}</p><small>Holdout 符合 {n(d.holdout?.groups?.triggered?.users??d.holdout_compact?.users)} 人</small></td>
    </tr>;
}


function TimeChart({rows,mode}:{rows:RecordData[];mode?:string}){
  const max=Math.max(1,...rows.map(r=>r.groups.triggered.users??0));
  const first=rows[0]?.groups.triggered.users??0;
  const cumulative=mode!=='snapshot'&&rows[0]?.baseline_24h_applicable!==false;
  return <figure style={{margin:'20px 0'}}><figcaption>{cumulative?'第一天已達標與之後才達標的玩家':'各觀察時間符合條件的玩家'}</figcaption>
    <svg role="img" aria-label="六個觀察時間的達標玩家人數" viewBox="0 0 660 235" style={{width:'100%',maxWidth:850}}>
      {rows.map((r,i)=>{const count=r.groups.triggered.users??0,base=cumulative?Math.min(first,count):count,extra=cumulative?Math.min(count-base,r.groups.added_since_24h.users??0):0,unknown=Math.max(0,count-base-extra),x=35+i*105,y=190-count/max*145;
        return <g key={r.hours}><title>{r.hours} 小時：{r.applicable?n(count)+' 人':'不適用或資料不足'}</title>
          {r.applicable&&<><rect x={x} y={190-base/max*145} width={55} height={base/max*145} fill="#647abb"/><rect x={x} y={190-(base+extra)/max*145} width={55} height={extra/max*145} fill="#b9c8ee"/><rect x={x} y={y} width={55} height={unknown/max*145} fill="#969da9"/></>}
          <text x={x+27} y={r.applicable?y-9:175} textAnchor="middle" fill="currentColor" fontSize="12">{r.applicable?n(count):'未知'}</text><text x={x+27} y={215} textAnchor="middle" fill="currentColor" fontSize="12">{r.hours}h</text></g>;
      })}
    </svg><p>{cumulative?'深色：第一天已達標；淺色：第一天未達標、之後才達標；灰色：第一天無法判定。':'指定時間條件可能符合、退出或再次符合，柱狀高度不是持續累積。'}</p>
  </figure>;
}

export function TimeEvidence({analysis,initialHours=24,initialCohort='observation',onViewChange,interactive=true}:{interactive?:boolean;analysis:RecordData;initialHours?:number;initialCohort?:string;onViewChange?:(view:{hours:number;cohort:string})=>void}){
  const [scope,setScope]=useState(initialCohort);
  useEffect(()=>setScope(initialCohort),[initialCohort]);
  const [hours,setHours]=useState(initialHours);
  useEffect(()=>setHours(initialHours),[initialHours]);
  const origin=analysis.origin==='first_open'?'首次開啟後':'安裝後';
  const rows=(analysis[scope]??[]) as RecordData[];
  const point=rows.find(r=>r.hours===hours);
  const tests=(analysis.inference??[]).filter((r:RecordData)=>r.hours===hours&&r.question==='d7_association');
  return <section aria-label="行為與時間比較">
    {interactive&&<nav className="view-switcher" aria-label="比較資料來源">{Object.entries(cohorts).map(([key,label])=><button key={key} aria-pressed={scope===key} onClick={()=>{setScope(key);onViewChange?.({hours,cohort:key});}}>{label} · {n(analysis[key]?.[0]?.groups.all.users)} 人</button>)}</nav>}
    <p>{scopeNote(scope)} 本視角母體：{n(rows[0]?.groups.all.users)} 人。全量包含探索集與 Holdout，不能把三者相加。</p>
    {!rows.length&&<p>此舊報告未保存本群體的明細，請建立新版分析；不從全量推算首次達標時間。</p>}
    {interactive&&<TimeButtons hours={hours} label={`${origin}觀察到`} onChange={h=>{setHours(h);onViewChange?.({hours:h,cohort:scope});}}/>}
    {point&&<><h3>這群玩家有多大價值？</h3><p>符合 {n(point.groups.triggered.users)} 人，未符合 {n(point.groups.untriggered.users)} 人；無法判定 {n(point.groups.unknown.users)} 人。覆蓋率以可判定玩家為分母。</p><div className="data-table"><table><thead><tr><th>人群</th><th>七天平均收入</th><th>七天總收入</th><th>占本群玩家七天收入</th></tr></thead><tbody>{[['符合',point.groups.triggered],['未符合',point.groups.untriggered]].map(([name,g])=><tr key={String(name)}><td>{String(name)}</td><td>{n((g as any).arpu_usd,'USD')}</td><td>{n((g as any).revenue_usd,'USD')}</td><td>{n((g as any).share_of_total_d7,'%')}</td></tr>)}</tbody></table></div><p>符合玩家截至 {hours} 小時已發生的總收入：{n(point.groups.triggered.before_revenue_usd,'USD')}；之後至第七天：{n(point.groups.triggered.remaining_revenue_usd,'USD')}。這是收入發生時間分解，不是回傳當下可用收入。</p></>}
    <h3>多觀察一天，能多找到誰？</h3>
    <TimeChart rows={rows} mode={analysis.rule?.mode??(rows[0]?.transition_kind==='entered_exited'?'snapshot':'cumulative')}/>
    {point&&<p>截至 {hours} 小時已達標：{n(point.groups.triggered.users)} 人；{point.baseline_24h_applicable===false?'此條件不適用 24 小時比較':hours===24?'第一天：比較基準':`比第一天多找到 ${n(point.groups.added_since_24h.users)} 人`}。{point.baseline_24h_unknown_users>0?`第一天無法判定的 ${n(point.baseline_24h_unknown_users)} 人不納入與第一天的差額。`:''}</p>}
    <div className="data-table" tabIndex={0} role="region" aria-label="每天新增玩家"><table><thead><tr><th>觀察到</th><th>目前符合</th><th>本日新增</th><th>新增玩家七天平均收入</th><th>新增玩家七天總收入</th><th>占本群七天收入</th><th>比第一天多找到</th><th>退出條件</th></tr></thead><tbody>{rows.map(r=><tr key={r.hours}><td>{origin} {r.hours} 小時</td><td>{r.applicable?n(r.groups.triggered.users):'不適用／資料不足'}</td><td>{n(r.groups.added.users)}</td><td>{n(r.groups.added.arpu_usd,'USD')}</td><td>{n(r.groups.added.revenue_usd,'USD')}</td><td>{n(r.groups.added.share_of_total_d7,'%')}</td><td>{r.baseline_24h_applicable===false?'不適用 24 小時比較':r.hours===24?'第一天：比較基準':n(r.groups.added_since_24h.users)}</td><td>{r.transition_kind==='entered_exited'?n(r.groups.exited.users):'已達標不撤銷'}</td></tr>)}</tbody></table></div>
    <p>新增是多辨識到的玩家，不是這個條件創造的收入。比率條件會顯示當日新增符合及退出，不能當作持續累積。</p>
    {analysis.existing?.length>0&&<p>現行方案：{analysis.existing.map((r:RecordData)=>`${displayRuleName(r.name)}（截止 ${r.deadline_hours} 小時）`).join('；')}。上表其他期限是延長或縮短後的替代方案。</p>}
    {analysis.cumulative_comparison&&<><h3>集中遊玩和慢慢累積，有什麼不同？</h3><p>同時間、同門檻比較；這是人群描述，未單獨證明哪一種較好。</p><div className="data-table"><table><thead><tr><th>觀察到</th><th>累積達標玩家</th><th>累積達標七天平均收入</th><th>24 小時集中達標玩家</th><th>集中達標七天平均收入</th></tr></thead><tbody>{rows.map((p:RecordData,i:number)=>{const c=analysis.cumulative_comparison[scope]?.[i];return <tr key={p.hours}><td>{p.hours} 小時</td><td>{n(c?.groups?.triggered.users)}</td><td>{n(c?.groups?.triggered.arpu_usd,'USD')}</td><td>{n(p.groups.triggered.users)}</td><td>{n(p.groups.triggered.arpu_usd,'USD')}</td></tr>;})}</tbody></table></div></>}
    <h3>Holdout 驗證</h3>
    <p>以下始終只使用未參與找規則的玩家，與上方全量描述分開。通過狀態已包含多重比較校正；95% 差異範圍為個別比較的重抽樣區間，不代替校正後結論。</p>
    {['d7_association'].map(question=>{const test=tests.find((t:RecordData)=>t.question===question),ci=test?.bootstrap?.difference_ci95_usd,hp=analysis.holdout?.find((p:RecordData)=>p.hours===hours);return <div key={question}><h4>是否能辨識七天收入較高的玩家？</h4><p>{evidenceLabel(test,analysis.evidence_status==='exploratory')}</p><p>符合 {n(test?.candidate_users??hp?.groups.triggered.users)} 人 ／ 未符合 {n(test?.comparison_users??hp?.groups.untriggered.users)} 人{test?.common_users!==undefined?`；本項檢驗的共同可判定母體 ${n(test.common_users)} 人`:''}。</p><p>Holdout 七天平均收入：{incomeComparison(test?.difference_usd,'未符合玩家')}；95% 差異範圍（此行為減去比較人群）：{ci?`${n(ci[0],'USD')} ～ ${n(ci[1],'USD')}`:'尚無法判斷'}。</p></div>})}
    <details><summary>查看這個時間點的計算依據</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify({point,tests},null,2)}</pre></details>
  </section>;
}

export function ReportV4({report,scope,selected,onSelect,tab='概覽',onViewChange}:{tab?:string;onViewChange?:(view:{hours:number;cohort:string})=>void;report:Report;scope:CandidateScope;selected:string|null;onSelect:(id:string|null)=>void}){
  const [items,setItems]=useState<RecordData[]>([]),[page,setPage]=useState(1),[count,setCount]=useState(0),[error,setError]=useState('');
  const [exporting,setExporting]=useState(false);
  const [detail,setDetail]=useState<RecordData|null>(null),[view,setView]=useState('priority'),[hours,setHours]=useState(24),[cohort,setCohort]=useState('observation');
  useEffect(()=>{if(view!=='all')return;const c=new AbortController();setError('');setItems([]);fetchCandidatePage(scope,{page,window_hours:hours},c.signal).then(p=>{setItems(p.items);setCount(p.filtered_count);}).catch(e=>{if(!c.signal.aborted)setError(String(e));});return()=>c.abort();},[scope.runId,scope.version,scope.reportSha,page,hours,view]);
  useEffect(()=>{setDetail(null);if(!selected)return;const c=new AbortController();fetchCandidateDetail(scope,selected,report.dataset_id,c.signal).then(setDetail).catch(e=>{if(!c.signal.aborted)setError(String(e));});return()=>c.abort();},[scope.runId,scope.version,selected]);
  useEffect(()=>{if(tab==='候選事件')setView('all');else setView('priority');},[tab]);
  useEffect(()=>{onViewChange?.({hours,cohort});},[hours,cohort,onViewChange]);
  useEffect(()=>{if(!selected&&report.candidates[0])onSelect(report.candidates[0].candidate_id);},[scope.runId,scope.version,selected,report.candidates,onSelect]);
  const selectRule=(id:string)=>{onSelect(id);requestAnimationFrame(()=>document.querySelector('[data-selected-candidate]')?.scrollIntoView({block:'start'}));};
  const r=report as unknown as RecordData;
  const activeId=selected??r.candidates?.[0]?.candidate_id;
  const activeCandidate=r.candidates?.find((c:RecordData)=>c.candidate_id===activeId);
  const activeAnalysis=detail?.candidate_id===activeId?detail?.validation:activeCandidate?{...activeCandidate.time_analysis,rule:{mode:activeCandidate.event_spec.mode},origin:activeCandidate.event_spec.origin,evidence_status:activeCandidate.evidence_status}:undefined;
  async function exportHtml(){setExporting(true);setError('');try{const {downloadV4Html}=await import('./v4-export');await downloadV4Html(report,scope);}catch(e){setError(String(e));}finally{setExporting(false);}}
  const chartCandidate=r.candidates?.find((c:RecordData)=>c.candidate_id===selected)??(!selected?r.candidates?.[0]:undefined);
  const chartAnalysis=detail?.candidate_id===selected?detail?.validation:chartCandidate?{...chartCandidate.time_analysis,evidence_status:chartCandidate.evidence_status}:undefined;
  const changeView=(v:{hours:number;cohort:string})=>{setHours(v.hours);setCohort(v.cohort);};
  if(tab==='資料品質')return <div className="report-panel v4-report"><h2>這批資料可以分析什麼？</h2><p>完整觀察七天：{n(report.summary.targets?.mature_users)} 人；未滿七天：{n(r.summary.targets?.immature_users)} 人。</p><p>不要求每天登入；來源用戶表中的零事件玩家也包含在內。缺失收入不補零。</p><ul>{Object.entries(report.summary.quality.capabilities??{}).map(([key,v])=><li key={key}>{capabilityLabels[key]??key}：{(v as RecordData).enabled?'可分析':'資料不足'}；{((v as RecordData).reasons??[]).map(reasonText).join('；')}</li>)}</ul><details><summary>查看資料品質依據</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(report.summary.quality,null,2)}</pre></details><CandidateSearchRecord scope={scope}/></div>;
  if(tab==='圖表')return <div className="report-panel v4-report"><h2>觀察時間與達標玩家</h2><label style={{display:"block"}}>選擇比較行為 <select style={{maxWidth:"100%",display:"block"}} value={selected??report.candidates[0]?.candidate_id??''} onChange={e=>onSelect(e.target.value)}>{report.candidates.map(c=><option key={c.candidate_id} value={c.candidate_id}>{displayRuleName(c.event_spec.name)}</option>)}{selected&&!r.candidates.some((c:RecordData)=>c.candidate_id===selected)&&<option value={selected}>{displayRuleName(detail?.event_spec.name??'正在讀取選定行為')}</option>}</select></label>{chartAnalysis?<TimeEvidence analysis={chartAnalysis} initialHours={hours} initialCohort={cohort} onViewChange={changeView}/>:<p>{selected?'正在讀取選定行為…':'目前沒有可繪製的規則，請查看候選事件與資料品質。'}</p>}</div>;
  return <div className="report-panel v4-report">
    <header className="overview-hero"><p className="overview-kicker">V4 · 行為與時間分析</p><h2>行為分析</h2>{report.synthetic&&<span>合成資料</span>}</header>
    <OverviewCards report={report}/>
    <details><summary>哪些資料可用、哪些方向還不能分析？</summary><ul>{Object.entries(report.summary.quality.capabilities??{}).map(([key,value])=>{const c=value as RecordData;return <li key={key}>{capabilityLabels[key]??key}：{c.enabled?'可分析':'尚不能完整分析'}{c.reasons?.length?'；'+c.reasons.map(reasonText).join('；'):''}</li>;})}</ul></details>
    <nav className="view-switcher" aria-label="V4 結果範圍">{[['priority','值得比較的行為'],['all','全部完整比較'],['search','搜尋範圍與未驗證原因']].map(([key,label])=><button key={key} aria-pressed={view===key} onClick={()=>setView(key)}>{label}</button>)}</nav>
    {error&&<p role="alert">讀取失敗：{error}</p>}
    <div className="v4-comparison-controls"><h3>行為比較</h3><nav className="view-switcher" aria-label="主表玩家範圍">{Object.entries(cohorts).map(([key,label])=><button key={key} aria-pressed={cohort===key} onClick={()=>setCohort(key)}>{label} · {n(key==='observation'?r.summary.targets?.mature_users:r.summary.targets?.summary?.[key]?.users)} 人</button>)}</nav></div>
    <TimeButtons hours={hours} label={`${r.candidates?.[0]?.event_spec.origin==='first_open'?'首次開啟':'安裝'}後觀察到`} onChange={h=>{setHours(h);setPage(1);}}/>
    {view==='search'?<CandidateSearchRecord scope={scope}/>:<><div className="data-table v4-decision-table" role="region" aria-label="行為比較" tabIndex={0}><table><thead><tr><th>行為條件</th><th>七天平均收入／人</th><th>辨識規模</th><th>達標時間</th><th>Holdout 驗證</th></tr></thead><tbody>{(view==='priority'?report.candidates:items).map((row:RecordData)=><DecisionRow key={row.candidate_id} row={row} hours={hours} cohort={cohort} selected={row.candidate_id===activeId} onSelect={selectRule}/>)}</tbody></table></div>
    {view==='all'&&<nav aria-label="結果分頁"><button disabled={page<=1} onClick={()=>setPage(page-1)}>上一頁</button><span>第 {page} 頁，共 {Math.max(1,Math.ceil(count/50))} 頁</span><button disabled={page*50>=count} onClick={()=>setPage(page+1)}>下一頁</button></nav>}
    {!report.candidates.length&&<p>這次沒有足夠資料選出優先方案。仍可查看搜尋範圍與資料限制。</p>}</>}
    {view!=='search'&&activeId&&<section className="v4-detail" data-selected-candidate={activeId}><h2>{displayRuleName(activeCandidate?.event_spec.name??detail?.event_spec.name??'行為詳情')}</h2><details><summary>精確條件</summary><p>{activeCandidate?.event_spec.name??detail?.event_spec.name}</p></details>{activeAnalysis?<TimeEvidence key={activeId} analysis={activeAnalysis} initialHours={hours} initialCohort={cohort} onViewChange={changeView}/>:<p role="status">正在讀取行為詳情…</p>}</section>}
    <nav className="v4-downloads" aria-label="下載報告"><button onClick={()=>void exportHtml()} disabled={exporting}>{exporting?'正在準備匯出…':'匯出分析 HTML'}</button><details><summary>完整計算資料與原始報告</summary>{['html','csv','json','discovery'].map(format=><a key={format} href={`/api/runs/${scope.runId}/reports/${scope.version}/${format}`} download>{format==='html'?'原始封存 HTML':format==='discovery'?'完整搜尋 JSON':`完整計算 ${format.toUpperCase()}`}　</a>)}</details></nav>

  </div>;
}
