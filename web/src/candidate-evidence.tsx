import {useEffect,useState} from 'react';
import {fetchCandidateDetail,type CandidateDetail,type CandidateScope} from './candidate-client';
import {candidateName,evidenceLabel} from './candidate-language';
import {displayNumber,reasonsText} from './report-language';
const obj=(value:unknown):Record<string,any>=>value&&typeof value==='object'&&!Array.isArray(value)?value as Record<string,any>:{};
const num=(value:unknown,unit='')=>typeof value==='number'&&Number.isFinite(value)?displayNumber(value,unit):'未知';
function Raw({title,data}:{title:string;data:unknown}){return <details className="evidence-details"><summary>{title}</summary><pre>{JSON.stringify(data,null,2)}</pre></details>;}
export function CandidateEvidence({scope,id,datasetId,onSelect}:{scope:CandidateScope;id:string;datasetId:string;onSelect?:(id:string)=>void}){
  const [saved,setSaved]=useState<{key:string;detail:CandidateDetail}|null>(null),[error,setError]=useState(false),[retry,setRetry]=useState(0);
  const key=JSON.stringify([scope,id,datasetId]);
  useEffect(()=>{const controller=new AbortController();let current=true;setError(false);
    fetchCandidateDetail(scope,id,datasetId,controller.signal).then(detail=>{if(current)setSaved({key,detail});}).catch(()=>{if(current)setError(true);});
    return ()=>{current=false;controller.abort();};
  },[key,retry]);
  if(error)return <p role="alert">證據讀取失敗，未顯示其他候選的資料。<button onClick={()=>setRetry(n=>n+1)}>重試</button></p>;
  if(saved?.key!==key)return <p role="status">正在核對此候選的證據…</p>;
  if(saved.detail.schema_version==='3.0')return <CandidateEvidenceV3 detail={saved.detail}/>;
  const d=saved.detail,m=obj(d.validation.metrics),groups=obj(m.groups),delay=obj(m.delay_seconds),comparisons=obj(m.comparisons);
  const revenue=obj(d.revenue_decomposition),inference=obj(d.validation.inference),days=Array.isArray(m.days)?m.days:[];
  return <section aria-label="完整候選證據" data-selected-candidate={id}>
    <h3>{candidateName(d.event_spec)}</h3><p>{evidenceLabel[d.validation.evidence_status]??'結果待確認'}。{reasonsText(d.validation.reasons)}</p>
    <p>從設定的安裝／首次開啟起點累積，只在前 {d.event_spec.window_hours} 小時內首次達標一次，不是七天內任意連續窗口。</p>
    <h4>覆蓋與達標速度</h4><p>符合比例 {num(m.coverage,'%')}；一半符合者在 {num(delay.median,'h')} 達標，九成符合者在 {num(delay.p90,'h')} 達標。</p>
    <h4>完整 D7 收益</h4><div className="data-table"><table><thead><tr><th>人群</th><th>人數</th><th>D7 平均廣告收益</th><th>收益未知人數</th></tr></thead><tbody>{(['all','triggered','untriggered'] as const).map(k=><tr key={k}><td>{{all:'全部比較用戶',triggered:'符合',untriggered:'未符合'}[k]}</td><td>{num(obj(groups[k]).users)}</td><td>{num(obj(groups[k]).arpu_usd,'USD')}</td><td>{num(obj(groups[k]).unknown_revenue_users)}</td></tr>)}</tbody></table></div>
    <p>符合者減未符合者的 D7 平均收益差：{num(comparisons.triggered_minus_untriggered,'USD')}。</p>
    <p>95% Bootstrap 描述區間：{num(obj(obj(obj(m.bootstrap).intervals).triggered_minus_untriggered).lower,'USD')} 至 {num(obj(obj(obj(m.bootstrap).intervals).triggered_minus_untriggered).upper,'USD')}。這是描述區間，不等於全家族檢驗通過。</p>
    <h4>窗口前後的收益</h4><p>仍以完整 D7 作主要比較。晚期候選剩餘時間較短，不因此淘汰，也不跨不同剩餘時長排名。</p>
    {d.revenue_decomposition===null?<p>此候選無法計算收益分解。</p>:<div className="data-table"><table><thead><tr><th>期間</th><th>符合 ARPU</th><th>未符合 ARPU</th><th>差額</th></tr></thead><tbody>{(['before','remaining','d7'] as const).map(k=><tr key={k}><td>{{before:`起點至前 ${d.event_spec.window_hours} 小時`,remaining:`${d.event_spec.window_hours} 至 168 小時`,d7:'完整 D7'}[k]}</td><td>{num(obj(obj(obj(revenue.groups).triggered)[k]).arpu_usd,'USD')}</td><td>{num(obj(obj(obj(revenue.groups).untriggered)[k]).arpu_usd,'USD')}</td><td>{num(obj(obj(revenue.comparisons)[k]).difference_usd,'USD')}</td></tr>)}</tbody></table></div>}
    <h4>探索與驗證</h4><p>探索集收益差：{num(d.exploration.difference_usd,'USD')}；驗證集收益差：{num(comparisons.triggered_minus_untriggered,'USD')}。優先名單不依驗證結果補選。</p>
    <p>比較角色：{typeof d.selection.role==='string'?d.selection.role:'非優先項'}；相似人群比例：{num(d.selection.jaccard,'%')}。</p>
    {typeof d.selection.similar_priority_id==='string'&&<p>相似優先條件：{onSelect?<button onClick={()=>onSelect(d.selection.similar_priority_id as string)}>查看這個相似候選的完整證據</button>:d.selection.similar_priority_id}。相似度來自探索用戶，不代表兩條件邏輯等價。</p>}
    <p>{reasonsText(Array.isArray(d.selection.reasons)?d.selection.reasons:[])}</p>
    <p>凍結家族 {num(inference.family_size)} 項；單尾 Welch p 值 {num(inference.p_value)}；Holm 校正後 p 值 {num(inference.adjusted_p_value)}。校正檢查：{inference.passed===true?'通過':inference.passed===false?'未通過':'未知'}，仍須同時符合樣本與品質等門檻。</p>
    <Raw title="統計檢驗與全家族 Holm 校正" data={inference}/><Raw title="Bootstrap 描述區間與完整驗證指標" data={m}/>
    <h4>安裝日觀察量</h4><p>這是資料中的安裝批次，不是廣告平台接收量或學習量保證。</p>
    {days.length?<div className="data-table"><table><thead><tr><th>安裝日</th><th>用戶</th><th>符合</th><th>覆蓋</th></tr></thead><tbody>{days.map((day:unknown,i:number)=>{const r=obj(day);return <tr key={i}><td>{String(r.install_day??'未知')}</td><td>{num(r.users)}</td><td>{num(r.triggered_users)}</td><td>{num(r.coverage,'%')}</td></tr>;})}</tbody></table></div>:<p>此版本／候選未提供逐日比較。</p>}
    <h4>來源內比較</h4><p>任一組少於 20 人會隱藏收益比較。來源差異僅輔助診斷，不表示已排除混雜。</p>
    {d.source_diagnostics===null?<p>無法計算來源比較。</p>:<div className="data-table"><table><thead><tr><th>來源</th><th>符合／未符合</th><th>符合 ARPU</th><th>未符合 ARPU</th><th>差額</th><th>限制</th></tr></thead><tbody>{d.source_diagnostics.map((r,i)=><tr key={i}><td>{String(r.acquisition_source??'unknown')}</td><td>{num(r.triggered_users)}／{num(r.untriggered_users)}</td><td>{num(r.triggered_arpu_usd,'USD')}</td><td>{num(r.untriggered_arpu_usd,'USD')}</td><td>{num(r.difference_usd,'USD')}</td><td>{reasonsText(Array.isArray(r.reasons)?r.reasons:[])}</td></tr>)}</tbody></table></div>}
    <h4>同一時間點之後，還有多少收益？</h4>
    <p>在共同的 24／72／144 小時切點，依當時是否已首次達標重新分組，再比較切點到 D7 的同一段剩餘收益。這與每位用戶各自觸發後的收益不同。</p>
    {Array.isArray(d.validation.landmarks)&&d.validation.landmarks.length>0?<div className="data-table"><table><thead><tr><th>切點</th><th>已達標／未達標人數</th><th>已達標剩餘 ARPU</th><th>未達標剩餘 ARPU</th><th>剩餘差額</th></tr></thead><tbody>{d.validation.landmarks.map((item:unknown,index:number)=>{
      const point=obj(item),g=obj(point.groups),hit=obj(g.triggered),miss=obj(g.untriggered);
      return <tr key={index}><td>起點後 {num(point.window_hours)} 小時</td><td>{num(hit.users)}／{num(miss.users)}</td><td>{num(obj(hit.remaining).arpu_usd,'USD')}</td><td>{num(obj(miss.remaining).arpu_usd,'USD')}</td><td>{num(obj(obj(point.comparisons).remaining).difference_usd,'USD')}</td></tr>;
    })}</tbody></table></div>:<p>此候選未計算共同時間點比較；本版只為優先候選提供，不能視為剩餘收益為零。</p>}
    <Raw title="共同時間點原始證據" data={d.validation.landmarks??null}/><Raw title="收益分解原始證據" data={d.revenue_decomposition}/><Raw title="給工程師的事件定義與來源" data={d}/>
    <p>這些結果是離線歷史關聯，不是投放實驗，也不是 ROI 保證。</p>
  </section>;
}

function CandidateEvidenceV3({detail:d}:{detail:CandidateDetail}){
  const validation=obj(d.validation),metrics=obj(validation.metrics),groups=obj(metrics.groups),delay=obj(metrics.delay_seconds),comparisons=obj(metrics.comparisons),candidate=obj((d as unknown as Record<string,unknown>).candidate);
  const hit=obj(groups.triggered),miss=obj(groups.untriggered),unknown=obj(groups.unknown);
  return <section className="candidate-detail" aria-label="完整候選證據" data-selected-candidate={d.candidate_id}>
    <h2>{candidateName(d.event_spec)}</h2>
    <p className="candidate-detail-lead">在完整觀察 7 天的玩家中，比較符合與未符合這個行為的人。</p>
    <div className="candidate-detail-metrics"><div><span>符合玩家</span><strong>{num(hit.users)}</strong><small>{num(metrics.coverage,'%')} 的玩家</small></div><div><span>平均多賺</span><strong>{num(comparisons.triggered_minus_untriggered,'USD')}</strong><small>7 天平均收益差</small></div><div><span>達標時間</span><strong>{num(delay.median,'h')}</strong><small>一半人達標，九成人為 {num(delay.p90,'h')}</small></div></div>
    <h3>收益比較</h3><div className="candidate-compare"><div><span>符合的玩家</span><strong>{num(hit.arpu_usd,'USD')}</strong><small>{num(hit.users)} 人</small></div><div><span>未符合的玩家</span><strong>{num(miss.arpu_usd,'USD')}</strong><small>{num(miss.users)} 人</small></div></div>
    <h3>事件怎麼觸發</h3><p>從安裝後第 {num(d.event_spec.observation_start_hours)} 小時開始觀察，到第 {num(d.event_spec.observation_end_hours)} 小時截止。{d.event_spec.trigger_mode==='checkpoint_snapshot'?'在截止時間判斷是否符合。':'玩家第一次達標時回傳一次。'}</p>
    {Number(unknown.users)>0&&<p className="muted">另有 {num(unknown.users)} 位玩家無法判定。</p>}
    <details className="advanced-evidence"><summary>資料可信度</summary><div>
      <p>另一組玩家中，符合 {num(obj(validation.membership).triggered_users)} 人，未符合 {num(obj(validation.membership).untriggered_users)} 人。{evidenceLabel[String(validation.evidence_status)]??'結果待確認'}。</p>
      <p>{reasonsText(Array.isArray(validation.reasons)?validation.reasons:[])}</p>
    </div></details>
    <details className="advanced-evidence"><summary>計算與資料來源</summary><div><Raw title="候選條件與判定規則" data={candidate}/><Raw title="完整計算資料" data={d}/></div></details>
  </section>;
}
