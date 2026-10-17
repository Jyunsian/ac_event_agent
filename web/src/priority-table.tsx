import type {Candidate} from './report-model';
import {candidateName} from './candidate-language';
import {displayNumber} from './report-language';

const number=(v:unknown,unit='')=>typeof v==='number'?<span title={`原始值：${v}`} data-value={v}>{displayNumber(v,unit)}</span>:'此版本未計算';
export function PriorityTable({rows,onSelect}:{rows:Candidate[];onSelect:(id:string)=>void}){
  return <div className="data-table" tabIndex={0} role="region" aria-label="優先候選完整比較"><table><thead><tr>
    <th>玩家行為條件</th><th>符合／未符合／無法判定</th><th>可判定者符合比例</th><th>符合者 7 天平均收益</th><th>未符合者 7 天平均收益</th><th>符合者平均多賺</th><th>一半人／九成人達標時間</th>
  </tr></thead><tbody>{rows.map(row=>{
    const comparison=row.metrics?.comparisons as Record<string,unknown>|undefined;
    return <tr key={row.candidate_id} data-candidate-id={row.candidate_id}>
      <td><button className="text-button" onClick={()=>onSelect(row.candidate_id)}>{candidateName(row.event_spec)}</button></td>
      <td>{number(row.metrics?.groups.triggered.users)}／{number(row.metrics?.groups.untriggered.users)}／{number(row.metrics?.groups.unknown?.users??0)}</td>
      <td>{number(row.metrics?.coverage,'%')}</td><td>{number(row.metrics?.groups.triggered.arpu_usd,'USD')}</td>
      <td>{number(row.metrics?.groups.untriggered.arpu_usd,'USD')}</td><td>{number(comparison?.triggered_minus_untriggered,'USD')}</td>
      <td>{number(row.metrics?.delay_seconds.median,'h')}／{number(row.metrics?.delay_seconds.p90,'h')}</td>
    </tr>;
  })}</tbody></table><p className="table-note">三組人數加總為完整觀察的玩家。缺少判定所需行為紀錄的玩家列為「無法判定」，不會硬算成未符合。</p></div>;
}
