import {useEffect,useState} from 'react';
import {fetchRevenueGroups,type CandidateScope,type RevenueGroup} from './candidate-client';
import {displayNumber} from './report-language';

export function CandidateRevenue({scope,onSelect}:{scope:CandidateScope;onSelect:(id:string)=>void}){
  const key=JSON.stringify(scope),[loaded,setLoaded]=useState(''),[groups,setGroups]=useState<RevenueGroup[]>([]);
  const [index,setIndex]=useState(0),[error,setError]=useState(false),[retry,setRetry]=useState(0);
  useEffect(()=>{const controller=new AbortController();let active=true;setError(false);
    fetchRevenueGroups(scope,controller.signal).then(rows=>{if(active){setGroups(rows);setLoaded(key);setIndex(0);}}).catch(()=>{if(active)setError(true);});
    return()=>{active=false;controller.abort();};},[key,retry]);
  const group=loaded===key?groups[index]:undefined;
  return <section aria-label="累積收入門檻比較"><h3>累積收入門檻的取捨</h3>
    <p>只比較同一固定起點窗口、同一廣告格式。兩圖橫軸相同；缺值不補零、不跨缺值連線。點選圓點或表格條件查看證據，歷史差額不代表投放 ROI。</p>
    {error?<p role="alert">收入門檻資料讀取失敗。<button onClick={()=>setRetry(n=>n+1)}>重試</button></p>:loaded!==key?<p role="status">讀取收入門檻…</p>:groups.length===0?<p>本報告沒有已評估的單一累積收入條件。</p>:<>
      <label>比較範圍<select value={index} onChange={e=>setIndex(Number(e.target.value))}>{groups.map((g,i)=><option key={`${g.window_hours}:${g.ad_format}`} value={i}>安裝／首次開啟後前 {g.window_hours} 小時 · {g.ad_format}</option>)}</select></label>
      {group&&<><RevenuePlot group={group} metric="coverage" onSelect={onSelect}/><RevenuePlot group={group} metric="difference_usd" onSelect={onSelect}/>
        <details><summary>全部圖點與精確值（含缺值）</summary><div className="data-table" tabIndex={0}><table><thead><tr><th>收入門檻 USD</th><th>覆蓋率</th><th>D7 差額 USD</th><th>比較用戶數</th></tr></thead><tbody>{group.points.map(p=><tr key={p.candidate_id}><td><button onClick={()=>onSelect(p.candidate_id)}>{String(p.threshold_usd)}</button></td><td>{p.coverage===null?'未知':String(p.coverage)}</td><td>{p.difference_usd===null?'未知':String(p.difference_usd)}</td><td>{p.sample_size??'未知'}</td></tr>)}</tbody></table></div></details></>}
    </>}
  </section>;
}

function RevenuePlot({group,metric,onSelect}:{group:RevenueGroup;metric:'coverage'|'difference_usd';onSelect:(id:string)=>void}){
  const title=metric==='coverage'?'覆蓋率（%）':'符合者 − 未符合者 D7 ARPU（USD）';
  const points=group.points,known=points.filter(p=>p[metric]!==null),xs=points.map(p=>p.threshold_usd);
  const xmin=Math.min(...xs),xmax=Math.max(...xs),values=known.map(p=>p[metric]!);
  const ymin=metric==='coverage'?0:Math.min(0,...values),ymax=metric==='coverage'?1:Math.max(0,...values);
  const x=(n:number)=>70+(xmax===xmin?.5:(n-xmin)/(xmax-xmin))*500;
  const y=(n:number)=>210-(ymax===ymin?.5:(n-ymin)/(ymax-ymin))*160;
  const label=(n:number)=>displayNumber(n,metric==='coverage'?'%':'USD');
  return <section><h4>{title}</h4>{known.length===0?<p>此範圍沒有可繪製的完整數值。</p>:<svg data-metric={metric} data-x-min={xmin} data-x-max={xmax} viewBox="0 0 640 270" style={{width:'100%',minHeight:180}} role="group" aria-label={title}>
    {[ymin,(ymin+ymax)/2,ymax].map((v,i)=><g key={i}><line x1="70" x2="570" y1={y(v)} y2={y(v)} stroke="var(--line)"/><text x="65" y={y(v)+4} textAnchor="end" fill="currentColor" fontSize="10">{label(v)}</text></g>)}
    {points.map((p,i)=>{const prev=points[i-1];return p[metric]!==null&&prev?.[metric]!=null?<line key={`line-${p.candidate_id}`} x1={x(prev.threshold_usd)} y1={y(prev[metric]!)} x2={x(p.threshold_usd)} y2={y(p[metric]!)} stroke="var(--accent)"/>:null;})}
    {known.map(p=><circle key={p.candidate_id} cx={x(p.threshold_usd)} cy={y(p[metric]!)} r="5" fill="var(--accent)" tabIndex={0} role="button" aria-label={`收入門檻 ${p.threshold_usd} USD，${title} ${label(p[metric]!)}，查看證據`} onClick={()=>onSelect(p.candidate_id)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect(p.candidate_id);}}}><title>{p.threshold_usd} USD · {label(p[metric]!)} · 分母 {p.sample_size??'未知'} 人</title></circle>)}
    <text x="70" y="235" fill="currentColor" fontSize="11">{xmin} USD</text><text x="570" y="235" textAnchor="end" fill="currentColor" fontSize="11">{xmax} USD</text><text x="320" y="260" textAnchor="middle" fill="currentColor" fontSize="12">累積廣告收入門檻（USD）</text>
  </svg>}</section>;
}
