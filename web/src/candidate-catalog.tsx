import {useEffect,useState} from 'react';
import {fetchCandidatePage,candidateExportUrl,type CandidatePage,type CandidateQuery,type CandidateScope} from './candidate-client';
import {candidateName} from './candidate-language';
import {displayNumber} from './report-language';
import './candidate-catalog.css';
import {CandidateRevenue} from './candidate-revenue';

const windows=[1,3,6,12,24,48,72,96,120,144,168];
const number=(v:number|null|undefined,unit='')=>v==null?'未知':displayNumber(v,unit);
export function CandidateCatalog({scope,onSelect}:{scope:CandidateScope;onSelect:(id:string)=>void}){
  const [query,setQuery]=useState<CandidateQuery>({page:1});
  const [saved,setSaved]=useState<CandidatePage|null>(null),[error,setError]=useState(false),[loading,setLoading]=useState(false);
  const [retry,setRetry]=useState(0);
  const key=JSON.stringify([scope,query]);
  const [loadedKey,setLoadedKey]=useState('');
  useEffect(()=>{
    const controller=new AbortController();let current=true;setLoading(true);setError(false);
    fetchCandidatePage(scope,query,controller.signal).then(result=>{if(current){setSaved(result);setLoadedKey(key);}})
      .catch(()=>{if(current)setError(true);}).finally(()=>{if(current)setLoading(false);});
    return ()=>{current=false;controller.abort();};
  },[key,retry]);
  const result=loadedKey===key?saved:null;
  const change=(patch:Partial<CandidateQuery>)=>setQuery(previous=>({...previous,...patch,page:1}));
  return <section aria-label="全部候選結果" className="candidate-catalog">
    <div className="catalog-filters">
      <label>起點後窗口<select value={query.window_hours??''} onChange={e=>change({window_hours:e.target.value?Number(e.target.value):undefined})}><option value="">全部窗口</option>{windows.map(w=><option key={w} value={w}>前 {w} 小時</option>)}</select></label>
      <label>條件類型<select value={query.family??''} onChange={e=>change({family:(e.target.value||undefined) as CandidateQuery['family']})}><option value="">全部類型</option><option value="atom">單一條件</option><option value="compound">且／或組合</option><option value="sequence">先後序列</option></select></label>
      <label>廣告格式<select value={query.ad_format??''} onChange={e=>change({ad_format:e.target.value||undefined})}><option value="">全部格式</option><option value="rewarded">獎勵式廣告</option><option value="interstitial">插頁式廣告</option><option value="banner">橫幅廣告</option><option value="app_open">開屏廣告</option><option value="native">原生廣告</option><option value="other">其他格式</option><option value="unknown">未分類格式</option></select></label>
      <label>排序<select value={query.sort??'candidate_id'} onChange={e=>change({sort:e.target.value as CandidateQuery['sort'],descending:['difference_usd','coverage'].includes(e.target.value)})}><option value="candidate_id">固定順序</option><option value="difference_usd">平均多賺多少：高到低</option><option value="coverage">符合比例：高到低</option><option value="p90_seconds">大多數人達標時間：快到慢</option></select></label>
    </div>
    {loading&&<p role="status">正在讀取候選清單…</p>}
    {error&&<p role="alert">候選清單讀取失敗，沒有重新計算。<button onClick={()=>setRetry(n=>n+1)}>重試讀取</button></p>}
    {result&&<><p aria-live="polite">本次評估 {result.evaluated_count} 項；符合篩選 {result.filtered_count} 項。</p>
      {result.items.length===0?<p>沒有符合此篩選的結果。這不代表未評估條件已被否定。</p>:<div className="data-table" tabIndex={0} role="region" aria-label="完整候選比較表"><table><thead><tr>
        <th>玩家行為條件</th><th>符合／未符合／無法判定</th><th>可判定者符合比例</th><th>符合者 7 天平均收益</th><th>未符合者 7 天平均收益</th><th>符合者平均多賺</th><th>一半人／九成人達標時間</th>
      </tr></thead><tbody>{result.items.map(row=>{const hit=row.summary?.triggered_users,miss=row.summary?.untriggered_users,unknown=hit!=null&&miss!=null?result.comparison_users-hit-miss:null;return <tr key={row.candidate_id} data-candidate-id={row.candidate_id}>
        <td><button className="text-button" onClick={()=>onSelect(row.candidate_id)}>{row.summary?candidateName(row.summary.event_spec):'此版本未計算完整條件名稱'}</button></td>
        <td>{number(hit)}／{number(miss)}／{number(unknown)}</td><td>{number(row.summary?.coverage,'%')}</td>
        <td>{number(row.summary?.triggered_arpu_usd,'USD')}</td><td>{number(row.summary?.untriggered_arpu_usd,'USD')}</td><td>{number(row.summary?.difference_usd,'USD')}</td>
        <td>{number(row.summary?.median_seconds,'h')}／{number(row.summary?.p90_seconds,'h')}</td>
      </tr>})}</tbody></table><p className="table-note">三組人數加總為 {number(result.comparison_users)} 位完整觀察玩家。缺少判定所需行為紀錄的玩家列為「無法判定」，不會硬算成未符合。</p></div>}
      <nav aria-label="候選結果分頁" className="report-controls"><button disabled={result.page<=1} onClick={()=>setQuery({...query,page:result.page-1})}>上一頁</button>
        <span>第 {result.page}／{Math.max(1,Math.ceil(result.filtered_count/50))} 頁，每頁 50 項</span>
        <button disabled={result.page*50>=result.filtered_count} onClick={()=>setQuery({...query,page:result.page+1})}>下一頁</button></nav>
    </>}
    <details className="catalog-tools"><summary>更多工具</summary><div><CandidateRevenue scope={scope} onSelect={onSelect}/><p>下載全部結果： <a href={candidateExportUrl(scope,'csv')}>CSV</a>、<a href={candidateExportUrl(scope,'json')}>JSON</a>、<a href={candidateExportUrl(scope,'html')}>離線 HTML</a></p><p>下載目前篩選： <a href={candidateExportUrl(scope,'csv',query)}>CSV</a>、<a href={candidateExportUrl(scope,'json',query)}>JSON</a>、<a href={candidateExportUrl(scope,'html',query)}>離線 HTML</a></p></div></details>
  </section>;
}
