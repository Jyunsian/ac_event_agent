# V4 demo／正式程式 review 修復

日期：2026-09-17。狀態：passed（功能修復、相關回歸、畫面及兩種分布容量驗證通過）。原 V4-01–06、V3 CG06 歷史不改寫。

## 已修正

1. 收入首次達標依當時可用資料判斷；未來缺失收入、負向修正或未知可用時間，不抹掉之前可靠達標。未知時間從事件發生後保守列未知，不假造到達時間。缺失之前尚未達標者不推算精確首次時間。
2. V4 使用自己的逐人收入時間線還原判斷值，避免 V3 的整批收入能力限制抹掉可靠玩家／時間的證據。保留原品質警告與 D7 缺值，不修改 V3。V4 feature manifest 標記 `per_user_available_timeline`；policy 增加計算修訂識別，pipeline hash 隨程式更新，舊產物保留。
3. 與第一天比較只納入第一天可判定玩家；完全不可比較時，新增數為 null 而非零。產物保存適用狀態及第一天未知人數，Web／CSV／HTML／Agent 同步。24h 顯示「第一天：比較基準」。
4. 正式頁面加入六時間點柱狀圖、每日新增總收入與占比；指定時間條件不畫成持續累積。第一天未知人群獨立標示。圖表、資料品質、候選頁籤各有對應內容，手機選單不溢出。主表母體直接取目標摘要，無優先候選仍能顯示人數。前端 V4 契約接受「第一天比較不適用」的 null，其他人數仍嚴格檢查；探索集也納入結構檢查。
5. Agent 提供全量、探索、holdout 三群；以指定 `window_hours` 取得單一時間點（預設 24h），明示可讀的六時間點，保留原 128 KiB 限制。聊天的時間與人群保存於訊息 context，傳到 Agent Worker，並在介面顯示；未使用逐用戶資料。非優先清單內的 V4 已評估候選也能被聊天選取。
6. 離線 HTML 的收入對照與滾動／累積比較補齊三群。正式檢驗另外記錄實際比較的兩組人數，避免用未限制共同可判定母體的人數冒充檢驗人數。
7. Demo 的同門檻累積／滾動在第一個完整 24h 使用相同人數與收入，說明差異在觸發時間。後續仍展示等待與人群取捨；假數字、預設問答維持明確示意。

主要程式：`server/analysis/v4_features.py`、`v4_metrics.py`、`v4_validation.py`、`v4_report.py`、`v4_contract.py`、`server/read_tools.py`、`server/conversations.py`、`server/api/schemas.py`、`agent/src/tools.ts`、`runtime.ts`、`worker.ts`、`web/src/report-v4.tsx`、`report-panel.tsx`、`workspace.tsx`、`chat-panel.tsx`、`web/public/mock-v4.html`。

## 已完成的驗證

- 初始 28 項計算測試通過；新增實際匯入資料的缺收入／缺到達時間測試後，`tests/test_v4_review_fixes.py tests/test_v4_features.py tests/test_v4_search_validation.py`：22 passed，12.48s。字典與陣列路徑、可追溯首次時間、實際品質警告均有覆蓋。
- 相關整合回歸：`tests/test_v4*.py tests/test_conversations.py tests/test_read_tools.py tests/test_report_api.py tests/test_report_delivery.py tests/test_candidate*.py`：59 passed，1 failed（311.19s）；失敗為先前 UI 改名後未更新的舊瀏覽器定位。更新定位並補上目前報告／人群上下文後，單獨重跑 `test_selected_report_version_is_pinned_in_message_context`：1 passed，36.45s。真 PostgreSQL、S3、Worker、上傳、讀取、匯出、恢復、舊報告 bytes 保留及 Agent 數字驗證已涵蓋；不是所有歷史測試重新驗收。
- 前端模型 25 passed；Agent 25 passed；build 與 typecheck 通過。保留既有 568.73 kB 圖表 chunk 警告與兩項 Starlette 棄用警告。
- `scripts/v4_browser_qa.cjs` 使用真正計算的聚合產物，以 API 路由 fixture 檢查 1440px／390px：圖表、六時間點、三群、聊天選取上下文、資料品質／圖表／候選頁籤、每日收入欄位、無頁面溢出、無 JS 錯誤。這不是付費模型測試。
- Demo 兩個寬度及三群第一天人數／收入相等、比較基準文案通過；原臨時預覽已更新。

證據集中於 `.runtime/v4-repair/`：`feature-final.log`、`integration-fixed.log`、`version-context.log`、`web-tests-final.log`、`agent-tests-final.log`、`typecheck-final.log`、`build-final.log`、`browser-final/`、`browser-capacity-complete/`、`mock-checks.json`。容量畫面 fixture 使用真正的候選 API 分頁投影，搜尋紀錄也按正式 API 分頁，而非把完整紀錄塞入單頁。

保留途中失敗紀錄：補記檢驗人数時誤把 Python list 當 array 使用 `.sum()`，已改成 `sum()`；修正後重跑整合。舊版瀏覽器測試先後發現過時的標題、按鈕及輸入框定位；手機圖表選單曾溢出，已修復後重驗。不把中途失敗算成 passed。

## 一般分布容量與格式核對

`python scripts/benchmark_time_v4.py --directory .runtime/v4-repair/capacity-normal --run`：passed。100,000 事件、20,000 規則、2,000 正式比較、171 個完整驗證規則、10 個優先項。計算 219.39s；CPU 205.52s；RSS 峰值 1,121,271,808 bytes；工作目錄 376,532,205 bytes。原 CPU 600s／wall 900s／RSS 1,536 MiB／工作目錄 4 GiB／DuckDB 256 MB、2 threads 不變。

3,078 列 CSV 的每列 point JSON 與明細逐一一致；候選頁使用正式 `read_candidate_page` 投影，六時間點每頁均小於 1 MiB，最大 601,693 bytes。十條最大候選 Agent 投影，加上額外 16 KiB 回應／引用預留，上界 69,009 bytes，低於 128 KiB。這是回應大小檢查，真工具 API 的數字驗證另由整合測試提供。主報告 990,246 bytes，低於 16 MiB。證據 `capacity-normal/result.json`、`capacity-normal/artifact-checks.json`。

集中案例第一次被磁碟 preflight 擋住，並未進入計算，不算通過。已完整封存本輪建立且已關閉的 24 個合成 PostgreSQL 測試資料庫，每個檔案以 SHA256 比對封存內容後才移除解壓副本，共釋放 875,280,607 bytes；封存與逐檔核對清單在 `closed-test-databases/manifest.json`，可以完整還原。未動客戶來源、舊報告或其他服務。保留原磁碟 reserve，集中案例以新目錄重跑。

## 集中案例的失敗、恢復與補驗

- 首次集中測試在報告儲存階段遇到 `STORAGE_SERVICE_ERROR`；重啟後小檔案可寫，大檔案重現 HTTP 507／`XMinioStorageFull`，確認為 MinIO 最低磁碟剩餘空間限制。證據 `storage-large-probe.json`。沒有調低 Worker 或 MinIO 限制。
- 另將本輪已關閉的合成 S3 及恢復暫存完整封存並逐檔 SHA256 核對，釋放 905,221,979 bytes；清單 `closed-test-stores/manifest.json`。容量暫存也封存於 `work-archive-manifest.json`、`concentrated-scratch-archive/manifest.json`。來源 CSV、報告、紀錄與所有封存可保留追溯；解壓暫存可還原。
- 原集中 run 從檢查點恢復後成功交付，恢復耗時 12.47s，7 個計算階段 restored，report 與 cache audit computed。175 規則、10 優先項、20,000 搜尋，但完整比較束分配只用了 **1,996** 單位。因此 `capacity-concentrated-final/result.json` 的 run_status 是 succeeded，容量 assertion 仍保留 failed，沒有把它寫成 2,000 通過。獨立真值的事件、用戶、成熟用戶、零事件用戶、D7 收入均核對一致，另記 `delivery-checks.json`；三群輸出逐列核對另見 `artifact-checks.json`。
- 曾嘗試 2,400 位合成玩家，核心事件超出固定 100,000 筆，生成器拒絕，未進入計算；沒有增加事件預算換取通過。補驗改用原 2,200 位玩家與 seed 43；正式資源限制、重抽樣、六時間點及完整比較束政策均維持。

## 最終補驗結果

- 集中分布 seed 43：`python scripts/benchmark_time_v4.py --directory .runtime/v4-repair/capacity-concentrated-seed43 --seed 43 --concentrated --run`：passed。仍為 2,200 玩家、100,000 事件、20,000 基本規則、2,000 正式比較；174 個完整驗證規則、10 優先項。計算 166.11s，CPU 161.80s，RSS 峰值 998,064,128 bytes，工作目錄 372,446,301 bytes。冷啟動完成全部階段，沒有用恢復時間冒充完整計算時間。一般及集中案例使用相同 pipeline identity `8acf3552f393ed8d6347433e354e5dbec97df1be8b85861d62de75920e9d0300`。
- 集中產物的 3,132 列 CSV 與明細 JSON 逐一相同；主報告 1,026,713 bytes，候選頁最大 579,868 bytes，十候選 Agent 投影加 16 KiB 預留上界 69,581 bytes，均符合既有限制。`capacity-concentrated-seed43/artifact-checks.json`。
- 兩種完整容量產物皆通過 1440px／390px 的實際前端檢查，包含真正候選頁 API 投影、三群、六時間點、圖表、頁籤、聊天選取上下文及無溢出／JS 錯誤。證據 `browser-capacity-complete/`、`browser-concentrated/`。
- 最新時間邊界回歸：`pytest -q tests/test_v4_review_fixes.py tests/test_v4_metrics.py tests/test_v4_rolling.py`：16 passed，3.10s；另有前述 features／search／validation 22 passed。
- 最後服務回歸 `pytest -q tests/test_v4_pipeline.py`：5 passed，34.85s，覆蓋 multipart 上傳、具名方案、真 PG／S3／Worker、所有匯出、候選讀取、檢查點恢復、Agent 48h 探索群及 UI context、版本揭露與 V3 原 bytes 保留。`pipeline-final-retry.log`。前一次最後回歸有 3 項被本機 MinIO 磁碟門檻擋住；封存最新已關閉的 13 個合成測試服務後釋放 572,024,531 bytes，再完整重跑此檔全部通過，沒有跳過失敗項。封存核對：`closed-test-stores-final/manifest.json`。
- 最新 build／typecheck、前端模型 25 項、Agent 25 項通過；原 22+7 契約例通過。保留既有 chunk 及 Starlette 警告，無新增套件。

本輪所列修復與驗證已完成；過程中的失敗與 1,996 單位案例均保留，不冒充 passed。沒有重跑整個歷史平台的每一項測試。

既有已發布報告不自動重算或覆寫。要在真實資料中取得修正數字需另建新 run；資料若已揭露驗證結果，新 run 仍遵循原探索狀態。沒有雲端部署、付費模型呼叫或投放驗證。
