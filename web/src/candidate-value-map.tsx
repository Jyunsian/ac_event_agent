import {useMemo,useState} from 'react';
import type {Report,ValuePoint} from './report-model';
import {displayNumber} from './report-language';

const categories=['iaa','session_retention','level_progress','level_friction','cross_category','sequence'];
const label:Record<string,string>={iaa:'IAA',session_retention:'Session／Retention',level_progress:'Level Progress',level_friction:'Level Friction',cross_category:'Cross-category',sequence:'Sequence'};
function extent(values:number[]){return [Math.min(0,...values),Math.max(0,...values)] as const;}
function scale(value:number,[low,high]:readonly number[],start:number,size:number){return start+(value-low)/(high-low||1)*size;}
function money(value:number|null){return value===null?'未知':displayNumber(value,'USD');}
export function CandidateValueMap({report,onSelect}:{report:Report;onSelect?:(id:string)=>void}){
  const map=report.value_map!;const [category,setCategory]=useState('all');const [active,setActive]=useState<string|null>(null);
  const points=useMemo(()=>map.points.filter(point=>category==='all'||point.category===category),[map.points,category]);
  const plotted=points.filter((point):point is ValuePoint&{x_early_72h_difference_usd:number;y_remaining_72_168h_difference_usd:number}=>point.chart_status==='PLOTTED'&&point.x_early_72h_difference_usd!==null&&point.y_remaining_72_168h_difference_usd!==null);
  const x=extent(plotted.map(point=>point.x_early_72h_difference_usd)),y=extent(plotted.map(point=>point.y_remaining_72_168h_difference_usd));
  const choose=(id:string)=>{setActive(id);onSelect?.(id);};
  return <section className="value-map" aria-label="72 小時候選價值圖"><h3>72 小時候選價值圖</h3><p>X 比較前 72 小時，Y 比較 72 至 168 小時。只有在 72 小時前完整可判定的候選會畫點；點的顏色與大小不代表額外數值。</p>
    <label>Category <select value={category} onChange={event=>setCategory(event.target.value)}><option value="all">全部</option>{categories.filter(item=>map.points.some(point=>point.category===item)).map(item=><option value={item} key={item}>{label[item]}</option>)}</select></label>
    <p aria-live="polite">可繪製 {plotted.length} / 全部 {points.length}。晚期或數值未知的候選仍保留在下方表格。</p>
    {plotted.length?<svg viewBox="0 0 800 420" role="img" aria-label="候選在前 72 小時與剩餘 D7 收益差的散點圖"><line x1="50" y1="370" x2="760" y2="370"/><line x1="50" y1="30" x2="50" y2="370"/>{plotted.map(point=>{
      const cx=scale(point.x_early_72h_difference_usd!,x,50,710),cy=370-scale(point.y_remaining_72_168h_difference_usd!,y,0,340);
      return <circle key={point.candidate_id} cx={cx} cy={cy} r="7" tabIndex={0} role="button" aria-label={`${label[point.category]}，前 72 小時差 ${point.x_early_72h_difference_usd}，剩餘差 ${point.y_remaining_72_168h_difference_usd}`} onClick={()=>choose(point.candidate_id)} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();choose(point.candidate_id);}}}><title>{point.candidate_id} | X {point.x_early_72h_difference_usd} | Y {point.y_remaining_72_168h_difference_usd}</title></circle>;})}</svg>:<p>這個篩選條件目前沒有可繪製數值。</p>}
    {active&&<p role="status">已選取候選 {active.slice(0,12)}，完整證據顯示於候選證據卡。</p>}
    <details open><summary>查看可及性數據表</summary><div className="data-table value-map-table" tabIndex={0} role="region" aria-label="72 小時候選價值數據表"><table><thead><tr><th>候選</th><th>Category</th><th>0 至 72 小時差</th><th>72 至 168 小時差</th><th>符合／未符合／未知</th><th>圖表狀態</th></tr></thead><tbody>{points.map(point=><tr key={point.candidate_id}><td data-label="候選"><button className="text-button" onClick={()=>choose(point.candidate_id)}>{point.candidate_id.slice(0,12)}</button></td><td data-label="Category">{label[point.category]||point.category}</td><td data-label="0 至 72 小時差">{money(point.x_early_72h_difference_usd)}</td><td data-label="72 至 168 小時差">{money(point.y_remaining_72_168h_difference_usd)}</td><td data-label="符合／未符合／未知">{point.triggered_users}／{point.untriggered_users}／{point.unknown_users}</td><td data-label="圖表狀態">{point.chart_status}</td></tr>)}</tbody></table></div></details>
  </section>;
}
