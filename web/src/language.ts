/** Presentation only: never changes stored states or calculation values. */
export const runStatus:Record<string,string>={queued:'等待開始分析',running:'正在分析資料',succeeded:'資料計算完成',failed:'這次分析未完成',cancelled:'已取消分析'};
export const stageLabel:Record<string,string>={normalized:'整理資料格式',quality:'檢查資料是否完整',targets:'確認哪些用戶已完整觀察 7 天',exploration:'整理用戶行為',search:'尋找可能的事件條件',exploration_triggers:'計算哪些用戶符合條件',selection:'選出要進一步檢查的條件',features:'整理比較所需的資料',validation:'用留出的用戶檢查結果',diagnostics:'比較條件與用戶重疊情況',baseline:'整理分析結果',report:'產生可下載的報告'};

const errors:Record<string,string>={
  TOO_MANY_RECHECK_WINDOWS:'選取的事件包含超過 10 種時間範圍，請減少要再次檢查的事件。',
  TASK_TIMEOUT:'這次分析超過可用的處理時間，尚未完成。請稍後重試；若持續發生，請聯絡維護人員。',
  NETWORK_UNAVAILABLE:'目前無法連線，請確認網路後再試一次。',
  INVALID_SERVER_RESPONSE:'服務暫時沒有回傳可讀取的內容，請稍後再試。',
  MISSING_PARTS:'檔案還沒有全部上傳。請重新選取原本的檔案，繼續上傳。',
  FILE_FINGERPRINT_MISMATCH:'這份檔案的內容與原本不同。請選取原本的檔案續傳；更換資料請開始新的分析。',
  INVALID_EXPORT_METADATA:'請檢查資料截止時間、匯出時間及資料說明是否完整。',
  REQUIRED_MAPPING_MISSING:'請填寫標示「必填」的來源欄位名稱。',
  CSV_OR_PARQUET_REQUIRED:'請選擇 CSV 或 Parquet 格式的檔案。',
  UPLOADS_INCOMPLETE:'還有檔案未完成上傳或檢查，請先完成上傳。',
  USERS_AND_EVENTS_REQUIRED:'請提供一份用戶名冊，以及至少一份用戶行為紀錄。',
  STORAGE_TRANSFER_FAILED:'檔案上傳中斷。請重新選取相同檔案，繼續上傳。',
  INVALID_FILE_FINGERPRINT:'這份檔案無法讀取或沒有內容，請檢查後重新選取。',
  AGENT_TIMEOUT:'助理這次未能及時完成回覆。你仍可閱讀已完成的報告，或重新提問。',
  AGENT_MODEL_FAILED:'助理暫時無法完成回覆，請稍後再試。',
  AGENT_REFERENCE_INVALID:'助理的回答未能通過來源檢查，因此沒有發布。請重新提問。',
  AGENT_OUTPUT_LIMIT:'助理的回答太長，還沒完成就達到長度上限，因此沒有發布。已完成的分析仍保留，請縮小問題範圍再試。',
  OPENROUTER_NOT_CONFIGURED:'分析助理尚未啟用。你仍可閱讀與下載已完成的報告。',
  AGENT_WORKER_UNAVAILABLE:'分析助理暫時無法連線。你仍可閱讀與下載已完成的報告。',
  AGENT_WORKER_DISCONNECTED:'分析助理暫時無法連線。你仍可閱讀與下載已完成的報告。',
  MEMORY_LIMIT:'這批資料超出目前可處理的記憶體範圍。請聯絡維護人員調整資源後再分析。',
};
export function errorText(error:unknown):string {
  const code=typeof error==='string'?error:error instanceof Error?error.message:'';
  return errors[code]??'這次操作未完成。請稍後再試；若持續發生，請聯絡維護人員。';
}
export function dateText(value:string):string {
  const date=new Date(value);
  return Number.isNaN(date.getTime())?'時間未知':new Intl.DateTimeFormat('zh-TW',{dateStyle:'medium',timeStyle:'short',timeZone:'UTC'}).format(date)+'（UTC）';
}
export function fileSize(bytes:number):string {
  if(!Number.isFinite(bytes)||bytes<0)return '大小未知';
  if(bytes<1024)return `${bytes} B`;
  if(bytes<1024**2)return `${(bytes/1024).toFixed(1)} KB`;
  if(bytes<1024**3)return `${(bytes/1024**2).toFixed(1)} MB`;
  return `${(bytes/1024**3).toFixed(1)} GB`;
}
