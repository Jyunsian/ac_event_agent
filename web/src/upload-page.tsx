import { useEffect, useRef, useState } from 'react';
import { api, APIError, requestIdentity, transferFile, type UploadRecord } from './upload-client';
import { fingerprintFile } from './file-hash';
import defaults from '../../contracts/defaults_v4.json';
import legacyDefaults from '../../contracts/defaults.json';
import {existingRule,type ExistingRuleInput} from './v4-existing-rules';
import schema from '../../contracts/schema.json';
import sampleExport from '../../tests/fixtures/hand/export.json';
import {FindingSelector,type PriorFinding} from './finding-selector';
import {errorText,fileSize} from './language';
import {fieldCopy,utcInput,utcValue} from './field-language';

type Mapping = Record<'users' | 'events', Record<string,string>>;
type Dataset = {id:string; mapping:Mapping; export_metadata:typeof sampleExport; sealed_at:string|null};
const fields = {users:Object.keys(schema.$defs.user.properties),events:Object.keys(schema.$defs.event.properties)};
const required = {users:schema.$defs.user.required,events:schema.$defs.event.required};
const initialMapping: Mapping = {users:Object.fromEntries(required.users.map(k=>[k,k])),events:Object.fromEntries(required.events.map(k=>[k,k]))};
const emptyExport = {schema_version:'1.0',complete_through:'',exported_at:'',origin:'first_open',id_policy:'',revenue_timing:'unknown',synthetic:false};
const textError = errorText;

export function UploadPage() {
  const [existing,setExisting]=useState<ExistingRuleInput[]>([]);
  const demo = new URLSearchParams(location.search).get('demo')==='hand';
  const [datasetId,setDatasetId] = useState(new URLSearchParams(location.search).get('dataset'));
  const [findings,setFindings]=useState<PriorFinding[]>([]);
  useEffect(()=>{
    if(!datasetId)return;
    try{const saved=JSON.parse(localStorage.getItem(`ac.recheck:${datasetId}`)||'[]');
      if(Array.isArray(saved)&&saved.length<=10&&saved.every(x=>typeof x.id==='string'&&typeof x.hypothesis==='string'&&
        typeof x.source_dataset_id==='string'&&typeof x.outcome==='string'&&typeof x.analysis_version==='string'&&typeof x.event_spec?.window_hours==='number'&&
        x.event_spec.window_hours>0&&x.event_spec.window_hours<=168))setFindings(saved);
    }catch{/* Optional draft preference; server validates all selected sources. */}
  },[datasetId]);
  function chooseFindings(items:PriorFinding[]){setFindings(items);try{localStorage.setItem(`ac.recheck:${datasetId}`,JSON.stringify(items));}catch{/* Draft still works in memory. */}}
  const [dataset,setDataset] = useState<Dataset|null>(null);
  const [appId,setAppId] = useState(''); const [name,setName] = useState('');
  const [uploads,setUploads] = useState<UploadRecord[]>([]);
  const [mapping,setMapping] = useState<Mapping>(initialMapping);
  const [metadata,setMetadata] = useState(emptyExport);
  const [busy,setBusy] = useState(false);const [error,setError] = useState('');const [notice,setNotice] = useState('');
  const [progress,setProgress] = useState<{label:string;bytes:number;total:number}|null>(null);
  const [runId,setRunId] = useState<string|null>(null);
  const operation = useRef<AbortController|null>(null);
  const errorBox = useRef<HTMLDivElement|null>(null);
  useEffect(()=>{if(error)errorBox.current?.focus();},[error]);
  const createKey = useRef(crypto.randomUUID());
  const refresh = async (id:string) => {
    const [ds,list] = await Promise.all([api<Dataset>(`/api/datasets/${id}`),api<{uploads:UploadRecord[]}>(`/api/datasets/${id}/uploads`)]);
    setDataset(ds);setUploads(list.uploads); return ds;
  };
  useEffect(()=>{
    if (!datasetId) return;
    let current = true;
    Promise.all([api<Dataset>(`/api/datasets/${datasetId}`),api<{uploads:UploadRecord[]}>(`/api/datasets/${datasetId}/uploads`)]).then(([ds,list])=>{
      if (!current) return;setDataset(ds);setUploads(list.uploads);
      if (ds.mapping && Object.keys(ds.mapping).length) setMapping({users:ds.mapping.users || {},events:ds.mapping.events || {}});
      if (ds.export_metadata && Object.keys(ds.export_metadata).length) setMetadata(ds.export_metadata);
    }).catch(e=>{if(current)setError(textError(e));});
    return ()=>{current=false;};
  },[datasetId]);
  useEffect(()=>()=>operation.current?.abort(),[]);
  async function perform(action:(signal:AbortSignal)=>Promise<void>) {
    if (operation.current) return;
    const controller = new AbortController();operation.current=controller;setBusy(true);setError('');setNotice('');
    try {await action(controller.signal);} catch(e) {setError(controller.signal.aborted ? '已暫停；重新選取相同檔案即可續傳。' : textError(e));}
    finally {operation.current=null;setBusy(false);setProgress(null);if(datasetId)try{await refresh(datasetId);}catch(e){setError(textError(e));}}
  }
  const sealed = Boolean(dataset?.sealed_at);
  async function upload(files:FileList|null,role:'users'|'events',record?:UploadRecord) {
    if (!files?.length || !datasetId) return;
    const chosen = Array.from(files);
    await perform(async signal=>{
      for (const file of chosen) {
        if (!/\.(csv|parquet)$/i.test(file.name)) throw new APIError('CSV_OR_PARQUET_REQUIRED');
        const fingerprint = await fingerprintFile(file,(bytes,total)=>setProgress({label:`核對 ${file.name}`,bytes,total}),signal);
        await transferFile({datasetId,file,role,record,fingerprint,signal,
          progress:(bytes,total)=>setProgress({label:`已確認上傳 ${file.name}`,bytes,total})});
        await refresh(datasetId);
      }
      setNotice('檔案已完整上傳，內容檢查通過。接著請確認欄位與時間說明。');
    });
  }
  async function save(signal:AbortSignal) {
    if (!datasetId) return;
    const complete=Date.parse(metadata.complete_through),exported=Date.parse(metadata.exported_at);
    if(!Number.isFinite(complete)||!Number.isFinite(exported)||complete>exported)throw new APIError('INVALID_EXPORT_METADATA');
    const clean:Mapping = {users:{},events:{}};
    for (const role of ['users','events'] as const) {
      for (const [key,value] of Object.entries(mapping[role])) if(value.trim()) clean[role][key]=value.trim();
      if (required[role].some(key=>!clean[role][key])) throw new APIError('REQUIRED_MAPPING_MISSING');
    }
    await api(`/api/datasets/${datasetId}/mapping`,'PUT',{mapping:clean,export_metadata:metadata},signal);
  }
  return <div className="upload-page"><header className="toolbar"><a className="wordmark" href="/">AC Event Agent</a><span>上傳資料</span><a className="new-dataset" href="/upload">上傳新資料</a></header>
    <main className="upload-content"><h1>從用戶資料，找出值得測試的廣告事件</h1><p className="muted">準備一份用戶名冊，以及一份或多份行為紀錄（CSV／Parquet）。我們會分析哪些行為與前 7 天的廣告收益有關，原始檔案會保留。</p>{demo&&<p className="fixture-notice">示範模式：只供範例資料操作，請勿填入真實客戶資料。</p>}
      {error && <div className="error-message" role="alert" tabIndex={-1} ref={errorBox}>{error}</div>}{notice && <p className="success-message" role="status">{notice}</p>}
      {!datasetId ? <form onSubmit={event=>{event.preventDefault();void perform(async signal=>{
        const project=await api<{id:string}>('/api/projects','POST',{app_id:appId,name},signal,createKey.current+':project');
        const ds=await api<Dataset>('/api/datasets','POST',{project_id:project.id},signal,createKey.current+':dataset');
        history.replaceState(null,'',`/upload?dataset=${ds.id}${demo?'&demo=hand':''}`);setDatasetId(ds.id);setDataset(ds);
      });}}><fieldset disabled={busy}><legend>專案</legend><label>App ID<input required maxLength={200} value={appId} onChange={e=>{setAppId(e.target.value);createKey.current=crypto.randomUUID();}}/></label><label>分析名稱<input required maxLength={200} value={name} onChange={e=>{setName(e.target.value);createKey.current=crypto.randomUUID();}}/></label><button type="submit">繼續上傳資料</button></fieldset></form> : <>
        <details><summary>資料識別資訊</summary><p className="dataset-identity">{datasetId}</p></details>{sealed && <p className="inline-note">這份資料已用於分析，不能直接修改檔案或欄位。更換資料請上傳新的一份；只想調整分析條件，可到報告中向助理提問。</p>}
        <section><h2>1. 上傳與續傳</h2><p>中斷或刷新後，從下方紀錄重新選取相同檔案。檔名相同但內容不同會拒絕續傳。</p>
          <fieldset disabled={busy||sealed||!dataset}><legend>新增檔案</legend>
            <label>用戶表<input type="file" accept=".csv,.parquet" disabled={uploads.some(u=>u.role==='users')} onChange={e=>{void upload(e.target.files,'users');e.target.value='';}}/></label>
            <label>事件檔（可多選）<input type="file" accept=".csv,.parquet" multiple onChange={e=>{void upload(e.target.files,'events');e.target.value='';}}/></label></fieldset>
          {progress && <div role="status"><p>{progress.label}：{fileSize(progress.bytes)} / {fileSize(progress.total)}</p><progress value={progress.bytes} max={progress.total}/><p className="muted">傳送後還會檢查檔案內容，檢查通過才算完成。</p></div>}
          {busy && <button onClick={()=>operation.current?.abort()}>暫停目前操作</button>}
          <ul className="upload-records">{uploads.map(record=><li key={record.id}><strong>{record.filename}</strong><span>{record.role==='users'?'用戶名冊':'行為紀錄'} · {fileSize(record.expected_size)} · {record.status==='completed'?'已檢查完成':'待完成上傳'}</span>
            {record.status!=='completed' && <><label>重新選取 {record.filename}<input type="file" disabled={busy||sealed} onChange={e=>{void upload(e.target.files,record.role,record);e.target.value='';}}/></label>
              <button disabled={busy||sealed} onClick={()=>void perform(async signal=>{await api(`/api/uploads/${record.id}/complete`,'POST',{size_bytes:record.expected_size,sha256:record.expected_sha256},signal);setNotice('已確認檔案完成並通過校驗。');})}>檢查完成狀態：{record.filename}</button></>}</li>)}</ul>
        </section>
        <form onSubmit={event=>{event.preventDefault();void perform(async signal=>{await save(signal);setNotice('欄位與資料說明已儲存，重新開啟頁面仍會保留。');});}}>
          <fieldset disabled={busy||sealed||!dataset}><legend>2. 確認每個欄位代表什麼</legend><p>在下方填入你檔案中的欄位名稱。例如檔案用 uid 識別用戶，就在「用戶識別碼」填入 uid。選填欄位不存在時請留空。</p><div className="mapping-columns">{(['users','events'] as const).map(role=><section key={role}><h3>{role==='users'?'用戶名冊':'行為紀錄'}</h3>{fields[role].map(key=><label key={key}>{fieldCopy[key]?.label||'其他資料欄位'}{required[role].includes(key)?'（必填）':'（選填）'}<small>{fieldCopy[key]?.help}</small><input aria-label={`${role==='users'?'用戶名冊':'行為紀錄'}：${fieldCopy[key]?.label||key}`} data-field={`${role}.${key}`} placeholder={`例如：${key}`} required={required[role].includes(key)} maxLength={200} value={mapping[role][key]||''} onChange={e=>setMapping({...mapping,[role]:{...mapping[role],[key]:e.target.value}})}/></label>)}</section>)}</div></fieldset>
          <fieldset disabled={busy||sealed||!dataset}><legend>3. 確認資料涵蓋的時間</legend><p>以下日期與時間一律使用世界標準時間（UTC），不是你電腦的本地時間。請向資料提供者確認，不要把匯出時間當成資料已全部到齊的時間。</p><label>資料完整截止時間（UTC）<small>哪個時間以前的紀錄已全部匯入？較晚才收到的資料也要考慮。</small><input type="datetime-local" step="any" required value={utcInput(metadata.complete_through)} onChange={e=>setMetadata({...metadata,complete_through:utcValue(e.target.value)})}/></label><label>檔案匯出時間（UTC）<small>這份檔案是在什麼時間產生的？</small><input type="datetime-local" step="any" required value={utcInput(metadata.exported_at)} onChange={e=>setMetadata({...metadata,exported_at:utcValue(e.target.value)})}/></label>
            <label>時間起點<select value={metadata.origin} onChange={e=>setMetadata({...metadata,origin:e.target.value})}><option value="first_open">首次開啟</option><option value="install">安裝</option></select></label>
            <label>如何識別同一位用戶？<small>請說明重新安裝或換裝置時是否會變成新的識別碼；不知道時請先向資料提供者確認。</small><input required maxLength={256} placeholder="例如：重新安裝會產生新的匿名識別碼" value={metadata.id_policy} onChange={e=>setMetadata({...metadata,id_policy:e.target.value})}/></label>
            <label>收益何時可取得<select value={metadata.revenue_timing} onChange={e=>setMetadata({...metadata,revenue_timing:e.target.value})}><option value="unknown">不確定（暫不分析以收益為條件的事件）</option><option value="immediate">展示時立即取得</option><option value="available_at">依「資料可取得時間」欄位</option></select></label>
            <label className="checkbox-label"><input type="checkbox" checked={metadata.synthetic} onChange={e=>setMetadata({...metadata,synthetic:e.target.checked})}/>這是合成測試資料</label>
            {demo&&<button type="button" onClick={()=>setMetadata(sampleExport)}>填入範例資料的時間與說明</button>}<button type="submit">儲存欄位與資料說明</button>
          </fieldset>
        </form>
        <section><h2>4. 開始分析</h2><p>我們會先儲存你的設定，再分析開始使用後 {defaults.windows_hours.join('、')} 小時內的行為。完成後可閱讀報告，再向助理深入提問。</p>
          <fieldset disabled={busy||sealed||!dataset||findings.length>0}><legend>目前使用的門檻（選填）</legend><p>加入公司現在的條件，與新發現的行為一起比較。不填也會自動比較單純收入門檻。</p>
            {existing.map((row,i)=><div key={i}><label>規則名稱<input value={row.name} maxLength={120} onChange={e=>setExisting(existing.map((r,j)=>j===i?{...r,name:e.target.value}:r))}/></label><label>行為<select value={row.metric} onChange={e=>setExisting(existing.map((r,j)=>j===i?{...r,metric:e.target.value}:r))}><option value="ad_revenue_sum">累積廣告收入（美元）</option><option value="ad_count">廣告展示次數</option><option value="session_count">不同遊玩次數</option><option value="level_complete_count">完成關卡次數</option><option value="level_fail_count">關卡失敗次數</option></select></label><label>至少達到<input type="number" min="0.000001" step="any" value={row.threshold} onChange={e=>setExisting(existing.map((r,j)=>j===i?{...r,threshold:Number(e.target.value)}:r))}/></label><label>從開始使用到<select value={row.deadline} onChange={e=>setExisting(existing.map((r,j)=>j===i?{...r,deadline:Number(e.target.value)}:r))}>{[24,48,72,96,120,144].map(h=><option key={h} value={h}>{h} 小時</option>)}</select></label><button onClick={()=>setExisting(existing.filter((_,j)=>j!==i))}>移除這條規則</button></div>)}
            <button disabled={existing.length>=30} onClick={()=>setExisting([...existing,{name:'現行收入門檻',metric:'ad_revenue_sum',threshold:0.01,deadline:24}])}>加入現有規則</button>
          </fieldset>
          <FindingSelector datasetId={datasetId} disabled={busy||sealed||!dataset} selected={findings} onChange={chooseFindings}/>
          <button disabled={busy||sealed||!dataset} onClick={()=>void perform(async signal=>{await save(signal);
            const windows=[...new Set([...defaults.windows_hours,...findings.map(x=>x.event_spec.window_hours)])].sort((a,b)=>a-b);
            if(windows.length>10)throw new APIError('TOO_MANY_RECHECK_WINDOWS');
            const sourceVersions=[...new Set(findings.map(x=>x.analysis_version))];
            if(sourceVersions.length>1)throw new APIError('RECHECK_ANALYSIS_VERSION_MISMATCH');
            const config={...legacyDefaults,analysis_version:sourceVersions[0]||legacyDefaults.analysis_version,windows_hours:windows};
            const body=findings.length?{config,finding_ids:findings.map(x=>x.id).sort()}:{...defaults,existing_rules:await Promise.all(existing.map(existingRule))};
            const route=findings.length?'finding-recheck':'baseline';
            const result=await api<{run_id:string}>(`/api/datasets/${datasetId}/${route}`,'POST',body,signal,requestIdentity(`${route}:${datasetId}:${JSON.stringify(body)}`));setRunId(result.run_id);setNotice('分析已排入等待，關閉頁面不會取消。你可以查看進度，完成後再開啟報告。');})}>{findings.length?'再次檢查先前的事件':'開始分析'}</button>
          {runId && <p><a href={`/runs/${runId}`}>查看分析進度</a></p>}
        </section>
      </>}
    </main></div>;
}
