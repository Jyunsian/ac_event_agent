# V4 比較文案與概覽精簡

2026-09-17，已完成。本次只調整呈現，不更動統計、候選選擇或既有分析產物。

- 正式主表與 mock 直接標示七天平均收入比未符合玩家／收入門檻玩家高、低或相同；缺失值顯示無法比較，小於半美分的差異不誤寫相同或零。
- Holdout 詳情明寫比較方向，區間註明此行為減去比較人群。主表可靠性明列「比未符合玩家收入高」與「比收入門檻玩家收入高」兩個問題。
- 概覽移除教學、閱讀指引、取捨解說和重複段落，保留資料狀態、數值、圖表及按需明細。mock 更新至現有臨時通道。
- 主要檔案：web/src/v4-presentation.ts、web/src/report-v4.tsx、web/public/mock-v4.html；PRD.md、TECH_PLAN.md 同步需求。

驗證：npm run test:web-model 26 passed；web typecheck/build passed（保留既有大型 chunk 警告）。正式 UI 以既有真實計算產物及 API fixture 檢查 1440／390px、三群、時間切換、詳情與頁籤；mock 三群乘六個時間點、明確比較文字、無 JS 錯誤及無頁面溢出皆通過。桌面 screenshot 已檢視。證據 .runtime/v4-copy-review/。公開臨時 URL HTTP 200，非部署；沒有重跑分析或改寫舊報告。
