# 分析進度、歷史及手動重試（PH21）

- `GET /api/runs/{run_id}/view`：持久 read model，包含 project/app/dataset、status、實際 completed_stages、attempt_number/max_attempts、error、ready、report_version 與 can_retry。不捏造百分比。自動重試排隊的錯誤取自 job；未知 run 404。
- `GET /api/runs?limit=25&cursor=...&dataset_id=...`：limit 1–100，dataset 篩選可省略。按 created_at/id 降序的 keyset cursor，next_cursor 為 null 表示末頁。cursor 是服務回傳的時間/UUID組合，請原樣 URL encode；非法 cursor 422。新 run 不會把較早頁面 offset 推移到重複資料。
- `POST /api/runs/{run_id}/retry`：需 Idempotency-Key，只允許特定技術錯誤的 failed baseline，且沒有任何已發布 artifact/report。回202是排隊ack，需重新讀view確認最新狀態。同key回相同ack，不重複擴張attempt budget。

ready 精確條件：run succeeded，且 report_versions 指向本run的 report_json，該attempt有唯一JSON/HTML/CSV三種匯出metadata。只看到succeeded或單一報告檔不能進工作區。此判定是持久發布完成，不替代下載時的S3 bytes checksum檢查。

手動重試先鎖job再鎖run、遞增fence、保留舊attempt與checkpoint，不改dataset/config或已發布結果。新的自動上限為當前attempt_number+3；只有明確POST行為才增加此額度，輪詢不會重試。技術錯誤allowlist見server/run_views.py；資料契約錯誤應建立新dataset修正。這是失敗執行的恢復，不是分析分支或重新使用holdout搜尋。

前端 `/runs/{id}` 定期讀view（queued/running時每次請求結束後2秒），終態停止；網路錯誤保留已讀資訊並標記未知，404/422停止自動重讀。`/workspace?run={id}` 也檢查ready，不能靠改URL跳過；Agent目前仍停用。`/history` 從DB分頁讀取，非localStorage。頁面刷新恢復同run，POST retry不是重新上傳或刪除舊run。
