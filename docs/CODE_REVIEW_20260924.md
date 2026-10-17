# 2026-09-24 全專案 code review

本輪只讀取、重現及測試，未修改產品程式或部署。檢查 V4 特徵、搜尋、驗證、報告、前端與離線呈現；並追查資料成熟度、探索／Holdout 隔離、揭露紀錄、Worker 發布與回復、API 內部授權及 Railway gateway 設定。不是重新執行容量驗收或逐行證明所有歷史版本沒有缺陷。

## 發現（按處理優先順序）

### 1. P1：第一次開啟遊戲可能被算成回訪

位置：`server/analysis/v4_features.py:60`、`server/analysis/casual_features.py:161`。

`session_start.event_time > installed_at` 就被當成首次回訪，未要求前面已有另一個 Session。安裝後 5 秒第一次開啟，305 秒結束，且沒有第二次遊玩的案例，`repair_timeline` 輸出 `post_return_session_count=[(5,1)]`、`post_return_engaged_seconds=[(305,300)]`。回訪後計數與時長因而包含第一次遊玩，搜尋、達標時間與收入比較都可能選到錯誤人群。這不代表所有其他行為計算都錯。

建議：以可識別的首次 Session 為基準，後續不同 Session 才算回訪；缺乏足夠識別資料時保留未知。同步處理 snapshot 與 V4 timeline，補「安裝時間與首次 session 差幾秒」「只有一次遊玩」「第二次 session」案例。修正後按新計算版本重跑，不能覆寫歷史產物或把已看過的資料重新宣稱獨立驗證。

重現：`PYTHONPATH=. uv run python .runtime/full-review-20260924/repro.py`，輸出 `return-repro.log`。

### 2. P2：搜尋上限只限制最後保留的集合，沒有涵蓋兩輪實際計算的聯集

位置：`server/analysis/v4_search.py:105`、`:144`、`:159`。

第一輪會先對最多 16,000 個原子／序列規則呼叫 `brief`，加入組合後又重新按配額選最多 20,000 個，再計算新入選規則。兩個集合不保證包含關係。分配器可重現第一輪 16,000、最後集合 20,000，但實際聯集 23,408；其中 3,408 條已評估的規則還會落入 `DISCOVERY_BUDGET_NOT_EVALUATED`。

這是候選量足夠大時的邊界；目前正式合成報告的原子候選較少，未觀察到超限。重現使用真正的 `category_take` 和構造的類別數量，不冒稱已用客戶事件完整跑出此情況。正式比較 2,000 上限是另一條預算，沒有因此證明它也超限。

另一個更直接的觸發是滿額後加入未在搜尋集合中的自訂規則（`:151–156`）：先刪除已評估規則，再計算新規則；最終集合仍是 20,000，實際計算則再加一。

建議：每次評估以全域已評估 ID 集合扣預算，後續新增規則只使用剩餘額度；已計算但未進完整比較者應標為探索結果。

重現：`PYTHONPATH=. uv run python .runtime/full-review-20260924/budget_repro.py`。

### 3. P2：新版 HTML 詳細證據只涵蓋 24 小時

位置：`web/src/v4-export.tsx:12`、`web/src/report-v4.tsx:47`。

HTML 的主表確實有三群 × 六時間點，但每個詳細區塊呼叫 `TimeEvidence` 時只指定群體，未傳 `initialHours`，且關閉互動；因此詳細人群收益分解、Holdout 差異區間與計算依據永久停在預設 24 小時。主表仍有其他時間點的狀態，每日新增表也有六天，不能把問題描述成整個匯出沒有多天分析。

目前下載的 HTML 中，30 個「符合玩家截至…已發生收入」區塊全部為 24 小時，而比較表標題有 24–144 六時間點。這是近期共用 UI 元件匯出時留下的缺口。

建議：離線詳情提供六個時間點的可展開證據，或離線時間切換；仍使用原產物，避免另算一套數字。

### 4. P2：正式端到端回歸腳本已和目前 UI 不一致

位置：`scripts/offline_report_qa.cjs:18`、`scripts/version_browser_qa.cjs:16` 與 `:31`。

匯出腳本找 `下載 HTML/JSON/CSV`，但目前標籤為 `原始封存 HTML` 和 `完整計算 JSON/CSV`，造成 30 秒逾時，父／子分析下載與斷線重開驗收走不到後段。版本腳本也仍要求 `匯出` 為 link，現在已是 button。本次完整回歸另外在等待 `查看分析進度與結果 · 處理中` 時失敗；該精確文字在現行聊天元件已不存在。這項等待中的流程仍需用現行狀態與進度入口重新驗收，不能僅憑文字過期就宣稱取消流程本身正常。

建議：更新穩定的互動定位與斷言，分別覆蓋新版閱讀版及原始匯出；補測處理中進度、取消與父／子版本，之後再宣稱完整整合驗收通過。這些是驗收缺口，不等同目前所有下載都壞掉。

## 驗證結果與界線

- 前端與 Agent build 通過。
- Web model：27 passed；Agent：25 passed。
- V4 contract/features/metrics/rolling/sequences/search-validation/review-fixes：36 passed。
- 資料成熟度與驗證隔離：12 passed（targets-policy.log），包括相同資料重用、獨立人群、揭露先後與併發鎖。
- V4 pipeline 五項及 V3 backward read 一項通過，含 PG/S3/Worker、原始報告保持不變與 Agent 聚合數字。
- 正式 Railway 六路由 × 桌面／手機、各報告頁籤與聊天配色複驗通過，無頁面溢出或瀏覽器例外（browser.log）；這不代替上述父／子分析流程驗收。
- contracts/check.py：22 基礎 + 7 V3 範例通過。
- 全 Python suite 收集 426 項；跑到 68 passed、1 failed 後中止，以調查已出現的 UI 回歸，不宣稱全套通過。
- 另一組整合測試為 6 passed、1 failed 後中止；失敗為父／子報告下載逾時。兩組失敗不同，不能把通過數相加當成不重複覆蓋率。
- 測試紀錄、重現案例均在 `.runtime/full-review-20260924/`。未修改產品原始碼、未修復上述問題。
