# PH31 — 受控重跑工具

狀態：PH31 本地 Gate 通過；詳見 evidence/PH31.md 的瀏覽器及運算中取消整合證據。真 OpenRouter 仍待 X01。

Agent 的正式工具集合在既有三個唯讀工具之外，加入：

- `rerun_analysis`：接受非空 patch，僅 `windows_hours`、`thresholds`、`max_candidates`。伺服器合併父 run 的不可變 config，沿用 dataset、split、seed、樣本與驗證規則；不接受 SQL、程式碼或任意資料路徑。建立持久 child run/job 後立即返回識別碼。
- `evaluate_analysis`：僅接受 `child_run_id`，伺服器要求該 child 由當前 turn 建立、parent 等於當前 selected run、現任 fence/lease 有效。未完成時返回真實狀態；成功時返回聚合候選、配置、限制與精確 artifact/checksum/pointer。Node 每秒輪詢，單次工具最多等待約 30 秒（最後一次 HTTP 最多 10 秒），SDK turn 仍受總 timeout 限制；未完成不捏造結果。

窗口為 `(0,168]` 小時，最多 10 個且不重複。候選預算最多 2,000 且不得高於父 run 預算。門檻為最多 20 個正數、不重複；count/session_count 必須為整數，revenue_sum/engaged_seconds 可為小數，工程安全上限均為 1,000,000。`thresholds` 若提供，取代父配置中的整個門檻物件；未指定 metric 沿用內建固定網格／探索集收益分位數。搜尋產物以 `configured_grid` 記錄自訂網格來源。門檻設定不代表歷史驗證通過。

Node 使用真 Vercel AI SDK 工具迴圈與既有 OpenRouter adapter。測試模型只用於測試，正式執行不自動注入。工具 HTTP 回應最多 128 KiB、每次請求最多 10 秒；所有引用在加入最終答案 allowlist 前校驗作用域、artifact UUID、checksum 格式與合法 pointer。

工具 running/completed/failed 卡片按 turn/fence/call/name 持久保存，輪詢不重複新增同一狀態。完成卡保存子報告版本與引用；UI 使用它解析子報告證據，不默認套用父報告版本。跨分支的完整工作區狀態／版本操作仍需後续 UI 驗證。

取消 turn 時在同一 PostgreSQL 交易內取消所有未完成 child jobs，遞增 fencing token，關閉未完成 attempt；已發布子／父報告保留。交易故障整體回滾。Worker 透過既有 heartbeat 發現失去租約後停止運算子程序；tests/test_compute_tools.py 已驗實際分析管線中由 HTTP 取消 turn 後子程序終止及舊報告可讀。
