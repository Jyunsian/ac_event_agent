# 全量、找規律、Holdout 三個視角

2026-09-17 使用者要求三個都列出。正式 Web 主表與規則明細提供三個具名切換，顯示本群體人數及用途。Holdout 證據欄保持只引用驗證集；不把探索數字當驗證。

`v4_validation.py` 新增探索集的獨立 describe 計算，含首次達標分布、每天新增、固定收入對照與 rolling 的累積對照。未改門檻、搜尋清單或統計決策。`v4_report.py` 新產物包含第三群體，CSV 每規則從 12 列改為 18 列，HTML／JSON 同步。舊產物不回寫；若沒有探索明細，Web 保持未知並提示建立新版分析，不由全量相減推算中位數。

分頁 API 只傳當前時點的三群明細；全時間陣列與完整對照仍剝除。Agent 的有界聚合讀取保持原契約，未新增探索集工具參數。

Mock 三群為 10,000／7,000／3,000 人；探索人數與收益使用全量減去示意 holdout，保證相加可對帳。所有資料與推論標示示意。

驗證：
- 首輪搜尋／報告與 pipeline 測試 14 passed、1 failed：唯一失敗是 CSV 測試仍預期兩群 12 列。改為三群 18 列並增加分群人數／收益對帳後，`tests/test_v4_search_validation.py` 10 passed（11.36s），沒有放寬計算斷言。首輪已通過的 5 個 pipeline 測試包含真服務與恢復。
- `tests/v4-presentation.test.mjs`：3 passed，確認指定群體缺資料時不回退至全量。
- Web build 通過；既有圖表 bundle 警告保留。
- Mock 桌面／手機三群與 24／48h 互動通過，無頁面橫向溢出或 JS 錯誤，截圖 `.runtime/v4-three-groups-qa/`。
- 正式三群合成計算 fixture：`.runtime/v4-three-cohort-fixture/report`，非手填正式報告。

本次未重跑大型容量；前次容量證據仍只對應先前 pipeline identity。

補充完成驗證：
- 48h API 三群對帳及 Agent／匯出讀取：單獨測試 1 passed，9.31s。
- `npm run test:web-model`：24 passed。
- 正式 ReportPanel 三群 fixture：1440／390px，探索集人數切換、Holdout 切換及既有六時點檢查通過。
- Cloudflare 公開頁 HTTP 200，探索切換顯示 1,260 位符合玩家（24h），手機無頁面溢出；連結為臨時示意頁。
