# Candidate Event V3 — Casual Game Implementation Plan

版本：1.0  
日期：2026-09-11  
狀態：執行規劃基線；尚未開始實作  
需求來源：`docs/CASUAL_GAME_CANDIDATE_V3_PLAN.md`  
進度與證據：`PHASE_STATUS.md`、`evidence/CG01.md`～`evidence/CG06.md`

## 1. 執行授權與邊界

本文件把 Candidate Event V3 拆成 CG01～CG06 六個可依序實作與驗收的 Phase。後續使用者以 Goal 指定單一 Phase 或一段 Phase，即代表該範圍的實作授權；本次建立計畫不代表 V3 已實作、通過或部署。

V3 以目前已存在的上傳、Python／DuckDB、PostgreSQL、S3、持久 Worker、報告、Agent 與雙欄 UI 為工程基礎，但使用獨立的 `analysis_version`、候選 AST、artifact schema、calculation version、feature version 與 pipeline identity。現有 CV05 狀態不是 CG01 的前置條件，也不阻擋 V3；舊 run、舊報告與舊 cache 必須保持可讀且不可被改寫。

固定產品流程更新為：

> 上傳資料 → Python V3 baseline → 凍結候選 → 全部成熟玩家描述性比較 → 可用時追加 holdout 重現檢查 → 報告／完整匯出 → Agent 讀取聚合證據

主表不得因 holdout 樣本不足而隱藏本批觀察。全量成熟玩家數字回答同批行為關聯；holdout 狀態只代表額外重現證據。兩者必須在 artifact、匯出與 UI 分開標示。

第一次分析不依賴 LLM。前端不計算候選、統計量或圖表數值。V3 仍是歷史關聯分析，不是因果提升、ROI 保證、即時 SDK 回傳或投放自動化。

## 2. 本計畫固定的實作決策

### 2.1 版本、身份與相容

- 新 run 明確保存 `analysis_version="3.0-casual-game"`；V3 上線後新 baseline 預設使用 V3，既有 run 依其已保存版本繼續讀取。
- 新增 `server/analysis/v3_contract.py` 作為 V3 數值及 artifact 合約入口；不把 V3 欄位塞進 V2 detail 後假裝相容。
- `candidate_id` 由 canonical JSON 計算，身份至少包含：analysis version、category、indicator type、觀察起迄、判定模式、predicate／sequence、門檻、方向、最小分母與身份約束。
- Pipeline identity 必須包含 V3 合約、policy、計算模組與 contracts hash；任何相關檔案或固定政策改動都使 cache key 改變。
- 舊 IAA-only 資料可走 V3；缺少 Casual Game 欄位時只關閉對應 capability，不能補造 Level 或 Retention 結果。

### 2.2 事件與資料身份

- 原始事件 identity 沿用 `(app_id, event_id)`；完全重複可去重，同 identity 不同內容整組隔離並列入品質阻擋，不任選一筆。
- Level attempt identity 為 `(app_id, user_id, level_id, attempt_id)`。`attempt_id` 只用於配對，不取代 `event_id`。
- 有順序需求時先按 `event_time`，同時間只在兩筆都有可靠 `source_sequence` 時判定先後；否則不配對，不靠檔案列順序猜測。
- 同一 attempt 出現非重複的多個 complete、或同時出現 complete 與 fail，標記 `ATTEMPT_TERMINAL_CONFLICT`，關閉該資料集的 `attempt_pairing` 及相依指標；Level 事件次數仍依合法 event 計算，不任選一個 terminal outcome。
- `level_index` 是來源提供的全域序位，必須為有限非負整數，不從 `level_id` 猜測。相同 `level_id` 對應衝突 index 時，Level progress capability 關閉並列原因。
- `level_mode`、`difficulty`、`revive_used`、`booster_used`、`app_version` 第一版保存與做品質摘要，但不生成主要候選，也不跨 mode 猜測進度關係。

### 2.3 Capability 粒度

V3 不使用「有一個欄位缺失就關閉整個 Category」的粗粒度判斷，至少分為：

| Capability | 最低條件 | 缺失時仍可做 |
|---|---|---|
| `level_event_counts` | 合法 Level event_name | IAA、Session；Level start／complete／fail 次數 |
| `level_identity` | Level event 有 `level_id` | Level 事件次數，但不算不同關卡與同關卡行為 |
| `level_progress` | 完整且一致的 `level_index` | Level 次數、identity 指標 |
| `attempt_pairing` | `level_id`＋`attempt_id`＋可靠時間順序 | 未配對的 Level 次數／進度 |
| `session_return` | 合法 `session_start`＋完整觀察區間 | 不要求 `session_id` 的正向區間回訪 |
| `distinct_session_count` | `session_start`＋完整 `session_id` | 單純回訪判定 |
| `session_duration` | 可驗證的 start/end 或合法結算時長 | Session count／return |
| `same_session_cross` | 交叉事件都有 `session_id` | 不要求同 Session 的其他候選 |

缺少某類事件不代表所有用戶該行為為零；只有 capability 已確認可觀察，且個別用戶的指定窗口完整時，才可將沒有事件解讀為零。無回訪只能在區間右端結束後確認，第一版不生成「沒有回訪」主要候選。

### 2.4 觸發與狀態指標

候選分兩種判定模式：

- `first_match_once`：累積次數、累積收益、最高進度、正向回訪、兩步序列等單調或事件型條件，在首次合法達標時觸發一次。
- `checkpoint_snapshot`：比率、平均嘗試、平均完成時間等可能上下變動的狀態指標，只在預註冊的 observation end 判定；其 `earliest_trigger_hours` 等於該觀察終點，不能宣稱更早可用。

狀態指標分母為 0、窗口未完整或配對資料不足時輸出 null，不補零。`gte` 與 `lte` 都可用於 snapshot 指標；事件型條件只使用具明確產品語意的正向達標方向。

### 2.5 Retention、Level 與序列語意

- `[24,48)`、`[48,72)`、`[72,96)` 都是以 install／first-open 起點計算的半開區間；剛好落在右端的事件屬下一區間。
- 正向回訪的觸發時間是區間內第一個合法 `session_start`；區間開始不等於實際觸發時間。
- `level_start → level_complete` 要求相同 `level_id` 與相同 `attempt_id`。
- `level_fail → level_start` 要求相同 `level_id` 且下一個不同 `attempt_id`，表示重試。
- `level_fail → level_complete` 要求相同 `level_id`，允許後續 attempt 完成。
- `level_fail → session_end`、`session_start → level_complete`、`level_complete → ad_impression`、`rewarded_ad → level_complete` 要求相同 `session_id`。
- 一個事件完成一組配對後不可重用；相同時間沒有可靠順序時不配對；repeats 固定為 1、2、3。
- 第一版固定 max-gap grid：5 分鐘、30 分鐘、2 小時；`fail → complete` 額外允許 24 小時。長 gap 不自動擴張到其他模板。
- `Retention × 後續廣告收益` 的「後續」只指回訪事件之後、候選 observation end 之前已可取得的收益，不得使用 observation end 之後或 `[72,168)` 的目標收益建立條件。

### 2.6 Friction 指標公式

- `complete_start_ratio = completed_attempts / valid_starts`。
- `fail_start_ratio = failed_attempts / valid_starts`。
- `attempts_per_level = valid_starts / distinct_started_level_id`。
- `completion_duration` 使用相同 attempt 的 start 至 complete 秒數；用戶級指標採窗口內 median，避免單一極端值主導。
- `consecutive_failures` 為同一 `level_id` 在下一次 complete 前連續失敗的不同 attempt 數，complete 後歸零；取窗口內最大值。
- 比率與平均值只有在 exploration 預先固定的最小有效分母達標時才可生成候選；`complete_start_ratio`／`fail_start_ratio` 至少 3 個 valid starts，`attempts_per_level` 至少 2 個不同 level，`completion_duration` 至少 2 個配對完成，`completes_per_session` 至少 2 個不同 session。最低分母由 V3 policy 保存並進 candidate identity，不由 holdout 修改。

### 2.7 固定窗口、門檻與父條件

候選 observation end 只使用以下預註冊集合：

| Category | Observation end／區間 |
|---|---|
| IAA | 1、3、6、12、24、48、72、96、120、144h |
| Session count | 3、6、12、24、48、72、96、144h |
| Retention | `[24,48)`、`[48,72)`、`[72,96)` |
| Level count／一般進度 | 1、3、6、12、24、48、72h |
| 最高 Level／到達 N | 1、3、6、12、24、48、72、96、120、144h |
| Ratio／friction | 6、12、24、48、72h |
| Sequence | 1、3、6、12、24、48h |

Threshold grid 固定為：

- IAA 次數、收益與格式沿用 V3 需求基線的 P5～P95、固定 count 與 1／2／5 × 10^n 收益刻度。
- Session／Level count 使用正值 exploration P10～P90 deciles，加固定 `1,2,3,5,8,10,20`。
- Level index 使用正值 exploration P10～P90 deciles，加固定 `1,2,3,5,10,20,50,100`；超出 exploration 已觀察範圍者不生成。
- Ratio 使用 P10～P90 deciles，加固定 `0.25,0.5,0.75`，限制在 `[0,1]`。
- Attempts per level 使用正值 deciles，加固定 `1.5,2,3,5,8`；duration 使用正值 deciles，加固定 60、300、900、1,800、3,600 秒。
- 分位門檻只由 exploration 產生；相同數值 canonicalize 為一個候選，holdout 不補門檻。

Cross-category 每一 `Category × observation end` 最多取 20 個已通過樣本門檻的父條件，依 exploration Pareto／diversity 規則固定後再組合。每個組合最多兩個原子，不接受巢狀 compound。

### 2.8 搜尋預算與固定回補

Discovery 上限 20,000，初始 Category 配額為 Validation 配額的十倍：

| Category | Discovery | Validation |
|---|---:|---:|
| IAA | 3,500 | 350 |
| Session／Retention | 3,000 | 300 |
| Level Progress | 4,500 | 450 |
| Level Friction | 3,000 | 300 |
| Cross-category | 4,000 | 400 |
| Sequence | 2,000 | 200 |
| 合計 | 20,000 | 2,000 |

每個 Category 先按 observation end、indicator type、canonical predicate、candidate ID 穩定排序。某 Category 不足時，剩餘名額按表格順序逐輪各補一名，跳過已耗盡 Category，直到用完或沒有候選；Discovery 與 Validation 使用同一回補規則。不得讀完 holdout 再調配。

Discovery 去蕪存菁順序固定為：

1. Canonical AST 完全等價去重。
2. Exploration 精確 membership hash 去重；保留語意較簡單、P90 較早、candidate ID 較小的代表。
3. 兩組未達既有 `min_group_users` 者標記樣本不足，不占 Validation 名額。
4. 同一連續門檻曲線的相鄰點若 Jaccard ≥ 0.995，且 coverage 差 ≤ 0.005，保留形成較大 coverage／D7 差取捨變化者；其他標 `NEAR_DUPLICATE_THRESHOLD`。常數寫入 policy 與 search manifest。
5. Category 內以 exploration D7 ARPU 差較大、coverage 較廣、P90 較早做 Pareto layer；同 layer 再以與已選集合的最大 Jaccard 較低者優先，最後以 candidate ID 平手。
6. Cross-category 只從各窗口／Category 已入選的有限父條件池生成，不把全 Discovery Pool 兩兩排列。

所有被生成但未進 Validation 的候選都必須保存單一主要原因及可選次要原因。Discovery 數字只能稱探索結果。

優先比較名單最多 10 個，在讀取 holdout 前依 exploration 的 Category coverage、Pareto layer、觸發 P90 與 membership diversity 凍結；至少嘗試覆蓋不同 Category，但不為湊數降低樣本門檻。Holdout 只更新每個優先候選的證據狀態，不補選或重新排序。

### 2.9 72 小時共同觀察點

- D2 定義為 early=`[0,48)`、remaining=`[48,168)`；D3／圖表共同觀察點定義為 early=`[0,72)`、remaining=`[72,168)`。
- 散點圖只納入 `decision_time_hours <= 72`、且 membership 在 72h 前可完整判定的完整驗證候選。
- 96／120／144h 候選與 `[72,96)` 回訪候選仍在完整表格、CSV、JSON、HTML 與證據卡中，但標記 `chart_status=LATE_INDICATOR_NOT_PLOTTED`。
- X／Y 都使用 holdout 成熟用戶、同一候選 triggered／untriggered 分組：X 是 `[0,72)` ARPU 差，Y 是 `[72,168)` ARPU 差。
- 候選條件不得讀取 `[72,168)` 收益後再進此圖；任何收益 availability 晚於 72h 的資料都不能回填早期 membership。
- null 點不繪製但保留於圖表資料與可及性表格；前端顯示「可繪製／全部」數量與排除原因。

## 3. 共通 Gate 與完成定義

每個 CG Phase 的 C1–C3 都是硬門檻，並同時要求 G1–G7：

- G1：交付已存在於真實程式／合約／UI，不以 stub、TODO、mock response 或只寫文件冒充。
- G2：執行本 Phase 指定測試，保存命令、退出碼、關鍵觀察值、產物 hash 與位置。
- G3：修改既有合約時執行受影響回歸；失敗先修復，不以刪測試、放寬斷言或縮減候選冒充通過。
- G4：不覆寫來源檔、舊 run、舊報告或舊 artifact；不提交原始 log、個資或憑證。
- G5：保存 `evidence/CGxx.md`，更新 `PHASE_STATUS.md`，逐條對應 C1–C3 與 G1–G7。
- G6：每個 artifact 都綁定 run、dataset、analysis version、pipeline／feature／policy identity、上游 hash；前端與 Agent 不跨版本拼接。
- G7：未知值保留 null；零事件用戶保留；未滿觀察期不補 false；所有報告措辭保持關聯而非因果。

狀態只使用 `pending`、`in_progress`、`passed`、`blocked`。只有使用者帳戶、真客戶資料、雲端或明確外部服務才可記入 `EXTERNAL_CHECKS.md`；本地核心實作、真 PostgreSQL／S3 相容整合、測試與 100,000 事件容量不可外部延期。

## 4. 目標 Pipeline 與 artifact

V3 baseline 的可恢復 stage 順序固定為：

1. `normalized_v3`
2. `quality_v3`
3. `targets_v3`
4. `exploration_features_v3`
5. `discovery_v3`
6. `discovery_membership_v3`
7. `validation_freeze_v3`
8. `full_features_v3`
9. `holdout_membership_v3`
10. `validation_v3`
11. `diagnostics_v3`
12. `catalog_v3`
13. `report_v3`

每個 stage 先寫 partial，再經 checksum／upstream identity 驗證才發布 manifest。中斷恢復不得重用不同 analysis version、policy hash 或 feature hash 的 checkpoint。

至少新增以下版本化產物：

- `quality_v3.json`、`dataset_profile_v3.json`
- `casual_features.parquet`、`feature_manifest_v3.json`
- `discovery_catalog_v3.json`、`discovery_membership.parquet`
- `validation_family_v3.json`、`holdout_membership.parquet`
- `validation_results_v3.json`
- `candidate_catalog_v3.json`、逐候選 `details/{candidate_id}.json`
- `candidate_value_map_v3.json`
- `report_v3.json`、`report_v3.html`、`report_v3.csv`

Discovery search log 與完整 Validation catalog 是不同 artifact；未進 Validation 的候選不得出現在 validated count，已進 Validation 的所有候選都必須有 detail 與 validation status。

## 5. CG01 — V3 資料合約與手算真值

前置：現有本地平台基礎可讀；不要求 CV05 passed。

目標：固定 V3 schema、事件／attempt／窗口語意、候選 AST、artifact identity 與獨立手算 fixture。

主要修改位置：

- `contracts/schema.json`、`contracts/defaults.json`、`contracts/examples.json`、`contracts/check.py`
- 新增 `contracts/casual_game_v3.schema.json`
- `server/analysis/ingest.py`、新增 `server/analysis/v3_contract.py`
- `server/api/schemas.py`、`web/src/upload-page.tsx`
- `tests/fixtures/casual_v3/`、`tests/test_v3_contract.py`、`tests/test_v3_ingest.py`
- `docs/decisions.md`、新增 `docs/CASUAL_GAME_CANDIDATE_V3_ACCEPTANCE.md`

### Delivery Criteria

- C1：合法／非法 schema 覆蓋 Level 欄位、analysis version、V3 AST、Category、observation start/end、trigger mode、direction、denominator、sequence identity；非法深層 AST、任意 SQL、三步序列與非有限數值整筆拒絕。
- C2：獨立 fixture 手算涵蓋 48h／72h 右端、亂序、同時間無 sequence、同 attempt 重複完成、complete＋fail 衝突、不同 level／attempt、缺 level ID/index、未成熟與未完整觀察；expected results 不由受測函式產生。
- C3：V3 candidate／artifact／pipeline identity 可重現；改任一固定語意會換 hash；舊 IAA fixture 可成功正規化且原始 bytes/hash 不變。

Gate：執行 contract check 與 CG01 測試；保存 `evidence/CG01.md` 後才可標 passed。

### Goal

> 依 `docs/CASUAL_GAME_CANDIDATE_V3_IMPLEMENTATION_PLAN.md` 完成 CG01「V3 資料合約與手算真值」。CV05 不是前置。逐條通過 C1–C3 與共同 G1–G7，保存 `evidence/CG01.md` 並更新 `PHASE_STATUS.md`。只執行 CG01，通過後停止，不自行開始 CG02。

## 6. CG02 — 多元特徵與首次判定

前置：CG01 passed。

目標：以事件時間與 capability 合約產出可重現的 Session／Retention、Level progress、Level friction、Retry 與有限序列特徵。

主要修改位置：

- `server/analysis/quality.py`、`server/analysis/features.py`
- 新增 `server/analysis/casual_features.py`、`server/analysis/casual_sequences.py`
- `server/analysis/predicates.py`、`server/analysis/exploration.py`
- `tests/test_v3_quality.py`、`tests/test_v3_features.py`、`tests/test_v3_sequences.py`

### Delivery Criteria

- C1：Capability flags 逐項符合第 2.3 節；舊 IAA、只有 Level event name、缺 session ID、缺 attempt ID、衝突 level index 等 fixture 均產出正確 enabled/reasons，不把缺失補零。
- C2：所有指標與 sequence 在固定窗口、半開端點、identity、same-time、available-at 及配對規則下等於獨立手算；零事件用戶保留，窗口不完整值為 null。
- C3：`first_match_once` 與 `checkpoint_snapshot` 分離；改變未來事件不改過去已可判定觸發；ratio denominator、median duration、consecutive fail 與跨日回訪邊界有負例。

Gate：CG02 測試、受影響 ingest／quality／features／predicates／sequence 回歸通過，保存 `evidence/CG02.md`。

### Goal

> 依 `docs/CASUAL_GAME_CANDIDATE_V3_IMPLEMENTATION_PLAN.md` 完成 CG02「多元特徵與首次判定」。先確認 CG01 passed；逐條通過 C1–C3 與共同 G1–G7，保存 `evidence/CG02.md` 並更新 `PHASE_STATUS.md`。只執行 CG02，通過後停止。

## 7. CG03 — Discovery、去重、Category 預算與凍結

前置：CG01–CG02 passed。

目標：只用 exploration 產生最多 20,000 候選，留下完整搜尋紀錄，依固定規則選出並凍結最多 2,000 Validation Family。

主要修改位置：

- 新增 `server/analysis/v3_policy.py`、`server/analysis/casual_search.py`
- 新增 `server/analysis/casual_selection.py`、`server/analysis/casual_freeze.py`
- `server/analysis/search.py`、`server/analysis/freeze.py`、`server/pipeline.py`
- `tests/test_v3_search.py`、`tests/test_v3_selection.py`、`tests/test_v3_freeze.py`

### Delivery Criteria

- C1：各 Category、窗口、threshold、方向與預註冊序列有限生成；20,000 cap、初始配額與逐輪回補完全依 policy；所有未生成／未入選者有可追溯原因。
- C2：Canonical、exact membership、near-duplicate、sample filter、Pareto、diversity 與受控 parent pool 均有手算案例；單一 Category 不能壟斷預算，相同 seed/input 產物 byte-identical。
- C3：Freeze receipt 保存精確候選順序、family size、policy hash、exploration split/hash；改 holdout 事件、收益或排序不改 Discovery、選擇與 freeze bytes。

Gate：CG03 測試與既有 search／selection／freeze 回歸通過；保存包含 20,000／2,000 邊界小型壓力證據的 `evidence/CG03.md`。

### Goal

> 依 `docs/CASUAL_GAME_CANDIDATE_V3_IMPLEMENTATION_PLAN.md` 完成 CG03「Discovery、去重、Category 預算與凍結」。先確認 CG01–CG02 passed；逐條通過 C1–C3 與共同 G1–G7，保存 `evidence/CG03.md` 並更新 `PHASE_STATUS.md`。只執行 CG03，通過後停止。

## 8. CG04 — Holdout 完整驗證與時間診斷

前置：CG01–CG03 passed。

目標：對整個凍結家族在 holdout 重新計算 membership，完成統計、D2／D3／D7 收益分解、每日與 source 診斷。

主要修改位置：

- 新增 `server/analysis/casual_validation.py`、`server/analysis/casual_diagnostics.py`
- `server/analysis/validation.py`、`statistics_v2.py`、`bootstrap.py`
- `server/validation_batches.py`、`server/checkpoints.py`、`server/pipeline.py`
- `tests/test_v3_validation.py`、`tests/test_v3_statistics.py`、`tests/test_v3_revenue_decomposition.py`
- `tests/test_v3_validation_recovery.py`

### Delivery Criteria

- C1：凍結家族每一候選都有 holdout 結果；使用 1,000 次 user-level bootstrap、單尾 Welch、全家族 Holm；不可檢驗者保留並以 p=1 進家族，校正未完整前不可發布。
- C2：D2、D3、D7 的 triggered／untriggered users、unknown users、revenue、ARPU 與 difference 皆可手算；early＋remaining 嚴格等於 D7，缺失傳播，晚期 indicator 不標早期。
- C3：每日與 acquisition source 只是診斷；小樣本隱藏比較但保留分母與原因；holdout 不回頭改 threshold、quota、priority 或 freeze。中斷／重領／舊 fence／損壞 checkpoint 均不能發布半套結果。

Gate：無訊號、少數真訊號、重尾、退化樣本、未完整觀察、收益延遲、72h 邊界與 batch recovery 測試通過；保存 `evidence/CG04.md`。

### Goal

> 依 `docs/CASUAL_GAME_CANDIDATE_V3_IMPLEMENTATION_PLAN.md` 完成 CG04「Holdout 完整驗證與時間診斷」。先確認 CG01–CG03 passed；逐條通過 C1–C3 與共同 G1–G7，保存 `evidence/CG04.md` 並更新 `PHASE_STATUS.md`。只執行 CG04，通過後停止。

## 9. CG05 — V3 報告、完整匯出與 72h 最小互動圖

前置：CG01–CG04 passed。

目標：讓客戶讀取少數優先比較、全部 Validation 結果、完整 Discovery 搜尋紀錄與單一 72h 候選價值圖。

主要修改位置：

- 新增 `server/analysis/catalog_v3.py`、`server/analysis/report_v3.py`
- `server/candidate_reader.py`、`server/candidate_exports.py`、`server/candidate_html.py`
- `server/api/main.py`、`server/api/schemas.py`、`server/read_tools.py`
- `web/src/report-model.ts`、`candidate-evidence.tsx`、`report-charts.tsx`
- `web/src/chart-model.ts`、`chart-renderer.tsx`、`candidate-language.ts`
- `tests/test_v3_catalog.py`、`tests/test_v3_exports.py`、`tests/test_v3_read_tools.py`
- `tests/test_v3_product_browser.py`、新增 V3 browser QA script

### Delivery Criteria

- C1：優先表、完整 catalog/detail、Discovery log、CSV／JSON／HTML 都提供 Category、indicator、observation start/end、decision/earliest trigger、D2／D3／D7、discovery/validation status；所有數值來自已驗證 Python artifact。
- C2：72h 圖只載入合格候選；X/Y、sample、coverage、status、detail hash 與 Python artifact 逐值相等。Category filter、hover、click evidence card、鍵盤操作、null／late 排除說明與可及性數據表通過。
- C3：前端不重算、不以多色或圓點大小加新編碼；離線 HTML 可讀；完整匯出包含所有實際 Validation 結果，Discovery 未驗證者只在搜尋紀錄；Agent 引用精確 run/version/candidate/detail hash。

Gate：model tests、build、typecheck、API、browser desktop 1440、mobile 390、離線 HTML 與逐值 read-back 通過；保存截圖與 `evidence/CG05.md`。

### Goal

> 依 `docs/CASUAL_GAME_CANDIDATE_V3_IMPLEMENTATION_PLAN.md` 完成 CG05「V3 報告、完整匯出與 72h 最小互動圖」。先確認 CG01–CG04 passed；逐條通過 C1–C3 與共同 G1–G7，保存 `evidence/CG05.md` 並更新 `PHASE_STATUS.md`。只執行 CG05，通過後停止。

## 10. CG06 — 全流程回歸、恢復與 100,000 事件容量

前置：CG01–CG05 passed。

目標：以最新版程式完成 V3 真實本地 PG/S3/Worker 端到端、故障恢復、舊 run 可讀與 100,000 事件／2,000 Validation 候選容量驗收。

主要修改位置：

- `scripts/benchmark.py` 或新增 `scripts/benchmark_casual_v3.py`
- `tests/test_v3_pipeline.py`、`tests/test_v3_end_to_end.py`
- `tests/test_v3_capacity_contract.py`、`tests/test_v3_backward_read.py`
- `docs/capacity.md`、`docs/release_audit.md`、`EXTERNAL_CHECKS.md`

### Delivery Criteria

- C1：從 CSV／Parquet 上傳、欄位映射、背景分析、進度恢復、報告、圖表、完整匯出到 Agent 唯讀引用全流程通過；父報告、來源與舊 run bytes/hash 不變。
- C2：Casual Game 100,000 事件完整跑完，實際到達 20,000 Discovery 與 2,000 Validation；保存 wall time、CPU、peak RSS、磁碟、各 artifact 大小、stage timing、candidate count 與獨立 fixture／CSV-Decimal 真值核對。
- C3：完整 Python suite、contracts、前端 build/typecheck/model tests、Agent tests、browser QA 全部通過；Worker kill/reclaim、PG/S3 重啟、損壞 artifact、cache version mismatch 與 null/late chart consistency 回歸通過。

第一版 100,000 事件是本地 MVP 容量硬門檻。1,000,000 事件、3,000／4,000 Validation candidates、真客戶資料、雲端 Vercel/Railway 才列後續決策或外部補驗；不得縮減 bootstrap、候選數或資源門檻冒充 CG06 passed。

Gate：最新版本所有必要命令及容量 run 退出碼為 0，產物逐項核對後保存 `evidence/CG06.md`；更新 release audit、capacity、external checks 與 `PHASE_STATUS.md`。

### Goal

> 依 `docs/CASUAL_GAME_CANDIDATE_V3_IMPLEMENTATION_PLAN.md` 完成 CG06「全流程回歸、恢復與 100,000 事件容量」。先確認 CG01–CG05 passed；逐條通過 C1–C3 與共同 G1–G7，保存 `evidence/CG06.md` 並更新 `PHASE_STATUS.md`。本 Goal 不建立雲端服務；完成後交付本地發布就緒結論與仍未驗證的外部項目。

## 11. 跨 Phase Goal

> 依 `docs/CASUAL_GAME_CANDIDATE_V3_IMPLEMENTATION_PLAN.md`，從第一個尚未 passed 的 CG Phase 開始，依序完成 CG01–CG06。CV05 不是前置或阻塞項。每個 Phase 必須先通過 C1–C3 與共同 G1–G7、保存 `evidence/CGxx.md` 並更新 `PHASE_STATUS.md`，才能進入下一 Phase。不可刪減驗收、用 mock 冒充整合、覆寫來源／舊報告，或把本地核心失敗列為外部延期。完成 CG06 後交付本地發布就緒報告；真客戶資料、百萬事件、提高候選上限及雲端部署保持未完成，除非使用者另行授權。

## 12. 最終停止條件

只有同時滿足以下條件，才可稱 Candidate Event V3 本地 MVP passed：

- CG01～CG06 全部 passed，且每一項有當前程式版本的 evidence。
- 新舊 run／artifact／cache version isolation 通過。
- 20,000 Discovery、2,000 Validation 與 100,000 事件硬門檻實跑，不是設定值或局部 stage 推論。
- Exploration／holdout、first-match／snapshot、正向回訪／未觀察、72h early／remaining 語意均有獨立真值。
- 主報告、完整 catalog/detail、CSV／JSON／HTML、互動圖與 Agent 引用使用同一不可變數值來源。
- 沒有把關聯寫成因果、把 null 寫成 0、把晚期條件寫成早期，或把未驗證 Discovery 候選寫成 validated。

本計畫不授權建立 Vercel、Railway、託管 PostgreSQL 或 S3，不授權使用真客戶資料，也不授權實作滾動窗口、ROI、IAP、SDK 回傳、投放自動化或任意 App 事件工作台。
