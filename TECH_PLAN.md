2026-09-17 最新授權：首次全部部署 Railway；共享密碼、獨立空白資料庫＋合成示範、US$50/月目標（模型另計）。狀態以 evidence/RAILWAY-DEPLOY.md 為準，以下舊部署目標保留歷史。

# V4 已確認增補（2026-09-17）

2026-09-17 最新表格文案：欄名使用「達標時間」「Holdout 驗證」，時間以「平均／50%／90%」表示；狀態簡寫「收入較高：已驗證／未確認」「資料不足」「尚未驗證」「僅供探索」。不使用對話式問句。

2026-09-17 時間與驗證文案：時間欄改「多久達成條件」，對截至所選時間已達標且首次時間可靠的玩家計算平均／中位數／九成時間，從安裝或首次開啟起算。未知時間不補值，固定時點規則不推算。Holdout 用「換一批玩家，結果還成立嗎？」與白話狀態；舊產物沒有平均時顯示尚無法判斷。

2026-09-17 最新呈現決策：正式 Web 與 mock 移除自動配對收入門檻的比較欄位、詳情與相對優勢狀態；保留行為符合／未符合比較及其 Holdout。底層收入對照計算、機器產物及既有報告保留，不重新選擇候選。

2026-09-17 文案更新：右側概覽只保留數據、圖表、篩選及證據狀態；方法解說按需讀取。七天平均收入比較明寫比較對象與高／低／相同，缺資料顯示無法比較；收入門檻人群不得稱為全體平均。

2026-09-17 review 修復契約：後來的缺失資料不得抹去先前可靠首次達標；第一天未知者不能算成第一天漏掉的人，無可比較母體時顯示不適用。Web、Agent 與離線比較均提供全量／找規律／Holdout；Agent 按指定觀察時間讀取三群，預設 24h，維持 128 KiB 上限。詳見 evidence/V4-REVIEW-FIXES.md。

2026-09-17 呈現增補：V4 主表提供全量、找規律（探索集）、Holdout 三個玩家範圍；全量包含另外兩群，三者不得相加。主表並列玩家價值、辨識規模、辨識速度、同時間收入對照與 Holdout 可靠性，不計算綜合分數。Holdout 分開呈現收入關聯與相對收入門檻的證據；明細提供收益分解、人數與差異區間。全量描述與驗證結果清楚分開，見 evidence/V4-FIVE-FACTORS.md。


本次新增 V4 時間分析與規則比較，執行基線見 `docs/CANDIDATE_V4_IMPLEMENTATION_PLAN.md`；實際完成範圍以 `PHASE_STATUS.md` 為準。首次達標、多天新增玩家、連續 24h、既有規則和收入對照是本版方向；不加入 ML，不宣稱唯一最佳回傳期限。舊版本文件保留作歷史，不代表 V4 已完成。

# Technical Implementation Plan — 資料優先的互動分析工作區

## Candidate V2 技術增補（已批准，CV05 驗收中）

V2 搜尋/統計/交付依 docs/CANDIDATE_V2_PLAN.md，優先於下文 V1 的前 10 個 finalist 驗證方案；其餘架構與資料保護不變。

- 全部候選與優先名單分離；完整目錄 v2 綁 run_id、dataset_id、frozen_sha256、evaluated_count、priority_ids 與逐候選 detail_sha256。最多 2,000 個評估項、10 個優先項；168h 不進優先。
- server/analysis/v2_contract.py 固定版本政策及完整目錄身分檢查。首報告保留精選 candidates；完整明細以獨立版本化產物存 S3，由帶 run/report version 的分頁 API 讀取。
- 計算仍 DuckDB/Parquet 與持久 Worker；全家族 Holm 校正完成後才能發布證據狀態。既有 bootstrap 是描述性區間，不改稱校正後區間。
- Predicate evaluator 1.4 在同一已驗證、不可變輸入連接內，按精確(op,ad_format,threshold)重用原子首次觸發表；每個候選另以其原窗口嚴格截止時間篩選，最後一次使用後立即釋放。理由是全特徵期間的最早達標若不在前W小時，前W小時就不可能另有更早達標；並非把晚期達標算進早期窗口。只減少相同GROUP BY重算，不合併候選、不改AND/OR時間規則、首次觸發或全家族數量。中間表仍受原DuckDB/Worker資源限制；源hash、holdout scope與最終全排序產物檢查保留，沒有全局跨來源快取。
- 選擇階段先驗證所有trigger屬於原探索母體/候選，再在該stage暫存DB一次映射到穩定用戶整數索引與原觸發delay。逐候選仍檢查重複、用完整探索母體計兩組均值/分位、保留精確bitmap與Pareto/Jaccard；均值依原app/user排序，不以總額相減推估對照。無觸發條件共用同一完整對照組的有序平均，仍全數保留。暫存DB位於Worker工作目錄，受原配額、完成後清理；不寫回來源或報告。
- SciPy/Welch 分布近似與高容量成本是待測方法假設，不是已驗證事實。零變異不算自動通過；逐日/來源/剩餘收益不混用分母。
- CV05 bootstrap 使用兩種精確經驗抽樣的固定成本選擇：總用戶N<=262144且N<=32×收益/身份類別數K時，按完整用戶權重展開並抽均勻索引；否則採多項分布類別計數。相同收益值保留用戶數權重，hit/all共同抽樣保留hit身份。仍為1000次user-level percentile bootstrap，非常態／Poisson近似，不四捨五入收益或跳過不足樣本。NumPy 2.5.3鎖版；PCG64/SeedSequence三串流及`empirical_hybrid_v4_shared_counts_PCG64`方法明示。索引路徑與先前純multinomial/Python RNG抽樣序列不同，依計算版本隔離，不宣稱舊區間端點逐值相等。矩陣最多32列、約8MiB/矩陣為批次目標（多個矩陣可共存），用戶展開最多約2MiB/完整向量；超大母體不無界展開。只快取相同精確經驗分布/seed/次數，最多1024筆且每筆最多8192類別，超出不快取。key用精確float64/int64二進位（每類16bytes，最大約128MiB key，另有抽樣結果開銷），不用四捨五入或僅摘要雜湊判等。此選擇由N/K決定，不根據計時或驗證結果挑方法；原Worker資源上限不變。重複收益較多時計數法節省工作，較多不同值時索引法避免大量binomial子抽樣；總成本仍須完整容量實測。無新增服務或付費成本。依據：[NumPy multinomial](https://numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.multinomial.html)與[均勻整數索引](https://numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.integers.html)官方說明。以手算分布/權重/共同抽樣、逐用戶獨立參考及重現测试驗證。
- 驗證連接內先按凍結窗口預聚合每位成熟holdout用戶的窗口前/後收益，再按每候選的觸發／landmark身份分組；不快取候選身份、不改未知與零事件語意。每位用戶收益按值固定加總順序，避免join計画造成浮點歸約順序漂移。連接內targets/events必須不可變；原資料及舊報告不重寫。
- API、Agent 工具、HTML/CSV/JSON 與前端需同步支援 v2；v1 保持唯讀相容，新欄位缺失不得補造。V2 計算版本使舊搜尋/驗證快取失效。


版本：0.3（需求／選型基線）｜日期：2026-09-09｜實作狀態：PH01–PH42本地驗收通過；真模型／雲端／真客戶仍未驗。下文規劃語氣不代替PHASE_STATUS及evidence現況。

- CV05 驗證內新增 invocation-local 精確 membership memo：同一份已驗證成熟用戶順序、收益、日期、source 與統計規則下，只在完整 bitmap 相等時重用 metrics/Welch/source；每候選仍重算 delay 分位、各自 W 的收益分解與 landmark，保留每個候選及整批 Holm。最多256筆、序列化 key/value 合計32MiB，超大結果旁路；取回新的巢狀物件，避免 checkpoint 或校正狀態互相污染。memo 不跨任務／資料／規則，也不持久化；新模組納入 pipeline hash。容量改善仍須實跑，不能以快取命中數宣稱通過。

- StageRunner 在 builder 完成且 PG/S3 checkpoint 發布成功後釋放該stage已關閉的 `work.duckdb`／`scope.duckdb`及其WAL/已識別spill。後續階段與恢復均讀同一批正式Parquet/manifest，不依賴這些本來就未發布的工作DB。只刪白名單暫存，保護manifest宣告及已發布artifact、未知檔案與symlink；build/publish失敗時不清理診斷。這是工作檔生命週期改善，不抬高磁碟或CPU配額。

- 固定浮點歸約次序：target逐用戶廣告收入依精確收益值排序加總，split總額/平均依app/user排序；同時間feature delta先依delta值歸約，再依唯一available_at累積；既有diagnostics/segment總額亦固定順序。target calculation_version為1.1_ordered_revenue_reduction，FEATURE_VERSION為1.1，避免舊feature identity混用。未四捨五入門檻、未改缺值/成熟/窗口規則；既有產物bytes不改。
- 選擇階段有序平均使用已由app/user穩定排序建立的membership_index作ORDER BY，保留完全相同加總順序，減少重複字串排序；需與原完整selection manifest精確對照，不以近似比較宣稱不變。

- Bootstrap indexed路徑將固定分母除法移至來源向量，common-cohort sampled矩陣原地mask/divide，避免每個replicate多份相同大小的copy。PCG64串流、抽樣次數、浮點除法操作數與逐row加總順序保持，原矩陣參考逐draw精確相等；method不變，仍由計算版本隔離產物。單階段及完整容量另驗，不由減少配置次数推論效能。

- V4 對適中母體額外重用原stream2的完整抽樣位置次數：N在2048–65535且N×replicates×4<=128MiB，counts/prefixes各uint16、單筆LRU、唯讀，僅快取隨機次數而不快取收入/身份。原hit/miss分層抽樣及其gate區間保持逐draw不變；hit/all同一批抽樣以次數加權歸約，因此末位可能與v3不同，方法明示版本而不冒稱逐位相同。極大/極小數值、超預算均旁路至原divide-before-sum，未降低1000replicate或抬Worker配額。增加最多128MiB常駐隨機矩陣，換取每候選不重建共同抽樣索引/大型樣本矩陣；無新套件/服務成本，實際效能另驗。

## 1. 決策摘要

- Validation固定窗口收益分解可在同一次不可變收入窗口表上重用，但key必須包含精確float64窗口及完整membership bitmap，不能只憑人群相同跨W重用。獨立memo仍各限256筆/32MiB，返回新的JSON物件；加上既有統計memo最多兩份有界cache，Worker1536MiB上限不變。Landmark仍按各自截止時間逐項計算，未共用候選窗口key。測試需確認相鄰float窗口不同key、不同membership隔離、快取開關全結果精確相同，source/hash/未知/分解加總檢查不移除。

- Snapshots先以實際timeline按用戶/窗口/metric/format求max，再LEFT JOIN完整users×windows×dimensions；沒有事件的組合仍全部輸出，不把unknown/disabled/incomplete補成已知零。避免先對大量全零維度建立GROUP BY state，FEATURE_VERSION1.2與數值語意不變。百萬資料完整manifest及timeline/snapshots SHA與原1.2精確相同，原Limits單stage量測另見evidence/CV05；不據此宣稱整體容量通過。

- Predicate evaluator1.6讓原子/AND/OR查詢直接COPY到各候選有序part，不先INSERT到TEMP triggers再複製；sequence仍使用原Python分批buffer。命名參數隔離窗口、候選ID及目的路徑，無動態輸入SQL拼接。1.5的part排序、受限臨時目錄、首次觸發與校驗保持；需新舊完整產物對照，不直接宣稱效能通過。
- 選擇階段在同一探索連接內，以原完整membership bitmap為key，LRU最多256筆重用兩組人數與有序均值；key引用本來已保留的hit_sets整數，不額外複製身份清單。P50/P90每候選讀自身delay重新算，重複/越界觸發仍先拒絕，Pareto/Jaccard及樣本gate不變。啟用/禁用memo全selection manifest精確對照及原百萬輸入量測是驗證門檻。

- 搜尋維度表按app/user一次建立整數membership_index，各threshold的兩組avg依該index排序，保持原字串有序加總的操作順序、減少重複字串sort。只用探索資料，P90/門檻/支持數/多維父條件選擇不改。需對不可變舊輸入的完整search manifest精確比對，再由完整容量實測判斷效益。

- FEATURE_VERSION 1.2 有序feature加總採metric/ad_format互斥分批：每批保留原GROUP BY timestamp、sum(delta ORDER BY delta)及用戶內累積window，最後維持同一全排序輸出。避免全部維度有序聚合state同時佔用256MB；窗口及同時間語意不變，但DuckDB window歸約分組可能使累積收入末位不同於1.1，因此明示新feature identity／pipeline版本，舊產物不重寫。原全維度SQL對照僅收入值允許rel1e-14/abs1e-15，非收入值與全部身份/時間精確相同；新版本threads2/2/1的完整manifest/Parquet bytes仍必須完全相同，不以容差放行重現。完整百萬特徵階段與全pipeline另驗，不能以小型通過外推容量。門檻仍使用新版本原始精確計算值，不四捨五入或放寬統計gate。

- Predicate evaluator 1.5 保留 1.4 首次觸發／跨窗口重用規則，將輸出暫存改成逐候選 TEMP table → 有序 Parquet part → 按 candidate ID 排列的明確檔案清單合併。parts 使用內部數字檔名與 stage 內 TemporaryDirectory，發布前清除；不把 candidate ID 當路徑。明設 preserve_insertion_order=true，避免整張觸發表的持久 WAL 與全量字串排序；代價是兩次 Parquet 編解碼及每候選 COPY，效能需實測。依據 [DuckDB order preservation](https://duckdb.org/docs/current/sql/dialect/order_preservation)，並以實際物理讀序、反向候選順序的 bytes 重現及完整參考產物對照驗證；未新增依賴或降低資源門檻。

### 2026-09-09 使用者確認的部署更新

測試模型選定`z-ai/glm-5.3-flash`（OpenRouter）；前端部署Vercel，後端部署Railway。順序為先完成測試，再執行雲端部署，目前不建立服務。後端範圍為FastAPI／Python計算Worker／Node Agent Worker；PG／S3供應商、區域、資源額度與入口保護待部署前確認。此決策取代下文早期「單台雲端VM＋Compose」的正式目標；Compose與三images仍保留為已驗本地部署包。Vercel／Railway適配、跨服務連線、上傳CORS、背景任務與重啟持久性尚未實驗，不因平台選定就宣稱已部署或相容驗收完成。

產品主流程固定為：上傳資料 → Python 完成基礎分析及第一份報告 → 使用者進入 Agent 對話 → Agent 調用預先封裝的 Python 工具，建立深入分析分支。第一份可用結果不依賴 LLM，不由 Agent 臨時決定資料清理或基礎計算流程。

採用 React + TypeScript + Vite 操作介面、FastAPI API、獨立 Python Worker、DuckDB + Parquet 分析、PostgreSQL 保存任務與中繼資料、S3 物件儲存保存原始檔與產物。以 Docker Compose 部署到單台雲端 Linux 主機，PostgreSQL 與物件儲存使用外部持久服務。

這是依目前需求提出的工程選擇，不是效能測試結果。具體雲端帳號、區域、模型與預算尚未指定，不影響先確立程式架構；不在本輪建立或購買服務。

### 已確認約束

- 內部團隊上傳資料、分析後交報告給客戶。
- 可部署上線；不只是一個本地 Notebook。
- 不做登入、會員、使用者角色或租戶系統。MVP 為單一共享工作區。
- 主要關注功能、使用流程與持久性。
- 可能數千至數十萬用戶、數百萬事件；真實資料大小未知。
- Python 計算、Agent 協調與解讀；純 IAA、D7 收益、小時及天級窗口。

## 2. 技術選擇與替代方案

| 部分 | 推薦 | 理由與代價 | 目前不選的路徑 |
|---|---|---|---|
| 前端 | React + TypeScript + Vite | 適合上傳、映射、進度與結果比較；靜態部署；需維護前端與 Python 兩個環境 | Next.js 的伺服端渲染非當前需求；Streamlit 作原型可行，但本版選獨立 UI |
| API | FastAPI + Pydantic | Python schema 驗證，HTTP 契約與分析層一致 | 不把長分析塞入 HTTP 請求 |
| 分析 | DuckDB SQL + Parquet，NumPy 處理小型統計陣列 | 支援窗口／聚合與磁碟運算；仍須控制記憶體與暫存量 | 不以全量 pandas 為核心；Polars 暫作替代，不同時導入雙引擎 |
| 中繼資料 | PostgreSQL；SQLAlchemy + Alembic 管理存取／遷移 | 保存資料集、配置、任務、產物版本；額外一個持久服務 | 不用瀏覽器狀態或 Worker 本地 SQLite 作共享事實來源 |
| 任務 | PostgreSQL 任務表 + 獨立 Python Worker | 一個計算任務並行起步，減少額外服務 | 暫不引入 Redis／Celery；代價是必須實作並驗證租約與重試 |
| 大檔儲存 | Amazon S3，經 S3 介面封裝 | 原始檔、標準化資料、報告獨立於容器生命週期 | 不把 log 塞入 PostgreSQL，也不以容器磁碟作唯一副本 |
| Agent | Vercel AI SDK ToolLoopAgent + OpenRouter provider（TypeScript／Node.js） | 現成 Agent loop，經 OpenRouter 選模型；工具透過內部 API 接 Python | 不再採 Claude Agent SDK；代價是增加 Node.js Agent Worker |
| 報告 | Web 檢視 + 可攜 HTML + JSON／CSV | 客戶可離線看報告，工程可讀事件規格 | PDF 排版先延後 |
| 部署 | Docker Compose、HTTPS 反向代理、長駐 API／Worker | 單機運維起步，計算與 API 分程序 | 暫不引入 Kubernetes，長任務不依賴短生命週期函數 |

以上是本專案取捨，並非宣稱替代方案無法做到。Vite 官方支援靜態 build，但 preview 不是正式伺服器；正式環境由反向代理提供靜態檔。[Vite 部署文件](https://vite.dev/guide/static-deploy.html)

FastAPI 官方對重計算提出獨立背景工具的建議，因此本案明確分離 API 與 Worker；持久佇列由下述任務合約提供。[FastAPI 背景任務](https://fastapi.tiangolo.com/tutorial/background-tasks/)

## 3. 執行架構

~~~mermaid
flowchart LR
    UI[瀏覽器：上傳／設定／結果] --> API[FastAPI]
    UI -->|預簽名分段上傳| S3[S3 原始檔與產物]
    API --> PG[(PostgreSQL 配置／任務)]
    W[Python Worker] -->|領取與回報| PG
    W -->|讀寫| S3
    W --> D[DuckDB 暫存分析]
    A[Node.js Agent Worker] -->|工具請求／聚合證據| API
    A --> OR[OpenRouter 模型 API]
    API -->|保存 Agent 狀態／建立計算任務| PG
~~~

API 和 Worker 可以用同一 Python image、不同啟動命令。Worker 每次只執行一個重分析任務，子程序執行計算；主程序持續發送心跳。API 不持有全量 log，不直接開啟 Worker 的 DuckDB 檔。

另加長駐 Node.js Agent Worker image，使用 Vercel AI SDK，不需要部署到 Vercel，也不要求改成 Next.js。Agent 經內部 FastAPI 端點領取 Agent 任務、續租與提交狀態；Python Worker 只領取計算任務。兩種任務分開，避免 Agent 等待自己占住的計算 slot。

每個 run／attempt 有自己的分析目錄。DuckDB 為任務內計算引擎；共享任務狀態放 PostgreSQL，跨程序不共享可寫 DuckDB 檔。[DuckDB 並行模型](https://duckdb.org/docs/current/connect/concurrency)

## 4. 使用流程

1. 建立分析專案：App 名稱與客戶標籤僅作整理，不是權限。
2. 上傳用戶表、事件表、匯出說明；支援多個事件檔。
3. 檢視資料樣本及 schema，保存欄位映射與完整截止時間；品質檢查在背景完成。
4. 設定 D7、候選窗口與搜尋預設；顯示可用／不可用分析方向。
5. 建立分析任務，取得永久 run URL。
6. 進度頁顯示已完成階段、處理筆數（可取得時）、警告與失敗原因；未知時不偽造百分比。
7. Python 完成基礎分析與模板報告後，顯示結果工作區：候選、證據、敏感度、重疊，以及 Agent 對話區。沒有 OpenRouter key 仍能看結果及匯出。
8. 使用者提問，Agent 先讀現有產物；需要新計算時建立子 run，顯示工具卡與進度，完成後引用新結果回答。
9. 歷史頁保存基礎報告、對話與分析分支；更改條件建立新 run，不覆蓋舊結果。匯出時明確選擇基礎版或某個分支版本。

### 工作區狀態

- uploading／mapping／processing：顯示上傳與 Python 進度；尚不啟動分析 Agent。品質失敗顯示修正入口。
- ready：已有可讀基礎產物，才啟用對話。若核心資料不足以推薦但品質診斷已完成，可提供說明型對話，停用不可用計算工具。
- turn_running：呈現使用者問題、工具名稱、計算狀態與結果引用；使用者可閱讀其他既有結果。
- turn_failed／cancelled：保留舊報告及已完成工具結果，可重試該 turn。單一對話一次一個 active turn，新問題排隊，避免交錯寫入上下文。

結果面板與對話面板共享 selected_run_id。Agent 回覆顯示所引用 run／artifact 的連結；新分支不默默替換使用者正看的舊報告，提供「查看新結果」操作。

MVP 用定期輪詢取得狀態，不先加入 WebSocket。已完成上傳後關閉分頁不影響分析；上傳中關閉分頁不代表檔案已完整送出，重開需重選本地檔案才能續傳。

## 5. 上傳與檔案持久性

以下資料實作接續第 4 節 UI 流程；視覺與分欄規格見第 12 節。

- API 建立 dataset／upload 紀錄與唯一物件 key，回傳短效預簽名分段上傳 URL。
- 瀏覽器直接傳 S3，避免大檔通過 API 記憶體。保存 upload_id、已完成 part 編號與 ETag。
- complete 端點向儲存服務確認完成、大小與校驗資訊，再將 dataset 設為可處理。multipart ETag 不視為全檔 MD5。
- Worker 標準化為型別固定的 Parquet，使用適量分片；分片方式依資料量測試，不建立每人一個檔案。
- 原始資料與已發布產物用不可變的唯一 key；重跑建立新版本。
- SQL、HTML 與路徑不得直接執行或信任上傳文字；映射只允許已知欄位及操作。
- 半成品不上報為完成；只有已驗證且寫入 manifest 的產物才可出現在結果頁。
- 保存映射、配置、輸入指紋、schema／程式版本、模型／prompt 版本與產物 checksum。

S3 分段上傳支援重試個別 part；未完成的 multipart 需要中止或生命週期清理。僅清理過期未完成上傳和可重建暫存，不自動刪客戶原始檔。[S3 multipart](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html)

## 6. 任務持久性與恢復

### 最小資料模型

| 表 | 主要內容 |
|---|---|
| projects | App／客戶標籤、建立時間 |
| datasets、uploads | 檔案 manifest、版本、上傳狀態、欄位映射與品質摘要 |
| runs | dataset 版本、不可變配置、狀態、進度、錯誤摘要 |
| job_attempts | stage、attempt、租約、心跳、開始／結束時間、重試原因 |
| artifacts | 物件 key、hash、類型、schema 版本與已提交的 attempt |
| report_versions | 分析產物引用、敘述版本、模型資訊與生成狀態 |
| conversations、messages | 綁定基礎 run、訊息序號、使用者內容、Agent 回覆、工具結果引用 |
| agent_turns、tool_executions | turn 狀態、冪等 key、工具參數、子 job／run、已提交步驟 |
| validation_exposures | dataset／split 版本、結果首次揭露時間、來源 run；用於跨對話驗證污染追蹤 |

runs 增加 kind（baseline／followup）、parent_run_id、root_run_id、source_turn_id、config_hash、split_id、evidence_status。每個 run 綁不可變 dataset 版本；對話預設沿用該版本，新上傳建立新 baseline，不能悄悄換資料。

狀態：queued → running → succeeded／failed／cancelled。analysis_status 與 narrative_status 分開保存，模型失败不使數值結果失效。

### 執行合約

- 建立 run 與 queued job 使用同一交易；重複提交以 idempotency key 回傳同一 run。
- Worker 使用短交易及 FOR UPDATE SKIP LOCKED 領取任務並寫租約；計算時不持有長交易。
- 心跳／租約初始建議 15／90 秒，可調。過期任務可被重新領取，重試上限初始 3 次。
- 每次領取遞增 attempt／fencing token；狀態與 manifest 提交必須匹配現任 token，過期 Worker 不能覆蓋新結果。
- 至少一次執行，非 exactly-once。各階段冪等；attempt 寫獨立物件前綴，成功後以 DB 交易發布 manifest。
- 已完成階段 checksum 驗證成功可重用；中斷中的 SQL 從該階段重算，不宣稱任意指令斷點續跑。
- DB 寫入失敗時不標成功；重啟後根據已提交 manifest 恢復。未引用產物可作孤兒清理，但不刪來源。
- 取消以 DB 旗標及計算子程序中止實作；發布結果時再次檢查取消狀態。
- 網路短暫失敗可以退避重試；schema 錯誤立即失敗；OOM 不反覆用相同設定自動重跑。
- API／Worker 重啟、瀏覽器關閉都不清空歷史。模型重試恢復對應 turn，重用已完成工具產物，不重跑基礎分析。

SKIP LOCKED 是 PostgreSQL 文件列出的 queue-like table 用途，但不是完整佇列系統；上述租約、冪等、取消與故障測試是本案必須承擔的工程工作。[PostgreSQL SELECT](https://www.postgresql.org/docs/current/sql-select.html)

## 7. 分析核心

### 計算階段

校驗與去重 → 正規化 Parquet → D7 成熟用戶與時間切分 → 行為累積／首次達標特徵 → 候選生成 → 固定候選驗證 → 重疊與推薦 → 報告。

上述 baseline 為版本化確定性 pipeline，使用預設配置，不調用 LLM。至少保存 quality.json、dataset_profile.json、features manifest、split manifest、candidates.json、metrics.json、overlap.json、report.html。資料缺少某類欄位時產出 capability flags，供 UI 與 Agent 工具共同使用。

### 重跑與快取

- 單純解釋、比較既有候選：讀現有聚合產物，不排計算任務。
- 新窗口／門檻／分群：建立 followup run，重用型別整理與去重後的 Parquet；若既有特徵足夠，只重算相關指標。
- 沒有足夠時間粒度的中間特徵：掃標準化事件，不以日級聚合猜小時級結果。
- 快取 key 包含 dataset fingerprint、映射／清理版本、split、特徵定義、完整配置、計算版本與種子；只有完全相符才重用。
- 同批資料下，分群報表保留既有成熟用戶與切分，不能重新切分來取得更漂亮的驗證結果。

DuckDB 支援超出記憶體的部分工作負載並可 spill 到磁碟，但不是所有操作都受 memory_limit 完整限制。對 join、排序、窗口計算及統計陣列仍須測試。[DuckDB 效能指南](https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads)、[記憶體限制](https://duckdb.org/docs/current/guides/performance/oom)

Polars 也支援 streaming，保留為實測後的替代；MVP 先使用一個核心分析引擎，減少雙份語意。[Polars streaming](https://docs.pola.rs/user-guide/concepts/streaming/)

### 候選規格

以版本化 JSON AST 表達，不接受 Agent 自由產生 SQL／Python。必要欄位包含 candidate_id、schema_version、window_hours、predicate、trigger_policy、dependencies。

predicate 支援 count／revenue_sum／session_count／engaged_seconds、AND／OR、有限 SEQUENCE。起始預設最多兩個原子條件或兩步序列；重複短序列以可驗證的有限模板表達。窗口固定 [起點, 起點 + W)，每人第一次達標回傳一次。

同時間事件沒有可靠來源順序時不據 event_id 編造先後；嚴格 sequence 需更晚時間或可靠序號。Session 時長以可取得時間判定；只有 session_end 結算時，不回填成更早達標。

預設窗口 1／3／6／24／72 小時；168 小時診斷與較早窗口分開。具體頻次／收益門檻由探索集及預設網格生成，將搜尋規模限制在可測量的上限；建議初始 2,000 候選上限，需容量測試驗證。

### 統計與推薦基線

- 按安裝時間切分探索／驗證，初始 70%／30%，同日批次不拆散；不足批次時只報探索結果。
- 探索集做搜尋與排序，預先固定最多 10 個 finalist 再看驗證集；避免以驗證集反覆選門檻。
- 用戶為重抽樣單位的 bootstrap，顯示 95% 區間、固定種子；區間是描述性不確定性，不等於多重搜尋校正或因果檢驗。
- 歷史驗證通過需預先記錄判定規則，並檢查樣本、跨批次方向及區間；初始樣本門檻為工程預設，不代表已做 power analysis。
- 比較同一驗證集全體及未觸發用戶；全體基準包含觸發者，兩組不是獨立樣本。
- 觸發後收益只作診斷。跨候選採共同 landmark（例如 24／72 小時）分組，僅用 landmark 前條件，比較 landmark 至 D7 收益；仍是觀察性分析。
- 用 Jaccard 與雙向覆蓋呈現候選重疊，保留收益／覆蓋／觸發速度的取捨，不以單一不透明分數決策。
- 高價值離群用戶保留在主要 ARPU，另報分位數及敏感度，不默默截尾。
- 時間語意、漏數、收益延遲按 PRD 執行；未知資料不由模型補齊。

## 8. Agent SDK、探索與學習

### 選型

使用者指定 OpenRouter API，因此選用 Vercel AI SDK 的 ToolLoopAgent（套件 ai）與 @openrouter/ai-sdk-provider，透過 createOpenRouter 建立模型介面。Agent 由 Node.js 執行，不自行重寫通用 Agent loop。[OpenRouter 官方整合](https://openrouter.ai/docs/guides/community/vercel-ai-sdk)

ToolLoopAgent 提供多輪工具執行與停止條件；Python 分析仍保留，經內部 API／工作佇列串接。這是因 OpenRouter 需求調整先前選型，不是宣稱 Claude Agent SDK 絕對不能接 OpenRouter。[Vercel Building Agents](https://ai-sdk.dev/docs/agents/building-agents)

OPENROUTER_API_KEY 僅放伺服器環境，OPENROUTER_MODEL 指定模型 ID；不使用 Vercel AI Gateway 作第二層路由。鎖定 ai 與 provider 的相容版本，選模型時驗證 tool calling、結構化輸出及多輪工具結果相容性，不假設所有模型皆可互換。每次 run 保存模型與路由設定；fallback 必須明確配置並記錄。[OpenRouter 工具調用](https://openrouter.ai/docs/guides/features/tool-calling)

### 接入方式

- agent/src/runtime.ts：配置 ToolLoopAgent、工具、步數限制、逾時與取消；模型經 createOpenRouter 注入。這些是規劃模組，尚未建立。
- agent/src/tools.ts：使用 SDK tool 與 schema 包裝內部 FastAPI；計算端點回傳 job_id，再以有界輪詢等待結果並保持 Agent 租約。工具執行可中斷／恢復，重計算不占 HTTP 請求。
- 工具只回傳聚合結果和 artifact／evidence ID；由伺服器綁定 run、資料集與資料切分，不讓 Agent 自選未授權路徑或驗證集。
- 只註冊必要工具，不提供 Shell 或任意 SQL。TypeScript schema 與 Python Pydantic 契約做一致性測試；內部工具端點僅內網服務可達，不新增使用者登入。
- Node.js Agent 與 Python 計算各自維持租約；取消 run 時傳遞至子任務，兩端提交均檢查 fencing token。

### 工具與流程

| 工具 | 功能 |
|---|---|
| profile_dataset | 讀取品質、分布及可用方向 |
| get_baseline_report | 讀取首份報告、候選指標與可引用 evidence ID |
| load_app_findings | 讀取同 App、先前批次的適用經驗與反例 |
| rerun_analysis | 修改允許的窗口／門檻設定，建立不可變 followup run |
| analyze_segment | 對國家／平台／來源等可用欄位做分群診斷，保存分母與小樣本警告 |
| evaluate_candidates | 在探索集計算一批受 schema 約束的候選，成果寫入 followup run |
| compare_candidates | 比較覆蓋、收益、門檻及重疊 |
| finalize_candidates | 凍結候選與判定規則，關閉本 run 的探索權限 |
| get_validation_results | 讀取凍結後由確定性 pipeline 產生的驗證證據 |
| save_findings | 保存結構化假設、結果、限制與 evidence ID |

Agent 可根據第一輪結果改搜窗口、門檻或短組合；範圍須留在已記錄的 run 搜尋預算內。新一輪保存 round_id、假設摘要、工具參數與結果，不保存或要求模型私有思考鏈。跨原始配置範圍才另建 run。

停止條件包含候選／回合／時間／成本上限或無新增價值。凍結後不允許再依驗證集改候選；新 run 也不能把已反覆使用的 holdout 宣稱全新證據。

### 已看過基礎報告後的驗證邊界

本產品在對話前已顯示 baseline 驗證結果，所以 followup 預設 evidence_status=exploratory。Agent 不得將同份 holdout 的重跑標成獨立驗證通過，即使換對話或建立新 run。既有 baseline 的原始證據狀態保持不變。

get_validation_results 可讀歷史證據作解釋，但讀到的結果不授予新候選驗證資格。重新獨立驗證需使用尚未揭露且無用戶重疊的新批次／保留資料，先凍結候選與規則再評估；後端檢查 exposure 紀錄，而非僅依 prompt 自律。分群結果若使用已揭露資料也標為診斷。

### 學習與持久性

SDK 提供執行迴圈，不代表自動訓練模型或自動形成可靠經驗庫。MVP 做兩種學習：單次依探索證據調整搜尋，以及同 App 在新批次重驗舊候選。

PostgreSQL 增加 agent_sessions、agent_rounds、app_findings：保存 session ID、SDK／prompt 版本、round、工具呼叫冪等 key、證據、適用資料版本與失效／反例。findings 先是 observation，只有通過獨立新批次檢查才升級為可重用經驗；新批次仍需驗證。跨 App 自動遷移與權重訓練延後。

Session ID 是應用程式識別碼，ToolLoopAgent 不代替持久任務系統。保存完整可重放的模型 messages、tool call／result、step 狀態和配置至 PostgreSQL／S3；重啟時載入最後已提交步驟，對未完成工具先查詢既有 job。以 SDK 完成步驟回呼保存紀錄，但工具副作用必須在工具層先做冪等處理，不能等回呼才保存。恢復時驗證 tool call／result 配對，不宣稱中斷串流能逐 token 續傳。

工具重放以 run＋round＋輸入 hash／工具呼叫 ID 查找既有產物；恢復 session 不保證 exactly-once。對話快照不可用時，可從已提交的應用狀態啟動新 session，明示恢復方式，不偽稱原對話無縫續跑。

LLM 輸出採結構化 schema；各結論需帶 evidence_id。表格數字由程式插入，不由模型重寫。模型不可用時保留已完成分析，提供確定性基礎候選／模板報告，標示自適應探索未完成，不冒充完整 Agent 結果。

### SDK 接入驗收

- 小型合成資料下，Agent 至少完成兩輪依結果改變的工具探索，再凍結候選。
- baseline 搜尋不讀驗證結果；對話 followup 可引用已揭露歷史結果，但新候選不能因此獲得獨立驗證標籤。
- 關閉／重啟 runtime 後可恢復已提交成果；重放不重複建立候選或覆蓋報告。
- 新批次能讀取帶來源的舊 findings，並記錄支持或反例。
- 預算到達、取消、SDK／模型失敗都有明確狀態，保留數值產物。
- 安裝及鎖版本時按官方文件確認 runtime 依賴，做 image 啟動與自訂工具合約測試。

## 9. 部署、保存與存取

- 推薦單台雲端 Linux VM：HTTPS 反向代理／靜態前端、FastAPI、Python 計算 Worker、Node.js Agent Worker；外部 PostgreSQL 與 S3。Compose 可用於單機 production，需正式設定與重啟策略。[Docker Compose production](https://docs.docker.com/compose/how-tos/production/)
- 初始容量測試主機假設 4 vCPU、16 GB RAM、可用 SSD 暫存 100 GB；不是最低規格或容量承諾。Worker 初始 1 並行、DuckDB 2 threads／6 GB memory_limit，容器另设總量限制，測量後調整。
- 資料庫使用持久服務及備份；S3 保存原始檔與產物，可啟用版本保留。Worker SSD 僅暫存，失去後可由 durable artifact 重建。
- 上線驗收包含 DB 備份還原並重新打開報告、檔案 hash 校驗；保存不等於已驗證備份。
- 無登入代表所有能接觸站點的人共享同一工作區，沒有每位使用者的資料隔離。建議正式內部環境以網路限制開放給團隊，不加會員頁面。完全匿名公開站點會讓可達者看到共享資料；這是部署邊界，不新增產品權限系統。
- 不在前端保存雲端或模型密鑰；檔案透過短效 URL 存取。專案 UUID 是識別碼，不宣稱是權限。
- 上傳上限、每任務磁碟與時間額度可配置；超限顯示原因。初期不加入自動刪來源檔功能。
- 成本構成為 VM、PostgreSQL、儲存／傳輸與模型用量；雲商與區域未定，故不提供未查證月費。以上假設可作部署估價清單。

## 10. 實作分期與驗收

執行版已細分為 IMPLEMENTATION_PLAN.md 的 PH01–PH42；下表 P0–P5 僅保留作里程碑映射，不作新的 Goal 執行編號。每階段硬門檻與 Goal 文字以 Implementation Plan 為準，狀態見 PHASE_STATUS.md，人工／外部延期見 EXTERNAL_CHECKS.md。

按下列順序交付。每階段完成可示範的垂直流程後再展開下一階段，不先把 Agent 當作全部流程的入口。

| 階段 | 交付 | 驗收 |
|---|---|---|
| P0 核心合約 | schema、候選 AST、baseline／followup、可手算合成資料 | D7、首次觸發、邊界、零收益、序列與未來資訊測試 |
| P1 上傳與持久骨架 | Web／API、映射、PostgreSQL 遷移、S3、Python Worker | 上傳後關頁仍處理；重複提交只建一個 run；未完成檔不進分析 |
| P2 第一份可用報告 | 確定性 DuckDB pipeline、進度、歷史、HTML／JSON／CSV | 不配置 OpenRouter 也能從上傳走完報告；重啟後可讀；數值可手算核對 |
| P3 Agent 唯讀互動 | Node Worker、AI SDK／OpenRouter、對話保存、讀報告／比較工具 | Agent 可解釋現有結果並引用 artifact；刷新後對話保留；無工具計算不重跑 |
| P4 Agent 深入分析 | 重跑／分群／候選工具、子 run、快取、工具進度、經驗保存 | 自然語言產生分析分支；父報告不變；重放不重複計算；followup 證據標記正確 |
| P5 上線驗證 | 容器部署、容量與故障測試、備份還原 | 停 Agent／Python Worker、DB 暫斷、上傳中斷、磁碟不足均可恢復或清楚失敗 |

容量測試用 10 萬／100 萬／1,000 萬事件，涵蓋欄位寬度、用戶偏斜、重複與亂序；保存時間、峰值 RAM、暫存及候選數。設定資源限制後才提出可支援容量，不能憑筆數宣稱一定跑得動。

規劃目錄：web/、agent/（TypeScript runtime／tools）、server/（api、worker、analysis、reporting）、migrations/、tests/、deploy/。目前已實作；實際模組位置、命令與證據見README及docs/release_audit.md，不將本節早期API草案視為目前完整路由契約。

### HTTP 契約

| 端點（規劃） | 行為 |
|---|---|
| POST /api/projects | 建立 App 工作區 |
| POST /api/datasets | 建立不可變資料版本的草稿 |
| POST /api/datasets/{id}/uploads | 建立分段上傳，取得 upload ID |
| POST /api/uploads/{id}/complete | 校驗檔案完成，不信任瀏覽器自行宣稱成功 |
| PUT /api/datasets/{id}/mapping | 分析前保存映射；已封存版本不可直接修改 |
| POST /api/datasets/{id}/baseline | 封存輸入與配置、排 Python baseline，202 回 run_id |
| GET /api/runs/{id} | 讀狀態、階段、父子關係與 evidence_status |
| GET /api/runs/{id}/report | 取得已發布報告 manifest，未完成回清楚狀態 |
| POST /api/runs/{id}/conversations | 在 baseline ready 後建立對話；未 ready 回 409 |
| POST /api/conversations/{id}/messages | 保存使用者訊息並排 Agent turn，202 回 turn_id |
| GET /api/conversations/{id}/events?after={seq} | 按遞增序號讀訊息、工具與完成事件；供輪詢恢復 |
| POST /api/turns/{id}/cancel | 取消 turn 及所屬未完成計算，保留已完成結果 |
| POST /internal/tools/{name} | 僅 Agent Worker 使用；讀取或建立計算 job |

寫入請求帶 Idempotency-Key；同 key 不同 payload 回 409。schema 不符回 422，超過容量回 413，資源不存在回 404。例外錯誤回 error_code、可读 message、retryable、job_id，不回傳密鑰或原始 log。

工具呼叫 envelope：turn_id、parent_run_id、tool_call_id、arguments；後端從 turn 綁定 dataset／split，不能由模型跨資料集指定。計算型回傳 job_id、child_run_id、status；完成結果包含 artifact_id、evidence_status、metrics、warnings，按 payload 大小限制摘要。

### 代表性使用案例驗收

1. 「改看前 3 小時」：建立 followup，window_hours=3，沿用同 dataset；舊報告仍可打開。
2. 「只看美國用戶」：先確認 country 存在；沒有則說明不能分析。有則顯示分群分母及低樣本狀態，不編造提升。
3. 「這三個候選的人群重疊嗎」：已有 overlap 直接讀；缺少才排計算，回覆帶結果引用。
4. 「覆蓋率高一點」：Agent 用 schema 內參數探索，保存測過的門檻；不能把只降低門檻描述成已證實投放更好。
5. 重整頁面／Worker 重啟：能重新取得同一 turn 和子 run；沒有重複產生分支，未完成串流允許重新生成文字但不得丟已提交工具結果。
6. 讀過驗證結果後換對話重跑：後端仍標 exploratory，不因換 conversation_id 洗掉 exposure。

測試工具規劃：Python pytest 驗證計算與任務恢復；TypeScript 測試驗證工具 schema、回合恢復與 provider adapter；瀏覽器端到端測試覆蓋上傳到基礎報告及對話分支。模型測試先用可重現替身，另在已配置 OpenRouter 後做真實 tool calling 冒煙測試；不能用替身通過宣稱真實模型整合已驗證。

## 11. 本輪完成與剩餘選擇

已完成：無登入範圍、推薦技術棧、背景任務恢復合約、資料保存、Agent 邊界、實作順序及驗收設計。

模型入口已確定 OpenRouter。部署前再依既有帳戶選定雲商／區域、網路入口、具體模型、費用與資料保留期間。這些不阻擋先開始實作。套件版本在實作時依相容性測試鎖定，不臆測最新版。

本輪只更新文件，沒有安裝依賴、建立付費資源、執行分析或部署。

## 12. UI 實作規格：左側對話、右側結果

2026-09-10 語言更新：依 docs/LANGUAGE_PLAN.md 執行 L01–L05。既有雙欄、計算與不可變版本契約不變；主內容不要求理解技術 ID、統計縮寫或 JSON。前端須有共用用語／錯誤／格式化規則，候選名称由真規格生成，引用以已驗證來源提供友善操作。Agent 的白話指令與安全訊息呈現均須實作；HTML 報告同步，機器可讀合約保持。舊版文案測試可更新 label，但不可取消行為與數值斷言。

訊息呈現實作：使用 React 文字節點呈現有限 Markdown 子集（段落、標題、清單、引言、表格、強調、程式內容），不執行原始 HTML、圖片或模型提供的任意連結。程式內容預設收合，原始回覆可查且不寫回歷史。引用先綁定該對話在回覆序號之前的完成工具紀錄；版本優先取證據自身，舊格式只允許從來源工具輪已保存且 run 相符的上下文補足。找不到來源或版本衝突不提供跳轉；點擊仍經既有 API 進行來源與範圍校驗。這不表示模型的全部敘述已被自動事實查核。

2026-09-10真模型複驗發現4096輸出token截斷引用，改為有限8192上限，並要求簡潔回答（約300中文字、最多3項發現）。SDK的length終止不算完成，顯示回答未完成的安全訊息並保留已完成分析。中文括號／頓號只作引用分隔符，完整ID仍須與交付證據完全相符。此修正仍需真模型與全套回歸證據，不以提高上限保證不再截斷。

對於完全漏附引用、但本輪已取得合法工具證據的草稿，最多進行一次文字補正：仍在原本剩餘步數／截止時間內，只提供已取得的對話與證據，不註冊任何工具，因此不會為補引用新增分析。修正答案再次經完整allowlist校驗；仍缺引用、引用非法或到限就拒絕發布。已含捏造或跨範圍引用的回答不走補正，不自動換成合法ID。模型步驟與補正用量仍經既有持久journal紀錄；不把來源校驗宣稱為全文事實查核。

### 方向與參考

已確認：資料處理完成後進入雙欄工作區，左側為 Agent 對話，右側為輸出報告與圖表。互動布局參考 Claude Design，整體視覺參考 Linear 的產品介面。

Claude Design 官方描述左側 chat／右側 canvas；本案借用這個交互分工，右側是可追溯的分析結果，非任意生成的網頁或設計編輯器。[Claude Design 使用說明](https://support.claude.com/en/articles/14604416-get-started-with-claude-design)

Linear 官方設計文章強調層級、對齊、降低視覺噪音與中性色。以下 token 與尺寸是本產品提案，不是 Linear 官方 token 或逐像素複製。[Linear UI 設計說明](https://linear.app/now/how-we-redesigned-the-linear-ui)

### 桌面布局

~~~text
┌──────────────────────────────────────────────────────────────┐
│ App／資料版本                 分析版本 ▾  歷史  匯出          │
├─────────────────────┬────────────────────────────────────────┤
│ Agent 對話           │ 概覽  候選事件  圖表  資料品質         │
│ 當前分析／引用條件   │ 當前版本、樣本、窗口、證據狀態         │
│                     │                                        │
│ 問題與分析解釋       │ 摘要、主要圖表                         │
│ 工具進度／结果引用   │ 候選比較表、證據細節                   │
│                     │                                        │
│ ┌─────────────────┐ │                                        │
│ │ 問這份資料…     │ │                                        │
│ │ 引用內容  送出  │ │                                        │
│ └─────────────────┘ │                                        │
└─────────────────────┴────────────────────────────────────────┘
~~~

- 全視窗工作區；頂部工具列建議 48–52 px。專案／歷史用切換器或抽屜，不再加常駐第三欄擠壓圖表。
- 左欄預設約 360 px，可拖曳調整 320–480 px；右欄占剩餘寬度。數字是初始設計預設，以 1280／1440 px 視窗實測。
- 左右獨立捲動；左側輸入框、右側結果 tabs 各自固定。桌面頁面本體不產生多餘的第二套垂直捲軸。
- 寬度不足 1024 px 時改「結果／對話」切換，保留同一資料、對話及版本；不把兩欄硬縮到不可讀。
- 手機預設顯示結果，可切到對話；保留草稿。表格只在自己的容器水平捲動，頁面不横向溢出。

### 左側對話

- 顯示使用者問題、Agent 解釋、工具狀態與引用，不把完整 dashboard 重複塞進訊息。
- 工具卡用產品語言，例如「比較前 3 小時的候選事件」，附 queued／running／completed／failed 對應文字；技術 ID 收在詳情。
- 輸入框可換行，Enter 送出、Shift+Enter 換行；中文輸入法組字時不得誤送。送出時顯示引用的報告版本或候選。
- 建議問題先用「縮短到前 3 小時」「比較候選重疊」「提高覆蓋率」等已有工具能完成的內容。
- 工具產生新結果時提供「查看結果」，點擊後右欄切到明確 artifact／run；長任務執行中不清空右側舊結果。
- 使用者往上閱讀時不強制跳到底，改顯示新訊息提示。重試保持原問題與已完成結果。

### 右側結果

| 頁籤 | 主內容 |
|---|---|
| 概覽 | 資料範圍、D7 目標、候選摘要與關鍵取捨 |
| 候選事件 | 可排序比較表；點候選呈現條件、觸發時間、分母、收益與打點規格 |
| 圖表 | 覆蓋率／D7 ARPU 散點圖、門檻敏感度曲線、候選重疊熱圖；按實際產物顯示 |
| 資料品質 | 完整期、缺失、排除、能力限制，不能以空白圖隱藏問題 |

圖表使用固定的前端 renderer 與後端結構化數據；Agent 只能引用或请求分析，不能注入可執行 HTML／JS。圖表 schema 至少有 chart_type、artifact_id、run_id、series、axes／units、sample_size、evidence_status；renderer 驗證型別及 payload 大小。圖表套件在實作前依這三類圖表的小型驗證選定，不能只因風格參考就新增多套庫。

跨候選視圖使用一致顏色。收益顯示 USD、覆蓋顯示 %、時間顯示小時／天；tooltip 帶分母與樣本數。缺失值不是 0，沒有資料顯示原因。相對全體的收益差異不得標為投放提升。

### 對話與結果連動

- URL 保存 project／conversation／selected_run／artifact／tab，重新整理可恢復當前結果。
- 送出問題時把當前 selected_run_id 與顯式選中的 candidate_id 保存到 message context；對話歷史固定綁 baseline，但不能忽略使用者正在看的分支。
- UI 自行切 tab、排序或點圖不觸發昂貴計算；「針對這個候選提問」才把引用放入輸入框。
- 父版與分支版以版本選擇器切換；兩者的圖表、表格和匯出必須使用同一 selected_run_id，不能顯示混合版本。
- layout 寬度／tab 偏好可放瀏覽器儲存；訊息、分析、版本與報告以後端持久資料為準。

### 視覺基線（初始提案）

先做一套深色主題：冷中性灰、低彩度、細分隔線、緊湊工具列與充足的圖表留白。深色是本案初始提案，並非使用者已指定或 Linear 唯一主題。

| Token | 初始值／規則 |
|---|---|
| 背景／面板／浮層 | #101114／#17181C／#202127 |
| 主文／次文 | #ECEDEF／#A5A8B2 |
| 裝飾分隔線 | #2C2E35；可操作控制的邊界另做對比驗證 |
| 強調色 | #8B94E8，僅用於主要操作、選中與焦點，不作大面積漸層 |
| 字體 | Inter＋系統繁中字體 fallback；數字採等寬數字特性 |
| 字級 | 正文 14 px、次要資訊 12 px、區域標題 16–18 px |
| 圓角／間距 | 控制項 6 px、面板 8 px；4／8／12／16／24 px 間距尺度 |

資料以表格、分隔線與清楚標題組織；避免每個指標都變成大型卡片。狀態同時用文字與顏色表達；圖表可有多個類別色，不受單一品牌強調色限制。

### UI 驗收與分期

- P2 完成雙欄 shell 及真實 baseline 圖表，對話呈待接入狀態；P3 啟用對話與引用；P4 啟用分支／圖表連動。
- 1280×800、1440×900、768 px 與 390 px 寬度檢查；可拖曳分隔線需鍵盤操作与可辨識標籤。
- 鍵盤能到達輸入、tabs、版本選擇與匯出，焦點清楚；正文對比至少 4.5:1，重要控制／圖表標記對比另驗證。
- 圖表有對應數據表或文字摘要，不只靠 hover 或顏色理解。
- 長中文訊息、長事件名稱、多候選、小樣本、模型失敗、資料品質失敗均不破版。
- 工具計算時右側既有結果可閱讀；點結果引用會開對的版本；刷新後對話與右側選擇可恢復。
- 不加入登入頁、會員頭像或與本產品無關的設計畫布編輯功能。


### 2026-09-24：V4 正式介面與 demo 對齊（已確認）

保留分析計算與三群／六時間點／六方向。V4 工作區採淺色，概覽以四張數字卡呈現，主表為行為、七天平均收入、人數、達標時間及 Holdout 五欄；時間用六個按鈕，三群按鈕附母體人數。預設顯示第一個行為，點選其他行為直接切換並定位詳情。手機主表以行為卡片顯示全部欄位。

「匯出」為新版分析閱讀 HTML，涵蓋優先比較行為、三群玩家與六個時間點，使用與 Web 相同的呈現元件及既有聚合資料，不重算。每日新增人群詳情依三群展開；各時間點主表可在離線檔案中展開閱讀。完整 CSV／JSON／搜尋紀錄及歷史 HTML 保留，明確標為完整計算資料／原始封存報告；原始格式含保留的收入對照，不冒充新版閱讀畫面。沒有改寫歷史分析產物。

2026-09-24 顯示精度：V4 網頁與新版 HTML 閱讀版，金額、比例、時間固定兩位小數；人數保持整數。非零但不足四捨五入最小顯示單位者使用「< 0.01」避免當成零。門檻名稱超過兩位時以「約」標示，精確條件可展開查看。底層計算、原始 CSV／JSON、封存報告保留原精度。

2026-09-24 全產品配色決策：以 demo 淺色為統一基線，所有 Web 路由、所有報告版本的線上呈現、聊天、表單、抽屜與圖表共用全域色彩。移除 V4 才啟用淺色的條件。背景 #f6f7f9、面板 #fff、正文 #252b34、次要文字 #626b78、強調色 #5368a7；保持錯誤／成功／警告語意。僅呈現變更，不覆寫歷史分析與封存產物。
