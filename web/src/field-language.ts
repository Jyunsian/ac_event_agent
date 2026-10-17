export const fieldCopy:Record<string,{label:string;help:string}>={
  app_id:{label:'App 識別碼',help:'同一個 App 請使用相同代碼，例如 com.example.game。'},
  user_id:{label:'用戶識別碼',help:'用來連接用戶名冊與行為紀錄，不需要姓名或電子郵件。'},
  installed_at:{label:'安裝或首次開啟時間',help:'作為每位用戶前 7 天的計算起點，須與下方時間起點一致。'},
  platform:{label:'手機系統',help:'例如 Android 或 iOS。'},
  country:{label:'國家',help:'用來比較不同國家的用戶；沒有此欄位可留空。'},
  acquisition_source:{label:'用戶來源',help:'用戶從哪個廣告管道或自然流量而來。'},
  campaign_id:{label:'廣告活動識別碼',help:'用來辨識帶來用戶的廣告活動。'},
  app_version_at_install:{label:'開始使用時的 App 版本',help:'例如 1.2.0；不知道可留空。'},
  event_id:{label:'行為紀錄識別碼',help:'每筆行為的唯一代碼，用來避免重複計算回傳紀錄。'},
  event_name:{label:'行為名稱',help:'例如 ad_impression（廣告展示）、session_start（開始使用）。'},
  event_time:{label:'行為發生時間',help:'這筆行為實際發生的時間。'},
  available_at:{label:'資料可取得時間',help:'系統何時真正收到這筆資料；不是行為發生時間。'},
  source_sequence:{label:'來源紀錄順序',help:'同一時間有多筆行為時，用來確認先後順序。'},
  session_id:{label:'本次使用的識別碼',help:'同一次開啟與結束 App 的紀錄使用相同代碼。'},
  ad_format:{label:'廣告類型',help:'例如 rewarded（獎勵式）、interstitial（插頁式）、banner（橫幅）。'},
  revenue_usd:{label:'單次廣告收益（美元）',help:'每次展示的收益，不是累積收益。缺少金額請留空，不要填成零。'},
  engaged_seconds:{label:'有效使用時間（秒）',help:'用戶實際在前景使用的時間，不包含 App 留在背景的時間。'},
  level_id:{label:'關卡識別碼',help:'遊戲原始關卡代碼；沒有時只能分析 Level 事件次數。'},
  level_index:{label:'關卡順序',help:'來源提供的非負整數進度，不會從關卡名稱猜測。'},
  attempt_id:{label:'挑戰識別碼',help:'同一次關卡挑戰的開始、失敗或完成使用相同代碼。'},
  level_mode:{label:'關卡模式',help:'例如 main、daily；第一版只保存與檢查品質。'},
  difficulty:{label:'關卡難度',help:'來源提供的難度標記；第一版不用來生成主要候選。'},
  revive_used:{label:'是否使用復活',help:'true／false；第一版只保存與檢查品質。'},
  booster_used:{label:'是否使用道具',help:'true／false；第一版只保存與檢查品質。'},
  app_version:{label:'事件發生時版本',help:'事件發生時的 App 版本；第一版只保存與檢查品質。'},
};

// The input explicitly uses UTC; never interpret the chosen value in the browser timezone.
export function utcInput(value:string):string {
  return value.endsWith('Z')?value.slice(0,-1):'';
}
export function utcValue(value:string):string {return value?(value.length===16?value+':00':value)+'Z':'';}
