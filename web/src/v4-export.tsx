/** Presentation export built from the same immutable aggregate report as the Web. */
import {renderToStaticMarkup} from 'react-dom/server';
import type {Report} from './report-model';
import type {CandidateScope} from './candidate-client';
import {OverviewCards,DecisionRow,TimeEvidence,cohorts,checkpoints} from './report-v4';
import {displayRuleName} from './v4-presentation';
import styles from './v4-report.css?inline';

export function renderV4Html(report:Report,scope:CandidateScope):string {
  const content=renderToStaticMarkup(<main className="v4-report"><h1>行為分析</h1><p>{report.synthetic?'合成資料 · ':''}D7 累積廣告收入</p><p>優先比較 {report.candidates.length} 個行為 · 全量／找規律／Holdout · 六個觀察時間點</p><small>Run {scope.runId} · 報告版本 {scope.version}</small><OverviewCards report={report}/>
    {Object.entries(cohorts).map(([cohort,label])=><section key={cohort}><h2>{label}</h2>{checkpoints.map(hours=><details key={hours} open={hours===24}><summary>{hours} 小時 · 行為比較</summary><div className="data-table v4-decision-table"><table><thead><tr>{['行為條件','七天平均收入／人','辨識規模','達標時間','Holdout 驗證'].map(t=><th key={t}>{t}</th>)}</tr></thead><tbody>{report.candidates.map(row=><DecisionRow key={row.candidate_id} row={row} hours={hours} cohort={cohort}/>)}</tbody></table></div></details>)}</section>)}
    <h2>觀察時間與每天新增玩家</h2>{report.candidates.map((row:any)=><details key={row.candidate_id}><summary title={row.event_spec.name}>{displayRuleName(row.event_spec.name)}</summary><details><summary>精確條件</summary><p>{row.event_spec.name}</p></details>{Object.entries(cohorts).map(([cohort,label])=><section key={cohort}><h3>{label}</h3><TimeEvidence interactive={false} initialCohort={cohort} analysis={{...row.time_analysis,rule:{mode:row.event_spec.mode},origin:row.event_spec.origin,evidence_status:row.evidence_status}}/></section>)}</details>)}
    <p>本檔為優先比較行為的閱讀版；所有完整比較與搜尋紀錄保留於 CSV／JSON。結果為收入關聯，不代表投放提升。</p></main>);
  return '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>V4 行為分析</title><style>body{--panel:#fff;--raised:#edf0f5;--text:#252b34;--muted:#626b78;--line:#e0e4eb;--accent:#5368a7;font:14px/1.6 system-ui;color:var(--text);background:#f6f7f9;margin:0;padding:24px}main{max-width:1200px;margin:auto}*{box-sizing:border-box}table{width:100%;border-collapse:collapse;white-space:nowrap}td,th{padding:12px;border-bottom:1px solid var(--line);text-align:left}small{color:var(--muted)}.data-table{overflow:auto;max-width:100%}section,details{margin:24px 0}summary{cursor:pointer;font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere}'+styles+'</style></head><body>'+content+'</body></html>';
}
export async function downloadV4Html(report:Report,scope:CandidateScope){
  const url=URL.createObjectURL(new Blob([renderV4Html(report,scope)],{type:'text/html;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download=`V4-analysis-${scope.runId}-v${scope.version}.html`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
