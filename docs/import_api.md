# 資料匯入 API（PH07）

提供真實上傳、排隊與 Python baseline 分析。收到 202 只表示持久任務已排隊，不代表分析或客戶報告已完成。baseline 已包含通過 PH18 本地驗收的離線 HTML/JSON/CSV renderer。

### 瀏覽器上傳（PH20）

前端 `/upload` 可建立專案／dataset、上傳一份 users 與多份 events、保存欄位映射／匯出說明並排 baseline。URL 的 dataset 識別用於刷新恢復；來源檔不能由瀏覽器跨刷新自動保留，續傳時請重新選取原檔。

`GET /api/datasets/{dataset_id}/uploads` 只返回上傳 ID、role、檔名／格式、預期大小與 SHA256、part 大小／數量與狀態。不返回 multipart ID、物件 key 或簽名網址。列表與映射均讀取 PostgreSQL，localStorage 不作真實上傳狀態來源。

瀏覽器使用 4 MiB 分塊，在 Web Worker 中增量計算 SHA256，再依 resume 返回的 missing_parts 逐段直傳。顯示進度是 hash／已確認分段 bytes，不代表 server 最終校驗已完成。「檢查完成狀態」對不確定的完成回應重新呼叫 complete，尚缺段時可見 MISSING_PARTS。暫停保留已傳入 S3 的分段。不同內容的同名／同大小檔案不能續用原 upload。

本地 Vite 預設轉發 API 至 127.0.0.1:8080，可在啟動時設 `API_PROXY_TARGET` 指定隔離測試 API。這不是憑證設定；DB/S3 secrets 僅在後端。S3 的 presigned PUT 直接由瀏覽器發出，指定部署的 CORS 仍需 X02 補驗。

### 已發布報告下載接口

`GET /api/runs/{run_id}/reports/{version}/{format}`，目前 baseline 版本為 `1`，format 為 `json`、`html`、`csv`。只有 Worker 完成全部格式並在有效租約內提交 report_versions 後可讀。已知 run 尚無該版本回 409，未知 run 回 404，非法格式／非正版本回 422。

回應是檔案附件，ETag 為實際 SHA256；服務從物件儲存讀取時驗證 hash 和大小，失敗不返回內容。HTML 可離線開啟，不依賴 OpenRouter 或外部腳本。JSON 是正式版本的報告模型，CSV 是其中候選比較欄位的匯出，不包含所有診斷明細；未知數值在 CSV 留空，文字公式前綴加單引號防注入。報告發布與 artifacts、run 完成狀態在同一 fenced 交易內提交。

## 啟動

1. 按 README 啟動 PostgreSQL，設定 DATABASE_URL；執行 `uv run alembic upgrade head`。
2. 準備已授權的 S3 相容 bucket，設定 S3_BUCKET、S3_ENDPOINT_URL、AWS_DEFAULT_REGION 與伺服器憑證；不把憑證放到瀏覽器。
3. `uv run uvicorn server.api.main:app --host 127.0.0.1 --port 8080`。schema 可在 `/docs` 查看。
4. 無登入、會員或租戶隔離，正式入口只對團隊網路開放。未配置 DB 的業務請求回 503；health 只代表 liveness。
5. 另開程序，以相同 DB/S3 環境執行 `uv run python -m server.worker`。API 不承載重分析；關閉呼叫端不取消持久任務。

本地可重現測試：`uv run pytest tests/test_upload_api.py -q`，自動建立專用 PostgreSQL 與 MinIO，不使用外部帳戶。測試採合成 bytes，驗證上傳協定而非 CSV 解析正確性。

## 請求順序

| 方法／路徑 | 輸入與結果 |
|---|---|
| POST /api/projects | app_id、name、選填 customer_label → project id |
| POST /api/datasets | project_id → 草稿 dataset id |
| POST /api/datasets/{id}/uploads | role=users/events、filename、format=csv/parquet、size_bytes、整檔 sha256 → upload_id |
| POST /api/uploads/{id}/resume | 重選檔案的 size_bytes、sha256 → 已收 parts、missing_parts、part_size，或 completed manifest |
| POST /api/uploads/{id}/parts | size_bytes、sha256、part_number → 短效 S3 PUT URL |
| PUT 短效 S3 URL | 該 part 的原始 bytes；長度必須精確，瀏覽器自行產生 Content-Length |
| POST /api/uploads/{id}/complete | size_bytes、sha256 → 已驗證 manifest，或缺段／大小／hash 錯誤 |
| PUT /api/datasets/{id}/mapping | mapping、export_metadata → 保存欄位與匯出設定 |
| POST /api/datasets/{id}/baseline | contracts/defaults.json 形狀的 config → 202 run_id/status=queued |
| GET /api/runs/{id} | 持久狀態、進度、錯誤、配置與版本關聯 |
| GET /api/datasets/{id} | 資料版本與封存狀態 |

建立／保存／完成／baseline 請求必須帶 `Idempotency-Key`（1–200 字元）。同 scope/key/輸入回原結果；同 key 不同輸入回 409。resume／parts 是可重複的狀態查詢與短效簽名，不快取過期 URL。

每個 dataset 恰一份 users 檔、一份以上 events 檔。尚未完成的 upload 不能封存。MVP 預設單檔最多 5 GiB，可用 MAX_UPLOAD_BYTES 調低；part_size 預設 8 MiB。這是保護上限，不是效能已驗證容量。

## 映射與完整期

mapping 的 key 是 canonical 欄位，value 是來源欄位。例如 `{"users":{"app_id":"app","user_id":"uid","installed_at":"first_open","platform":"os"},"events":{"app_id":"app","user_id":"uid","event_id":"eid","event_name":"event","event_time":"timestamp"}}`。

export_metadata 必須符合 contracts/schema.json 的 export 定義；合成示例見 tests/fixtures/hand/export.json。未知資訊不得抄 synthetic 範例冒充客戶完整期。這個 API 先驗結構，跨筆品質由 PH08–PH10 檢查。

## 續傳、錯誤與持久性

- 重新選檔先計算整檔 SHA256 與大小，符合已登記 fingerprint 才能續傳；只補 missing_parts，不重傳已存在段。
- 完成時從 S3 查實際段與大小，不採信前端 ETag 清單。最後串流核對整檔 SHA256；multipart ETag 不作檔案 hash。
- S3 初始化成功但回應／DB 提交遺失：以持久 object key 找回原 multipart。完成成功但 DB 未提交：resume/complete 查原物件並重新校驗後恢復。
- 校驗不通過的物件不加入 verified manifest、不把 dataset 標 ready，也不自動刪來源。修正檔案建立新 dataset/upload；本階段不提供刪原始檔 API。
- baseline 在同一 DB 交易封存 dataset、建立 run 與 job。封存後不能修改映射或追加檔案；新版本建立另一個 dataset，舊結果保留。
- 完成確認目前為同步串流 I/O、記憶體有界。大型檔可因 HTTP 逾時重試同一 upload/key；不把連線斷開當作成功。後續容量測試需量測此成本。
- 常見狀態：404 未知資源；409 缺段／不符／已封存／冪等衝突；413 超限；422 schema 錯誤；503 儲存或 DB 暫不可用。錯誤訊息不含 SQL、原始 log 或憑證。

真 AWS 的 CORS、權限及網路仍待 X02。服務需要限定 bucket/prefix 的 multipart initiate/list/part/complete、head/get，以及 ListBucketMultipartUploads 權限供未知回應恢復。短效 URL 視同暫時存取能力，不保存到客戶報告或公開日誌。
# 品質產物讀取（PH09）

`GET /api/runs/{run_id}/quality` 與 `GET /api/runs/{run_id}/profile` 分別讀已提交的 `quality`、`dataset_profile` artifact。回傳 `{run_id, artifact_id, kind, sha256, content}`，content 為 checksum 驗證後的原始 JSON，API 不重新計算 capability flags。

存在 run 但尚未發布產物回 409 `ARTIFACT_NOT_READY`；不存在 run 回 404；同 kind 多份未消歧產物回 409 `ARTIFACT_AMBIGUOUS`；checksum 或內容損毀不回假結果。僅 S3 上傳不等於發布，正式 Worker 在有效租約的 metadata 交易內發布。

`normal_recommendations_allowed` 僅表示來源品質允許後續分析，不代表已達樣本／驗證門檻。missing 以保留後 canonical rows 計數；excluded_input_rows 是輸入減保留、包含重複，原因可能重疊。profile 各分布最多 100 組，`distribution_coverage` 揭露總組數與省略用戶數。

Baseline 已接通：`GET /api/runs/{id}` 的 status=succeeded 表示計算完成；progress.analysis_status 分 analyzed／diagnostic_only，reasons 解釋資料不足或無歷史驗證候選。ready 不能從某個 stage checkpoint 推定。checkpoint 已保存但尚未最終提交時，品質 API 仍回 ARTIFACT_NOT_READY。Worker SIGKILL 後由自然到期租約接手，stage_modes 記錄 computed/restored；程式／契約／配置變動不誤用 checkpoint。
