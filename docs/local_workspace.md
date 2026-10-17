# 本地常駐合成資料工作區

這是 macOS／Unix 開發與本地產品驗收入口，使用真 PostgreSQL、磁碟 MinIO、正式 API／Workers。不是 `?demo=hand`，也不是自動驗收後丟棄的臨時工作區。PostgreSQL 只監聽 loopback、採 trust auth，因此**只供自己的本機合成資料使用**，不要放客戶資料、轉發連線或當成正式部署。正式部署沿用 [部署手冊](deployment.md) 的外部 PostgreSQL／S3。

## 首次準備

在專案根目錄執行 `uv sync --locked`、`npm ci`。安裝 PostgreSQL binaries（預設 Homebrew postgresql@15，其他位置設 `AC_POSTGRES_BIN`）；依 README 安裝 MinIO（或設 `AC_MINIO_BIN`）。啟動器不下載套件、不讀取其他專案憑證。

```sh
uv run python -m scripts.local_workspace init --name mvp
```

此命令只建立 `.runtime/local-workspace-mvp`；若已存在會失敗而不覆寫。私密 config.json 權限600、目錄700，包含固定服務port與隨機S3／內部token。不要分享整個目錄。所有資料保持原地，不提供自動刪除指令。

## 啟動與使用

終端1，保持開啟：

```sh
uv run python -m scripts.local_workspace serve --name mvp
```

看到 `Local synthetic services ready` 後，在終端2先執行 migration，再啟動API：

```sh
uv run python -m scripts.local_workspace exec --name mvp -- uv run alembic upgrade head
uv run python -m scripts.local_workspace exec --name mvp -- uv run uvicorn server.api.main:app --host 127.0.0.1 --port 8080
```

終端3：

```sh
uv run python -m scripts.local_workspace exec --name mvp -- uv run python -m server.worker
```

終端4：

```sh
uv run python -m scripts.local_workspace exec --name mvp -- npm run dev:agent
```

終端5：

```sh
npm run dev:web
```

服務使用固定8080／8081／5173，先確認沒有其他程序占用；不要終止不明服務。`exec` 只把本工作區PG／S3設定注入指定子程序，不輸出秘密、不自動讀.env。模型設定若由操作者明確放入程序環境會沿用；未設定OpenRouter時Agent不可送出，但Python報告與匯出仍可使用。

若既有開發服務占用port，可以在所有應用終端設定相同的`AC_LOCAL_API_PORT`及`AGENT_PORT`，並讓uvicorn的`--port`匹配前者。Vite終端的`API_PROXY_TARGET`設為該API的loopback URL，透過`npm run dev --workspace web -- --port 5174 --strictPort`選未占用的前端port（直接呼叫workspace，避免根目錄的巢狀npm script吃掉參數）。端口必須由操作者確認空閒；不自動切到不明服務。PH42測試用獨立port保留原5173示範頁。

先建立一批合成CSV（輸出目錄必須不存在）：

```sh
uv run python scripts/generate_fixture.py --output .data/local-first --users 1000 --events 10000 --seed 42
```

開啟 http://127.0.0.1:5173/upload，上傳 `.data/local-first/users.csv` 與 `events.csv`，完整截止時間讀同目錄的export.json；欄位映射依 [匯入說明](import_api.md)。合成資料不能當成商業推薦。`tests/fixtures/hand/` 是JSON手算測試來源，不是可直接選取的CSV。完整四題的明示測試模型驗收另見 [產品驗收](product_acceptance.md)，啟動器不把替身注入正式Agent。

## 停止與重開

先在API、Python Worker、Node Agent、Vite終端按Ctrl-C，最後在服務終端按Ctrl-C。服務監督程序只停止自己啟動的PG／MinIO，保留資料、log與設定。再次執行相同的 `serve --name mvp` 及上述應用命令，不再init；報告由相同DB／S3讀回，從 `/history` 重開。migration可以重跑upgrade head，不執行downgrade。

同名工作區已有監督程序時拒絕第二次啟動。若監督程序被SIGKILL或主機斷電留下postmaster.pid，啟動器會拒絕自動接管；先核對本工作區postgres.log與PG實際程序，不要直接刪PID檔或kill不明服務。這是保守恢復邊界，不是自動災難恢復；備份及隔離還原見 [備份手冊](backup_restore.md)。port被占用也會明確失敗，不改用其他資料目錄。

## 驗證範圍

`uv run pytest tests/test_local_workspace.py -q -s` 使用唯一命名工作區，真啟停兩次，校驗DB記錄及S3 bytes、第二監督程序拒絕、環境注入及秘密不輸出；資料保留在打印的目錄。

`uv run pytest tests/test_local_workspace_product.py -q -s` 已通過1項／30.86s：透過CLI exec啟動正式migration、uvicorn、Python Worker、Node及Vite，先確認正式無key入口，再以明示SDK測試模型跑真Chrome上傳／四題／三格式。全停後重開同PG/S3與API，六份父子報告hash相同，四turn／三branch保存。驗收使用轉換為CSV的手算fixture及獨立應用port，未呼叫真OpenRouter；不是宣稱生成器任意資料分布都已驗。PH42整體最終狀態仍以evidence為準。
