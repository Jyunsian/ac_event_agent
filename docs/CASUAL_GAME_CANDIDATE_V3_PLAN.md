# Candidate Event V3 — Casual Game 多元指標與最小互動圖規劃

狀態：已實作基線；2026-09-11 依使用者決策追加「全量描述、Holdout 增強」政策。逐階段執行、固定政策與驗收 Gate 以 `docs/CASUAL_GAME_CANDIDATE_V3_IMPLEMENTATION_PLAN.md` 為準。

## 0. 最新證據呈現決策

- 主問題是「這批成熟玩家中，高 D7 廣告收益者更常完成什麼事件」，因此主表使用全部成熟玩家的描述性關聯。
- 每個凍結候選都保留全量成熟玩家的符合／未符合人數、覆蓋、D7 ARPU 差與達標時間；這些數字標示為「本批觀察」，不稱獨立驗證。
- Holdout 仍由探索後凍結的條件計算，但只作額外重現證據。符合與未符合任一組少於 `min_group_users` 時標示「Holdout 樣本不足」，不得抹掉全量觀察。
- Holdout 足夠時可標示「重現」或「未重現」。更強的長期證據來自下一批新資料對既有固定條件的重跑。
- 本政策不引入模型訓練、預測分數或交叉驗證。

## 1. 背景與目標

現有 Candidate Event V2 聚焦純 IAA，主要從早期廣告展示、累積廣告收益及資料具備時的 Session／有效時間，尋找能辨識較高 D7 廣告收益用戶的固定事件條件。

V3 擬擴充為 Casual Game 的有限領域分析，在不開放任意產品事件、不犧牲可重現性及統計驗證的前提下，加入：

- Session 與跨日回訪。
- Level start／complete／fail。
- Level 進度、摩擦、重試與持續性。
- Level、留存與 IAA 的受控交叉條件。
- 一張以共同觀察點比較早期與後續變現的最小互動圖。

核心問題：

> 哪些安裝後早期、可以明確實作的行為條件，能在較新的成熟用戶中穩定辨識出較高 D7 廣告收益玩家？

這仍是歷史關聯分析，不是投放因果效果、ROI 保證或自動投放系統。

## 2. 版本與現有範圍邊界

- V2 繼續代表 IAA 候選事件分析；本計畫不改寫 V2 歷史產物、證據或狀態。
- V3 是獨立版本，新增資料欄位、候選 AST、計算版本與 pipeline identity，禁止誤用 V2 cache。
- 主目標仍為成熟用戶完整 D7 廣告收益 `[install, install+168h)`。
- 主要排名仍合併所有 acquisition source；來源只作輔助診斷。
- 固定起點與半開區間不變。滾動窗口仍不納入本輪。
- 第一次分析由 Python 完成，不依賴 LLM；Agent 只協調、搜尋、比較及解釋聚合證據。

## 3. 資料合約擴充

### 3.1 保留事件

- `ad_impression`
- `session_start`
- `session_end`

### 3.2 新增 Casual Game 事件

- `level_start`
- `level_complete`
- `level_fail`

### 3.3 Level 事件欄位

最低需求：

| 欄位 | 要求 | 用途 |
|---|---|---|
| `level_id` | Level 事件必填 | 保留遊戲原始關卡識別 |
| `level_index` | 進度分析必填 | 比較最高進度與到達 Level N |
| `attempt_id` | Start／complete／fail 配對時必填 | 防止不同挑戰錯配 |
| `session_id` | 建議必填 | Session、回訪與關卡行為交叉 |
| `event_time` | 必填 | 固定窗口與序列時間 |

選填欄位：`level_mode`、`difficulty`、`revive_used`、`booster_used`、`app_version`。

只有事件名稱但缺少 `level_id`／`level_index` 時，只允許可證明的事件次數分析；不得補造進度、不同關卡數或到達 Level N。

### 3.4 相容與缺失政策

- 舊 IAA 檔案仍可分析。
- 沒有 Level 事件時，Level capabilities 關閉並列原因。
- 沒有 `session_start` 或 Session ID 不完整時，Session／Retention capabilities 關閉並列原因。
- 缺少某類事件不等於所有用戶該行為為零。
- 未完整觀察指定區間時，不能把「尚未看到回訪」補成 false。
- 完全重複資料可去重；同 identity 不同內容需整組隔離，不任選一筆。

## 4. 指標家族

### 4.1 IAA 廣告與收益

保留 V2：

- 全部及各廣告格式展示次數。
- 全部及各廣告格式累積收益。
- P5～P95 探索分位門檻。
- 1／2／5 × 10^n 固定收益刻度。
- 廣告次數與收益的有限 AND／OR。

### 4.2 Session 與跨日回訪

- 累積不同 Session 次數。
- 首次回訪所需時間。
- `[24h,48h)` 是否回訪。
- `[48h,72h)` 是否回訪。
- `[72h,96h)` 是否回訪。
- 24～72 小時回訪過幾個不同區間。
- 是否連續兩個觀察日回訪。
- 回訪後 Session 次數與有效使用時間。

正向回訪可在區間內第一個合法 `session_start` 到達時觸發；「沒有回訪」只能在區間結束後確認，第一版只作診斷，不作主要即時回傳事件。

### 4.3 Level 次數與進度

- Level start 次數。
- Level complete 次數。
- 完成的不同 `level_id` 數。
- 最高完成 `level_index`。
- 首次完成 Level N。
- 到達 Level N 所需時間。
- 每個 Session 完成關卡數。

### 4.4 Level 摩擦與持續性

- Level fail 次數。
- Fail 後是否重試同一 Level。
- Fail 後是否完成同一 Level。
- Fail 後是否開始下一個 Session。
- 平均每關嘗試次數。
- Complete／Start 比率。
- Fail／Start 比率。
- 完成一關所需時間。
- 同一 Level 連續失敗次數。

Fail 不單獨解讀為負面訊號。高 Fail 可能代表流失，也可能代表高投入；應優先與 Retry、Complete、Session return 交叉。

### 4.5 跨 Category 組合

只建立有產品意義的兩原子條件：

- Level progress × Session return。
- Level progress × IAA revenue。
- Fail／Retry × Session return。
- Level complete × Rewarded ad。
- Retention × 後續廣告收益。

不允許所有事件任意兩兩交叉。

### 4.6 有限行為序列

第一版只支援預註冊兩步模板：

- Level start → Level complete。
- Level fail → Level start。
- Level fail → Level complete。
- Level fail → Session end。
- Session start → Level complete。
- Level complete → Ad impression。
- Rewarded ad → Level complete。

序列需固定最大間隔、重複次數、觀察窗口，以及是否要求相同 `level_id`／`attempt_id`。第一版不支援任意三步以上序列。

## 5. Category 專屬時間窗口

不同指標不強制套用相同窗口：

| Category | 建議窗口 |
|---|---|
| IAA 收益與展示 | 1、3、6、12、24、48、72、96、120、144h |
| 累積 Session | 3、6、12、24、48、72、96、144h |
| 跨日回訪 | `[24,48)`、`[48,72)`、`[72,96)` |
| Level 次數／一般進度 | 1、3、6、12、24、48、72h |
| 最高 Level／到達 Level N | 1～72h，加 96、120、144h |
| 比率／摩擦 | 6、12、24、48、72h |
| 行為序列 | 1、3、6、12、24、48h |

縮減原則是產品與時間語意，不是依 holdout 結果事後刪除。前 1 小時分母過小的比率不大量生成；短序列不無必要延伸至 144 小時。

## 6. 兩層候選搜尋

### 6.1 Discovery Pool

第一層上限先設定為 20,000 個探索候選，只讀較早的 exploration 用戶，計算：

- 觸發者／未觸發者人數。
- 覆蓋率。
- 探索 D7 ARPU 差。
- 觸發時間 P50／P90。
- 精確命中人群與相似度。
- 是否具備進入完整驗證的最低樣本。

這一層不跑完整家族 Holm，不稱獨立驗證。全部結果仍保存候選條件、探索數字、是否進入驗證及未進入原因。

### 6.2 Validation Family

第二層暫時維持最多 2,000 個，才執行：

- Holdout 重新計算首次觸發。
- 1,000 次 user-level bootstrap。
- 單尾 Welch。
- 全凍結家族 Holm 校正。
- 前段／剩餘／D7 收益分解。
- 每日穩定性與 acquisition source 診斷。
- 完整候選證據卡。

暫不直接提高 2,000，原因：

- V2 百萬事件／2,000 候選尚未通過既定完整容量限制。
- 增加候選也會提高 Holm 的多重比較懲罰。
- 新增 Casual Game 指標後的實際候選量與重複程度尚未量測。
- 報告、證據卡與完整匯出成本也會隨候選數增加。

提高至 3,000／4,000 需另作容量與統計影響決策，不作本版預設。

## 7. 完整驗證預算

初始 2,000 名額：

| Category | 名額 |
|---|---:|
| IAA 廣告與收益 | 350 |
| Session 與跨日留存 | 300 |
| Level 次數與進度 | 450 |
| Level 摩擦與效率 | 300 |
| 跨 Category AND／OR | 400 |
| 行為序列 | 200 |
| 合計 | 2,000 |

若某批資料缺少整個 capability，可依預先固定規則回補名額；不得看完 holdout 結果後調配。

## 8. Discovery 到 Validation 的去蕪存菁

### 8.1 完全相同命中人群

- 所有候選仍保留在 Discovery 紀錄。
- 只選一個語意較簡單、觸發較早的代表進完整驗證。
- 其餘標記 `IDENTICAL_MEMBERSHIP_ALTERNATIVE`，不稱效果差。

### 8.2 樣本注定不足

- 保留條件、人數、覆蓋與原因。
- 標記樣本不足。
- 不執行昂貴 bootstrap，不占完整驗證名額。

### 8.3 無資訊門檻

同一窗口／Category 的連續門檻若覆蓋、收益差及命中人群幾乎相同，只選擇有明顯取捨變化的轉折點進驗證；其他點留在探索曲線與搜尋紀錄。

### 8.4 Category 內 Pareto

各 Category 分別看：

- 探索 D7 差較大。
- 覆蓋較廣。
- 觸發較快。
- 與已選候選人群重複較少。

避免數量較多的 IAA 收益門檻擠掉 Level／Retention 訊號。

### 8.5 受控父條件

跨 Category AND／OR 只使用各窗口、各 Category 的有限強父條件。禁止把 Discovery Pool 全體兩兩排列。

## 9. 時間與資料洩漏政策

- 所有 indicator 必須在其宣告觀察終點前成立。
- `[24,48)` 回訪最早在安裝後 24 小時觸發；剛好 48 小時不屬此區間。
- `[48,72)` 回訪最早在安裝後 48 小時觸發。
- D7 Top 10% 不能再作為預測 D7 的輸入條件。
- 門檻只由 exploration 產生；holdout 不得改門檻、預算或優先名單。
- 越晚的 indicator 留給投放系統使用的時間越少，報告必須同時顯示最早可觸發時間、實際 P50／P90、完整 D7 與共同觀察點後的剩餘收益。
- 晚期回訪與 D7 收益的關係可能部分來自更多變現機會，必須另看共同觀察點後收益，不能直接稱增量。

## 10. 最小互動圖 MVP

互動圖只做一張二維候選散點圖，主線仍是多元指標與驗證。

### 10.1 固定觀察點

第一版固定安裝後 72 小時，原因：

- `[24,48)` 與 `[48,72)` 回訪已可觀察。
- Level 進度已有一定資訊。
- 仍有 `[72,168)` 共 96 小時可觀察後續變現。

### 10.2 圖表定義

每個點代表一個完整驗證候選：

- X 軸：觸發者－未觸發者在 `[0,72h)` 的廣告收益 ARPU 差。
- Y 軸：觸發者－未觸發者在 `[72h,168h)` 的廣告收益 ARPU 差。

只納入在 72 小時前可完整判定 membership 的候選。觀察終點晚於 72 小時的候選仍保留於完整結果及證據卡，但不放入此圖，避免用未來行為替過去分組或讓候選條件與 Y 軸收益期間重疊。

四個閱讀區域：

- 右下：偏早期大量看廣告，後續價值有限。
- 右上：早期變現且後續繼續變現。
- 左上：前期收益不高但後期成長。
- 左下：目前價值訊號較弱。

只使用「前段收益差」「後續收益差」，禁止寫成因果增量。

### 10.3 第一版互動

- Category 篩選。
- Hover 顯示候選條件、兩段收益差、樣本與覆蓋。
- Click 打開既有完整證據卡。

第一版不做：

- 多種顏色或圓點大小編碼。
- 24／72／144h 切換。
- 自訂 X／Y 軸。
- Source 切換。
- 動畫路徑。
- 用戶級散點與個資輸出。

### 10.4 Python 圖表產物

Python 預先輸出：

- `candidate_id`
- `category`
- `checkpoint_hours=72`
- `early_difference_usd`
- `remaining_difference_usd`
- `coverage`
- `evidence_status`
- `triggered_users`
- `untriggered_users`
- `detail_sha256`

前端只渲染及篩選，不重新計算。空值保留 null，不能補零。圖表資料、候選詳情與報告需用 run／dataset／report version／hash 綁定。

## 11. 報告與匯出

### 11.1 優先比較

增加：

- Category／indicator type。
- 最早可觸發時間。
- 是否包含跨日回訪。
- 72 小時前收益差。
- 72～168 小時收益差。

### 11.2 全部結果

新增 Category 篩選：

- IAA。
- Session／Retention。
- Level Progress。
- Level Friction。
- Cross-category。
- Sequence。

### 11.3 搜尋紀錄

分開顯示：

- Discovery 生成數。
- 邏輯等價數。
- 相同命中人群數。
- 樣本不足數。
- Category 配額外數。
- 進入完整驗證數。
- 完整驗證結果數。

### 11.4 完整 CSV

增加：

- `category`
- `indicator_type`
- `observation_start_hours`
- `observation_end_hours`
- `earliest_trigger_hours`
- `early_difference_usd`
- `remaining_difference_usd`
- `discovery_status`
- `validation_status`

主報告可維持少數優先候選；完整候選 CSV／JSON／HTML 必須包含全部實際完整驗證結果。Discovery 未進驗證的候選另存搜尋紀錄，不冒充已驗證。

## 12. 分階段實作與驗收

### CG01：資料合約與手算真值

- 新增事件 schema、Level／attempt 配對與回訪區間。
- 建立舊 IAA 相容及缺欄位負例。
- 手算 `[24,48)`、`[48,72)`、同 Level retry、不同 attempt、邊界與未完整觀察。

Gate：剛好 48h 不算前一區間；同一次 attempt 不重複完成；不同 Level／attempt 不錯配；缺 `level_index` 不補造進度。

### CG02：多元特徵

- Session／Retention。
- Level progress。
- Level friction／Retry。
- 指定區間特徵與 capability quality。

Gate：零事件用戶保留；未完整觀察不補 false；各指標在固定時間與 identity 規則下可手算重現。

### CG03：兩層搜尋與預算

- 20,000 Discovery Pool。
- Category 預算及固定回補。
- 精確命中人群去重、樣本先篩、Category 內 Pareto。
- 凍結最多 2,000 Validation Family。

Gate：改 holdout 不改 Discovery／凍結；所有未進驗證者都有原因；單一 Category 不壟斷預算。

### CG04：完整驗證

- 全部凍結候選 holdout。
- Bootstrap、Welch、Holm。
- D2／D3、72h 共同收益分解、每日與 source 診斷。

Gate：全家族完成才發布；晚期 indicator 不冒充早期；後續收益嚴格使用 `[72,168)`。

### CG05：報告與最小互動圖

- Category 篩選。
- 72h 二維散點圖。
- Hover／click evidence card。
- 完整 CSV 欄位與離線 HTML。

Gate：圖表值與 Python 產物完全一致；前端不重算；null 不補零；無因果／增量宣稱。

### CG06：回歸與容量

- V2 IAA 回歸。
- Casual Game 手算及端到端 fixture。
- Casual Game 100,000 事件、最多 2,000 完整候選容量。
- 報告、圖表、完整 CSV、catalog/detail 一致性。

第一版以 100,000 事件為本地 MVP 容量驗收。1,000,000 事件及提高 3,000／4,000 候選另作容量決策，不以縮減 bootstrap 或放寬資源門檻冒充通過。

## 13. 非目標

- 任意 App 事件自由分析。
- 每日動態 Top 10%／Top 20。
- 滾動窗口。
- 任意三步以上序列。
- SDK 即時回傳。
- 廣告平台自動投放。
- 每用戶獲客成本與 ROI 計算。
- 因果提升保證。
- 複雜圖表工作台或自訂指標拖拉。
- 用戶級個資散點或原始 log 送入模型。

## 14. 建議執行順序

1. 固定 Casual Game 資料與時間語意。
2. 完成 Session／Retention、Level progress、Level friction 特徵。
3. 建立 Discovery／Validation 兩層搜尋及 Category 預算。
4. 完成全部凍結候選的 holdout 與統計驗證。
5. 擴充完整報告及客戶匯出。
6. 最後接入單一 72h 二維互動圖。
7. 完成 100,000 事件端到端與回歸後，再決定是否測更高候選數或百萬事件。
