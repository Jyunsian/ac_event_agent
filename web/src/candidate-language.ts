type Spec={analysis_version?:unknown;name?:unknown;window_hours:number;predicate:Record<string,unknown>;origin?:unknown};
const events:Record<string,string>={ad_impression:'看到廣告',session_start:'開始使用 App',session_end:'結束這次使用'};
const formats:Record<string,string>={rewarded:'獎勵式廣告',interstitial:'插頁式廣告',banner:'橫幅廣告',app_open:'開屏廣告',native:'原生廣告',other:'其他類型廣告',unknown:'未分類廣告'};
const sequences:Record<string,string>={level_start_to_complete:'開始關卡後完成同一關',level_fail_to_start:'關卡失敗後重試同一關',level_fail_to_complete:'關卡失敗後完成同一關',level_fail_to_session_end:'關卡失敗後離開 App',session_start_to_level_complete:'打開 App 後完成關卡',level_complete_to_ad_impression:'完成關卡後看到廣告',rewarded_ad_to_level_complete:'看完獎勵式廣告後完成關卡'};
function compact(value:number,digits=2):string{return new Intl.NumberFormat('zh-TW',{maximumFractionDigits:digits}).format(value);}
function dollars(value:number):string{return `$${compact(value,value<.0001?8:value<.01?5:4)}`;}
function count(value:number):string{return compact(value,2);}
function scopeOf(p:Record<string,unknown>):Record<string,unknown>{return p.scope&&typeof p.scope==='object'&&!Array.isArray(p.scope)?p.scope as Record<string,unknown>:{};}
function comparison(p:Record<string,unknown>,positive:string,negative:string){return p.comparator==='lte'?negative:positive;}
export function duration(seconds:number):string {
  if(!Number.isFinite(seconds)||seconds<0)return '時間未知';
  const totalSeconds=Math.round(seconds);
  if(totalSeconds<60)return `${totalSeconds} 秒`;
  const wholeMinutes=Math.floor(totalSeconds/60),secondsLeft=totalSeconds%60;
  if(wholeMinutes<60)return secondsLeft?`${wholeMinutes} 分鐘 ${secondsLeft} 秒`:`${wholeMinutes} 分鐘`;
  const minutes=Math.round(totalSeconds/60);
  const hours=Math.floor(minutes/60),remainder=minutes%60;
  return remainder?`${hours} 小時 ${remainder} 分鐘`:`${hours} 小時`;
}
function atomName(p:Record<string,unknown>):string {
  const threshold=Number(p.threshold),scope=scopeOf(p),metric=String(p.metric);
  if(!Number.isFinite(threshold))return '條件資料不完整';
  const amount=count(threshold),format=scope.ad_format&&scope.ad_format!=='all'?formats[String(scope.ad_format)]||String(scope.ad_format):'';
  if(metric==='ad_count')return `看過至少 ${amount} 次${format||'廣告'}`;
  if(metric==='ad_revenue_sum')return `${format||'廣告'}累積收益至少 ${dollars(threshold)}`;
  if(metric==='session_count')return `使用 App 至少 ${amount} 次`;
  if(metric==='first_return_delay_seconds')return comparison(p,`首次回來使用 App 時，距離安裝至少 ${duration(threshold)}`,`安裝後 ${duration(threshold)}內首次回來使用 App`);
  if(metric==='return_in_interval'){
    const start=Number(scope.start_hours),end=Number(scope.end_hours);
    return Number.isFinite(start)&&Number.isFinite(end)?`在安裝後第 ${compact(start)}～${compact(end)} 小時期間回來使用 App`:`在指定期間回來使用 App`;
  }
  if(metric==='return_interval_count')return `在至少 ${amount} 個不同時段回來使用 App`;
  if(metric==='consecutive_return_days')return `連續回來使用 App 至少 ${amount} 天`;
  if(metric==='post_return_session_count')return `首次回訪後，又使用 App 至少 ${amount} 次`;
  if(metric==='post_return_engaged_seconds')return `首次回訪後，累積有效使用至少 ${duration(threshold)}`;
  if(metric==='level_start_count')return `開始關卡至少 ${amount} 次`;
  if(metric==='level_complete_count')return `完成關卡至少 ${amount} 次`;
  if(metric==='level_fail_count')return `關卡失敗至少 ${amount} 次`;
  if(metric==='distinct_completed_levels')return `完成至少 ${amount} 個不同關卡`;
  if(['max_completed_level_index','completed_level','reached_level'].includes(metric))return `至少玩到第 ${amount} 關`;
  if(metric==='level_time_to_reach_seconds'){
    const level=Number(scope.level_index),target=Number.isFinite(level)?`第 ${compact(level)} 關`:'指定關卡';
    return comparison(p,`花了至少 ${duration(threshold)}才到達${target}`,`在 ${duration(threshold)}內到達${target}`);
  }
  if(metric==='attempts_per_level')return comparison(p,`平均每關嘗試至少 ${amount} 次`,`平均每關嘗試不超過 ${amount} 次`);
  if(metric==='completes_per_session')return comparison(p,`平均每次使用完成至少 ${amount} 關`,`平均每次使用完成不超過 ${amount} 關`);
  if(metric==='complete_start_ratio')return comparison(p,`開始的關卡中，至少 ${compact(threshold*100)}% 有完成`,`開始的關卡中，完成比例不超過 ${compact(threshold*100)}%`);
  if(metric==='fail_start_ratio')return comparison(p,`開始的關卡中，至少 ${compact(threshold*100)}% 以失敗結束`,`開始的關卡中，失敗比例不超過 ${compact(threshold*100)}%`);
  if(metric==='completion_duration_seconds')return comparison(p,`完成一關通常要花至少 ${duration(threshold)}`,`完成一關通常不超過 ${duration(threshold)}`);
  if(metric==='consecutive_failures')return `曾經連續失敗至少 ${amount} 次`;
  if(metric==='retry_same_level')return `同一關失敗後重試至少 ${amount} 次`;
  if(metric==='complete_after_fail')return `關卡失敗後又完成至少 ${amount} 次`;
  if(metric==='session_after_fail')return `關卡失敗後，另一次回來使用 App 至少 ${amount} 次`;
  return `其他玩家行為${p.comparator==='lte'?'不超過':'至少'} ${amount}`;
}
export function conditionName(p:Record<string,unknown>,depth=0):string {
  if(depth>3)return '多個行為的組合';
  if(p.node==='boolean'&&Array.isArray(p.clauses))return p.clauses.map(c=>'（'+conditionName(c as Record<string,unknown>,depth+1)+'）').join(p.operator==='and'?'，而且':'，或者');
  if(p.node==='sequence'){
    const repeats=Number(p.repeats),tail=Number.isFinite(repeats)&&repeats>1?`，至少出現 ${count(repeats)} 次`:'';
    return `${sequences[String(p.template)]||'指定行為依序發生'}，兩個行為相隔不超過 ${duration(Number(p.max_gap_seconds))}${tail}`;
  }
  if(p.node==='atom')return atomName(p);
  if((p.op==='and'||p.op==='or')&&Array.isArray(p.clauses))return p.clauses.map(c=>'（'+conditionName(c as Record<string,unknown>,depth+1)+'）').join(p.op==='and'?'，而且':'，或者');
  if(p.op==='sequence'&&Array.isArray(p.steps)){
    const repeats=Number(p.repeats),tail=Number.isFinite(repeats)&&repeats>1?`，至少出現 ${count(repeats)} 次`:'';
    return `${p.steps.map(s=>events[String(s)]||'指定行為').join('，接著')}，兩個行為相隔不超過 ${duration(Number(p.max_gap_seconds))}${tail}`;
  }
  const threshold=Number(p.threshold);if(!Number.isFinite(threshold))return '條件資料不完整';
  const ad=p.ad_format?formats[String(p.ad_format)]||'指定類型廣告':'廣告';
  if(p.op==='count')return `${p.event_name==='session_start'?'使用 App':p.event_name==='session_end'?'結束使用 App':`看過${ad}`}至少 ${count(threshold)} 次`;
  if(p.op==='revenue_sum')return `${ad}累積收益至少 ${dollars(threshold)}`;
  if(p.op==='session_count')return `使用 App 至少 ${count(threshold)} 次`;
  if(p.op==='engaged_seconds')return `累積有效使用至少 ${duration(threshold)}`;
  return '其他玩家行為';
}
export function candidateName(spec:Spec):string {
  if(spec.analysis_version==='4.0-time-aware'&&typeof spec.name==='string')return spec.name;
  const origin=spec.origin==='first_open'?'首次開啟 App':spec.origin==='install'?'安裝':'開始使用 App';
  const p=spec.predicate,scope=scopeOf(p),threshold=Number(p.threshold),window=duration(spec.window_hours*3600);
  if(p.node==='atom'&&Number.isFinite(threshold)&&p.metric==='level_time_to_reach_seconds'){
    const level=Number(scope.level_index),target=Number.isFinite(level)?`第 ${compact(level)} 關`:'指定關卡';
    return p.comparator==='lte'?`${origin}後 ${duration(threshold)}內到達${target}`:`${origin}後，超過 ${duration(threshold)}才到達${target}（只觀察前 ${window}）`;
  }
  if(p.node==='atom'&&Number.isFinite(threshold)&&p.metric==='first_return_delay_seconds')
    return p.comparator==='lte'?`${origin}後 ${duration(threshold)}內首次回來使用 App`:`${origin}後，超過 ${duration(threshold)}才首次回來使用 App（只觀察前 ${window}）`;
  if(p.node==='atom'&&p.metric==='return_in_interval')return conditionName(p);
  return `${origin}後 ${window}內，${conditionName(p)}`;
}
export const evidenceLabel:Record<string,string>={
  historically_validated:'新資料已確認',
  historically_supported:'新資料已確認',
  not_supported:'新資料未重現',
  insufficient_data:'資料仍不足',
  exploratory:'等待新資料'
};
