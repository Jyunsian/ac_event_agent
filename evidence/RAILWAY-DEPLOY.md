# Railway 首次部署

2026-09-17：部署與本輪技術驗收 passed，待使用者實際使用確認。共享密碼、新工作區＋合成示範、月費目標 US$50（不含模型）、AI 已啟用。此結論不涵蓋真客戶資料品質、投放效果或長期月費保證。

## 實際服務

- AC Event Agent：`dc58eb6f-bd60-42a2-9135-5ea95b028a35`；production：`5b35b2a1-b283-4688-80c6-385c8cbd697d`。
- 正式入口：`https://web-production-ac81b.up.railway.app`；只有 web 有公開 domain。API、worker、agent、Postgres、backup 經私有網路，所有服務新加坡，Bucket sin。既有其他 Railway 專案未更動。
- 正式 DB `ac_event`，只載入一份 1,200 玩家／60,000 事件的合成分析。沒有搬移原本本地歷史或客戶資料。
- Demo run `8163c4ff-85a1-4808-9793-4ceadd440c2b`，report v1 SHA-256 `32934e33c35aff7edcb9fb1c83ee06578d9188828fb15bfcd9a318f463e2490d`。
- 私密檔集中 `.runtime/railway-deploy/private`，未放入發布包。登入資料另存權限 600 的 `登入資料.md`，不可公開整個 private 目錄。

## 已取得證據

- Railway Bucket：immutable put/get、禁止覆寫、multipart create/list/upload/complete、SHA-256 驗證通過。CORS 限正式 origin。`storage-check.json`。
- 真瀏覽器直接上傳兩份 CSV，封存資料並啟動 V4。工作中重啟 worker，attempt 2 恢復 normalized/quality/targets/exploration_features 檢查點，最終 succeeded。`demo-view.json`。
- 上傳首段後中斷、重啟 API、resume 只傳缺少段，complete 校驗通過。`upload-resume-result.json`。該未封存測試資料集不產生第二份分析。
- API、Agent 重啟／更新後，既有 run/report/conversation 都持久保存；正式報告數字不重算。
- 真 OpenRouter `z-ai/glm-5.3-flash` 已完成資料摘要、24/48 小時新增人群、Holdout 問答。發現模型混淆整條規則與單一時間點的驗證狀態，補強 runtime 指示後重新詢問成功；保留原始失敗回答，不把第一次測試寫成通過。`chat-events.json`、`chat-state.json`。
- 每日 UTC 19:00（UTC+8 03:00）備份，7 日保留。手動觸發同一 backup service 產生 `database-backups/production/20260917T132957Z.dump`，237,449 bytes，SHA-256 `2a2b6a2da9a00f3a807c1b1afcb440c774690f4ec6ab7b71e52aec9c30e34787`。
- 從此 S3 備份還原至獨立 `ac_event_restore_check`：33 個資料表、1 份成功分析、report SHA 一致。未覆写 production。`restore-result.json`。未宣稱已跨日觀察自動排程。

## 容量

測試在同一雲端 worker、獨立 `ac_event_acceptance` DB 執行。資源不變：RSS 1536 MiB、DuckDB 256 MiB、2 threads、CPU 600 秒、wall 900 秒、工作目錄 4 GiB、reserve 2 GiB。1,000 次重抽樣、每組至少 100 人、六個時間點完整保留。

- 標準 seed 42：100,000 事件、20,000 基本規則、2,000 正式比較；通過。wall 424.15 秒、CPU 396.84 秒、峰值 RSS 1,303,228,416 bytes。人數、零事件玩家、成熟玩家、D7 收入與獨立真值一致。
- 集中 seed 43：分析成功，同樣真值對帳通過，但正式比較為 1,996，未達本輪 2,000 驗收值，保留為未通過容量條件。wall 475.04 秒、CPU 332.88 秒、RSS 1,257,009,152 bytes。沒有刪掉比較或減少重抽樣。
- 集中 seed 44：100,000 事件／20,000 基本規則／2,000 正式比較，通過。wall 349.00 秒、CPU 327.01 秒、RSS 1,295,826,944 bytes，真值對帳全數通過。前兩次保存在 `capacity-results.json`，補驗另存 `capacity-extra-results.json`，不覆蓋失敗證據。

## 雲端驗收發現與修正

1. Web Dockerfile 原本只複製舊 contracts，補齊 V4 contracts。
2. Nginx 非 root 的暫存目錄改 /tmp，共享密碼保護頁面及 API，/internal 拒絕，/healthz 只回存活狀態。
3. Agent 的 PORT 與 AGENT_PORT 均設 8081，修正部署健康檢查。
4. Railway gzip 將 ETag 改為 `W/` 格式。Web 現接受同一 SHA 的強／弱 ETag，仍逐位元組校驗，不放寬缺失或錯誤內容。
5. 完整 CSV 16,830,511 bytes、HTML 33,271,556 bytes、discovery 115,920,810 bytes 超出 16 MiB get_bytes 限制。新增先校驗暫存檔再串流的匯出路徑，主 JSON 限制維持。大檔與損壞資料測試通過。
6. Nginx startup 解析 API 舊位址造成後端換版後 504；改用容器 DNS resolver、10 秒解析快取。再次部署 API 後，web 部署 ID 不變，正式網址仍可讀取原報告且 SHA 一致。`dns-redeploy-check.json`。
7. V4 優先清單切換時間不再預先抓完整候選頁；Agent 明確按單一時間點的 d7_association 解釋 Holdout。

本地驗證：26 項前端模型測試、25 項 Agent 測試、5 項 report API 測試通過；Web/Agent build 通過。Vite 仍有 chart chunk 大於 500 kB 警告；Python 測試有既有 Starlette/httpx 與 anyio deprecation 警告。

## 發布與費用

CLI 5.57.7 隔離安裝；舊 CLI 4.27.5 與目前區域 API 不相容。非 TTY environment edit 優先讀 stdin，不把 No changes to apply 當成功；設定以已查 schema 的官方 GraphQL 套用。Config as Code API 目前拒絕 railwayConfigFile，本地 JSON 僅為設定參考，非自動發布設定。

發布採 allowlist，原始碼與來源資料不覆寫。操作文件見 `docs/RAILWAY_OPERATIONS.md`。所有驗收原始證據位於 `.runtime/railway-deploy`；不可將其中 private 子目錄上傳／分享。

本專案讀到累計基礎設施用量 US$0.077（驗收中途快照，帳單有延遲）；不是月費預測。US$50 是目標而非已保證價格，未改 workspace 上限以免影響其他專案，模型另計。`usage.json`、`metrics.json`。

## 最後整合證據

- 正式網址桌面 1440×1000／手機 390×844 通過；全量／找規律／Holdout × 六個時間點共 18 組人數與產物相符。明細、手機切換對話／結果可用，無頁面整體水平溢出與 pageerror。表格自身保留橫向捲動。`browser-acceptance.json`、`production-desktop.png`、`production-mobile.png`。
- 正式 JSON／CSV／HTML／完整搜尋 JSON 全數下載成功，各自 SHA-256 與已保存產物一致；未登入 401、internal 404、healthz 200。`download-check.json`。
- CSV 3,042 列；優先十規則 × 三群 × 六時間點，共 180 組與報告的符合人數及平均收入一致。`export-consistency.json`。下載完成後 API 無遺留 ac-report-download 暫存目錄。
- 額外回歸：`pytest tests/test_report_delivery.py tests/test_v3_backward_read.py -q`：4 passed，包含下載後離線開啟與舊報告不變，2 項既有 deprecation warnings。
- 發布 allowlist 189 檔案，沒有 .env、.runtime、CSV／Parquet 客戶來源檔。`release-review-manifest.json`。實際部署 ID 記錄於 `deployment-ids.json`。
