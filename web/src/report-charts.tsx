import {candidateName,conditionName} from './candidate-language';
import type {Report} from './report-model';
import {ChartRenderer} from './chart-renderer';
import type {Chart,Point} from './chart-model';
import {CandidateValueMap} from './candidate-value-map';

function obj(v:unknown):Record<string,any>{if(!v||typeof v!=='object'||Array.isArray(v))throw new Error('DIAGNOSTIC_SCHEMA_INVALID');return v as Record<string,any>;}
function count(v:unknown):number{if(!Number.isSafeInteger(v)||(v as number)<0)throw new Error('DIAGNOSTIC_SAMPLE_INVALID');return v as number;}
export default function ReportCharts({report,onSelect}:{report:Report;onSelect?:(id:string)=>void}){
  if(report.schema_version==='3.0'&&report.value_map)return <CandidateValueMap report={report} onSelect={onSelect}/>;
  try{return Charts({report});}catch(e){return <div role="alert"><p>目前無法顯示圖表，因為資料未通過完整性檢查。你仍可查看其他報告內容，或重新載入頁面再試。</p><details><summary>錯誤詳細資料</summary>{String(e)}</details></div>;}
}
function Charts({report}:{report:Report}){
  const ids=report.candidates.map(c=>c.candidate_id);
  const names=Object.fromEntries(report.candidates.map(c=>[c.candidate_id,candidateName(c.event_spec)]));
  const make=(type:Chart['chart_type'],source:string,n:number,x:string,y:string,series:Point[]):Chart=>({chart_type:type,artifact_id:source,run_id:report.run_id,x_unit:x,y_unit:y,sample_size:n,evidence_status:'exploratory',series});
  const scatter=report.candidates.filter(c=>c.metrics!==null);
  const groups=new Map<string,typeof scatter>();
  for(const c of scatter){const n=c.metrics!.groups.all.users;const key=String(n);groups.set(key,[...(groups.get(key)||[]),c]);}
  const sensitivity=report.diagnostics?.sensitivity,overlap=report.diagnostics?.overlap;
  const source=(name:string)=>{const sources=obj(report.audit.sources);const entry=obj(sources[name]);if(typeof entry.sha256!=='string')throw new Error('DIAGNOSTIC_SOURCE_MISSING');return `${name}:${entry.sha256}`;};
  const lines:{title:string;chart:Chart}[]=[];
  if(sensitivity){const d=obj(sensitivity);count(d.cohort_users);if(!Array.isArray(d.points)||d.points.length>10000)throw new Error('DIAGNOSTIC_POINTS_INVALID');
    const families=new Map<string,Point[]>();
    for(const raw of d.points){const p=obj(raw);if(p.family===null)continue;const f=obj(p.family);if(p.cohort_id!==d.cohort_id||p.cohort_users!==d.cohort_users)throw new Error('DIAGNOSTIC_COHORT_MISMATCH');
      names[p.candidate_id]??=`${f.window_hours} 小時內，${conditionName({...f,threshold:p.threshold})}`;
      const key=JSON.stringify([f.op,f.ad_format,f.window_hours]);families.set(key,[...(families.get(key)||[]),{candidate_id:p.candidate_id,x:p.threshold,y:p.coverage}]);}
    for(const [family,points] of families){const [op,format,hours]=JSON.parse(family);points.sort((a,b)=>(a.x??Infinity)-(b.x??Infinity));lines.push({title:`提高要求，還有多少人符合？${hours} 小時內・${({count:'廣告次數',revenue_sum:'廣告收益',session_count:'使用次數',engaged_seconds:'使用時間'} as Record<string,string>)[op]||'條件'}・${({rewarded:'獎勵式',interstitial:'插頁式',banner:'橫幅',app_open:'開屏',native:'原生',other:'其他',unknown:'未分類'} as Record<string,string>)[format]||'所有類型'}`,chart:make('line',source('sensitivity'),d.cohort_users,op==='revenue_sum'?'USD':op==='engaged_seconds'?'hours':'count','percent',points.map(p=>op==='engaged_seconds'?{...p,x:p.x===null?null:p.x/3600}:p))});}
  }
  let heat:Chart|null=null,heatIds:string[]=[];
  if(overlap){const d=obj(overlap);count(d.cohort_users);if(!Array.isArray(d.comparison_ids)||d.comparison_ids.length>10||!d.comparison_ids.every((x:unknown)=>typeof x==='string')||!Array.isArray(d.pairs)||d.pairs.length>55)throw new Error('OVERLAP_SCHEMA_INVALID');heatIds=d.comparison_ids;
    const points:Point[]=[];for(const raw of d.pairs){const p=obj(raw);const x=heatIds.indexOf(p.a),y=heatIds.indexOf(p.b);if(x<0||y<0)throw new Error('OVERLAP_CANDIDATE_INVALID');points.push({candidate_id:p.a,x,y,value:p.jaccard});if(x!==y)points.push({candidate_id:p.b,x:y,y:x,value:p.jaccard});}
    heat=make('heatmap',source('overlap'),d.cohort_users,'candidate','candidate',points);
  }
  return <><p>第一張圖使用留出來檢查結果的用戶，條件調整與人群重疊使用各自的分析人群。請注意每張圖的人數，不要混合比較。過去收益差異不是投放效果。</p>
    {[...groups].map(([n,rows])=><ChartRenderer key={n} input={make('scatter',source('validation'),count(Number(n)),'percent','USD',rows.map(c=>({candidate_id:c.candidate_id,x:c.metrics!.coverage,y:c.metrics!.groups.triggered.arpu_usd})))} runId={report.run_id} title="哪些條件能兼顧人數與收益？" ids={ids} names={names}/>)}
    {!scatter.length&&<p>目前沒有足夠的比較數值可繪圖，請查看資料限制。</p>}
    {lines.map(item=><ChartRenderer key={item.title} input={item.chart} runId={report.run_id} title={item.title} ids={ids} names={names}/>)}
    {!lines.length&&<p>目前沒有可比較的單一條件調整結果。</p>}
    {heat?<><ChartRenderer input={heat} runId={report.run_id} title="不同條件選中的是同一批人嗎？" ids={ids} names={names} labels={heatIds.map((_,i)=>`C${i+1}`)}/><details><summary>重疊圖 C 編號與候選對照</summary>{heatIds.map((id,i)=><p className="dataset-identity" key={id}>C{i+1}：{names[id]||'其他事件條件'}</p>)}</details></>:<p>未產生人群重疊資料。</p>}
  </>;
}
