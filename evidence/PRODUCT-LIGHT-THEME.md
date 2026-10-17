# 全產品 demo 淺色配色

2026-09-24 使用者明確要求整個產品顏色對標 demo。

## 修改

- `web/src/style.css`：全域 light color-scheme 與共用背景／面板／正文／次要文字／連結／狀態色，涵蓋所有路由及首屏空白／載入狀態。
- `web/src/v4-report.css`：移除 V4 條件式工作區配色，保留 V4 布局。
- `web/src/chat-panel.css`：聊天文字、工具記錄、引用、輸入框與狀態使用全域色彩。
- `web/src/report-panel.css`：舊版報告強調文字及候選抽屜採淺色。
- `web/src/chart-renderer.tsx`、`chart-model.ts`、`candidate-revenue.tsx`：圖表座標、網格、提示框與系列顏色對齊淺色。

## 驗證

- `npm run build --workspace web` 通過。
- `npm run test:web-model`：27 項通過。
- `.runtime/product-light/check.cjs`：本地 build 配合正式 API，1440px／390px 的首頁、上傳、歷史、舊版 hand 範例、任務狀態、V4 正式合成報告共 12 個頁面／尺寸組合通過。另切換候選／圖表／資料品質及手機對話，所有路由共用 light palette，無頁面橫向溢出、無瀏覽器例外。
- 已視覺檢查上傳桌面、首頁手機、舊版範例桌面截圖。此輪不重新執行資料上傳或耗時分析；舊版本採既有 hand 範例檢查，不冒稱所有歷史 run 逐一重驗。
- 產物及截圖：`.runtime/product-light/`。此輪不改分析資料、計算或封存報告。

## 部署

Railway web 已更新成功，部署 `de9ee6bc-12cb-408f-b6ce-53e6fc1b4dbd` 為 SUCCESS。

`LIVE=1 node .runtime/product-light/check.cjs` 正式網址複驗通過：六路由 × 桌面／手機、報告頁籤及聊天輸入區，全站淺色、無溢出與瀏覽器例外。見 `live-check.json` 和 `live-*.png`。

正文、次要文字、連結、錯誤、成功、警告色在 #f6f7f9 背景的計算對比為 13.29／5.03／6.12／6.77／5.61／6.21，均超過 4.5；此為指定色對驗證，不宣稱完整無障礙認證。
