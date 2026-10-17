# V4 兩位小數呈現

2026-09-24 使用者要求小數收到後兩位。

修改 `web/src/v4-presentation.ts`、`report-v4.tsx`、`v4-export.tsx` 及 mock 百分比。V4 網頁／閱讀版 HTML 共用兩位小數格式；人數保留整數、缺失仍未知、極小非零值不冒充零。規則名稱的顯示近似值標「約」，精確條件與原始產物保持不變。V1–V3 formatter 未修改。

驗證：web build、27 項前端測試及格式邊界直接斷言通過。本地 build 使用正式 API，桌面／手機、三群六時間、180 筆網頁及 180 筆 HTML 人數與收入（顯示捨入容許 0.005）、兩處匯出相同、無瀏覽器例外。證據 `.runtime/v4-two-decimals/`。

Railway web 已更新成功：`1060c195-79ee-4a88-8dad-b01d601789cc`（SUCCESS）。`LIVE=1 node .runtime/v4-two-decimals/check.cjs` 正式站複驗通過：桌面／手機、三群六時間、網頁與匯出數字、兩處匯出一致、無瀏覽器例外。見 `live-check.json` 與 `deployment.json`。
