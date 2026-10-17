# AC Event Agent — 專案協作規範

## 專案定位

本目錄為獨立的 IAA 候選廣告事件分析專案，不是父目錄描述的 JTBD skill／job-library 專案；不建立那些專案的 corpus 或流程。

閱讀 PRD.md 作為產品需求基線，TECH_PLAN.md 作為技術選型規劃。以使用者最新明確指示為準；修改需求時同步文件，區分已確認決策與提案。

既有平台執行歷史以 IMPLEMENTATION_PLAN.md 的 PH01–PH42 為準；Candidate Event V3 以 `docs/CASUAL_GAME_CANDIDATE_V3_IMPLEMENTATION_PLAN.md` 的 CG01–CG06 為準。UI 位於 TECH_PLAN.md 第 12 節。先讀 PHASE_STATUS.md 及對應 evidence，再繼續工作；EXTERNAL_CHECKS.md 單獨追蹤外部驗證。

## 目前階段

### Candidate Event V4 — 目前工作方向

- 使用者於 2026-09-17 授權實作完整 V4；需求與階段基線為 `docs/CANDIDATE_V4_IMPLEMENTATION_PLAN.md`，只以 PHASE_STATUS.md 與 evidence/V4-xx.md 判斷完成範圍。
- 保留 D7 累積廣告收入，不加入 ML；區分累積首次達標、指定時間判斷、連續 24 小時滾動，固定比較 24/48/72/96/120/144h。
- 報告分開全量描述與另一批用戶驗證，不選唯一最佳期限，不將多辨識到的收益寫成投放提升。
- V4 獨立版本、快取與產物；V3 CG06 保持 closed_partial，舊版本報告不可改寫。2,000 上限按正式比較單位計算，不能把六個時間點算一次。

### Candidate Event V3 — 歷史基線

- 2026-09-11 使用者指示先不處理 V2，改為規劃 Candidate Event V3 implementation plan。V3 需求基線見 `docs/CASUAL_GAME_CANDIDATE_V3_PLAN.md`，執行與驗收基線見 `docs/CASUAL_GAME_CANDIDATE_V3_IMPLEMENTATION_PLAN.md`。
- V3 CG01 不以前述 CV05 passed 為前置；後續 Goal 依 CG01–CG06 順序執行並保存 `evidence/CGxx.md`。
- V3 仍沿用既有本地平台基礎，但必須有獨立 analysis version、AST、artifact、calculation/pipeline identity；舊 run、舊報告與 cache 不可改寫或混用。
- 72h 互動圖只納入 72h 前可完整判定 membership 的候選；晚期候選保留於完整結果與證據卡，不用未來行為替過去分組。

### Candidate Event V2 歷史資訊（目前暫不處理）

- 使用者已批准 Candidate Event V2 算法與呈現計畫，見 docs/CANDIDATE_V2_PLAN.md；Goal Card 見 docs/CANDIDATE_V2_GOAL.md。本次文件交付不表示 V2 已實作或驗收，後續依使用者下達的 /goal 執行並逐階段留證。
- 固定起點窗口：從每批資料已定義的安裝／首次開啟時間開始，僅在前 W 小時累積，首次達標回傳一次；D7 是收益衡量期間，不是所有候選共同的達標期限。UI 必須明寫起點，不能只寫「6 小時內」。
- **提醒使用者後續討論滾動窗口設計**：例如「首次開啟後 7 天內，任意連續 6 小時廣告展示達 3 次」。這與「首次開啟後前 6 小時達 3 次」不同。本輪 V2 只記錄待辦，不實作滾動窗口；未來需先固定滑動區間端點、觀察終點、首次達標／重複回傳、累積收益時間語意及新搜尋預算。下次討論窗口擴充時主動提出此提醒，不因此阻擋本輪 V2。
- V2 沿用事件級 CSV／用戶表，維持純 IAA；所有來源合併分析且保留探索／驗證時間切分。累積廣告收入是主要搜尋方向之一。完整 D7 為主指標，剩餘收益為診斷，不因 D6 剩餘時間短而淘汰。
- 客戶同時取得少數優先比較候選與全部實際評估結果，包含樣本不足、不支持及相似替代項；搜尋預算外條件須標未評估，不宣稱無限窮盡。

2026-09-09最新使用者決策：測試模型先用OpenRouter `z-ai/glm-5.3-flash`；正式目標為前端Vercel、後端Railway。先完成測試，再部署；現在不要建立雲端服務。後端包含FastAPI、Python Worker與Node Agent Worker，不能把背景分析搬到前端。PostgreSQL／S3供應商與區域尚未指定。原Compose是已驗證本地部署包，不是新的雲端目標；上雲前需適配並驗證平台網路／持久性／私密入口。

PH01–PH42 是既有平台交付歷史。Candidate Event V4 是目前工作方向；技術與 UI 基線見 TECH_PLAN.md，V3 實際完成範圍只以 PHASE_STATUS.md 及 `evidence/CGxx.md` 為準，不把規劃寫成已實作。

使用者用 Goal 要求某階段或一段範圍，即為該範圍實作授權；不需再詢問是否開始。

## Phase 執行與交付

- PH 階段依既有 G1–G5 與 `evidence/PHxx.md`；V3 CG 階段依 V3 implementation plan 的 G1–G7 與 `evidence/CGxx.md`。前一階段 Gate 通過並更新狀態後才可開始下一階段。
- 單 Phase Goal 通過後停止；跨 Phase Goal 在門檻通過後自動繼續，無須每階段請使用者批准。
- 需要使用者帳戶、金鑰、雲端操作等，按對應 implementation plan 的外部項規則延期並記 EXTERNAL_CHECKS.md，完成可獨立驗證的實作；不要反覆索取。
- 不可將核心實作、資料庫／任務整合或測試失敗列為外部延期。mock 通過不是整合通過，未部署不可稱上線。
- 不以刪減驗收條件換取 passed；前階段回歸失敗先修復。Phase 證據必須對應實際檔案與命令。

## 範圍

- 目前 MVP 是 V4 時間與候選事件分析，沿用 Casual Game V3 的行為方向，以 D7 累積廣告收益為目標；變現範圍仍為純 IAA，但行為條件包含 Session、Retention、Level progress／friction、受控交叉與兩步序列。
- 支援小時級與天級候選，不擅自縮限為早期幾小時。
- Python 負責可重現分析；Agent 協調與解釋。
- 產品順序固定為上傳 → Python 基礎分析／首份報告 → Agent 對話及工具深入分析。首次分析不依賴 LLM；重跑保存分支，不覆蓋父報告。
- UI 固定左側對話、右側結果／圖表，布局參考 Claude Design、視覺參考 Linear；遵循 TECH_PLAN.md 第 12 節，不變成全螢幕聊天或三欄儀表板。
- 讀過 baseline 驗證結果後的 followup 預設探索狀態；跨對話沿用資料揭露紀錄，不宣稱同份資料可重新獨立驗證。
- Agent 採 Vercel AI SDK ToolLoopAgent（TypeScript）與 OpenRouter provider；Node.js Agent 經內部 API 接 Python 分析。不要再使用先前 Claude SDK 選型；分析工具、經驗庫與持久任務仍由本專案負責。
- 可部署的內部 Web 工具，不做登入、會員或角色系統；單一共享工作區。
- 資料、配置、任務與報告需持久保存；背景任務須可恢復，不能只存在 API 記憶體。
- ROI、IAP、即時 SDK、平台回傳及投放自動化不屬目前 MVP。
- 預設使用繁體中文溝通與寫產品文件，程式欄位可用英文。

## 資料與證據

- 保存原始資料，不覆寫或刪除客戶來源檔；衍生結果分開保存。
- 不將原始 log、個人資料或憑證提交版本控制。模型預設僅接收必要的聚合證據。
- 不把缺失收益當零，不遺漏零事件用戶，不把未滿 D7 的用戶補零。
- 只以當時可取得資料觸發候選；留意收益回傳延遲與日終排名。
- 探索與驗證分離；不可用驗證資料選門檻後宣稱獨立驗證。
- 相關性不等於投放提升。沒有投放實驗，不標示投放驗證通過。
- 報告所有數字必須來自可追溯的計算產物；示例與真實數據明確區分。
- 樣本不足或無可靠候選時如實輸出，不湊推薦數量。

## 工程約定

- 先檢查現有檔案與變更，保留使用者工作；不要擅自建立多租戶平台或大型框架。
- 計算層與 Agent 敘述分離；保存資料指紋、配置、版本及隨機種子（若有）。
- 有新套件、SDK 或平台能力主張時查官方來源，記錄選型依據。
- 技術方案比較需包含使用方式、資料量、成本、可重現性及維護負擔。
- 測試聚焦 D7／窗口邊界、去重、首次觸發、未來資料洩漏、驗證切分及報告數值一致性。
- 未建立執行環境前不宣稱測試通過；依實際建立的命令更新文件。
- 完成工作時交代修改檔案、驗證方式與待定問題。
