# AC Event Agent

[本地交付報告](docs/release_report.md)彙整入口、部署映像、實測容量、限制與外部待驗項；[需求追蹤](docs/traceability.md)連到各Phase實際Gate證據。

純 IAA 的 D7 事件分析工作區：上傳 → Python 基礎報告 → Agent 對話 → 工具深入分析 → 分支及 HTML／JSON／CSV 匯出。PH01–PH42 已通過本地驗收；權威狀態見 [PHASE_STATUS.md](PHASE_STATUS.md)。

Vercel AI SDK＋OpenRouter 正式接入已實作，但目前 Agent 功能驗收使用明示測試模型，尚未呼叫真 OpenRouter。正式 Docker images、真本地 PostgreSQL／S3、容器重建及隔離備份還原已驗證；未部署雲端、未驗真客戶資料或投放成效。這是無登入的單一共享工作區，不能直接匿名公開。

部署入口與私密設定見 [部署手冊](docs/deployment.md)；從空資料服務跑完整正式容器驗收：依下方安裝依賴、PostgreSQL／MinIO、Chrome 及 Docker Desktop，建置 `ac-event-python:ph41-local`、`ac-event-agent:ph41-local`、`ac-event-web:ph41-local` 後執行 `uv run python -m scripts.deployment_acceptance --tag ph41-local --run`。此命令自建隔離服務、驗收後停止，只保留資料及證據，不是常駐使用入口。常駐產品需依部署手冊配置持久 PG／S3，再以 Compose 啟動；缺模型 key 仍可產出報告。

前端 `/?demo=hand` 可檢視明示合成資料的雙欄工作區，數值來自 `tests/fixtures/hand/expected.json`。這是可調欄寬、獨立捲動與窄螢幕切換的介面驗收範例，不是客戶分析；無 demo 或 run 識別時顯示尚無資料。Agent 送出及 fixture 匯出仍停用，不提供假成功。

`/history` 與 `/runs/{id}` 已接真持久歷史／進度；報告完整發布後可進 `/workspace?run={id}` 或下載HTML/JSON/CSV。工作區結果頁籤已接入，Agent 設定且連線後可送出，缺 key 或 Worker 離線時明示不可用。技術性失敗可在修復環境後手動重試，資料問題不重寫封存dataset。契約見 [run API](docs/run_api.md)。

`/upload` 是真實上傳與映射介面，需要已設定 DB/S3 的 API。可分段上傳、刷新後選檔續傳、保存映射並排 baseline；未知服務狀態會明示錯誤。排隊後由獨立 Python Worker 執行，不是只靠瀏覽器跑分析。

## 開發環境

需要停止後能重開相同資料的本機合成工作區，先讀 [本地常駐啟動](docs/local_workspace.md)。新啟動器保存固定PG／S3工作區；CLI啟動、真瀏覽器上傳／四題／匯出及重開同報告已通過本地補驗，模型明示替身。正式部署仍用外部持久服務。

Python 3.12（uv 管理）、Node.js 22.12+或相容新版、npm。已用Node26.5驗證。首次安裝：

~~~sh
uv sync --locked
npm ci
~~~

分別開終端執行：

~~~sh
uv run uvicorn server.api.main:app --host 127.0.0.1 --port 8080
uv run python -m server.worker
npm run dev:web
npm run dev:agent
~~~

前端 http://127.0.0.1:5173；API health http://127.0.0.1:8080/api/health；Agent liveness http://127.0.0.1:8081/health。API health 的 analysis_pipeline_available=true 表示程式具備 baseline；analysis_ready=false/readiness_verified=false 表示此 liveness 端點未探測 DB/S3/Worker 就緒狀態，不代表 Worker 已啟動。

Node Agent 已可經內部 HTTP 領取持久 turn、讀取報告、續租和提交回覆；左側 UI 已接持久對話、工具卡、取消／重試與右側引用。設定 `.env.example` 中的伺服器變數並載入程序環境，`npm run dev:agent` 會先編譯再啟動。OPENROUTER key/model 缺少時不領取問題；`GET /api/agent/status` 可區分模型未設定與 Worker 不可用，不代表真模型驗證通過。內部端點與取消／重試見 [對話 API](docs/conversation_api.md)。

Agent 工具與公開 SDK 步驟已持久保存，重啟沿用原 tool call ID、固定配置與剩餘預算；需先升級至 migration 0017 或以上。恢復邊界、錯誤處理與驗證命令見 [Agent 中斷恢復](docs/agent_recovery.md)。這不是逐 token 續傳，也不代表真 OpenRouter 或雲端驗證已通過。

## 驗證

~~~sh
npm run check
~~~

包括build、兩個TS專案型別、Python測試及22個合約例子。鎖檔記錄實際解析版本。Python 整合測試需要真 PostgreSQL binaries（initdb、pg_ctl、postgres）；缺少時會失敗而不是跳過。macOS 預設偵測 Homebrew postgresql@15，其他安裝位置設定 AC_POSTGRES_BIN。

瀏覽器整合使用鎖定的 Playwright，預設 `chrome` channel（本機 Google Chrome）；可設 `PLAYWRIGHT_CHANNEL` 選已安裝 channel。`uv run pytest tests/test_upload_browser.py -q -s` 會建立隔離 PostgreSQL/MinIO/API/Vite，執行真 multipart／續傳／錯誤／映射／排隊並終止測試服務，截圖及 checks 留於 `.runtime/upload-ui-*/visual/`。不使用記憶體假後端，不碰既有開發server。未提供瀏覽器時會失敗而非跳過。

.env.example列未填的伺服器設定；未提供OpenRouter不阻止基礎環境啟動。開發啟動命令不自動讀.env，設定透過程序環境注入；正式Compose使用兩份伺服器專用env_file。不要把任何key放VITE_變數。啟動API／Worker前必須配置同一PG／S3並完成migration；上述四行應分別在四個終端執行，不是僅啟動UI就具備後端。

## 依據與限制

已接入的上傳／續傳／封存與排隊操作見 [匯入 API 說明](docs/import_api.md)。API 排 baseline 後由獨立 Worker 執行，不能把上傳完成或 202 當作分析完成。

PRD.md、TECH_PLAN.md、IMPLEMENTATION_PLAN.md為需求與執行基線；evidence記錄真實驗收。數值由Python產生，Agent只取得聚合工具證據；同份資料揭露驗證結果後的重跑保持探索狀態。真模型、託管服務、雲端與客戶資料的補驗見 [EXTERNAL_CHECKS.md](EXTERNAL_CHECKS.md)，不可把替身或合成資料當成真實商業效果。

## Python Worker（持久任務）

在 DATABASE_URL 已設定且 `uv run alembic upgrade head` 完成的環境執行 `uv run python -m server.worker`，或用 `--once` 只嘗試領取一個任務。主程序短交易領取並續租，計算在獨立 spawn 子程序；SIGTERM/SIGINT 會停止子程序並將尚有租約的任務重新排隊，SIGKILL 後由到期租約恢復。取消／失去租約不發布舊成果；子程序偵測父程序消失會退出。

正式 baseline handler 已接入。API 與 Worker 都需同一 DATABASE_URL、S3_BUCKET/S3_ENDPOINT_URL 及 AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY；先 `uv run alembic upgrade head`（目前0017），再 `uv run python -m server.worker`。上傳流程見 docs/import_api.md。沒有模型 key 仍可完成 baseline；Worker 缺 DB 設定會明確失敗。

`uv run pytest tests/test_pipeline.py tests/test_checkpoints.py tests/test_worker.py tests/test_jobs.py -q` 使用真 PostgreSQL/S3 驗證上傳202後關閉client、Worker子程序分析、kill後租約接手、持久checkpoint還原及缺收益診斷。stage cache 綁資料/config/程式與contract hashes；恢復不依賴舊worker目錄。最終狀態 succeeded 表示計算完成，progress.analysis_status=diagnostic_only 表示資料不足，不是投放推薦通過。小樣本可能 analyzed 但沒有歷史驗證候選，必須讀 reasons。

checkpoint/local暫存保留供稽核，沒有客戶來源自動刪除政策；不建議在未知磁碟容量下連續跑大型資料。10萬／100萬一般與寬欄位合成批次已完整通過；1000萬在1536MiB RSS配額下受控MEMORY_LIMIT，不能宣稱通過。參見 [容量與資源限制](docs/capacity.md)。舊測試資料的一次性授權清理不代表未來可自動刪資料。

## 合成資料生成

完整管線benchmark與伺服器資源設定見 [容量測試](docs/capacity.md)。CLI預設只做不產生資料的預檢；實跑需`--run`，每批保留獨立結果及真值校驗。

完整產品示範（空工作區 → 真上傳／Python 報告 → 四題 Agent 工具分析 → 下載）見 [產品流程驗收](docs/product_acceptance.md)。`/?demo=hand` 僅是介面範例，不能作完整產品流程證據。

正規化核心位於 server/analysis/ingest.py；`uv run pytest tests/test_ingest.py -q` 驗證 CSV／原生型別 Parquet 等價、去重／隔離、來源保存及 15 萬事件分組寫入。呼叫 canonicalize 時提供已驗證的本地 source（path/role/format/sha256）、canonical→來源欄位 mapping 與不存在的輸出目錄；完成後讀 manifest.json，不從零散 Parquet 推定成功。這仍不是完整分析管線。

`uv run python scripts/generate_fixture.py --output .data/synthetic-01 --users 1000 --events 10000 --seed 42`

輸出目錄必須不存在；生成器不覆蓋檔案。手算小資料與預期值見 tests/fixtures/hand/，不代表真客戶效果。

## 本地 PostgreSQL 與 migration

維護窗口備份與全新隔離還原見 [備份與故障處理](docs/backup_restore.md)。備份包含原始資料與對話，`.backups/` 已排除版本控制；不能當成客戶匯出報告公開。

`uv run python scripts/local_postgres.py` 啟動新的隔離 cluster，只監聽 127.0.0.1、隨機 port。終端輸出專用 DATABASE_URL，另開終端以該 URL 設定環境後執行：

~~~sh
uv run alembic upgrade head
~~~

DATABASE_URL 需使用 `postgresql+psycopg://`。不對不明既有資料庫執行 migration。上述隔離服務 Ctrl-C 停止；資料與 postgres.log 保留於輸出的 .runtime/pg-test-* 目錄，測試也不自動刪除。這個 trust-auth helper 只用於本機合成資料測試，不能作正式部署設定。

`uv run pytest tests/test_database.py -q -s` 自動建立專用 cluster、从空庫 migration、重啟並驗證持久性，結束後只停止該 cluster。測試連線不使用外部 DATABASE_URL，不觸及其他服務。Alembic destructive downgrade 明確禁止；需還原時應使用隔離備份流程（PH39）。

## 本地 S3 測試服務

macOS ARM64 可執行 `uv run python scripts/install_local_minio.py`，下載固定版本並驗證官方 SHA256 後安裝至 .runtime/bin/minio。其他平台自行準備相容 MinIO binary 並設定 AC_MINIO_BIN；此 helper 僅用於合成資料本地測試，不作 production 元件選型。上游 MinIO 採 AGPLv3；正式部署仍使用 TECH_PLAN 的外部 S3。

安裝後執行 `uv run pytest tests/test_storage.py -q -s`：啟動真實磁碟儲存服務，測試 put/get/head、重啟、不可覆寫、multipart checksum、缺檔及斷線。服務只綁 loopback、使用臨時測試憑證、不讀既有 AWS 帳戶，結束時停止精確子程序；資料及日誌保留在 .runtime/s3-test-*。測試程式存在不表示驗收已通過，狀態以 PHASE_STATUS.md 為準。

已授權外部 bucket 的基本補驗命令：確認 .env.example 對應 S3_BUCKET、endpoint、region 與憑證均正確設定至程序環境，再執行 `uv run python -m scripts.storage_smoke --write-synthetic`。它新增且保留一個唯一 synthetic object，不建立 bucket、不刪除資料；只驗證基本寫讀，不代表 CORS、分段上傳或雲端重啟已驗。
