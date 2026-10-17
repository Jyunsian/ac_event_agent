/** Read-only presentation: no scoring, selection or statistical decisions here. */
type Data=Record<string,any>;
export function evidenceLabel(test:Data|undefined,exploratory=false):string {
  if(exploratory)return '僅供探索';
  if(!test)return '尚未驗證';
  if(test.claim_allowed===true)return '收入較高：已驗證';
  if(test.testable===true)return '收入較高：未確認';
  return '資料不足';
}
export function difference(a:unknown,b:unknown):number|null{return typeof a==='number'&&Number.isFinite(a)&&typeof b==='number'&&Number.isFinite(b)?a-b:null;}
export function overviewPoint(row:Data,hours:number,cohort='observation'):Data {
  const a=row.time_analysis;
  const p=a?.[cohort]?.find((p:Data)=>p.hours===hours);
  if(p)return {point:p,control:a.controls?.[String(hours)]?.[cohort],threshold:a.controls?.[String(hours)]?.rule?.predicate?.threshold,
    tests:(a.inference??[]).filter((t:Data)=>t.hours===hours),holdout:a.holdout?.find((p:Data)=>p.hours===hours),mode:row.event_spec?.mode};
  const d=row.summary?.decision??{};
  if(cohort!=='observation')return {...d,point:undefined,control_compact:undefined,...d.scopes?.[cohort],mode:row.summary?.event_spec?.mode};
  return {...d,mode:row.summary?.event_spec?.mode};
}
export function deadlineLabel(spec:Data,hours:number):string {
  const origin=spec?.origin==='first_open'?'首次開啟後':'安裝後';
  if(spec?.mode==='snapshot')return `${origin} ${hours} 小時的指定時間判斷`;
  if(spec?.mode==='rolling')return `截至${origin} ${hours} 小時，曾在連續 24 小時內達標`;
  return `${origin} ${hours} 小時內累積達標`;
}

export function incomeComparison(delta:unknown,target:string):string {
  if(typeof delta!=='number'||!Number.isFinite(delta))return `與${target}無法比較`;
  if(delta===0)return `與${target}相同`;
  const amount=Math.abs(delta)<.005?'不到 $0.01':`$${Math.abs(delta).toFixed(2)}`;
  return `比${target}${delta>0?'高':'低'} ${amount}／人`;
}

/** Totals cover all mature players, even when no rule can be recommended. */
export function reportTotals(report:Data):{revenue_usd:number|null;arpu_usd:number|null}{
  const all=report.candidates?.[0]?.time_analysis?.observation?.[0]?.groups?.all;
  if(all)return {revenue_usd:all.revenue_usd??null,arpu_usd:all.arpu_usd??null};
  const targets=report.summary?.targets,parts=Object.values(targets?.summary??{}) as Data[];
  if(!parts.length||parts.some(p=>p.unknown_targets!==0||typeof p.revenue_usd!=='number')||parts.reduce((n,p)=>n+p.users,0)!==targets?.mature_users)return {revenue_usd:null,arpu_usd:null};
  const revenue=parts.reduce((n,p)=>n+p.revenue_usd,0);
  return {revenue_usd:revenue,arpu_usd:targets.mature_users>0?revenue/targets.mature_users:null};
}

export function reportNumber(value:number,unit=''):string {
  if(!Number.isFinite(value))return '未知';
  const n=unit==='%'?value*100:unit==='h'?value/3600:value;
  const suffix=unit==='h'?' 小時':unit==='USD'?' 美元':unit;
  if(n!==0&&Math.abs(n)<.005)return (n<0?'> -0.01':'< 0.01')+suffix;
  return new Intl.NumberFormat('zh-TW',{minimumFractionDigits:unit?2:0,maximumFractionDigits:2}).format(n)+suffix;
}
export function displayRuleName(name:unknown):string {
  return String(name??'').replace(/-?\d+\.\d{3,}/g,value=>'約 '+Number(value).toFixed(2));
}
