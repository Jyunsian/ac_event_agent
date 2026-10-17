import {useEffect,useState} from 'react';
import {api} from './upload-client';
import {errorText} from './language';
export type PriorFinding={id:string;hypothesis:string;source_dataset_id:string;outcome:string;analysis_version:string;event_spec:{window_hours:number}};
export function FindingSelector({datasetId,disabled,selected,onChange}:{datasetId:string;disabled:boolean;selected:PriorFinding[];onChange:(items:PriorFinding[])=>void}){
 const [items,setItems]=useState<PriorFinding[]>([]),[cursor,setCursor]=useState<string|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function read(next?:string){setBusy(true);setError('');try{
  const page=await api<{items:PriorFinding[];next_cursor:string|null}>(`/api/datasets/${datasetId}/recheck-sources?limit=25${next?'&cursor='+encodeURIComponent(next):''}`);
  setItems(old=>next?[...old,...page.items]:page.items);setCursor(page.next_cursor);
 }catch(e){setError(errorText(e));}finally{setBusy(false);}}
 useEffect(()=>{void read();},[datasetId]);
 return <fieldset disabled={disabled}><legend>選填：再次檢查之前找到的事件</legend>
  <p>不選擇時，會尋找新的事件條件。選擇後，改用這批資料檢查同一個 App 之前的條件，不再修改門檻。是否足以確認結果，仍取決於資料是否獨立與完整。最多選 10 筆。</p>
  <button type="button" disabled={busy} onClick={()=>void read()}>重新讀取舊觀察</button>
  {error&&<p role="alert">{error}。未自動改變選擇。</p>}
  {selected.length>0&&<p>已選 {selected.length} 筆 <button type="button" onClick={()=>onChange([])}>清除重驗選擇</button></p>}
  {items.map(item=><label key={item.id} className="checkbox-label"><input type="checkbox" value={item.id} checked={selected.some(x=>x.id===item.id)}
   disabled={['3.0-casual-game','4.0-time-aware'].includes(item.analysis_version)||(!selected.some(x=>x.id===item.id)&&selected.length>=10)}
   onChange={e=>onChange(e.target.checked?[...selected,item]:selected.filter(x=>x.id!==item.id))}/>
   <span>{item.hypothesis} · {item.event_spec.window_hours} 小時 · {['3.0-casual-game','4.0-time-aware'].includes(item.analysis_version)?'此版本暫不支援舊規則跨批次重驗':(({observation:'先前的觀察',supported:'新資料也支持',contradicted:'新資料未支持',inconclusive:'還無法判斷'} as Record<string,string>)[item.outcome]||'結果待確認')}</span></label>)}
  {!busy&&!items.length&&!error&&<p>目前沒有同 App 的舊觀察。</p>}
  {busy&&<p role="status">讀取觀察…</p>}{cursor&&<button type="button" disabled={busy} onClick={()=>void read(cursor)}>載入較早觀察</button>}
 </fieldset>;
}
