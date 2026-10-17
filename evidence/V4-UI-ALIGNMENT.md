# V4 正式介面與 demo 對齊

2026-09-24，使用者授權依正式版／demo review 優化。

## 修改

- `web/src/report-v4.tsx`：四張概覽卡、三群人數、六個時間按鈕、五欄表格、預設／點選詳情及清楚區分的匯出入口。
- `web/src/v4-report.css`：僅 V4 的淺色工作區、桌面五欄同時可見、手機行為卡片、聊天文字對比。
- `web/src/v4-export.tsx`：讀取既有聚合產物，與 Web 共用主表、概覽及時間詳情元件的離線閱讀版。範圍為優先比較行為；完整結果仍在原始匯出。18 組主表（三群 × 六時間點），每日新增明細三群各自呈現。沒有收入對照主表。
- `web/src/branch-picker.tsx`：頂部匯出使用相同閱讀版；V1–V3 維持原始 HTML 入口。
- `web/src/v4-presentation.ts`：無推薦候選時仍可從完整、無未知收益的成熟人群摘要取得概覽收入；不足時保持未知，不補零。
- `tests/v4-presentation.test.mjs`：檢查無候選、未知收入與母體不完整時的概覽結果。
- PRD、TECH_PLAN 同步界定閱讀版與完整原始產物的範圍。

## 本地驗證

- `npm run build --workspace web` 通過（typecheck + build）。
- `npm run test:web-model`：27 項通過。
- `.runtime/v4-ui-alignment/check.cjs`：本地 build 搭配正式 API 的真計算合成報告，1440px／390px；五欄主表無橫向溢出、三群切換、六時間點、預設詳情、完整目錄行為點選、離線匯出均通過，無瀏覽器例外。
- 10 個行為 × 三群 × 六時間點，共 180 筆主表的符合人數與七天平均收入，逐筆比對正式 JSON 通過。
- 離線 HTML 有 18 組比較表，無失效操作按鈕、無被移除的收入對照文案；所有內容由 React escape，不把資料拼入可執行 script。
- `desktop.png`、`mobile.png` 已視覺檢查；資料仍為 1,200 人合成示範，不代表客戶效果。

## 部署

Railway web 更新成功，部署 ID `e223e490-ddbb-48b8-8e47-65562e5d47f4`，狀態 SUCCESS。此次只發布五個前端來源檔，沒有更新後端或重新分析。

- `LIVE=1 node .runtime/v4-ui-alignment/check.cjs` 通過：正式網址 1440px／390px、三群、六時間點、目錄詳情、頂部與底部匯出；無瀏覽器例外，主表寬度 1009px 且無橫向捲動。
- Web 180 筆主表數字及離線 HTML 180 筆數字分別比對既有 report JSON，符合人数與七天平均收入一致；兩個匯出入口下載内容相同。離線檔約 491 KB。
- 原始 JSON、CSV、HTML、完整搜尋 JSON 的 SHA-256 與部署前完全相同。證據 `artifact-check.json`。
- 正式畫面 `live-desktop.png`／`live-mobile.png`，測試 `live-check.json`，發布檔雜湊 `release-files.json`，部署狀態 `deployment.json` 均位於 `.runtime/v4-ui-alignment/`。
- 正式入口：https://web-production-ac81b.up.railway.app/workspace?run=8163c4ff-85a1-4808-9793-4ceadd440c2b&tab=概覽

此輪是呈現驗收，不重跑容量或宣稱新的分析／投放驗證。V1–V3 分析產物未修改。
