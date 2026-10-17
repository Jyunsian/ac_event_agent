import {useEffect,useState} from 'react';
import {fetchCandidateSearch,type CandidateScope,type CandidateSearch} from './candidate-client';
import {conditionName} from './candidate-language';
export function CandidateSearchRecord({scope}:{scope:CandidateScope}){
  const [page,setPage]=useState(1),[result,setResult]=useState<CandidateSearch|null>(null),[error,setError]=useState(false),[retry,setRetry]=useState(0);
  const key=JSON.stringify(scope);
  useEffect(()=>{const controller=new AbortController();let current=true;setResult(null);setError(false);
    fetchCandidateSearch(scope,page,controller.signal).then(value=>{if(current)setResult(value);}).catch(()=>{if(current)setError(true);});
    return ()=>{current=false;controller.abort();};},[key,page,retry]);
  if(error)return <p role="alert">搜尋紀錄讀取失敗。<button onClick={()=>setRetry(n=>n+1)}>重試</button></p>;
  if(!result)return <p role="status">正在核對搜尋紀錄…</p>;
  const s=result.summary,v4=s.analysis_version==='4.0-time-aware',show=(v:unknown)=>typeof v==='number'?v:'此版本未計算';
  return <section aria-label="搜尋範圍與紀錄"><h3>本次搜尋的邊界</h3>
    <p>{v4?'在已支援的累積、指定時間與連續 24 小時規則內分析。':'只在已設定的固定起點窗口內評估。'}預算外條件是「未評估」，不是被資料否定。</p>
    <dl className="facts"><div><dt>生成條件</dt><dd>{show(s.enumerated)}</dd></div><div><dt>合併後、預算截取前</dt><dd>{show(s.unique_before_cap)}</dd></div><div><dt>實際評估</dt><dd>{show(s.discovery_count??s.selected_count)}</dd></div><div><dt>合併／排除紀錄</dt><dd>{result.pruning_count}</dd></div></dl>
    <p>窗口：{v4?'24、48、72、96、120、144':Array.isArray(s.searched_windows)?s.searched_windows.join('、'):'此版本未計算'} 小時。累積規則從資料定義起點開始；滾動規則只看之前連續 24 小時。</p>
    <details><summary>搜尋配額、收入／頻次門檻與組合父條件</summary><pre>{JSON.stringify(s,null,2)}</pre></details>
    <h4>逐條合併與排除紀錄</h4>{result.items.length===0?<p>此頁沒有紀錄。</p>:<div className="data-table"><table><thead><tr><th>條件</th><th>處理原因</th><th>是否評估</th><th>追溯資料</th></tr></thead><tbody>{result.items.map((row,index)=><tr key={index}>
      <td>{row.candidate?.predicate?`起點後前 ${row.candidate.window_hours} 小時，${conditionName(row.candidate.predicate)}`:'同等條件／組合父條件（見追溯資料）'}</td>
      <td>{({DISCOVERY_BUDGET_NOT_EVALUATED:'超出搜尋預算，尚未評估',FULL_TIME_BUNDLE_OUTSIDE_VALIDATION_BUDGET:'已作探索，完整時間比較超出驗證預算',MAX_CANDIDATES_LIMIT:'超出本次搜尋預算',EQUIVALENT_PREDICATE:'邏輯等價，合併重複條件',DIFFERENT_WINDOWS_NOT_COMPOSABLE:'不同窗口，不組合'} as Record<string,string>)[row.reason]??'其他處理原因'}</td>
      <td>{row.evaluation_status==='not_evaluated'?'未評估，不代表不支持':row.evaluation_status==='exploration_only'?'已作描述分析，未完整驗證':'合併／排除紀錄，不是驗證結果'}</td>
      <td><details><summary>查看條件識別與原始紀錄</summary><pre>{JSON.stringify(row,null,2)}</pre></details></td>
    </tr>)}</tbody></table></div>}
    <nav className="report-controls" aria-label="搜尋紀錄分頁"><button disabled={page<=1} onClick={()=>setPage(n=>n-1)}>上一頁</button><span>第 {page} 頁，每頁 50 項</span><button disabled={page*50>=result.pruning_count} onClick={()=>setPage(n=>n+1)}>下一頁</button></nav>
  </section>;
}
