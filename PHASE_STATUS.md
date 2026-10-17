# Phase 執行狀態

Railway 首次部署與技術驗收：passed，待使用者使用確認。正式入口、真 AI、持久性、備份還原及標準／集中 100k／20k／2k 驗收見 evidence/RAILWAY-DEPLOY.md。先全 Railway，日後可移動前端至 Vercel；費用目標不等於月費保證。V3 CG06 歷史狀態不變。

## Candidate Event V4

2026-09-24 全產品 demo 淺色配色：已部署 Railway，六路由桌面／手機及各報告頁籤複驗通過；見 evidence/PRODUCT-LIGHT-THEME.md。

2026-09-24 兩位小數呈現：已部署 Railway 並完成正式站複驗；原始計算精度不變。見 evidence/V4-TWO-DECIMALS.md。

2026-09-24 正式介面與 demo 對齊：passed，已部署 Railway；桌面／手機、180 筆 Web 與離線閱讀版數字核對、原始產物雜湊均通過。見 evidence/V4-UI-ALIGNMENT.md。

平均達標時間與 Holdout 白話呈現：已完成，見 evidence/V4-TIME-COPY.md；舊報告缺平均值不推估。

收入門檻比較呈現移除：已完成，正式 Web 與 mock 已驗證；計算與既有產物保留。見 evidence/V4-REMOVE-CONTROL-UI.md。

比較文案與概覽精簡：已完成；方向、比較人群與缺值狀態明確，正式 UI／mock 桌面手機通過。見 evidence/V4-COMPARISON-COPY.md。

後續 demo／程式 review 修復：passed；首次達標／第一天比較、三群 Web／Agent／匯出、圖表頁籤與 demo 一致性已修正；相關回歸、桌面／手機、一般及集中分布 100,000／20,000／2,000 容量均通過。原階段歷史不改寫，本次證據見 evidence/V4-REVIEW-FIXES.md。

依使用者 2026-09-17 授權進行；基線 `docs/CANDIDATE_V4_IMPLEMENTATION_PLAN.md`。

| 階段 | 狀態 | 證據 |
|---|---|---|
| V4-01 | passed | evidence/V4-01.md |
| V4-02 | passed | evidence/V4-02.md |
| V4-03 | passed | evidence/V4-03.md |
| V4-04 | passed | evidence/V4-04.md |
| V4-05 | passed | evidence/V4-05.md |
| V4-06 | passed | evidence/V4-06.md |

## Candidate Event V3 — Casual Game

2026-09-11：依使用者最新指示，V3 依 `docs/CASUAL_GAME_CANDIDATE_V3_IMPLEMENTATION_PLAN.md` 實作；V2 CV05 暫不作為工作前置或阻塞。CG01–CG05 已通過；CG06 核心 E2E 與固定容量通過，但使用者要求停止追加耗時回歸並收尾，故以 `closed_partial` 如實結案，不標 passed。

2026-09-11 後續產品決策：V3 主表改用全部成熟玩家呈現「本批觀察」；既有 exploration→freeze→holdout 邊界保留，但 holdout 降為額外重現徽章，樣本不足不再抹掉全量描述。實作與驗證見 `evidence/V3-DESCRIPTIVE-HOLDOUT.md`。

| Phase | 工作 | 狀態 | Gate 證據 |
|---|---|---|---|
| CG01 | V3 資料合約與手算真值 | passed | evidence/CG01.md |
| CG02 | 多元特徵與首次判定 | passed | evidence/CG02.md |
| CG03 | Discovery、去重、Category 預算與凍結 | passed | evidence/CG03.md |
| CG04 | Holdout 完整驗證與時間診斷 | passed | evidence/CG04.md |
| CG05 | V3 報告、完整匯出與 72h 最小互動圖 | passed | evidence/CG05.md |
| CG06 | 全流程回歸、恢復與 100,000 事件容量 | closed_partial | evidence/CG06.md |

## Candidate Event V2（歷史狀態，目前暫不處理）

使用者已下達 CV01–CV05 Goal；本表為新版狀態，以下原 PH／語言交付歷史保持不變。

| Phase | 工作 | 狀態 | Gate 證據 |
|---|---|---|---|
| CV01 | 版本合約與手算真值 | passed | evidence/CV01.md |
| CV02 | 搜尋與多維選擇 | passed | evidence/CV02.md |
| CV03 | 整批驗證與診斷 | passed | evidence/CV03.md |
| CV04 | 證據卡與完整交付 | passed | evidence/CV04.md |
| CV05 | 整合與容量 | in_progress | evidence/CV05.md（尚待完整 Gate） |

## 原交付歷史

更新日期：2026-09-09。來源：IMPLEMENTATION_PLAN.md。規劃完成不等於 Phase 完成。

2026-09-10 語言體驗改造 Goal 的L01–L05交付門檻通過，見 docs/LANGUAGE_PLAN.md、docs/LANGUAGE_AUDIT.md及evidence/LANGUAGE-L05.md。包含247項全套回歸、最後改動局部回歸、真GLM五情境與白話短回覆、桌面／手機驗收。以下 PH01–PH42 保留原始歷史；本次亦未部署雲端。

當前：PH01–PH42 全部本地交付門檻通過。真模型、雲端、真客戶資料與更高容量的外部補驗另見 EXTERNAL_CHECKS.md；未宣稱正式上線。

| Phase | 工作 | 狀態 | Gate 證據 |
|---|---|---|---|
| PH01 | 資料與驗收合約 | passed | evidence/PH01.md |
| PH02 | 專案與開發命令 | passed | evidence/PH02.md |
| PH03 | 可手算合成資料 | passed | evidence/PH03.md |
| PH04 | PostgreSQL 與版本模型 | passed | evidence/PH04.md |
| PH05 | 物件儲存介面 | passed | evidence/PH05.md |
| PH06 | 持久任務與租約 | passed | evidence/PH06.md |
| PH07 | 上傳 API | passed | evidence/PH07.md |
| PH08 | CSV／Parquet 正規化 | passed | evidence/PH08.md |
| PH09 | 品質與能力檢查 | passed | evidence/PH09.md |
| PH10 | D7 目標與成熟用戶 | passed | evidence/PH10.md |
| PH11 | 累積特徵與可用時間 | passed | evidence/PH11.md |
| PH12 | 原子條件與 AND／OR | passed | evidence/PH12.md |
| PH13 | 有限行為序列 | passed | evidence/PH13.md |
| PH14 | 候選搜尋與剪枝 | passed | evidence/PH14.md |
| PH15 | 歷史驗證與證據狀態 | passed | evidence/PH15.md |
| PH16 | 重疊與敏感度診斷 | passed | evidence/PH16.md |
| PH17 | Python baseline 管線 | passed | evidence/PH17.md |
| PH18 | 第一份報告與匯出 | passed | evidence/PH18.md |
| PH19 | Linear 風格雙欄 Shell | passed | evidence/PH19.md |
| PH20 | 上傳與欄位映射 UI | passed | evidence/PH20.md |
| PH21 | 分析進度與歷史 UI | passed | evidence/PH21.md |
| PH22 | 結果表與證據詳情 | passed | evidence/PH22.md |
| PH23 | 分析圖表 | passed | evidence/PH23.md |
| PH24 | 響應式與可及性第一輪 | passed | evidence/PH24.md |
| PH25 | 對話與 Turn 持久模型 | passed | evidence/PH25.md |
| PH26 | AI SDK 與 OpenRouter 接口 | passed | evidence/PH26.md |
| PH27 | Agent 唯讀工具 | passed | evidence/PH27.md |
| PH28 | 左側 Agent 對話 UI | passed | evidence/PH28.md |
| PH29 | 驗證揭露與污染防線 | passed | evidence/PH29.md |
| PH30 | 分析分支與快取 | passed | evidence/PH30.md |
| PH31 | 重跑窗口與門檻工具 | passed | evidence/PH31.md |
| PH32 | 分群深入分析工具 | passed | evidence/PH32.md |
| PH33 | 自適應探索與停止 | passed | evidence/PH33.md |
| PH34 | 新結果與版本連動 | passed | evidence/PH34.md |
| PH35 | 同 App 經驗庫 | passed | evidence/PH35.md |
| PH36 | Agent 恢復與工具重放 | passed | evidence/PH36.md |
| PH37 | 報告版本與客戶交付 | passed | evidence/PH37.md |
| PH38 | 完整產品流程回歸 | passed | evidence/PH38.md |
| PH39 | 全系統故障與備份還原 | passed | evidence/PH39.md |
| PH40 | 容量測試與限制 | passed | evidence/PH40.md |
| PH41 | 部署包與本地正式演練 | passed | evidence/PH41.md |
| PH42 | 最終交付與發布就緒審核 | passed | evidence/PH42.md |
