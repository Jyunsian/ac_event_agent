# Implementation Plan — 可逐階段交付的 Goal 任務

版本：1.0｜日期：2026-09-09｜狀態：執行規劃基線；實際進度見 PHASE_STATUS.md 與 evidence/

## 1. 執行基線

需求以 PRD.md 為準，技術以 TECH_PLAN.md 為準，UI 以 TECH_PLAN.md 第 12 節為準。本文件把原本 P0–P5 大里程碑細拆成 PH01–PH42，取代它們作為日常執行編號；不擴張 MVP 範圍。

固定體驗：上傳 → Python 基礎分析與第一份報告 → 左側 Agent 對話、右側結果 → 工具深入分析與版本分支。Vercel AI SDK＋OpenRouter，Python／DuckDB，PostgreSQL／S3；無登入、會員或多租戶。

42 個 Phase 按順序執行，一個 Phase 是一個可驗收單元，不是一天或一次模型回合。大目標可以連續完成多個 Phase，但前一個硬門檻通過才能開始下一個。僅要求單一 Phase 的 Goal 完成後停止，不自行開始下一 Phase。

## 2. Gate 與完成定義

每個 Phase 的 C1–C3 都是硬門檻，加上以下共同條件 G1–G5；不可由 Agent 自行刪減或改成 soft requirement：

- G1：本階段交付內容已在真實檔案中實作。只寫計畫、stub、TODO 或假成功回應不算。
- G2：執行本階段相關驗證，保存命令、退出碼、觀察值及產物連結；不宣稱未執行的測試通過。
- G3：改動涉及前階段契約時跑受影響回歸，修正失敗；不必每階段重跑無關全套。
- G4：不覆寫使用者資料、不改變已確認範圍，模型 key／客戶原始 log 不提交版本控制。
- G5：更新 PHASE_STATUS.md 與 evidence/PHxx.md，逐條對應 Criteria。後續 Goal 先讀證據及目前程式，遇到漂移先修復。

狀態只有 pending／in_progress／passed／blocked。passed 表示本地硬门檻通過，外部驗證狀態另外保存；有延期外部驗證不代表已正式上線。

前置：PH01 無；PH02–PH42 各要求所有較早 Phase passed。若指定較後 Phase 而前置未通過，先讀現況，列出缺失；除非 Goal 授權補做前置，不跳關或悄悄做整個專案。

## 3. 需要使用者操作的項目

按使用者指示，缺 key、帳戶、真資料或雲端操作時先延期，不反覆停下索取。做完可以獨立完成的程式與本地驗證，留下 EXTERNAL_CHECKS.md 的項目與確切重跑方式。

- X01：OpenRouter 真 API／實際模型多輪工具調用。先用 SDK 相容測試模型驗證整合，不替換正式 adapter。
- X02：真 AWS S3／託管 PostgreSQL 帳戶、權限及網路設定。先用真本地 PostgreSQL 和 S3 相容服務，不只用記憶體 mock。
- X03：正式雲端資源、DNS、TLS、入口網路設定。交付可執行部署包並本地演練，不購買資源或聲稱已部署。
- X04：若現有機器資源不足，延期 1000 萬事件容量測試；10萬／100萬的本地功能容量仍需實測。
- X05：真客戶 log、收益來源／完整期確認、真投放成效驗證。以合成資料驗證功能，不以合成結果宣稱商業效果。

只有這些外部操作可延期。核心演算法、UI、持久儲存、跨程序恢復與測試失敗不能列成「等使用者」跳過。缺本地 runtime 時可在授權範圍內配置隔離工具；若一定需要使用者啟動系統服務且沒有可行替代，誠實 blocked，不能以 mock 當整合完成。

如果既有環境已有所需設定且任務授權允許，執行相應外部測試並更新證據；不掃描無關憑證或輸出秘密。真外部驗證有成本／資料外傳時依當時授權範圍執行。

## 4. Goal 用法

完整跨 Phase 任務稿與交付總覽見 GOAL_PLAN.md；本文件保留每個 Phase 的權威驗收條件。

本輪不啟動任何 Goal。之後可在輸入框使用 /goal 並貼入下列文字；這些是任務描述，不假定斜線指令有其他參數格式。

### 一次完成一個 Phase

每節附有獨立 Goal 文字。每個 Goal 都必須讀本文件第 1–3 節，據此判定何時完成及如何處理外部項。

### 連續執行多個 Phase 的 Goal

> 依 IMPLEMENTATION_PLAN.md，從第一個尚未 passed 的 Phase 開始，依序完成 PH01–PH42。每一階段全部 C1–C3 與共同 G1–G5 通過、保存 evidence 並更新 PHASE_STATUS.md 後，才能进入下一階段。只延期第 3 節定義的使用者／外部操作，記入 EXTERNAL_CHECKS.md；不要把核心失敗當延期。遵循 AGENTS.md、PRD.md 與 TECH_PLAN.md 的技術/UI範圍。完成所有本地門檻後交付發布就緒報告，清楚列出真模型、雲端、真資料及容量仍未驗證的項目；不將延期項稱為已完成或已上線。

## 5. 階段索引

| 範圍 | 可交付里程碑 | 對應 TECH 大階段 |
|---|---|---|
| PH01–PH03 | 合約、環境、真值資料 | P0 |
| PH04–PH09 | 持久性、上傳與資料整理 | P1 |
| PH10–PH18 | 不依賴 LLM 的完整基礎報告 | P2 |
| PH19–PH24 | Linear 風格結果工作區 | P2 UI |
| PH25–PH28 | 持久 Agent 對話與唯讀工具 | P3 |
| PH29–PH37 | 可恢復的深入分析與交付 | P4 |
| PH38–PH42 | 回歸、容量、部署與交接 | P5 |

## PH01 — 資料與驗收合約

前置：無。來源：TECH §6–8；PRD §5–8。

目標：固定資料、候選 AST、artifact、run、chart schema，明定 baseline 與 followup 邊界。

交付：contracts/、docs/decisions.md、需求追蹤矩陣。

### Delivery Criteria

- C1：列出合法／非法輸入及預期結果；UTC、[0,168h)、零值／缺值、收入延遲與首次觸發有明確規則。
- C2：確定 baseline 預設窗口、候選上限、統計判定和最低樣本的可配置初值；小合成資料可測計算但不可假裝達到實證樣本門檻。
- C3：每個 PRD／UI 要求對應後續 Phase；未定工程小選擇寫入決策，不停等使用者。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH01.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH01「資料與驗收合約」：固定資料、候選 AST、artifact、run、chart schema，明定 baseline 與 followup 邊界。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH01.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH01，通過後交付結果，不自行開始下一 Phase。

## PH02 — 專案與開發命令

前置：PH01–PH01 全部 passed。來源：TECH §2、§10。

目標：建立 React/Vite、FastAPI、Node Agent 三個可啟動骨架與統一檢查入口。

交付：web/、server/、agent/、鎖檔、README。

### Delivery Criteria

- C1：乾淨安裝後前端 build、Python import／health、TypeScript typecheck 通過。
- C2：README 記錄實際可執行命令；環境範例不含真密鑰，缺模型 key 不阻擋啟動。
- C3：正式程式尚未實作的功能不以成功回應冒充；不加入登入或會員。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH02.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH02「專案與開發命令」：建立 React/Vite、FastAPI、Node Agent 三個可啟動骨架與統一檢查入口。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH02.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH02，通過後交付結果，不自行開始下一 Phase。

## PH03 — 可手算合成資料

前置：PH01–PH02 全部 passed。來源：PRD §11。

目標：建立可重現的小型真值資料，以及分批生成大資料的工具。

交付：tests/fixtures/、fixture generator、expected results。

### Delivery Criteria

- C1：涵蓋零事件、零收益、缺值、亂序、重複、未成熟用戶、同時間事件與收益延遲。
- C2：expected results 由獨立手算紀錄定義，不由受測計算函式產生。
- C3：同種子輸出同 hash；資料明示 synthetic，生成器不覆蓋來源檔。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH03.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH03「可手算合成資料」：建立可重現的小型真值資料，以及分批生成大資料的工具。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH03.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH03，通過後交付結果，不自行開始下一 Phase。

## PH04 — PostgreSQL 與版本模型

前置：PH01–PH03 全部 passed。來源：TECH §6。

目標：建立專案、dataset、run、job、artifact、report 的持久模型與隔離測試資料庫。

交付：migrations/、repository 層、DB 整合測試。

### Delivery Criteria

- C1：真實本地 PostgreSQL 上 migration 可從空庫執行；重啟服務後紀錄保留。
- C2：run 綁不可變 dataset／config 版本，非法 parent 或 artifact 關聯被拒绝。
- C3：交易回滾無半套紀錄；測試不使用 SQLite 代替 PostgreSQL 行鎖語意。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH04.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH04「PostgreSQL 與版本模型」：建立專案、dataset、run、job、artifact、report 的持久模型與隔離測試資料庫。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH04.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH04，通過後交付結果，不自行開始下一 Phase。

## PH05 — 物件儲存介面

前置：PH01–PH04 全部 passed。來源：TECH §5、§9。

目標：建立 S3 API 存取與可在本地驗證的物件保存。

交付：storage adapter、本地 S3 相容測試服務、manifest。

### Delivery Criteria

- C1：本地服務真實完成 put/get/head，重啟後 hash 相同；不是只測 mock。
- C2：唯一 key 保存多版本，不覆寫原始資料；checksum 不依赖 multipart ETag 等同 MD5。
- C3：斷線／物件不存在回可辨識錯誤；真 AWS 權限/CORS 驗證列 X02。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH05.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH05「物件儲存介面」：建立 S3 API 存取與可在本地驗證的物件保存。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH05.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH05，通過後交付結果，不自行開始下一 Phase。

## PH06 — 持久任務與租約

前置：PH01–PH05 全部 passed。來源：TECH §6。

目標：完成 queued/running/terminal 狀態、領取、心跳、fencing 與取消。

交付：job repository、Python Worker、故障測試。

### Delivery Criteria

- C1：两個 Worker 競爭時同一 attempt 只有一個持有效租約；計算不持長 DB 交易。
- C2：殺掉 Worker 後過期任務可重領；舊 fencing token 無法提交結果。
- C3：取消、重試上限及重複 Idempotency-Key 行為通過；同 key 不同 payload 回 409。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH06.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH06「持久任務與租約」：完成 queued/running/terminal 狀態、領取、心跳、fencing 與取消。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH06.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH06，通過後交付結果，不自行開始下一 Phase。

## PH07 — 上傳 API

前置：PH01–PH06 全部 passed。來源：TECH §5、§10 HTTP。

目標：完成分段上傳、續傳、完成校驗與 dataset 封存。

交付：dataset/upload routes、multipart tests。

### Delivery Criteria

- C1：本地 S3 相容服務完成多 part 上傳；中斷只重傳缺少 part。
- C2：缺 part、錯大小或未知 upload 無法標為 ready；超限回 413。
- C3：已封存映射不可改，改動建立新版本；瀏覽器重選檔續傳先核對檔案指紋。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH07.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH07「上傳 API」：完成分段上傳、續傳、完成校驗與 dataset 封存。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH07.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH07，通過後交付結果，不自行開始下一 Phase。

## PH08 — CSV／Parquet 正規化

前置：PH01–PH07 全部 passed。來源：TECH §7。

目標：將多檔輸入按映射及固定型別轉成標準事件與用戶資料。

交付：analysis/ingest、標準 Parquet manifest。

### Delivery Criteria

- C1：CSV 和 Parquet 等價輸入產生相同標準值；跨檔事件依 app/event_id 去重。
- C2：同 ID 內容衝突、非法時間、無法串接有具體處置及數量，不任意挑一筆。
- C3：分批讀寫、來源 hash 不變；未完整寫出檔案不發布 manifest。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH08.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH08「CSV／Parquet 正規化」：將多檔輸入按映射及固定型別轉成標準事件與用戶資料。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH08.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH08，通過後交付結果，不自行開始下一 Phase。

## PH09 — 品質與能力檢查

前置：PH01–PH08 全部 passed。來源：PRD §5；TECH §7。

目標：產出可解釋的品質摘要並决定可執行分析方向。

交付：quality.json、dataset_profile.json、capability flags。

### Delivery Criteria

- C1：輸入／保留／排除／缺值數與 fixture 真值一致，零事件用戶仍保留。
- C2：核心收益資料無法使用時不產生正常推薦；Session 缺失只停相關工具。
- C3：API 與產物提供相同 capability flags，未知資料不填零或猜測。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH09.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH09「品質與能力檢查」：產出可解釋的品質摘要並决定可執行分析方向。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH09.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH09，通過後交付結果，不自行開始下一 Phase。

## PH10 — D7 目標與成熟用戶

前置：PH01–PH09 全部 passed。來源：TECH §7 統計。

目標：計算 D7 與時間切分，保留可回查的人群定義。

交付：targets、cohort/split manifest。

### Delivery Criteria

- C1：167:59:59 收益納入、168:00:00 排除；未成熟用戶排除但不補零。
- C2：ARPU 分母包含成熟零收益用戶；批次邊界及同用戶不跨集合。
- C3：改變 holdout 收益不改探索集目標或 split；批次不足回探索狀態。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH10.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH10「D7 目標與成熟用戶」：計算 D7 與時間切分，保留可回查的人群定義。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH10.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH10，通過後交付結果，不自行開始下一 Phase。

## PH11 — 累積特徵與可用時間

前置：PH01–PH10 全部 passed。來源：TECH §7。

目標：建立展示頻次、收益、Session、有效時長及首次達標所需特徵。

交付：features Parquet、feature manifest。

### Delivery Criteria

- C1：按時間累積與真值一致，小時及天級窗口均有輸出。
- C2：收益／時長只在可取得時使用；未知延遲標示限制，不回填更早觸發。
- C3：特徵 hash 含資料與定義版本；不用日級聚合猜小時級數值。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH11.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH11「累積特徵與可用時間」：建立展示頻次、收益、Session、有效時長及首次達標所需特徵。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH11.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH11，通過後交付結果，不自行開始下一 Phase。

## PH12 — 原子條件與 AND／OR

前置：PH01–PH11 全部 passed。來源：TECH §7 候選規格。

目標：實作受控 AST 的計數、收益、Session、時長與布林條件。

交付：predicate evaluator、trigger records。

### Delivery Criteria

- C1：所有原子與 AND/OR 測例輸出正確首次觸發時間及每人一次事件。
- C2：窗口右端排除、未知操作／錯型別／超深 AST 被拒絕。
- C3：加入未來 log 不改已發生觸發；有非單調修正收益時按既定規則處理。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH12.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH12「原子條件與 AND／OR」：實作受控 AST 的計數、收益、Session、時長與布林條件。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH12.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH12，通過後交付結果，不自行開始下一 Phase。

## PH13 — 有限行為序列

前置：PH01–PH12 全部 passed。來源：PRD §7；TECH §7。

目標：實作兩步順序、間隔與受限重複序列模板。

交付：sequence evaluator、序列真值測試。

### Delivery Criteria

- C1：A→B、時間上限、重複序列與負例均符合獨立真值。
- C2：沒有可靠序號的同時間事件不得用 event_id 人為排先後。
- C3：明定事件是否可重用及不重疊匹配規則；未來事件不改過去觸發。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH13.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH13「有限行為序列」：實作兩步順序、間隔與受限重複序列模板。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH13.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH13，通過後交付結果，不自行開始下一 Phase。

## PH14 — 候選搜尋與剪枝

前置：PH01–PH13 全部 passed。來源：TECH §7。

目標：在探索集枚舉有限窗口／門檻／組合並去除等價條件。

交付：search config、候選與剪枝 manifest。

### Delivery Criteria

- C1：1/3/6/24/72 小時均可搜尋；總候選受配置上限約束。
- C2：同配置輸出相同候選 ID，記錄枚舉／剪枝原因；超限不偷偷略過。
- C3：holdout 內容變更不改候選生成；門檻不可從全體用戶分位數取得。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH14.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH14「候選搜尋與剪枝」：在探索集枚舉有限窗口／門檻／組合並去除等價條件。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH14.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH14，通過後交付結果，不自行開始下一 Phase。

## PH15 — 歷史驗證與證據狀態

前置：PH01–PH14 全部 passed。來源：TECH §7–8。

目標：凍結候選後計算 holdout 指標及不確定性。

交付：validation metrics、bootstrap、evidence rules。

### Delivery Criteria

- C1：樣本、覆盖、觸發延遲、ARPU、全體／未觸發基準與 fixture 相符。
- C2：固定種子區間可重現；最低樣本、不穩定、全零等情況不誤標通過。
- C3：凍結後變更候選拒絕；相關性不得標成因果、描述區間不得宣稱多重檢驗已校正。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH15.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH15「歷史驗證與證據狀態」：凍結候選後計算 holdout 指標及不確定性。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH15.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH15，通過後交付結果，不自行開始下一 Phase。

## PH16 — 重疊與敏感度診斷

前置：PH01–PH15 全部 passed。來源：TECH §7；PRD §9。

目標：整理候選之間的差異、門檻取捨及觸發後收益。

交付：overlap、sensitivity、landmark 產物。

### Delivery Criteria

- C1：Jaccard 和雙向覆蓋的分母正確，空集合處理明示。
- C2：門檻曲線對應同一 cohort；重疊候選不被包裝成不同人群。
- C3：觸發後收益排除觸發該筆，跨時間比較使用共同 landmark 並標觀察性診斷。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH16.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH16「重疊與敏感度診斷」：整理候選之間的差異、門檻取捨及觸發後收益。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH16.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH16，通過後交付結果，不自行開始下一 Phase。

## PH17 — Python baseline 管線

前置：PH01–PH16 全部 passed。來源：TECH §7。

目標：把上傳後分析串成可恢復的確定性背景任務。

交付：baseline orchestration、stage checkpoints。

### Delivery Criteria

- C1：fixture 從 dataset 到 metrics／推薦 manifest 全程不呼叫 LLM。
- C2：各 stage 狀態與產物一致；失敗不標 ready，已完成 stage 重啟可重用。
- C3：API 回 202 後可關閉呼叫端，任務仍完成；核心資料不足產出診斷而非假推薦。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH17.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH17「Python baseline 管線」：把上傳後分析串成可恢復的確定性背景任務。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH17.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH17，通過後交付結果，不自行開始下一 Phase。

## PH18 — 第一份報告與匯出

前置：PH01–PH17 全部 passed。來源：TECH §7；PRD §9。

目標：將 baseline 產物生成可用報告與精確事件規格。

交付：report renderer、HTML/JSON/CSV。

### Delivery Criteria

- C1：摘要、比較、證據、門檻、重疊、限制與打點規格齊備，數字都能回查 artifact。
- C2：無 OpenRouter key 仍能生成離線 HTML，JSON／CSV 與報告數值一致。
- C3：用戶輸入正確轉義、CSV 公式注入有防護；半成品不成為正式版本。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH18.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH18「第一份報告與匯出」：將 baseline 產物生成可用報告與精確事件規格。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH18.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH18，通過後交付結果，不自行開始下一 Phase。

## PH19 — Linear 風格雙欄 Shell

前置：PH01–PH18 全部 passed。來源：TECH §12。

目標：建立左對話右結果的可調雙欄與頂部工具列。

交付：web layout/tokens、瀏覽器截圖。

### Delivery Criteria

- C1：1280/1440 桌面左欄初始約360px，可調320–480px；兩側獨立捲動。
- C2：實作深色初始 token、細分隔與緊湊層級，不增加登入或第三常駐側欄。
- C3：輸入框及結果 tabs 固定，頁面無多餘水平捲軸；以 fixture 明示展示狀態。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH19.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH19「Linear 風格雙欄 Shell」：建立左對話右結果的可調雙欄與頂部工具列。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH19.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH19，通過後交付結果，不自行開始下一 Phase。

## PH20 — 上傳與欄位映射 UI

前置：PH01–PH19 全部 passed。來源：TECH §4–5。

目標：讓使用者從瀏覽器完成實際上傳與映射。

交付：upload/mapping pages、服務整合。

### Delivery Criteria

- C1：瀏覽器到本地 S3 相容服務真實傳檔並建立 dataset；不可只顯示假進度。
- C2：必填欄位、缺 part、錯型別錯誤可見；修正後可建立 baseline。
- C3：重新整理保留已保存映射；重選檔續傳不誤用別的檔案。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH20.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH20「上傳與欄位映射 UI」：讓使用者從瀏覽器完成實際上傳與映射。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH20.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH20，通過後交付結果，不自行開始下一 Phase。

## PH21 — 分析進度與歷史 UI

前置：PH01–PH20 全部 passed。來源：TECH §4、§12。

目標：實作背景分析進度、歷史與 ready 轉場。

交付：progress/history/run routes。

### Delivery Criteria

- C1：API 實際狀態驅動各階段，未知總量不偽造百分比。
- C2：baseline ready 才開對話入口；失敗显示原因和適當重試。
- C3：關頁重開同 run 保留進度或結果；歷史列表不因重啟消失。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH21.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH21「分析進度與歷史 UI」：實作背景分析進度、歷史與 ready 轉場。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH21.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH21，通過後交付結果，不自行開始下一 Phase。

## PH22 — 結果表與證據詳情

前置：PH01–PH21 全部 passed。來源：TECH §12。

目標：右側呈現真實 baseline 比較與候選詳情。

交付：overview/candidates/quality tabs。

### Delivery Criteria

- C1：三頁籤接真實產物，排序不改資料，候選展示完整條件與觸發規格。
- C2：样本／分母／證據狀態／資料品質均可查；缺資料不顯示為0。
- C3：固定 selected_run_id，不混用其他版本；資料更新不清空既有可讀內容。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH22.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH22「結果表與證據詳情」：右側呈現真實 baseline 比較與候選詳情。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH22.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH22，通過後交付結果，不自行開始下一 Phase。

## PH23 — 分析圖表

前置：PH01–PH22 全部 passed。來源：TECH §12。

目標：選一套圖表實作並呈現散點、敏感度曲線、重疊熱圖。

交付：chart renderer/schema、圖表測試與截圖。

### Delivery Criteria

- C1：官方能力查證後鎖定單一圖表庫；三類圖真實對應 baseline 產物。
- C2：USD/%/時間軸、樣本、分母及候選顏色一致，空值與極值可讀。
- C3：有數據表替代，未知 chart_type／超大 payload 被拒；不執行 Agent HTML/JS。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH23.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH23「分析圖表」：選一套圖表實作並呈現散點、敏感度曲線、重疊熱圖。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH23.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH23，通過後交付結果，不自行開始下一 Phase。

## PH24 — 響應式與可及性第一輪

前置：PH01–PH23 全部 passed。來源：TECH §12。

目標：完成窄螢幕切換與長內容操作。

交付：responsive states、鍵盤／對比證據。

### Delivery Criteria

- C1：768/390px 使用結果／對話切換且保留狀態，頁面不橫向溢出。
- C2：鍵盤可操作分隔、tabs、版本與匯出；焦點清楚，正文達4.5:1。
- C3：長中文／事件名、空資料、失敗狀態都有截圖，圖表資訊不只靠hover。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH24.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH24「響應式與可及性第一輪」：完成窄螢幕切換與長內容操作。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH24.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH24，通過後交付結果，不自行開始下一 Phase。

## PH25 — 對話與 Turn 持久模型

前置：PH01–PH24 全部 passed。來源：TECH §6、§10 HTTP。

目標：建立有序訊息、背景 Agent 任務與事件輪詢契約。

交付：conversation/message/turn routes、遷移。

### Delivery Criteria

- C1：同 conversation 只一個 active turn，新訊息可排隊且順序稳定。
- C2：送出原子保存 message/turn，重复 key 不重複；未ready回409。
- C3：事件 after=seq 可續讀，保存 selected_run/candidate context；刷新能讀全歷史。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH25.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH25「對話與 Turn 持久模型」：建立有序訊息、背景 Agent 任務與事件輪詢契約。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH25.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH25，通過後交付結果，不自行開始下一 Phase。

## PH26 — AI SDK 與 OpenRouter 接口

前置：PH01–PH25 全部 passed。來源：TECH §8。

目標：用真正 ToolLoopAgent 接 OpenRouter provider，提供測試模型注入點。

交付：agent runtime/provider adapter、版本鎖定。

### Delivery Criteria

- C1：真實 ai／provider 套件可 build，正式路徑讀伺服器 key/model，無自寫 loop 替代 SDK。
- C2：用 SDK 相容替身通過兩輪 tool-call/result、步數上限、錯誤、取消測試。
- C3：缺key清楚標示不可用且baseline仍可用；真API smoke列X01，不能標成已實測。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH26.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH26「AI SDK 與 OpenRouter 接口」：用真正 ToolLoopAgent 接 OpenRouter provider，提供測試模型注入點。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH26.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH26，通過後交付結果，不自行開始下一 Phase。

## PH27 — Agent 唯讀工具

前置：PH01–PH26 全部 passed。來源：TECH §8。

目標：讓 Agent 在對話中讀 baseline 與既有候選比較。

交付：profile/report/compare tools、引用校驗。

### Delivery Criteria

- C1：工具由 turn 綁 dataset/run，不能靠 arguments 跨資料；payload 限量。
- C2：同一問題可引用正確 artifact/evidence；錯引用被攔截或明示。
- C3：唯讀查詢不建立計算 job，不提供Shell/任意SQL；工具整合以真後端＋測試模型驗證。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH27.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH27「Agent 唯讀工具」：讓 Agent 在對話中讀 baseline 與既有候選比較。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH27.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH27，通過後交付結果，不自行開始下一 Phase。

## PH28 — 左側 Agent 對話 UI

前置：PH01–PH27 全部 passed。來源：TECH §12。

目標：接通持久 turn、回覆與右側引用。

交付：composer/message/tool cards。

### Delivery Criteria

- C1：送出、排隊、取消、失败重試狀態正確；IME組字不誤送，Shift+Enter換行。
- C2：向上閱讀不強制到底；刷新保留對話，無key顯示實際不可用而非假Agent。
- C3：點引用切到正確右側結果；已選候選在送出上下文可見。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH28.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH28「左側 Agent 對話 UI」：接通持久 turn、回覆與右側引用。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH28.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH28，通過後交付結果，不自行開始下一 Phase。

## PH29 — 驗證揭露與污染防線

前置：PH01–PH28 全部 passed。來源：TECH §8 驗證邊界。

目標：在開放重跑前完成跨對話的 holdout 使用紀錄。

交付：exposure ledger、後端資格檢查。

### Delivery Criteria

- C1：顯示baseline驗證報告會記錄揭露；同 dataset 的新對話不能清掉紀錄。
- C2：已揭露資料產生的新候選只標 exploratory，即使改run/config也不能升級。
- C3：新獨立批次需先凍結候選再驗證；新資料有用戶重疊時拒絕獨立標籤。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH29.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH29「驗證揭露與污染防線」：在開放重跑前完成跨對話的 holdout 使用紀錄。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH29.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH29，通過後交付結果，不自行開始下一 Phase。

## PH30 — 分析分支與快取

前置：PH01–PH29 全部 passed。來源：TECH §7。

目標：建立不可變子 run 和精確中間產物重用。

交付：followup API、lineage/cache manifest。

### Delivery Criteria

- C1：父子run、資料版本、來源turn及配置差異可查，父報告hash不變。
- C2：完全相符才快取；改mapping/split/feature/version任一項會失效。
- C3：重複工具提交只建一個子run；缺細粒度特徵改讀標準事件，不猜結果。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH30.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH30「分析分支與快取」：建立不可變子 run 和精確中間產物重用。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH30.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH30，通過後交付結果，不自行開始下一 Phase。

## PH31 — 重跑窗口與門檻工具

前置：PH01–PH30 全部 passed。來源：TECH §8。

目標：讓 Agent 指定受控條件後交 Python 重算。

交付：rerun_analysis/evaluate tools。

### Delivery Criteria

- C1：前3小時問題生成真正3h分支並返回正確fixture結果。
- C2：超範圍窗口、非法欄位或超候選預算拒絕；工具不接受任意程式碼。
- C3：等待計算時兩端租約正常，取消傳到子job，舊報告始終可讀。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH31.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH31「重跑窗口與門檻工具」：讓 Agent 指定受控條件後交 Python 重算。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH31.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH31，通過後交付結果，不自行開始下一 Phase。

## PH32 — 分群深入分析工具

前置：PH01–PH31 全部 passed。來源：TECH §8、§10 案例。

目標：支援國家、平台、來源的分群分析。

交付：analyze_segment、分群 metrics。

### Delivery Criteria

- C1：有country可產生美國子群，分母與真值一致，保留原成熟／split定義。
- C2：缺欄位及低样本回具體限制，不編造候選收益。
- C3：診斷標籤與父版关系正確，已揭露資料不宣稱全新驗證。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH32.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH32「分群深入分析工具」：支援國家、平台、來源的分群分析。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH32.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH32，通過後交付結果，不自行開始下一 Phase。

## PH33 — 自適應探索與停止

前置：PH01–PH32 全部 passed。來源：TECH §8。

目標：完成根據工具結果調整下一輪的 SDK 行為與停止機制。

交付：round log、budget/finalize tools。

### Delivery Criteria

- C1：測試模型在第一輪結果後調整窗口／門檻並完成第二輪真計算，保存round與證據。
- C2：凍結後不可繼續改候選；步數/時間/候選預算到限停止並留部分產物。
- C3：SDK管理迴圈，程式只管業務限制；對真模型的探索品質驗證保留X01。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH33.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH33「自適應探索與停止」：完成根據工具結果調整下一輪的 SDK 行為與停止機制。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH33.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH33，通過後交付結果，不自行開始下一 Phase。

## PH34 — 新結果與版本連動

前置：PH01–PH33 全部 passed。來源：TECH §12。

目標：把深入分析結果接回雙欄工作區。

交付：branch picker、view-result、export context。

### Delivery Criteria

- C1：點查看結果精確選child run/artifact；新結果不自動搶走舊視圖。
- C2：版本切換後圖表/表格/匯出一致；URL刷新還原選擇。
- C3：點圖/排序不觸發分析，針對候選提問才加入context；待算工具卡不清空右側。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH34.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH34「新結果與版本連動」：把深入分析結果接回雙欄工作區。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH34.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH34，通過後交付結果，不自行開始下一 Phase。

## PH35 — 同 App 經驗庫

前置：PH01–PH34 全部 passed。來源：TECH §8 學習。

目標：保存有證據的觀察並在新批次重驗。

交付：findings store、load/save tools。

### Delivery Criteria

- C1：findings有App、來源批次、條件、證據、限制、反例，不只是對話摘要。
- C2：新批次可讀舊觀察但不能直接標通過；支持與失效都能保存。
- C3：不跨App自動遷移，不改模型權重；相同觀察重放不重複新增。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH35.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH35「同 App 經驗庫」：保存有證據的觀察並在新批次重驗。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH35.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH35，通過後交付結果，不自行開始下一 Phase。

## PH36 — Agent 恢復與工具重放

前置：PH01–PH35 全部 passed。來源：TECH §6、§8。

目標：完成 Node runtime 中斷後恢復與 tool-call/result 配對。

交付：message checkpoint、recovery tests。

### Delivery Criteria

- C1：在工具提交前/後、回覆完成前各殺程序，恢復後無重複子run。
- C2：載入已提交messages；未完成工具先查既有job，結果配對一致。
- C3：模型與計算失敗狀態分開，baseline和已完成分支不丟失；不假稱逐token續傳。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH36.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH36「Agent 恢復與工具重放」：完成 Node runtime 中斷後恢復與 tool-call/result 配對。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH36.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH36，通過後交付結果，不自行開始下一 Phase。

## PH37 — 報告版本與客戶交付

前置：PH01–PH36 全部 passed。來源：PRD §9；TECH §12。

目標：支援選定基礎版或分支版匯出與後續再開啟。

交付：export UI、report versions、artifact links。

### Delivery Criteria

- C1：HTML/JSON/CSV 都使用所選run，带資料範圍、證據狀態與事件規格。
- C2：離線HTML不依賴登入/暫時API或過期預簽名URL，圖表可用或有完整靜態/表格替代。
- C3：基礎／分支報告可重開，敘述引用與數值一致，無原始識別資料意外外洩。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH37.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH37「報告版本與客戶交付」：支援選定基礎版或分支版匯出與後續再開啟。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH37.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH37，通過後交付結果，不自行開始下一 Phase。

## PH38 — 完整產品流程回歸

前置：PH01–PH37 全部 passed。來源：TECH §10、§12。

目標：從空工作區驗證上傳→報告→對話→深入分析→匯出。

交付：browser E2E、完整示範與截圖。

### Delivery Criteria

- C1：以真本地PostgreSQL/S3/Workers跑完流程，LLM替身使用標示清楚。
- C2：四個代表問題、取消、模型失败、刷新、中文長內容與窄屏全部通過。
- C3：無登入/第三常駐欄；資料結果來自實際管線，不以預寫fixture UI偽装完成。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH38.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH38「完整產品流程回歸」：從空工作區驗證上傳→報告→對話→深入分析→匯出。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH38.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH38，通過後交付結果，不自行開始下一 Phase。

## PH39 — 全系統故障與備份還原

前置：PH01–PH38 全部 passed。來源：TECH §6、§9。

目標：驗證 API/Workers/DB/儲存故障與隔離還原。

交付：fault suite、restore runbook、證據。

### Delivery Criteria

- C1：斷DB/物件服務、過期租約、磁碟滿各有可恢復或清楚失敗，無誤標成功。
- C2：從備份還原到隔離資料庫與儲存後重開報告，hash一致。
- C3：停止/重啟使用精確測試目標，不動客戶來源；自動清理只針對可重建暫存。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH39.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH39「全系統故障與備份還原」：驗證 API/Workers/DB/儲存故障與隔離還原。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH39.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH39，通過後交付結果，不自行開始下一 Phase。

## PH40 — 容量測試與限制

前置：PH01–PH39 全部 passed。來源：TECH §9–10。

目標：量測10萬/100萬/1000萬事件並落實資源限制。

交付：benchmark generator/results、資源預檢。

### Delivery Criteria

- C1：10萬與100萬完整管線實跑，記錄硬體/版本/候選數/時間/RAM/暫存/結果校驗。
- C2：1000萬先檢查磁碟與記憶體：足夠則實跑，不足則提供可執行benchmark並列X04，不能虛報容量。
- C3：CPU/記憶體/磁碟/時間/上傳限制可配置；超限有預檢或受控失敗，OOM不無限重試。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH40.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH40「容量測試與限制」：量測10萬/100萬/1000萬事件並落實資源限制。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH40.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH40，通過後交付結果，不自行開始下一 Phase。

## PH41 — 部署包與本地正式演練

前置：PH01–PH40 全部 passed。來源：TECH §9。

目標：交付可上線的服務包，先在本地隔離環境作正式設定演練。

交付：production Dockerfiles/Compose、健康檢查、部署文件。

### Delivery Criteria

- C1：正式images可build並啟動前端/API/兩Workers，不用開發伺服器作正式入口。
- C2：持久服務外部連線可配置；重建容器仍可開報告，migration與回復步驟有演練。
- C3：密鑰不進image/前端；無使用者登入，internal端點不經公開proxy暴露；真雲端/DNS/TLS列X02/X03。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH41.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH41「部署包與本地正式演練」：交付可上線的服務包，先在本地隔離環境作正式設定演練。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH41.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH41，通過後交付結果，不自行開始下一 Phase。

## PH42 — 最終交付與發布就緒審核

前置：PH01–PH41 全部 passed。來源：PRD §11；全TECH/UI。

目標：核對所有Phase證據，交付可由下一個Goal接手的完整專案。

交付：release report、需求追蹤矩陣、外部驗證清單。

### Delivery Criteria

- C1：PH01–PH41硬門檻都有有效證據；標示失效的舊證據需重驗，不以文件存在代替功能。
- C2：README從乾淨環境可重現本地產品；所有必需人工步驟、外部驗證命令及預期結果齐備。
- C3：分開結論：本地功能完成／真模型已驗或未驗／雲端已部署或未部署／容量已測範圍；未完成外部項不宣稱整體正式上線。

Gate：C1–C3 與 G1–G5 全部通過，evidence/PH42.md 有逐條證據，才可標 passed。

### Goal

> 完成 IMPLEMENTATION_PLAN.md 的 PH42「最終交付與發布就緒審核」：核對所有Phase證據，交付可由下一個Goal接手的完整專案。先檢查前置與本文件共同 Gate。實作本節交付內容，逐條通過 C1–C3 與 G1–G5，保存 evidence/PH42.md 並更新 PHASE_STATUS.md。遇第 3 節外部操作按規則延期至 EXTERNAL_CHECKS.md，不掩蓋核心缺失。本 Goal 只執行 PH42，通過後交付結果，不自行開始下一 Phase。

## 6. 證據格式與變更紀律

每份 evidence/PHxx.md 至少保存：

- Phase ID、日期、輸入版本（若有 Git 用 commit／dirty 描述，否則記檔案 hash）。
- 每個 C1–C3 的實際結果、命令、退出碼及產物／截圖路徑。
- G1–G5 的核對與受影響前階段回歸。
- 驗證用的是合成資料／測試模型／真外部服務，區分清楚。
- 本輪外部延期 ID、具體補驗命令、預期結果。
- 尚存限制；Gate 結論 passed 或 blocked 及原因。

Phase 切換是機器驗收，不要求 JJ 每次批准。文件/UI 最終偏好可集中交付，不因此停住每個 Phase。若發現必須更改產品範圍，保留原門檻並說明，不以編輯驗收條件讓失敗變通過。

需求新增時追加穩定 Phase ID 或子階段，保留原 ID 與證據。未來修改使已 passed 階段失效時，將受影響 Phase 退回 in_progress，完成必要回歸後再繼續。

本文件沒有執行測試、建立付費資源或自動啟動 /goal；所有程式路徑是待實作交付位置。
