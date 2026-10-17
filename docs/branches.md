# 分支建立契約（PH30 實作中）

`POST /internal/analysis/branches` 使用伺服器 Bearer token；envelope 與唯讀工具一致：turn_id、parent_run_id、worker_id、fence、tool_call_id、arguments。arguments 目前僅接受完整 config，按既有 config schema 驗證；不可改 exploration_fraction，不能換 dataset 或自行選 split。

回傳 job_id / child_run_id / status / reused。以 source turn + tool call 唯一；相同呼叫相同配置重放回同一子run，不同配置回409。租約過期或取消的worker不能建立分支。這不是公開任意運算接口，也尚未作為模型工具註冊（PH31接續）。

`GET /api/runs/{id}/lineage` 讀父/root/dataset、來源turn、父報告version/hash、配置差異與cache context；不回S3路徑或原始log。分支provenance不可改寫，DB核對來源turn選取的parent及父report artifact。

Python Worker 已可執行具合法 provenance 的 followup。運算前核對父報告hash、不可變dataset/mapping/config及計算版本；產生targets後核對父split。PH29 policy確保followup維持exploratory，輸出保存為子run，父報告不覆寫。

已接跨run stage快取：normalized、quality、targets、exploration、features可重用；search、selection、validation、report不跨run快取。資料指紋、mapping、完整期、split設定、seed、計算版本、feature定義及直接上游檔案hash均納入key。窗口只影響exploration/features；因此改窗口仍可重用標準事件，但不能把舊窗口features當新結果。

analysis_stage_cache只指向已提交的不可變checkpoint，hit仍需驗所有S3物件；內容損壞明確失敗，不假裝命中或發布半成品。命中後在子run保存自己的checkpoint與來源audit，不覆寫父版。實體object key搬遷不改語意，檔案checksum改变則失效。baseline登錄但不使用跨run快取；followup才查索引。

每份報告audit.cache與cache_audit artifact保存stage/key/mode/source_run_id/reason；區分computed、cached與同run restored。cache_context不是命中證據，應核對這些執行產物。整個cache模式目前會校驗並複製至子run checkpoint，不宣稱零拷貝或沒有儲存傳輸成本。

驗證：`uv run pytest tests/test_branches.py -q`。真PostgreSQL/S3/Python Worker，合成資料；並行四次建立只產生一個job/run，子報告實際可讀，父報告bytes不變。
